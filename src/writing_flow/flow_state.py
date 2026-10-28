"""Session- and target-scoped state for the two flow gates.

violations_store.py fixed this bug class once already. A state path with no
session id in it let an unrelated process consume a record it never wrote.
The flow override marker and the repeat-block counter carried the same
defect one level finer. Both keyed on session id alone, and one session runs
more than one writer: guard_flow.py sees every subagent's file writes and
response_audit.py sees the chat reply, all under the same id.

Confirmed live on 2026-09-10. A retrospective subagent wrote an override for
its own document. That slot was the only one a second subagent could have
drawn from, and the second subagent took five blocks in a row with no escape
left to spend.

Scoping on the target as well as the session gives each writer its own slot.
A file write scopes to its path. A chat reply scopes to the literal "chat".

This module owns both pieces of state because they answer the same question,
"has this writer already argued about this passage". violations_store.py
stays separate: it owns the next-turn violation record, which is one per
session by design.
"""
import hashlib
import json
import os
from pathlib import Path

from . import paths

CHAT_TARGET = "chat"


def state_dir() -> Path:
    """Read the env each call so a test can redirect state after import."""
    return paths.state_dir()


def scope_key(target: str = "") -> str:
    """A short, stable token for one writer's target.

    An empty target means the chat reply. Any other value is a file path,
    hashed so the slot name stays one path segment on every filesystem.
    """
    if not target or target == CHAT_TARGET:
        return CHAT_TARGET
    return hashlib.sha256(target.encode("utf-8", "replace")).hexdigest()[:12]


def override_path(session_id: str, target: str = "") -> Path:
    return state_dir() / f"flow-override-{session_id or 'unknown'}-{scope_key(target)}"


def take_override(session_id: str, target: str = "", allowed: bool = True) -> str | None:
    """Consume a one-shot override and return its reason.

    The model writes this file when it judges a finding wrong for the passage
    in hand. Consuming it here keeps the escape single use, so an override
    covers one write rather than opening the gate for the session.
    """
    if not allowed:
        return None
    marker = override_path(session_id, target)
    try:
        if not marker.is_file():
            return None
        reason = marker.read_text(encoding="utf-8").strip()
        marker.unlink()
        return reason or "no reason given"
    except Exception:
        return None


def discard_override(session_id: str, target: str = "", allowed: bool = True) -> None:
    """Drop an override that never got applied.

    A clean pass means the reason never matched any finding. Left on disk, it
    would silently forgive whatever the next unrelated block turns out to be.
    """
    if not allowed:
        return
    try:
        override_path(session_id, target).unlink()
    except OSError:
        pass


def block_count_path(session_id: str, target: str = "") -> Path:
    return state_dir() / f"flow-blocks-{session_id or 'unknown'}-{scope_key(target)}.json"


def read_block_count(session_id: str, target: str = "") -> int:
    try:
        raw = block_count_path(session_id, target).read_text(encoding="utf-8")
        return int(json.loads(raw).get("count", 0))
    except (OSError, ValueError, AttributeError):
        return 0


def write_block_count(session_id: str, count: int, target: str = "") -> None:
    try:
        path = block_count_path(session_id, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"count": count}), encoding="utf-8")
    except OSError:
        pass


def reset_block_count(session_id: str, target: str = "") -> None:
    try:
        block_count_path(session_id, target).unlink()
    except OSError:
        pass
