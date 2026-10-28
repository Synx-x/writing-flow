"""plain_log: prints the rewrite log as before-and-after pairs, so the
cosmetic layer can be read without jq."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import rewrite_log

SCRIPT = ROOT / "scripts" / "plain_log.py"
SWAPPED = "lever" + "age"


def _run(state_dir, *args):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env, timeout=10)


def test_empty_log_says_so(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "no" in result.stdout.lower()


def test_prints_before_and_after(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    rewrite_log.record("message_display_audit", "tier1", SWAPPED, "use", "s1")
    result = _run(tmp_path)
    assert SWAPPED in result.stdout
    assert "use" in result.stdout


def test_limit_flag_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    for i in range(5):
        rewrite_log.record("h", "r", f"before{i}", "after", "s1")
    result = _run(tmp_path, "--limit", "2")
    assert "before4" in result.stdout
    assert "before0" not in result.stdout
