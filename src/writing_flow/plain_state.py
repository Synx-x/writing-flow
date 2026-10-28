#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""State for plain mode: the on/off flag, and which terms already carry a
gloss in this session.

Both live under CLAUDE_STATE_DIR so a test can redirect them. The flag is a
whole-file JSON object rather than a bare marker, so a later field needs no
migration.

The flag is one flat file with no session key and no expiry. Once
set_active(True) runs, the mode stays on across every later session until
something calls set_active(False). The user asked for "default on" after
one session of live use. The flag already persists forever, so that ask
needs no code change, only leaving the flag set to true.

A missing or corrupt file still fails open to off, not on. A fresh install
or a test's own isolated state directory must never come up in plain mode
by surprise. Only an explicit set_active(True) call may turn it on.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from . import flow_state


def flag_path() -> Path:
    return flow_state.state_dir() / "plain-active.json"


def is_active() -> bool:
    try:
        data = json.loads(flag_path().read_text(encoding="utf-8"))
        return bool(data.get("active", False))
    except Exception:
        return False


def set_active(on: bool) -> None:
    path = flag_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"active": bool(on)}), encoding="utf-8")
    except Exception:
        pass


def gloss_path(session_id: str) -> Path:
    return flow_state.state_dir() / f"plain-glossed-{session_id or 'unknown'}.json"


def glossed_terms(session_id: str) -> set:
    try:
        data = json.loads(gloss_path(session_id).read_text(encoding="utf-8"))
        return set(data.get("terms", []))
    except Exception:
        return set()


def record_glossed(session_id: str, terms: set) -> None:
    if not terms:
        return
    merged = glossed_terms(session_id) | set(terms)
    path = gloss_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"terms": sorted(merged)}), encoding="utf-8")
    except Exception:
        pass


def full_rules_sent_path(session_id: str) -> Path:
    """Path to the per-session full rules sent marker."""
    return flow_state.state_dir() / f"plain-rules-sent-{session_id or 'unknown'}.json"


def full_rules_sent_this_session(session_id: str) -> bool:
    """True if full plain rules were sent earlier in this session."""
    try:
        data = json.loads(full_rules_sent_path(session_id).read_text(encoding="utf-8"))
        return bool(data.get("sent", False))
    except Exception:
        return False


def mark_full_rules_sent(session_id: str, prompt_hash: str = "") -> None:
    """Record that full plain rules were sent in this session."""
    path = full_rules_sent_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sent": True, "prompt_hash": prompt_hash}), encoding="utf-8")
    except Exception:
        pass


def reset_full_rules_sent(session_id: str) -> None:
    """Reset full rules flag to allow re-emission after compaction."""
    path = full_rules_sent_path(session_id)
    try:
        path.write_text(json.dumps({"sent": False}), encoding="utf-8")
    except Exception:
        pass
