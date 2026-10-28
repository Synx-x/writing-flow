"""Best-effort journal for errors that hooks intentionally swallow."""
import json
from datetime import datetime, timezone

from . import paths


def note_swallowed(where: str, exc: BaseException) -> None:
    try:
        target = paths.state_dir() / "swallowed.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"time": datetime.now(timezone.utc).isoformat(), "where": where,
                  "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return
