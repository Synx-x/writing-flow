"""Strict mode, its two escapes, and the outcome log that measures them."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "guard_flow.py"
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
from writing_flow import flow_state  # noqa: E402

PROBE = "/tmp/probe.md"


def marker_for(state, session="S1", target=PROBE):
    """The scoped override slot, resolved against the test's state dir.

    flow_state reads WRITING_FLOW_STATE_DIR at call time and this process does not
    set it, so take the name and join it to the tmp state dir the hook sees.
    """
    return Path(state) / flow_state.override_path(session, target).name

# Prose that trips the rules: a long runway, then a paragraph whose sentences
# share no anchor.
FLAGGED = (
    "Across every affected subsystem on this particular machine the operator "
    "eventually observes a fault in the display path.\n\n"
    "The compositor holds one buffer. Memory pressure arrives from an unrelated "
    "service. A scheduler decision changes the frame order. Nothing here repeats "
    "the earlier subject at all.\n"
)


def run(content, state, mode="strict", session="S1", extra_env=None,
        cfg=None, target=PROBE):
    env = dict(os.environ, HARNESS_KIT_FLOW=mode, WRITING_FLOW_STATE_DIR=str(state))
    env.pop("HARNESS_KIT_SKIP_FLOW_CHECK", None)
    # Point local config at the tmp dir either way, so a developer's own
    # config.json cannot decide the result of a test run.
    local = Path(state) / "local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "config.json").write_text(
        json.dumps({"hooks": {"guard_flow": cfg}}) if cfg else "{}",
        encoding="utf-8",
    )
    env["WRITING_FLOW_CONFIG"] = str(local / "config.json")
    env.update(extra_env or {})
    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "session_id": session,
        "tool_input": {"file_path": target, "content": content},
    })
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload,
        capture_output=True, text=True, env=env,
    )


def outcomes(state):
    log = Path(state) / "guard_flow_log.jsonl"
    if not log.is_file():
        return []
    return [
        json.loads(line).get("outcome")
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture
def flagged(tmp_path):
    """Skip unless the sample still trips a rule, so a rule change is visible."""
    probe = run(FLAGGED, tmp_path / "probe-state")
    if probe.returncode != 2:
        pytest.skip("sample prose no longer trips any flow rule")
    return FLAGGED


def test_strict_blocks(tmp_path, flagged):
    result = run(flagged, tmp_path)
    assert result.returncode == 2
    assert "FLOW VIOLATION" in result.stderr


def test_block_message_names_both_escapes(tmp_path, flagged):
    result = run(flagged, tmp_path)
    assert "flow-exempt" in result.stderr
    assert "flow-override-S1" in result.stderr


def test_warn_does_not_block(tmp_path, flagged):
    result = run(flagged, tmp_path, mode="warn")
    assert result.returncode == 0
    assert "FLOW NOTICE" in result.stdout


def test_off_is_silent(tmp_path, flagged):
    result = run(flagged, tmp_path, mode="off")
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_exempt_marker_allows_the_write(tmp_path, flagged):
    result = run("flow-exempt: fixed template shape\n\n" + flagged, tmp_path)
    assert result.returncode == 0
    assert outcomes(tmp_path) == ["exempt"]


def test_override_file_allows_one_write_then_is_consumed(tmp_path, flagged):
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("issue template shape, not free prose", encoding="utf-8")

    first = run(flagged, tmp_path)
    assert first.returncode == 0
    assert not marker.exists(), "override must be single use"

    second = run(flagged, tmp_path)
    assert second.returncode == 2, "the escape must not stay open for the session"
    assert outcomes(tmp_path) == ["override", "blocked"]


def test_override_reason_is_recorded(tmp_path, flagged):
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("quoting a mandated banner verbatim", encoding="utf-8")
    run(flagged, tmp_path)

    record = json.loads((tmp_path / "guard_flow_log.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["outcome"] == "override"
    assert record["reason"] == "quoting a mandated banner verbatim"


def test_override_ignored_for_a_different_session(tmp_path, flagged):
    marker = marker_for(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("reason", encoding="utf-8")

    result = run(flagged, tmp_path, session="OTHER")
    assert result.returncode == 2
    assert marker.exists(), "another session's override must stay untouched"


def test_override_ignored_for_a_different_file(tmp_path, flagged):
    """Two subagents in one session must not spend each other's escape.

    Live on 2026-09-10: a retrospective subagent wrote an override for its own
    document. A second subagent in the same session then took five blocks with
    nothing left to spend, and exited without writing its file.
    """
    marker = marker_for(tmp_path, target="/tmp/other.md")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("mandated shape in the other file", encoding="utf-8")

    result = run(flagged, tmp_path)
    assert result.returncode == 2
    assert marker.exists(), "another file's override must stay untouched"


def test_repeat_blocks_are_capped_then_the_write_passes(tmp_path, flagged):
    """A rule the model cannot satisfy is a loop, not a gate."""
    codes = [run(flagged, tmp_path).returncode for _ in range(3)]
    assert codes == [2, 2, 0], codes
    assert outcomes(tmp_path) == ["blocked", "blocked", "capped"]


def test_block_cap_is_configurable_to_zero(tmp_path, flagged):
    """block_cap 0 means never block, which is warn mode with strict logging."""
    result = run(flagged, tmp_path, cfg={"block_cap": 0})
    assert result.returncode == 0
    assert outcomes(tmp_path) == ["capped"]


def test_a_clean_write_resets_the_block_count(tmp_path, flagged):
    """A settled file must not carry a count that caps its next real block."""
    run(flagged, tmp_path)
    run("The compositor holds one buffer. It releases that buffer on vblank.\n", tmp_path)
    assert run(flagged, tmp_path).returncode == 2
    assert run(flagged, tmp_path).returncode == 2


def test_session_env_escape_still_wins(tmp_path, flagged):
    result = run(flagged, tmp_path, extra_env={"HARNESS_KIT_SKIP_FLOW_CHECK": "1"})
    assert result.returncode == 0
