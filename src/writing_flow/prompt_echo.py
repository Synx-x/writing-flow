"""Detect prompt guidance copied into prose and document narration."""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+", re.I)
_STOP = set("a an and are as at be by cover do for from has have i in include into is it keep make of on or our please short that the this to we what when with without write you your".split())

_KIND_PATTERNS = {
    "audience": re.compile(r"^\s*(?:for\s+\S+|aimed at\b|written for\b)|\b(?:target audience|intended reader)\b", re.I),
    "scope": re.compile(r"\b(cover|covers|include|includes|explain|describe|address|discuss)\b", re.I),
    "form": re.compile(r"\b(in chat|without (?:creating|writing|making)|keep it (?:short|brief)|as a|format|tone)\b", re.I),
    "process": re.compile(r"\b(ask no questions|make sure|ensure|do not|don't|never|must|should)\b", re.I),
}

_FRAMES = {
    "audience": re.compile(r"\b(this|the)\s+(?:guide|document|readme|article|answer|page|tutorial)\s+(?:is|was|has been)\s+(?:written\s+)?for\b", re.I),
    "scope": re.compile(r"\b(this|the)\s+(?:guide|document|readme|article|page|section)\s+(?:covers|includes|explains|describes|addresses|discusses)\b|\bI\s+(?:have\s+)?(?:covered|included|explained|addressed)\b", re.I),
    "form": re.compile(r"\bhere (?:is|are)\b.*\b(?:short|brief|chat|files?|file|answer|response)\b|\b(?:in chat|without creating files|no files created)\b", re.I),
    "process": re.compile(r"\b(?:i|we)\s+(?:made sure|ensured|will make sure|made certain|included|covered|checked|followed|kept)\b|\b(?:this|the) (?:guide|answer|response)\s+(?:makes sure|ensures)\b", re.I),
}

_NARRATION = [
    (re.compile(r"^here (?:is|are)\s+(?:the\s+)?(?:readme|guide|options|answer|document)\b", re.I), "deliverable introduction"),
    (re.compile(r"^below (?:you(?:'ll| will) find|is|are)\b", re.I), "deliverable introduction"),
    (re.compile(r"^now for the\s+(?:options|next section|details)\b", re.I), "section narration"),
    (re.compile(r"^(?:i|we)'ll start by\b|^(?:i|we) will start by\b", re.I), "process narration"),
    (re.compile(r"\bin this guide we will\b", re.I), "document narration"),
    (re.compile(r"^the following sections? (?:cover|explain|describe|include)\b", re.I), "section narration"),
]


def _sentences(text: str):
    for match in re.finditer(r"[^\n]+(?:\n|$)", text):
        line = match.group(0).rstrip("\n")
        base = match.start()
        for part in re.finditer(r"[^.!?]+(?:[.!?]+|$)", line):
            sentence = part.group(0).strip()
            if sentence:
                offset = base + part.start() + len(part.group(0)) - len(part.group(0).lstrip())
                yield sentence, text.count("\n", 0, offset) + 1


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) > 2 and w.lower() not in _STOP}


def guidance_clauses(prompts: list[str]) -> list[dict]:
    """Split prompts and retain clauses that direct the writing process."""
    result = []
    seen = set()
    for prompt in prompts:
        for sentence, _line in _sentences(prompt):
            parts = re.split(r"\s*(?:;|,\s*(?=(?:for|without|in chat|keep|cover|include|ask|make sure|ensure)\b))\s*", sentence)
            for clause in parts:
                clause = clause.strip(" .,:;\t")
                words = _words(clause)
                kind = next((name for name, pattern in _KIND_PATTERNS.items() if pattern.search(clause)), None)
                if kind is None or not words:
                    continue
                key = (kind, clause.casefold())
                if key in seen:
                    continue
                seen.add(key)
                result.append({"kind": kind, "clause": clause, "content_words": sorted(words)})
    return result


def find_echo(text: str, clauses: list[dict]) -> list[dict]:
    """Report overlap with prompt guidance; guidance framing makes it blocking."""
    findings = []
    for sentence, line in _sentences(text):
        sentence_words = _words(sentence)
        candidates = []
        for clause in clauses:
            overlap = sorted(sentence_words & set(clause.get("content_words", ())))
            if not overlap:
                continue
            kind = clause.get("kind", "")
            sure = bool(_FRAMES.get(kind) and _FRAMES[kind].search(sentence))
            candidates.append({"sentence": sentence, "line": line, "clause": clause.get("clause", ""), "kind": kind, "sure": sure, "overlap": overlap})
        if candidates:
            findings.append(next((item for item in candidates if item["sure"]), candidates[0]))
    return findings


def find_narration(text: str) -> list[dict]:
    """Report document and process narration absent from the source residue rules."""
    findings = []
    for sentence, line in _sentences(text):
        for pattern, label in _NARRATION:
            if pattern.search(sentence):
                findings.append({"sentence": sentence, "line": line, "rule": label, "sure": True})
                break
    return findings
