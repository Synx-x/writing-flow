#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""The four checks plain mode enforces.

writing-flow judges where information sits, which serves a reader who
already knows the domain. These checks judge how much arrives at once,
which is what a reader outside the domain needs.

Each check returns (severity, detail) pairs, the shape
response_audit.compute_findings() already returns. Severity is always HARD
because the spec blocks on any finding.

Code blocks, inline code spans, commands and paths are never counted. A
path is not prose and a command cannot be shortened.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from . import prose_rules

SENTENCE_CAP = 20
PARAGRAPH_SENTENCE_CAP = 4
PARAGRAPH_WORD_CAP = 60
CHAIN_CAP = 4

# A cap blocks only on a clear overage. Measured 2026-09-23: the median blocked
# plain sentence ran 1.25x its cap, and its rewrite changed about half the
# reply for a few words over. Smaller overages reach the next turn as SOFT.
HARD_OVERAGE = 1.5


def _severity(value: int, cap: int) -> str:
    return "HARD" if value >= cap * HARD_OVERAGE else "SOFT"

# A curated list, not a pattern. A pattern flags ordinary words and misses
# real jargon. Edit this list rather than widening a regex.
TRACKED_TERMS = [
    "hook", "subagent", "transcript", "compaction", "jsonl",
    "flag file", "gate", "harness", "payload", "stdin",
]

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`]*`")
_HEADING_LINE = re.compile(r"^\s*#{1,6}\s")
_BULLET_LINE = re.compile(r"^\s*[-*+]\s+|^\s*\d+\.\s+")
# A gloss is the term followed by a short parenthetical on the same line.
_GLOSS_WINDOW = 80


# YAML frontmatter at the top of a file is metadata. On 2026-09-23 an agent
# definition's frontmatter held no blank line, so all of it counted as one
# 107-word, 18-sentence paragraph and blocked the write.
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

# A file carries this marker when its shape is fixed by something other than
# the reader, such as a template another tool fills in.
_OPT_OUT = re.compile(r"<!--\s*plain:\s*off\s*-->", re.I)


def _prose_only(text: str) -> str:
    """Text with frontmatter, code blocks and inline spans removed."""
    out = _FRONTMATTER.sub("", text)
    out = _CODE_BLOCK.sub(" ", out)
    return _CODE_SPAN.sub(" ", out)


# A per-turn override the model writes in its own reply, with a reason:
#   [override-plain-mode: comparing five API versions needs one table]
# It lifts the plain caps for that turn only, in the reply audit and in file
# writes. Every other style check still runs. A bare token with no reason
# does not count, so each override states why the scenario needs it.
_OVERRIDE = re.compile(r"\[override-plain-mode:\s*([^\]\n]{3,200})\]", re.I)


def override_reason(text: str) -> str:
    """The stated reason of the first override token in text, or ""."""
    m = _OVERRIDE.search(text or "")
    if not m or len(m.group(1).split()) < 3:
        return ""
    return m.group(1).strip()


def turn_override(transcript_path: str) -> str:
    """The override reason written anywhere in the current turn, or ""."""
    if not transcript_path:
        return ""
    from . import transcript
    return override_reason(transcript.current_turn_assistant_text(transcript_path))


def template_reason(path: str, text: str) -> str:
    """Why a file's plain findings are advisory, or "" when they block.

    Plain mode serves a person reading an answer. An agent definition, a
    SKILL.md, a slash command or an issue template is read by a model that
    follows it section by section. Its length and section count come from the
    template, so a four-paragraph cap cannot fit it. The findings still print,
    so the author sees them and can tighten what the template allows.
    """
    if _OPT_OUT.search(text or ""):
        return "plain: off marker"
    p = Path(path or "")
    parts = p.parts
    if p.name == "SKILL.md":
        return "skill definition"
    if p.suffix == ".md" and p.parent.name == "agents":
        return "agent definition"
    if p.suffix == ".md" and p.parent.name == "commands":
        return "command definition"
    if ".github" in parts and "ISSUE_TEMPLATE" in parts:
        return "issue template"
    if p.name.endswith(".template.md"):
        return "template file"
    return ""


def _is_heading_only(block: str) -> bool:
    lines = [ln for ln in block.split("\n") if ln.strip()]
    return bool(lines) and all(_HEADING_LINE.match(ln) for ln in lines)


def _is_list_block(block: str) -> bool:
    return any(_BULLET_LINE.match(ln) for ln in block.split("\n"))


def _paragraphs(text: str) -> list:
    """Blank-line-separated blocks judged as prose paragraphs.

    A heading line names a section. It carries no content of its own to cap.
    A list block is exempt too: chain_cap's own suggested fix for a long
    chain is "make the middle a list", so a list cannot also be judged as
    an oversized paragraph or another link in the chain it replaces.
    Individual sentences inside a list still answer to sentence_cap, which
    scans raw prose directly rather than going through this function.
    """
    out = []
    for block in _prose_only(text).split("\n\n"):
        block = block.strip()
        if not block or _is_heading_only(block) or _is_list_block(block):
            continue
        out.append(block)
    return out


def sentence_cap(text: str) -> list:
    findings = []
    for sentence in prose_rules._split_sentences(_prose_only(text)):
        count = len(sentence.split())
        if count > SENTENCE_CAP:
            findings.append((
                _severity(count, SENTENCE_CAP),
                f"Plain: {count}-word sentence, cap {SENTENCE_CAP}. "
                f"Split it: '{sentence[:50]}'"
            ))
    return findings


def paragraph_cap(text: str) -> list:
    findings = []
    for para in _paragraphs(text):
        sentences = prose_rules._split_sentences(para)
        words = len(para.split())
        if len(sentences) > PARAGRAPH_SENTENCE_CAP:
            findings.append((
                _severity(len(sentences), PARAGRAPH_SENTENCE_CAP),
                f"Plain: {len(sentences)} sentences in one paragraph, cap "
                f"{PARAGRAPH_SENTENCE_CAP}. Break it after the first point."
            ))
        if words > PARAGRAPH_WORD_CAP:
            findings.append((
                _severity(words, PARAGRAPH_WORD_CAP),
                f"Plain: {words}-word paragraph, cap {PARAGRAPH_WORD_CAP}. "
                "Break it after the first point."
            ))
    return findings


def _sections(text: str) -> list:
    """(heading, body) pairs split at heading lines, frontmatter removed."""
    out, heading, body = [], "", []
    # A "# comment" inside a fenced shell block is not a heading.
    for line in _CODE_BLOCK.sub(" ", _FRONTMATTER.sub("", text)).split("\n"):
        if _HEADING_LINE.match(line):
            out.append((heading, "\n".join(body)))
            heading, body = line.strip().lstrip("#").strip(), []
        else:
            body.append(line)
    out.append((heading, "\n".join(body)))
    return out


def chain_cap(text: str, per_section: bool = False) -> list:
    """A reply is one chain. A file is one chain per heading section.

    A document with ten sections of two paragraphs each reads as ten short
    chains, and its headings already split it for the reader. Counting it
    as one twenty-paragraph chain blocked every real document.
    """
    if not per_section:
        paras = _paragraphs(text)
        if len(paras) > CHAIN_CAP:
            return [(
                _severity(len(paras), CHAIN_CAP),
                f"Plain: {len(paras)} paragraphs, cap {CHAIN_CAP}. Cut a part, "
                "or make the middle a list."
            )]
        return []
    findings = []
    for heading, body in _sections(text):
        paras = _paragraphs(body)
        if len(paras) > CHAIN_CAP:
            name = f"'{heading[:40]}'" if heading else "before the first heading"
            findings.append((
                _severity(len(paras), CHAIN_CAP),
                f"Plain: section {name} has {len(paras)} paragraphs, cap "
                f"{CHAIN_CAP}. Cut a part, or make the middle a list."
            ))
    return findings


def _is_glossed(window: str) -> bool:
    """Check if the text window shows a gloss after the term.

    Accepts parenthetical glosses: (explanation), comma-separated glosses,
    and meaning glosses: , meaning explanation or meaning: explanation.
    """
    stripped = window.lstrip()
    if stripped.startswith("("):
        return True
    if stripped.startswith(","):
        return True
    if stripped.startswith("meaning"):
        return True
    return False


def gloss_check(text: str, seen: set) -> tuple:
    """Flag the first bare use of a tracked term. Return the terms that did
    arrive with a gloss, so the caller can record them.

    Accepts multiple gloss formats: parenthetical term (explanation),
    comma-separated term, explanation, or meaning form
    term, meaning explanation.
    """
    prose = _prose_only(text)
    lower = prose.lower()
    findings = []
    newly_glossed = set()
    for term in TRACKED_TERMS:
        if term in seen:
            continue
        match = re.search(r"\b" + re.escape(term) + r"\b", lower)
        if not match:
            continue
        window = prose[match.end():match.end() + _GLOSS_WINDOW]
        if _is_glossed(window):
            newly_glossed.add(term)
            continue
        findings.append((
            "SOFT",
            f"Plain: \'{term}\' used with no gloss on first mention. "
            f"Write '{term} (short plain explanation)' once, then use it bare."
        ))
    return findings, newly_glossed


def scan_plain(text: str, seen: set) -> tuple:
    """Every plain check at once. Returns (findings, newly_glossed)."""
    findings = []
    findings.extend(sentence_cap(text))
    findings.extend(paragraph_cap(text))
    findings.extend(chain_cap(text))
    gloss_findings, newly_glossed = gloss_check(text, seen)
    findings.extend(gloss_findings)
    return findings, newly_glossed
