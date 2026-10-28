#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""
Shared helper for hooks that spawn a detached background worker.

Reuses the exact process-detach shape already proven by
skills_turn_counter.py's spawn_background_reviewer: start_new_session=True
plus all stdio to DEVNULL means the child outlives the parent hook process
(and the run_hook.py dispatcher's blocking wait on it) without hanging the
Claude Code hook timeout.
"""

import os
import subprocess
import sys
from pathlib import Path

# start_new_session (setsid) is POSIX-only: on Windows subprocess.Popen simply
# ignores the kwarg (verified against cpython's subprocess.py — the mswindows
# branch of _execute_child never reads it, so passing it is a silent no-op,
# not an error). CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS is the Windows
# equivalent for a child that outlives its parent and its own console.
# https://docs.python.org/3/library/subprocess.html#subprocess.CREATE_NEW_PROCESS_GROUP
# https://docs.python.org/3/library/subprocess.html#subprocess.DETACHED_PROCESS
_POPEN_KWARGS = (
    {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
    }
    if os.name == "nt"
    else {"start_new_session": True}
)


def spawn_detached(argv: list[str], stdout=None, stderr=None) -> subprocess.Popen:
    """Launch `argv` fully detached from the current hook process.

    Generic form of spawn_worker for callers whose target isn't "re-invoke
    this same script with --worker" (e.g. running a different script under
    the same interpreter). stdout/stderr default to DEVNULL. Pass an open
    file handle to redirect to a log instead. Returns the Popen handle so
    callers that need the child pid (e.g. for a lockfile) can read
    `.pid` — most callers can just discard the return value.
    """
    return subprocess.Popen(
        argv,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=stderr if stderr is not None else subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        **_POPEN_KWARGS,
    )


def spawn_worker(script_path: Path, extra_args: list[str] | None = None) -> None:
    argv = [sys.executable, str(script_path), "--worker", *(extra_args or [])]
    spawn_detached(argv)
