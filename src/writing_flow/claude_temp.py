"""Detect paths under Claude Code session temp directories.

Claude Code keeps session state under <tempdir>/claude-<uid>/, scoped per
project and session. Files the agent writes there are internal, not product
source. completion_gate.py checks these to exclude scratchpad edits.
bash_write_router.py checks to skip validation of raw output and logs the
agent never authored.
"""
import os
from . import paths
import re
import tempfile
from pathlib import Path

__all__ = ["is_claude_temp_root", "is_claude_scratchpad", "is_machine_path"]


def is_claude_temp_root(file_path: str) -> bool:
    """True for any path under <tempdir>/claude-<uid>/ at any depth.
    
    Paths are normalized to forward-slash form before matching, to keep
    Windows paths and POSIX paths in one code path. Windows: backslashes
    and drive letters are converted. POSIX: unchanged.
    """
    try:
        norm = str(file_path).replace("\\", "/")
        if not norm.startswith("/") and not re.match(r"^[A-Za-z]:/", norm):
            return False
        roots = {str(tempfile.gettempdir()).replace("\\", "/").rstrip("/"), "/tmp"}
        for root in roots:
            if not norm.lower().startswith(root.lower() + "/"):
                continue
            parts = [p for p in norm[len(root) + 1:].split("/") if p]
            if parts and re.match(r"^claude-\d+$", parts[0]):
                return True
    except Exception:
        return False
    return False


def is_claude_scratchpad(file_path: str) -> bool:
    """True only for a Claude Code session scratchpad, not a bare /tmp path.
    
    The real shape is <tempdir>/claude-<uid>/<project>/<session-id>/scratchpad/...
    A plain prefix match on /tmp would also exclude test fixtures under
    pytest tmp_path, which lives under /tmp for isolation, not because it is
    scratch. Require both the claude-<uid> segment and the scratchpad segment
    so only the real shape matches.
    """
    try:
        norm = str(file_path).replace("\\", "/")
        if not norm.startswith("/") and not re.match(r"^[A-Za-z]:/", norm):
            return False
        roots = {str(tempfile.gettempdir()).replace("\\", "/").rstrip("/"), "/tmp"}
        for root in roots:
            if not norm.lower().startswith(root.lower() + "/"):
                continue
            parts = [p for p in norm[len(root) + 1:].split("/") if p]
            if parts and re.match(r"^claude-\d+$", parts[0]) and "scratchpad" in parts:
                return True
    except Exception:
        return False
    return False


def is_machine_path(file_path: str) -> bool:
    """True for a file no person reads as prose: the kit's own state directory,
    such as an agent brief or a log, or Claude Code's session temp root.

    On 2026-09-23 guard_style blocked a hand-written dispatch brief under
    ~/.claude/state/agent_briefs for plain-mode paragraph caps.
    """
    if is_claude_temp_root(file_path):
        return True
    try:
        from . import paths
        state = str(paths.state_dir()).replace("\\", "/").rstrip("/").lower() + "/"
        return str(file_path).replace("\\", "/").lower().startswith(state)
    except Exception:
        return False
