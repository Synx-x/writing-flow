"""response_audit's plain branch: while plain mode is on, the plain caps
replace the flow gate and block a reply that breaks them.

They replace the flow gate only. The tier-1, AI-ism, personal-style,
verbosity and grounded-response checks are not writing-flow, and an
ungrounded claim is wrong in any mode."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_state
from hooks import response_audit

TIER1 = "lever" + "age"


def _long_sentence():
    return " ".join(["word"] * 30) + "."


def test_plain_off_leaves_findings_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    findings = response_audit.compute_findings("", text=_long_sentence(),
                                               session_id="s1")
    assert not any("Plain:" in d for _sev, d in findings)


def test_plain_on_flags_the_long_sentence(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    findings = response_audit.compute_findings("", text=_long_sentence(),
                                               session_id="s1")
    assert any("Plain:" in d for _sev, d in findings)


def test_plain_on_passes_clean_text(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    text = "Rain fell all morning.\n\nThe river rose by noon."
    findings = response_audit.compute_findings("", text=text, session_id="s1")
    assert not any("Plain:" in d for _sev, d in findings)


def test_gloss_is_remembered_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    first = "A hook (a script that runs on its own) fired here."
    response_audit.compute_findings("", text=first, session_id="s1")
    second = "The hook fired again today."
    findings = response_audit.compute_findings("", text=second, session_id="s1")
    assert not any("gloss" in d for _sev, d in findings)


def test_tier1_still_caught_while_plain_is_on(tmp_path, monkeypatch):
    """Plain mode replaces the flow gate, not the anti-slop checks. A banned
    word is wrong in plain mode too."""
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    text = f"We should {TIER1} this.\n\nIt fits the plan."
    findings = response_audit.compute_findings("", text=text, session_id="s1")
    assert any(TIER1 in d for _sev, d in findings)


def test_override_token_lifts_plain_caps_for_the_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    text = _long_sentence() + "\n\n[override-plain-mode: five-way comparison needs one table]"
    findings = response_audit.compute_findings("", text=text, session_id="s1")
    assert not any("Plain:" in d for _sev, d in findings)


def test_override_without_a_reason_does_not_count(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    text = _long_sentence() + "\n\n[override-plain-mode: table]"
    findings = response_audit.compute_findings("", text=text, session_id="s1")
    assert any("Plain:" in d for _sev, d in findings)


def test_override_leaves_tier1_checks_running(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    plain_state.set_active(True)
    text = (f"We {TIER1} the cache here.\n\n"
            "[override-plain-mode: five-way comparison needs one table]")
    findings = response_audit.compute_findings("", text=text, session_id="s1")
    assert findings
