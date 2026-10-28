"""rewrite_log: one record per change the harness made to what the user read.

A display-only rewrite never reaches the saved transcript, so without this
log nothing anywhere records what was actually shown."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import rewrite_log

SWAPPED = "lever" + "age"


def test_record_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    rewrite_log.record("message_display_audit", "tier1", SWAPPED, "use", "s1")
    rows = rewrite_log.read_recent()
    assert len(rows) == 1
    assert rows[0]["before"] == SWAPPED
    assert rows[0]["after"] == "use"


def test_record_carries_every_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    rewrite_log.record("guard_style", "paragraph_cap", "long", "short", "s1")
    row = rewrite_log.read_recent()[0]
    for key in ("ts", "session_id", "hook", "rule", "before", "after"):
        assert key in row


def test_read_recent_returns_newest_last(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    rewrite_log.record("h", "r", "first", "a", "s1")
    rewrite_log.record("h", "r", "second", "b", "s1")
    rows = rewrite_log.read_recent()
    assert rows[-1]["before"] == "second"


def test_read_recent_honours_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    for i in range(10):
        rewrite_log.record("h", "r", str(i), "x", "s1")
    assert len(rewrite_log.read_recent(limit=3)) == 3


def test_missing_log_reads_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert rewrite_log.read_recent() == []


def test_corrupt_line_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    rewrite_log.record("h", "r", "good", "x", "s1")
    with rewrite_log.log_path().open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    rows = rewrite_log.read_recent()
    assert len(rows) == 1


def test_unwritable_log_does_not_raise(tmp_path, monkeypatch):
    """A logging failure must never break the hook that called it."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", "/proc/nonexistent-and-unwritable")
    rewrite_log.record("h", "r", "a", "b", "s1")
