"""Residue table plus suppressors (issue #45): 2/12 measured probes caught by
the old 10-entry table, 12/12 after this fix. Three suppressors make the
wider table's false-positive rate survivable: quote-stripping, sentence
anchoring, and a skills/agents path standdown for four labels.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS / "lib"))

from writing_flow import prose_rules as pr

# The 12 probes from issue #45's own measurement. Old table: 2/12.
PROBES = [
    "Step 3. Open the picker and click the day.",
    "Next, force the full load and assert the count.",
    "The grid used to be a plain table.",
    "Renamed from GetTasks to ReadTasks.",
    "Fixes the bug where dirty rows vanished.",
    "Not sure why the pager lies.",
    "Keep in mind the buffer is volatile.",
    "You mentioned the filter was wrong.",
    "Claude generated this table.",
    "I changed the page size to 200.",
    "We agreed the mapping keys on record id.",
    "As discussed, the label is denormalised.",
]


@pytest.mark.parametrize("probe", PROBES)
def test_probe_caught(probe):
    assert pr.scan(probe, kinds=("residue",)), probe


def test_all_twelve_probes_caught():
    hits = sum(1 for p in PROBES if pr.scan(p, kinds=("residue",)))
    assert hits == 12


# ---- suppressor 1: quote-strip ----

def test_quoted_residue_text_not_flagged():
    text = 'The rule reads "we decided to keep this" in the spec.\n'
    assert pr.scan(text, kinds=("residue",)) == []


def test_blockquoted_residue_text_not_flagged():
    text = "> We decided to keep this pattern.\nSome unrelated real prose.\n"
    assert pr.scan(text, kinds=("residue",)) == []


def test_quote_strip_preserves_line_numbers():
    # The quoted span sits entirely on one line, so it can never desync a
    # later finding's line number the way deleting a multi-line span would.
    text = 'Line one is plain.\n"We decided to keep this" is quoted.\nWe decided to keep this for real.\n'
    hits = pr.scan(text, kinds=("residue",))
    assert len(hits) == 1
    assert hits[0]["line"] == 3


# ---- suppressor 2: sentence anchoring ----

def test_wrapped_continuation_line_still_a_known_residual():
    # agents/explore-code.md's real wrapped line, isolated. Read alone it is
    # a genuine sentence start, so scan() still finds it. The mitigation is
    # that "tutorial narration" is advisory, not blocking. See
    # test_reflow_false_positive_from_the_real_repo_does_not_block below.
    text = "first, if registered. jcodemunch cannot answer these:\n"
    labels = {h["label"] for h in pr.scan(text, kinds=("residue",))}
    assert "tutorial narration" in labels


def test_genuine_sentence_start_still_flagged():
    text = "First, open the file and read it.\n"
    labels = {h["label"] for h in pr.scan(text, kinds=("residue",))}
    assert "tutorial narration" in labels


def test_this_edit_anchored_to_sentence_start():
    # "this (change|edit|commit)" only fires as a sentence opener, not
    # mid-sentence domain prose like "would this edit have changed".
    assert pr.scan("Would this edit have changed the outcome?\n", kinds=("residue",)) == []
    hit = pr.scan("This edit fixes the regression.\n", kinds=("residue",))
    assert any(h["label"] == "change narration" for h in hit)


# ---- suppressor 3: skills/agents path standdown ----

STANDDOWN_LABELS = ["conversational address", "unresolved deliberation",
                     "third-person user ref", "session-time reference"]

CASES = {
    "conversational address": "Keep in mind the buffer is volatile.\n",
    "unresolved deliberation": "Not sure why the pager lies.\n",
    "third-person user ref": "The user wants to stand up a new workstream.\n",
    "session-time reference": "This happened earlier in this session.\n",
}


@pytest.mark.parametrize("label", STANDDOWN_LABELS)
def test_standdown_label_suppressed_under_skills_path(label):
    text = CASES[label]
    assert any(h["label"] == label for h in pr.scan(text, kinds=("residue",)))
    assert pr.scan(text, kinds=("residue",), filepath="skills/x/SKILL.md") == []
    assert pr.scan(text, kinds=("residue",), filepath="/repo/skills/x/SKILL.md") == []


@pytest.mark.parametrize("label", STANDDOWN_LABELS)
def test_standdown_label_suppressed_under_agents_path(label):
    text = CASES[label]
    assert pr.scan(text, kinds=("residue",), filepath="agents/foo.md") == []
    assert pr.scan(text, kinds=("residue",), filepath="/repo/agents/foo.md") == []


def test_standdown_does_not_cover_every_label():
    # tutorial narration is not one of the four -- a skills/ path does not
    # get a blanket exemption from every residue category.
    text = "Step 6: create files again.\n"
    assert pr.scan(text, kinds=("residue",), filepath="skills/x/SKILL.md")


def test_standdown_relative_path_without_leading_slash():
    # Regression: _residue_standdown_active used to require "/skills/" as a
    # substring, so a project-relative path like "skills/x/SKILL.md" (no
    # leading slash) silently missed the standdown. Found by measuring this
    # fix against the kit's own real files.
    text = CASES["third-person user ref"]
    assert pr.scan(text, kinds=("residue",), filepath="skills/new-loop/SKILL.md") == []


def test_non_skills_path_not_suppressed():
    text = CASES["third-person user ref"]
    assert pr.scan(text, kinds=("residue",), filepath="docs/design.md")


# ---- first_only ----

def test_first_only_default_matches_one_per_pattern():
    text = "We decided X.\nWe decided Y.\nWe decided Z.\n"
    hits = pr.scan(text, kinds=("residue",))
    assert len(hits) == 1


def test_first_only_false_matches_every_occurrence():
    text = "We decided X.\nWe decided Y.\nWe decided Z.\n"
    hits = pr.scan(text, kinds=("residue",), first_only=False)
    assert len(hits) == 3
    assert [h["line"] for h in hits] == [1, 2, 3]


# ---- per-occurrence em-dash ----

def test_em_dash_first_only_reports_one_document_level_finding():
    text = "a—b c—d e—f g—h i—j k—l m—n o—p q—r s—t.\n" * 3  # force over threshold
    hits = pr.scan(text, kinds=("em_dash",))
    assert len(hits) <= 1
    if hits:
        assert hits[0]["line"] == 0


def test_em_dash_per_occurrence_reports_line_and_column():
    text = "word " * 5 + "a—b\n" + "word " * 5 + "c—d\n"
    hits_summary = pr.scan(text, kinds=("em_dash",))
    hits_detail = pr.scan(text, kinds=("em_dash",), first_only=False)
    if hits_summary:
        assert len(hits_detail) == 2
        assert hits_detail[0]["line"] == 1
        assert hits_detail[1]["line"] == 2
        assert "column" in hits_detail[0]


# ---- blocking vs advisory split (guard_style.py) ----

def _run_guard_style(path, content):
    payload = json.dumps({"tool_name": "Write",
                           "tool_input": {"file_path": path, "content": content}})
    return subprocess.run([sys.executable, str(HOOKS / "guard_style.py")],
                          input=payload, capture_output=True, text=True)


def test_legacy_blocking_label_still_blocks():
    result = _run_guard_style("/tmp/probe/x.md", "We decided to keep this pattern.\n")
    assert result.returncode == 2
    assert "harness-kit[style:blocked]" in result.stderr


def test_new_label_is_advisory_only():
    result = _run_guard_style("/tmp/probe/x.md", "Fixes the bug where dirty rows vanished.\n")
    assert result.returncode == 0
    assert "advisory only" in result.stderr


def test_reflow_false_positive_from_the_real_repo_does_not_block():
    content = ("1. Use codebase-memory-mcp\n"
               "   first, if registered. jcodemunch cannot answer these:\n"
               "   - a real list item\n")
    result = _run_guard_style("/tmp/probe/reflow.md", content)
    assert result.returncode == 0


def test_changelog_self_reference_exemption():
    # decision narration is a blocking label; a CHANGELOG entry describing
    # the residue feature itself (quoting "user decision" as an example)
    # must not trip it, the same way guard_doc_residue.py already exempts
    # CHANGELOG.md.
    content = "- feat(guard): flags decision narration such as 'user decision' in prose.\n"
    result = _run_guard_style("/repo/CHANGELOG.md", content)
    assert result.returncode == 0


def test_docs_changelog_directory_also_exempt():
    content = "- feat(guard): flags decision narration such as 'user decision' in prose.\n"
    result = _run_guard_style("/repo/docs/changelog/old.md", content)
    assert result.returncode == 0


def test_residue_blocking_labels_are_exactly_the_legacy_six():
    assert pr.RESIDUE_BLOCKING_LABELS == frozenset((
        "dated decision stamp", "decision narration", "chat reference",
        "reader address", "first-person opinion", "conversational filler",
    ))
