"""shell_argv yields the argv of each command a shell string would run."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import git_command  # noqa: E402
from writing_flow import shell_argv  # noqa: E402


def words(command):
    return [argv[0] for argv in shell_argv.command_argvs(command)]


def test_quoted_text_stays_one_argument():
    assert shell_argv.command_argvs("grep -n 'a b c' f") == [["grep", "-n", "a b c", "f"]]


def test_operators_split_commands():
    assert words("a && b || c | d & e; f") == ["a", "b", "c", "d", "e", "f"]


def test_redirections_and_fd_numbers_are_dropped():
    assert shell_argv.command_argvs("ls x 2>/dev/null >out.txt") == [["ls", "x"]]


def test_wrappers_unwrap_to_the_real_command():
    assert shell_argv.command_argvs("sudo -u root env A=1 nice -n 5 /bin/ls -l") == [
        ["/bin/ls", "-l"]]


def test_substitutions_expose_the_inner_command():
    assert "rm" in words("echo $(rm x)")
    assert "rm" in words("echo `rm x`")


def test_shell_c_eval_ssh_and_find_exec_recurse():
    assert "rm" in words("bash -lc 'rm x'")
    assert "rm" in words("eval 'rm x'")
    assert "rm" in words("ssh -p 22 host 'rm x'")
    argvs = shell_argv.command_argvs("find /data -exec rm {} +")
    assert ["rm", "/data"] in argvs


def test_heredoc_bodies_are_data_unless_a_shell_reads_them():
    assert words("cat > f <<'EOF'\nrm x\nEOF") == ["cat"]
    assert "rm" in words("bash <<'EOF'\nrm x\nEOF")
    assert "rm" in words("cat <<'EOF' | sh\nrm x\nEOF")


def test_unbalanced_quote_raises_for_the_fallback():
    with pytest.raises(ValueError):
        shell_argv.command_argvs("echo 'open")


def test_strip_heredocs_keeps_the_opener_line_and_is_idempotent():
    command = "cat <<'EOF' > out.txt\nbody > here\nEOF\necho done"
    once = git_command.strip_heredocs(command)
    assert "> out.txt" in once
    assert "body" not in once
    assert "echo done" in once
    assert git_command.strip_heredocs(once) == once


def test_git_subcommand_skips_global_options():
    assert git_command.git_subcommand(["-C", "/r", "-c", "a=b", "push", "-f"]) == ("push", ["-f"])
    assert git_command.git_subcommand(["--version"]) == ("", [])
