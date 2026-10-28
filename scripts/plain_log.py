#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Print the rewrite log as before-and-after pairs.

The log answers one question: what did the harness change about what I
read? A display-only rewrite never reaches the transcript, so this listing
is the only place that difference shows.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from writing_flow import rewrite_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Show recent harness rewrites.")
    parser.add_argument("--limit", type=int, default=20,
                        help="how many records to show (default 20)")
    args = parser.parse_args()

    rows = rewrite_log.read_recent(limit=args.limit)
    if not rows:
        print("No rewrites recorded yet.")
        return

    print(f"{len(rows)} recent rewrite(s), oldest first:\n")
    for row in rows:
        stamp = row.get("ts", "")[:19].replace("T", " ")
        print(f"  {stamp}  {row.get('hook', '?')} / {row.get('rule', '?')}")
        print(f"    before: {row.get('before', '')[:120]}")
        print(f"    after:  {row.get('after', '')[:120]}")
        print()


if __name__ == "__main__":
    main()
