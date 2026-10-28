"""Command-position parsing for the git guards (issue #16 false positive #1).

The reported defect: a heredoc that wrote a `.md` file was blocked because its
body contained staging and committing verbs near the path. No git command was
invoked. These tests pin the distinction between a git command and text that
merely looks like one.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import git_command as gc  # noqa: E402

HEREDOC_WRITE = (
    "cat > notes.md <<'EOF'\n"
    "remember to stage and commit this .md file\n"
    "EOF"
)


def test_heredoc_body_is_not_a_git_command():
    """The reported false positive. No git invocation here at all."""
    assert gc.git_invocations(HEREDOC_WRITE, "add") == []
    assert gc.git_invocations(HEREDOC_WRITE, "commit") == []
    assert not gc.is_git_subcommand(HEREDOC_WRITE, "add")


def test_heredoc_body_is_replaced_not_kept():
    stripped = gc.strip_heredocs(HEREDOC_WRITE)
    assert "stage and commit" not in stripped
    assert "notes.md" in stripped  # the command itself survives


def test_unterminated_heredoc_drops_the_body():
    cmd = "cat > a.md <<'EOF'\nstage and commit\n"
    assert "stage and commit" not in gc.strip_heredocs(cmd)


def test_dash_form_heredoc_with_tab_indented_terminator():
    cmd = "cat > a.md <<-EOF\n\tstage and commit\n\tEOF\necho done"
    stripped = gc.strip_heredocs(cmd)
    assert "stage and commit" not in stripped
    assert "echo done" in stripped


def test_real_git_add_is_detected():
    assert gc.git_invocations("git add notes.md", "add") == ["notes.md"]


@pytest.mark.parametrize("cmd", [
    "sudo git add b.md",
    "GIT_DIR=x git add b.md",
    "git -C /repo add b.md",
])
def test_git_prefixes_still_parse(cmd):
    assert gc.git_invocations(cmd, "add") == ["b.md"]


def test_chained_commands_each_parse():
    cmd = "git add . && git commit -m 'msg'"
    assert gc.git_invocations(cmd, "add") == ["."]
    assert gc.git_invocations(cmd, "commit") == ["-m 'msg'"]


def test_echoed_command_is_not_a_command():
    assert gc.git_invocations("echo 'git add x.md'", "add") == []


def test_subcommand_named_inside_a_commit_message_is_not_an_invocation():
    cmd = 'git commit -m "fix: git add docs.md mention"'
    assert gc.git_invocations(cmd, "add") == []
    assert gc.git_invocations(cmd, "commit")


def test_quoted_message_stays_one_token():
    args = gc.git_invocations('git commit -m "two words here"', "commit")[0]
    assert gc.unquoted_args(args) == ["-m", "two words here"]


def test_unquoted_args_splits_plain_paths():
    assert gc.unquoted_args("a.md b.md -f") == ["a.md", "b.md", "-f"]
