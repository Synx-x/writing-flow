#!/usr/bin/env python3
"""Report what guard_flow blocked, and how often it was wrong.

A count of findings measures how loud the rules are. The number that matters is
the override rate, because an override is the model stating a finding was wrong
for the passage in hand. Run this after a week of strict mode to decide whether
the rules earn their block.

Usage:
  python3 scripts/flow_report.py [--log PATH] [--days N]
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths  # noqa: E402
# The directory guard_flow writes to, whichever override is set.
DEFAULT_LOG = paths.state_dir() / "guard_flow_log.jsonl"


def load(path: Path, days: int) -> list[dict]:
    if not path.is_file():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        stamp = record.get("ts", "")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            out.append(record)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    records = load(Path(args.log), args.days)
    if not records:
        print(f"No guard_flow records in the last {args.days} days at {args.log}")
        return

    outcomes = Counter(r.get("outcome", "unrecorded") for r in records)
    kinds = Counter()
    kinds_overridden = Counter()
    for record in records:
        for kind, n in (record.get("counts") or {}).items():
            kinds[kind] += n
            if record.get("outcome") == "override":
                kinds_overridden[kind] += n

    blocked = outcomes.get("blocked", 0)
    overridden = outcomes.get("override", 0)
    decided = blocked + overridden

    print(f"guard_flow, last {args.days} days, {len(records)} scans")
    print()
    for name, count in outcomes.most_common():
        print(f"  {name:12} {count}")
    print()
    if decided:
        rate = 100.0 * overridden / decided
        print(f"  override rate {rate:.1f}%  ({overridden} of {decided} strict decisions)")
        print("  A high rate means the rules block prose that was already right.")
    else:
        print("  No strict decisions yet. Set mode to strict to start measuring.")
    print()

    print("  findings by kind (overridden in brackets):")
    for kind, count in kinds.most_common():
        print(f"    {kind:22} {count:5}  [{kinds_overridden.get(kind, 0)}]")

    reasons = [r.get("reason", "") for r in records if r.get("outcome") == "override"]
    if reasons:
        print()
        print("  override reasons:")
        for reason in reasons[-10:]:
            print(f"    - {reason}")


if __name__ == "__main__":
    main()
