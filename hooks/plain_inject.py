#!/usr/bin/env python3
# @schema-version: 1
# @portable: false
"""UserPromptSubmit hook: inject the plain ruleset while the mode is on.

The full rules go in every turn, not a summary. The caveman plugin records
why in its own caveman-activate.js. A short summary drifted back to verbose
output once compaction pruned it. Full rules with examples held.

The term list comes from plain_rules rather than the markdown, so the list
the model reads and the list the checker enforces are one list.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from writing_flow.failopen import note_swallowed
except ImportError:
    def note_swallowed(hook, exc=None):
        return None

from writing_flow import config as wf_config
from writing_flow import plain_rules
from writing_flow import plain_state
from writing_flow.scope import in_subagent

DEFAULT_RULES = (Path(__file__).parent.parent
                 / "skills" / "plain-mode" / "RULES.md")


def rules_path() -> Path:
    return Path(wf_config.env("PLAIN_RULES", str(DEFAULT_RULES)))


def build_context(session_id: str) -> str:
    """Build full rules on first prompt, empty on later prompts."""
    if plain_state.full_rules_sent_this_session(session_id):
        return ""

    body = rules_path().read_text(encoding="utf-8")
    terms = ", ".join(plain_rules.TRACKED_TERMS)
    return (
        "PLAIN MODE IS ON. These rules supersede the writing-flow output "
        "style for this reply.\n\n"
        + body
        + f"\n\nTerms needing a gloss on first mention: {terms}\n"
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if in_subagent(data):
        return
    if not plain_state.is_active():
        return
    session_id = data.get("session_id", "")
    try:
        context = build_context(session_id)
    except Exception:
        return
    if not context:
        return
    plain_state.mark_full_rules_sent(session_id)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail open, but leave a trace: a crash here looked like a clean run.
        note_swallowed("plain_inject", exc)
