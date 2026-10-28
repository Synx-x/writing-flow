"""ASD-STE100-derived structural kinds in prose_rules.scan: long_sentence,
semicolon, nominalization, phrasal_verb, passive, synonym_rotation.

Existing four kinds (ai_ism, tier1, em_dash, residue) are covered by
test_prose_rules.py and are untouched by this addition; the default
scan() kinds tuple stays the same, so callers who never pass the new
kinds see no behavior change."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow.prose_rules import scan, STE_STRICT, STE_FLAVORED, ste_mode, prose_only


def test_long_sentence_over_cap():
    text = " ".join(["word"] * 30) + "."
    findings = scan(text, kinds=("long_sentence",))
    assert len(findings) == 1
    assert findings[0]["kind"] == "long_sentence"


def test_long_sentence_under_cap_clean():
    text = " ".join(["word"] * 10) + "."
    assert scan(text, kinds=("long_sentence",)) == []


def test_semicolon_in_prose_flagged():
    findings = scan("One idea; another idea.", kinds=("semicolon",))
    assert len(findings) == 1
    assert findings[0]["kind"] == "semicolon"


def test_semicolon_inside_code_fence_not_flagged():
    text = "```\ncode; more code;\n```\nProse without semicolons here."
    assert scan(text, kinds=("semicolon",)) == []


def test_nominalization_detected():
    NOM = "perform" + "s an analysis of"
    findings = scan(f"The tool {NOM} the data.", kinds=("nominalization",))
    assert len(findings) >= 1
    assert findings[0]["kind"] == "nominalization"


def test_nominalization_no_duplicate_finding():
    NOM = "perform an analysis of"
    text = f"The tool was designed to {NOM} the data."
    findings = scan(text, kinds=("nominalization",))
    assert len(findings) == 1


def test_phrasal_verb_matches_inflected_form():
    # "reaches out" (inflected), not the bare infinitive "reach out"
    findings = scan("The system reaches out to the customer.", kinds=("phrasal_verb",))
    assert len(findings) == 1
    assert findings[0]["kind"] == "phrasal_verb"


def test_phrasal_verb_no_overlap_duplicate():
    # "reach out to" should fire once, not once for "reach out to" and again for "reach out"
    findings = scan("Please reach out to the team.", kinds=("phrasal_verb",))
    assert len(findings) == 1


def test_passive_ratio_over_threshold():
    text = "The file was written. The data was processed. The result was saved."
    findings = scan(text, kinds=("passive",))
    assert len(findings) == 1
    assert findings[0]["kind"] == "passive"


def test_passive_ratio_under_threshold_clean():
    text = "The tool writes the file. It processes the data. It saves the result. The user reviews it. The team ships it."
    assert scan(text, kinds=("passive",)) == []


def test_synonym_rotation_detected_over_min_words():
    doc = ("The user opens the app and reviews data. " * 15) + "The customer then logs in."
    findings = scan(doc, kinds=("synonym_rotation",))
    assert len(findings) == 1
    assert findings[0]["kind"] == "synonym_rotation"


def test_synonym_rotation_skipped_below_min_words():
    doc = "The user opens the app. The customer logs in."
    assert scan(doc, kinds=("synonym_rotation",)) == []


def test_synonym_rotation_single_member_not_flagged():
    doc = ("The user opens the app and reviews recent activity data here. " * 15)
    assert scan(doc, kinds=("synonym_rotation",)) == []


def test_clean_text_all_structural_kinds_empty():
    text = "The tool writes the file. It processes the data and saves the result."
    assert scan(text, kinds=STE_STRICT) == []


def test_default_kinds_unaffected_by_structural_additions():
    """Existing four-kind default behavior is unchanged: passing the classic
    kinds tuple must not pick up structural findings."""
    NOM = "perform an analysis of"
    text = f"The tool was designed to {NOM} the data; it reaches out to the customer."
    findings = scan(text, kinds=("ai_ism", "tier1", "em_dash", "residue"))
    assert findings == []


def test_ste_mode_reads_env(monkeypatch):
    monkeypatch.delenv("HARNESS_KIT_STE", raising=False)
    assert ste_mode() == "default"
    monkeypatch.setenv("HARNESS_KIT_STE", "off")
    assert ste_mode() == "off"
    monkeypatch.setenv("HARNESS_KIT_STE", "WARN")
    assert ste_mode() == "warn"
    monkeypatch.setenv("HARNESS_KIT_STE", "bogus")
    assert ste_mode() == "default"


def test_prose_only_strips_frontmatter_and_tables():
    text = "---\ntitle: x\n---\n# Heading\n| a | b |\n|---|---|\nActual prose sentence here."
    stripped = prose_only(text)
    assert "title: x" not in stripped
    assert "Heading" not in stripped
    assert "| a | b |" not in stripped
    assert "Actual prose sentence here." in stripped


def test_prose_only_strips_code_span_broken_across_a_newline():
    """Regression for issue #9: a single-backtick span wrapped across a
    source line must still strip, not leak its identifier into prose."""
    text = (
        "coroutine: `await client.send(method, params)` inside `async with\n"
        "CDPClient(ws_url) as client:`. Do not write a CDP call from memory."
    )
    stripped = prose_only(text)
    assert "client" not in stripped
    assert "CDPClient" not in stripped


def test_prose_only_unbalanced_backtick_does_not_swallow_next_paragraph():
    """An unbalanced opening backtick must not eat past the next blank
    line hunting for its close, or a stray backtick anywhere later in the
    document could delete an entire real paragraph of prose."""
    text = (
        "First paragraph has a stray ` backtick with no close.\n"
        "\n"
        "Second paragraph is genuine prose that must survive untouched."
    )
    stripped = prose_only(text)
    assert "Second paragraph is genuine prose that must survive untouched." in stripped


def test_long_sentence_does_not_glue_across_paragraphs():
    """Regression: a real-corpus scan (this repo's own docs) originally hit
    long_sentence on 92% of files because a thematic break (---) or a
    paragraph boundary without a trailing [.!?] got collapsed by \\s+ ->
    ' ' and read as a single 30+ word run-on. Fixed by splitting per-line
    before collapsing whitespace, and by turning stripped thematic breaks
    into a hard line break in prose_only()."""
    text = (
        "First paragraph ends without punctuation here\n\n"
        "---\n\n"
        "Second paragraph is a completely separate short sentence."
    )
    assert scan(text, kinds=("long_sentence",)) == []


def test_long_sentence_does_not_glue_across_bullet_items():
    text = "- First short item here\n- Second short item here\n- Third short item here"
    stripped = prose_only(text)
    assert scan(stripped, kinds=("long_sentence",)) == []


def test_ste_strict_includes_flavored_subset():
    assert set(STE_FLAVORED).issubset(set(STE_STRICT))
    assert "long_sentence" in STE_STRICT and "long_sentence" not in STE_FLAVORED
    assert "semicolon" in STE_STRICT and "semicolon" not in STE_FLAVORED
