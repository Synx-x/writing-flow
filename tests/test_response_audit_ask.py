"""The ask-via-tool check: a reply that asks the user in prose must use AskUserQuestion."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

from hooks import response_audit  # noqa: E402


def _exit_code(fn, *args):
    with pytest.raises(SystemExit) as e:
        fn(*args)
    return e.value.code


def _payload(transcript_path="/t/x.jsonl", stop_hook_active=False, agent_id=None,
             last_assistant_message=None, session_id="TESTSESS"):
    d = {"transcript_path": transcript_path, "stop_hook_active": stop_hook_active,
         "session_id": session_id}
    if agent_id is not None:
        d["agent_id"] = agent_id
    if last_assistant_message is not None:
        d["last_assistant_message"] = last_assistant_message
    return d


def _write_transcript(path, text):
    path.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }) + "\n", encoding="utf-8")


def flagged(text, tools=frozenset({"Bash"})):
    return [d for s, d in response_audit.check_ask_via_tool(text, set(tools)) if s == "HARD"]


def test_question_in_the_last_block_is_flagged():
    assert flagged("Done the work.\n\nShould I commit it?") == [
        'Ask via tool: "Should I commit it?" asked in prose. Ask through AskUserQuestion, recommended option first']


def test_an_askuserquestion_call_clears_it():
    assert flagged("Done.\n\nShould I commit it?", {"AskUserQuestion"}) == []


def test_code_quotes_and_blockquotes_are_ignored():
    text = ('Run:\n```\nread -p "continue?" x\n```\nIt prints `ready?` first.\n\n> Is it done?\n\n'
            'You asked "mod? hook? prompt?" and I answered.')
    assert flagged(text) == []


def test_rhetorical_question_mid_reply_passes_and_addressed_one_fails():
    assert flagged("Why did it fail? The cache was stale.\n\nFixed and verified.") == []
    assert len(flagged("Do you want the long form? I wrote the short one.\n\nFixed.")) == 1


def test_url_query_is_not_a_question():
    assert flagged("See https://x.io/a?b=1 for the log.\n\nDone.") == []


def test_more_questions_are_counted():
    assert flagged("A?\n\nShould I push? Or open a PR?")[0].startswith(
        'Ask via tool: "Should I push?" asked in prose with 1 more.')


def test_compute_findings_runs_it_except_on_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path / "state"))
    t = tmp_path / "t.jsonl"; t.write_text("")
    text = "All done here.\n\nShould I push it?"
    monkeypatch.delenv("HARNESS_KIT_HARNESS", raising=False)
    assert any(d.startswith("Ask via tool") for _, d in response_audit.compute_findings(str(t), text, "S"))
    monkeypatch.setenv("HARNESS_KIT_HARNESS", "codex")
    assert not any(d.startswith("Ask via tool") for _, d in response_audit.compute_findings(str(t), text, "S"))


