"""flow_reinforce swaps its reminder while plain mode is on.

The flow reminder names topic slots and anchors. Those describe a shape the
plain rules do not use, so sending both would contradict.

Plain mode behavior: full rules on first prompt via plain_inject, short
reminder on later prompts via flow_reinforce."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_state

HOOK = ROOT / "hooks" / "flow_reinforce.py"
PLAIN_INJECT = ROOT / "hooks" / "plain_inject.py"


def _run(state_dir, session_id="s1"):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": "explain this", "session_id": session_id}),
        capture_output=True, text=True, env=env, timeout=10)


def _run_plain_inject(state_dir, session_id="s1"):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(PLAIN_INJECT)],
        input=json.dumps({"prompt": "hello", "session_id": session_id}),
        capture_output=True, text=True, env=env, timeout=10)


def test_flow_silent_when_plain_is_on_first_prompt(tmp_path, monkeypatch):
    """flow_reinforce is silent on first prompt (plain_inject sends full rules)."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_plain_reminder_when_plain_is_on_after_full_rules(tmp_path, monkeypatch):
    """flow_reinforce emits short reminder on second prompt."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)

    # First: plain_inject sends full rules
    result1 = _run_plain_inject(tmp_path, session_id="s1")
    assert result1.returncode == 0

    # Second: flow_reinforce sends short reminder
    result2 = _run(tmp_path, session_id="s1")
    assert result2.returncode == 0
    payload = json.loads(result2.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "20 words" in context


def test_plain_reminder_never_names_flow_shapes(tmp_path, monkeypatch):
    """Plain mode reminder never names topic slots or anchors."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)

    # First: plain_inject sends full rules
    _run_plain_inject(tmp_path, session_id="s1")

    # Second: flow_reinforce sends short reminder
    result = _run(tmp_path, session_id="s1")
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "anchor" not in context.lower()
    assert "topic slot" not in context.lower()


def test_output_stays_valid_json(tmp_path, monkeypatch):
    """A bare print would emit text where the runtime expects JSON."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)

    # First: plain_inject
    _run_plain_inject(tmp_path, session_id="s1")

    # Second: flow_reinforce
    result = _run(tmp_path, session_id="s1")
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
