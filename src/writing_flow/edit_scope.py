#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Which lines an Edit changes, so a prose guard checks those and no others.

An Edit's old_string and new_string carry unchanged context around the change.
A guard that checks all of new_string, or rereads the whole file, reports debt
the edit never touched. Live run v62 on 2026-09-23: guard_style and
guard_doc_residue both flagged README line 3, a line the edit only carried as
context, and the model spent its reply explaining that it left the line alone.
"""
from difflib import SequenceMatcher


def changed_lines(old: str, new: str) -> set[int]:
    """1-based numbers of the lines in `new` that `old` does not hold unchanged."""
    before, after = old.splitlines(), new.splitlines()
    keep = set()
    for tag, _i1, _i2, j1, j2 in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            keep.update(range(j1 + 1, j2 + 1))
    return keep


def blank_unchanged(text: str, keep: set[int], offset: int = 0) -> str:
    """`text` with every line outside `keep` blanked, so line numbers hold.

    `offset` shifts `keep` when the numbers count from a later line of `text`,
    for example when `text` is the whole file and `keep` numbers new_string.
    """
    return "\n".join(line if n - offset in keep else ""
                     for n, line in enumerate(text.split("\n"), 1))


def edit_offset(file_text: str, new: str) -> int | None:
    """Lines before `new` in `file_text`, when it occurs there exactly once."""
    if not new or file_text.count(new) != 1:
        return None
    return file_text[:file_text.index(new)].count("\n")
