"""plain_inject: injects the full ruleset every turn while the mode is on."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_state

HOOK = ROOT / "hooks" / "plain_inject.py"


def _run(state_dir):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": "hello", "session_id": "s1"}),
        capture_output=True, text=True, env=env, timeout=10)


def test_silent_when_mode_is_off(tmp_path):
    result = _run(tmp_path)
    assert result.stdout.strip() == ""
    assert result.returncode == 0


def test_injects_rules_when_mode_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    result = _run(tmp_path)
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "20 words" in context
    assert "supersede" in context.lower()


def test_injection_carries_the_tracked_terms(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    result = _run(tmp_path)
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "subagent" in context


def test_missing_rules_file_fails_open(tmp_path, monkeypatch):
    """A missing ruleset must not block the turn."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(tmp_path)
    env["HARNESS_KIT_PLAIN_RULES"] = str(tmp_path / "nope.md")
    proc = subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"prompt": "hi"}),
                          capture_output=True, text=True, env=env, timeout=10)
    assert proc.returncode == 0
