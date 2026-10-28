#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""One record per change the harness made to what the user read.

A display-only rewrite never reaches the saved transcript. The transcript
keeps what the model wrote, and the screen showed something else. Without
this log, nothing records the difference, and a rewrite that changed the
meaning would leave no trace at all.

Writing here must never break a caller. Every failure is swallowed.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from . import flow_state


def log_path() -> Path:
    return flow_state.state_dir() / "plain_rewrites.jsonl"


def record(hook: str, rule: str, before: str, after: str,
           session_id: str = "") -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "hook": hook,
        "rule": rule,
        "before": before,
        "after": after,
    }
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except Exception:
        pass


def read_recent(limit: int = 20) -> list:
    try:
        lines = log_path().read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-limit:]
