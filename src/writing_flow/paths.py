"""Home, config and state paths owned by writing-flow."""
import os
from pathlib import Path

HARNESS_STATE_DIRS = {"claude": ".claude", "codex": ".codex"}


def home() -> Path:
    override = os.environ.get("WRITING_FLOW_HOME") or os.environ.get("HARNESS_KIT_HOME")
    return Path(override).expanduser() if override else Path.home()


def claude_code_dir() -> Path:
    return home() / ".claude"


def config_path() -> Path:
    override = os.environ.get("WRITING_FLOW_CONFIG") or os.environ.get("HARNESS_KIT_CONFIG")
    return Path(override).expanduser() if override else claude_code_dir() / "writing-flow" / "config.json"


def state_override() -> Path | None:
    override = os.environ.get("WRITING_FLOW_STATE_DIR") or os.environ.get("HARNESS_KIT_STATE_DIR")
    return Path(override).expanduser() if override else None


def state_dir() -> Path:
    override = state_override()
    if override:
        return override
    harness = (os.environ.get("WRITING_FLOW_HARNESS") or os.environ.get("HARNESS_KIT_HARNESS") or "claude").lower()
    state_home = os.environ.get("CODEX_HOME") if harness == "codex" else None
    base = Path(state_home).expanduser() if state_home else home()
    return base / HARNESS_STATE_DIRS.get(harness, ".claude") / "writing-flow" / "state"


def claude_dir() -> Path:
    return claude_code_dir()
