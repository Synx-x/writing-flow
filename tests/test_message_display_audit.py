"""message_display_audit: the MessageDisplay hook that rewrites a streaming
delta in place. Scope is deliberately narrow -- literal tier-1 word/phrase
swaps only, fence-safe, backtick-span-safe -- since this hook sees one batch
of lines with no view of the rest of the message.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

import message_display_audit as mda  # noqa: E402


# ===== shape_delta: the pure rewrite function =====

def test_literal_tier1_word_rewritten():
    shaped, _ = mda.shape_delta("We should leverage the new API.\n", False)
    assert "leverage" not in shaped
    assert "use the new API" in shaped


def test_case_preserved_on_rewrite():
    shaped, _ = mda.shape_delta("Leverage this carefully.\n", False)
    assert shaped.startswith("Use this carefully.")


def test_all_caps_word_rewritten_all_caps():
    shaped, _ = mda.shape_delta("LEVERAGE is the wrong word.\n", False)
    assert shaped.startswith("USE is the wrong word.")


def test_multi_word_phrase_rewritten():
    shaped, _ = mda.shape_delta("Just make use of the helper.\n", False)
    assert "make use of" not in shaped
    assert "use the helper" in shaped


def test_non_literal_entry_left_alone():
    """'groundbreaking' maps to a parenthetical instruction, not a literal
    replacement. This hook has no context to act on that judgment call."""
    shaped, _ = mda.shape_delta("A groundbreaking result.\n", False)
    assert "groundbreaking" in shaped


def test_clean_text_unchanged():
    text = "Rain taps the window in a steady rhythm.\n"
    shaped, in_fence = mda.shape_delta(text, False)
    assert shaped == text
    assert in_fence is False


def test_word_not_flagged_as_substring():
    """'user' must not match inside 'used' or similar -- word boundaries only."""
    shaped, _ = mda.shape_delta("The user used the tool.\n", False)
    assert shaped == "The user used the tool.\n"


# ===== article agreement: 13 of 52 entries flip leading vowel sound =====

def test_an_actionable_becomes_a_practical():
    shaped, _ = mda.shape_delta("This is an actionable findings report.\n", False)
    assert shaped.startswith("This is a practical findings report.")


def test_an_embark_becomes_a_start():
    shaped, _ = mda.shape_delta("That was an embark point.\n", False)
    assert shaped.startswith("That was a start point.")


def test_a_paradigm_becomes_an_approach():
    shaped, _ = mda.shape_delta("Adopt a paradigm shift now.\n", False)
    assert shaped.startswith("Adopt an approach shift now.")


def test_a_leverage_becomes_a_use_not_an_use():
    """'use' starts with a vowel letter but a consonant sound. The fix must
    not treat every leading vowel letter as needing 'an'.
    """
    shaped, _ = mda.shape_delta("Find a leverage point here.\n", False)
    assert shaped.startswith("Find a use point here.")


def test_article_fix_only_runs_when_a_swap_happened():
    """No tier-1 word present: the article-fix pass must not alter an
    already-correct 'an' before an unrelated vowel-leading word.
    """
    text = "This is an ordinary sentence.\n"
    shaped, _ = mda.shape_delta(text, False)
    assert shaped == text


# ===== fence safety: never rewrite inside a code block =====

def test_fence_opens_and_protects_content():
    text = "```\nleverage_ratio = 2\n```\n"
    shaped, in_fence = mda.shape_delta(text, False)
    assert "leverage_ratio" in shaped
    assert in_fence is False  # closed again by the second fence line


def test_fence_state_carries_across_deltas():
    """A fence opened in one flush must still protect content in the next
    flush -- this is why fence state persists per message, not per call."""
    opened, in_fence = mda.shape_delta("```\n", False)
    assert in_fence is True
    protected, in_fence2 = mda.shape_delta("leverage_ratio = 2\n", in_fence)
    assert "leverage_ratio" in protected
    assert in_fence2 is True
    closed, in_fence3 = mda.shape_delta("```\n", in_fence2)
    assert in_fence3 is False


def test_fence_delimiter_line_itself_not_rewritten():
    shaped, _ = mda.shape_delta("```leverage\n", False)
    assert shaped == "```leverage\n"


# ===== inline code span safety =====

def test_inline_code_span_protected():
    shaped, _ = mda.shape_delta(
        "Call `leverage()` then leverage the result.\n", False
    )
    assert "`leverage()`" in shaped
    assert "use the result" in shaped


# ===== final-flush and empty-delta edge cases =====

def test_empty_delta_no_output(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    result = _run_hook({
        "session_id": "s1", "message_id": "m1",
        "index": 0, "final": True, "delta": "",
    })
    assert result.stdout.strip() == ""
    assert result.returncode == 0


def test_final_flush_clears_fence_state(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    _run_hook({
        "session_id": "s1", "message_id": "m1",
        "index": 0, "final": False, "delta": "```\n",
    })
    state_path = mda._fence_state_path("s1", "m1")
    assert state_path.exists()

    _run_hook({
        "session_id": "s1", "message_id": "m1",
        "index": 1, "final": True, "delta": "leverage\n",
    })
    assert not state_path.exists()


def test_malformed_stdin_fails_open():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "message_display_audit.py")],
        input="not json", capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ===== end-to-end hook output shape =====

def test_hook_emits_display_content_when_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    result = _run_hook({
        "session_id": "s2", "message_id": "m2",
        "index": 0, "final": True, "delta": "We will leverage this.\n",
    })
    payload = json.loads(result.stdout)
    shaped = payload["hookSpecificOutput"]["displayContent"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "MessageDisplay"
    assert "use this" in shaped


def test_hook_emits_nothing_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    result = _run_hook({
        "session_id": "s3", "message_id": "m3",
        "index": 0, "final": True, "delta": "Nothing to fix here.\n",
    })
    assert result.stdout.strip() == ""


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "message_display_audit.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=10, env=env,
    )


# ===== rewrite logging =====
# A display-only swap leaves no trace in the transcript, so this log is the
# only record that it happened.

SWAPPED = "lever" + "age"


def test_swap_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    _run_hook({
        "session_id": "s9", "message_id": "m9",
        "index": 0, "final": True, "delta": f"We should {SWAPPED} this.\n",
    })
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    from writing_flow import rewrite_log
    rows = rewrite_log.read_recent()
    assert any(r["hook"] == "message_display_audit" for r in rows)
    assert any(SWAPPED in r["before"] for r in rows)


def test_no_swap_writes_no_row(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    _run_hook({
        "session_id": "s10", "message_id": "m10",
        "index": 0, "final": True, "delta": "Nothing to fix here.\n",
    })
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    from writing_flow import rewrite_log
    assert rewrite_log.read_recent() == []
