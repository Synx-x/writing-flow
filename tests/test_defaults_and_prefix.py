import json
import subprocess
import sys
from pathlib import Path

from _env import home_env

ROOT = Path(__file__).resolve().parents[1]


def test_live_flow_defaults_merge_under_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(tmp_path / "missing.json"))
    from writing_flow import config

    default = config.hook_config("guard_flow")
    assert default["mode"] == "strict"
    assert default["kinds"] == [
        "topic_drift", "unanchored_chain", "new_in_topic", "missing_index",
        "preview_term_dropped", "vague_heading", "index_count_mismatch",
        "doc_intro_too_long",
    ]
    user_config = tmp_path / "config.json"
    user_config.write_text(json.dumps({"hooks": {"guard_flow": {"mode": "warn"}}}))
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(user_config))
    assert config.hook_config("guard_flow")["mode"] == "warn"


def test_hook_output_uses_only_writing_flow_prefix(tmp_path):
    hook = ROOT / "hooks" / "guard_style.py"
    content = "def f():\n    # The tool performs an analysis of the data; it reaches out to the service.\n    pass\n"
    payloads = [
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "bad.py"), "content": content}},
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "good.md"), "content": "A clear sentence.\n"}},
    ]
    codes = []
    for payload in payloads:
        result = subprocess.run(
            [sys.executable, str(hook)], input=json.dumps(payload), text=True,
            capture_output=True, env=home_env(tmp_path), timeout=20,
        )
        codes.append(result.returncode)
        assert "harness-kit" not in result.stdout + result.stderr
    assert codes == [2, 0]

