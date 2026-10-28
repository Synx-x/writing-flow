#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Shared transcript inspection utilities for Claude Code hooks.

Provides helpers for reading session JSONL transcripts to extract
tool usage context. Used by Stop hooks (response_audit) and
PreToolUse hooks (workflow_detect) to understand what happened
earlier in the current turn without requiring a separate state file.
"""

import json


def get_current_turn_tools(transcript_path: str) -> tuple[set, dict]:
    """Get tools called in the current turn from session transcript.

    Finds the last real user message (not a tool_result), then collects
    all tool_use blocks in assistant messages after that point.

    Args:
        transcript_path: Path to the session JSONL transcript file.

    Returns:
        (tool_names, tool_inputs) where:
        - tool_names: set of tool name strings called this turn
        - tool_inputs: dict mapping tool_name -> list of input dicts
    """
    records = []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return set(), {}

    # Find the index of the last real user message.
    # Real = type "user" with content that is not exclusively tool_results.
    last_user_idx = -1
    for i, rec in enumerate(records):
        if rec.get("type") != "user":
            continue
        content = rec.get("message", {}).get("content", [])
        if isinstance(content, str):
            last_user_idx = i
            continue
        if isinstance(content, list):
            has_real = any(
                isinstance(block, dict) and block.get("type") != "tool_result"
                for block in content
            )
            if has_real:
                last_user_idx = i

    if last_user_idx == -1:
        return set(), {}

    # Collect tool_use blocks from assistant messages after last_user_idx.
    tool_names: set = set()
    tool_inputs: dict = {}
    for rec in records[last_user_idx + 1:]:
        if rec.get("type") != "assistant":
            continue
        content = rec.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                if name:
                    tool_names.add(name)
                    tool_inputs.setdefault(name, []).append(block.get("input", {}))

    return tool_names, tool_inputs
