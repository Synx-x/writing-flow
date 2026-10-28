"""Read session phase state when a classifier has written it."""
import json
from pathlib import Path


def get_phase_file_path(state_dir: Path, session_id: str | None) -> Path:
    root = Path(state_dir)
    if not session_id:
        return root / "current_phase.json"
    return root / "phase" / f"current_phase_{session_id}.json"


def read_current_phase(state_dir: Path, session_id: str | None) -> dict:
    active = session_id if session_id and session_id != "unknown-session" else None
    try:
        value = json.loads(get_phase_file_path(Path(state_dir), active).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}
