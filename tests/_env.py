"""Environment helpers that redirect the home directory on every platform.

Six test modules isolated themselves by setting HOME to a tmp_path, so a hook
would write its state under the temporary directory instead of the real
~/.claude. That works on Linux and does nothing on Windows.

`Path.home()` calls `os.path.expanduser("~")`, and CPython's ntpath version
reads USERPROFILE, then HOMEDRIVE with HOMEPATH. It never reads HOME. So every
one of those hooks wrote to the runner's real profile, the tmp_path stayed
empty, and the assertion that read a state file raised FileNotFoundError.
Roughly 15 of the 37 failures on the first Windows CI run trace to this.

Windows also needs a few variables present or a child process fails to start at
all, so `home_env` carries them through when the caller replaces the whole
environment.

PATH stays the caller's business. test_self_maintenance sets it empty on
purpose, because resolve_claude_bin() probes an absolute path and a PATH-only
guard still starts a real agent. Overriding that here would defeat the guard.
"""
import os
from pathlib import Path

# Absent from a child environment, these make Windows fail to start a process
# or resolve a temp directory. Harmless to carry on any platform.
_WINDOWS_ESSENTIALS = ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")


def home_env(home, **extra) -> dict:
    """A child environment whose home directory really is `home`.

    Pass PATH yourself when the test depends on its value.
    """
    env = {"HOME": str(home), "USERPROFILE": str(home),
           "WRITING_FLOW_HOME": str(home),
           "WRITING_FLOW_STATE_DIR": str(Path(home) / ".claude" / "writing-flow" / "state"),
           "WRITING_FLOW_CONFIG": str(Path(home) / ".claude" / "writing-flow" / "config.json")}
    if os.name == "nt":
        for key in _WINDOWS_ESSENTIALS:
            value = os.environ.get(key)
            if value:
                env[key] = value
    env.update({k: str(v) for k, v in extra.items()})
    return env


def set_home(monkeypatch, home) -> None:
    """Point Path.home() at `home` for the current process, on any platform."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def assert_home_redirects(home) -> None:
    """Guard against this helper silently regressing.

    A test that sets the wrong variable still passes on Linux, which is exactly
    how the gap survived until a Windows runner existed.
    """
    assert Path.home() == Path(home), (
        f"Path.home() is {Path.home()}, not {home}. The home redirect failed, "
        "so this test would read and write the real profile."
    )
