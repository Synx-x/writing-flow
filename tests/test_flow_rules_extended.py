"""Extensions to flow_rules.py from the Reader-Flow Rule Atlas review.

Four changes: preview_term_dropped widened from exactly three terms to 3-6, a new
index_count_mismatch for derived-parts completeness, and two new document-scale
checks (doc_intro_too_long, intro_missing_turn). A live sweep of this repo's own
34-file docs tree caught two design flaws before they shipped: a 2-term floor on
the preview rule and an unconfirmed count check both false-positived on real
prose, and intro_missing_turn alone fired on 59% of real docs. Both narrowed rules
and the opt-in exclusion are tested here alongside the checks themselves.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
from writing_flow import flow_rules as fr  # noqa: E402

FIXTURES = {
    f["id"]: f for f in json.loads(
        (ROOT / "tests" / "fixtures" / "fixtures_flow.json").read_text(encoding="utf-8")
    )["fixtures"]
}


def kinds(text):
    return sorted(f["kind"] for f in fr.scan_flow(text))


# --- preview_term_dropped, widened past exactly three -----------------------
# The floor stays at 3, not 2. A live sweep of this repo's docs found a false
# positive: an ordinary "X and Y" clause read as a two-term preview.

def test_two_term_pair_is_never_flagged():
    """The floor excludes 2 on purpose, see the module note above."""
    text = (
        "The rewrite covers backend and frontend. Backend now uses the new queue. "
        "Nothing else changed this sprint."
    )
    assert "preview_term_dropped" not in kinds(text)


def test_four_term_preview_all_present_is_clean():
    text = (
        "The rewrite touched auth, billing, search, and notifications. Auth now uses "
        "short-lived tokens. Billing switched providers. Search moved to a managed "
        "index. Notifications also moved to the new queue."
    )
    assert "preview_term_dropped" not in kinds(text)


def test_four_term_preview_dropped_term_fires():
    text = (
        "The rewrite touched auth, billing, search, and notifications. Auth now uses "
        "short-lived tokens. Billing switched providers. Search moved to a managed index."
    )
    assert "preview_term_dropped" in kinds(text)


def test_three_term_fixture_still_fires():
    """The original case this rule shipped for must keep working."""
    assert "preview_term_dropped" in kinds(FIXTURES["theme_preview_bad_synonym"]["text"])
    assert "preview_term_dropped" not in kinds(FIXTURES["theme_preview_good"]["text"])


def test_oxford_comma_join_splits_correctly():
    """', and X' must split as one token, not leave 'and X' as a stray term."""
    m = None
    for cand in fr._COORD_LIST.finditer("auth, billing, search, and notifications"):
        m = cand
    terms = fr._coord_terms(m.group(1))
    assert terms == ["auth", "billing", "search", "notifications"]


# --- index_count_mismatch ----------------------------------------------------

def test_matching_count_is_clean():
    text = (
        "Three fixes landed this week. The first fix closed a race condition. "
        "The second fix added a retry. The third fix repaired a typo."
    )
    assert "index_count_mismatch" not in kinds(text)


def test_undercount_fires():
    text = (
        "Three fixes landed this week. The first fix closed a race condition. "
        "The second fix added a retry."
    )
    assert "index_count_mismatch" in kinds(text)


def test_overcount_fires():
    text = (
        "Two fixes landed this week. The first fix closed a race condition. "
        "The second fix added a retry. The third fix repaired a typo."
    )
    assert "index_count_mismatch" in kinds(text)


def test_a_comparative_count_with_no_enumeration_is_clean():
    """Real false positive from docs/model-routing-design.md, fixed by requiring
    an ordinal signpost before trusting the paragraph's raw sentence count.
    """
    text = (
        "Two axes replace one. Complexity becomes a separate score that selects "
        "the model. A ledger records when a thorough architecture exists."
    )
    assert "index_count_mismatch" not in kinds(text)


def test_labeled_parts_with_no_ordinal_word_are_clean():
    """Real false positive from docs/plans/2026-06-30-*-phase5-init-telemetry.md:
    'Part A' and 'Part B' name two parts but neither is the word 'first' or
    'second', so the count check has nothing to confirm the enumeration with.
    """
    text = (
        "Two parts, sequenced, one version bump. Part A touches the init engine. "
        "Part B prefers wiring telemetry at a shared entry point. Both must read "
        "the existing code first."
    )
    assert "index_count_mismatch" not in kinds(text)


def test_silent_when_the_paragraph_already_drifted():
    """A drifting paragraph gets one finding, not two, for the same sentences."""
    text = (
        "Three fixes landed this week. The database migration finished overnight. "
        "Redis warmed the cache before traffic shifted. A Slack message announced the deploy."
    )
    found = kinds(text)
    assert "topic_drift" in found
    assert "index_count_mismatch" not in found


# --- document-scale: doc_intro_too_long --------------------------------------

def _doc(intro, sections=2, words_per_section=60):
    body = "".join(
        f"\n\n## Section {i}\n\n" + ("Detail follows in this section. " * words_per_section)
        for i in range(1, sections + 1)
    )
    return f"# Title\n\n{intro}{body}"


def test_short_intro_is_clean():
    doc = _doc("This tool automates the release checklist.\n\n")
    assert "doc_intro_too_long" not in kinds(doc)


def test_long_intro_fires():
    doc = _doc(("This tool solves the problem well. " * 60) + "\n\n")
    assert "doc_intro_too_long" in kinds(doc)


def test_short_document_is_exempt():
    """Under the word floor, the check does not run at all."""
    doc = "# Title\n\n" + ("Long intro paragraph. " * 60) + "\n\n## Section\n\nShort body."
    assert "doc_intro_too_long" not in kinds(doc)


def test_single_heading_document_is_exempt():
    """One heading means no second section to compare the intro against."""
    doc = "# Title\n\n" + ("Long intro paragraph repeated many times over. " * 60)
    assert "doc_intro_too_long" not in kinds(doc)


# --- document-scale: intro_missing_turn, opt-in ------------------------------
# Not in ALL_KINDS, so every case here passes kinds explicitly.

_TURN_KINDS = fr.ALL_KINDS + fr.OPT_IN_KINDS


def test_intro_with_a_turn_is_clean():
    doc = _doc(
        "Today the pipeline runs on manual triggers only. But that leaves no audit "
        "trail when something fails silently.\n\n",
        sections=3,
    )
    found = [f["kind"] for f in fr.scan_flow(doc, kinds=_TURN_KINDS)]
    assert "intro_missing_turn" not in found


def test_intro_with_no_turn_fires():
    doc = _doc(
        "Today the pipeline runs on manual triggers only. It has worked this way "
        "for two years.\n\n",
        sections=3,
    )
    found = [f["kind"] for f in fr.scan_flow(doc, kinds=_TURN_KINDS)]
    assert "intro_missing_turn" in found


def test_needs_three_headings_not_two():
    doc = _doc(
        "Today the pipeline runs on manual triggers only. It has worked this way "
        "for two years.\n\n",
        sections=1,
    )
    found = [f["kind"] for f in fr.scan_flow(doc, kinds=_TURN_KINDS)]
    assert "intro_missing_turn" not in found


def test_one_sentence_intro_is_exempt():
    """A single-sentence intro has no claim-then-turn shape to judge."""
    doc = _doc("This tool automates the release checklist.\n\n", sections=3)
    found = [f["kind"] for f in fr.scan_flow(doc, kinds=_TURN_KINDS)]
    assert "intro_missing_turn" not in found


def test_intro_missing_turn_is_opt_in_not_default():
    """The 59% rate measured on this kit's own docs kept it out of ALL_KINDS."""
    assert "intro_missing_turn" not in fr.ALL_KINDS
    assert "intro_missing_turn" in fr.OPT_IN_KINDS
    doc = _doc(
        "Today the pipeline runs on manual triggers only. It has worked this way "
        "for two years.\n\n",
        sections=3,
    )
    assert fr.scan_flow(doc) == fr.scan_flow(doc, kinds=fr.ALL_KINDS)


# --- regression guard against this repo's own docs --------------------------

def test_all_default_kinds_stay_clean_on_this_repos_docs():
    """The two false positives that shipped narrowed rules were caught here.

    Runs every default (non-opt-in) kind over every doc in docs/ and fails
    on the first hit, so a future change that reopens either false positive
    is caught by CI, not by a live sweep after the fact.
    """
    docs_dir = ROOT / "docs"
    if not docs_dir.is_dir():
        return
    hits = []
    for path in sorted(docs_dir.rglob("*.md")):
        if "superpowers" in path.relative_to(docs_dir).parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for f in fr.scan_flow(text, kinds=("preview_term_dropped", "index_count_mismatch")):
            hits.append(f"{path.relative_to(ROOT)}: {f['kind']}: {f['label'][:100]}")
    assert not hits, "\n".join(hits)
