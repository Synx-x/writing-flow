"""The "used to" change-narration rule flags history, not purpose.

On 2026-09-23 the rule flagged README line 3 of the live-test repo, "Tiny
calculator used to live-test harness-kit hooks.", in three live runs, and the
v62 evolver recorded it as a false positive. "is used to call" is the purpose
form too. "used to return None" still narrates a change.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
from writing_flow import prose_rules  # noqa: E402


def _narration(text):
    return [f for f in prose_rules.scan(text, kinds=("residue",)) if f["label"] == "change narration"]


def test_a_hyphenated_compound_is_not_narration():
    assert _narration("Tiny calculator used to live-test harness-kit hooks.") == []


def test_the_purpose_form_is_not_narration():
    assert _narration("The helper is used to call the API.") == []
    assert _narration("These files are used to return defaults.") == []


def test_history_is_still_narration():
    assert _narration("This function used to return None.")
    assert _narration("It used to live in lib/.")
