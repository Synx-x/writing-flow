"""The active Claude Code output style, and the chat rules it exempts.

Claude Code reads outputStyle from settings.json and loads
~/.claude/output-styles/<name>.md. flow_reinforce needs the file to build its
reminder. response_audit needs what the style says about chat: the operator's
writing-flow style states "Word caps and the semicolon ban do not apply to
chat", yet the chat-form checks hard-coded both and blocked 98 replies over
them (75 sentence-length, 23 semicolon) across the local transcripts measured
on 2026-09-23 with scripts/audit_finding_stats.py.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from . import paths

# "<rules> do not apply to chat". The rules part is read for known names.
_EXEMPTION_SENTENCE = re.compile(r"([^.\n]*?)\s+do(?:es)?\s+not\s+apply\s+to\s+chat", re.I)
_RULE_NAMES = (
    ("semicolon", re.compile(r"semicolon", re.I)),
    ("word_caps", re.compile(r"\bword\s+caps?\b|\bsentence\s+caps?\b|\blength\s+caps?\b", re.I)),
)


def active_style_path():
    """The active style file, checking the plugin copy before the user copy."""
    claude = paths.claude_code_dir()
    try:
        settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = settings.get("outputStyle") if isinstance(settings, dict) else None
    if not name:
        return None
    if name.startswith("writing-flow:"):
        name = name.split(":", 1)[1]
    roots = [Path(__file__).resolve().parents[2] / "output-styles", claude / "output-styles"]
    for directory in roots:
        path = directory / f"{name}.md"
        if path.is_file():
            return path
    return None

def exemptions_in(text: str) -> frozenset:
    """Rule names a style's text exempts from chat."""
    found = set()
    for match in _EXEMPTION_SENTENCE.finditer(text or ""):
        for name, pattern in _RULE_NAMES:
            if pattern.search(match.group(1)):
                found.add(name)
    return frozenset(found)


@lru_cache(maxsize=1)
def chat_exemptions() -> frozenset:
    """Rule names the active style exempts from chat. Empty when unknown."""
    path = active_style_path()
    if path is None:
        return frozenset()
    try:
        return exemptions_in(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return frozenset()
