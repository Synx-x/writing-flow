#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""PostToolUse hook (Write|Edit) for prose files (.md/.rst/.txt).

Flags conversation/decision residue: text that narrates the chat that produced the
doc instead of stating the fact. Generated docs and code comments should be generic,
focused, and to the point, not a transcript of the session.

Caught (high-signal) patterns:
  - dated decision stamps:      "locked 2026-06-26", "(user decision 2026-06-30)"
  - decision narration:         "user decision", "we decided/chose/agreed/discussed"
  - chat references:            "as discussed", "as we discussed"
  - second-person chat address: "per your", "you asked", "as you requested"
  - first-person opinion:       "my lean/pick/recommendation", "I recommend/lean/suggest"
  - conversational openers:     "let's", "honestly", "the catch is", "worth flagging"

Non-blocking: injects additionalContext so the agent rewrites to plain factual prose.
Skips files that document the writing rules themselves (self-reference). Override:
include [residue-ok] anywhere in the file, or set HARNESS_KIT_ALLOW_RESIDUE=1.
"""

import json
import os
import sys
from pathlib import Path

# Import shared prose rules
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config as wf_config
from writing_flow.prose_rules import scan as scan_prose

# Stdlib only. A from-import so sync_hooks.py ships it with this hook.
from writing_flow.edit_scope import blank_unchanged, changed_lines, edit_offset  # noqa: E402

PROSE_EXTS = (".md", ".rst", ".txt")

# Files whose JOB is to document these patterns — don't flag them.
SELF_REF = ("guard_doc_residue", "writing-style", "avoid-ai-writing", "CHANGELOG", "changelog", "prose_rules")


def main():
    if wf_config.env("ALLOW_RESIDUE") == "1":
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)
    fp = (data.get("tool_input") or {}).get("file_path", "")
    if not fp or Path(fp).suffix.lower() not in PROSE_EXTS:
        sys.exit(0)
    if any(tok in fp for tok in SELF_REF):
        sys.exit(0)
    try:
        text = Path(fp).read_text(encoding="utf-8", errors="replace")
    except OSError:
        sys.exit(0)
    if "[residue-ok]" in text:
        sys.exit(0)
    # An Edit reports only the lines it changed, numbered as file lines. The
    # rest of the file is debt this edit did not write. See lib/edit_scope.py.
    tin = data.get("tool_input") or {}
    if data.get("tool_name") == "Edit":
        new = tin.get("new_string", "")
        keep = changed_lines(tin.get("old_string", ""), new)
        offset = edit_offset(text, new)
        text = blank_unchanged(new, keep) if offset is None else blank_unchanged(text, keep, offset)

    # Use shared prose rules for residue patterns
    findings = scan_prose(text, kinds=("residue",), filepath=fp)
    if not findings:
        sys.exit(0)

    shown = []
    for i, f in enumerate(findings[:12], 1):
        shown.append(f"  line {f['line']}: {f['label']} -> \"{f['match']}\"")

    more = f"\n  ...and {len(findings) - len(shown)} more" if len(findings) > len(shown) else ""
    msg = (
        "DOC RESIDUE (guard_doc_residue): this file narrates the chat/decision process "
        "instead of stating facts. Rewrite as generic, focused prose — drop dated decision "
        "stamps, first/second-person, and 'we decided' narration. Keep the fact, cut the story.\n"
        + "\n".join(shown) + more
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": msg,
    }}))
    sys.exit(0)


if __name__ == "__main__":
    main()
