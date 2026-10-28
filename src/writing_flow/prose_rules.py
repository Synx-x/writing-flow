#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""
Shared prose rule library: single source of truth for AI writing pattern detection.

Consolidates rule data from guard_style, style_check, response_audit, and guard_doc_residue.
Called by each hook instead of duplicating rule lists.

Interface:
  scan(text, kinds=("ai_ism","tier1","em_dash","residue", ...)) -> list[dict]
  Each finding: {"kind", "label", "match", "line"}

  tier1_map() -> dict[word, replacement]
  banned_phrases() -> list[str]

Structural (ASD-STE100 derived) kinds, added because vocabulary bans alone
under-perform: see harness-kit@c48f5e6:docs/harness-kit.md for the source experiment. These check
sentence structure rather than word choice, so they catch slop a banned-word
list cannot (nominalization, passive voice, run-ons, synonym drift).

  STE_STRICT   -> word caps + semicolon ban + structural checks (docs, commits, code comments)
  STE_FLAVORED -> structural checks only, no caps (chat, subagent output)
  ste_mode()   -> reads HARNESS_KIT_STE env var: "off" | "warn" | "strict" | None (default)
"""
import ast
import os
import re
from . import config
from pathlib import Path


# ===== AI-isms and chatbot phrases (guard_style + style_check) =====
_BANNED_PHRASES = [
    "certainly!", "absolutely!", "great question!", "i hope this helps",
    "feel free to reach out", "let me know if you need anything else",
    "let's dive in", "let me walk you through", "let's explore",
    "let's take a look", "let's break this down", "let's examine",
    "excellent point", "you're absolutely right", "that's a really insightful",
    "in conclusion,", "in summary,", "to summarize,",
    "that being said,", "when it comes to",
    "at the end of the day",
    "it's worth noting that", "it is worth noting",
    "it's important to note", "it is important to note",
    "the reality is that", "quite frankly,", "to be honest,",
    "as we move forward", "only time will tell", "one thing is certain",
    "the future looks bright",
    # Opener adverbs (filler starters)
    "honestly,", "frankly,", "clearly,", "essentially,",
    "interestingly,", "notably,", "importantly,",
    "as a matter of fact,",
    # Cutoff disclaimers
    "as of my last update", "as of my knowledge cutoff",
    "i don't have access to real-time", "while specific details are limited",
    "my training data", "my knowledge cutoff",
    # Significance inflation
    "watershed moment", "marks a significant milestone",
    # Notability boilerplate
    "maintains an active social media", "maintains a low profile",
    "recognized authority", "noted specialist", "leading expert",
    # Sycophancy variants
    "that's an excellent", "what a great",
    "i'd be happy to",
]


# ===== Tier 1 words (guard_style + style_check) =====
_TIER1_WORDS = {
    "delve": "look at / explore",
    "leverage": "use",
    "utilize": "use",
    "robust": "solid",
    "comprehensive": "thorough",
    "seamless": "smooth",
    "seamlessly": "smoothly",
    "pivotal": "key",
    "meticulous": "careful",
    "holistic": "complete",
    "actionable": "practical",
    "impactful": "effective",
    "paradigm": "approach",
    "embark": "start",
    "testament to": "shows",
    "in order to": "to",
    "due to the fact that": "because",
    "bolstered": "strengthened",
    "garner": "get",
    "groundbreaking": "(describe what is new)",
    "renowned": "well-known",
    "stands as": "is",
    "diverse array": "variety",
    "setting the stage for": "(say what follows)",
    "in the heart of": "is in",
    "make use of": "use",
    "in terms of": "(state directly)",
    "a number of": "(give the number)",
    "for the purpose of": "to",
    "cutting-edge": "latest",
    "underscores": "shows",
    "boasts": "has",
    "deep dive": "look at",
    "unpack": "explain",
    "learnings": "lessons",
    "synergy": "(describe effect)",
    "thought leadership": "expertise",
    "at its core": "(cut)",
    "game-changer": "(describe what changed)",
    "vibrant": "(specific)",
    "bustling": "(specific)",
    "thriving community": "(specific)",
    "realm": "field",
    "furthermore,": "also",
    "moreover,": "also",
    "additionally,": "also",
    "reflects broader": "(be specific)",
    "indelible mark": "(describe effect)",
    "deeply rooted": "(describe origin)",
    "align with": "match",
    "serves as": "is",
    "enhancing": "improve",
}


# ===== Em-dash density threshold (from response_audit.py check_em_dash_density) =====
# Max allowed: 1 em dash per 1000 words
_EM_DASH_THRESHOLD = 1000


# ===== Structural (ASD-STE100 derived) thresholds =====
_MAX_WORDS_INSTRUCTION = 20   # STE rule 5.1: instruction sentences
_MAX_WORDS_DESCRIPTIVE = 25   # STE rule 6.3: descriptive sentences
_PASSIVE_RATIO_THRESHOLD = 0.20   # flag when >20% of sentences are passive
_SYNONYM_MIN_WORDS = 120      # skip synonym-rotation check below this length

_INSTRUCTION_PATTERN = re.compile(r"^\s*(?:\d+[.)]\s+|[-*]\s+)?(?:Do|Run|Use|Add|Remove|Set|Check|Call|Read|Write|Edit|Verify|Confirm|Open|Close|Start|Stop)\b", re.I)

_NOMINALIZATION_PATTERN = re.compile(
    r"\b(?:perform|conduct|carry out|undertake|make|provide|give|do)\s+"
    r"(?:a|an|the)?\s*\w+(?:tion|ment|ance|ence|sis)\s+(?:of|to|for)\b",
    re.I,
)
_NOMINALIZATION_PHRASES = [
    "performs an analysis of", "perform an analysis of", "conducts an analysis of",
    "provides assistance", "provides support", "gives consideration to",
    "makes a decision", "make a decision",
]

# (verb stem, particle) — matched with inflection endings (s/es/ed/ing) on
# the verb so "reaches out" / "reached out" / "reaching out" all match, not
# just the bare infinitive.
_PHRASAL_VERBS = [
    ("reach", "out to"), ("reach", "out"), ("circle", "back"),
    ("touch", "base"), ("drill", "down into"), ("drill", "down"),
    ("double", "down"), ("loop", "in"), ("level", "up"),
    ("zero", "in on"), ("tease", "out"), ("flesh", "out"),
]
_PHRASAL_VERB_PATTERNS = [
    (verb, re.compile(r"\b" + re.escape(verb) + r"(?:es|ed|ing)?\s+" + re.escape(particle) + r"\b", re.I),
     f"{verb} {particle}")
    for verb, particle in _PHRASAL_VERBS
]

# Clusters of near-synonyms that indicate synonym rotation (STE 1.11: one
# name per thing). Flag when 2+ members of the same cluster appear in one
# document — a single use of any member is normal English, not a violation.
_SYNONYM_CLUSTERS = [
    {"user", "customer", "client"},
    {"start", "begin", "commence", "initiate"},
    {"show", "display", "present"},
    {"remove", "delete", "erase"},
]

# "present" carries a second, unrelated sense this cluster must not catch: the
# predicate adjective meaning "exists" ("is present in mcpServers", "always
# present by this point"), not the verb meaning "show/display". Real hits:
# scaffold/SKILL.md and web-design/SKILL.md each flagged synonym rotation on
# "display, present, show" with every "present" in the adjective sense and
# zero uses as a verb. A be-verb, or "always"/"already"/"still"/"no longer",
# immediately before "present", or "present" immediately before a locative
# preposition, covers every real instance found. This does not attempt full
# part-of-speech tagging: it only excludes the specific shapes observed, so it
# stays conservative rather than trying to enumerate every possible sentence.
_PRESENT_ADJECTIVE_RE = re.compile(
    r"\b(?:is|are|was|were|been|being)\s+(?:\w+\s+){0,4}present\b"
    r"|\b(?:always|already|still|no\s+longer)\s+present\b"
    r"|\bpresent\s+(?:in|at|on|within|inside)\b"
    r"|\bpresent(?=\s*[)\].,;:|]|\s*$)",
    re.I,
)

# STE_STRICT: for docs, commits, code comments — full word caps + structural checks.
STE_STRICT = ("long_sentence", "semicolon", "nominalization",
              "phrasal_verb", "passive", "synonym_rotation")

# STE_FLAVORED: for chat and subagent output — structural checks only, no caps.
# ASD-STE100 itself warns against applying hard caps to prose that needs voice.
STE_FLAVORED = ("nominalization", "phrasal_verb", "passive", "synonym_rotation")


def ste_mode() -> str:
    """Read HARNESS_KIT_STE env var. Returns 'off', 'warn', 'strict', or 'default'."""
    val = (config.env("STE") or "").strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    return "default"


def get_rule_kinds(retro_fix_enabled: bool = True) -> tuple:
    """Get rule kinds tuple, selecting STE_STRICT based on retro_fix and ste_mode.

    This function consolidates the rule selection logic shared by guard_comment_debt
    and guard_style, ensuring they scan identical rule sets when retro_fix_enabled()
    is on (issue: guard-rule-sync).

    When retro_fix_enabled is True, STE_STRICT (structural rules) is included if
    ste_mode() != "off". When False, STE_STRICT is excluded.

    The base rule kinds are always: ("ai_ism", "tier1", "residue").

    Args:
        retro_fix_enabled: Whether retroactive fixing is enabled. Typically obtained
            from config.retro_fix_enabled(), or True as a safe default.

    Returns:
        Tuple of rule kinds to pass to scan().
    """
    kinds = ("ai_ism", "tier1", "residue")
    if retro_fix_enabled and ste_mode() != "off":
        kinds = kinds + STE_STRICT
    return kinds


# ===== Conversation/decision residue patterns (guard_doc_residue) =====
#
# 28 rules across 16 categories, replacing an earlier 10-rule/6-category table
# that caught 2 of 12 measured probe sentences (issue #45). Three suppressors
# in _prose_only_aligned() (quote-strip, blockquote-strip) and in scan() below
# (sentence anchoring, skills/agents path standdown) cut the false-positive
# rate this wider table produced on the kit's own docs from roughly half to
# roughly a third, measured against 165 files.
#
# Two refinements over the first draft: "turns out" narrowed to "it turned
# out" (the present tense reads as a conditional, e.g. "if a task turns out
# heavier"), and "this (change|edit|commit)" anchored to a sentence start
# (mid-sentence it matches ordinary domain prose, e.g. "would this edit have
# changed").
_RESIDUE_PATTERNS = [
    (re.compile(r"^step \d+\b|^(?:first|next|then|now),\s", re.I | re.M), "tutorial narration"),
    (re.compile(r"^(?:renamed|moved|extracted|switched|migrated|converted|refactored|replaced|split)\s+(?:it\s+|them\s+|this\s+)?from\b", re.I | re.M), "change narration"),
    # "is used to call" states a purpose, and "used to live-test" is a compound
    # verb. Both read as history to the old pattern (live run v62, 2026-09-23).
    (re.compile(r"\bwas (?:previously|originally|formerly)\b"
                r"|(?<!\bis )(?<!\bare )(?<!\bwas )(?<!\bwere )(?<!\bbe )(?<!\bbeen )"
                r"\bused to (?:be|return|call|live|sit)\b(?!-)", re.I), "change narration"),
    (re.compile(r"\bno longer (?:needed|used|required|necessary)\b", re.I), "change narration"),
    (re.compile(r"\b(?:this|it) now\b|^this (?:change|edit|commit)\b", re.I | re.M), "change narration"),
    (re.compile(r"\b(?:replaces|supersedes|deprecates) the (?:old|previous|former)\b", re.I), "change narration"),
    (re.compile(r"\bbug where\b|\bfixes? the (?:bug|issue|problem|regression)\b", re.I), "defect narration"),
    (re.compile(r"\bnot sure (?:if|why|whether|what)\b|\b(?:might|may) be worth\b|\bfor now\b", re.I), "unresolved deliberation"),
    (re.compile(r"\bfeel free to\b|\bkeep in mind\b|\bif that makes sense\b|\blet me\b", re.I), "conversational address"),
    (re.compile(r"\byou (?:asked|wanted|requested|mentioned|said|noted|suggested|prefer|flagged)\b", re.I), "reader address"),
    (re.compile(r"\b(?:as )?per your\b|\bas you (?:requested|asked|said|noted|mentioned|wanted)\b", re.I), "reader address"),
    (re.compile(r"\byour (?:request|feedback|comment|preference|instruction|note|call)s?\b", re.I), "reader address"),
    (re.compile(r"\bI (?:recommend|lean|think|suggest|reckon|assume|added|changed|removed|kept|chose|opted|went)\b", re.I), "first-person opinion"),
    (re.compile(r"\bmy (?:lean|pick|recommendation|take|call|guess|assumption)\b", re.I), "first-person opinion"),
    (re.compile(r"\b(?:locked|decided|agreed|confirmed)\s+\d{4}-\d{2}-\d{2}\b", re.I), "dated decision stamp"),
    (re.compile(r"\buser decision\b|\(\s*(?:locked|decided|per user)\b[^)]*\)", re.I), "decision narration"),
    (re.compile(r"\bwe (?:decided|chose|agreed|discussed|picked|settled)\b|\blet'?s\b", re.I), "decision narration"),
    (re.compile(r"\b(?:honestly|frankly|admittedly|arguably|presumably|hopefully)\b", re.I), "conversational filler"),
    (re.compile(r"\bworth (?:flagging|noting|mentioning)\b|\bthe (?:catch|crux|gotcha|trick) is\b", re.I), "conversational filler"),
    (re.compile(r"\bas (?:we )?discussed\b|\bas we saw\b", re.I), "chat reference"),
    (re.compile(r"\bthe assistant\b|\bai[- ]generated\b|\b(?:claude|chatgpt|copilot)\s+(?:wrote|generated|produced|suggested|added|created)\b", re.I), "assistant self-reference"),
    (re.compile(r"\b(?:in|earlier in|during) (?:this|the) (?:session|conversation|thread|turn)\b|\b(?:this|the previous|the last) turn\b", re.I), "session-time reference"),
    (re.compile(r"\bafter (?:a few|several|some|many) (?:attempts|tries|goes)\b|\btrial and error\b|\bit turned out\b|\bat first,\s", re.I), "attempt narration"),
    (re.compile(r"\bthe user (?:wants|asked|said|prefers|requested|mentioned|flagged|confirmed)\b", re.I), "third-person user ref"),
    (re.compile(r"\bhope (?:this|that) helps\b|\blet me know\b|\bapologies\b|\bsorry (?:about|for)\b", re.I), "courtesy close"),
    (re.compile(r"\bper our (?:conversation|discussion|chat|call)\b|\bbased on your feedback\b|\bfrom the chat\b", re.I), "conversation reference"),
    (re.compile(r"\bI(?:'ve| have) (?:added|updated|changed|removed|fixed|created|left|moved|renamed)\b", re.I), "agent action narration"),
    (re.compile(r"\bleft as[- ]is\b|\bplaceholder until\b|\bpending (?:discussion|a decision)\b|\bTBD pending\b", re.I), "deferred decision"),
]

# Labels stood down under skills/ and agents/ paths (issue #45): a skill or
# agent file legitimately addresses "the user" as a trigger condition and
# instructs an agent directly, which is not a narrated past conversation.
# Path-scoped rather than content-scoped, since the tell is where the file
# lives, not anything the sentence itself contains.
_RESIDUE_PATH_STANDDOWN = frozenset((
    "conversational address", "unresolved deliberation",
    "third-person user ref", "session-time reference",
))

# Six labels carried over from the original 10-entry table (some
# consolidated under a new name here, all with a proven survivor list from
# running in production as blocking findings). Every other label in the
# 28-rule table is new in this fix and ships advisory-only, per issue #45's
# own recommendation, until its own survivor list is clean on a larger
# corpus. guard_style.py is the only hook that can block on a residue
# finding at all; guard_doc_residue.py and guard_comment_debt.py are
# advisory regardless of label.
RESIDUE_BLOCKING_LABELS = frozenset((
    "dated decision stamp", "decision narration", "chat reference",
    "reader address", "first-person opinion", "conversational filler",
))


def _residue_standdown_active(filepath: str) -> bool:
    if not filepath:
        return False
    # An absolute path (what tool_input.file_path is in practice) always has
    # a "/" before "skills"/"agents". A project-relative path (what at least
    # scripts/check_uncommitted.py passes, per its own "rel" variable name)
    # does not, so the leading-component case needs its own check rather
    # than only the mid-path substring.
    norm = filepath.replace("\\", "/").lstrip("/")
    return (norm.startswith("skills/") or norm.startswith("agents/")
            or "/skills/" in norm or "/agents/" in norm)


def prose_only(text: str) -> str:
    """Strip non-prose regions before structural/AI-ism analysis.

    Removes fenced code blocks, inline code, YAML frontmatter, ATX headings,
    markdown tables, list-marker prefixes, bold/italic emphasis markers, and
    bare URLs. Shared by every hook that scans markdown so there is one strip
    implementation instead of each hook carrying its own narrower version.

    Emphasis markers unwrap rather than delete: `**Label.**` becomes
    `Label.`, keeping the text but dropping the asterisks. Left wrapped, a
    line like `**Step 0.** Run the setup.` puts the period one character
    before the `**`, so _split_sentences' boundary check (period immediately
    before whitespace) never fires there. That glued the bold lead-in to
    every numbered-list item in web-design/SKILL.md onto the sentence after
    it, inflating three separate short sentences into one over-cap run-on.
    Found 2026-08-12 auditing health_check's own long_sentence findings.
    """
    result = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # A code span is not prose regardless of how the source wraps it. The
    # old `[^`\n]*` excluded newlines entirely, so a span broken across a
    # line (`` `foo` bar `` `baz` ``) never stripped past the first line,
    # leaking the identifier into prose checks (issue #9). Allow a single
    # newline inside a span but not a blank line, so an unbalanced opening
    # backtick can't swallow past the next paragraph break looking for its
    # close, and cap the repeat count so it can't run away regardless.
    result = re.sub(r"`(?:[^`\n]|\n(?!\n)){0,500}`", "", result)
    result = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", result)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", result)
    if result.startswith("---\n"):
        result = re.sub(r"^---\n.*?\n---\n", "", result, count=1, flags=re.DOTALL)
    result = re.sub(r"^#{1,6}\s+.*$", "", result, flags=re.MULTILINE)
    # Markdown thematic breaks (---, ***, ___ alone on a line) are structural,
    # not prose. Left unstripped they glue the sentence before and after into
    # one run-on when whitespace is later collapsed for sentence splitting.
    result = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "\n\n", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*\|.*\|\s*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", result, flags=re.MULTILINE)
    result = re.sub(r"https?://\S+", "", result)
    return result


def _prose_only_aligned(text: str) -> str:
    """Like prose_only(), but preserves the original line count and line
    numbers instead of collapsing removed regions away.

    scan()'s word-level checks (ai_ism, tier1, em_dash, residue) need to
    match against stripped prose -- otherwise a tier-1 word in YAML
    frontmatter or a table gets flagged as if it were body prose -- but they
    also report a `line` number back to the caller, which has to point at
    the original file for the finding to be useful. prose_only() itself
    deliberately does NOT preserve alignment (frontmatter and fenced code
    blocks are deleted outright, and a thematic break is turned into an
    extra blank line on purpose, to stop sentence-splitting from gluing
    paragraphs together). This variant keeps every removed span's newline
    count intact so `stripped.splitlines()[i]` still lines up with the
    source file's line `i + 1`.

    Same-line whitespace uses `[ \\t]` instead of prose_only()'s `\\s`: `\\s`
    matches `\\n`, so `^\\s*` before a table/list/thematic-break marker
    silently eats every blank line above it into the match, and dropping
    those newlines along with it desyncs every later line number.
    """
    def _blank(m):
        return "\n" * m.group(0).count("\n")

    result = re.sub(r"```.*?```", _blank, text, flags=re.DOTALL)
    result = re.sub(r"`[^`\n]*`", "", result)
    # A double-quoted span never contains a newline by construction ([^\n]),
    # so stripping it with "" cannot desync a line count the way deleting a
    # fenced block would -- that risk is specific to multi-line spans, which
    # is why those go through _blank above instead. Issue #45: a verbatim
    # quote naming a flagged word or phrase is not this file's own claim,
    # and scanning it as prose produced the false-positive class that
    # blocked six drafts of that issue and, independently, this fix's own
    # planning session, on quoted rule text like this comment's own example.
    result = re.sub(r'"[^"\n]{0,300}"', "", result)
    # A blockquote line (> ...) quotes someone else's words by markdown
    # convention, the same reason a fenced code block or a table row is not
    # this file's own prose. `.` excludes \n by default, so the match never
    # crosses a line and the trailing newline survives untouched.
    result = re.sub(r"^>[ \t]?.*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", result)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", result)
    if result.startswith("---\n"):
        result = re.sub(r"^---\n.*?\n---\n", _blank, result, count=1, flags=re.DOTALL)
    result = re.sub(r"^#{1,6}[ \t]+.*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^[ \t]*\|.*\|[ \t]*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", "", result, flags=re.MULTILINE)
    result = re.sub(r"https?://\S+", "", result)
    return result


# ===== Per-language comment grammar =====
#
# Ten grammar families. Only the tokens a language actually uses are enabled for
# that language, so `#` as a C preprocessor directive and `--` as SQL negation
# cannot be read as a comment opener in a language that lacks that form.
#
# Each family declares line-comment openers and (open, close) block pairs. A
# language with no block form gets an empty tuple.
COMMENT_GRAMMARS = {
    "c":     {"line": ("//",),         "block": (("/*", "*/"),)},
    "hash":  {"line": ("#",),          "block": ()},
    "sql":   {"line": ("--",),         "block": (("/*", "*/"),)},
    "html":  {"line": (),              "block": (("<!--", "-->"),)},
    "razor": {"line": ("//",),         "block": (("/*", "*/"), ("@*", "*@"))},
    "ps":    {"line": ("#",),          "block": (("<#", "#>"),)},
    "lua":   {"line": ("--",),         "block": (("--[[", "]]"),)},
    "lisp":  {"line": (";",),          "block": ()},
    "pct":   {"line": ("%",),          "block": ()},
    "batch": {"line": ("::", "rem "),  "block": ()},
    # block-only: a family with no line-comment token at all. Routing one of
    # these to "c" reads a "//" inside ordinary content as a comment opener --
    # issue #41's headline case is `url(http://...)` inside CSS, which is not
    # a comment in CSS at all, so it silently drops real code as prose.
    "block": {"line": (),              "block": (("/*", "*/"),)},
    # Three distinct template-comment tokens, kept separate rather than
    # merged into one family: routing hbs's "{{! }}" through jinja's "{# #}"
    # would find no comments at all, and either token in the wrong file is
    # ordinary template syntax, not a comment.
    "jinja": {"line": (),              "block": (("{#", "#}"),)},
    "ejs":   {"line": (),              "block": (("<%#", "%>"),)},
    # "{{!--" checked before "{{!" -- the longer pair is a specific case of
    # the shorter opener, so trying the short one first would still find the
    # comment but leave its own "--" delimiters as visible prose text.
    "hbs":   {"line": (),              "block": (("{{!--", "--}}"), ("{{!", "}}"))},
}

_GRAMMAR_EXT_GROUPS = {
    "c": (
        "c", "h", "cc", "cpp", "cxx", "hpp", "hxx", "cs", "java", "js", "jsx",
        "mjs", "cjs", "ts", "tsx", "mts", "cts", "go", "rs", "swift", "kt",
        "kts", "scala", "groovy", "dart", "php", "mm", "vala", "zig", "d",
        "jl", "as", "hx", "sol", "gd", "glsl", "vert", "frag", "hlsl",
        "metal", "proto", "thrift", "less", "scss", "sass", "styl", "vue",
        "svelte", "astro", "json5", "jsonc", "gradle",
        # issue #41: hh (C++ header variant), ino (Arduino), pde (Processing),
        # sv/v (SystemVerilog/Verilog), m (Objective-C), cu/cuh (CUDA) all use
        # // and /* */. fs/fsi/fsx (F#) share the // line token; F#'s real
        # block form is (* *) rather than /* */, so a block comment there is
        # missed rather than misread -- the safer direction for a lint.
        "hh", "ino", "pde", "sv", "v", "m", "fs", "fsi", "fsx", "cu", "cuh",
    ),
    "hash": (
        "py", "pyi", "pyx", "sh", "bash", "zsh", "fish", "ksh", "rb", "rake",
        "gemspec", "pl", "pm", "r", "tcl", "awk", "yml", "yaml", "toml",
        "ini", "cfg", "conf", "properties", "env", "gitignore",
        "dockerignore", "editorconfig", "mk", "cmake", "nix", "tf",
        "tfvars", "hcl", "nim", "cr", "ex", "exs", "coffee", "gitconfig",
        "gitattributes", "service", "desktop", "spec",
        "npmrc", "make",
    ),
    "sql": (
        "sql", "psql", "mysql", "plsql", "pgsql", "hql", "ddl", "dml",
        "tsql", "pls", "prc",
    ),
    "html": (
        "html", "htm", "xhtml", "xml", "xsl", "xslt", "svg", "plist",
        "resx", "csproj", "vbproj", "wxs",
        # issue #41's MSBuild/WebForms cluster. Each is XML with no // or
        # /* */ at all, so the old "c" fallback found no real comments and
        # nothing stopped a "//" inside a URL from opening a fake one.
        "aspx", "ascx", "master", "axml", "xaml", "xsd", "wsdl", "config",
        "props", "targets", "nuspec", "fsproj", "sqlproj",
    ),
    "razor": ("razor", "cshtml", "vbhtml"),
    "ps": ("ps1", "psm1", "psd1"),
    "lua": (
        "lua", "rockspec", "hs", "elm", "purs", "idr", "agda", "ada", "adb",
        "ads", "vhd", "vhdl", "applescript", "scpt",
    ),
    "lisp": (
        "lisp", "cl", "el", "clj", "cljs", "cljc", "edn", "scm", "ss", "rkt",
        "fnl", "asm", "s", "nasm",
    ),
    "pct": ("tex", "sty", "cls", "bib", "ltx", "erl", "hrl", "prolog", "pro"),
    "batch": ("bat", "cmd"),
    # css has /* */ and no line comment. Routing it to "c" would read the
    # "//" in url(http://...) as a comment opener -- issue #41's headline
    # case, 501 files in the census this fix was measured against.
    "block": ("css",),
    "jinja": ("jinja", "j2", "twig"),
    "ejs": ("ejs",),
    "hbs": ("hbs", "handlebars"),
}

# Extension to grammar family. Suffixes carry no leading dot.
_GRAMMAR_BY_EXT = {
    ext: family
    for family, exts in _GRAMMAR_EXT_GROUPS.items()
    for ext in exts
}

# Comment-less or binary formats. These drop out rather than falling back to a
# grammar, because a fallback scan of a data file is pure noise.
SKIP_EXTENSIONS = frozenset((
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "tiff", "avif",
    "mp3", "mp4", "wav", "ogg", "flac", "webm", "mov", "avi", "mkv",
    "zip", "gz", "bz2", "xz", "zst", "7z", "rar", "tar", "jar", "war",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods",
    "so", "dylib", "dll", "exe", "bin", "o", "a", "lib", "pyc", "pyo",
    "class", "wasm", "db", "sqlite", "sqlite3", "csv", "tsv", "parquet",
    "lock", "sum", "woff", "woff2", "ttf", "otf", "eot", "ipynb", "json",
    # issue #41: a census of 100,914 files across 597 extensions found these
    # binary formats among the unmapped ones, all falling to the "c" fallback
    # before this fix. jsonl is issue #41's own example: a data file with
    # comment-shaped syntax nowhere in it.
    "crate", "nupkg", "rmeta", "rlib", "p7s", "sha512", "tga", "snd", "m4a",
    "stl", "ldb", "pak", "jsonlz4", "gguf", "3mf", "glb", "jsonl",
))

# Files whose whole body is text, so there is no comment syntax to resolve.
PROSE_ROUTE_EXTS = frozenset((
    "md", "mdx", "markdown", "rst", "txt", "adoc", "asciidoc", "org", "text",
))

# Shebang interpreter to grammar family, for a bare-name executable script.
_SHEBANG_FAMILIES = (
    (("python", "ruby", "perl", "bash", "zsh", "fish", "tcl", "awk"), "hash"),
    (("node", "deno", "bun"), "c"),
    (("pwsh", "powershell"), "ps"),
    (("lua",), "lua"),
)

_BARE_NAME_HASH = (
    "makefile", "dockerfile", "containerfile", "justfile", "rakefile",
    "gemfile", "vagrantfile", "brewfile", "procfile", "pkgbuild",
)

PROSE_ROUTE = "PROSE"


# Bytes sniffed from the head of a file to tell binary from text when no
# extension, shebang or bare name says which. 2KB is enough to catch a NUL
# in any binary format actually seen in the census this fix was measured
# against; a text file this short with a genuine NUL in its first 2KB does
# not occur in that census.
_BINARY_SNIFF_WINDOW = 2048


def _looks_binary(code: str) -> bool:
    return "\x00" in code[:_BINARY_SNIFF_WINDOW]


def grammar_for(filepath: str, code: str = "") -> str | None:
    """Grammar family for a file, or None when it must not be scanned.

    Three outcomes, matching the routing this guard needs: a family name for a
    file with comment syntax, PROSE_ROUTE for a file whose whole body is text,
    and None for a binary or comment-less data format.

    An unmapped suffix used to fall to "c" unconditionally -- issue #41's
    class bug, since 21.7% of files on a real machine carried an extension
    absent from every table here (597 distinct suffixes, 122 mapped). Most
    of that gap is now closed by the tables above. What remains sniffs the
    actual bytes: a NUL in the first 2KB means binary, dropped like any other
    comment-less format. Text with no known grammar still gets "c", the
    widest real match, but grammar_is_known() marks the call low-confidence
    so a caller can report rather than block on it.
    """
    name = Path(filepath).name
    suffix = Path(filepath).suffix.lower().lstrip(".")
    if suffix in SKIP_EXTENSIONS:
        return None
    if suffix in PROSE_ROUTE_EXTS:
        return PROSE_ROUTE
    if suffix in _GRAMMAR_BY_EXT:
        return _GRAMMAR_BY_EXT[suffix]
    if not suffix:
        lowered = name.lower()
        if lowered.startswith(_BARE_NAME_HASH):
            return "hash"
        first = (code.splitlines() or [""])[0]
        if first.startswith("#!"):
            for names, family in _SHEBANG_FAMILIES:
                if any(n in first for n in names):
                    return family
            return "hash"
        # LICENSE, AUTHORS, NOTICE and friends.
        return PROSE_ROUTE
    # Unknown suffix. A real binary format under a suffix nobody has curated
    # drops out rather than being scanned as C.
    if code and _looks_binary(code):
        return None
    # Still unknown, and text. C-style is the most widespread comment
    # grammar, so it is the fallback rather than a drop -- but see
    # grammar_is_known() below, since this branch is a guess, not a match.
    return "c"


def grammar_is_known(filepath: str) -> bool:
    """False only for the blind C-style guess at the end of grammar_for().

    Every other outcome -- an explicit family, PROSE_ROUTE, a shebang match,
    a bare-name match, or None for a skipped format -- comes from a table
    someone actually curated for that case. A guard that hard-blocks should
    not do so on a guess: issue #41 is exactly this pattern, an unmapped
    suffix scanned as if it were C and mis-parsed as a result. This check
    needs no file content, only the suffix, so a caller can use it before
    ever reading the file.
    """
    suffix = Path(filepath).suffix.lower().lstrip(".")
    if not suffix:
        return True
    return suffix in SKIP_EXTENSIONS or suffix in PROSE_ROUTE_EXTS or suffix in _GRAMMAR_BY_EXT


def _python_docstrings(code: str) -> list:
    """Every module/class/function docstring in `code`, via ast.get_docstring.

    A hash-style extraction alone finds only `#` comments. In Python, most
    real prose lives in docstrings, which carry no `#` at all, so the hash
    pass left the sample near-empty on a well-documented file and stray
    section-divider comments dominated it instead. A two-word divider like
    "# things that must not be flagged" grammatically contains "be flagged"
    and reads as passive in isolation; against a handful of divider lines as
    the entire sample, one such fragment alone crossed the ratio threshold.
    Docstrings restore a real, representative sample.

    Returns [] on a syntax error rather than raising: a hook mid-Edit can see
    invalid Python, and a miss here is far cheaper than crashing the guard.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    out = []
    nodes = [tree] + [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in nodes:
        doc = ast.get_docstring(node)
        if doc:
            out.append(doc)
    return out


_QUOTE_CHARS = "\"'`"


def extract_comment_spans(code: str, family: str) -> list:
    """Comment regions in `code` under one grammar family.

    Returns [{"text", "line", "inline", "block"}] in source order. `line` is
    1-based. `inline` is True when code preceded the opener on that line, which
    is what separates a trailing note from a documentation block.

    Scans character by character tracking quote state, because the previous
    line-split approach could not tell a comment opener from the same
    characters inside a string literal. Two live consequences: in a hash
    language `color = "#fff"` yielded `fff"` as comment prose, and in a
    C-family language any `https://` inside a string literal opened a comment
    that swallowed the rest of the line.
    """
    grammar = COMMENT_GRAMMARS.get(family)
    if not grammar:
        return []
    line_tokens = grammar["line"]
    block_pairs = grammar["block"]

    spans = []
    i, n = 0, len(code)
    line_no = 1
    quote = None
    code_seen_on_line = False

    while i < n:
        ch = code[i]

        if ch == "\n":
            line_no += 1
            code_seen_on_line = False
            i += 1
            continue

        if quote:
            # Inside a string. Only the matching close quote, honouring escapes,
            # gets us out. Nothing here can open a comment.
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in _QUOTE_CHARS:
            quote = ch
            code_seen_on_line = True
            i += 1
            continue

        matched = False
        for opener, closer in block_pairs:
            if code.startswith(opener, i):
                start_line = line_no
                j = code.find(closer, i + len(opener))
                if j == -1:
                    body, i = code[i + len(opener):], n
                else:
                    body, i = code[i + len(opener):j], j + len(closer)
                spans.append({
                    "text": body,
                    "line": start_line,
                    "inline": code_seen_on_line,
                    "block": True,
                })
                line_no += body.count("\n")
                matched = True
                break
        if matched:
            continue

        for opener in line_tokens:
            if code.startswith(opener, i):
                j = code.find("\n", i)
                end = n if j == -1 else j
                body = code[i + len(opener):end]
                # A shebang is an interpreter directive, not prose.
                if not (opener == "#" and code.startswith("#!", i) and start_of_file(code, i)):
                    spans.append({
                        "text": body,
                        "line": line_no,
                        "inline": code_seen_on_line,
                        "block": False,
                    })
                i = end
                matched = True
                break
        if matched:
            continue

        if not ch.isspace():
            code_seen_on_line = True
        i += 1

    return spans


def start_of_file(code: str, index: int) -> bool:
    """True when `index` sits on the first line of `code`."""
    return "\n" not in code[:index]


def extract_comments_and_strings(code: str, filepath: str) -> str:
    """Extract comment and docstring text from source code for prose scanning.

    Only returns text from comment/docstring regions, never identifiers or
    code syntax, so a variable named e.g. `utilize_fn` does not trigger a
    tier1 finding.
    """
    family = grammar_for(filepath, code)
    if family is None:
        return ""
    if family == PROSE_ROUTE:
        return code

    extracted = [s["text"] for s in extract_comment_spans(code, family)]

    if Path(filepath).suffix.lower() in (".py", ".pyi", ".pyx"):
        extracted.extend(_python_docstrings(code))

    return "\n".join(extracted)


def _split_line_into_sentences(line: str) -> list:
    """One physical line split into sentences on . ! ? boundaries.

    Factored out of _split_sentences() so a caller that needs the line
    number back (the residue scan, anchoring a rule like "^this change" to a
    sentence start rather than a wrapped continuation line) can pair each
    result with the line it came from, instead of losing that mapping the
    way _split_sentences()'s flat return already does.

    Closing emphasis markers (**, *, __, _, `) and closing brackets or
    parentheses that appear between the terminal punctuation and the
    following whitespace are treated as part of the sentence boundary and
    do not prevent the split.
    """
    line = re.sub(r"[ \t]+", " ", line).strip()
    if not line:
        return []
    # A divider ("# ---...---", "# ====") carries no words at all and is
    # not a sentence in any sense these checks care about. Counting it
    # inflates the denominator with noise, which is how a comment section
    # of two real titles and four divider lines turned one accidental
    # passive fragment into "1 in 4" instead of "1 in 70" against a file's
    # actual prose.
    if not re.search(r"[A-Za-z]", line):
        return []

    # Split on boundaries: terminal punctuation, optional closing markdown/brackets,
    # then whitespace followed by uppercase/paren. This handles cases like
    # "**Bold.** Next" correctly even when markdown markers are not pre-stripped.
    sentences = []
    last_start = 0
    for m in re.finditer(r'[.!?][*_`\]\)]*\s+(?=[A-Z(])', line):
        # Extract sentence up to and including the punctuation and emphasis markers,
        # but not the whitespace that separates sentences.
        sentence_end = m.start() + len(m.group(0).rstrip())
        sentence = line[last_start:sentence_end].strip()
        if sentence:
            sentences.append(sentence)
        last_start = m.end()

    # Add the final sentence
    final = line[last_start:].strip()
    if final:
        sentences.append(final)

    return sentences


def _split_sentences(text: str) -> list:
    """Rough sentence split: on . ! ? followed by whitespace, skipping common abbreviations.

    Never joins text across a newline. Splitting per line first undercounts
    a sentence a human hard-wrapped across two lines (rare here), which is
    the safer failure direction for a lint: fewer false positives, not more.
    See _split_line_into_sentences() for the per-line logic and why it
    exists as its own function.
    """
    sentences = []
    for line in text.splitlines():
        sentences.extend(_split_line_into_sentences(line))
    return sentences


_PASSIVE_PATTERN = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+ed\b", re.I
)


def _is_passive(sentence: str) -> bool:
    return bool(_PASSIVE_PATTERN.search(sentence))


def tier1_map() -> dict:
    """Return dict of tier-1 words to their replacements."""
    return _TIER1_WORDS.copy()


# 13 of the 52 literal tier-1 entries flip leading vowel/consonant sound on
# replacement ("actionable" -> "practical", "embark" -> "start"). A rewriter
# that swaps the word but leaves the preceding article produces "an
# practical" or "a approach". Found sweeping this repo's own docs with the
# fix this powers, prose_sweep.py.
_AN_EXCEPTION_WORDS = frozenset((
    "university", "unique", "user", "users", "usual", "use", "used",
    "useful", "usefully", "european", "one", "once",
))
_A_EXCEPTION_WORDS = frozenset(("hour", "honest", "honor", "heir"))
_ARTICLE_RE = re.compile(r"\b([Aa]n?)(\s+)(\w+)")


def _wants_an(word: str) -> bool:
    lowered = word.lower()
    if lowered in _AN_EXCEPTION_WORDS or lowered.startswith("uni"):
        return False
    if lowered in _A_EXCEPTION_WORDS or lowered.startswith("hour"):
        return True
    return lowered[:1] in "aeiou"


def fix_article_agreement(text: str) -> str:
    """Correct "a"/"an" against the word that now follows it.

    Call this once, after every substitution in a rewrite pass has already
    run, so it sees the word the reader will actually see next rather than
    the one a tier-1 swap just replaced.
    """
    def _fix(m):
        article, space, word = m.group(1), m.group(2), m.group(3)
        want_an = _wants_an(word)
        had_an = article.lower() == "an"
        if want_an == had_an:
            return m.group(0)
        new_article = "an" if want_an else "a"
        if article[:1].isupper():
            new_article = new_article.capitalize()
        return new_article + space + word

    return _ARTICLE_RE.sub(_fix, text)


def banned_phrases() -> list:
    """Return list of banned chatbot phrases."""
    return _BANNED_PHRASES.copy()


def scan(text: str, kinds: tuple = ("ai_ism", "tier1", "em_dash", "residue"),
         filepath: str = "", first_only: bool = True) -> list:
    """
    Scan text for prose rule violations.

    Args:
        text: Text to scan.
        kinds: Tuple of rule kinds to check. Options: "ai_ism", "tier1", "em_dash", "residue".
        filepath: Source path, used only by "residue" to stand down four
            labels under skills/ and agents/ paths (issue #45).
        first_only: True (default) matches every guard's existing behaviour --
            one finding per pattern, enough to nudge a rewrite. False reports
            every occurrence with its own line (and, for "em_dash", column),
            which is what a sweep needs to fix each instance rather than one.

    Returns:
        List of findings, each a dict: {"kind", "label", "match", "line"}.
    """
    findings = []
    # Word-level checks match against stripped prose, not raw text, so YAML
    # frontmatter, fenced code, headings and tables aren't policed as body
    # prose (issue #10). _prose_only_aligned keeps line numbers pointing at
    # the original file even though the matched content is stripped.
    stripped = _prose_only_aligned(text)
    stripped_lower = stripped.lower()
    lines = stripped.splitlines()

    # ===== AI-isms: banned phrases =====
    if "ai_ism" in kinds:
        for phrase in _BANNED_PHRASES:
            if phrase in stripped_lower:
                for line_num, line in enumerate(lines, 1):
                    if phrase in line.lower():
                        findings.append({
                            "kind": "ai_ism",
                            "label": f"banned phrase '{phrase}'",
                            "match": phrase,
                            "line": line_num,
                        })
                        break

    # ===== Tier 1 words =====
    if "tier1" in kinds:
        for word in _TIER1_WORDS:
            if " " in word:
                # Multi-word phrase
                if word in stripped_lower:
                    for line_num, line in enumerate(lines, 1):
                        if word in line.lower():
                            findings.append({
                                "kind": "tier1",
                                "label": f"tier-1 word '{word}'",
                                "match": word,
                                "line": line_num,
                            })
                            break
            else:
                # Single word — word boundary match
                pattern = r"\b" + re.escape(word) + r"\b"
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        findings.append({
                            "kind": "tier1",
                            "label": f"tier-1 word '{word}'",
                            "match": word,
                            "line": line_num,
                        })
                        break

    # ===== Em-dash density =====
    if "em_dash" in kinds:
        em_dash_count = stripped.count("—")
        word_count = len(stripped.split())
        allowed = max(1, word_count // _EM_DASH_THRESHOLD)
        if em_dash_count > allowed:
            if first_only:
                findings.append({
                    "kind": "em_dash",
                    "label": f"em dash overuse: {em_dash_count} found, max {allowed} per {word_count} words",
                    "match": "—",
                    "line": 0,  # Whole-document check
                })
            else:
                # Per-occurrence mode (issue #45): a sweep corrects each em
                # dash in place, so it needs a line and column per hit, not
                # one document-wide verdict. Still gated on the same
                # density threshold -- a document under the allowance is
                # not a violation, so nothing here reports it either.
                line_num = 1
                line_start = 0
                for idx, ch in enumerate(stripped):
                    if ch == "\n":
                        line_num += 1
                        line_start = idx + 1
                    elif ch == "—":
                        findings.append({
                            "kind": "em_dash",
                            "label": f"em dash overuse: {em_dash_count} found, max {allowed} per {word_count} words",
                            "match": "—",
                            "line": line_num,
                            "column": idx - line_start,
                        })

    # ===== Residue patterns =====
    if "residue" in kinds:
        standdown = _residue_standdown_active(filepath)
        # Sentence-anchored, not raw-line-anchored (issue #45): a rule like
        # "^(?:first|next|then|now),\s" used to fire on a wrapped
        # continuation line that only looked like a sentence start once
        # whitespace collapsed. Splitting each line into its own sentences
        # first, then anchoring against each sentence, is the fix; see
        # _split_line_into_sentences() above.
        sentence_lines = []
        for line_num, line in enumerate(lines, 1):
            for sentence in _split_line_into_sentences(line):
                sentence_lines.append((line_num, sentence))
        for pattern, label in _RESIDUE_PATTERNS:
            if standdown and label in _RESIDUE_PATH_STANDDOWN:
                continue
            for line_num, sentence in sentence_lines:
                m = pattern.search(sentence)
                if m:
                    findings.append({
                        "kind": "residue",
                        "label": label,
                        "match": m.group(0),
                        "line": line_num,
                    })
                    if first_only:
                        break

    # ===== Structural: any of the ASD-STE100-derived kinds requested =====
    structural = {"long_sentence", "semicolon", "nominalization",
                  "phrasal_verb", "passive", "synonym_rotation"} & set(kinds)
    if structural:
        stripped = prose_only(text)

        if "semicolon" in structural:
            for line_num, line in enumerate(stripped.splitlines(), 1):
                if ";" in line:
                    findings.append({
                        "kind": "semicolon",
                        "label": "semicolon in prose (STE 6.3 bans it)",
                        "match": ";",
                        "line": line_num,
                    })

        if "nominalization" in structural:
            seen_nom = set()
            stripped_lower = stripped.lower()
            for phrase in _NOMINALIZATION_PHRASES:
                if phrase in stripped_lower and phrase not in seen_nom:
                    seen_nom.add(phrase)
                    findings.append({
                        "kind": "nominalization",
                        "label": f"nominalized verb '{phrase}' (STE 3.7: use the verb)",
                        "match": phrase,
                        "line": 0,
                    })
            for m in _NOMINALIZATION_PATTERN.finditer(stripped):
                match_lower = m.group(0).lower()
                if match_lower not in seen_nom:
                    seen_nom.add(match_lower)
                    findings.append({
                        "kind": "nominalization",
                        "label": f"nominalized verb '{m.group(0)}' (STE 3.7: use the verb)",
                        "match": m.group(0),
                        "line": 0,
                    })

        if "phrasal_verb" in structural:
            seen_verbs = set()
            for verb, pattern, label in _PHRASAL_VERB_PATTERNS:
                if verb in seen_verbs:
                    continue
                m = pattern.search(stripped)
                if m:
                    seen_verbs.add(verb)
                    findings.append({
                        "kind": "phrasal_verb",
                        "label": f"phrasal verb '{label}' (STE 9.3: use the plain verb)",
                        "match": m.group(0),
                        "line": 0,
                    })

        need_sentences = {"long_sentence", "passive", "synonym_rotation"} & structural
        if need_sentences:
            sentences = _split_sentences(stripped)

            if "long_sentence" in structural:
                for s in sentences:
                    word_count = len(s.split())
                    cap = _MAX_WORDS_INSTRUCTION if _INSTRUCTION_PATTERN.match(s) else _MAX_WORDS_DESCRIPTIVE
                    if word_count > cap:
                        findings.append({
                            "kind": "long_sentence",
                            "label": f"sentence has {word_count} words, cap is {cap} (STE 5.1/6.3)",
                            "match": s[:60] + ("..." if len(s) > 60 else ""),
                            "line": 0,
                        })

            if "passive" in structural and sentences:
                passive_count = sum(1 for s in sentences if _is_passive(s))
                ratio = passive_count / len(sentences)
                if ratio > _PASSIVE_RATIO_THRESHOLD:
                    findings.append({
                        "kind": "passive",
                        "label": f"passive voice in {passive_count}/{len(sentences)} sentences, over {int(_PASSIVE_RATIO_THRESHOLD*100)}% threshold",
                        "match": "",
                        "line": 0,
                    })

            if "synonym_rotation" in structural and len(stripped.split()) >= _SYNONYM_MIN_WORDS:
                stripped_words = set(re.findall(r"\b[a-z]+\b", stripped.lower()))
                if "present" in stripped_words:
                    starts = [m.start() for m in re.finditer(r"\bpresent\b", stripped, re.I)]
                    adj_spans = [m.span() for m in _PRESENT_ADJECTIVE_RE.finditer(stripped)]
                    if starts and all(
                        any(a <= s < b for a, b in adj_spans) for s in starts
                    ):
                        # Every occurrence is the adjective sense ("is present",
                        # "always present", "present in X"). None is the verb
                        # sense this cluster exists to catch, so it does not count.
                        stripped_words.discard("present")
                for cluster in _SYNONYM_CLUSTERS:
                    hits = cluster & stripped_words
                    if len(hits) >= 2:
                        findings.append({
                            "kind": "synonym_rotation",
                            "label": f"synonym rotation: {', '.join(sorted(hits))} (STE 1.11: one name per thing)",
                            "match": ", ".join(sorted(hits)),
                            "line": 0,
                        })

    return findings


# ===== Comment structure (group 2) =====
#
# These four rules need span metadata, not flat text: whether code preceded the
# opener, which line it started on, and how many comment-only lines run
# together. scan() takes a flat string and cannot see any of that, so comment
# structure gets its own entry point rather than a `kinds` member.

MAX_COMMENT_LINE_LENGTH = 100
MAX_CONSECUTIVE_COMMENT_LINES = 2

_URL_RE = re.compile(r"https?://\S+")

COMMENT_STRUCTURE_KINDS = (
    "comment_long_line",
    "comment_block_too_long",
    "comment_inline_url",
    "comment_question",
)


def scan_comment_structure(code: str, filepath: str) -> list:
    """Structural findings over the comment regions of one source file.

    Rules:
      comment_long_line       a comment line over MAX_COMMENT_LINE_LENGTH
      comment_block_too_long  more than MAX_CONSECUTIVE_COMMENT_LINES comment-
                              only lines in a row, which is a block that should
                              collapse to the rule it states
      comment_inline_url      a link in a trailing comment, where it is invisible
                              to anyone reading the doc comment
      comment_question        a comment ending in `?`, which records an
                              unanswered question instead of the domain rule
    """
    family = grammar_for(filepath, code)
    if family is None or family == PROSE_ROUTE:
        return []

    spans = extract_comment_spans(code, family)
    if not spans:
        return []

    findings = []
    comment_only_lines = set()

    for span in spans:
        text = span["text"]

        if not span["inline"]:
            for offset in range(len(text.splitlines()) or 1):
                comment_only_lines.add(span["line"] + offset)

        for offset, raw in enumerate(text.splitlines() or [""]):
            if len(raw) > MAX_COMMENT_LINE_LENGTH:
                findings.append({
                    "kind": "comment_long_line",
                    "label": f"comment line over {MAX_COMMENT_LINE_LENGTH} chars ({len(raw)})",
                    "match": raw.strip()[:60],
                    "line": span["line"] + offset,
                })

        if span["inline"]:
            url = _URL_RE.search(text)
            if url:
                findings.append({
                    "kind": "comment_inline_url",
                    "label": "link in a trailing comment (put it on the doc comment)",
                    "match": url.group(0)[:60],
                    "line": span["line"],
                })

        # Trailing punctuation of a block form is decoration, not content, so
        # strip the closer's own characters before testing the last character.
        stripped = text.strip().rstrip("*/-]}>#").strip()
        if stripped.endswith("?"):
            findings.append({
                "kind": "comment_question",
                "label": "comment ends in a question (state the rule, not the doubt)",
                "match": stripped[-60:],
                "line": span["line"] + max(0, len(text.rstrip().splitlines()) - 1),
            })

    for start, length in _consecutive_runs(sorted(comment_only_lines)):
        if length > MAX_CONSECUTIVE_COMMENT_LINES:
            findings.append({
                "kind": "comment_block_too_long",
                "label": (
                    f"{length} consecutive comment lines "
                    f"(cap {MAX_CONSECUTIVE_COMMENT_LINES}); collapse to the rule it states"
                ),
                "match": f"lines {start}-{start + length - 1}",
                "line": start,
            })

    return findings


def _consecutive_runs(numbers: list) -> list:
    """[(start, length)] for each run of consecutive integers in `numbers`."""
    runs = []
    for value in numbers:
        if runs and value == runs[-1][0] + runs[-1][1]:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    return [(start, length) for start, length in runs]


if __name__ == "__main__":
    # Quick test
    test = "We certainly decided this is comprehensive."
    results = scan(test)
    print(f"Found {len(results)} issues:")
    for r in results:
        print(f"  Line {r['line']}: {r['label']} — {r['match']}")
