"""Bounded transcript readers: correctness + early-exit / tail perf.

These guard the fix for UserPromptSubmit hook timeouts caused by full-transcript
read_text() calls (see CHANGELOG 0.28.0). The perf assertions fail if either
helper regresses to a whole-file read.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
from writing_flow import transcript  # noqa: E402


def _tool_line(name):
    return '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"%s"}]}}' % name


def test_tail_lines_small_file(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(f"line{i}" for i in range(20)) + "\n", encoding="utf-8")
    assert transcript.tail_lines(str(f), 3) == ["line17", "line18", "line19"]


def test_tail_lines_missing_file(tmp_path):
    assert transcript.tail_lines(str(tmp_path / "nope.jsonl"), 5) == []


def test_tail_lines_large_file_drops_partial_first(tmp_path):
    f = tmp_path / "big.jsonl"
    # ~5 MB so the seek window starts mid-file.
    lines = [f"record-{i}-" + "x" * 200 for i in range(25000)]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    got = transcript.tail_lines(str(f), 5, max_bytes=65536)
    assert got == lines[-5:]
    # The window is bounded, so no full-file line count leaks in.
    assert len(transcript.tail_lines(str(f), 100000, max_bytes=65536)) < 25000


def test_tail_lines_is_bounded_fast(tmp_path):
    f = tmp_path / "big.jsonl"
    f.write_text(("y" * 500 + "\n") * 200000, encoding="utf-8")  # ~100 MB
    start = time.perf_counter()
    got = transcript.tail_lines(str(f), 10)
    elapsed = time.perf_counter() - start
    assert len(got) == 10
    assert elapsed < 0.2, f"tail_lines took {elapsed:.3f}s — not seeking from EOF"


def test_count_tool_turns_exact(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(_tool_line("Write") for _ in range(7)) + "\n", encoding="utf-8")
    assert transcript.count_tool_turns(str(f), ("Write", "Edit", "Bash")) == 7


def test_count_tool_turns_one_per_line(tmp_path):
    f = tmp_path / "t.jsonl"
    # A line with two markers still counts once.
    f.write_text('{"name":"Write"}{"name":"Bash"}\n', encoding="utf-8")
    assert transcript.count_tool_turns(str(f), ("Write", "Bash")) == 1


def test_count_tool_turns_early_exit_is_fast(tmp_path):
    f = tmp_path / "big.jsonl"
    # 10 tool turns at the top, then a huge tail of non-tool lines.
    head = [_tool_line("Bash") for _ in range(10)]
    tail = ["z" * 500 for _ in range(400000)]  # ~200 MB of junk after threshold
    f.write_text("\n".join(head + tail) + "\n", encoding="utf-8")
    start = time.perf_counter()
    n = transcript.count_tool_turns(str(f), ("Write", "Edit", "Bash"), threshold=10)
    elapsed = time.perf_counter() - start
    assert n == 10
    assert elapsed < 0.2, f"count_tool_turns took {elapsed:.3f}s — not early-exiting at threshold"


def test_count_tool_turns_missing_file(tmp_path):
    assert transcript.count_tool_turns(str(tmp_path / "nope.jsonl"), ("Write",)) == 0
