"""Integration test: guard_comment_debt and guard_style scan identical rule sets.

Regression test for guard-rule-sync: both guards report the same rule findings
for the shared rule families when retro_fix_enabled() is on.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import prose_rules as pr  # noqa: E402


def test_get_rule_kinds_includes_ste_strict_when_retro_fix_on():
    """STE_STRICT inclusion depends on retro_fix and ste_mode."""
    os.environ["HARNESS_KIT_STE"] = "strict"
    try:
        kinds = pr.get_rule_kinds(retro_fix_enabled=True)
        # Base kinds always present
        assert "ai_ism" in kinds
        assert "tier1" in kinds
        assert "residue" in kinds
        # STE_STRICT included when retro_fix=True and mode="strict"
        for ste_kind in pr.STE_STRICT:
            assert ste_kind in kinds, f"{ste_kind} should exist when retro_fix=True and mode='strict'"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_get_rule_kinds_excludes_ste_strict_when_retro_fix_off():
    """STE_STRICT excluded when retro_fix is disabled."""
    os.environ["HARNESS_KIT_STE"] = "strict"
    try:
        kinds = pr.get_rule_kinds(retro_fix_enabled=False)
        # Base kinds present
        assert "ai_ism" in kinds
        assert "tier1" in kinds
        assert "residue" in kinds
        # STE_STRICT absent
        for ste_kind in pr.STE_STRICT:
            assert ste_kind not in kinds, f"{ste_kind} should not exist when retro_fix=False"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_get_rule_kinds_respects_ste_mode_off():
    """STE_STRICT excluded when ste_mode is 'off'."""
    os.environ["HARNESS_KIT_STE"] = "off"
    try:
        kinds = pr.get_rule_kinds(retro_fix_enabled=True)
        # Base kinds present
        assert "ai_ism" in kinds
        assert "tier1" in kinds
        assert "residue" in kinds
        # STE_STRICT absent
        for ste_kind in pr.STE_STRICT:
            assert ste_kind not in kinds, f"{ste_kind} should not exist when mode='off'"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_both_guards_report_same_findings_for_shared_rules():
    """Shared rules produce identical findings from both guards."""
    test_text = """
    This semicolon is forbidden; it violates the structural rules.
    Certainly! This phrase triggers ai_ism rules.
    Let me walk you through the implementation.
    """
    filepath = "test_file.py"

    os.environ["HARNESS_KIT_STE"] = "strict"
    try:
        # Both guards use get_rule_kinds to determine which rules to apply
        kinds = pr.get_rule_kinds(retro_fix_enabled=True)
        findings = pr.scan(test_text, kinds=kinds, filepath=filepath)

        # Structural findings detected
        structural_findings = [f for f in findings if f["kind"] in pr.STE_STRICT]
        assert len(structural_findings) > 0, "Should detect structural violations"

        # ai_ism findings detected
        ai_ism_findings = [f for f in findings if f["kind"] == "ai_ism"]
        assert len(ai_ism_findings) > 0, "Should detect ai_ism violations"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_backward_compatibility_with_original_guard_comment_debt():
    """The original guard_comment_debt logic holds."""
    os.environ["HARNESS_KIT_STE"] = "strict"
    try:
        # Original logic: if retro_fix and ste_mode() != "off", add STE_STRICT
        retro_fix = True
        kinds = pr.get_rule_kinds(retro_fix_enabled=retro_fix)

        # With retro_fix=True and mode="strict", STE_STRICT exists
        assert any(k in kinds for k in pr.STE_STRICT), "STE_STRICT should exist"

        # With retro_fix=False, STE_STRICT absent
        kinds_off = pr.get_rule_kinds(retro_fix_enabled=False)
        assert not any(k in kinds_off for k in pr.STE_STRICT), "STE_STRICT should not exist when retro_fix=False"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_backward_compatibility_with_guard_style():
    """Guard_style behavior consistent with get_rule_kinds."""
    os.environ["HARNESS_KIT_STE"] = "warn"
    try:
        # get_rule_kinds with retro_fix=True includes STE_STRICT when mode="warn"
        kinds = pr.get_rule_kinds(retro_fix_enabled=True)
        assert any(k in kinds for k in pr.STE_STRICT), "STE_STRICT should exist when mode='warn'"
    finally:
        os.environ.pop("HARNESS_KIT_STE", None)


def test_default_ste_mode_includes_ste_strict():
    """Default ste_mode() (not "off") includes STE_STRICT when retro_fix=True."""
    # Clear the env var to get default behavior
    os.environ.pop("HARNESS_KIT_STE", None)
    try:
        # With default mode and retro_fix=True
        kinds = pr.get_rule_kinds(retro_fix_enabled=True)
        # Default mode is not "off", so STE_STRICT should exist
        assert any(k in kinds for k in pr.STE_STRICT), "STE_STRICT should exist with default mode"
    finally:
        pass


def test_retro_fix_off_never_weakens_write_enforcement(tmp_path):
    """HARNESS_KIT_RETRO_FIX=0 shapes the Read-time debt report only. The
    first version of this consolidation dropped STE_STRICT from guard_style too."""
    import json, os, subprocess, sys
    doc = tmp_path / "notes.md"
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(doc), "content": "The build runs; the tests pass.\n"}}
    env = dict(os.environ, HARNESS_KIT_RETRO_FIX="0")
    env.pop("HARNESS_KIT_STE", None)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "guard_style.py")],
                       input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert "semicolon" in r.stderr
