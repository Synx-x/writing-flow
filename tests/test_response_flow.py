"""Reader-flow enforcement on the chat reply itself, not just on files.

guard_flow fires on Write and Edit, so it never sees a chat reply. These cover
the Stop-hook path that does, which is the only mechanism that makes flow rules
binding on conversational output rather than advisory.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "response_audit.py"
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
from writing_flow import flow_state  # noqa: E402


def marker_for(state, session="CHAT"):
    """The chat-scoped override slot, resolved against the test's state dir.

    flow_state reads WRITING_FLOW_STATE_DIR at call time and this process does not
    set it, so take the name and join it to the tmp dir the hook sees.
    """
    return Path(state) / flow_state.override_path(session, flow_state.CHAT_TARGET).name

# Four sentences, four different subjects, no shared anchor.
DRIFTING = (
    "DXVK fails first at screen capture. DXVK does not implement DXGI Desktop "
    "Duplication, so the log records an unimplemented error. The application then "
    "relaunches itself three times through ShellExecute and exits. Steam records "
    "exit code -1 in the game process log."
)

# Same facts, one anchor held throughout.
ANCHORED = (
    "The application fails first at screen capture. It calls DXGI Desktop "
    "Duplication, which DXVK does not implement, so the log records an "
    "unimplemented error. It then relaunches itself three times through "
    "ShellExecute and exits. Its exit code reaches Steam as -1 in the log."
)


def run(reply, mode, state, session="CHAT"):
    # A fixture home keeps the operator's real output style, which exempts
    # semicolons from chat, out of the test.
    env = dict(os.environ, HARNESS_KIT_RESPONSE_FLOW=mode, WRITING_FLOW_STATE_DIR=str(state),
               HARNESS_KIT_HOME=str(Path(state) / "home"))
    transcript = Path(state) / "t.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")
    payload = json.dumps({
        "hook_event_name": "Stop",
        "session_id": session,
        "transcript_path": str(transcript),
        "last_assistant_message": reply,
    })
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload,
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def drifting():
    """Skip unless the sample still trips a rule, so a rule change stays visible.

    Checked through flow_rules directly. Running the hook as a probe would burn
    the one-block-per-text guard and leave every real assertion deduped.
    """
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    from writing_flow import flow_rules
    if not flow_rules.scan_flow(DRIFTING):
        pytest.skip("sample reply no longer trips a flow rule")
    return DRIFTING


def test_off_allows(tmp_path, drifting):
    assert run(drifting, "off", tmp_path).returncode == 0


def test_warn_allows(tmp_path, drifting):
    assert run(drifting, "warn", tmp_path).returncode == 0


def test_strict_blocks_the_reply(tmp_path, drifting):
    result = run(drifting, "strict", tmp_path)
    assert result.returncode == 2
    assert "Reader flow" in result.stderr


def test_anchored_reply_passes_strict(tmp_path):
    """The fix is structural. Same facts, one anchor, no block."""
    assert run(ANCHORED, "strict", tmp_path).returncode == 0


def test_override_allows_one_reply_then_is_consumed(tmp_path, drifting):
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("quoting the user's own wording back", encoding="utf-8")

    assert run(drifting, "strict", tmp_path).returncode == 0
    assert not marker.exists(), "override must be single use"


def test_chat_override_is_not_a_file_override(tmp_path, drifting):
    """A subagent's escape for its own document must not cover a chat reply.

    Live on 2026-09-10: a retrospective subagent wrote an override while a
    second subagent needed one. One slot served both, and the second ran out.
    """
    file_marker = Path(tmp_path) / flow_state.override_path("CHAT", "/tmp/doc.md").name
    file_marker.parent.mkdir(parents=True, exist_ok=True)
    file_marker.write_text("mandated shape in that document", encoding="utf-8")

    assert run(drifting, "strict", tmp_path).returncode == 2
    assert file_marker.exists(), "a file's override must survive a chat block"


def test_override_is_logged_for_measurement(tmp_path, drifting):
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("mandated banner text", encoding="utf-8")
    run(drifting, "strict", tmp_path)

    log = tmp_path / "guard_flow_log.jsonl"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    override = [r for r in records if r["outcome"] == "override"]
    assert override, "an override on a chat reply must reach the same log as a file one"
    assert override[0]["path"] == "<chat response>"
    assert override[0]["reason"] == "mandated banner text"


def test_mode_defaults_to_strict_without_config(tmp_path, drifting):
    """An advisory notice never fixed a reply, because the reply already went."""
    env = dict(os.environ, WRITING_FLOW_STATE_DIR=str(tmp_path))
    env.pop("HARNESS_KIT_RESPONSE_FLOW", None)
    env["HARNESS_KIT_LOCAL_DIR"] = str(tmp_path / "empty-local")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    payload = json.dumps({
        "hook_event_name": "Stop", "session_id": "CHAT",
        "transcript_path": str(transcript), "last_assistant_message": drifting,
    })
    result = subprocess.run([sys.executable, str(HOOK)], input=payload,
                            capture_output=True, text=True, env=env)
    assert result.returncode == 2


def test_block_message_names_the_override_escape(tmp_path, drifting):
    """A block the model cannot argue with is a loop, not a gate."""
    result = run(drifting, "strict", tmp_path)
    assert result.returncode == 2
    assert "flow-override-CHAT" in result.stderr


def test_repeat_blocks_are_capped_then_logged(tmp_path, drifting):
    """One block, then the next reply goes through and records 'capped'.

    Each block costs the reader a duplicate answer, because Claude Code adds
    the revision as a new message instead of replacing the one it judged.
    Observed 2026-09-10: a cap of two shipped three near-identical answers.
    """
    variants = [drifting, drifting + " One more sentence here."]
    codes = [run(v, "strict", tmp_path).returncode for v in variants]
    assert codes == [2, 0], codes
    log = tmp_path / "guard_flow_log.jsonl"
    outcomes = [json.loads(l)["outcome"] for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert outcomes[-1] == "capped"
    assert outcomes.count("blocked") == 1


def test_form_and_flow_share_one_block_budget(tmp_path, drifting):
    """Two rule families, one budget, because the reader pays per block.

    check_chat_form carried no counter at all, so a form finding could block
    every revision no matter how many flow blocks had already fired.
    """
    form_only = "The service " + " ".join(["restarted"] * 47) + " cleanly."
    assert run(drifting, "strict", tmp_path).returncode == 2
    assert run(form_only, "strict", tmp_path).returncode == 0
    log = tmp_path / "guard_flow_log.jsonl"
    outcomes = [json.loads(l)["outcome"] for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert outcomes == ["blocked", "capped"], outcomes


def test_the_shared_log_counts_chat_form_kinds(tmp_path):
    """One log line covers both families, so the form kinds must appear."""
    run("The service restarted cleanly; it logged nothing unusual.", "strict", tmp_path)
    log = tmp_path / "guard_flow_log.jsonl"
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert record["counts"] == {"semicolon": 1}, record


def test_a_passing_reply_resets_the_block_count(tmp_path, drifting):
    run(drifting, "strict", tmp_path)
    run(ANCHORED, "strict", tmp_path)
    assert run(drifting + " Extra.", "strict", tmp_path).returncode == 2


def test_violation_records_follow_the_state_dir(tmp_path, drifting):
    """A test run must not leave last_violations_CHAT.json in the real home."""
    run(drifting, "strict", tmp_path)
    assert (tmp_path / "last_violations_CHAT.json").is_file()
    assert (tmp_path / "rule-activations.jsonl").is_file()


def test_written_override_does_not_outlive_a_clean_reply(tmp_path, drifting):
    """A reason written this turn must not silently cover a later, unrelated block."""
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("topic drift was the task", encoding="utf-8")

    clean = "The service restarted cleanly. It logged nothing unusual."
    assert run(clean, "strict", tmp_path).returncode == 0
    assert not marker.exists(), "an unused override must not survive a clean reply"

    # The next, unrelated block must not be silently forgiven by the ghost.
    result = run(drifting, "strict", tmp_path)
    assert result.returncode == 2


def test_hint_says_to_resend_the_same_answer(tmp_path, drifting):
    """Live-driven: a model that wrote the reason then answered with a status
    report about the file, not the paragraph the user asked for. The hint
    must rule that out explicitly.
    """
    result = run(drifting, "strict", tmp_path)
    assert "SAME answer again unchanged" in result.stderr
    assert "report about writing the file" in result.stderr
