#!/usr/bin/env python3
# @schema-version: 1
# @portable: false
"""MessageDisplay hook: fix mechanical AI-writing tells on screen, live,
before the reader sees them.

Every other style gate in this kit acts on a finished draft. guard_style and
guard_flow block a file write. response_audit and flow_reinforce act at
Stop. All three fire once, after the model already composed the whole
reply, so a fix there means recomposing text that already looks done. That
is the reason chat's clean-enforcement rate lagged file writes in the
2026-09-11 measurement (session notes, see docs/mods.md).

MessageDisplay fires earlier and more often: once per batch of newly
completed lines while the assistant message streams, then once more when it
finishes. Its hookSpecificOutput.displayContent field replaces what renders
on screen for that batch, in place, without touching the stored message.
Confirmed against the shipped runtime schema and by driving a real session
(a live session, 2026-09-11). That gives this hook a channel none of
the others have. A correction lands before the reader ever sees the tell,
with no recomposition and no Stop-hook retry budget spent.

Scope, deliberately narrow. This hook can only rewrite the lines in the
current batch. Lines already flushed to the screen are gone, and a stated
final flush may carry no text at all: the delta is empty when the message
ends on a newline, so final is treated as the end-of-message signal
regardless (same live session). So it carries only fixes safe to apply
one line at a time, with no view of the rest of the message: the tier-1
vocabulary swaps from prose_rules.tier1_map() that have exactly one
literal drop-in replacement. A tier-1 word mapped to a single-word
substitute rewrites in place this way. An entry mapped to a parenthetical
instruction is a judgment call this hook cannot make, so it is excluded.

Structural findings need the whole paragraph or the whole message to judge:
topic drift, sentence length, the verbosity budget. Those stay with
flow_reinforce (before composition) and response_audit (at Stop).

Fence-safe: tracks an open/closed code-fence flag per (session, message) in
state, so a rewrite never touches the inside of a fenced code block, and
skips inline single-backtick spans the same way, so an identifier is never
rewritten as prose. Fails open on any error: never blocks, never raises
past main().
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from writing_flow import flow_state  # noqa: E402
from writing_flow import prose_rules  # noqa: E402

# The log is optional. A missing module leaves the swap working and
# unrecorded rather than breaking the display.
try:
    from writing_flow import rewrite_log
except Exception:
    rewrite_log = None


def _literal_tier1_map() -> dict:
    """Tier-1 replacements safe to apply with no surrounding context: one
    literal word or phrase, not a parenthetical instruction or a choice
    between options."""
    out = {}
    for word, repl in prose_rules.tier1_map().items():
        if repl.startswith("(") or "/" in repl:
            continue
        out[word] = repl
    return out


# Longest phrase first, so a longer entry matches whole before a shorter
# substring inside a different entry would.
_TIER1_SUBS = [
    (re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE), repl)
    for word, repl in sorted(
        _literal_tier1_map().items(), key=lambda kv: len(kv[0]), reverse=True
    )
]

_BACKTICK_SPAN = re.compile(r"`[^`]*`")
_FENCE_LINE = re.compile(r"^\s*```")


def _match_case(original: str, replacement: str) -> str:
    """Carry the matched text's capitalization onto its replacement."""
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _rewrite_prose(text: str) -> str:
    """Apply the literal tier-1 swaps to one span of real prose.

    13 of the 52 literal entries flip leading vowel/consonant sound on
    replacement ("actionable" -> "practical"), which left "an actionable"
    rewritten to "an practical" with the article untouched. Fixed once,
    after every swap in this span, in prose_rules.fix_article_agreement --
    shared with scripts/prose_sweep.py rather than fixed here alone.
    """
    swapped = False
    for pattern, repl in _TIER1_SUBS:
        new_text, n = pattern.subn(lambda m, r=repl: _match_case(m.group(0), r), text)
        if n:
            swapped = True
        text = new_text
    if swapped:
        text = prose_rules.fix_article_agreement(text)
    return text


def _rewrite_line(line: str, in_fence: bool) -> tuple:
    """Rewrite one line, honoring code fences and inline spans.

    Returns (rewritten_line, new_in_fence_state). A fence delimiter line
    toggles the state and is never itself rewritten. Inside a fence, or
    inside an inline code span, the text passes through unchanged.
    """
    if _FENCE_LINE.match(line):
        return line, not in_fence
    if in_fence:
        return line, in_fence

    spans = _BACKTICK_SPAN.findall(line)
    pieces = _BACKTICK_SPAN.split(line)
    out = []
    for i, piece in enumerate(pieces):
        out.append(_rewrite_prose(piece))
        if i < len(spans):
            out.append(spans[i])
    return "".join(out), in_fence


def _fence_state_path(session_id: str, message_id: str) -> Path:
    key = f"{session_id or 'unknown'}-{message_id or 'unknown'}"
    return flow_state.state_dir() / f"message-display-fence-{key}.json"


def _read_fence_state(path: Path) -> bool:
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("in_fence", False))
    except Exception:
        return False


def _write_fence_state(path: Path, in_fence: bool) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"in_fence": in_fence}), encoding="utf-8")
    except Exception:
        pass


def _clear_fence_state(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def shape_delta(delta: str, in_fence: bool) -> tuple:
    """Rewrite one delta's lines. Returns (shaped_text, new_in_fence_state)."""
    ends_with_newline = delta.endswith("\n")
    lines = delta.split("\n")
    if ends_with_newline:
        lines = lines[:-1]

    out_lines = []
    for line in lines:
        rewritten, in_fence = _rewrite_line(line, in_fence)
        out_lines.append(rewritten)

    shaped = "\n".join(out_lines)
    if ends_with_newline:
        shaped += "\n"
    return shaped, in_fence


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    delta = payload.get("delta", "")
    if not isinstance(delta, str) or delta == "":
        return

    session_id = payload.get("session_id", "")
    message_id = payload.get("message_id", "")
    final = bool(payload.get("final", False))

    state_path = _fence_state_path(session_id, message_id)
    in_fence = _read_fence_state(state_path)

    shaped, in_fence = shape_delta(delta, in_fence)

    if final:
        _clear_fence_state(state_path)
    else:
        _write_fence_state(state_path, in_fence)

    if shaped == delta:
        return

    # This swap never reaches the stored transcript, so the log is the only
    # record that the reader saw something other than what was written.
    if rewrite_log is not None:
        rewrite_log.record("message_display_audit", "tier1", delta, shaped,
                           session_id)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "MessageDisplay",
            "displayContent": shaped,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
