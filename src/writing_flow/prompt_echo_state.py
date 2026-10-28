"""One-shot prompt-echo overrides in flow-state's target namespace."""
from . import flow_state


def override_path(session_id: str, target: str = ""):
    return flow_state.state_dir() / f"echo-override-{session_id or 'unknown'}-{flow_state.scope_key(target)}"


def take_override(session_id: str, target: str = "") -> str | None:
    path = override_path(session_id, target)
    try:
        reason = path.read_text(encoding="utf-8").strip()
        path.unlink()
        return reason or "no reason given"
    except OSError:
        return None
