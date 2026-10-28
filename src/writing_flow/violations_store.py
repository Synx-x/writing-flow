"""Session-scoped storage for response_audit.py's next-turn violation feedback.

Was one global path with no session_id in it. Any process hitting
UserPromptSubmit next, including a background subagent's own first turn,
could consume a violation record left by an unrelated session's prior
response and "correct" a violation it never wrote. Confirmed live: three
background subagent runs each replied to this notice instead of returning
their actual task output.
"""
from pathlib import Path

from .paths import claude_code_dir as claude_dir, state_dir

# CLAUDE_STATE_DIR redirects the record the way it redirects the flow log, so
# a test run leaves nothing under the real home. HARNESS_KIT_STATE_DIR is
# accepted alongside it, matching lib/harness_runtime.py's own precedence.
#
# The legacy path used Path.home() directly and took no override. On Windows
# Path.home() reads USERPROFILE and ignores HOME, so a test that redirected
# only HOME cleaned up the real profile's file instead of the fixture's, and
# four tests in test_violation_feedback.py failed on that runner alone.
VIOLATIONS_DIR = state_dir()
LEGACY_VIOLATIONS_FILE = claude_dir() / ".last_violations.json"


def violations_file_for(session_id: str) -> Path:
    return VIOLATIONS_DIR / f"last_violations_{session_id or 'unknown'}.json"
