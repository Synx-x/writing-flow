"""plain_rules: the four checks plain mode enforces. Each cap is tested at
its boundary, since an off-by-one here either blocks clean prose or admits
the shape the mode exists to prevent."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from writing_flow import plain_rules


def _words(n):
    return " ".join(["word"] * n)


# --- sentence_cap: 20 words ---

def test_sentence_at_cap_is_clean():
    assert plain_rules.sentence_cap(_words(20) + ".") == []


def test_sentence_over_cap_flags_soft():
    findings = plain_rules.sentence_cap(_words(21) + ".")
    assert len(findings) == 1
    assert findings[0][0] == "SOFT"
    assert "21" in findings[0][1]


def test_sentence_at_one_and_a_half_times_the_cap_blocks():
    """Measured 2026-09-23: the median plain sentence block ran 1.25x its cap."""
    assert plain_rules.sentence_cap(_words(29) + ".")[0][0] == "SOFT"
    assert plain_rules.sentence_cap(_words(30) + ".")[0][0] == "HARD"


def test_code_block_exempt_from_sentence_cap():
    text = "Short line.\n```\n" + _words(90) + "\n```"
    assert plain_rules.sentence_cap(text) == []


# --- paragraph_cap: 4 sentences, 60 words ---

def test_paragraph_at_sentence_cap_is_clean():
    para = "One two. Three four. Five six. Seven eight."
    assert plain_rules.paragraph_cap(para) == []


def test_paragraph_over_sentence_cap_flags():
    para = "One two. Three four. Five six. Seven eight. Nine ten."
    findings = plain_rules.paragraph_cap(para)
    assert findings and findings[0][0] == "SOFT"
    six = para + " Eleven twelve."
    assert plain_rules.paragraph_cap(six)[0][0] == "HARD"


def test_paragraph_over_word_cap_flags():
    para = _words(30) + ". " + _words(35) + "."
    findings = plain_rules.paragraph_cap(para)
    assert findings
    assert any("word" in detail for _sev, detail in findings)


def test_two_short_paragraphs_are_clean():
    text = "One two three. Four five.\n\nSix seven. Eight nine ten."
    assert plain_rules.paragraph_cap(text) == []


def test_bullet_list_is_exempt_from_paragraph_cap():
    """chain_cap's own suggested fix for a long chain is 'make it a list',
    so a list block cannot also be judged as one oversized paragraph."""
    text = ("Notes:\n- one\n- two\n- three\n- four\n- five\n- six")
    assert plain_rules.paragraph_cap(text) == []


def test_bullet_lines_still_obey_the_sentence_cap():
    """The list exemption covers paragraph shape, not sentence length. A
    single overlong bullet still needs to be caught."""
    long_bullet = "- " + _words(25)
    findings = plain_rules.sentence_cap(long_bullet)
    assert findings and findings[0][0] == "SOFT"


# --- chain_cap: 4 paragraphs ---

def test_four_paragraph_chain_is_clean():
    text = "\n\n".join(["Short one here." for _ in range(4)])
    assert plain_rules.chain_cap(text) == []


def test_bullet_list_does_not_count_toward_the_chain():
    """A retrospective-style doc runs prose paragraphs plus several bulleted
    sections. The bullets are the list alternative, not more chain links."""
    text = "\n\n".join([
        "Intro paragraph here.",
        "**Notes:**\n- one\n- two\n- three\n- four",
        "**More:**\n- five\n- six",
        "**Even more:**\n- seven\n- eight",
    ])
    assert plain_rules.chain_cap(text) == []


def test_heading_only_block_does_not_count_toward_the_chain():
    text = "\n\n".join([
        "## Some title",
        "Body one.",
        "Body two.",
        "Body three.",
        "Body four.",
    ])
    assert plain_rules.chain_cap(text) == []


def test_five_paragraph_chain_flags():
    text = "\n\n".join(["Short one here." for _ in range(5)])
    findings = plain_rules.chain_cap(text)
    assert findings and findings[0][0] == "SOFT"
    six = "\n\n".join(["Short one here." for _ in range(6)])
    assert plain_rules.chain_cap(six)[0][0] == "HARD"


# --- gloss_check ---

def test_first_use_without_gloss_flags():
    findings, new = plain_rules.gloss_check("The hook fired twice.", set())
    assert findings and "hook" in findings[0][1]
    assert new == set()


def test_first_use_with_gloss_is_clean_and_records():
    text = "A hook (a script that runs on its own) fired."
    findings, new = plain_rules.gloss_check(text, set())
    assert findings == []
    assert new == {"hook"}


def test_already_glossed_term_passes_bare():
    findings, new = plain_rules.gloss_check("The hook fired.", {"hook"})
    assert findings == []


def test_untracked_word_is_ignored():
    findings, new = plain_rules.gloss_check("The kettle boiled.", set())
    assert findings == []


def test_term_inside_code_span_is_ignored():
    findings, new = plain_rules.gloss_check("Run `hook` now.", set())
    assert findings == []


# --- scan_plain ---

def test_scan_plain_runs_every_check():
    text = _words(25) + "."
    findings, new = plain_rules.scan_plain(text, set())
    assert any("word" in detail for _sev, detail in findings)


def test_scan_plain_clean_text_returns_nothing():
    text = "Rain fell all morning.\n\nThe river rose by noon."
    findings, new = plain_rules.scan_plain(text, set())
    assert findings == []


# ------- DEFECT B: gloss formats must support comma and meaning

def test_gloss_check_accepts_comma_separated_gloss():
    """Defect B: plain mode must accept comma-separated glosses like
    'hook, a script that runs on its own' in addition to parenthetical glosses."""
    text = "A hook, a script that runs on its own, rewrote the line."
    findings, new = plain_rules.gloss_check(text, set())
    assert findings == []
    assert new == {"hook"}


def test_gloss_check_accepts_meaning_gloss():
    """Defect B: plain mode must accept meaning-form glosses like
    'hook, meaning a script that runs on its own'."""
    text = "The hook, meaning a script that runs on its own, fired."
    findings, new = plain_rules.gloss_check(text, set())
    assert findings == []
    assert new == {"hook"}


def test_gloss_check_accepts_meaning_colon_gloss():
    """Defect B: plain mode must accept 'meaning: explanation' form."""
    text = "A harness, meaning: the kit that runs hooks, blocks replies."
    findings, new = plain_rules.gloss_check(text, set())
    assert findings == []
    assert new == {"harness"}


# --- frontmatter, sections and template files ---

def test_frontmatter_is_not_a_paragraph():
    text = "---\nname: x\ndescription: " + ". ".join(["Word"] * 12) + ".\n---\n\nBody line."
    assert plain_rules.paragraph_cap(text) == []


def test_per_section_chain_counts_each_heading_alone():
    section = "## Part\n\nOne.\n\nTwo."
    text = "\n\n".join([section] * 6)
    assert plain_rules.chain_cap(text) != []
    assert plain_rules.chain_cap(text, per_section=True) == []


def test_per_section_chain_names_the_long_section():
    text = "## Setup\n\n" + "\n\n".join(["Line."] * 6)
    hits = plain_rules.chain_cap(text, per_section=True)
    assert len(hits) == 1 and "'Setup'" in hits[0][1]


def test_template_reason_by_path():
    assert plain_rules.template_reason("repo/agents/x.md", "") == "agent definition"
    assert plain_rules.template_reason("repo/skills/x/SKILL.md", "") == "skill definition"
    assert plain_rules.template_reason("repo/commands/x.md", "") == "command definition"
    assert plain_rules.template_reason("r/.github/ISSUE_TEMPLATE/bug.md", "") == "issue template"
    assert plain_rules.template_reason("r/docs/x.template.md", "") == "template file"
    assert plain_rules.template_reason("r/docs/guide.md", "") == ""


def test_template_reason_by_marker():
    assert plain_rules.template_reason("r/docs/guide.md", "<!-- plain: off -->") == "plain: off marker"


# --- [override-plain-mode: <reason>] ---

def test_override_reason_needs_three_words():
    assert plain_rules.override_reason("[override-plain-mode: agent spec template]") == "agent spec template"
    assert plain_rules.override_reason("[override-plain-mode: table]") == ""
    assert plain_rules.override_reason("[override-plain-mode]") == ""


def _transcript(tmp_path, records):
    import json
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(p)


def _assistant(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _user(text):
    return {"type": "user", "message": {"content": text}}


def test_turn_override_reads_only_the_current_turn(tmp_path):
    token = "[override-plain-mode: writing a fixed agent template]"
    same_turn = _transcript(tmp_path, [_user("go"), _assistant(token)])
    assert plain_rules.turn_override(same_turn) == "writing a fixed agent template"
    old_turn = _transcript(tmp_path, [_user("go"), _assistant(token), _user("next")])
    assert plain_rules.turn_override(old_turn) == ""


def test_section_split_ignores_hash_lines_in_code():
    text = "## Run\n\n```bash\n# one\n# two\n```\n\n" + "\n\n".join(["Line."] * 6)
    hits = plain_rules.chain_cap(text, per_section=True)
    assert len(hits) == 1 and "'Run'" in hits[0][1]
