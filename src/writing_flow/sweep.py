#!/usr/bin/env python3
"""Sweep past prose artefacts across a filesystem, not just uncommitted diffs.

check_uncommitted.py answers "what does the working tree currently contain."
This answers a different question: "what did the kit's own writing rules
already build up as debt before those rules existed, or before this
machine's own tables grew wide enough to catch it." Scope is mtime-bounded
on purpose. A file untouched in months is not this sweep's business. The
user reviews those case by case.

Two stages, deliberately different in how much they trust automation:

  Deterministic (always safe): tier-1 word substitution, reusing the exact
  literal map hooks/message_display_audit.py already applies to the live
  display stream. One word in, one word out, case-matched, fence-aware.
  Nothing here requires judgment, so nothing here needs a human in the loop
  before --apply.

  Reported, not applied: em-dash density and residue findings. Both need a
  real rewrite decision -- an em-dash might want a period, a comma, or a
  restructured clause, and residue needs the sentence reworded, not a word
  swapped. This script surfaces every occurrence with line and column
  (scan(..., first_only=False)) so a human or a scoped model pass can act on
  them, but it never touches them itself.

Safety:
  --dry-run is the default. --apply is required to write anything, and only
  ever applies the deterministic stage.
  Every applied change is journalled through config.record_revert() into
  harness-kit-local/reverts.jsonl, with a full before/after body, before the
  write happens.
  retrospective.md (or any path under an archive/ directory) is skipped
  outright. It is append-only by convention, snapshot-then-edit territory
  this script has no business rewriting word by word.

Usage:
  python3 scripts/prose_sweep.py --roots DIR [DIR...] [--days N] [--json]
                                 [--apply]
"""

import argparse
import fnmatch
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from .prose_rules import scan as scan_prose, tier1_map, fix_article_agreement  # noqa: E402
from . import config  # noqa: E402

DEFAULT_DAYS = 15

# Directories a sweep never descends into. Plugin caches ran 91% of one
# real machine's raw file count (issue #47), none of it authored content.
EXCLUDE_DIR_NAMES = frozenset((
    ".git", "node_modules", "__pycache__", "site-packages", ".venv", "venv",
    ".cache", "dist", "build",
))
EXCLUDE_PATH_GLOBS = (
    "*/.claude/plugins/*",
    "*/.codex/plugins/*",
    "*/.zen/*",
)
# retrospective.md is append-only per docs/README.md's versioning protocol.
# archive/ holds frozen snapshots that protocol already produced.
SKIP_BASENAMES = frozenset(("retrospective.md",))
SKIP_PATH_GLOBS = ("*/archive/*",)

_LITERAL_TIER1 = {
    word: repl for word, repl in tier1_map().items()
    if not repl.startswith("(") and "/" not in repl
}


def _excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIR_NAMES:
        return True
    s = str(path)
    if any(fnmatch.fnmatch(s, g) for g in EXCLUDE_PATH_GLOBS):
        return True
    if path.name in SKIP_BASENAMES:
        return True
    if any(fnmatch.fnmatch(s, g) for g in SKIP_PATH_GLOBS):
        return True
    return False


def discover_files(roots: list, days: int) -> list:
    """Every *.md file under `roots` modified within `days`, exclusions applied.

    Markdown only for this pass. It is the corpus this fix was measured
    against (issue #45's own corpus), and the lowest-risk surface to
    rewrite: no compiler, no build step, a wrong word is just a wrong word.
    """
    cutoff = time.time() - days * 86400
    out = []
    seen = set()
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            if p in seen or _excluded(p):
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            seen.add(p)
            out.append(p)
    return sorted(out)


def _case_match(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


_BACKTICK_SPAN = re.compile(r"`[^`]*`")
_FENCE_LINE = re.compile(r"^\s*```")
_TIER1_SUBS = [
    (re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE), repl)
    for word, repl in sorted(_LITERAL_TIER1.items(), key=lambda kv: len(kv[0]), reverse=True)
]


def _rewrite_prose_span(text: str) -> tuple:
    """Apply literal tier-1 swaps to one span. Returns (text, count)."""
    count = 0

    def _sub(m, repl):
        nonlocal count
        count += 1
        return _case_match(m.group(0), repl)

    for pattern, repl in _TIER1_SUBS:
        text = pattern.sub(lambda m, r=repl: _sub(m, r), text)
    return text, count


def rewrite_tier1(body: str) -> tuple:
    """Fence- and code-span-aware tier-1 rewrite of a whole file body.

    Returns (new_body, substitutions_made). Mirrors
    message_display_audit.py's _rewrite_line/shape_delta shape, applied to a
    static file instead of a streamed delta.
    """
    ends_with_newline = body.endswith("\n")
    lines = body.split("\n")
    if ends_with_newline:
        lines = lines[:-1]

    in_fence = False
    total = 0
    out_lines = []
    for line in lines:
        if _FENCE_LINE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        spans = _BACKTICK_SPAN.findall(line)
        pieces = _BACKTICK_SPAN.split(line)
        rebuilt = []
        for i, piece in enumerate(pieces):
            new_piece, n = _rewrite_prose_span(piece)
            total += n
            rebuilt.append(new_piece)
            if i < len(spans):
                rebuilt.append(spans[i])
        out_lines.append("".join(rebuilt))

    new_body = "\n".join(out_lines)
    if total:
        # Only worth the pass when a substitution actually happened -- most
        # files change nothing here and this call would be pure overhead.
        new_body = fix_article_agreement(new_body)
    if ends_with_newline:
        new_body += "\n"
    return new_body, total


def scan_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    em_dash = scan_prose(text, kinds=("em_dash",), filepath=str(path), first_only=False)
    residue = scan_prose(text, kinds=("residue",), filepath=str(path), first_only=False)
    new_body, tier1_count = rewrite_tier1(text)
    return {
        "path": str(path),
        "tier1_substitutions": tier1_count,
        "em_dash_findings": em_dash,
        "residue_findings": residue,
        "_original": text,
        "_rewritten": new_body,
    }


def apply_one(result: dict) -> None:
    """Write the tier-1 rewrite, journalled before the write happens."""
    path = Path(result["path"])
    before = result["_original"]
    after = result["_rewritten"]
    if before == after:
        return
    config.record_revert(
        target=str(path), action="prose_sweep_tier1",
        before=before, after=after, after_len=len(after),
        reason=f"tier1 sweep: {result['tier1_substitutions']} substitution(s)",
    )
    path.write_text(after, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true",
                     help="write the tier-1 rewrite. Default is dry-run.")
    args = ap.parse_args()

    files = discover_files(args.roots, args.days)
    results = [scan_file(p) for p in files]
    results = [r for r in results if r]

    changed = [r for r in results if r["tier1_substitutions"] > 0]
    em_dash_total = sum(len(r["em_dash_findings"]) for r in results)
    residue_total = sum(len(r["residue_findings"]) for r in results)

    if args.apply:
        for r in changed:
            apply_one(r)

    if args.json:
        out = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in results
        ]
        print(json.dumps({
            "scanned": len(results),
            "tier1_files_changed": len(changed),
            "tier1_substitutions_total": sum(r["tier1_substitutions"] for r in results),
            "em_dash_findings_total": em_dash_total,
            "residue_findings_total": residue_total,
            "applied": args.apply,
            "results": out,
        }, indent=2))
        return 0

    print(f"{len(results)} file(s) scanned under {args.roots}, last {args.days} day(s)")
    print(f"tier-1: {len(changed)} file(s) with a substitution "
          f"({sum(r['tier1_substitutions'] for r in results)} total)"
          + (", applied" if args.apply else ", dry-run only -- pass --apply to write"))
    print(f"em-dash: {em_dash_total} occurrence(s) over the density threshold, reported only")
    print(f"residue: {residue_total} occurrence(s), reported only")
    if changed:
        print("\nFiles with a tier-1 substitution:")
        for r in changed:
            print(f"  {r['path']}  ({r['tier1_substitutions']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
