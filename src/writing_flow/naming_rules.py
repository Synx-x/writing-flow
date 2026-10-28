"""Flag a cryptic identifier where the surrounding code is descriptive.

Why relative rather than absolute. A minimum-name-length rule is wrong in both
directions: `i` in a two-line loop is fine, and `d` as a module-level cache is
not, at the same length. Naming is a consistency property of a file, so the
comparison that works is against the file's own other names.

So this needs no style fingerprint, which is what makes it cheap to run. It
reads the file it is given. A file whose names are already short and terse
reports nothing, because there is no local convention being broken.

Scored on two axes:

  brevity      character length, and whether the name has any word boundary
  isolation    how far it sits from the file's median name length

A name is flagged when the file's names are descriptive by median, and this one
is far below it, and it is not in the conventional-short-name set below.
"""

import re
import statistics

# Short names that are conventional and carry meaning by position. Flagging
# these is the fastest way to make a naming rule ignored.
CONVENTIONAL = frozenset((
    # loop and index
    "i", "j", "k", "n", "m", "x", "y", "z", "w", "h",
    # idiomatic bindings
    "e", "f", "p", "s", "t", "v", "c", "r", "q", "db", "id", "ok", "fn",
    "cb", "el", "ev", "ex", "kv", "ns", "op", "os", "re", "io", "fs",
    # language keywords used as names
    "self", "cls", "this", "args", "kwargs", "err", "res", "req", "ctx",
    "val", "key", "idx", "tmp", "buf", "src", "dst", "len", "num", "obj",
    "arr", "str", "int", "map", "set", "sum", "min", "max", "acc", "url",
    "uri", "api", "cfg", "env", "log", "msg", "out", "ret", "row", "col",
))

DECLARATION_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?function\s+([A-Za-z_$]\w*)", re.MULTILINE),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(
        r"^\s*(?:public|private|protected|internal|static|final|\s)*"
        r"(?:[A-Za-z_<>\[\],.]+\s+)([a-z_]\w*)\s*\(",
        re.MULTILINE,
    ),
    # Module-level assignment, Python and shell
    re.compile(r"^([A-Za-z_]\w*)\s*=(?!=)", re.MULTILINE),
)

# A file must declare this many names before its median means anything.
MIN_NAMES = 6
# The file counts as descriptive when its median name is at least this long.
DESCRIPTIVE_MEDIAN = 9
# A name is cryptic when it is at or under this length.
CRYPTIC_MAX = 3
# ... or under this fraction of the file's median.
CRYPTIC_RATIO = 0.45


def declared_names(text: str) -> list:
    """Declared identifiers in `text`, in order, deduplicated."""
    seen, out = set(), []
    for pattern in DECLARATION_PATTERNS:
        for name in pattern.findall(text):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def has_word_boundary(name: str) -> bool:
    """True when the name is more than one word: snake, camel or kebab."""
    if "_" in name.strip("_") or "-" in name:
        return True
    inner = name.strip("_")
    return bool(re.search(r"[a-z][A-Z]", inner))


def scan_naming(text: str, filepath: str = "") -> list:
    """Cryptic names in a file whose other names are descriptive.

    Returns finding dicts matching the shape the style hooks already use, so a
    caller can merge them into an existing findings list without translation.
    """
    names = [n for n in declared_names(text) if n.strip("_")]
    if len(names) < MIN_NAMES:
        return []

    lengths = [len(n) for n in names]
    median = statistics.median(lengths)
    if median < DESCRIPTIVE_MEDIAN:
        # The file is terse throughout. There is no local convention to break.
        return []

    threshold = max(CRYPTIC_MAX, median * CRYPTIC_RATIO)
    findings = []
    for name in names:
        bare = name.strip("_").lower()
        if bare in CONVENTIONAL:
            continue
        if len(name) > threshold:
            continue
        if has_word_boundary(name):
            continue
        findings.append({
            "kind": "cryptic_name",
            "label": (
                f"`{name}` is {len(name)} chars where this file's median name is "
                f"{median:.0f}. Name it for what it holds."
            ),
            "match": name,
            "line": _line_of(text, name),
        })
    return findings


def _line_of(text: str, name: str) -> int:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return number
    return 0
