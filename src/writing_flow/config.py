"""Configuration and bypass controls for writing-flow hooks."""
import json
import os
from datetime import datetime, timezone

from . import paths

BYPASSABLE_HOOKS = {"guard_style", "guard_flow", "subagent_style_audit", "response_audit"}
VERBOSITY_LEVELS = ("terse", "auto", "full")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"WRITING_FLOW_{name}", os.environ.get(f"HARNESS_KIT_{name}", default))


def config() -> dict:
    try:
        value = json.loads(paths.config_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def hook_config(hook_name: str) -> dict:
    hooks = config().get("hooks", {})
    value = hooks.get(hook_name, {}) if isinstance(hooks, dict) else {}
    return value if isinstance(value, dict) else {}


def hook_enabled(hook_name: str) -> bool:
    return hook_config(hook_name).get("enabled", True) is not False


def hook_verbosity(hook_name: str, default: str = "auto") -> str:
    value = hook_config(hook_name).get("verbosity", default)
    return value if value in VERBOSITY_LEVELS else default


def retro_fix_enabled() -> bool:
    if env("RETRO_FIX") == "0":
        return False
    return config().get("retro_fix_conformance", True) is not False


def bypass_release(hook_name: str, content: str = "", findings: int = 0) -> str | None:
    if hook_name not in BYPASSABLE_HOOKS:
        return None
    reason = None
    if env("BYPASS") == "1":
        reason = "WRITING_FLOW_BYPASS"
    elif config().get("bypass_all") is True:
        reason = "config:bypass_all"
    elif "[writing-flow-bypass]" in content or "[kit-bypass]" in content:
        reason = "content-marker"
    if reason is None:
        return None
    record = {"time": datetime.now(timezone.utc).isoformat(), "hook": hook_name,
              "reason": reason, "findings": findings}
    try:
        target = paths.state_dir() / "bypasses.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return reason


def record_revert(**record) -> None:
    """Journal a sweep change before the caller writes it."""
    try:
        target = paths.state_dir() / "reverts.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return
