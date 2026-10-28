"""guard_style's plain caps: while plain mode is on, a file write also has
to satisfy the paragraph and chain caps ASD-STE100 never covered.

ASD-STE100 caps the sentence and nothing else, so a file can pass every
sentence check and still arrive as one unbroken block."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_state

GUARD = ROOT / "hooks" / "guard_style.py"


def _write(tmp_path, content, state_dir, rel="doc.md", tool="Write", transcript=""):
    env = dict(os.environ)
    env["WRITING_FLOW_STATE_DIR"] = str(state_dir)
    env.pop("HARNESS_KIT_STE", None)
    # The doc sits beside the state dir, not in it. guard_style skips files
    # under the state dir as machine state, such as agent briefs.
    doc = tmp_path.parent / f"{tmp_path.name}-project" / rel
    key = "content" if tool == "Write" else "new_string"
    payload = {"tool_name": tool,
               "tool_input": {"file_path": str(doc), key: content},
               "transcript_path": transcript}
    return subprocess.run([sys.executable, str(GUARD)],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=15)


def test_long_paragraph_passes_when_plain_is_off(tmp_path):
    content = "Short one. Short two. Short three. Short four. Short five."
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 0


def test_long_paragraph_blocks_when_plain_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    # Six sentences is 1.5x the cap of four, a HARD overage.
    content = "Short one. Short two. Short three. Short four. Short five. Short six."
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 2
    assert "Plain:" in result.stderr


def test_short_paragraphs_pass_when_plain_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    content = "Rain fell all morning.\n\nThe river rose by noon."
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 0


def test_long_chain_blocks_when_plain_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    content = "\n\n".join(["Short one here." for _ in range(6)])
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 2
    assert "paragraphs" in result.stderr


def _on(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)


def test_soft_overage_is_advisory_in_a_file(tmp_path, monkeypatch):
    """Five sentences against a cap of four is SOFT. It prints, it does not block."""
    _on(tmp_path, monkeypatch)
    content = "Short one. Short two. Short three. Short four. Short five."
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 0
    assert "Plain:" in result.stderr


def test_chain_cap_counts_per_section_in_a_file(tmp_path, monkeypatch):
    """Eight sections of two short paragraphs each read as eight short chains."""
    _on(tmp_path, monkeypatch)
    section = "## Part\n\nRain fell all morning.\n\nThe river rose by noon."
    content = "\n\n".join([section] * 8)
    result = _write(tmp_path, content, tmp_path)
    assert result.returncode == 0, result.stderr


AGENT = """---
name: demo
description: >
  One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten. Eleven. Twelve.
---

""" + "\n\n".join(["One short line." for _ in range(8)])


def test_agent_definition_reports_without_blocking(tmp_path, monkeypatch):
    """An agent file takes its shape from the template, so plain findings advise."""
    _on(tmp_path, monkeypatch)
    result = _write(tmp_path, AGENT, tmp_path, rel="agents/demo.md")
    assert result.returncode == 0, result.stderr
    assert "advisory, agent definition" in result.stderr


def test_same_content_blocks_outside_a_template_path(tmp_path, monkeypatch):
    _on(tmp_path, monkeypatch)
    result = _write(tmp_path, AGENT, tmp_path, rel="notes/demo.md")
    assert result.returncode == 2


def test_opt_out_marker_on_disk_covers_an_edit(tmp_path, monkeypatch):
    """An Edit carries only new_string, so the marker is read from the file."""
    _on(tmp_path, monkeypatch)
    doc = tmp_path.parent / f"{tmp_path.name}-project" / "notes" / "form.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("<!-- plain: off -->\n\nBody.\n", encoding="utf-8")
    new = "\n\n".join(["One short line." for _ in range(8)])
    result = _write(tmp_path, new, tmp_path, rel="notes/form.md", tool="Edit")
    assert result.returncode == 0, result.stderr
    assert "advisory, plain: off marker" in result.stderr


def test_turn_override_lets_a_long_doc_through(tmp_path, monkeypatch):
    _on(tmp_path, monkeypatch)
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n"
                 + json.dumps({"type": "assistant", "message": {"content": [
                     {"type": "text", "text": "[override-plain-mode: fixed report template here]"}]}})
                 + "\n", encoding="utf-8")
    result = _write(tmp_path, AGENT, tmp_path, rel="notes/demo.md", transcript=str(t))
    assert result.returncode == 0, result.stderr
    assert "override this turn" in result.stderr
