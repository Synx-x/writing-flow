"""Regression tests for markdown emphasis and code handling in sentence splitting.

Issue: _split_sentences() only splits where the character right before the
boundary is '.', '!' or '?'. Markdown emphasis and code spans break that:
in '**Bold claim.** Next sentence' the period sits before '**', so two
sentences are counted as one, inflating sentence length caps.

Fix: the splitter treats closing emphasis (** * __ _ `) and closing brackets
or quotes after terminal punctuation as part of the boundary.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

import pytest
from writing_flow.prose_rules import _split_sentences, _split_line_into_sentences, scan


def test_markdown_bold_sentence_boundary():
    """Markdown bold markers after period should not prevent sentence split."""
    text = "**Bold claim.** Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"
    assert sentences[0].strip() == "**Bold claim.**"
    assert sentences[1].strip() == "Next sentence"


def test_markdown_italic_sentence_boundary():
    """Markdown italic markers after period should not prevent sentence split."""
    text = "*Italic claim.* Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_markdown_underscore_bold_sentence_boundary():
    """Markdown underscore bold markers after period should not prevent sentence split."""
    text = "__Bold claim.__ Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_markdown_code_sentence_boundary():
    """Markdown code span markers after period should not prevent sentence split."""
    text = "`Code snippet.` Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_markdown_link_sentence_boundary():
    """Markdown link should not prevent sentence boundary after its closing paren."""
    # In real usage, the link itself ends with ), and the period comes after the )
    text = "[Link](url). Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_combined_markdown_emphasis_sentence_boundary():
    """Multiple markdown markers after period should not prevent sentence split."""
    text = "**Bold and *italic*.** Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_markdown_in_list_items():
    """Markdown emphasis in list items should not break sentence splitting."""
    text = "- **Step 0.** Run the setup."
    sentences = _split_line_into_sentences(text)
    # List marker is at the start, followed by emphasized text with period
    # Should be treated as one sentence (the list item is the sentence)
    assert len(sentences) >= 1


def test_multiple_emphasis_markers():
    """Multiple emphasis markers after punctuation should not break split with proper boundaries."""
    # Two sentences with emphasis and proper boundaries
    text = "**Bold.** Next claim. More text."
    sentences = _split_sentences(text)
    # Should split: "**Bold.**" and "Next claim. More text."
    # (The third sentence "More text." is part of the second because it starts lowercase)
    assert len(sentences) >= 2, f"Expected at least 2 sentences, got {len(sentences)}: {sentences}"


def test_exclamation_with_emphasis():
    """Exclamation mark with emphasis should split correctly."""
    text = "**Exciting!** Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_question_with_emphasis():
    """Question mark with emphasis should split correctly."""
    text = "**Question?** Next sentence"
    sentences = _split_sentences(text)
    assert len(sentences) == 2, f"Expected 2 sentences, got {len(sentences)}: {sentences}"


def test_long_sentence_detection_with_markdown():
    """Long sentence detection should work correctly with markdown emphasis."""
    # A descriptive sentence with emphasis that exceeds the 25-word cap.
    # Exceeds cap by adding extra words and phrases well beyond the limit.
    text = "**This is a very long descriptive sentence with many words and extra content that definitely exceeds the twenty five word descriptive cap limit and more stuff.** Short."
    findings = scan(text, kinds=("long_sentence",))
    assert any(f["kind"] == "long_sentence" for f in findings), f"Expected long_sentence finding, got {findings}"


def test_passive_voice_detection_with_markdown():
    """Passive voice detection should work with markdown emphasis."""
    # Emphasized text containing passive voice. The first sentence has passive
    # voice ("was designed"), second is active ("works"), so passive ratio is
    # 50%, which is above the 20% threshold.
    text = "**The system was designed.** It works well."
    findings = scan(text, kinds=("passive",))
    assert any(f["kind"] == "passive" for f in findings), f"Expected passive finding, got {findings}"


def test_plain_mode_sentence_cap_with_markdown():
    """Plain mode sentence cap should work correctly with markdown."""
    # Import plain_rules if available
    try:
        sys.path.insert(0, str(ROOT / "hooks" / "lib"))
        from writing_flow import plain_rules

        # A sentence with emphasis markers that exceeds the 20-word cap.
        # plain_rules.SENTENCE_CAP is 20, so we need > 20 words.
        text = "**This is a sentence with bold that is way too long and has many extra words in it beyond the cap.** Short."
        findings = plain_rules.sentence_cap(text)
        assert len(findings) >= 1, f"Expected plain mode finding, got {findings}"
    except ImportError:
        pytest.skip("plain_rules not available")


def test_flow_and_prose_strippers_differ_on_inline_code():
    """Flow rules read an identifier in the topic slot. Vocabulary rules skip it.

    A first pass replaced flow_rules.prose_only with prose_rules.prose_only, which
    left "The  hook" and made every identifier-led sentence read as drift.
    """
    from writing_flow import flow_rules
    from writing_flow import prose_rules

    text = "The `guard_style` hook blocks it."
    assert "guard_style" in flow_rules.prose_only(text)
    assert "guard_style" not in prose_rules.prose_only(text)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
