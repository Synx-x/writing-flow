#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Stop hook: audit last assistant response for AI writing pattern violations.

Writes violations to ~/.claude/.last_violations.json for next-turn feedback
via violation_feedback.py (UserPromptSubmit hook). Also logs to
rule-activations.jsonl for observability (Phase 5).

Source of truth for pattern lists: style_check.py (imported, not duplicated).
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config as wf_config
from writing_flow import guard_format  # noqa: E402
from writing_flow.scope import in_subagent, read_payload
from writing_flow.bg_spawn import spawn_worker
from writing_flow.violations_store import violations_file_for
from writing_flow import flow_state
from writing_flow import paths as kit_paths
from writing_flow.phase import read_current_phase as read_phase_state
from writing_flow.runtime import HarnessRuntime
try:
    import clean_reply_handoff
except Exception:
    clean_reply_handoff = None
from writing_flow.transcript import user_prose

# Plain mode is optional. A missing module leaves the flow gate in charge
# rather than breaking the audit.
try:
    from writing_flow import plain_rules
    from writing_flow import plain_state
    from writing_flow import rewrite_log
except Exception:
    plain_rules = None
    plain_state = None
    rewrite_log = None

# An overridden state dir holds the log itself, so a test run stays inside
# its own directory. A real install keeps it at ~/.claude/rule-activations.jsonl.
ACTIVATIONS_LOG = (
    kit_paths.state_override() or kit_paths.claude_code_dir()
) / "rule-activations.jsonl"
# stop_hook_active is shared across the WHOLE Stop-hook batch for a session,
# not scoped to this script -- if any other Stop hook blocks (completion_gate,
# a /goal condition, etc), every hook's next invocation sees stop_hook_active
# true, permanently disabling this one's own block path regardless of that
# turn's actual content (confirmed live, see main()'s use of BLOCK_MARKER_FILE
# instead). Track our own one-block-per-distinct-response marker.
BLOCK_MARKER_FILE = (
    kit_paths.state_dir()
    / "response_audit_last_blocked.json"
)

RETRIEVAL_TOOLS = {
    "WebSearch", "WebFetch", "Bash", "Read", "Grep", "Glob",
    "mcp__firecrawl__firecrawl_scrape", "mcp__firecrawl__firecrawl_search",
}

DISCLOSURE_PHRASES = [
    # Training knowledge acknowledgment
    "best guess", "unverified", "training knowledge", "can't confirm", "not verified",
    "i haven't verified", "haven't confirmed",
    # User-context attribution (user-provided is not independently verified)
    "as you mentioned", "as you said", "per your description", "based on what you",
    "you mentioned that", "you said that", "you noted that", "user-reported",
    "according to you",
]

# Decision/recommendation language — the class of statement EnterPlanMode's own
# trigger criteria describe as "architectural decisions" and "multiple valid
# approaches" (library picks, config choices, implementation approach). Narrower
# than FACTUAL_CLAIM_PATTERNS: only fires in coding/meta phases, where an
# unverified choice has real cost, not on general conversation.
DECISION_PATTERNS = [
    re.compile(r"\bI'?ll use\b", re.IGNORECASE),
    re.compile(r"\brecommend(?:s|ed)?\s+using\b", re.IGNORECASE),
    re.compile(r"\bthe best approach is\b", re.IGNORECASE),
    re.compile(r"\bchoose\s+\S+\s+over\s+\S+\b", re.IGNORECASE),
    re.compile(r"\bshould use\b", re.IGNORECASE),
    re.compile(r"\bopt for\b", re.IGNORECASE),
]

FACTUAL_CLAIM_PATTERNS = [
    re.compile(r'\b(introduced|released|launched|published|shipped|announced)\s+in\s+\d{4}', re.IGNORECASE),
    re.compile(r'\bv?\d+\.\d+(\.\d+)?\b'),
    re.compile(r'\bsince\s+\d{4}\b', re.IGNORECASE),
    re.compile(r'\b(is|are|was|were)\s+(based on|built on|built with|powered by|written in)\b', re.IGNORECASE),
    re.compile(r'\b(supports?|requires?|depends on)\s+\S+\s+(v\d|version|\d+\.\d+)', re.IGNORECASE),
]

# Localization rules live in lib/locale_preset.py, keyed on the reader's locale.

# Import shared prose rules
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from writing_flow.prose_rules import scan as scan_prose, STE_FLAVORED, ste_mode
except ImportError:
    def scan_prose(text, kinds=None, **_kwargs):
        return []
    STE_FLAVORED = ()
    def ste_mode():
        return "default"

# Import personal style checks if available
try:
    from writing_flow.personal_style import check_personal_style, check_verbosity_budget, is_short_continuation
except ImportError:
    def check_personal_style(content):
        return []
    def check_verbosity_budget(text, phase, prompt_word_count, prompt_text="",
                               tools_used=None):
        return []
    def is_short_continuation(prompt_text):
        return False

try:
    from writing_flow.shell_argv import command_argvs
except ImportError:
    command_argvs = None

try:
    from writing_flow import output_style
except ImportError:
    output_style = None

# Reader-flow checks over the chat reply itself. guard_flow covers files it
# never sees a chat reply, because it fires on Write and Edit only.
try:
    from writing_flow import flow_rules
except ImportError:
    flow_rules = None

try:
    from writing_flow import config as local_kit
except ImportError:
    local_kit = None

FLOW_STATE_DIR = kit_paths.state_dir()
FLOW_LOG = FLOW_STATE_DIR / "guard_flow_log.jsonl"

def read_current_phase(state_dir: Path | None = None, session_id: str | None = None) -> str:
    """The phase phase_classifier.py wrote for this session, or "".

    Reads the legacy "phase" key, which holds the topic (coding, meta,
    writing). The decision-verify check and the verbosity exemptions compare
    against topics, so the stage key would silently disable both.
    """
    try:
        phase_data = read_phase_state(state_dir or kit_paths.state_dir(), session_id)
        return phase_data.get("phase", "")
    except (OSError, json.JSONDecodeError):
        return ""

try:
    import research_ledger
except Exception:
    research_ledger = None
try:
    import research_gate
except Exception:
    research_gate = None

try:
    from _transcript_utils import get_current_turn_tools
except ImportError:
    def get_current_turn_tools(transcript_path):
        return set(), {}


# Response-specific checks (not in style_check — these apply to
# conversation output, not file content)
OPENER_ADVERBS = [
    "honestly,", "frankly,", "clearly,", "essentially,",
    "interestingly,", "notably,", "importantly,",
]

ACKNOWLEDGMENT_LOOPS = [
    "you're asking about", "to answer your question",
    "the question of whether", "that's a great question",
]


def get_last_assistant_text(transcript_path: str) -> str:
    """Extract text from the last assistant message in a session JSONL."""
    last_text = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                parts = []
                for block in rec.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if t:
                            parts.append(t)
                if parts:
                    last_text = "\n".join(parts)
    except OSError:
        pass
    return last_text


def _genuine_user_prompts(transcript_path: str):
    """Generator of genuine user prompts, newest first.

    Skips isMeta turns (system records), Stop hook feedback, and audit
    findings. Yields text of each genuine user prompt in reverse order
    (newest first).
    """
    prompts = []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # user_prose also drops compaction summaries and agent
                # notifications, which no person typed.
                text_content = user_prose(rec)
                if text_content is None:
                    continue

                # Skip harness feedback: Stop hook feedback, audit findings, etc.
                if text_content.startswith("Stop hook feedback:"):
                    continue
                if ("RESPONSE AUDIT" in text_content or "Plain: " in text_content
                        or "harness-kit[audit:" in text_content):
                    continue

                prompts.append(text_content)
    except OSError:
        pass

    for prompt in reversed(prompts):
        yield prompt


def get_last_user_prompt_text(transcript_path: str) -> str:
    """Text of the last real user prompt (not a tool_result, not a
    hook-injected pseudo-turn) in the transcript.

    Used both to scale the verbosity budget to how much the user actually
    asked, and to read a stated hard limit ("in under 100 words") straight
    off what they typed.

    Claude Code marks injected content -- a blocked Stop hook's reason
    replayed back as a "user"-role turn, a system reminder, etc -- with
    isMeta: true on the JSONL record. Skipping those isn't optional: a
    Stop-hook block reason is often long prose, and counting it as "what
    the user asked" inflates the budget until nothing can trip a HARD
    finding (confirmed live -- a single blocking hook elsewhere in the
    session, e.g. a /goal condition, otherwise silently defeats this check
    for the rest of the session).

    Additionally, turns starting with "Stop hook feedback:" or carrying
    audit's own finding phrasing (like "RESPONSE AUDIT", "Plain: ") are
    harness feedback, not user prompts. They are skipped when searching
    for stated word limits and budget.
    """
    for prompt in _genuine_user_prompts(transcript_path):
        return prompt
    return ""


def get_last_user_prompt_word_count(transcript_path: str) -> int:
    """Word count of the last real user prompt. See get_last_user_prompt_text."""
    return len(get_last_user_prompt_text(transcript_path).split())


def phase_of_prompt(state_dir, session_id: str, prompt: str) -> str:
    """The legacy "phase" key phase_classifier gave `prompt` in this session, or "".

    Reads phase_history.jsonl newest first. The "phase" key holds the topic,
    which the verbosity exemptions and the decision-verify check compare
    against, so "stage" would be the wrong key.
    """
    if not session_id or not prompt:
        return ""
    history = Path(state_dir or kit_paths.state_dir()) / "phase_history.jsonl"
    try:
        lines = history.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    preview = prompt[:100]
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("session_id") == session_id and record.get("prompt_preview") == preview:
            return str(record.get("phase", ""))
    return ""


def get_most_recent_substantive_prompt_text(transcript_path: str) -> str:
    """Text of the most recent substantive user prompt, skipping continuations.

    A short continuation (like 'yes', 'continue', 'go') is not suitable for
    budget sizing because its brevity does not reflect the scope of work the
    model is expected to report. The budget must be sized from the prompt that
    opened the multi-step task, not the continuation that asks for the next step.

    Uses the same filtering as get_last_user_prompt_text to skip meta records,
    Stop hook feedback, and audit findings.
    """
    for prompt in _genuine_user_prompts(transcript_path):
        if not is_short_continuation(prompt):
            return prompt
    return ""


def check_response_patterns(text: str) -> list[tuple[str, str]]:
    """Response-specific pattern checks beyond what style_check covers."""
    findings = []
    text_lower = text.lower().strip()

    # Opener adverb: first word is a filler adverb followed by comma
    first_line = text_lower.split("\n")[0] if text_lower else ""
    for adverb in OPENER_ADVERBS:
        if first_line.startswith(adverb):
            word = adverb.rstrip(",")
            findings.append(("SOFT", f"Filler opener '{word}' as first word. Cut it."))
            break

    # Acknowledgment loop opener
    for phrase in ACKNOWLEDGMENT_LOOPS:
        if phrase in text_lower[:200]:
            findings.append(("SOFT", f"Acknowledgment loop: '{phrase}'. Just answer."))
            break

    # Header density: 3+ markdown headers in < 300 words
    lines = text.split("\n")
    md_headers = [ln for ln in lines if re.match(r"^\s*#{1,4}\s", ln)]
    word_count = len(text.split())
    if len(md_headers) >= 3 and word_count < 300:
        findings.append((
            "SOFT",
            f"Header density: {len(md_headers)} headers in {word_count} words "
            f"(max 2 under 300 words)."
        ))

    # Bullet density: 8+ bullets in < 200 words
    bullets = [ln for ln in lines
               if ln.strip().startswith("- ") or ln.strip().startswith("* ")
               or re.match(r"^\s*\d+\.\s", ln.strip())]
    if len(bullets) >= 8 and word_count < 200:
        findings.append((
            "SOFT",
            f"Bullet density: {len(bullets)} bullets in {word_count} words "
            f"(max 7 under 200 words)."
        ))

    return findings


_GH_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/(?:pull|issues)/(\d+)")
_GH_API = re.compile(r"^/?repos/([^/]+/[^/]+)/(?:pulls|issues)/(\d+)")
_GH_READS = {("pr", "view"), ("pr", "checks"), ("pr", "diff"), ("issue", "view")}
_GH_VALUE_OPTS = frozenset(("-R", "--repo", "-q", "--jq", "-t", "--template", "--json",
                            "-H", "--header", "-X", "--method", "-F", "-f", "--field",
                            "--raw-field", "-c", "--comments"))


def _gh_reads(bash_inputs: list) -> set:
    """(repo or None, number) for each PR or issue a gh command in this turn read.

    `gh pr view 66` names no repo because gh takes it from the checkout, so a
    read without a repo matches a cited URL by number alone.
    """
    reads = set()
    if command_argvs is None:
        return reads
    for inp in bash_inputs or []:
        command = str((inp or {}).get("command", ""))
        if "gh" not in command:
            continue
        try:
            argvs = command_argvs(command)
        except ValueError:
            continue
        for argv in argvs:
            if not argv or Path(argv[0]).name != "gh" or len(argv) < 2:
                continue
            if argv[1] == "api":
                for arg in argv[2:]:
                    match = _GH_API.match(arg)
                    if match:
                        reads.add((match.group(1), match.group(2)))
                continue
            if tuple(argv[1:3]) not in _GH_READS:
                continue
            repo, number, rest = None, None, argv[3:]
            while rest:
                arg = rest.pop(0)
                if arg in ("-R", "--repo") and rest:
                    repo = rest.pop(0)
                elif arg.startswith("--repo="):
                    repo = arg.split("=", 1)[1]
                elif arg in _GH_VALUE_OPTS and rest:
                    rest.pop(0)
                elif arg.startswith("-"):
                    continue
                elif number is None:
                    url = _GH_URL.match(arg)
                    if url:
                        repo, number = url.group(1), url.group(2)
                    elif arg.isdigit():
                        number = arg
            if number:
                reads.add((repo, number))
    return reads


def _read_by_gh(url: str, reads: set) -> bool:
    match = _GH_URL.match(url)
    if not match:
        return False
    repo, number = match.group(1), match.group(2)
    return (repo, number) in reads or (None, number) in reads


def check_grounded_response(text: str, tools_used: set, tool_inputs: dict, phase: str = "",
                            ledger_urls: set | None = None) -> list[tuple[str, str]]:
    """Check if response makes factual claims or non-trivial decisions without
    verification or self-disclosure.

    Requires 2+ factual claim pattern matches before flagging (reduces false positives).
    User-provided context is not a bypass — the model must explicitly attribute the source
    or independently verify it.

    Also counts gh reads (gh pr view, gh pr checks, gh issue view, gh api repos/...)
    as fetching the matching GitHub URLs.
    """
    findings = []

    # Strip code blocks before analysis so version numbers in code don't trigger
    prose = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    prose_lower = prose.lower()

    has_disclosure = any(phrase in prose_lower for phrase in DISCLOSURE_PHRASES)
    retrieval_done = bool(RETRIEVAL_TOOLS & tools_used)

    # Count factual claim pattern matches
    claim_matches = sum(1 for pattern in FACTUAL_CLAIM_PATTERNS if pattern.search(prose))

    if claim_matches >= 2 and not has_disclosure and not retrieval_done:
        findings.append((
            "SOFT",
            "Grounded-response: factual claims detected without retrieval tool use or "
            "self-disclosure. Label training-knowledge assertions as unverified, or fetch first."
        ))

    # Decision-verify nudge: narrower than the factual-claim check above, fires
    # on recommendation/choice language specifically, only in coding/meta phases
    # (library picks, config/approach choices — non-trivial technical decisions).
    if phase in ("coding", "meta"):
        decision_matches = sum(1 for pattern in DECISION_PATTERNS if pattern.search(prose))
        if decision_matches >= 1 and not has_disclosure and not retrieval_done:
            findings.append((
                "SOFT",
                "Decision language without verification: cite what was checked "
                "(docs, --help, source), or state this is a judgment call."
            ))

    # URL citation cross-check: cited URLs that were never fetched.
    # Count WebFetch, gh reads and the research ledger as fetching. The ledger
    # holds every URL a tool result showed this session, such as the issue URL
    # that `gh issue create` prints (issue #98).
    cited_urls = re.findall(r'https?://\S+', prose)
    if cited_urls:
        fetched_urls = {
            inp.get("url", "")
            for inp in tool_inputs.get("WebFetch", [])
        } | set(ledger_urls or ())

        gh_reads = _gh_reads(tool_inputs.get("Bash", []))
        unfetched = [
            u.rstrip(".,)>") for u in cited_urls[:3]
            if u.rstrip(".,)>") not in fetched_urls and not _read_by_gh(u.rstrip(".,)>"), gh_reads)
        ]
        if unfetched and "WebFetch" not in tools_used and "WebSearch" not in tools_used:
            findings.append((
                "SOFT",
                f"Cited URLs not fetched this turn: {unfetched[0][:80]}. "
                "Either fetch them or remove the citation."
            ))

    return findings


def response_flow_mode() -> str:
    """How hard reader-flow rules push on a chat reply.

    Chat is a different surface from a document, so it carries its own mode
    rather than inheriting guard_flow's. Someone who blocks a sloppy doc may
    still want a fast conversational reply.

    The default is strict. A reply the reader cannot follow is the failure this
    kit exists to prevent, and an advisory notice never changed one, because
    the reply has already been sent by the time the notice lands. Set
    `flow_mode` to warn or off to soften it.

    Config: hooks.response_audit.flow_mode, one of off, warn, strict.
    Env override: HARNESS_KIT_RESPONSE_FLOW.
    """
    val = (wf_config.env("RESPONSE_FLOW") or "").strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    if local_kit is None:
        return "strict"
    try:
        cfg = local_kit.hook_config("response_audit") or {}
    except Exception:
        return "strict"
    val = str(cfg.get("flow_mode", "")).strip().lower()
    return val if val in ("off", "warn", "strict") else "strict"


def _flow_cfg() -> dict:
    if local_kit is None:
        return {}
    try:
        return local_kit.hook_config("response_audit") or {}
    except Exception:
        return {}


def take_flow_override(session_id: str, cfg: dict) -> str | None:
    """Consume the same one-shot override guard_flow uses, scoped to chat.

    One escape mechanism covers both surfaces, so a judgement call about a
    passage needs no second mechanism when that passage is a chat reply. The
    slot itself is per surface: a subagent's override for its own document
    must not be spent on an unrelated chat reply, or the reverse.
    """
    return flow_state.take_override(
        session_id, flow_state.CHAT_TARGET, bool(cfg.get("allow_override", True))
    )


def discard_stale_override(session_id: str, cfg: dict) -> None:
    """Drop a written override that never got applied.

    A clean final reply means the marker's reason never matched any finding
    in this turn. Left on disk, it would silently forgive whatever the next
    unrelated block turns out to be.
    """
    flow_state.discard_override(
        session_id, flow_state.CHAT_TARGET, bool(cfg.get("allow_override", True))
    )


def log_flow_outcome(outcome: str, kinds: list, reason: str = "") -> None:
    """Record chat-reply outcomes in guard_flow's log.

    One log covers both surfaces, so scripts/flow_report.py measures the whole
    override rate rather than the file half of it.

    Takes plain kind strings rather than finding dicts, because the chat-form
    rules and the reader-flow rules now share one gate and one log line.
    """
    try:
        FLOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        for kind in kinds:
            counts[kind] = counts.get(kind, 0) + 1
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": "<chat response>",
            "mode": response_flow_mode(),
            "counts": counts,
            "outcome": outcome,
        }
        if reason:
            record["reason"] = reason[:400]
        with FLOW_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def check_response_flow(text: str, session_id: str = "",
                        kinds_out: list | None = None) -> list[tuple[str, str]]:
    """Reader-flow findings on the chat reply, severity set by the mode.

    Strict returns HARD findings, which block Stop and force a revision before
    the reply reaches the user. That is the only path that makes flow rules
    deterministic for chat, because a system-prompt instruction is advice the
    model can drift from and a Stop block is not.

    Candidates only. apply_flow_gate() owns the override, the repeat-block
    cap and the log line, because check_chat_form shares all three. Gated
    separately, each surface carried its own block budget, so one reply could
    spend both and the reader saw a duplicate answer for each.

    `session_id` stays in the signature for callers that predate the split.
    `kinds_out`, when passed, collects every finding's kind for the log.
    """
    mode = response_flow_mode()
    if mode == "off" or flow_rules is None or not text:
        return []
    cfg = _flow_cfg()
    kinds = tuple(cfg.get("flow_kinds") or flow_rules.ALL_KINDS)
    try:
        findings = flow_rules.scan_flow(text, kinds=kinds)
    except Exception:
        return []  # a linter bug must never trap a reply
    if kinds_out is not None:
        kinds_out.extend(f["kind"] for f in findings[:6])
    if mode == "strict":
        return [("HARD", f"Reader flow: {f['label']}") for f in findings[:6]]
    return [(f["kind"], f["label"]) for f in findings[:6]]


def flow_block_cap(cfg: dict) -> int:
    """Consecutive Stop blocks before the reply goes through regardless.

    One. Each block sends the turn back for a revision, and Claude Code
    renders that revision as a new assistant message rather than replacing
    the one it judged. The reader therefore sees every block as a duplicate
    answer. Observed 2026-09-10: a cap of two shipped three near-identical
    answers to one question, and the third still carried a finding, because
    the cap released it rather than the model satisfying the rule.

    Config: hooks.response_audit.flow_block_cap. Zero never blocks.
    """
    try:
        return max(0, int(cfg.get("flow_block_cap", 1)))
    except (TypeError, ValueError):
        return 1


def apply_flow_gate(items: list[tuple[str, str]], kinds: list[str],
                    session_id: str) -> list[tuple[str, str]]:
    """One override, one block budget and one log line for both chat gates.

    check_response_flow and check_chat_form both emit HARD in strict mode.
    Each used to own its decision, so a reply could block twice for flow and
    twice again for form, and every block cost the reader another duplicate
    answer. The budget belongs to the reply, not to the rule family.
    """
    cfg = _flow_cfg()
    if not items:
        _reset_block_count(session_id)
        # A written-but-unused override must not outlive the turn it was
        # written for. Confirmed live: a model wrote a reason, then its own
        # final reply carried no finding to apply it to, and the marker sat
        # on disk ready to silently forgive an unrelated later block.
        discard_stale_override(session_id, cfg)
        return []

    if not any(severity == "HARD" for severity, _ in items):
        log_flow_outcome("notice", kinds)
        return items

    reason = take_flow_override(session_id, cfg)
    if reason is not None:
        _reset_block_count(session_id)
        log_flow_outcome("override", kinds, reason)
        return []

    cap = flow_block_cap(cfg)
    blocks = _read_block_count(session_id)
    if blocks >= cap:
        _reset_block_count(session_id)
        log_flow_outcome("capped", kinds, f"{blocks} consecutive blocks")
        return []

    _write_block_count(session_id, blocks + 1)
    log_flow_outcome("blocked", kinds)
    return items


def _block_count_path(session_id: str) -> Path:
    return flow_state.block_count_path(session_id, flow_state.CHAT_TARGET)


def _read_block_count(session_id: str) -> int:
    return flow_state.read_block_count(session_id, flow_state.CHAT_TARGET)


def _write_block_count(session_id: str, count: int) -> None:
    flow_state.write_block_count(session_id, count, flow_state.CHAT_TARGET)


def _reset_block_count(session_id: str) -> None:
    flow_state.reset_block_count(session_id, flow_state.CHAT_TARGET)


SENTENCE_HARD_CAP = 30
_PARENTHETICAL = re.compile(r"\([^)\n]{2,}\)")
_BOLD_SPAN = re.compile(r"\*\*([^*\n]+)\*\*")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_FENCE_BLOCK = re.compile(r"```.*?```", re.DOTALL)


def _is_glossed_parenthetical(text: str, paren_match) -> bool:
    """Check if a parenthetical is actually a gloss for a tracked term.

    A gloss parenthetical like 'hook (a script that runs on its own)' should
    not trigger the parenthetical violation if it follows a term from the
    plain-mode TRACKED_TERMS list.
    """
    if not plain_rules:
        return False

    # Position just before the parenthetical match
    paren_start = paren_match.start()
    if paren_start < 1:
        return False

    # Look back up to 50 characters for a tracked term
    search_start = max(0, paren_start - 50)
    before_text = text[search_start:paren_start].strip()

    # Find which tracked term appears at the end of before_text
    for term in plain_rules.TRACKED_TERMS:
        # Case-insensitive, word-boundary check
        pattern = r"\b" + re.escape(term) + r"\s*$"
        if re.search(pattern, before_text, re.IGNORECASE):
            return True

    return False


def chat_form_mode() -> str:
    """How hard the chat form rules push. Same three modes as flow.

    Provenance: these rules come from this harness's own reply-formatting
    instructions (the "Writing for the user" section of the system prompt),
    not from writerscience.com. flow_rules.py's seven kinds trace to William
    Fitzpatrick's Writer Science video and its writing-tools library, cited
    in flow_rules.py's own module docstring. check_chat_form() is a second,
    complementary source layered onto the same block-and-hint mechanism.

    These rules carry no linter anywhere else. A model reads them in a style
    guide and drifts from them, which is the same failure the flow gate was
    built to close. Measured on one real reply: a 72-word sentence, a
    parenthetical, a semicolon and three whole-sentence bold spans all
    shipped past every existing check.

    Config: hooks.response_audit.chat_form, one of off, warn, strict.
    Env override: HARNESS_KIT_CHAT_FORM.
    """
    val = (wf_config.env("CHAT_FORM") or "").strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    cfg = _flow_cfg()
    val = str(cfg.get("chat_form", "")).strip().lower()
    return val if val in ("off", "warn", "strict") else "strict"


def chat_prose(text: str) -> str:
    """The reply minus fenced code, table rows, markdown links, and inline code."""
    out = _FENCE_BLOCK.sub("", text)
    out = _TABLE_ROW.sub("", out)
    # Strip markdown links [text](url) → keep the text part only
    out = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', out)
    # Strip inline code spans to avoid false positives on parentheses in code
    out = re.sub(r'`[^`\n]*`', '', out)
    return out


_JARGON_TOKEN = re.compile(r"`([A-Za-z][\w.:/-]{2,40})`")
_GLOSS_NEAR = re.compile(
    r"\b(is|are|was|means|holds|writes|reads|runs|returns|blocks|scans|the)\b",
    re.IGNORECASE,
)


def undefined_jargon(text: str, limit: int = 3) -> list[str]:
    """Backticked identifiers used in prose with no gloss in the same sentence.

    A reply naming `flow_state` or `subagent_style_audit` reads fine to the
    person who wrote the hook and stops the person who did not. The check is
    a heuristic, so it stays advisory: it looks only at the FIRST mention of
    each term, and clears the term when the same sentence carries a defining
    verb or an appositive. Code blocks and paths are left alone, since those
    are quoted material rather than terms the reader must hold.
    """
    if not text:
        return []
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    out, seen = [], set()
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        if sentence.lstrip().startswith(("|", ">", "#", "-", "*")):
            continue          # tables, quotes, headings and list rows
        for m in _JARGON_TOKEN.finditer(sentence):
            term = m.group(1)
            if term in seen:
                continue
            seen.add(term)
            if "/" in term or term.endswith((".md", ".json", ".txt", ".jsonl")):
                continue      # a path, not a term
            if not re.search(r"[_.]|[a-z][A-Z]", term):
                continue      # a plain word in backticks reads as itself
            tail = sentence[m.end():]
            if _GLOSS_NEAR.search(tail[:90]) or tail.lstrip().startswith(","):
                continue      # glossed in place
            out.append(term)
            if len(out) >= limit:
                return out
    return out


def check_chat_form(text: str, kinds_out: list | None = None) -> list[tuple[str, str]]:
    """Form rules for a chat reply that no other check covers.

    Each one is deterministic and cheap. A finding names what to do, not
    what went wrong, because the model reads it while revising.

    Candidates only, like check_response_flow. apply_flow_gate() decides
    whether they block. `kinds_out`, when passed, collects each finding's
    kind so the shared log line counts these rules alongside the flow ones.
    """
    mode = chat_form_mode()
    if mode == "off" or not text:
        return []
    prose = chat_prose(text)
    severity = "HARD" if mode == "strict" else "SOFT"
    out = []

    def add(kind: str, detail: str, level: str | None = None) -> None:
        out.append((level or severity, detail))
        if kinds_out is not None:
            kinds_out.append(kind)

    # Measured 2026-09-23 over local transcripts: a blocked reply came back
    # 20 to 30 percent rewritten for a bracket, a semicolon or an arrow, at the
    # cost of a full extra turn. Those reach the next turn as SOFT feedback.
    # The active output style can exempt rules from chat outright.
    exempt = output_style.chat_exemptions() if output_style is not None else frozenset()

    for term in undefined_jargon(text):
        # Advisory on its own. A reader who does not already know the term
        # loses the sentence, but the rule guesses at what counts as known,
        # so it must not be the thing that blocks a correct answer.
        out.append(("SOFT", f"Jargon: '{term}' used without a gloss. Say what it is on first use."))
        if kinds_out is not None:
            kinds_out.append("undefined_jargon")

    match = _PARENTHETICAL.search(prose)
    if match and not _is_glossed_parenthetical(prose, match):
        add("parenthetical", f"Chat form: parenthetical {match.group(0)[:50]}. Fold it into the sentence or drop it.", "SOFT")
    if ";" in prose and "semicolon" not in exempt:
        add("semicolon", "Chat form: semicolon. Start a new sentence instead.", "SOFT")
    for arrow in ("->", "=>", "→"):
        if arrow in prose:
            add("arrow", f"Chat form: arrow {arrow}. Say the relation in words.", "SOFT")
            break

    for span in _BOLD_SPAN.findall(prose):
        if span.rstrip().endswith((".", "!", "?")):
            add("bold_sentence", f"Chat form: whole sentence bolded, '{span[:45]}'. Bold the opening few words only.", "SOFT")
            break

    if flow_rules is not None and "word_caps" not in exempt:
        try:
            sentences = flow_rules.split_sentences(flow_rules.prose_only(prose))
        except Exception:
            sentences = []
        for sentence in sentences:
            count = len(sentence.split())
            if count > SENTENCE_HARD_CAP:
                add(
                    "long_sentence",
                    f"Chat form: {count}-word sentence, cap {SENTENCE_HARD_CAP}. "
                    f"Split it, or make it a list: '{sentence[:45]}'",
                    None if count >= SENTENCE_HARD_CAP * 1.5 else "SOFT",
                )
                break

    return out


def flow_override_hint(session_id: str) -> str:
    """Tell the model where the escape is, so a wrong finding costs one line.

    Live-driven, caught: a model wrote a correct reason, then answered with a
    status report about writing the file instead of resending the actual
    paragraph. The user's question went unanswered. The wording now says so.
    """
    marker = flow_state.override_path(session_id, flow_state.CHAT_TARGET)
    return (
        "  Revise the flagged paragraph. If a finding is wrong for this passage, "
        f"write one line saying why to {marker}, then send the SAME answer again "
        "unchanged. Do not replace it with a report about writing the file."
    )


def log_violations(violations: list[tuple[str, str]]) -> None:
    """Append violations to rule-activations.jsonl for observability."""
    ts = datetime.now(timezone.utc).isoformat()
    for severity, detail in violations:
        rule = (
            "grounded-responses"
            if detail.startswith("Grounded-response") or detail.startswith("Cited URLs")
            else "localization"
            if detail.startswith("Localization:")
            else "anti-ai-writing"
        )
        entry = {
            "ts": ts,
            "event": "violation",
            "rule": rule,
            "severity": severity,
            "detail": detail,
        }
        try:
            with open(ACTIVATIONS_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass


ASK_VIA_TOOL = "Ask via tool"
_ASK_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_ASK_INLINE = re.compile(r"`[^`\n]*`")
_ASK_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d')
_ASK_QUESTION = re.compile(r"[^.!?\n]*\?(?=\s|$)")
_ASK_ADDRESSED = re.compile(r"\b(you|your|should i|shall i|want me to|would you|do you|which)\b", re.I)


def check_ask_via_tool(text: str, tools_used: set) -> list[tuple[str, str]]:
    """A reply that asks the user a question without AskUserQuestion.

    Code, block quotes and quoted spans drop out first. A question counts when
    it sits in the last block or speaks to the reader. The finding names the
    first one and says how many more follow.
    """
    if "AskUserQuestion" in tools_used:
        return []
    stripped = _ASK_FENCE.sub("", text)
    stripped = _ASK_INLINE.sub("", stripped)
    stripped = "\n".join(ln for ln in stripped.splitlines() if not ln.lstrip().startswith(">"))
    stripped = _ASK_QUOTED.sub("", stripped)
    blocks = [b for b in re.split(r"\n\s*\n", stripped) if b.strip()]
    kept = []
    for i, block in enumerate(blocks):
        for match in _ASK_QUESTION.finditer(block):
            question = match.group(0).strip()
            if i == len(blocks) - 1 or _ASK_ADDRESSED.search(question):
                kept.append(question)
    if not kept:
        return []
    quoted = kept[0].replace(". ", ", ")[:80]
    more = f" with {len(kept) - 1} more" if len(kept) > 1 else ""
    return [("HARD", f'{ASK_VIA_TOOL}: "{quoted}" asked in prose{more}. '
                     "Ask through AskUserQuestion, recommended option first")]


def compute_findings(transcript_path: str, text: str | None = None,
                     session_id: str = "", state_dir: Path | None = None) -> list[tuple[str, str]]:
    """Pure check pass over the last assistant response. No side effects --
    fast enough (regex/string work over an already-bounded transcript read,
    no LLM call) to run synchronously in main(), which is what lets a HARD
    finding block Stop this same turn instead of only surfacing next turn.

    `text` lets a caller that already read the transcript (main(), to hash
    the exact same text for BLOCK_MARKER_FILE) pass it in instead of this
    function re-reading the file independently. Two separate reads of a
    transcript that's still being actively written can race and disagree
    (confirmed live: compute_findings saw real content while a second,
    independent get_last_assistant_text() call moments later saw an empty
    read, hashing "" instead of the actual judged text) -- one read, shared,
    closes that.
    """
    if text is None:
        text = get_last_assistant_text(transcript_path)
    if not text or len(text) < 20:
        return []

    # Run all checks
    all_findings = []
    # Use shared prose rules for ai_ism, tier1, em_dash, and (flavored, no
    # word caps — chat needs voice) the ASD-STE100-derived structural checks.
    kinds = ("ai_ism", "tier1", "em_dash")
    if ste_mode() != "off":
        kinds = kinds + STE_FLAVORED
    prose_findings = scan_prose(text, kinds=kinds)
    all_findings.extend([(f["kind"], f["label"]) for f in prose_findings])
    # Add response-specific checks
    all_findings.extend(check_response_patterns(text))
    all_findings.extend(check_personal_style(text))
    # Both chat gates share one override, one block budget and one log line.
    # Separately gated, each carried its own budget and the reader paid for
    # every block with another near-identical answer.
    # Plain mode swaps the flow gate for the plain caps. Gopen's model
    # serves a reader who knows the domain, the plain caps serve one who
    # does not, so running both would send one sentence two contradictory
    # instructions. Every other check still runs, since tier-1 words and
    # ungrounded claims are wrong in any mode.
    gate_kinds: list[str] = []
    # [override-plain-mode: <reason>] in this turn's text lifts the plain
    # caps for this reply only. The reply then meets the normal flow gate.
    override = ""
    if plain_rules is not None:
        override = (plain_rules.override_reason(text)
                    or plain_rules.turn_override(transcript_path))
        if override and rewrite_log is not None:
            rewrite_log.record("response_audit", "plain-override", text[:200],
                               override, session_id)
    if (plain_state is not None and plain_rules is not None
            and plain_state.is_active() and not override):
        seen = plain_state.glossed_terms(session_id)
        gate_items, newly_glossed = plain_rules.scan_plain(text, seen)
        if newly_glossed:
            plain_state.record_glossed(session_id, newly_glossed)
        if gate_items and rewrite_log is not None:
            rewrite_log.record("response_audit", "plain", text[:200], "",
                               session_id)
        gate_kinds.extend(["plain"] * len(gate_items))
    else:
        gate_items = check_response_flow(text, session_id, gate_kinds)
        gate_items += check_chat_form(text, gate_kinds)
    all_findings.extend(apply_flow_gate(gate_items, gate_kinds, session_id))

    # Verbosity budget. A stated limit in the prompt overrides phase and
    # exemption. Without one: phase-scaled, cited evidence exempt, and a
    # read-only turn exempt alongside writing/research/wrap_up/meta.
    phase = read_current_phase(state_dir, session_id)
    prompt_text = get_last_user_prompt_text(transcript_path)
    # "continue" or "yes" asks for the next step and a report of it. Its own
    # length set a 40-word budget and blocked 93-word progress reports in
    # session 9c11c4ed, so the budget follows the prompt that set the task.
    if is_short_continuation(prompt_text):
        substantive = get_most_recent_substantive_prompt_text(transcript_path)
        if substantive:
            prompt_text = substantive
            phase = phase_of_prompt(state_dir, session_id, substantive) or phase
    prompt_word_count = len(prompt_text.split())
    tools_used, tool_inputs = get_current_turn_tools(transcript_path)
    if wf_config.env("HARNESS") != "codex":
        all_findings.extend(check_ask_via_tool(text, tools_used))
    all_findings.extend(check_verbosity_budget(
        text, phase, prompt_word_count, prompt_text, tools_used))

    # Grounded response check — needs tool usage context from transcript
    ledger_urls = set()
    if research_ledger is not None:
        try:
            ledger_urls = research_ledger.seen_urls(session_id)
        except Exception:
            ledger_urls = set()
    all_findings.extend(check_grounded_response(text, tools_used, tool_inputs, phase, ledger_urls))
    try:
        all_findings.extend(check_research_gate(text, session_id, transcript_path, os.getcwd()))
    except Exception as exc:
        print(f"response_audit: research gate skipped: {exc}", file=sys.stderr)

    return all_findings


def check_research_gate(text: str, session_id: str, transcript_path: str,
                        cwd: str = "") -> list[tuple[str, str]]:
    """Research Gate backstop over the whole reply (issue #98).

    The same detector as research_gate_pre, run once at Stop. Warn mode gives
    a SOFT finding. Strict mode gives a HARD one, and the audit's own marker
    blocks only once per reply text. It reads gate state and writes nothing,
    so compute_findings stays side-effect free.
    """
    if research_gate is None or research_ledger is None:
        return []
    gate_mode = research_gate.mode()
    if gate_mode == "off":
        return []
    rules = research_gate.load_rules(cwd)
    state = research_gate.load_state(session_id)
    pins = research_gate.pins_for(rules, cwd, state["pins"])
    _, events = research_gate.turn_events(transcript_path)
    ledger = research_ledger.entries(session_id)
    gaps = research_gate.claim_gaps(text, rules) + research_gate.promise_gaps(events)
    findings = []
    level = "HARD" if gate_mode == "strict" else "SOFT"
    for gap in gaps:
        if research_gate.covered(gap, ledger, pins):
            continue
        findings.append((level, "Research Gate: " + research_gate.describe(gap, rules, pins)))
        if len(findings) >= research_gate.MAX_PER_TURN:
            break
    return findings


def persist_and_log(findings: list[tuple[str, str]], session_id: str) -> None:
    """Write this session's violation record for next-turn feedback, plus
    append to the activations log. Shared by the blocking path (main(), same
    turn) and the backgrounded worker path (run_audit()), so there is one
    place that does this write, not two copies drifting apart.
    """
    target = violations_file_for(session_id)
    if not findings:
        target.unlink(missing_ok=True)
        return

    violation_data = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "violations": [{"severity": s, "detail": d} for s, d in findings],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(violation_data), encoding="utf-8")
    except OSError:
        pass

    log_violations(findings)


def run_audit(transcript_path: str, session_id: str) -> None:
    """Backgrounded worker entrypoint (spawn_worker's --worker path): compute
    and persist, no blocking possible from here since the parent Stop hook
    has already exited by the time this runs.
    """
    persist_and_log(compute_findings(transcript_path, session_id=session_id), session_id)


def _already_blocked_for(text_hash: str) -> bool:
    """Have we already blocked once for this exact response text?

    One entry, not a growing log -- only the most recent block matters,
    since a genuinely new (different) response should always get its own
    chance to block regardless of how many turns have passed.
    """
    try:
        return json.loads(BLOCK_MARKER_FILE.read_text(encoding="utf-8")).get("hash") == text_hash
    except (OSError, json.JSONDecodeError):
        return False


def _record_blocked(text_hash: str) -> None:
    try:
        BLOCK_MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        BLOCK_MARKER_FILE.write_text(json.dumps({"hash": text_hash}), encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    hook_input = read_payload()
    if not hook_input or in_subagent(hook_input):
        return

    transcript_path = hook_input.get("transcript_path", "")
    session_id = hook_input.get("session_id", "")

    runtime = HarnessRuntime.from_event(hook_input)
    state_dir = runtime.state_dir

    # Prefer the Stop payload's own last_assistant_message (same field
    # completion_gate.py already relies on, live-proven in production) over
    # re-deriving it from the transcript file. The file write consistently
    # lags one full Stop event behind under back-to-back Stop cycles (a
    # /goal condition or any other blocking hook keeps triggering those) --
    # confirmed live, reading the file at decision time repeatedly returned
    # the PRIOR turn's text, never the one just generated. The payload field
    # is constructed by Claude Code in-memory at invocation time, so it has
    # no file-flush dependency.
    text = hook_input.get("last_assistant_message") or get_last_assistant_text(transcript_path)
    if not text:
        return
    findings = compute_findings(transcript_path, text=text, session_id=session_id, state_dir=state_dir)
    hard = [detail for severity, detail in findings if severity == "HARD"]
    # Transcript text can carry lone surrogates such as \udc8d, which arrive
    # when undecodable bytes pass through surrogateescape. Strict UTF-8 refuses
    # to encode them and the hook dies. The hash only needs to be stable, so
    # replace the offenders rather than raise.
    text_hash = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()

    # The clean-reply mod already fixed this reply out of sight. A block now
    # would redraft clean text on screen. Without the mod, nothing is recorded
    # and the block below runs as before.
    if hard and clean_reply_handoff and clean_reply_handoff.handled(session_id, text):
        # A rewrite would delete the question, so the question finding stays.
        hard = [d for d in hard if d.startswith(ASK_VIA_TOOL)]

    if hard and not _already_blocked_for(text_hash):
        # Live, this-turn correction: block Stop so the model revises before
        # the response ever reaches the user, instead of only surfacing the
        # finding next turn via violation_feedback.py. Gated on our own
        # content-hash marker, not Claude Code's stop_hook_active -- that
        # flag is shared across the WHOLE Stop-hook batch for a session, so
        # any other hook blocking (completion_gate, a /goal condition, etc)
        # makes it true on our very first real evaluation too, permanently
        # disabling this block path for reasons that have nothing to do with
        # this turn's actual content. Confirmed live: exit code 2 does reach
        # Claude Code and does fold into the same visible response -- the
        # earlier failures were this contamination plus a second bug in
        # get_last_user_prompt_word_count (see its docstring).
        _record_blocked(text_hash)
        persist_and_log(findings, session_id)
        hint = flow_override_hint(session_id) if any(d.startswith("Reader flow") for d in hard) else ""
        items = []
        for detail in hard:
            text, fix = guard_format.split_fix(detail)
            items.append((text, fix[:1].lower() + fix[1:] if fix else ""))
        notes = ["revise the reply before finishing"] + ([hint] if hint else [])
        print(guard_format.render("audit", "the reply", items, notes=notes), file=sys.stderr)
        if local_kit and local_kit.bypass_release("response_audit"):
            print("  (kit bypass active -- reported, not enforced)",
                  file=sys.stderr)
            sys.exit(0)
        sys.exit(2)

    # No HARD finding, or this exact text already blocked once: keep today's
    # behavior, backgrounded, never stall Stop for logging/SOFT next-turn
    # feedback.
    if findings:
        spawn_worker(Path(__file__).resolve(), [transcript_path, session_id])
    else:
        violations_file_for(session_id).unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        run_audit(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        main()
