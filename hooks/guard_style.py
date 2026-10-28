#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""
Hard filter on PreToolUse:Write,Edit. Blocks prose files that contain
AI-writing violations: banned chatbot phrases, Tier 1 words, and (for
prose files) the ASD-STE100-derived structural checks in STE_STRICT.

Exit 2 with stderr rejects the tool call; the model sees the error and
retries. Prose scope: .md .txt .rst .mdx .adoc .org files, plus code
comments/docstrings in supported code files (via extract_comments_and_strings,
so identifiers and syntax are never flagged). Self-reference exception skips
files that document the writing rules themselves.

HARNESS_KIT_STE controls the structural checks: "off" skips them entirely,
"warn" downgrades a violation to a printed notice with exit 0, unset/"strict"
blocks as normal. ai_ism and tier1 checks are unaffected by this var.

A verbatim record (a transcript, a pasted log, quoted third-party speech)
is not this session's own prose, so a rewrite to comply would falsify it.
Include [verbatim-ok] anywhere in the file, or set HARNESS_KIT_ALLOW_VERBATIM=1.
"""

import json
import os
import re
import sys
from pathlib import Path

# Import prose rules from shared library
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config as wf_config
from writing_flow.prose_rules import (
    scan as scan_prose,
    STE_STRICT,
    ste_mode,
    get_rule_kinds,
    extract_comments_and_strings,
    scan_comment_structure,
    grammar_for,
    grammar_is_known,
    PROSE_ROUTE,
    COMMENT_STRUCTURE_KINDS,
    RESIDUE_BLOCKING_LABELS,
    _TIER1_WORDS,
)
try:
    from writing_flow import config as local_kit
except Exception:
    local_kit = None

# Stdlib only. A from-import so sync_hooks.py ships it with this hook.
from writing_flow.edit_scope import blank_unchanged, changed_lines  # noqa: E402
from writing_flow import guard_format  # noqa: E402
from writing_flow.claude_temp import is_machine_path  # noqa: E402

# Plain mode is optional. A missing module leaves the existing caps in
# charge rather than breaking the write.
try:
    from writing_flow import plain_rules
    from writing_flow import plain_state
    from writing_flow import rewrite_log
except Exception:
    plain_rules = None
    plain_state = None
    rewrite_log = None

PROSE_EXTS = (".md", ".txt", ".rst", ".mdx", ".adoc", ".org")

# CODE_EXTS was a 17-entry list, so a comment in any other language was never
# scanned at all. Routing goes through prose_rules.grammar_for now, which
# resolves a comment grammar for 139 extensions across ten families, sniffs a
# shebang for a bare-name script, and returns None only for a binary or
# comment-less data format. The tuple stays as the fast path and as the record
# of which extensions were covered before.
CODE_EXTS = (
    ".py", ".sh", ".bash", ".rb",
    ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".cpp", ".h", ".hpp",
    ".rs", ".vue", ".svelte",
)

# Files that document the writing rules themselves — they name the banned
# phrases and rules as examples, and must not be blocked for containing them.
SELF_REF_PATTERNS = [
    "/CLAUDE.md",
    "/rules/",
    "/avoid-ai-writing/",
    "/technical-english/",
    "/output-styles/",
    "/hooks/guard_style",
    "/hooks/style_check",
    "/hooks/lib/prose_rules",
    "response_audit",
    "message_display_audit",
    # issue #45's own wider residue table put "decision narration" into
    # guard_style.py's blocking set. A changelog entry describing that same
    # feature -- quoting "user decision" or "lets" as the pattern it detects
    # -- is the tool documenting itself, not narrating a chat. Measured
    # directly against this repo's own CHANGELOG.md and docs/changelog/
    # while validating this fix. guard_doc_residue.py already exempts
    # CHANGELOG (case-sensitive); this hook never did, on any casing.
    "CHANGELOG",
    "changelog",
]


STRUCTURAL_FIX = {
    "semicolon": "split it into two sentences",
    "synonym rotation": "pick one name and use it everywhere",
    "passive voice": "name who does the action",
    "nominalization": "use the verb",
    "phrasal verb": "use the one-word verb",
    "sentence": "split the sentence",
}


def _structural_item(label: str) -> tuple[str, str]:
    text = re.sub(r"\s*\((STE|ASD)[^)]*\)", "", label).strip()
    fix = next((v for k, v in STRUCTURAL_FIX.items() if text.lower().startswith(k)), "")
    return text, fix


def style_block(path, ai_isms, tier1s, structural, residue_blocking, residue_advisory,
                comment_structure, plain_findings, plain_exempt) -> str:
    """The guard_style block in the shared harness-kit format (guard_format)."""
    items = [(f'chatbot phrase "{f["match"]}"', "cut it") for f in ai_isms]
    for f in tier1s[:6]:
        better = _TIER1_WORDS.get(f["match"].lower())
        items.append((f'word "{f["match"]}"', f'write "{better}" instead' if better else "use a plain word"))
    items += [_structural_item(f["label"]) for f in structural[:6]]
    items += [(f'line {f["line"]}: {f["label"]} "{f["match"]}"', "state the fact, not the conversation")
              for f in residue_blocking[:6]]
    advice = [f'line {f["line"]}: {f["label"]} "{f["match"]}"' for f in residue_advisory[:4]]
    advice += [f'comment structure, line {f["line"]}: {f["label"]}' for f in comment_structure[:4]]
    for f in plain_findings[:6]:
        text, fix = guard_format.split_fix(f["label"])
        hard = f.get("severity", "HARD") == "HARD" and not plain_exempt
        if hard:
            items.append((text, fix.lower()[:1] + fix[1:] if fix else ""))
        else:
            advice.append(text + (f" (advisory, {plain_exempt})" if plain_exempt else ""))
    return guard_format.render("style", guard_format.short_path(path), items, advice,
                               notes=["then retry the Write or Edit"] if items else None)


def retitle(lines: list[str], stage: str, why: str) -> list[str]:
    """The same block with its headline marked as a notice, not a block."""
    if not lines:
        return lines
    head = re.sub(r"^harness-kit\[style:blocked\]: ", f"writing-flow[style:{stage}]: ", lines[0])
    # Nothing is blocked, so "3 to fix" would overstate it.
    head = re.sub(r", (\d+) to fix$", r", \1 findings", head)
    return [f"{head} ({why})"] + lines[1:]


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    if data.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)

    tin = data.get("tool_input") or {}
    path = tin.get("file_path", "")
    if is_machine_path(path):
        sys.exit(0)
    suffix = Path(path).suffix.lower()
    is_prose = suffix in PROSE_EXTS
    is_code = suffix in CODE_EXTS
    if not is_prose and not is_code:
        # Not on either legacy list. grammar_for decides: a comment grammar
        # means scan it as code, PROSE_ROUTE means scan the whole body, None
        # means a binary or comment-less format and we drop out.
        # For bare-name files (no extension), grammar_for needs the first line
        # to find a shebang. A Write carries it in content. An Edit does not, so
        # it comes from disk. On 2026-09-23 an Edit to scripts/git-hooks/pre-push
        # was blocked as prose over the "; then" of shell code.
        shebang_code = ""
        if not suffix:
            if data["tool_name"] == "Write":
                shebang_code = tin.get("content") or ""
            else:
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        shebang_code = fh.read(2048)
                except OSError:
                    pass
        family = grammar_for(path, shebang_code)
        if family is None:
            sys.exit(0)
        if family == PROSE_ROUTE:
            is_prose = True
        else:
            is_code = True

    # issue #41: an extension nobody has curated still gets scanned as C, but
    # grammar_is_known() says so is a guess rather than a match. A guess
    # should not block -- see the low_confidence branch near the exit below.
    low_confidence = is_code and not grammar_is_known(path)

    for pat in SELF_REF_PATTERNS:
        if pat in path:
            sys.exit(0)

    # A NOTICE file marks a vendored tree, copied in from an upstream project
    # with its own LICENSE.txt. Its prose is not this repo's to rewrite for
    # local style rules -- a NOTICE-marked tree is a signed contract to keep
    # the content as shipped upstream. skill-creator (vendored, its own
    # LICENSE.txt and NOTICE) has dozens of long-sentence findings that are
    # exactly this: unrelated to this repo's own writing.
    current = Path(path).resolve().parent
    for _ in range(12):
        if (current / "NOTICE").exists():
            sys.exit(0)
        parent = current.parent
        if parent == current:
            break
        current = parent

    content = tin.get("content") if data["tool_name"] == "Write" else tin.get("new_string", "")
    if not content:
        sys.exit(0)

    # A transcript, interview record, support thread, or pasted log is a
    # record of what someone else said, not this session's own prose. Every
    # finding this guard raises assumes authored text, so a verbatim quote
    # naming a flagged word or a first-person aside falsifies the record
    # if rewritten to comply. No existing escape hatch covers this.
    # HARNESS_KIT_STE only gates the structural checks, not ai_ism/tier1.
    # SELF_REF_PATTERNS matches on path, and a business artifact has no
    # reason to live at one of those paths. Same convention as
    # guard_doc_residue.py's [residue-ok] / HARNESS_KIT_ALLOW_RESIDUE.
    if wf_config.env("ALLOW_VERBATIM") == "1" or "[verbatim-ok]" in content:
        sys.exit(0)

    # An Edit carries unchanged context in new_string. Only the lines it
    # changes are this write's prose. See lib/edit_scope.py. Prose files only:
    # blanking a docstring's opening line would hide the lines after it from
    # comment extraction in a code file.
    if data["tool_name"] == "Edit" and is_prose:
        content = blank_unchanged(content, changed_lines(tin.get("old_string", ""), content))
        if not content.strip():
            sys.exit(0)

    scan_text = content if is_prose else extract_comments_and_strings(content, path)
    if is_code and not scan_text.strip():
        sys.exit(0)

    # get_rule_kinds() consolidates the rule selection logic with guard_comment_debt,
    # ensuring both scan identical rule sets when retro_fix_enabled() is on.
    # "residue" was absent here, so the conversation-residue family reached
    # prose only: guard_doc_residue covers .md/.rst/.txt, and this hook is the
    # only path to a code comment. A comment could carry a dated decision
    # stamp, reader address or first-person opinion and nothing looked.
    # Write-time enforcement always applies STE_STRICT (ste_mode still gates
    # it). HARNESS_KIT_RETRO_FIX shapes guard_comment_debt's Read-time report
    # and never turns off what a write is checked against.
    kinds = get_rule_kinds(retro_fix_enabled=True)

    findings = scan_prose(scan_text, kinds=kinds, filepath=path)
    if is_code:
        findings = findings + scan_comment_structure(content, path)

    # Plain mode adds a paragraph and chain cap for prose files. ASD-STE100
    # caps the sentence and nothing else, so a file could pass every
    # sentence check and still arrive as one unbroken block. This runs
    # before the early exit, since a plain finding may be the only one.
    # A file's chain cap runs per heading section, since the headings already
    # split it for the reader. A template-shaped file, such as an agent
    # definition, reports its plain findings without blocking: its shape comes
    # from the template, not from a choice the author can undo.
    plain_exempt = ""
    if (plain_rules is not None and plain_state is not None
            and plain_state.is_active() and is_prose):
        # An Edit carries only new_string, so read the marker from disk.
        whole = content
        if data["tool_name"] == "Edit":
            try:
                whole = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        plain_exempt = plain_rules.template_reason(path, whole)
        override = plain_rules.turn_override(data.get("transcript_path", ""))
        if override:
            plain_exempt = f"override this turn: {override[:60]}"
            if rewrite_log is not None:
                rewrite_log.record("guard_style", "plain-override", path, override, "")
        plain_hits = plain_rules.paragraph_cap(content)
        plain_hits += plain_rules.chain_cap(content, per_section=True)
        for severity, detail in plain_hits:
            findings.append({"kind": "plain", "label": detail,
                             "match": "", "line": 0, "severity": severity})
            if rewrite_log is not None:
                rewrite_log.record("guard_style", "plain", path, detail, "")

    if not findings:
        sys.exit(0)

    plain_findings = [f for f in findings if f["kind"] == "plain"]
    ai_isms = [f for f in findings if f["kind"] == "ai_ism"]
    tier1s = [f for f in findings if f["kind"] == "tier1"]
    structural = [f for f in findings if f["kind"] in STE_STRICT]
    residue = [f for f in findings if f["kind"] == "residue"]
    # issue #45: the residue table grew from 10 entries to 28. Six carry a
    # proven survivor list from running in production as blocking findings.
    # The other twenty-two are new categories, shipped advisory-only until
    # each one's own survivor list is clean on a larger corpus.
    residue_blocking = [f for f in residue if f["label"] in RESIDUE_BLOCKING_LABELS]
    residue_advisory = [f for f in residue if f["label"] not in RESIDUE_BLOCKING_LABELS]
    comment_structure = [f for f in findings if f["kind"] in COMMENT_STRUCTURE_KINDS]

    # verbosity=terse is opt-in only: auto and full both mean "show the
    # actual violations," never rolled up. The model needs the specific
    # phrase/word/sentence to fix -- a count alone ("3 tier1 words") gives it
    # nothing to act on and risks a blind retry. terse exists for a user who
    # explicitly wants the shorter form anyway, not as an automatic default.
    verbosity = local_kit.hook_verbosity("guard_style") if local_kit else "auto"
    if verbosity == "terse":
        parts = []
        if ai_isms:
            parts.append(f"{len(ai_isms)} banned phrase(s)")
        if tier1s:
            parts.append(f"{len(tier1s)} tier1 word(s)")
        if structural:
            parts.append(f"{len(structural)} structural")
        if residue:
            parts.append(f"{len(residue)} residue")
        if comment_structure:
            parts.append(f"{len(comment_structure)} comment structure")
        if plain_findings:
            parts.append(f"{len(plain_findings)} plain")
        lines = [
            "STYLE VIOLATION blocked by guard_style.py",
            ", ".join(parts) + ". Set verbosity=full for the actual violations.",
            "Rewrite without these then retry the Write/Edit.",
        ]
    else:
        lines = style_block(path, ai_isms, tier1s, structural, residue_blocking, residue_advisory,
                            comment_structure, plain_findings, plain_exempt).splitlines()

    # ai_ism/tier1/blocking-residue findings always block. A HARD plain
    # finding blocks by itself too: the user turned that mode on deliberately,
    # so an unbroken block of text is a real violation, not a shape heuristic.
    #
    # Everything else here is advisory on its own: a structural violation
    # under HARNESS_KIT_STE=warn, a comment-structure shape heuristic (a
    # 101-character comment line and a three-line block are both legitimate
    # often enough that blocking a Write over one would train the model to
    # strip comments rather than tighten them), or a new/unproven residue
    # category (issue #45). One unified check covers all three rather than a
    # branch per combination, so a soft finding that happens to arrive alone
    # cannot fall through to the hard block at the bottom unhandled.
    # A plain finding blocks only when it is HARD, meaning 1.5x its cap, and
    # the file is not template-shaped. A SOFT overage is a few words over,
    # and its rewrite cost far more than the words it saved.
    plain_blocking = [] if plain_exempt else [
        f for f in plain_findings if f.get("severity", "HARD") == "HARD"]
    hard_findings = bool(ai_isms or tier1s or residue_blocking or plain_blocking)
    blocking_structural = bool(structural) and ste_mode() != "warn"
    if not hard_findings and not blocking_structural:
        print("\n".join(retitle(lines, "notice", "advisory only, nothing blocked")), file=sys.stderr)
        sys.exit(0)

    # issue #41: an unmapped extension only ever reaches "c" as a guess, so a
    # finding here may be a real violation or a misparsed comment span. Report
    # it, never block on it. Checked ahead of the bypass below: this is a
    # confidence question, not a policy override, and it should read as one.
    if low_confidence:
        print("\n".join(retitle(lines, "notice", "unmapped extension, advisory only")), file=sys.stderr)
        sys.exit(0)

    # Kit-wide bypass (issue #47). Checked last, so the findings are already
    # built and still get printed. Bypassing changes enforcement, not
    # reporting: the write proceeds and the reader still sees what tripped.
    bypass = local_kit.bypass_release("guard_style", content, len(findings)) if local_kit else None
    if bypass:
        print("\n".join(retitle(lines, "bypassed", f"kit bypass active ({bypass}), not enforced")),
              file=sys.stderr)
        sys.exit(0)

    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
