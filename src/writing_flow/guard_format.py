"""One block format for every blocking guard.

    harness-kit[style:blocked]: agents/meta-pr-publisher.md, 2 to fix
      1 chatbot phrase "certainly!"
        fix: cut it
      2 line 37: chat wording "lets"
        fix: state the fact instead
      advice (not blocking): 1 plain-mode note

Each guard had its own shape before. Headers were in capitals, the rule code
came before the fix, and a terminal cut long absolute paths in the middle.
Advice sat mixed with blocking findings. The model reads the same block, so a
clear block also gets fixed on the first try.
"""
from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

from . import paths as kit_paths

WIDTH = 72
# The guard file behind each component, for readers that count blocks per guard.
GUARDS = {"style": "guard_style.py", "shell-write": "bash_write_router.py",
          "paths": "guard_protected_paths.py", "audit": "response_audit.py"}
HEAD = re.compile(r"^harness-kit\[(?P<component>[a-z-]+):(?P<stage>[a-z-]+)\]: (?P<text>.*)$")
ITEM = re.compile(r"^  (?P<n>\d+) (?P<text>.+)$")
FIX = re.compile(r"^    fix: (?P<fix>.+)$")


def short_path(path: str | os.PathLike | None, root: str | os.PathLike | None = None) -> str:
    """A path relative to the project, else with ~ for home, so it never wraps."""
    if not path:
        return ""
    text = str(path)
    for base in (root, os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not base:
            continue
        try:
            rel = os.path.relpath(text, str(base))
        except ValueError:
            continue
        if not rel.startswith(".."):
            return rel
    home = str(kit_paths.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def _wrap(text: str, indent: str) -> list[str]:
    return _tw(text, indent, indent + "  ")


def _tw(text: str, first: str, rest: str) -> list[str]:
    # Tokens such as flow-override-CHAT or a file path must stay whole, or a
    # reader that searches the block for them misses a split one.
    return textwrap.wrap(text, WIDTH, initial_indent=first, subsequent_indent=rest,
                         break_on_hyphens=False, break_long_words=False) or [first + text]


def split_fix(label: str) -> tuple[str, str]:
    """Split "Plain: 9 paragraphs, cap 4. Cut a part." into the finding and its fix."""
    head, sep, rest = label.partition(". ")
    if sep and rest and rest[0].isupper():
        return head.rstrip("."), rest.rstrip(".")
    return label.rstrip("."), ""


def render(component: str, subject: str, items: list[tuple[str, str]], advice: list[str] | None = None,
           notes: list[str] | None = None, stage: str = "blocked") -> str:
    """The block: a headline, numbered findings each with its fix, then advice and notes."""
    count = len(items)
    head = f"harness-kit[{component}:{stage}]: {subject}"
    if count:
        head += f", {count} to fix"
    lines = [head]
    for n, (text, fix) in enumerate(items, 1):
        lines += _tw(text, f"  {n} ", "    ")
        if fix:
            lines += _wrap(f"fix: {fix}", "    ")
    if advice:
        lines += _wrap("advice (not blocking): " + "; ".join(advice), "  ")
    for note in notes or []:
        lines += _wrap(note, "  ")
    return "\n".join(lines)


def parse(text: str) -> tuple[str, str, list[str]] | None:
    """(component, headline text, findings) of a rendered block, or None.

    A finding joins its text and fix, as in "Plain: 9 paragraphs, cap 4. Cut a
    part", so a reader of old blocks and new ones sees the same strings.
    """
    raw = text.splitlines()
    at = next((i for i, line in enumerate(raw) if HEAD.match(line.strip())), None)
    if at is None:
        return None
    # The Stop gate indents each hook's block, so strip the headline's indent.
    indent = len(raw[at]) - len(raw[at].lstrip())
    lines = [line[indent:] if line[:indent].strip() == "" else line for line in raw[at:]]
    head = HEAD.match(lines[0])
    findings: list[str] = []
    for line in lines:
        if m := ITEM.match(line):
            findings.append(m.group("text"))
        elif (m := FIX.match(line)) and findings:
            fix = m.group("fix")
            findings[-1] = f"{findings[-1]}. {fix[:1].upper() + fix[1:]}"
        elif line.startswith("    ") and not line.startswith("      ") and findings:
            findings[-1] += " " + line.strip()
    return head.group("component"), head.group("text"), findings
