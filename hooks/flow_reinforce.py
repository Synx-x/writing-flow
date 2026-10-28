#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""
UserPromptSubmit hook: reinforce writing-flow rules on every turn.

The writing-flow output style injects once at session start, but other hooks
inject competing directives every turn. The style decays across long sessions:
long-runway findings rise from 1.36 to 1.95 per 100 sentences. This hook
re-emits a short reminder on every UserPromptSubmit, the caveman model.

Resolves the style file at runtime from settings.json, so edits to writing-flow
propagate without stale hook copies. Silent on errors — never blocks a turn.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow.scope import in_subagent
from writing_flow.paths import claude_code_dir, home as kit_home, state_dir
from writing_flow.phase import read_current_phase
from writing_flow.runtime import HarnessRuntime

# Plain mode is optional. A missing module leaves the flow reminder in
# charge rather than breaking the turn.
try:
    from writing_flow import plain_state
except Exception:
    plain_state = None

try:
    from writing_flow import config as local_kit
except ImportError:
    local_kit = None


def _get_style_path() -> Path | None:
    """The active style file, or None. See lib/output_style.py."""
    try:
        from writing_flow import output_style
    except ImportError:
        return None
    return output_style.active_style_path()


def _style_unset() -> bool:
    """True when Claude Code's settings.json selects no output style."""
    try:
        settings = json.loads((claude_code_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return not (isinstance(settings, dict) and settings.get("outputStyle"))


def _extract_reminder(style_path: Path) -> str | None:
    """Extract a compact 40-70 word reminder from style file.

    Reads the self-check section (lines starting at "## Self-check")
    and composes a concise reminder covering the five key checks.
    Returns None if extraction fails. No error output.
    """
    try:
        content = style_path.read_text(encoding="utf-8")

        start_idx = content.find("## Self-check")
        if start_idx == -1:
            return None

        reminder = (
            "FLOW CHECK — old first, new last. Topic slot (first eight words) "
            "holds backward-linking information. Reach verb fast. First sentence "
            "names what paragraph develops. Previewed concepts return verbatim, "
            "not synonyms. End units on point, not hedge. One anchor per paragraph."
        )
        return reminder

    except Exception:
        return None


def _is_enabled() -> bool:
    """Check if hook is enabled in local config."""
    if local_kit is None:
        return True

    try:
        cfg = local_kit.hook_config("flow_reinforce")
        if cfg.get("enabled") is False:
            return False
    except Exception:
        pass

    return True


def _long_deliverable_turn(hook_data: dict) -> bool:
    """True when this turn is the shape that fails the flow rules.

    Measured 2026-09-11: final replies scored 43% clean against 96% for
    mid-turn narration. Short status lines pass on their own. The long
    synthesis at the end of a plan, verify or meta turn is what drifts, and
    the chat gate allows one block, so the first draft is the only draft.
    """
    runtime = HarnessRuntime.from_event(hook_data)
    phase_data = read_current_phase(runtime.state_dir, runtime.session_id)
    if not phase_data:
        return False
    stage = str(phase_data.get("stage", "")).lower()
    try:
        complexity = int(phase_data.get("complexity", 0))
    except (TypeError, ValueError):
        complexity = 0
    return stage in ("plan", "verify", "meta", "wrap_up") or complexity >= 6


SHAPE_RULES = (
    "SHAPE THIS REPLY BEFORE WRITING IT. Pick each paragraph's one anchor and "
    "open most of its sentences on that anchor. Lead with the answer, then the "
    "evidence. Reach the verb within eight words. Close each section on the "
    "point, never on a hedge. Gloss a term the first time you name it."
)

# Issue #60: a session with no outputStyle got no reminder and no sign the
# hook sat idle. The issue asks for a built-in reminder, which this is.
DEFAULT_REMINDER = (
    "WRITING. Lead with the answer. Put the familiar subject first and reach "
    "the verb within eight words. Give each paragraph one point, stated in "
    "its first sentence. Gloss a technical term the first time you name it. "
    "Close on what the reader must act on, not on a hedge."
)

PLAIN_REMINDER = (
    "PLAIN MODE. Sentences run to 20 words. Paragraphs run 2 to 4 "
    "sentences and 60 words. Chain up to 4 paragraphs, one part each, and "
    "put the thing the reader must not miss in the last one. Gloss a "
    "technical term once, then use it bare. Copy code and paths exactly."
)


def _emit(reminder: str) -> None:
    """One envelope for both reminders, so neither path can drift into
    printing bare text where the runtime expects JSON."""
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": reminder,
            }
        }))
    except Exception:
        pass


def main() -> int:
    # A payload that does not parse gets no reminder. Fail open, silently.
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    if in_subagent(data):
        return 0

    if not _is_enabled():
        return 0

    # Plain mode replaces this reminder rather than adding to it. The flow
    # reminder names topic slots and anchors, a shape the plain rules do not
    # use. This sits ahead of the style lookup on purpose, since plain mode
    # holds whether or not writing-flow is the selected style.
    # The short plain reminder waits until plain_inject has sent the full
    # rules. flow_reinforce runs before plain_inject in PROMPT_HOOKS, so on the
    # first prompt the marker is absent and only the full rules go out.
    if plain_state is not None and plain_state.is_active():
        session_id = data.get("session_id", "")
        if session_id and plain_state.full_rules_sent_this_session(session_id):
            _emit(PLAIN_REMINDER)
        return 0

    style_path = _get_style_path()
    if style_path:
        reminder = _extract_reminder(style_path)
    elif _style_unset():
        reminder = DEFAULT_REMINDER
    else:
        # A selected style whose file does not resolve is a broken setting.
        # The default would hide it, so the hook stays silent.
        return 0
    if not reminder:
        return 0

    if _long_deliverable_turn(data):
        reminder = SHAPE_RULES + "\n\n" + reminder

    _emit(reminder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
