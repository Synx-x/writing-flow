"""plain_tracker: turns plain mode on and off from what the user typed."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
sys.path.insert(0, str(ROOT / "hooks"))

from writing_flow import plain_state
import plain_tracker

HOOK = ROOT / "hooks" / "plain_tracker.py"


def _run(prompt, state_dir):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt, "session_id": "s1"}),
        capture_output=True, text=True, env=env, timeout=10)


def test_slash_on_activates(tmp_path, monkeypatch):
    _run("/plain on", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is True


def test_slash_off_deactivates(tmp_path, monkeypatch):
    _run("/plain on", tmp_path)
    _run("/plain off", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is False


def test_plain_speech_activates(tmp_path, monkeypatch):
    _run("switch to plain mode please", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is True


def test_plain_speech_deactivates(tmp_path, monkeypatch):
    _run("/plain on", tmp_path)
    _run("turn off plain mode", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is False


def test_unrelated_prompt_leaves_flag_alone(tmp_path, monkeypatch):
    _run("explain the plain truth about caching", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is False


def test_bare_turn_plain_on_activates(tmp_path, monkeypatch):
    """Observed live: a user said exactly this and the flag never moved,
    since the old speech pattern required the word 'mode'."""
    _run("turn plain on", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is True


def test_bare_turn_on_plain_activates(tmp_path, monkeypatch):
    _run("turn on plain", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is True


def test_bare_turn_plain_off_deactivates(tmp_path, monkeypatch):
    _run("/plain on", tmp_path)
    _run("turn plain off", tmp_path)
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is False


def test_bare_plain_on_with_no_verb_stays_inert():
    """'plain on' with no toggle verb nearby is too close to ordinary text
    ('keep it plain on this page') to trigger safely."""
    assert plain_tracker.decide("plain on") is None


def test_plain_on_in_an_unrelated_sentence_is_ignored():
    """A bare 'plain on' clause is deliberately loose. Guard it with a
    boundary case: a real sentence carrying those two words by coincidence
    must not toggle anything."""
    assert plain_tracker.decide("the plain on the table looked old") is None


def test_malformed_stdin_fails_open(tmp_path):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(tmp_path)
    proc = subprocess.run([sys.executable, str(HOOK)], input="not json",
                          capture_output=True, text=True, env=env, timeout=10)
    assert proc.returncode == 0
