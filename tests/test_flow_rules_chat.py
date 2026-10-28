"""flow_rules on chat-shaped prose.

The fixture set in tests/fixtures/fixtures_flow.json holds essay prose. A chat
reply has shapes an essay never does: imperatives, subjectless status lines,
bold label openers, quoted error strings, and a pronoun that reaches past a
first-person aside. Each case here is a sentence or paragraph a real session
wrote, that the rules blocked, and that a reader followed without trouble.
The replay that found them is in docs/retrospective.md under 2026-09-08.
"""
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1] / "hooks" / "lib"
sys.path.insert(0, str(LIB))
from writing_flow import flow_rules  # noqa: E402


def kinds(text):
    return sorted(f["kind"] for f in flow_rules.scan_flow(text))


# --- imperatives and subjectless openers -----------------------------------

@pytest.mark.parametrize("sentence", [
    "Run the block from my previous message to unblock the compile check and secret generation.",
    "Look at the list: ChatGPT Codex Connector, coderabbitai, and Cursor all show a pending request.",
    "Let me zoom in on the recording area, since the GIF may be broken.",
    "Found a real, arithmetically demonstrable bug in the safe-to-spend figure this morning.",
    "Verified on the existing branch with the full suite, nine hundred and one tests passing.",
])
def test_imperative_or_subjectless_opener_has_no_runway(sentence):
    info = flow_rules.analyze_sentence(sentence)
    assert info["runway"] is not None and info["runway"] <= 1, info["runway"]
    assert info["imperative"] is True


def test_noun_that_is_also_a_verb_still_opens_a_subject():
    """'Support for X' is a noun phrase. The next word decides."""
    info = flow_rules.analyze_sentence(
        "Support for Truman's foreign policy came from both parties in the Senate."
    )
    assert info["imperative"] is False
    assert info["head"] == flow_rules.stem("support")


def test_instruction_paragraph_is_not_topic_drift():
    text = (
        "Run the migration first. Check the row count against the backup. "
        "Restart the API only after both match. Tell me if either step fails."
    )
    assert "topic_drift" not in kinds(text)


# --- verb detection ----------------------------------------------------------

@pytest.mark.parametrize("word,prev,nxt", [
    ("used", "it", "the"),
    ("removes", "that", "the"),
    ("lets", "that", "each"),
    ("changes", "this", "the"),
])
def test_verb_after_pronoun_subject(word, prev, nxt):
    assert flow_rules._is_verb(word, prev, nxt)


def test_noun_after_demonstrative_stays_a_noun():
    assert not flow_rules._is_verb("limit", "that", "is")
    assert not flow_rules._is_verb("need", "the", "for")


@pytest.mark.parametrize("sentence,cap", [
    ("It used the same pnpm command and a fresh Playwright context, so it was already seeded-only.", 2),
    ("That removes the whole Funnel and always-on problem, because GitHub's runners come to you.", 2),
    ("SIGTERM first, not SIGKILL, because that lets each session flush its transcript to disk.", 6),
])
def test_short_runway_when_the_verb_follows_a_pronoun(sentence, cap):
    info = flow_rules.analyze_sentence(sentence)
    assert info["runway"] is not None and info["runway"] <= cap, info


# --- sentence splitting ------------------------------------------------------

def test_period_inside_quotes_does_not_end_the_sentence():
    text = (
        'The screenshot shows "Permission updates requested. Review request." on three apps. '
        "Claude has only a plain Configure button."
    )
    sentences = flow_rules.split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0].startswith("The screenshot")


def test_quoted_error_paragraph_is_judged_on_its_real_sentences():
    """The drift call on this paragraph stands. The quote artifact does not."""
    text = (
        "Claude had no pending permission request. The screenshot of your installed apps "
        'shows "Permission updates requested. Review request." on ChatGPT Codex Connector, '
        "coderabbitai, and Cursor. Claude has only a plain Configure button. So the approval "
        "step I described never existed, and Claude was never the blocker."
    )
    labels = [f["label"] for f in flow_rules.scan_flow(text) if f["kind"] == "topic_drift"]
    assert labels and "4 sentences" in labels[0], labels
    assert "Review request" not in labels[0]


# --- pronoun links -----------------------------------------------------------

def test_possessive_pronoun_reaches_past_a_first_person_aside():
    text = (
        "The skill is stale. It documents two scripts under the state directory. "
        "Neither exists on this machine. I did the work by hand instead. "
        "Its whole premise was also outdated, since the services it stops were already inactive."
    )
    assert "topic_drift" not in kinds(text)


def test_neither_and_both_link_to_the_previous_sentence():
    for word in ("Neither", "Both", "None"):
        info = flow_rules.analyze_sentence(f"{word} exists on this machine today.")
        assert info["is_link"], word


# --- label openers -----------------------------------------------------------

def test_bold_label_with_colon_is_an_orienting_phrase_not_a_clause():
    text = (
        "**Where the thinking happens:** the code fix comes from Claude over the internet, "
        "using your existing subscription login. Everything else happens locally. "
        "Your laptop must be awake for any of it."
    )
    assert "missing_index" not in kinds(text)
    assert "long_runway" not in kinds(text)


def test_label_opener_does_not_count_toward_the_runway():
    info = flow_rules.analyze_sentence(
        "Day to day: a labelled issue produces a draft PR about twenty-five minutes later."
    )
    assert info["runway"] is not None and info["runway"] <= 4


def test_gerund_subject_is_not_a_participial_opener():
    text = (
        "**Also worth weighing:** reporting from April 2026 puts AI agents at 17 million PRs "
        "a month on GitHub, up 4x in six months, with roughly 1 in 10 judged legitimate. "
        "Your label gate keeps you out of that statistic. Most hosted tools default to looser triggers."
    )
    assert "missing_index" not in kinds(text)


def test_real_long_runway_still_fires():
    """The fix must not swallow the finding it exists beside."""
    text = (
        "Investigating against the dev repo (main@9418dc1) rather than restating the report changed the picture. "
        "The report named three defects. Two were already fixed upstream. One was a duplicate."
    )
    assert "long_runway" in kinds(text)


def test_real_drift_still_fires():
    text = (
        "DXVK fails first at screen capture. The log records an unimplemented error. "
        "The application then relaunches itself three times and exits. Steam records exit code -1."
    )
    assert "topic_drift" in kinds(text)
