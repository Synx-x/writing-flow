"""prose_rules.py: Python docstring extraction and non-sentence filtering.

Root cause of a real false positive, found 2026-08-12: extract_comments_and_strings()
pulled only "#" comment text on Python files. Docstrings carry no "#" at all, so a
well-documented file's real prose was invisible to the structural checks, and the
sample shrank to whatever stray inline comments happened to exist. A two-word
section-divider comment ("# things that must not be flagged", which legitimately
contains "be flagged") became one of a four-item sample and tripped the passive-voice
ratio alone. Fixed two ways: docstrings now feed the same pipeline, and a pure-
punctuation line (a "---" divider) no longer counts as a sentence at all.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow.prose_rules import (
    extract_comments_and_strings,
    _python_docstrings,
    _split_sentences,
    scan,
)


# --------------------------------------------------------------------------
# _python_docstrings
# --------------------------------------------------------------------------


def test_module_docstring_is_extracted():
    code = '"""Module level text here."""\n\nx = 1\n'
    docs = _python_docstrings(code)
    assert docs == ["Module level text here."]


def test_function_and_class_docstrings_are_extracted():
    code = (
        "class Foo:\n"
        "    \"\"\"Class docstring.\"\"\"\n"
        "    def bar(self):\n"
        "        \"\"\"Method docstring.\"\"\"\n"
        "        pass\n"
    )
    docs = _python_docstrings(code)
    assert "Class docstring." in docs
    assert "Method docstring." in docs


def test_no_docstrings_returns_empty_list():
    assert _python_docstrings("x = 1\ny = 2\n") == []


def test_syntax_error_degrades_to_empty_list_not_a_raise():
    """A hook mid-Edit can carry invalid Python. A miss here beats a crash."""
    assert _python_docstrings("def f(:\n    pass") == []


# --------------------------------------------------------------------------
# extract_comments_and_strings, python path
# --------------------------------------------------------------------------


def test_python_extraction_includes_both_comments_and_docstrings():
    code = (
        '"""Module docstring sentence one."""\n'
        "# an inline comment\n"
        "x = 1\n"
    )
    out = extract_comments_and_strings(code, "x.py")
    assert "Module docstring sentence one." in out
    assert "an inline comment" in out


def test_non_python_hash_language_still_comment_only():
    """Bash gets no docstring pass -- it has no such construct."""
    code = '#!/bin/sh\n# a real comment\necho hi\n'
    out = extract_comments_and_strings(code, "x.sh")
    assert "a real comment" in out


# --------------------------------------------------------------------------
# _split_sentences: divider lines are not sentences
# --------------------------------------------------------------------------


def test_pure_punctuation_line_is_dropped():
    text = "-" * 40 + "\nReal sentence here."
    sentences = _split_sentences(text)
    assert sentences == ["Real sentence here."]


def test_equals_divider_is_also_dropped():
    text = "=" * 20 + "\nAnother sentence."
    sentences = _split_sentences(text)
    assert sentences == ["Another sentence."]


def test_a_line_with_one_letter_is_kept():
    """The filter drops lines with zero letters, not short ones."""
    text = "A cat sat."
    assert _split_sentences(text) == ["A cat sat."]


# --------------------------------------------------------------------------
# the actual reported bug, reproduced end to end
# --------------------------------------------------------------------------


def test_the_reported_false_positive_no_longer_fires():
    """Exact reproduction: two comment section-header lines flanked by
    divider comments, in a file whose real prose lives in docstrings the old
    extraction never saw. "things that must not be flagged" legitimately
    contains "be flagged" and is genuinely passive in isolation; the fix is
    that it is no longer treated as the entire sample. The docstring spans
    several physical lines, matching how a real module docstring is actually
    written, since _split_sentences treats each physical line as at least
    one candidate sentence."""
    code = (
        '"""A clean, fully active-voice module docstring with real prose.\n\n'
        'It has several sentences and covers its subject in some detail.\n'
        'None of it is passive at all, so a reasonable sample size should\n'
        'pass this check easily on real, representative content.\n'
        '"""\n\n'
        "# --------------------------------------------------------------------------\n"
        "# things that must not be flagged\n"
        "# --------------------------------------------------------------------------\n\n"
        "def f():\n"
        '    """Also a clean, active docstring describing this function."""\n'
        "    pass\n"
    )
    scan_text = extract_comments_and_strings(code, "x.py")
    findings = scan(scan_text, kinds=("passive",))
    assert findings == []


def test_a_file_that_really_is_mostly_passive_still_gets_flagged():
    """The fix must not neuter the check. Real, dominant passive voice in a
    file's actual docstrings has to keep firing."""
    code = (
        '"""The file was written. The data was processed. The result was '
        'saved. The report was generated."""\n'
    )
    scan_text = extract_comments_and_strings(code, "x.py")
    findings = scan(scan_text, kinds=("passive",))
    assert len(findings) == 1
