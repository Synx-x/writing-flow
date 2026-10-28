import json
import os
import subprocess
import sys
from pathlib import Path

from writing_flow import output_style

ROOT = Path(__file__).resolve().parents[1]


def test_namespaced_style_reaches_flow_reinforce(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"outputStyle": "writing-flow:writing-flow"}')
    monkeypatch.setenv("WRITING_FLOW_HOME", str(home))
    output_style.chat_exemptions.cache_clear()
    path = output_style.active_style_path()
    assert path is not None and path.name == "writing-flow.md"
    event = json.dumps({"session_id": "edge-session", "cwd": str(tmp_path)})
    proc = subprocess.run([sys.executable, str(ROOT / "hooks/flow_reinforce.py")],
                          input=event, text=True, capture_output=True,
                          env={**os.environ, "WRITING_FLOW_HOME": str(home)})
    assert proc.returncode == 0
    assert proc.stdout.strip() or proc.stderr.strip()


def test_unwritable_state_dir_fails_open(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    target = tmp_path / "clean.md"
    event = {"tool_name": "Write", "tool_input": {"file_path": str(target),
             "content": "The system is ready."}, "session_id": "edge"}
    proc = subprocess.run([sys.executable, str(ROOT / "hooks/guard_style.py")],
                          input=json.dumps(event), text=True, capture_output=True,
                          env={**os.environ, "WRITING_FLOW_STATE_DIR": str(blocker / "state")})
    assert proc.returncode in (0, 2)
    assert "Traceback" not in proc.stderr


def test_unknown_phase_runs_grounding():
    from hooks import response_audit
    findings = response_audit.check_grounded_response(
        "The tool launched in 2024. It requires Python version 3.11.", set(), {}, phase="")
    assert findings
