"""plain_state: the flag that turns plain mode on, and the per-session record
of which terms already carry a gloss."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_state


def test_inactive_until_set(tmp_path, monkeypatch):
    """A fresh state directory, with no flag file yet, must never come up
    in plain mode by surprise. Only an explicit set_active(True) turns it
    on. Once it does, the flag has no expiry: it is on for every later
    session too, which is how the user's own "default on" request works,
    with no code change needed for it."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.is_active() is False


def test_set_active_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    assert plain_state.is_active() is True
    plain_state.set_active(False)
    assert plain_state.is_active() is False


def test_glossed_terms_start_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert plain_state.glossed_terms("s1") == set()


def test_glossed_terms_accumulate(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.record_glossed("s1", {"hook"})
    plain_state.record_glossed("s1", {"subagent"})
    assert plain_state.glossed_terms("s1") == {"hook", "subagent"}


def test_gloss_record_is_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.record_glossed("s1", {"hook"})
    assert plain_state.glossed_terms("s2") == set()


def test_unreadable_state_reads_as_inactive(tmp_path, monkeypatch):
    """Fail open. A corrupt flag must not turn the mode on or raise."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.flag_path().write_text("not json at all", encoding="utf-8")
    assert plain_state.is_active() is False


def test_active_flag_survives_a_second_independent_read(tmp_path, monkeypatch):
    """The flag has no session key and no expiry. Once one call turns it
    on, a later, unrelated call sees it on too, with no reset in between.
    This is the whole mechanism behind "default on" for every session
    after the one that turned it on."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    assert plain_state.is_active() is True
    assert plain_state.is_active() is True
