"""check_grounded_response: existing factual-claim check plus the new decision-
verify nudge (DECISION_PATTERNS), which fires only in coding/meta phases when
recommendation/choice language appears without a retrieval tool or disclosure.

Also: main()'s live-this-turn blocking contract. A HARD finding blocks Stop
(exit 2) so the model revises before the response ever reaches the user,
instead of only surfacing next turn via violation_feedback.py -- confirmed
empirically (live smoke test, not just this suite) that a blocked Stop's
stderr reason gets folded into the same visible response, not a separate
stacked message. The retry cap is a locally-owned content-hash marker
(BLOCK_MARKER_FILE), not Claude Code's stop_hook_active -- that flag is
shared across the whole Stop-hook batch for a session, so any other hook
blocking (completion_gate, a /goal condition, etc) makes it true on our
very first real evaluation too, confirmed live to silently disable this
path for reasons unrelated to that turn's actual content.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

from hooks import response_audit
from hooks.response_audit import check_grounded_response

# Built by concatenation so this file holds no literal trigger phrase that
# could itself be scanned as a decision claim by an unrelated tool.
REC = "recommend" + " using Redis for the cache layer"
BEST = "the best " + "approach is a queue"


def _is_decision_finding(findings):
    return any("Decision language" in f[1] for f in findings)


def test_decision_language_fires_in_coding_phase():
    findings = check_grounded_response(REC, set(), {}, "coding")
    assert _is_decision_finding(findings)


def test_decision_language_fires_in_meta_phase():
    findings = check_grounded_response(BEST, set(), {}, "meta")
    assert _is_decision_finding(findings)


def test_decision_language_silent_in_conversational_phase():
    findings = check_grounded_response(REC, set(), {}, "conversational")
    assert not _is_decision_finding(findings)


def test_decision_language_silent_in_research_phase():
    findings = check_grounded_response(REC, set(), {}, "research")
    assert not _is_decision_finding(findings)


def test_decision_language_silent_with_disclosure():
    text = "Best guess: " + REC
    findings = check_grounded_response(text, set(), {}, "coding")
    assert not _is_decision_finding(findings)


def test_decision_language_silent_with_retrieval():
    findings = check_grounded_response(REC, {"WebFetch"}, {}, "coding")
    assert not _is_decision_finding(findings)


def test_no_decision_language_no_finding():
    findings = check_grounded_response("The tool writes the file to disk.", set(), {}, "coding")
    assert not _is_decision_finding(findings)


def test_phase_defaults_to_empty_string_backward_compatible():
    """Call without the new phase argument (as older callers would) — must not
    crash and must not fire the decision branch, since '' isn't coding/meta."""
    findings = check_grounded_response(REC, set(), {})
    assert not _is_decision_finding(findings)


def test_existing_factual_claim_check_unaffected():
    text = "It was released in 2024. It supports v2.3 and was built with Rust."
    findings = check_grounded_response(text, set(), {}, "conversational")
    assert any(f[0] == "SOFT" and "Grounded-response" in f[1] for f in findings)


# ------------------------------------------------------- main() blocking contract

def _exit_code(fn, *args):
    with pytest.raises(SystemExit) as e:
        fn(*args)
    return e.value.code


class _SpawnRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, script_path, extra_args=None):
        self.calls.append((script_path, extra_args))


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
    """A minimal transcript with one assistant text turn -- real enough for
    get_last_assistant_text (used for the block-marker hash) to read."""
    path.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }) + "\n", encoding="utf-8")


def test_main_prefers_payload_last_assistant_message_over_stale_transcript(monkeypatch, tmp_path):
    """The exact live bug: under back-to-back Stop cycles (a /goal condition
    or any blocking hook keeps triggering those), the transcript FILE write
    consistently lagged one full Stop event behind -- get_last_assistant_text
    kept returning the PRIOR turn's text, so a genuine HARD finding in the
    turn that just completed was silently missed. hook_input's own
    last_assistant_message (the same field completion_gate.py already relies
    on) has no file-flush dependency and must win whenever both disagree.
    """
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "stale prior-turn text, no trigger phrases here")
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(str(transcript), last_assistant_message="in order to understand this test"),
    )
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")

    code = _exit_code(response_audit.main)
    assert code == 2
    marker = json.loads((tmp_path / "blocked.json").read_text(encoding="utf-8"))
    assert marker["hash"] == hashlib.sha256(b"in order to understand this test").hexdigest()


def test_main_blocks_on_hard_finding_first_pass(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "some response text")
    spawner = _SpawnRecorder()
    monkeypatch.setattr(response_audit, "read_payload", lambda: _payload(str(transcript)))
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("HARD", "over budget by a lot")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")

    code = _exit_code(response_audit.main)
    assert code == 2
    assert spawner.calls == []  # blocked, never backgrounded
    assert (tmp_path / "violations.json").exists()
    assert json.loads((tmp_path / "blocked.json").read_text(encoding="utf-8"))["hash"]  # recorded


def test_main_does_not_reblock_identical_text(monkeypatch, tmp_path):
    """Not stop_hook_active -- that flag is shared across the whole Stop-hook
    batch for a session (any other hook blocking makes it true for us too,
    confirmed live), so it can't be trusted as our retry cap. The cap is our
    own content-hash marker: if this exact response text already triggered a
    block, don't block it again even on a payload claiming this is a fresh
    first pass, or Stop could never actually conclude on an unfixable HARD
    finding.
    """
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "same response text every time")
    marker_file = tmp_path / "blocked.json"
    spawner = _SpawnRecorder()
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(str(transcript), stop_hook_active=False),  # claims first pass
    )
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("HARD", "still over budget")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", marker_file)

    text_hash = hashlib.sha256(b"same response text every time").hexdigest()
    marker_file.write_text(json.dumps({"hash": text_hash}), encoding="utf-8")  # already blocked this exact text

    response_audit.main()  # must return normally, not sys.exit(2)
    assert len(spawner.calls) == 1  # falls through to the normal backgrounded path


def test_main_reblocks_genuinely_different_text(monkeypatch, tmp_path):
    """A prior block for DIFFERENT text must not suppress a block for new
    content -- only the identical text is capped."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "a brand new response, never blocked before")
    marker_file = tmp_path / "blocked.json"
    marker_file.write_text(json.dumps({"hash": hashlib.sha256(b"some earlier response").hexdigest()}), encoding="utf-8")
    monkeypatch.setattr(response_audit, "read_payload", lambda: _payload(str(transcript)))
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("HARD", "over budget")])
    monkeypatch.setattr(response_audit, "spawn_worker", _SpawnRecorder())
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", marker_file)

    assert _exit_code(response_audit.main) == 2


def test_main_backgrounds_soft_only_finding(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "some soft-flagged text")
    spawner = _SpawnRecorder()
    monkeypatch.setattr(response_audit, "read_payload", lambda: _payload(str(transcript)))
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("SOFT", "minor hedge word")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")

    response_audit.main()  # no HARD finding: never blocks
    assert len(spawner.calls) == 1
    assert spawner.calls[0][0] == Path(response_audit.__file__).resolve()
    assert spawner.calls[0][1] == [str(transcript), "TESTSESS"]


def test_main_removes_violations_file_when_clean(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "clean text")
    violations_file = tmp_path / "violations.json"
    violations_file.write_text("{}", encoding="utf-8")  # stale from a prior turn
    monkeypatch.setattr(response_audit, "read_payload", lambda: _payload(str(transcript)))
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [])
    monkeypatch.setattr(response_audit, "spawn_worker", _SpawnRecorder())
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: violations_file)
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")

    response_audit.main()
    assert not violations_file.exists()


def test_main_skips_subagent_turns(monkeypatch, tmp_path):
    spawner = _SpawnRecorder()
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(str(tmp_path / "t.jsonl"), agent_id="sub-123"),
    )
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("HARD", "x")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)

    response_audit.main()  # returns normally, doesn't even reach compute_findings' caller
    assert spawner.calls == []


def test_violations_file_is_session_scoped(tmp_path, monkeypatch):
    """The live bug: a single global path let ANY process hitting
    UserPromptSubmit next, including a background subagent's own first turn,
    consume a violation record left by an unrelated session's prior
    response. Two sessions writing findings must land in two distinct
    files."""
    from writing_flow import violations_store
    monkeypatch.setattr(violations_store, "VIOLATIONS_DIR", tmp_path)

    response_audit.persist_and_log([("SOFT", "finding A")], "SESSION-A")
    response_audit.persist_and_log([("SOFT", "finding B")], "SESSION-B")

    a = json.loads(response_audit.violations_file_for("SESSION-A").read_text(encoding="utf-8"))
    b = json.loads(response_audit.violations_file_for("SESSION-B").read_text(encoding="utf-8"))
    assert a["violations"][0]["detail"] == "finding A"
    assert b["violations"][0]["detail"] == "finding B"
    assert response_audit.violations_file_for("SESSION-A") != response_audit.violations_file_for("SESSION-B")


def test_backgrounded_path_passes_session_id_to_worker(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "some soft-flagged text")
    spawner = _SpawnRecorder()
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(str(transcript), session_id="SESSION-XYZ"),
    )
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("SOFT", "x")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)

    response_audit.main()
    assert spawner.calls[0][1] == [str(transcript), "SESSION-XYZ"]


def test_main_skips_missing_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(str(tmp_path / "does-not-exist.jsonl")),
    )
    called = []
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, **_: called.append(p) or [("HARD", "x")])
    response_audit.main()
    assert called == []  # never reached: transcript file doesn't exist


def test_main_end_to_end_via_real_subprocess(tmp_path, monkeypatch):
    """Real stdin contract, real transcript file, real over-budget response --
    the actual integration this feature depends on, not just mocked units.
    Live-confirmed: a concurrently-blocking Stop hook does NOT suppress this
    block, because the decision no longer depends on Claude Code's shared
    stop_hook_active flag.
    """
    hooks_dir = ROOT / "hooks"
    transcript = tmp_path / "t.jsonl"
    long_response = " ".join(["word"] * 300)  # far past any conversational budget
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"
        + json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": long_response}]},
        }) + "\n"
    , encoding="utf-8")
    # PHASE_STATE_FILE, the violations_store state dir, and BLOCK_MARKER_FILE
    # are all Path.home()-relative -- overriding HOME isolates all three.
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "current_phase.json").write_text(json.dumps({"phase": "conversational"}), encoding="utf-8")

    env = dict(**__import__("os").environ)
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)

    # stop_hook_active=True on this very first pass -- simulates the exact
    # contamination confirmed live (another Stop hook already blocked this
    # turn for an unrelated reason). Must still block: our own hash marker
    # is what gates this, not this flag.
    payload = json.dumps({"transcript_path": str(transcript), "stop_hook_active": True})
    result = subprocess.run(
        [sys.executable, str(hooks_dir / "response_audit.py")],
        input=payload, capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 2, result.stderr
    assert "harness-kit[audit:blocked]" in result.stderr

    # Second pass, identical text, identical payload: must not re-block --
    # our own marker file (written by the first pass) caps it.
    result2 = subprocess.run(
        [sys.executable, str(hooks_dir / "response_audit.py")],
        input=payload, capture_output=True, text=True, env=env, timeout=10,
    )
    assert result2.returncode == 0, result2.stderr


def test_get_last_user_prompt_word_count_skips_meta_records(tmp_path):
    """A blocked Stop hook's reason gets replayed into the transcript as a
    "user"-role record tagged isMeta: true, not a real typed prompt. Counting
    it as one both mislabels intent and, live, silently defeats the
    verbosity budget once any hook has ever blocked in the session (the
    meta text is often long prose, ballooning the multiplier-scaled budget
    past anything a real response could exceed)."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "short real prompt"}}) + "\n"
        + json.dumps({
            "type": "user", "isMeta": True,
            "message": {"content": [{"type": "text", "text": " ".join(["word"] * 200)}]},
        }) + "\n"
    , encoding="utf-8")
    assert response_audit.get_last_user_prompt_word_count(str(transcript)) == 3


# ------- DEFECT 1: dark chat gate (no transcript, has payload message)

def test_main_judges_reply_with_no_transcript_when_payload_has_message(monkeypatch, tmp_path):
    """Sessions spawned as children (CLAUDE_CODE_CHILD_SESSION=1) don't write
    transcript files. The old code returned early without checking
    last_assistant_message in the payload. Now it judges the reply whenever
    the payload carries last_assistant_message, even with no transcript."""
    spawner = _SpawnRecorder()
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(
            transcript_path="/nonexistent/path.jsonl",
            last_assistant_message="in order to understand this",
        ),
    )
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, text=None, **_: [("HARD", "acknowledgment loop")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")

    code = _exit_code(response_audit.main)
    assert code == 2
    assert spawner.calls == []


def test_main_returns_early_with_no_transcript_and_no_payload_message(monkeypatch, tmp_path):
    """When there's no transcript file AND no last_assistant_message in
    payload, there's no text to judge. Return early."""
    called = []
    spawner = _SpawnRecorder()
    monkeypatch.setattr(
        response_audit, "read_payload",
        lambda: _payload(transcript_path="/nonexistent/path.jsonl"),
    )
    monkeypatch.setattr(response_audit, "compute_findings", lambda p, **_: called.append(p) or [])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)

    response_audit.main()
    assert called == []  # never reached compute_findings


# ------- DEFECT 2: false positive on markdown links and inline code

def test_check_chat_form_ignores_markdown_link_url():
    """Markdown link syntax [text](https://example.com) was flagging the
    parenthetical. Now the URL part is stripped, leaving only the text."""
    text = "See [the documentation](https://example.com/very/long/path) for details."
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    assert parenthetical_findings == []


def test_check_chat_form_ignores_inline_code_with_parens():
    """Inline code spans containing parentheses like `func(arg)` should not
    trigger the parenthetical rule."""
    text = "Call `init(config)` to start the process."
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    assert parenthetical_findings == []


def test_check_chat_form_still_flags_genuine_parentheticals():
    """The parenthetical check should still work for actual asides that aren't
    markdown links or inline code."""
    text = "This is a statement (with a genuine aside) that should trigger."
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    assert len(parenthetical_findings) > 0


def test_check_chat_form_handles_multiple_markdown_links():
    """Multiple markdown links in a reply should all be stripped."""
    text = (
        "Check [this](https://example.com) and [that](https://other.com) "
        "for reference (this is a genuine aside)."
    )
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    # Only the genuine aside should remain
    assert any("genuine aside" in f[1] for f in parenthetical_findings)


def test_undefined_jargon_flags_bare_backticked_term():
    text = "I mirrored `response_audit.py` but missed `flow_state`. That broke the gate."
    terms = response_audit.undefined_jargon(text)
    assert "response_audit.py" in terms
    assert "flow_state" in terms


def test_undefined_jargon_clears_glossed_term():
    text = "The chat gate is `response_audit.py`, which is the Stop hook that judges the reply."
    assert response_audit.undefined_jargon(text) == []


def test_undefined_jargon_ignores_paths_and_plain_words():
    text = "Read `/home/pc/.claude/state/guard_flow_log.jsonl` and note the `cap`."
    assert response_audit.undefined_jargon(text) == []


def test_undefined_jargon_ignores_table_rows():
    text = '| `flow_block_cap` | is 1 | high |'
    assert response_audit.undefined_jargon(text) == []


def test_undefined_jargon_surfaces_as_soft_chat_form_finding():
    text = "I mirrored `response_audit.py` but missed `flow_state`. That broke the gate."
    findings = response_audit.check_chat_form(text)
    jargon = [f for f in findings if "Jargon" in f[1]]
    assert jargon
    assert all(sev == "SOFT" for sev, _ in jargon)


# ------- DEFECT A: audit reads its own feedback as user word limit

def test_get_last_user_prompt_text_skips_stop_hook_feedback(tmp_path):
    """Defect A: Stop hook feedback turns (starting with 'Stop hook feedback:')
    are not user prompts and must be skipped when searching for the last user
    input. Without the fix, this would return the audit's own feedback, not
    the real user prompt."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "real user prompt is short"}}) + "\n"
        + json.dumps({
            "type": "user",
            "message": {"content": "Stop hook feedback:\nSome audit finding here"},
        }) + "\n"
    , encoding="utf-8")

    result = response_audit.get_last_user_prompt_text(str(transcript))
    assert result == "real user prompt is short"
    assert "Stop hook feedback" not in result


def test_get_last_user_prompt_text_skips_audit_finding_markers(tmp_path):
    """Defect A: Turns containing audit's own finding phrasing
    ('RESPONSE AUDIT', 'Plain: ') are harness feedback, not user prompts.
    They must be skipped when determining the user's stated word limit."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "user says something"}}) + "\n"
        + json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "RESPONSE AUDIT (blocking):\n- Plain: 22-word sentence, cap 20"}
                ]
            },
        }) + "\n"
    , encoding="utf-8")

    result = response_audit.get_last_user_prompt_text(str(transcript))
    assert result == "user says something"
    assert "RESPONSE AUDIT" not in result


def test_explicit_word_limit_ignores_audit_sentence_pattern(monkeypatch):
    """Defect A: explicit_word_limit() must ignore the audit's own phrasing
    'N-word sentence, cap M' (e.g. '22-word sentence, cap 20'). Without the fix,
    it would return 22, blocking a response against a user limit of 20 that the
    audit itself reported, not the user."""
    from writing_flow import personal_style

    # This exact prompt from the defect report should not match as an explicit limit
    prompt = "Plain: 22-word sentence, cap 20. Split it: 'It mines 8 sources in parallel'"
    result = personal_style.explicit_word_limit(prompt)
    # Should be None or should not match the 22
    assert result is None or result != 22


def test_explicit_word_limit_ignores_audit_against_pattern(monkeypatch):
    """Defect A: explicit_word_limit() must ignore 'against a stated limit of N'
    phrasing which appears in the audit's own findings, not user input."""
    from writing_flow import personal_style

    prompt = "Verbosity: 145 words against a stated limit of 21. The prompt asked for a hard cap."
    result = personal_style.explicit_word_limit(prompt)
    # Should not match the 21 or 145
    assert result is None or result not in (21, 145)


# ------- DEFECT B: chat-form check and gloss check must not contradict

def test_check_chat_form_allows_gloss_parenthetical_for_tracked_term():
    """Defect B: A parenthetical that glosses a tracked term (like 'hook')
    should not trigger the parenthetical violation. The chat-form check must
    recognize it as a plain-mode gloss, not a generic aside."""
    text = "A hook (a script that runs on its own) rewrote the line."
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    # Should NOT flag the gloss parenthetical
    assert parenthetical_findings == []


def test_check_chat_form_still_flags_non_gloss_parentheticals():
    """Defect B regression: genuine asides that are not glosses should still be flagged."""
    text = "A statement (with a genuine aside) that should trigger."
    findings = response_audit.check_chat_form(text)
    parenthetical_findings = [f for f in findings if "parenthetical" in f[1]]
    # Non-gloss parentheticals should still be flagged
    assert len(parenthetical_findings) > 0


def test_run_audit_passes_session_id_to_compute_findings(monkeypatch, tmp_path):
    """Regression: session isolation breaks if run_audit() backgrounded worker
    doesn't pass session_id to compute_findings(). This leads to findings being
    computed without session context, breaking per-session state lookups.
    """
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "some text")

    captured_calls = []

    def mock_compute_findings(transcript_path, text=None, session_id="", state_dir=None):
        captured_calls.append({
            "transcript_path": transcript_path,
            "text": text,
            "session_id": session_id,
            "state_dir": state_dir,
        })
        return [("SOFT", "test finding")]

    def mock_persist_and_log(findings, session_id):
        pass  # no-op for this test

    monkeypatch.setattr(response_audit, "compute_findings", mock_compute_findings)
    monkeypatch.setattr(response_audit, "persist_and_log", mock_persist_and_log)

    # Call run_audit with a specific session_id
    response_audit.run_audit(str(transcript), "SESSION-FOR-TEST")

    # Verify compute_findings was called with the session_id
    assert len(captured_calls) == 1
    assert captured_calls[0]["session_id"] == "SESSION-FOR-TEST"


# ------- PART 2a: is_short_continuation precision tests

def test_is_short_continuation_true_cases():
    """PART 2a: Continuation detection must be precise. Only exact phrases
    in the closed set with 4 words or fewer count as continuations."""
    from writing_flow import personal_style

    # These should be True
    assert personal_style.is_short_continuation("continue")
    assert personal_style.is_short_continuation("go")
    assert personal_style.is_short_continuation("yes")
    assert personal_style.is_short_continuation("ok go ahead")
    assert personal_style.is_short_continuation("yes please")
    assert personal_style.is_short_continuation("keep going")
    assert personal_style.is_short_continuation("carry on")


def test_is_short_continuation_false_cases():
    """PART 2a: These should NOT be continuations because they're too long,
    have extra words, or ask questions rather than acknowledge."""
    from writing_flow import personal_style

    # Too long (5+ words)
    assert not personal_style.is_short_continuation("go and continue with the next step")

    # Doesn't match the closed set or includes non-matching words
    assert not personal_style.is_short_continuation("is the fix on main?")
    assert not personal_style.is_short_continuation("yes but only fix on_load")

    # Goes followed by a path is context, not a standalone continuation
    assert not personal_style.is_short_continuation("go /tmp/file")

    # Empty
    assert not personal_style.is_short_continuation("")


def test_get_last_user_prompt_vs_substantive(tmp_path):
    """PART 2b/2c: When the latest prompt is a continuation, the substantive
    prompt (the one that opened the task) must be found without duplication."""
    from writing_flow import personal_style

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "explain the architecture in under 100 words"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "explanation"}]}}) + "\n"
        + json.dumps({"type": "user", "message": {"content": "continue"}}) + "\n"
    , encoding="utf-8")

    # get_last_user_prompt_text should return "continue"
    last = response_audit.get_last_user_prompt_text(str(transcript))
    assert last == "continue"

    # get_most_recent_substantive_prompt_text should return the original task
    substantive = response_audit.get_most_recent_substantive_prompt_text(str(transcript))
    assert substantive == "explain the architecture in under 100 words"


def test_gh_reads_count_as_fetched():
    """PART 3: gh pr view, gh pr checks, gh issue view, and gh api repos/...
    commands should count as fetching the corresponding GitHub URL."""
    # Simulate a response citing a PR
    text = "The PR checks passed: [PR #66](https://github.com/Synx-x/harness-kit/pull/66)"

    # Simulate that gh pr view was called
    tools_used = {"Bash"}
    tool_inputs = {
        "Bash": [
            {"command": "gh pr view 66 -R Synx-x/harness-kit"}
        ]
    }

    findings = response_audit.check_grounded_response(text, tools_used, tool_inputs, phase="")

    # Should not flag this URL as unfetched because gh pr view fetched it
    unfetched = [f for f in findings if "Cited URLs not fetched" in f[1]]
    assert not unfetched, f"gh pr view should count as fetching the URL, but got: {unfetched}"


CITED_PR = "Checks passed on https://github.com/Synx-x/harness-kit/pull/66 today."
CITED_ISSUE = "Closed https://github.com/Synx-x/harness-kit/issues/61 after the fix."


@pytest.mark.parametrize("text,command,fetched", [
    (CITED_PR, "gh pr view 66", True),
    (CITED_PR, "gh pr checks 66", True),
    (CITED_PR, "cd repo && gh pr view 66 --json state -R Synx-x/harness-kit", True),
    (CITED_PR, "gh api repos/Synx-x/harness-kit/pulls/66", True),
    (CITED_ISSUE, "gh issue view https://github.com/Synx-x/harness-kit/issues/61", True),
    (CITED_PR, "gh pr view 67", False),
    (CITED_PR, "gh pr view 66 -R someone/else", False),
    (CITED_PR, "echo 'gh pr view 66'", False),
])
def test_gh_reads_match_cited_urls_by_number(text, command, fetched):
    findings = response_audit.check_grounded_response(
        text, {"Bash"}, {"Bash": [{"command": command}]}, phase="")
    unfetched = [f for f in findings if "Cited URLs" in f[1]]
    assert (not unfetched) == fetched, (command, unfetched)


def test_a_continuation_sizes_the_budget_from_the_task_prompt(tmp_path, monkeypatch):
    """'continue' set a 40-word budget and blocked 93-word progress reports."""
    task = "Fix the flaky retry test in the scheduler and report which assertion was wrong " * 2
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in (
        {"type": "user", "message": {"content": task}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Working."}]}},
        {"type": "user", "message": {"content": "continue"}},
    )) + "\n", encoding="utf-8")
    (tmp_path / "phase_history.jsonl").write_text(json.dumps(
        {"session_id": "S", "prompt_preview": task[:100], "phase": "coding", "stage": "execute"}) + "\n",
        encoding="utf-8")
    seen = {}

    def spy(text, phase, words, prompt_text="", tools_used=None):
        seen.update(phase=phase, words=words)
        return []

    monkeypatch.setattr(response_audit, "check_verbosity_budget", spy)
    reply = "The retry test waited on the wrong clock. It passes now in every run."
    response_audit.compute_findings(str(transcript), text=reply, session_id="S", state_dir=tmp_path)
    assert seen == {"phase": "coding", "words": len(task.split())}


def _hard_reply_setup(monkeypatch, tmp_path, text):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, text)
    spawner = _SpawnRecorder()
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(response_audit, "read_payload",
                        lambda: _payload(str(transcript), last_assistant_message=text))
    monkeypatch.setattr(response_audit, "compute_findings",
                        lambda p, text=None, **_: [("HARD", "Plain: 15 sentences in one paragraph, cap 4")])
    monkeypatch.setattr(response_audit, "spawn_worker", spawner)
    monkeypatch.setattr(response_audit, "violations_file_for", lambda sid: tmp_path / "violations.json")
    monkeypatch.setattr(response_audit, "BLOCK_MARKER_FILE", tmp_path / "blocked.json")
    return spawner


def test_main_blocks_as_before_without_a_mod_verdict(monkeypatch, tmp_path):
    """Codex, or Claude Code without mods: nothing recorded, old Stop block."""
    _hard_reply_setup(monkeypatch, tmp_path, "a reply no mod has seen")
    assert _exit_code(response_audit.main) == 2


