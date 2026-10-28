"""guard_doc_residue flags chat/decision narration in prose docs (non-blocking)."""
import json, os, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard_doc_residue.py"


def _run(file_path, env=None):
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(file_path)}})
    p = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                       capture_output=True, env={**os.environ, **(env or {})})
    return p.stdout.strip()


def test_flags_decision_residue(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("The plugin is named harness-kit (locked 2026-06-26).\n"
                 "armature reserved per user decision. My lean is to keep it.\n", encoding="utf-8")
    out = _run(f)
    assert out, "expected residue context"
    data = json.loads(out)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "DOC RESIDUE" in ctx
    assert "dated decision stamp" in ctx or "decision narration" in ctx


def test_clean_doc_no_output(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("# harness-kit\n\nThe repo name is harness-kit. The command is /scaffold.\n", encoding="utf-8")
    assert _run(f) == ""


def test_override_token(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("user decision: keep it. [residue-ok]\n", encoding="utf-8")
    assert _run(f) == ""


def test_env_override(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("we decided to lock the name.\n", encoding="utf-8")
    assert _run(f, env={"HARNESS_KIT_ALLOW_RESIDUE": "1"}) == ""


def test_non_prose_skipped(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("# user decision: we decided this\n", encoding="utf-8")
    assert _run(f) == ""
