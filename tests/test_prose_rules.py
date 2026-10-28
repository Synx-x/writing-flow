"""prose_rules: shared library for AI writing pattern detection."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

import pytest
from writing_flow.prose_rules import scan, tier1_map, banned_phrases, fix_article_agreement


def test_ai_ism_detection():
    """Banned chatbot phrase input triggers ai_ism finding."""
    # Build trigger string via concatenation so file contains no literal phrase
    BANNED = "Certainly" + "!"
    findings = scan(f"This is helpful. {BANNED}", kinds=("ai_ism",))
    assert len(findings) >= 1
    assert findings[0]["kind"] == "ai_ism"


def test_tier1_word_detection():
    """Tier-1 word input triggers tier1 finding."""
    T1 = "lever" + "age"
    findings = scan(f"We should {T1} this tool.", kinds=("tier1",))
    assert len(findings) >= 1
    assert findings[0]["kind"] == "tier1"


def test_em_dash_overuse():
    """Text with em dashes exceeding density threshold triggers em_dash finding."""
    # The threshold is max 1 per 1000 words. Build text with 5 dashes in ~300 words.
    text = "Point one — explanation.\n" * 5
    text += " word " * 50  # pad to ~300 words
    findings = scan(text, kinds=("em_dash",))
    assert len(findings) >= 1
    assert findings[0]["kind"] == "em_dash"
    assert "em dash" in findings[0]["label"].lower() or "overuse" in findings[0]["label"]


def test_residue_detection():
    """Conversation residue input triggers residue finding."""
    findings = scan("We decided to keep this pattern.", kinds=("residue",))
    assert len(findings) >= 1
    assert findings[0]["kind"] == "residue"


def test_clean_text_returns_empty():
    """Clean text with no violations returns empty list."""
    findings = scan("The system uses this pattern consistently.", kinds=("ai_ism", "tier1", "em_dash", "residue"))
    assert findings == []


def test_tier1_map_exists():
    """tier1_map() helper returns dict of word->replacement."""
    m = tier1_map()
    assert isinstance(m, dict)
    assert "leverage" in m
    assert m["leverage"] == "use"


def test_banned_phrases_list():
    """banned_phrases() helper returns list of banned phrases."""
    phrases = banned_phrases()
    assert isinstance(phrases, list)
    assert len(phrases) > 0
    # Check that at least one known phrase is present
    assert any("certainly" in p.lower() for p in phrases)


def test_tier1_word_in_frontmatter_is_not_flagged():
    """Regression for issue #10: scan() used to match raw text, so a tier-1
    word in YAML frontmatter (metadata, not body prose) was flagged the same
    as if it were in a sentence."""
    T1 = "action" + "able"
    text = (
        "---\n"
        f"description: an {T1} findings report\n"
        "---\n"
        "Body prose with no tier-1 words here.\n"
    )
    assert scan(text, kinds=("tier1",)) == []


def test_tier1_word_in_body_prose_still_flagged_with_correct_line():
    """The same word outside frontmatter still fires, on the right line."""
    T1 = "action" + "able"
    text = (
        "---\n"
        "title: x\n"
        "---\n"
        f"This is an {T1} sentence.\n"
    )
    findings = scan(text, kinds=("tier1",))
    assert len(findings) == 1
    assert findings[0]["line"] == 4


def test_ai_ism_phrase_in_fenced_code_block_is_not_flagged():
    BANNED = "Certainly" + "!"
    text = f"```\n# {BANNED}\n```\nClean prose sentence here.\n"
    assert scan(text, kinds=("ai_ism",)) == []


def test_residue_pattern_in_table_is_not_flagged():
    text = "| Note |\n|---|\n| we decided this |\nClean prose sentence here.\n"
    assert scan(text, kinds=("residue",)) == []


# ===== fix_article_agreement: 13 of 52 literal tier-1 entries flip the
# leading vowel/consonant sound on replacement =====

@pytest.mark.parametrize("before,after", [
    ("an practical findings report", "a practical findings report"),
    ("an start point", "a start point"),
    ("a approach shift", "an approach shift"),
    ("An shows view", "A shows view"),
    ("a use point", "a use point"),
    ("an use case", "a use case"),
    ("a university course", "a university course"),
    ("an hour later", "an hour later"),
])
def test_fix_article_agreement(before, after):
    assert fix_article_agreement(before) == after


def test_fix_article_agreement_leaves_correct_text_alone():
    text = "This is a normal sentence about an ordinary topic.\n"
    assert fix_article_agreement(text) == text


def test_all_literal_tier1_replacements_get_correct_article():
    """Every literal (non-parenthetical, non-slash-choice) replacement ends
    up preceded by the article it actually wants, whichever article the
    text started with.
    """
    from writing_flow.prose_rules import _wants_an

    for word, repl in tier1_map().items():
        if repl.startswith("(") or "/" in repl or " " in repl or not repl:
            continue
        wants_an = _wants_an(repl)
        wrong_article = "a" if wants_an else "an"
        right_article = "an" if wants_an else "a"
        fixed = fix_article_agreement(f"{wrong_article} {repl} example")
        assert fixed.startswith(f"{right_article} {repl}"), (word, repl, fixed)
