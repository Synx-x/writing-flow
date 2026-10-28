"""guard_flow.py: PreToolUse reader-expectation checks on prose files.

Companion to test_guard_style_gaps.py. That hook checks vocabulary and
ASD-STE100 form. This one checks information flow: topic position, old
before new, one anchor per paragraph, Index then Discussion.

Unit tests run flow_rules over the fixture set. E2e tests drive the hook as
a subprocess with a stdin payload, the way Claude Code runs it. Ground truth
in fixtures/fixtures_flow.json comes from William Fitzpatrick's Writer
Science video and writing-tools library. Verdicts are the source author's.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _env import home_env

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "guard_flow.py"
LIB = ROOT / "hooks" / "lib"

sys.path.insert(0, str(LIB))
from writing_flow import flow_rules  # noqa: E402

ALL_FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "fixtures_flow.json").read_text(encoding="utf-8"))["fixtures"]
# Only the author tier is asserted. Panel passages carry a judge's opinion.
FIXTURES = [f for f in ALL_FIXTURES if f.get("tier", "author") == "author"]
GOOD = [f for f in FIXTURES if f["verdict"] == "good"]
BAD = [f for f in FIXTURES if f["verdict"] == "bad" and f["expected_findings"]]

# Bad passages the linter is known to miss, with the reason. A fix that
# catches one of these should remove it here so the test starts asserting.
KNOWN_MISSES = {
    "fractal_bad_paragraph_no_index": "the point arrives late but the opener is a plain subject; no surface cue",
}


def run_hook(payload, tmp_path, env_extra=None):
    env = home_env(tmp_path)
    env.pop("HARNESS_KIT_FLOW", None)
    env.pop("HARNESS_KIT_SKIP_FLOW_CHECK", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def write_payload(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def by_id(fid):
    return next(f for f in FIXTURES if f["id"] == fid)


# ----- unit: flow_rules over the fixture set -----

@pytest.mark.parametrize("fx", GOOD, ids=[f["id"] for f in GOOD])
def test_good_passages_stay_clean(fx):
    kinds = sorted(set(f["kind"] for f in flow_rules.scan_flow(fx["text"])))
    assert kinds == [], f"{fx['id']} flagged: {kinds}"


@pytest.mark.parametrize("fx", BAD, ids=[f["id"] for f in BAD])
def test_bad_passages_yield_an_expected_kind(fx):
    if fx["id"] in KNOWN_MISSES:
        pytest.xfail(KNOWN_MISSES[fx["id"]])
    got = set(f["kind"] for f in flow_rules.scan_flow(fx["text"]))
    assert got & set(fx["expected_findings"]), (
        f"{fx['id']}: expected one of {fx['expected_findings']}, got {sorted(got)}"
    )


def test_every_finding_has_the_prose_rules_shape():
    for fx in BAD:
        for f in flow_rules.scan_flow(fx["text"]):
            assert set(f) >= {"kind", "label", "match", "line"}
            assert f["kind"] in flow_rules.ALL_KINDS
            assert f["label"]


def test_vague_heading_fires_on_markdown_headings():
    text = "# Background\n\nSome text here.\n\n## Why misinformation resists fact checking\n\nMore text."
    kinds = [f["kind"] for f in flow_rules.scan_flow(text)]
    assert kinds.count("vague_heading") == 1


def test_topics_helper_returns_one_entry_per_sentence():
    fx = by_id("constant_theme_good")
    tops = flow_rules.topics(fx["text"])
    assert len(tops) == 5
    assert tops[0].lower().startswith("happiness")


def test_scan_is_fast_on_long_input():
    import time
    text = "\n\n".join(by_id("linking_bad_no_anchor")["text"] for _ in range(300))
    start = time.perf_counter()
    flow_rules.scan_flow(text)
    assert time.perf_counter() - start < 3.0


# ----- e2e: the hook as Claude Code and Codex run it -----

def test_non_prose_path_is_skipped(tmp_path):
    res = run_hook(write_payload(str(tmp_path / "thing.py"), by_id("linking_bad_no_anchor")["text"]), tmp_path)
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_output_styles_path_is_exempt(tmp_path):
    d = tmp_path / ".claude" / "output-styles"
    d.mkdir(parents=True)
    res = run_hook(write_payload(str(d / "flow.md"), by_id("linking_bad_no_anchor")["text"]), tmp_path)
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_good_prose_is_silent(tmp_path):
    res = run_hook(write_payload(str(tmp_path / "doc.md"), by_id("constant_theme_good")["text"]), tmp_path)
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_warn_mode_emits_additional_context(tmp_path):
    res = run_hook(write_payload(str(tmp_path / "doc.md"), by_id("linking_bad_no_anchor")["text"]), tmp_path,
                   {"WRITING_FLOW_FLOW": "warn"})
    assert res.returncode == 0
    out = json.loads(res.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "FLOW NOTICE" in ctx and "anchor" in ctx


def test_strict_mode_blocks(tmp_path):
    res = run_hook(
        write_payload(str(tmp_path / "doc.md"), by_id("linking_bad_no_anchor")["text"]),
        tmp_path,
        {"HARNESS_KIT_FLOW": "strict"},
    )
    assert res.returncode == 2
    assert "FLOW VIOLATION" in res.stderr and "anchor" in res.stderr


def test_off_mode_is_silent(tmp_path):
    res = run_hook(
        write_payload(str(tmp_path / "doc.md"), by_id("linking_bad_no_anchor")["text"]),
        tmp_path,
        {"HARNESS_KIT_FLOW": "off"},
    )
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_yaml_frontmatter_not_scanned():
    """YAML frontmatter with long description should stay clean."""
    text = """---
name: some-skill
description: Some sentence describing the skill that runs past ten words before any verb appears
metadata:
  type: project
---

First paragraph with good flow. This has structure and makes sense.
"""
    kinds = [f["kind"] for f in flow_rules.scan_flow(text)]
    assert "long_runway" not in kinds


def test_multiline_yaml_frontmatter_not_scanned():
    """Multi-line YAML frontmatter stays excluded."""
    text = """---
name: test-skill
description: This is a very long description that would definitely trigger the long runway
  rule if it were scanned as prose because it has many words before any verb
metadata:
  type: project
  tags:
    - test
    - sample
---

Body text with proper flow and structure here.
"""
    kinds = [f["kind"] for f in flow_rules.scan_flow(text)]
    assert "long_runway" not in kinds


def test_no_frontmatter_scans_normally():
    """Files without frontmatter scan for violations."""
    fx = by_id("linking_bad_no_anchor")
    kinds = [f["kind"] for f in flow_rules.scan_flow(fx["text"])]
    assert any(k in kinds for k in fx["expected_findings"])


def test_horizontal_rule_mid_document_not_confused():
    """Mid-document horizontal rules do not get confused with frontmatter."""
    text = """First paragraph with content.

---

Second paragraph after a horizontal rule dividing the sections.
"""
    kinds = [f["kind"] for f in flow_rules.scan_flow(text)]
    assert len(kinds) == 0


def test_skip_env_is_honoured(tmp_path):
    res = run_hook(
        write_payload(str(tmp_path / "doc.md"), by_id("linking_bad_no_anchor")["text"]),
        tmp_path,
        {"HARNESS_KIT_SKIP_FLOW_CHECK": "1"},
    )
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_edit_payload_uses_new_string(tmp_path):
    config_path = tmp_path / ".claude" / "writing-flow" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"hooks": {"guard_flow": {
        "mode": "warn", "kinds": list(flow_rules.ALL_KINDS),
    }}}))
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(tmp_path / "doc.md"),
            "old_string": "a",
            "new_string": by_id("emphasis_bad_long_runway")["text"],
        },
    }
    res = run_hook(payload, tmp_path)
    assert res.returncode == 0
    assert "long runway" in json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("payload", ["not json", "null", "[]", "\"text\"", "42", "true", ""])
def test_odd_stdin_is_silent(payload, tmp_path):
    res = run_hook(payload, tmp_path)
    assert res.returncode == 0 and res.stdout.strip() == "" and res.stderr.strip() == ""


def test_topic_drift_label_names_the_anchor():
    """The label names a real word from the paragraph, not just the drift."""
    text = (
        "The bug is a real defect. It hit both arms of the test. "
        "Six subagent dispatches carried the bug. The evidence sits in the "
        "evolutions log now."
    )
    findings = flow_rules.scan_flow(text, kinds=("topic_drift",))
    assert findings
    label = findings[0]["label"]
    assert "bug" in label.lower()
    assert "no anchor" not in label or "Open most of them on it" in label or "Name one anchor" in label


def test_topic_drift_falls_back_when_no_word_repeats():
    """No repeated content word still returns usable guidance, not a crash."""
    text = (
        "Apples cost more this year. Bicycles need better lanes downtown. "
        "Weather stayed dry through autumn. Music sales dropped again."
    )
    findings = flow_rules.scan_flow(text, kinds=("topic_drift",))
    assert findings
    assert "Name one anchor" in findings[0]["label"]


def test_long_runway_label_names_words_to_move():
    text = "A raw sweep of every single one of the transcripts in both arms found the same shape."
    findings = flow_rules.scan_flow(text, kinds=("long_runway",))
    assert findings
    assert "Move \"" in findings[0]["label"]


def test_codex_adapter_runs_guard_flow(tmp_path):
    """The Codex mirror in hooks.json points at the same hook by name."""
    adapter = ROOT / "adapters" / "codex" / "run_hook.py"
    env = home_env(tmp_path)
    env["HARNESS_KIT_HOOKS_DIR"] = str(ROOT / "hooks")
    codex_event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": str(tmp_path / "doc.md"), "content": by_id("linking_bad_no_anchor")["text"]},
    }
    res = subprocess.run(
        [sys.executable, str(adapter), "guard_flow"],
        input=json.dumps(codex_event),
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    assert res.returncode in (0, 2)
