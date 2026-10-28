#!/usr/bin/env python3
"""Run one shared harness-kit hook against a normalized Codex event."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from events import normalize_event, split_patch_event


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from writing_flow.config import env as config_env
HOOKS = ROOT / "hooks"


def _telemetry_path() -> Path:
    return Path(
        config_env("TELEMETRY_LOG", str(Path(tempfile.gettempdir()) / "writing-flow-telemetry.jsonl"))
    )


def _log(hook_name: str, event: dict) -> None:
    try:
        path = _telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "harness": "codex",
                "hook": hook_name,
                "event": event.get("hook_event_name", ""),
                "tool": event.get("tool_name", ""),
            }) + "\n")
    except Exception:
        pass


def _codex_output(stdout: str, event_name: str) -> str:
    """Make legacy Claude hook output safe for Codex's JSON hook contract.

    Claude-compatible hooks may emit a plain-text advisory. Codex expects each
    non-empty hook response to be JSON, so preserve valid JSON and wrap legacy
    text as additional context instead of letting Codex reject the response.
    """

    if not stdout.strip():
        return ""
    try:
        json.loads(stdout)
        return stdout
    except json.JSONDecodeError:
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": stdout.strip(),
            }
        }) + "\n"


def _codex_output_with_stderr(stdout: str, stderr: str, event_name: str) -> str:
    """Keep actionable legacy stderr visible as Codex model context."""
    output = stdout.strip()
    diagnostics = stderr.strip()
    if output and diagnostics:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            specific = parsed.setdefault("hookSpecificOutput", {})
            if isinstance(specific, dict):
                current = str(specific.get("additionalContext", "")).strip()
                specific["additionalContext"] = "\n\n".join(
                    x for x in (current, diagnostics) if x
                )
                return json.dumps(parsed) + "\n"
        output = f"{output}\n\n{diagnostics}"
    elif diagnostics:
        output = diagnostics
    return _codex_output(output, event_name)


def _denies(output: str) -> bool:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    specific = parsed.get("hookSpecificOutput") or {}
    return (parsed.get("decision") == "block"
            or (isinstance(specific, dict) and specific.get("permissionDecision") == "deny"))


def _merge_context(outputs: list[str]) -> str:
    """Join the advisories of several per-file runs into one Codex response."""
    outputs = [o for o in outputs if o.strip()]
    if len(outputs) < 2:
        return outputs[0] if outputs else ""
    merged = json.loads(outputs[0])
    specific = merged.setdefault("hookSpecificOutput", {})
    parts = [str(specific.get("additionalContext", "")).strip()]
    for output in outputs[1:]:
        other = json.loads(output).get("hookSpecificOutput") or {}
        parts.append(str(other.get("additionalContext", "")).strip())
    specific["additionalContext"] = "\n\n".join(p for p in parts if p)
    return json.dumps(merged) + "\n"


def _run(hook: Path, event: dict) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
    )
    output = _codex_output_with_stderr(
        result.stdout, result.stderr, event.get("hook_event_name", "")
    )
    return result.returncode, output, result.stderr


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: run_hook.py <hook_name>", file=sys.stderr)
        return 1

    # The registration is intentionally broad because Codex's hook matcher
    # receives an internal tool label that differs from the response item
    # label. Never run the Codex adapter in a Claude process.
    if not os.environ.get("CODEX_THREAD_ID") and not os.environ.get("CODEX_HOME"):
        return 0

    hook_name = sys.argv[1]
    try:
        raw = json.load(sys.stdin)
    except Exception:
        return 0

    event = normalize_event(raw)
    os.environ.setdefault("WRITING_FLOW_HARNESS", "codex")
    os.environ.setdefault("WRITING_FLOW_PLUGIN_ROOT", str(ROOT))
    _log(hook_name, event)
    hook = HOOKS / f"{hook_name}.py"
    if not hook.exists():
        return 0

    # A patch can touch several files. Each hook judges one file, so run it
    # once per file and let any block stand for the whole patch.
    runs = [_run(hook, single) for single in split_patch_event(event)]
    blocked = next((r for r in runs if r[0] != 0), None)
    if blocked is None:
        blocked = next((r for r in runs if _denies(r[1])), None)
    if blocked is not None:
        code, output, stderr = blocked
    else:
        code, output, stderr = 0, _merge_context([r[1] for r in runs]), ""
    if output:
        print(output, end="")
    if code != 0 and stderr:
        print(stderr, end="", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
