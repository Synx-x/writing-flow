"""Test flow_reinforce: reinforce writing-flow on every UserPromptSubmit."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))


def test_emits_reminder_when_style_active(tmp_path):
    """Hook emits reminder JSON when writing-flow style is active."""
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()
    styles_dir = home_override / ".claude" / "output-styles"
    styles_dir.mkdir(parents=True)

    style_file = styles_dir / "writing-flow.md"
    style_file.write_text(
        "# Writing flow\n\n"
        "Some content.\n\n"
        "## Self-check before you send\n\n"
        "1. Read the first seven or eight words.\n"
        "2. Does any sentence run more than eight words before its verb?\n"
        "3. Does the first sentence of each paragraph name what the rest develops?\n"
        "4. Do previewed terms return verbatim in later topics?\n"
        "5. Does the last sentence end on point, not on a hedge?\n"
    , encoding="utf-8")

    settings = home_override / ".claude" / "settings.json"
    settings.write_text(json.dumps({"outputStyle": "writing-flow"}), encoding="utf-8")

    payload = {"prompt": "test prompt", "session_id": "test_session"}

    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    output = json.loads(result.stdout.strip())
    assert "hookSpecificOutput" in output
    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "FLOW CHECK" in output["hookSpecificOutput"]["additionalContext"]


def test_default_reminder_when_style_unset(tmp_path):
    """Issue #60: with outputStyle unset the hook used to print nothing, so a
    session with no style got no reminder. It now emits a built-in one."""
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()

    settings = home_override / ".claude" / "settings.json"
    settings.write_text(json.dumps({}), encoding="utf-8")

    payload = {"prompt": "test prompt", "session_id": "test_session"}

    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("WRITING. Lead with the answer.")


def test_silent_when_style_file_missing(tmp_path):
    """Hook outputs nothing when style file does not exist."""
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()

    settings = home_override / ".claude" / "settings.json"
    settings.write_text(json.dumps({"outputStyle": "no-such-style"}), encoding="utf-8")

    payload = {"prompt": "test prompt", "session_id": "test_session"}

    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_plugin_style_used_when_user_style_is_missing(tmp_path):
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()
    (home_override / ".claude" / "settings.json").write_text(
        json.dumps({"outputStyle": "writing-flow"}), encoding="utf-8")
    payload = {"prompt": "test prompt", "session_id": "test_session"}
    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "FLOW CHECK" in result.stdout


def test_silent_when_self_check_section_missing(tmp_path):
    """Hook outputs nothing when self-check section is not in style file."""
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()
    styles_dir = home_override / ".claude" / "output-styles"
    styles_dir.mkdir(parents=True)

    style_file = styles_dir / "writing-flow.md"
    style_file.write_text("# Writing flow\n\nSome content without self-check.\n", encoding="utf-8")

    settings = home_override / ".claude" / "settings.json"
    settings.write_text(json.dumps({"outputStyle": "writing-flow"}), encoding="utf-8")

    payload = {"prompt": "test prompt", "session_id": "test_session"}

    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "FLOW CHECK" in result.stdout


def test_exits_cleanly_on_invalid_json(tmp_path):
    """Hook handles invalid JSON gracefully."""
    home_override = tmp_path / "home"
    home_override.mkdir()
    (home_override / ".claude").mkdir()

    settings = home_override / ".claude" / "settings.json"
    settings.write_text(json.dumps({}), encoding="utf-8")

    payload = "invalid json"

    env = {
        **dict(os.environ),
        "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(home_override / ".claude" / "writing-flow" / "state"),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def _style_home(tmp_path):
    home_override = tmp_path / "home"
    styles_dir = home_override / ".claude" / "output-styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "writing-flow.md").write_text(
        "# Writing flow\n\nSome content.\n\n## Self-check before you send\n\n1. x\n"
    , encoding="utf-8")
    (home_override / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "writing-flow"}), encoding="utf-8")
    return home_override


def test_adds_shape_rules_for_a_long_deliverable_phase(tmp_path):
    """A verify/plan-stage turn gets the extra shaping block, not just the reminder."""
    home_override = _style_home(tmp_path)
    state_dir = tmp_path / "state"
    (state_dir / "phase").mkdir(parents=True)
    (state_dir / "phase" / "current_phase_s.json").write_text(json.dumps({"stage": "verify", "complexity": 3}), encoding="utf-8")

    env = {**dict(os.environ), "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(state_dir)}
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps({"prompt": "p", "session_id": "s"}),
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    ctx = json.loads(result.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert "SHAPE THIS REPLY" in ctx
    assert "FLOW CHECK" in ctx


def test_no_shape_rules_for_a_short_conversational_phase(tmp_path):
    """A plain low-complexity turn gets only the standing reminder."""
    home_override = _style_home(tmp_path)
    state_dir = tmp_path / "state"
    (state_dir / "phase").mkdir(parents=True)
    (state_dir / "phase" / "current_phase_s.json").write_text(json.dumps({"stage": "execute", "complexity": 1}), encoding="utf-8")

    env = {**dict(os.environ), "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(state_dir)}
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps({"prompt": "p", "session_id": "s"}),
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    ctx = json.loads(result.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert "SHAPE THIS REPLY" not in ctx


def test_missing_phase_file_does_not_crash(tmp_path):
    """No current_phase.json on disk still emits the base reminder."""
    home_override = _style_home(tmp_path)
    env = {**dict(os.environ), "HOME": str(home_override),
        "USERPROFILE": str(home_override),
        "WRITING_FLOW_HOME": str(home_override),
        "WRITING_FLOW_STATE_DIR": str(tmp_path / "nope")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "flow_reinforce.py")],
        input=json.dumps({"prompt": "p", "session_id": "s"}),
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "FLOW CHECK" in result.stdout
