"""Input and project-root helpers used by standalone hooks."""
import json
import os
import subprocess
import sys
from pathlib import Path


def read_hook_stdin() -> dict:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def get_project_root(hook_input: dict | None = None) -> Path:
    from .paths import home
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured and Path(configured).is_dir():
        return Path(configured)
    if hook_input and hook_input.get("cwd") and Path(hook_input["cwd"]).is_dir():
        return Path(hook_input["cwd"])
    try:
        root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
        if root:
            return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path.cwd()
