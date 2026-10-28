import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def all_commands(path):
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return [hook["command"] for entries in data["hooks"].values()
            for entry in entries for hook in entry["hooks"]]


def test_every_registered_script_exists():
    data = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    for entries in data["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                command = hook["command"]
                name = command.rsplit("/", 1)[-1].removesuffix(".py\"")
                assert (ROOT / "hooks" / f"{name}.py").is_file()


def test_plugin_root_is_quoted():
    for command in all_commands("hooks/hooks.json"):
        assert '"${CLAUDE_PLUGIN_ROOT}' in command


def _run_guard(path, content):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
             "tool_input": {"file_path": str(path), "content": content},
             "session_id": "plugin-test"}
    return subprocess.run([sys.executable, str(ROOT / "hooks/guard_style.py")],
                          input=json.dumps(event), text=True, capture_output=True,
                          env={**os.environ, "WRITING_FLOW_STATE_DIR": str(path.parent / "state")})


def test_violating_write_denies(tmp_path):
    proc = _run_guard(tmp_path / "bad.md", "This phrase uses a semicolon; and it is unsafe.\n")
    assert proc.returncode == 2


def test_clean_write_passes(tmp_path):
    proc = _run_guard(tmp_path / "good.md", "The system is ready.\n")
    assert proc.returncode == 0


def test_codex_adapter_runs_guard_style(tmp_path):
    path = tmp_path / "codex.md"
    event = {"hook_event_name": "PreToolUse", "tool_name": "write_file",
             "tool_input": {"file_path": str(path),
                            "content": "This phrase uses a semicolon; and it is unsafe.\n"},
             "cwd": str(tmp_path), "session_id": "codex-test"}
    env = {**os.environ, "CODEX_THREAD_ID": "codex-test",
           "WRITING_FLOW_STATE_DIR": str(tmp_path / "state")}
    proc = subprocess.run([sys.executable, str(ROOT / "adapters/codex/run_hook.py"), "guard_style"],
                          input=json.dumps(event), text=True, capture_output=True, env=env)
    assert proc.returncode == 2
