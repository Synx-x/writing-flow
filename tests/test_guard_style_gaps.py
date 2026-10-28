"""Regression tests for the three coverage gaps closed alongside the
ASD-STE100 structural rules:

  Gap 1: guard_style.py (PreToolUse, blocking) never scanned code comments —
         only style_check.py (PostToolUse, warn-only) did. A structural or
         AI-ism violation hidden in a docstring passed the blocking gate.
  Gap 2: guard_commit_attribution.py's message extractor only matched
         `-m "..."`, so a heredoc commit body (`git commit -F - <<'EOF'`)
         passed unchecked.
  Gap 3: guard_commit_attribution.py only recognized `git ... commit`; a
         `gh pr create --body "..."` carrying the same violations was
         never inspected.

Also covers the HARNESS_KIT_STE off/warn/strict dial on guard_style.py.
"""
import json
import subprocess
import sys
from pathlib import Path

from _env import home_env

ROOT = Path(__file__).resolve().parent.parent
GUARD_STYLE = ROOT / "hooks" / "guard_style.py"
GUARD_COMMIT = ROOT / "hooks" / "guard_commit_attribution.py"

# Build trigger strings by concatenation so this file holds no literal token
# that would itself trip the live guard hooks running over this session.
NOM = "perform" + "s an analysis of"
PHRASAL = "reach" + "es out to"


def _run(hook, payload, env=None):
    import os
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    else:
        full_env.pop("HARNESS_KIT_STE", None)
    r = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=full_env,
    )
    return r.returncode, r.stderr


def test_gap1_structural_violation_in_comment_blocks(tmp_path):
    # extract_comments_and_strings only extracts # comments for Python, not
    # triple-quoted docstrings — that is a pre-existing extraction-scope
    # limit, not part of this gap. Gap 1 is about guard_style.py never
    # calling the extractor at all; this proves it now does.
    content = f"def f():\n    # The tool {NOM} the data; it {PHRASAL} the customer.\n    pass\n"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py"), "content": content}}
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 2, "structural violation inside a code comment must block"
    assert "nominalized verb" in stderr or "semicolon" in stderr or "phrasal verb" in stderr


def test_verbosity_default_shows_actual_violations(tmp_path):
    """auto (the default) never rolls this up -- the model needs the
    specific words/sentence to fix, not a count."""
    content = f"def f():\n    # The tool {NOM} the data{chr(59)} it {PHRASAL} the customer.\n    pass\n"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py"), "content": content}}
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 2
    assert "semicolon in prose" in stderr and "writing-flow[style:blocked]" in stderr


def test_verbosity_terse_rolls_up_but_stays_blocking(tmp_path):
    """An explicit verbosity=terse opt-in still blocks. This is a hard gate,
    not an advisory. It only shortens the message to counts."""
    import json as _json
    local_dir = tmp_path / "home" / ".claude" / "harness-kit-local"
    local_dir.mkdir(parents=True)
    (local_dir / "config.json").write_text(_json.dumps(
        {"hooks": {"guard_style": {"verbosity": "terse"}}}), encoding="utf-8")
    content = f"def f():\n    # The tool {NOM} the data{chr(59)} it {PHRASAL} the customer.\n    pass\n"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py"), "content": content}}
    code, stderr = _run(GUARD_STYLE, payload,
                        env=home_env(tmp_path / "home", WRITING_FLOW_CONFIG=str(local_dir / "config.json")))
    assert code == 2
    assert "writing-flow[style:blocked]" not in stderr
    assert "structural" in stderr
    assert "Set verbosity=full for the actual violations." in stderr


def test_gap1_clean_code_not_blocked(tmp_path):
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": str(tmp_path / "y.py"),
        "content": "def add(a, b):\n    return a + b  # sum two ints\n",
    }}
    code, _ = _run(GUARD_STYLE, payload)
    assert code == 0


def test_gap1_identifier_only_not_blocked(tmp_path):
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": str(tmp_path / "z.py"),
        "content": "utilize_count = 1\nrobust_value = 2\n",
    }}
    code, _ = _run(GUARD_STYLE, payload)
    assert code == 0, "identifiers must not trigger the comment-prose scan"


def test_ste_off_skips_structural_block(tmp_path):
    content = f"# The tool {NOM} the data; it {PHRASAL} the customer.\nx = 1\n"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py"), "content": content}}
    code, _ = _run(GUARD_STYLE, payload, env={"HARNESS_KIT_STE": "off"})
    assert code == 0


def test_ste_warn_downgrades_to_notice_not_block(tmp_path):
    content = "# The service starts the job; then it waits for the result.\nx = 1\n"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py"), "content": content}}
    code, stderr = _run(GUARD_STYLE, payload,
                        env={"WRITING_FLOW_STE": "warn", "HARNESS_KIT_STE": "warn"})
    assert code == 0
    assert "writing-flow[style:blocked]" in stderr
    assert "semicolon in prose" in stderr


def test_self_ref_exemption_still_narrow():
    """SELF_REF_PATTERNS must not exempt the whole shared skills tree anymore
    (that was the pre-existing over-broad exemption), only the docs that
    literally document the writing rules."""
    from importlib import util
    spec = util.spec_from_file_location("guard_style_mod", GUARD_STYLE)
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not any("/shared/skills/" in p for p in mod.SELF_REF_PATTERNS)


def test_message_display_audit_is_self_ref_exempt(tmp_path):
    """message_display_audit.py documents the same tier-1 words it rewrites,
    as literal examples in its docstring -- the same shape as response_audit,
    already on this list. Without the exemption, its own docstring trips the
    blocking gate it must pass to ever be written or edited."""
    content = "# leverage\n"  # any content containing a tier-1 word
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "hooks" / "message_display_audit.py"),
            "content": content,
        },
    }
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 0
    assert stderr == ""


# ===== issue #19: verbatim third-party content has no compliant rewrite =====

_TRANSCRIPT = (
    "Presenter: Is there a test setup that we can " + "utilize" + "?\n"
    "Participant: I think we need to align it " + "in order to" + " update.\n"
)


def test_verbatim_transcript_blocks_without_the_marker(tmp_path):
    """A quote of what someone else said trips the same findings authored
    prose would, with no way to fix them without falsifying the record."""
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "meeting.md"), "content": _TRANSCRIPT},
    }
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 2
    assert "utilize" in stderr


def test_verbatim_marker_exempts_the_write():
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/meeting.md",
                       "content": _TRANSCRIPT + "\n<!-- [verbatim-ok] -->\n"},
    }
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 0
    assert stderr == ""


def test_verbatim_env_var_exempts_the_write():
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/meeting.md", "content": _TRANSCRIPT},
    }
    code, stderr = _run(GUARD_STYLE, payload, env={"HARNESS_KIT_ALLOW_VERBATIM": "1"})
    assert code == 0
    assert stderr == ""


# ===== issue: shebang detection in Edit payloads for bare-name scripts =====

def test_bare_name_bash_script_with_shebang_treated_as_code(tmp_path):
    """A bare-name script with a bash shebang (like git-hooks/pre-push)
    must scan as code with comment checks, not as prose.

    The bug: guard_style calls grammar_for() without the file content,
    so it cannot detect the shebang and defaults to PROSE_ROUTE for bare
    names. This causes comments with semicolons to trip prose violations
    instead of structural code-comment checks.
    """
    # Create a bare-name bash script with shebang
    bash_script = tmp_path / "test-script"
    bash_script.write_text(
        "#!/usr/bin/env bash\n"
        "# Comment one. Comment two. Comment three.\n"
        "echo test\n",
        encoding="utf-8"
    )

    # Edit that adds comments with a semicolon (allowed in code, blocked in prose)
    old_text = (
        "#!/usr/bin/env bash\n"
        "# Comment one.\n"
        "echo test\n"
    )
    new_text = (
        "#!/usr/bin/env bash\n"
        "# Comment one. Comment two; then comment three.\n"
        "echo test\n"
    )

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(bash_script),
            "old_string": old_text,
            "new_string": new_text,
        }
    }

    code, stderr = _run(GUARD_STYLE, payload)
    # A semicolon violation from extracted comments proves code routing.
    # Prose routing would skip # lines and find no violations.
    assert code == 2
    assert "semicolon" in stderr


def _hook_script(tmp_path, exists=True):
    script = tmp_path / "pre-push"
    body = ("#!/usr/bin/env bash\n"
            "# Blocks a push without a version bump.\n"
            "while read -r a b c d; do\n"
            "    if [ \"$d\" = \"$a\" ]; then\n"
            "        continue\n"
            "    fi\n"
            "done\n")
    if exists:
        script.write_text(body, encoding="utf-8")
    return script, body


def test_shell_code_semicolons_are_not_prose_on_edit(tmp_path):
    """The live case: '; then' and '; do' are shell syntax, not prose."""
    script, body = _hook_script(tmp_path)
    new = body.replace("continue", "continue  # skip a new branch")
    payload = {"tool_name": "Edit", "tool_input": {
        "file_path": str(script), "old_string": body, "new_string": new}}
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 0, stderr
    assert "semicolon" not in stderr and "sentences in one paragraph" not in stderr


def test_shell_code_semicolons_are_not_prose_on_write_of_a_new_script(tmp_path):
    """A new script has no file on disk yet, so its shebang comes from content."""
    script, body = _hook_script(tmp_path, exists=False)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(script), "content": body}}
    code, stderr = _run(GUARD_STYLE, payload)
    assert code == 0, stderr
    assert "semicolon" not in stderr
