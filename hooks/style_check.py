#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""PostToolUse hook (Write|Edit): validates code changes conform to the project's
detected style fingerprint. Enforces at three levels:

  HARD rules (>90% codebase consistency): injects correction context
  SOFT rules (70-90%): injects warning context
  ASK rules (no established pattern): prompts user consent

Reads the fingerprint from docs/code-style-fingerprint.md. If the fingerprint
doesn't exist, silently skips (scaffold not fully initialized).

This hook does NOT block — it injects additionalContext that instructs the agent
to self-correct. The agent sees the style violation and fixes it before the user
has to notice.
"""

import json
import os
import re
import sys
from pathlib import Path

# Import shared utilities — handle case where _hook_utils isn't adjacent
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from writing_flow.hookio import get_project_root, read_hook_stdin
except ImportError:
    def get_project_root(payload=None):
        env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if env_dir:
            return Path(env_dir)
        return Path.cwd()

    def read_hook_stdin():
        try:
            return json.load(sys.stdin)
        except Exception:
            return {}

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    from writing_flow.failopen import note_swallowed
except ImportError:
    def note_swallowed(hook, exc=None):
        return None

# Import shared prose rules
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from writing_flow.prose_rules import (
        scan as scan_prose,
        extract_comments_and_strings,
        STE_STRICT,
        ste_mode,
    )
except ImportError:
    def scan_prose(text, kinds=None, **_kwargs):
        return []

    def extract_comments_and_strings(code, filepath):
        return ""

    STE_STRICT = ()

    def ste_mode():
        return "default"

try:
    from writing_flow.personal_style import check_personal_style, is_personal_style_doc
except ImportError:
    def check_personal_style(content: str) -> list:
        return []

    def is_personal_style_doc(filepath: str) -> bool:
        return False


def is_code_file(filepath: str) -> bool:
    """Check if the file is a code file worth style-checking."""
    code_extensions = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.cs', '.java', '.go',
        '.rs', '.rb', '.php', '.kt', '.scala', '.swift', '.c', '.cpp',
        '.h', '.hpp', '.vue', '.svelte',
    }
    return Path(filepath).suffix.lower() in code_extensions


def is_prose_file(filepath: str) -> bool:
    """Check if the file is a prose file worth checking for AI-isms."""
    prose_extensions = {'.md', '.txt', '.rst', '.mdx', '.adoc', '.org'}
    return Path(filepath).suffix.lower() in prose_extensions


def is_data_file(filepath: str) -> bool:
    """Check if file is JSON/YAML/TOML data file."""
    exts = {'.json', '.yaml', '.yml', '.toml'}
    return Path(filepath).suffix.lower() in exts


# extract_comments_and_strings now lives in hooks/lib/prose_rules.py (single
# implementation shared with guard_style.py's PreToolUse comment-prose check).


def is_ai_writing_doc(filepath: str) -> bool:
    """Check if this file documents AI writing patterns (self-reference escape hatch).

    Files that list bad words as examples should not be flagged for containing them.
    """
    path_lower = filepath.lower()
    escape_patterns = ["avoid-ai-writing", "writing-style", "anti-ai"]
    if path_lower.endswith("claude.md"):
        return True
    return any(p in path_lower for p in escape_patterns)


def strip_non_prose_markdown(content: str) -> str:
    """Remove structural Markdown content before prose style analysis.

    Strips:
    - Fenced code blocks (``` ... ```) — ASCII diagrams and code use em dashes structurally.
    - ATX heading lines (# through ######) — headings use 'Title — Subtitle' as a
      conventional separator, not a prose style choice.

    Inline code (single backticks) is left in place; it rarely contains em dashes
    and the added regex complexity isn't worth it.
    Unclosed fences at end-of-file are handled by re.DOTALL + non-greedy match.
    """
    import re
    # Strip fenced code blocks first
    result = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    # Strip ATX heading lines (must be start of line)
    result = re.sub(r"^#{1,6} .*$", "", result, flags=re.MULTILINE)
    return result


def check_em_dash_density(content: str) -> list[tuple[str, str]]:
    """Check em dash density against content word count.

    Called separately from check_prose_ai_isms so that Edit operations
    can pass the full file content (not just the diff).

    Fenced code blocks are stripped before counting because em dashes inside
    ASCII diagrams (e.g. 'hook_name \u2014 description') are structural, not prose style.
    Word count uses the stripped content so the ratio stays meaningful.
    """
    findings = []
    prose_findings = scan_prose(content, kinds=("em_dash",))

    for f in prose_findings:
        if f["kind"] == "em_dash":
            findings.append(("SOFT", f["label"]))

    return findings


def check_ste_structural(content: str) -> list[tuple[str, str]]:
    """Scan for ASD-STE100-derived structural violations (SOFT, non-blocking).

    Covers what guard_style.py's blocking PreToolUse pass may skip (self-ref
    exempt files, HARNESS_KIT_STE=warn mode) and gives a second, non-blocking
    chance to catch structural slop that guard_style.py's HARNESS_KIT_STE=off
    turned off entirely for the block path. Respects the same env var.
    """
    if ste_mode() == "off":
        return []
    findings = []
    prose_findings = scan_prose(content, kinds=STE_STRICT)
    for f in prose_findings:
        findings.append(("SOFT", f["label"]))
    return findings


def check_prose_ai_isms(content: str, skip_tier1: bool = False) -> list[tuple[str, str]]:
    """Scan prose content for AI writing anti-patterns.

    Args:
        content: Text to scan (new_string for Edit, full content for Write).
        skip_tier1: If True, skip Tier 1 word checks (self-reference escape hatch).

    Returns list of (severity, message) tuples.
    Em dash checking is handled separately by check_em_dash_density().
    """
    findings = []
    kinds = ("ai_ism",) if skip_tier1 else ("ai_ism", "tier1")
    prose_findings = scan_prose(content, kinds=kinds)

    ai_isms = [f for f in prose_findings if f["kind"] == "ai_ism"]
    tier1s = [f for f in prose_findings if f["kind"] == "tier1"]

    if ai_isms:
        phrases = [f["match"] for f in ai_isms[:5]]
        findings.append((
            "HARD",
            f"AI writing anti-patterns detected: {', '.join(repr(p) for p in phrases)}. "
            "Remove chatbot filler, sycophancy, and hedge phrases."
        ))

    if tier1s:
        words = [f["match"] for f in tier1s[:5]]
        findings.append((
            "SOFT",
            f"AI Tier-1 words found: {', '.join(repr(w) for w in words)}. "
            "Replace: leverage→use, utilize→use, robust→solid, comprehensive→thorough, "
            "delve→look at, pivotal→key, seamless→smooth."
        ))

    return findings


def parse_enforcement_rules(fingerprint_content: str) -> dict:
    """Extract HARD, SOFT, and ASK rules from the fingerprint document."""
    rules = {"hard": [], "soft": [], "ask": []}

    current_section = None
    for line in fingerprint_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("### HARD"):
            current_section = "hard"
            continue
        elif stripped.startswith("### SOFT"):
            current_section = "soft"
            continue
        elif stripped.startswith("### ASK"):
            current_section = "ask"
            continue
        elif stripped.startswith("### ") or stripped.startswith("## "):
            current_section = None
            continue

        if current_section and stripped.startswith("- "):
            rule_text = stripped[2:].strip()
            if rule_text:
                rules[current_section].append(rule_text)

    return rules


def parse_comment_patterns(fingerprint_content: str) -> dict:
    """Extract comment style patterns from the fingerprint."""
    patterns = {
        "density": None,
        "commented_areas": [],
        "uncommented_areas": [],
    }

    for line in fingerprint_content.splitlines():
        if line.startswith("**Comment density:**"):
            match = re.search(r'\*\*Comment density:\*\*\s*(\w+)', line)
            if match:
                patterns["density"] = match.group(1)
        elif line.startswith("**Chosen areas:**"):
            areas = line.split(":", 2)[-1].strip()
            patterns["commented_areas"] = [a.strip() for a in areas.split(",") if a.strip()]
        elif line.startswith("**Absent areas:**"):
            areas = line.split(":", 2)[-1].strip()
            patterns["uncommented_areas"] = [a.strip() for a in areas.split(",") if a.strip()]

    return patterns


def parse_health_areas(fingerprint_content: str) -> list:
    """Extract low-health areas that warrant stronger enforcement."""
    low_health = []
    in_low_health = False
    for line in fingerprint_content.splitlines():
        if "Low-Health Areas" in line:
            in_low_health = True
            continue
        if in_low_health:
            if line.startswith("##") or line.startswith("---"):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                low_health.append(stripped[2:])
    return low_health


def check_style_conformance(tool_input: dict, rules: dict,
                            comment_patterns: dict, low_health: list) -> list:
    """Check if the tool's file change conforms to detected style rules.

    Returns a list of (severity, message) tuples.
    """
    findings = []
    filepath = tool_input.get("file_path", "")

    if not filepath or not is_code_file(filepath):
        return findings

    # Check the content being written/edited
    content = tool_input.get("content", "")
    new_string = tool_input.get("new_string", "")
    code_to_check = content or new_string
    if not code_to_check:
        return findings

    # Check each HARD rule
    for rule in rules.get("hard", []):
        rule_lower = rule.lower()

        # Naming convention checks
        if "naming" in rule_lower and "camelcase" in rule_lower:
            # Check for PascalCase where camelCase expected (or vice versa)
            if re.search(r'(let|var|const)\s+[A-Z][a-z]', code_to_check):
                findings.append(("HARD", f"Naming: {rule}"))

        # Comment style checks
        if "comment" in rule_lower and "section" in rule_lower:
            if "// ---" in rule_lower and "//" in code_to_check:
                # Check if comments follow the section comment pattern
                plain_comments = re.findall(r'^\s*//(?!\s*---)[^/].*$', code_to_check, re.MULTILINE)
                section_comments = re.findall(r'^\s*//\s*---.*---', code_to_check, re.MULTILINE)
                if plain_comments and not section_comments and len(plain_comments) > 2:
                    findings.append(("HARD", f"Comment style: {rule}"))

        # Error handling checks
        if "error" in rule_lower and "throw" in rule_lower:
            if "catch" in code_to_check and "return null" in code_to_check.lower():
                findings.append(("HARD", "Error handling: project throws exceptions, doesn't return null"))

    # Check SOFT rules
    for rule in rules.get("soft", []):
        rule_lower = rule.lower()

        if "import order" in rule_lower and ("import " in code_to_check or "using " in code_to_check):
            findings.append(("SOFT", f"Import organization: {rule}"))

    # Check if file is in a low-health zone — insist on improvement
    for area in low_health:
        if any(indicator in filepath for indicator in area.split()[:3] if len(indicator) > 3):
            findings.append(("INFO",
                             f"This file is in a low-health zone: {area}. "
                             "Consider improving style consistency while making changes."))
            break

    # ASK rules — only flag when the edit touches a relevant area
    # Map keywords in ASK rules to code patterns that indicate relevance
    ask_relevance = {
        "error": lambda c: any(kw in c for kw in ["catch", "throw", "except", "try", "error", "Error"]),
        "test": lambda c: any(kw in c for kw in ["test", "Test", "assert", "describe(", "it("]),
        "log": lambda c: any(kw in c for kw in ["log", "Log", "logger", "Logger", "console."]),
        "naming": lambda c: bool(re.search(r'(class |def |function |const |let |var |interface )', c)),
        "comment": lambda c: bool(re.search(r'(//|#|/\*|\*/|"""|\'\'\')', c)),
        "import": lambda c: any(kw in c for kw in ["import ", "using ", "require(", "from "]),
        "async": lambda c: any(kw in c for kw in ["async", "await", "Task", "Promise"]),
        "null": lambda c: any(kw in c for kw in ["null", "None", "nil", "undefined", "Optional"]),
    }
    for rule in rules.get("ask", []):
        rule_lower = rule.lower()
        # Only fire if the edit actually touches code related to this ASK rule
        relevant = False
        for keyword, checker in ask_relevance.items():
            if keyword in rule_lower and checker(code_to_check):
                relevant = True
                break
        if relevant:
            findings.append(("ASK", f"No established pattern: {rule}"))

    return findings


def _naming_findings(tool_input: dict) -> list:
    """Cryptic-name findings for the written content, or [] on any failure.

    Best-effort by design. This is an advisory line in a hook that already has
    plenty to say, so an import failure or an unparseable file is silence rather
    than an error.
    """
    path = tool_input.get("file_path", "")
    if not path or not is_code_file(path):
        return []
    content = tool_input.get("content") or tool_input.get("new_string") or ""
    if not content.strip():
        return []
    try:
        from writing_flow.naming_rules import scan_naming
    except ImportError:
        return []
    try:
        return scan_naming(content, path)
    except Exception:
        return []


def main() -> None:
    data = read_hook_stdin()
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Only check Write and Edit tools
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    filepath = tool_input.get("file_path", "")
    if not filepath:
        sys.exit(0)

    findings = []

    # Prose check — runs on markdown/text files, no fingerprint needed
    if is_prose_file(filepath):
        content = tool_input.get("content", "") or tool_input.get("new_string", "")
        if content:
            skip_tier1 = is_ai_writing_doc(filepath)
            findings.extend(check_prose_ai_isms(content, skip_tier1=skip_tier1))
            if not is_personal_style_doc(filepath):
                findings.extend(check_personal_style(content))

            # Em dash: check full file for Edit (not just the diff), full content for Write.
            # Skip CHANGELOG files — their bullet format 'hook — description' and version
            # headings '## vX.Y.Z — date' use em dashes as structural separators throughout.
            if "CHANGELOG" not in Path(filepath).name and "retrospective" not in Path(filepath).name:
                if tool_name == "Edit":
                    try:
                        full_content = Path(filepath).read_text(encoding="utf-8")
                        findings.extend(check_em_dash_density(full_content))
                    except Exception:
                        findings.extend(check_em_dash_density(content))
                else:
                    findings.extend(check_em_dash_density(content))

            findings.extend(check_ste_structural(content))

    # Code / data files: scan comment + string regions for prose rules (AI-isms,
    # tier-1, structural). Identifiers and syntax are excluded by
    # extract_comments_and_strings, so `leverage_count` is never flagged.
    # Runs with NO fingerprint dependency.
    if is_code_file(filepath) or is_data_file(filepath):
        content = tool_input.get("content", "") or tool_input.get("new_string", "")
        if not content:
            try:
                content = Path(filepath).read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
        if content:
            extracted = extract_comments_and_strings(content, filepath)
            if extracted.strip():
                findings.extend(check_prose_ai_isms(extracted, skip_tier1=False))
                findings.extend(check_ste_structural(extracted))

    # Code style conformance — requires the fingerprint
    if is_code_file(filepath):
        root = get_project_root(data)
        fingerprint_path = root / "docs" / "code-style-fingerprint.md"

        if fingerprint_path.exists():
            try:
                fingerprint = fingerprint_path.read_text(encoding="utf-8")
                rules = parse_enforcement_rules(fingerprint)
                comment_patterns = parse_comment_patterns(fingerprint)
                low_health = parse_health_areas(fingerprint)
                findings.extend(check_style_conformance(tool_input, rules, comment_patterns, low_health))
            except Exception as exc:
                note_swallowed("style_check", exc)

    if not findings:
        sys.exit(0)

    # Build context injection
    parts = []

    hard_findings = [f for f in findings if f[0] == "HARD"]
    soft_findings = [f for f in findings if f[0] == "SOFT"]
    ask_findings = [f for f in findings if f[0] == "ASK"]
    info_findings = [f for f in findings if f[0] == "INFO"]

    if hard_findings:
        violations = "\n".join(f"  - {f[1]}" for f in hard_findings)
        prose_hard = any("AI writing" in f[1] or "chatbot" in f[1] for f in hard_findings)
        if prose_hard:
            guidance = "Edit the file to remove these patterns before proceeding."
        else:
            guidance = ("Review docs/code-style-fingerprint.md and correct your change to match "
                        "the established patterns. Do not proceed without fixing these.")
        parts.append(
            f"STYLE VIOLATION:\n{violations}\n{guidance}"
        )

    if soft_findings:
        warnings = "\n".join(f"  - {f[1]}" for f in soft_findings)
        prose_soft = any("Em dash" in f[1] or "Tier-1" in f[1] for f in soft_findings)
        if prose_soft:
            guidance = "Fix these before the response is finalised."
        else:
            guidance = "Consider aligning with the established pattern. Check docs/code-style-fingerprint.md."
        parts.append(
            f"Style warning:\n{warnings}\n{guidance}"
        )

    if ask_findings:
        questions = "\n".join(f"  - {f[1]}" for f in ask_findings)
        parts.append(
            f"Style decision needed (no established pattern detected):\n"
            f"{questions}\n"
            f"Ask the user which approach to use before establishing a new pattern."
        )

    if info_findings:
        notes = "\n".join(f"  - {f[1]}" for f in info_findings)
        parts.append(f"Style health note:\n{notes}")

    # Identifier naming, merged in from a local `code-style-naming` hook. It
    # belongs here rather than in a hook of its own: this file already owns
    # per-write style conformance and already has the content in hand.
    #
    # The rule is relative, so it needs no fingerprint entry. A minimum-length
    # rule is wrong in both directions, since `i` in a short loop is fine and
    # `d` as a module-level cache is not, at the same length. It compares each
    # name against the file's own median, and stays silent in a file that is
    # terse throughout, because there is no local convention being broken.
    naming = _naming_findings(tool_input)
    if naming:
        listed = "\n".join(f"  - line {f['line']}: {f['label']}" for f in naming[:5])
        parts.append(
            "Naming (this file's other names are descriptive):\n" + listed
        )

    if parts:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(parts)
            }
        }
        print(json.dumps(output))


if __name__ == "__main__":
    main()
