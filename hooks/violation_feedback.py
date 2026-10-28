#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""UserPromptSubmit hook: inject feedback from previous response's AI pattern violations.

Reads violations written by response_audit.py (Stop hook) and injects them as
context for the current turn. Deletes the file after reading (one-shot).

Session-scoped and subagent-gated. response_audit.py never writes a record
for a subagent's own response, it skips subagent turns outright, so this hook
has nothing of its own to correct inside a subagent and must not read at all
there. Confirmed live: an unscoped single global file let a background
subagent's own first turn consume the parent session's leftover violation
record and reply to it instead of returning its actual task output, three
times in one planning pass.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow.scope import in_subagent, read_payload
from writing_flow.violations_store import violations_file_for, LEGACY_VIOLATIONS_FILE


def main() -> None:
    # One-time cleanup, best effort. A stale copy from before this fix
    # existed would otherwise sit there forever and nothing would ever read
    # it, since every path below now reads the session-scoped file instead.
    LEGACY_VIOLATIONS_FILE.unlink(missing_ok=True)

    data = read_payload()
    if not data or in_subagent(data):
        sys.exit(0)

    target = violations_file_for(data.get("session_id", ""))
    if not target.exists():
        sys.exit(0)

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        target.unlink(missing_ok=True)
        sys.exit(0)

    violations = payload.get("violations", [])
    if not violations:
        target.unlink(missing_ok=True)
        sys.exit(0)

    target.unlink(missing_ok=True)

    grounded = [v for v in violations if
                v["detail"].startswith("Grounded-response") or
                v["detail"].startswith("Cited URLs")]
    style = [v for v in violations if v not in grounded]

    context_parts = []

    if grounded:
        grounded_items = "\n".join(f"  - [{v['severity']}] {v['detail']}" for v in grounded)
        context_parts.append(
            f"GROUNDING FAILURE (previous turn):\n"
            f"{grounded_items}\n"
            f"Fix in this response: verify claims before asserting, or explicitly label "
            f"as training knowledge / best guess."
        )

    if style:
        style_items = "\n".join(f"  - [{v['severity']}] {v['detail']}" for v in style[:5])
        context_parts.append(
            f"RESPONSE AUDIT (previous turn):\n"
            f"Your last response had these AI writing violations:\n"
            f"{style_items}\n"
            f"Apply corrections in this response. Do not mention the audit to the user."
        )

    if not context_parts:
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n\n".join(context_parts),
        }
    }))


if __name__ == "__main__":
    main()
