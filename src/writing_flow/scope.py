"""Scope detection utilities for hook filtering."""
import json
import sys
from typing import Any


def in_subagent(data: dict[str, Any]) -> bool:
    """
    Return True if the stdin payload indicates a subagent context.

    Subagent context is detected by the presence of a non-empty agent_id
    or agent_type field in the payload.
    """
    if not data:
        return False
    agent_id = data.get("agent_id")
    agent_type = data.get("agent_type")
    return bool(agent_id or agent_type)


def read_payload() -> dict[str, Any] | None:
    """Read and parse JSON payload from stdin. Return None on parse error."""
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return None
