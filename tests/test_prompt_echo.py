import json
import subprocess
import sys
from pathlib import Path

from _env import home_env
from writing_flow import prompt_echo

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "guard_prompt_echo.py"


def _transcript(path, prompt):
    path.write_text(json.dumps({"type": "user", "message": {"content": prompt}}) + "\n")
    return str(path)


def _run(tmp_path, transcript, tool, tool_input):
    event = {"harness": "claude", "session_id": "echo-test", "transcript_path": transcript,
             "tool_name": tool, "tool_input": tool_input}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), text=True,
                          capture_output=True, env=home_env(tmp_path), timeout=20)


def test_guidance_clause_kinds_and_echo_certainty():
    clauses = prompt_echo.guidance_clauses([
        "For a backend developer who never configured caching, cover install and usage. In chat, keep it short. Ask no questions."
    ])
    assert {item["kind"] for item in clauses} == {"audience", "scope", "form", "process"}
    sure = prompt_echo.find_echo("This guide is for backend developers who never configured caching.", clauses)
    assert sure and sure[0]["sure"] is True
    advisory = prompt_echo.find_echo("Backend developers can configure caching with this service.", clauses)
    assert advisory and advisory[0]["sure"] is False


def test_narration_catches_new_phrases_only():
    findings = prompt_echo.find_narration("Here is the README.\nBelow you'll find the options.\nNow for the options section.\nI'll start by listing the flags.\nIn this guide we will rotate keys.\nThe following sections cover setup.")
    assert len(findings) == 6
    assert all(item["sure"] for item in findings)
    assert not prompt_echo.find_narration("The service rotates a key after validation.")


def test_write_blocks_echo_and_records_outcome(tmp_path):
    transcript = _transcript(tmp_path / "transcript.jsonl", "For a backend developer who never configured caching, explain caching.")
    result = _run(tmp_path, transcript, "Write", {"file_path": str(tmp_path / "guide.md"), "content": "This guide is for backend developers who never configured caching."})
    assert result.returncode == 2
    assert "writing-flow[echo:blocked]" in result.stderr
    assert "audience guidance" in result.stderr and "This guide is for" in result.stderr
    log = (tmp_path / ".claude" / "writing-flow" / "state" / "guard_prompt_echo_log.jsonl").read_text()
    assert '"outcome": "block"' in log
    assert "For a backend developer" not in log


def test_advisory_does_not_block_and_write_logs_pass(tmp_path):
    transcript = _transcript(tmp_path / "transcript.jsonl", "For a backend developer who never configured caching, explain caching.")
    result = _run(tmp_path, transcript, "Write", {"file_path": str(tmp_path / "guide.md"), "content": "Backend developers can configure caching with this service."})
    assert result.returncode == 0
    assert "possible prompt echo" in result.stderr
    assert '"outcome": "pass"' in (tmp_path / ".claude" / "writing-flow" / "state" / "guard_prompt_echo_log.jsonl").read_text()


def test_code_comment_scope_and_edit_changed_lines(tmp_path):
    transcript = _transcript(tmp_path / "transcript.jsonl", "Cover install, usage and options.")
    code = "def run():\n    return 1\n# This README covers install, usage and options.\n"
    result = _run(tmp_path, transcript, "Write", {"file_path": str(tmp_path / "code.py"), "content": code})
    assert result.returncode == 2
    old = "This README covers install, usage and options.\nunchanged context"
    new = "This README covers install, usage and options.\nA normal sentence."
    edit = _run(tmp_path, transcript, "Edit", {"file_path": str(tmp_path / "edit.md"), "old_string": old, "new_string": new})
    assert edit.returncode == 0


def test_echo_waiver_is_target_scoped_and_one_shot(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path / "transcript.jsonl", "Cover install, usage and options.")
    path = str(tmp_path / "guide.md")
    event_input = {"file_path": path, "content": "This README covers install, usage and options."}
    assert _run(tmp_path, transcript, "Write", event_input).returncode == 2
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path / ".claude" / "writing-flow" / "state"))
    from writing_flow.prompt_echo_state import override_path
    override = override_path("echo-test", path)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("Keep this sentence to set reader expectations.")
    waived = _run(tmp_path, transcript, "Write", event_input)
    assert waived.returncode == 0 and "waiver accepted" in waived.stdout
    assert not override.exists()
    assert _run(tmp_path, transcript, "Write", event_input).returncode == 2
    log = (tmp_path / ".claude" / "writing-flow" / "state" / "guard_prompt_echo_log.jsonl").read_text()
    assert '"outcome": "waive"' in log
    assert "Keep this sentence" in log


def test_instruction_path_is_exempt_and_logged(tmp_path):
    transcript = _transcript(tmp_path / "transcript.jsonl", "Cover install, usage and options.")
    result = _run(tmp_path, transcript, "Write", {"file_path": str(tmp_path / "AGENTS.md"), "content": "This guide covers install, usage and options."})
    assert result.returncode == 0
    assert '"outcome": "exempt"' in (tmp_path / ".claude" / "writing-flow" / "state" / "guard_prompt_echo_log.jsonl").read_text()


def test_chat_echo_skips_first_sentence(tmp_path):
    transcript = _transcript(tmp_path / "transcript.jsonl", "In chat, without creating any files: explain the options.")
    from hooks import response_audit
    text = "Here is a short answer in chat, with no files created. This answer is in chat and creates no files."
    findings = response_audit.check_prompt_echo(text, transcript)
    assert len(findings) == 1
    assert "This answer" in findings[0][1]
