"""Test subagent_style_audit hook on SubagentStop."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "subagent_style_audit.py"


def _run(transcript_path, session_id="sess_123"):
    """Run subagent_style_audit hook with its state beside the transcript."""
    env = dict(os.environ, WRITING_FLOW_STATE_DIR=str(Path(transcript_path).parent / "state"))
    payload = json.dumps({
        "agent_id": "agent_1",
        "agent_type": "test-agent",
        "agent_transcript_path": str(transcript_path),
        "session_id": session_id,
        "last_assistant_message": ""
    })
    p = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                       capture_output=True, env=env)
    return p.stdout.strip(), p.stderr.strip(), p.returncode


def _journal(transcript_path):
    path = Path(transcript_path).parent / "state" / "subagent_style_audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_transcript(tmpdir, messages):
    """Create a mock transcript JSONL file with given message texts."""
    f = Path(tmpdir) / "transcript.jsonl"
    for msg_text in messages:
        rec = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": msg_text}
                ]
            }
        }
        f.write_text(f.read_text(encoding="utf-8") + json.dumps(rec) + "\n" if f.exists() else json.dumps(rec) + "\n")
    return f


def test_flags_banned_phrase_in_the_journal_not_the_subagent():
    """A non-blocking finding must never reach the finished subagent.

    Live run v60: the note reopened the subagent, and its reply "no action
    needed" replaced its deliverable as the result the parent received.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        BANNED = "Certainly" + "!"
        final_msg = f"The system is {BANNED} The update is now complete."
        f = _make_transcript(tmpdir, [final_msg])
        out, err, code = _run(f)
        assert out == "" and code == 0
        records = _journal(f)
        assert len(records) == 1 and records[0]["kinds"].get("ai_ism")
        assert records[0]["agent_type"] == "test-agent"


def test_flags_tier1_word_in_the_journal():
    with tempfile.TemporaryDirectory() as tmpdir:
        T1 = "lever" + "age"
        final_msg = f"We should {T1} this tool for better efficiency."
        f = _make_transcript(tmpdir, [final_msg])
        out, err, code = _run(f)
        assert out == ""
        assert _journal(f)[0]["kinds"].get("tier1")


def test_clean_subagent_output_no_findings():
    """Clean subagent output produces no output and no journal record."""
    with tempfile.TemporaryDirectory() as tmpdir:
        final_msg = "The system processes requests efficiently and reliably."
        f = _make_transcript(tmpdir, [final_msg])
        out, err, code = _run(f)
        assert not out, "expected no audit output for clean text"
        assert code == 0
        assert _journal(f) == []


def test_multiple_findings_counted_by_kind():
    with tempfile.TemporaryDirectory() as tmpdir:
        BANNED = "Certainly" + "!"
        T1 = "robust"
        msg = f"{BANNED} This is a {T1} and comprehensive solution."
        f = _make_transcript(tmpdir, [msg])
        _run(f)
        assert sum(_journal(f)[0]["kinds"].values()) >= 2


DRIFT = (
    "The system handles requests efficiently. "
    "We need to update the documentation regularly. "
    "The weather today is quite nice. "
    "Code quality is important. "
    "Running tests takes time."
)


def test_flow_findings_never_block_a_subagent():
    """Issue #53: a flow block made subagents defend their report instead of
    resending it, which stranded 18 returns. Flow findings are journaled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = _make_transcript(tmpdir, [DRIFT])
        out, err, code = _run(f)
        assert (code, out, err) == (0, "", "")
        assert _journal(f)[0]["kinds"].get("reader_flow")


# ===== issue #4 regression =====
# A resumed subagent once answered "please resend your findings" by
# describing this hook's own stale note instead. Both messages now state
# plainly that they are closed and carry no action, and these tests pin it.

def test_get_subagent_final_text_never_picks_up_hook_json():
    """Real assistant text only. A prior additionalContext payload sitting
    in the same transcript must never be read back as the subagent's own
    words, the way a SubagentStop resume can fold one into the context.
    """
    sys.path.insert(0, str(ROOT / "hooks"))
    import subagent_style_audit as mod

    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "t.jsonl"
        real_reply = "Here is the full research report, section one of three."
        injected_note = "SUBAGENT OUTPUT AUDIT (non-blocking, closed, needs no reply):"
        lines = [
            json.dumps({"type": "assistant",
                        "message": {"content": [{"type": "text", "text": real_reply}]}}),
            json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStop",
                        "additionalContext": injected_note}}),
        ]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        text = mod.get_subagent_final_text(str(f))
        assert text == real_reply
        assert "SUBAGENT OUTPUT AUDIT" not in text
