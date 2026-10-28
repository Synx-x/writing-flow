"""Pure text metrics and writing-flow rule counts for A/B outputs."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))
from writing_flow import flow_rules, prose_rules


_WORD = re.compile(r"\b[\w]+(?:['’][\w]+)*\b", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?]+(?:[\"’'”)]*)?(?=\s|$)")
_FENCE = re.compile(r"(?ms)^\s*(```+|~~~+)[^\n]*\n.*?^\s*\1\s*$")
_INLINE_CODE = re.compile(r"(?s)`+[^`]*`+")


def prose_without_code(text: str) -> str:
    """Return text with fenced and inline code spans removed."""
    return _INLINE_CODE.sub(" ", _FENCE.sub(" ", text))


def sentence_lengths(text: str) -> list[int]:
    """Count words in each detected sentence, excluding code spans."""
    prose = prose_without_code(text).strip()
    if not prose:
        return []
    chunks = [part.strip() for part in _SENTENCE_END.split(prose) if part.strip()]
    return [len(_WORD.findall(chunk)) for chunk in chunks]


def semicolon_count_outside_code(text: str) -> int:
    """Count semicolons after removing inline and fenced code."""
    return prose_without_code(text).count(";")


def writing_flow_findings(text: str) -> list[dict[str, Any]]:
    """Return findings from the repository's writing-flow text scanners."""
    # Match the isolated plugin's default configuration without reading ambient settings.
    kinds = ("ai_ism", "tier1", "residue") + prose_rules.STE_STRICT
    return prose_rules.scan(text, kinds=kinds, filepath="output.md") + flow_rules.scan_flow(text)


def measure_output(text: str, hook_blocks: int = 0) -> dict[str, Any]:
    """Compute all output metrics without changing the supplied text."""
    lengths = sentence_lengths(text)
    words = len(_WORD.findall(prose_without_code(text)))
    findings = writing_flow_findings(text)
    return {
        "word_count": len(_WORD.findall(text)),
        "sentence_count": len(lengths),
        "mean_sentence_length": round(sum(lengths) / len(lengths), 2) if lengths else 0.0,
        "sentences_over_25_words": sum(length > 25 for length in lengths),
        "semicolon_count_outside_code": semicolon_count_outside_code(text),
        "writing_flow_findings": len(findings),
        "hook_blocks_met": hook_blocks,
        "finding_details": findings,
        "prose_word_count": words,
    }


def count_hook_blocks(records: list[dict[str, Any]]) -> int:
    """Count blocked hook responses by exit code or standard blocked marker."""
    import re
    count = 0
    marker = re.compile(r"\[[^\]\r\n]+:blocked\]", re.I)
    for record in records:
        if record.get("subtype") != "hook_response" and record.get("type") != "hook_response":
            continue
        output = "\n".join(str(record.get(key, "")) for key in ("stdout", "stderr", "output"))
        if record.get("exit_code") == 2 or marker.search(output):
            count += 1
    return count


def count_hook_blocks_in_stream(stream: str) -> int:
    """Parse a Claude stream and count blocked hook events."""
    records = []
    for line in stream.splitlines():
        try:
            value = __import__("json").loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return count_hook_blocks(records)
