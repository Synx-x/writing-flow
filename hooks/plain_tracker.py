#!/usr/bin/env python3
# @schema-version: 1
# @portable: false
"""UserPromptSubmit hook: turn plain mode on or off from what the user typed.

Three shapes turn it on. The command `/plain on`. Plain speech naming the
mode, such as "switch to plain mode". A bare toggle verb next to "plain"
and "on" or "off", such as "turn plain on". The same three shapes turn it
off.

The bare-verb shape is deliberately close in wording to "the plain on the
table": it requires an actual toggle verb (turn, switch, set, toggle,
enable, disable) within a short window of both "plain" and "on"/"off", so
an ordinary sentence carrying those two words by coincidence stays inert.
Confirmed live 2026-09-12: a user typed exactly "turn plain on" and the
flag never moved, since the older speech pattern required the word "mode".

An off word wins over an on phrase, so "turn off plain mode" never
activates on the word "plain".
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from writing_flow.failopen import note_swallowed
except ImportError:
    def note_swallowed(hook, exc=None):
        return None

from writing_flow import plain_state
from writing_flow.scope import in_subagent

_OFF = re.compile(r"\b(off|stop|disable|deactivate|end)\b", re.IGNORECASE)
_SPEECH = re.compile(
    r"\bplain\s+mode\b"
    r"|\b(switch|change|go)\s+to\s+plain\b"
    r"|\b(turn|switch|toggle|set|enable|disable)\b[^.?!]{0,20}\bplain\b[^.?!]{0,15}\b(on|off)\b"
    r"|\b(turn|switch|toggle|set|enable|disable)\b[^.?!]{0,20}\b(on|off)\b[^.?!]{0,15}\bplain\b",
    re.IGNORECASE)


def decide(prompt: str):
    """Return True to activate, False to deactivate, None to leave alone."""
    text = (prompt or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("/plain"):
        return not bool(_OFF.search(lowered))
    if _SPEECH.search(lowered):
        return not bool(_OFF.search(lowered))
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # plain_state.py is one flat file with no session key, so a subagent
    # tripping _SPEECH here would flip a persistent, global flag for every
    # future session -- not just its own dispatch. A dispatch prompt that
    # merely quotes hook text containing "plain mode" was enough to do it.
    if in_subagent(data):
        return
    decision = decide(data.get("prompt", ""))
    if decision is None:
        return
    plain_state.set_active(decision)
    state = "on" if decision else "off"
    print(json.dumps({"systemMessage": f"plain mode {state}"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail open, but leave a trace: a crash here looked like a clean run.
        note_swallowed("plain_tracker", exc)
