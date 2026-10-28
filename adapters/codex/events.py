"""Normalize Codex hook payloads into harness-kit portable hook payloads.

This module deliberately contains no policy. It only translates event and
tool vocabulary at the harness boundary, keeping Claude behavior unchanged.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
from copy import deepcopy
from typing import Any


EVENT_MAP = {
    "preToolUse": "PreToolUse",
    "PreToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "PostToolUse": "PostToolUse",
    "sessionStart": "SessionStart",
    "SessionStart": "SessionStart",
    "sessionEnd": "SessionEnd",
    "SessionEnd": "SessionEnd",
    "stop": "Stop",
    "Stop": "Stop",
    "subagentStart": "SubagentStart",
    "SubagentStart": "SubagentStart",
    "subagentStop": "SubagentStop",
    "SubagentStop": "SubagentStop",
    "userPromptSubmit": "UserPromptSubmit",
    "UserPromptSubmit": "UserPromptSubmit",
}

TOOL_MAP = {
    "shell": "Bash",
    "exec_command": "Bash",
    "command_execution": "Bash",
    "apply_patch": "Edit",
    "file_change": "Edit",
    "write_file": "Write",
    "read_file": "Read",
    "list_files": "Glob",
    "search_files": "Grep",
    "spawn_agent": "Agent",
    "collab_agent": "Agent",
}


def _value(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+?)\s*$")


def _resolve(path: str, cwd: str) -> str:
    # Join in the style of the event's cwd, not the host's: a POSIX cwd stays POSIX on Windows.
    style = ntpath if re.match(r"^[A-Za-z]:", cwd) or "\\" in cwd else posixpath
    if cwd and not style.isabs(path):
        return style.normpath(style.join(cwd, path))
    return path


def parse_patch(patch: str, cwd: str = "") -> list[dict[str, str]]:
    """Split a Codex apply_patch envelope into one portable input per file.

    Codex sends the whole envelope in tool_input.command, with paths relative
    to cwd. An added file becomes a Write of its full content. An updated file
    becomes an Edit: old_string keeps the context and removed lines, new_string
    keeps the context and added lines, as a Claude Edit does. A deleted file
    becomes an Edit with no content, so path guards still see it.
    """

    files: list[dict[str, str]] = []
    current: dict[str, Any] | None = None
    for line in str(patch or "").splitlines():
        header = PATCH_FILE.match(line)
        if header:
            current = {"kind": header.group(1), "path": header.group(2), "body": []}
            files.append(current)
            continue
        move = PATCH_MOVE.match(line)
        if move and current is not None:
            current["move_from"] = current["path"]
            current["path"] = move.group(1)
            continue
        if current is not None and not line.startswith("***"):
            current["body"].append(line)

    out = []
    for item in files:
        body = item["body"]
        entry = {"file_path": _resolve(item["path"], cwd)}
        if item.get("move_from"):
            entry["move_from"] = _resolve(item["move_from"], cwd)
        if item["kind"] == "Add":
            entry["tool_name"] = "Write"
            entry["content"] = "\n".join(line[1:] for line in body if line.startswith("+"))
            entry["new_string"] = entry["content"]
        else:
            entry["tool_name"] = "Edit"
            old = [line[1:] for line in body if line[:1] in (" ", "-")]
            new = [line[1:] for line in body if line[:1] in (" ", "+")]
            entry["old_string"] = "\n".join(old)
            entry["new_string"] = "\n".join(new)
            entry["content"] = entry["new_string"]
        out.append(entry)
    return out


def split_patch_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one portable event per file that a Codex patch touches."""

    files = (event.get("tool_input") or {}).get("patch_files") or []
    if len(files) < 2:
        return [event]
    events = []
    for entry in files:
        single = deepcopy(event)
        single["tool_name"] = entry["tool_name"]
        tool_input = single["tool_input"]
        for key in ("file_path", "content", "old_string", "new_string", "move_from"):
            tool_input.pop(key, None)
        tool_input.update({k: v for k, v in entry.items() if k != "tool_name"})
        events.append(single)
    return events


def normalize_tool_name(name: Any) -> str:
    raw = str(name or "")
    return TOOL_MAP.get(raw, raw)


def normalize_tool_input(name: Any, tool_input: Any = None, cwd: str = "") -> dict[str, Any]:
    """Return the Claude-shaped tool_input expected by portable hooks."""

    if isinstance(tool_input, dict):
        result = deepcopy(tool_input)
    elif tool_input is None:
        result = {}
    else:
        result = {"command": str(tool_input)}

    codex_name = str(name or "")
    if codex_name in {"shell", "exec_command", "command_execution"}:
        command = _value(result, "command", "cmd", "content", default="")
        result.setdefault("command", command)
    elif codex_name in {"apply_patch", "file_change"}:
        patch = _value(result, "patch", "content", "diff", "command", default="")
        files = parse_patch(patch, cwd)
        if files:
            result["patch_files"] = files
            for key, value in files[0].items():
                if key != "tool_name":
                    result.setdefault(key, value)
            return result
        result.setdefault("file_path", _value(result, "path", "file_path", default=""))
        result.setdefault("content", patch)
        result.setdefault("new_string", patch)
    elif codex_name == "write_file":
        result.setdefault("file_path", _value(result, "path", "file_path", default=""))
        result.setdefault("content", _value(result, "content", "text", default=""))
    elif codex_name == "read_file":
        result.setdefault("file_path", _value(result, "path", "file_path", default=""))
    return result


def normalize_event(data: dict[str, Any]) -> dict[str, Any]:
    """Translate one Codex hook event to the portable hook schema."""

    source = deepcopy(data)
    source_event = _value(source, "hook_event_name", "event_name", "eventName", "event", default="")
    source_tool = _value(source, "tool_name", "toolName", "tool", "name", default="")
    normalized_tool = normalize_tool_name(source_tool)
    source_input = _value(source, "tool_input", "toolInput", "input", "args", default={})

    source["harness"] = "codex"
    source["hook_event_name"] = EVENT_MAP.get(str(source_event), str(source_event))
    source["cwd"] = _value(source, "cwd", "project_root", "projectRoot", default="")
    source["tool_input"] = normalize_tool_input(source_tool, source_input, source["cwd"])
    patch_files = source["tool_input"].get("patch_files") or []
    source["tool_name"] = patch_files[0]["tool_name"] if patch_files else normalized_tool
    source["session_id"] = _value(source, "session_id", "sessionId", "thread_id", "threadId", default="")
    return source
