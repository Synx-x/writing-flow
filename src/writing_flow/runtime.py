"""Normalize tool aliases and runtime fields from hook events."""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from . import paths

TOOL_ALIASES = {"shell": "Bash", "exec_command": "Bash", "command_execution": "Bash",
                "apply_patch": "Edit", "file_change": "Edit", "write_file": "Write",
                "read_file": "Read", "list_files": "Glob", "search_files": "Grep",
                "spawn_agent": "Agent", "collab_agent": "Agent"}


def canonical_tool_name(name: Any) -> str:
    raw = str(name or "")
    return TOOL_ALIASES.get(raw.lower(), raw)


def _first(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return ""


@dataclass(frozen=True)
class HarnessRuntime:
    name: str
    project_root: Path
    state_dir: Path
    session_id: str
    plugin_root: Path | None = None

    @classmethod
    def from_event(cls, event: dict[str, Any] | None = None):
        event = event or {}
        name = _first(event.get("harness"), os.environ.get("WRITING_FLOW_HARNESS"),
                      os.environ.get("HARNESS_KIT_HARNESS"), "claude").lower()
        project = Path(_first(event.get("cwd"), event.get("project_root"),
                              os.environ.get("CLAUDE_PROJECT_DIR"), Path.cwd())).expanduser()
        state = Path(_first(event.get("state_dir"), paths.state_dir())).expanduser()
        session = _first(event.get("session_id"), event.get("thread_id"),
                         os.environ.get("WRITING_FLOW_SESSION_ID"),
                         os.environ.get("HARNESS_KIT_SESSION_ID"), "unknown-session")
        plugin = _first(event.get("plugin_root"), os.environ.get("WRITING_FLOW_PLUGIN_ROOT"),
                        os.environ.get("HARNESS_KIT_PLUGIN_ROOT"),
                        os.environ.get("CLAUDE_PLUGIN_ROOT"))
        return cls(name, project, state, session, Path(plugin) if plugin else None)

    def is_claude(self) -> bool:
        return self.name == "claude"

    def is_codex(self) -> bool:
        return self.name == "codex"
