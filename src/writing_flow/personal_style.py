#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Personal writing style checks.

Enforces the user's direct, declarative content style, layered on top of the
anti-AI writing rules in style_check.py. These patterns are not generic AI-isms.
They are specific to the user's preference for:

  - No academic setup sentences
  - No expository padding between ideas
  - Imperative for instructions, not indirect suggestions
  - No qualification hedges when the fact can be stated plainly
  - No verbose constructions where a shorter one exists
  - Response length scaled to the turn's phase and prompt, not padded regardless

Source: chat history analysis + writing_style.docx, 2026-04-11.

Escape hatch: files with 'personal-style', 'writing-style', 'avoid-ai-writing',
or 'anti-ai' in the path are skipped (they document patterns as examples).
"""
import re

ACADEMIC_SETUP_PHRASES = [
    "in order to understand",
    "in order to work with",
    "in order to use",
    "in order to",
    "before we can",
    "before diving into",
    "before we dive",
    "to appreciate this",
    "to fully understand",
    "to better understand",
    "to understand this",
    "to understand how",
    "to understand why",
    "it is important to understand",
    "it is worth understanding",
    "let us first consider",
    "let us consider",
    "let us look at",
    "we first need to",
    "we need to first",
    "we need to understand",
]

EXPOSITORY_TRANSITIONS = [
    "as we can see,",
    "as we have seen,",
    "as mentioned above,",
    "as discussed above,",
    "as mentioned earlier,",
    "as discussed earlier,",
    "it follows that",
    "we have established that",
    "we have seen that",
    "as noted above,",
    "as we noted,",
    "recall that",
]

INDIRECT_INSTRUCTIONS = [
    "you should consider",
    "you might want to consider",
    "you may want to",
    "it is recommended that",
    "it is recommended to",
    "it is suggested that",
    "it is advised that",
    "it may be useful to",
    "it might be worth",
    "it may be worth",
    "it would be good to",
    "one should",
    "one can",
    "one might",
    "one must",
]

OVER_HEDGES = [
    "generally speaking,",
    "in most cases,",
    "in many cases,",
    "it is generally",
    "tends to be the case",
    "it should be noted that",
    "needless to say,",
    "it goes without saying",
    "arguably,",
    "presumably,",
    "supposedly,",
    "under most circumstances",
]

# Verbose constructions with shorter alternatives
VERBOSE_CONSTRUCTIONS = [
    "make use of",
    "in the case of",
    "in the context of",
    "with respect to",
    "with regard to",
    "in terms of",
    "the fact that",
    "a number of",
    "a variety of",
    "a wide range of",
    "in light of",
    "by means of",
    "for the purpose of",
    "in spite of the fact",
]


def check_personal_style(content: str) -> list[tuple[str, str]]:
    """Scan prose content for personal style violations.

    Returns list of (severity, message) tuples.
    """
    findings = []
    content_lower = content.lower()

    hits = [p for p in ACADEMIC_SETUP_PHRASES if p in content_lower]
    if hits:
        findings.append((
            "HARD",
            f"Academic setup sentences: {', '.join(repr(h) for h in hits[:3])}. "
            "Start with the fact or action directly. Cut the setup clause."
        ))

    hits = [p for p in EXPOSITORY_TRANSITIONS if p in content_lower]
    if hits:
        findings.append((
            "HARD",
            f"Expository padding: {', '.join(repr(h) for h in hits[:3])}. "
            "Cut it. The content stands without a pointer back to itself."
        ))

    hits = [p for p in INDIRECT_INSTRUCTIONS if p in content_lower]
    if hits:
        findings.append((
            "HARD",
            f"Indirect instruction: {', '.join(repr(h) for h in hits[:3])}. "
            "Use the imperative: 'Do X' not 'You should consider doing X'."
        ))

    hits = [p for p in OVER_HEDGES if p in content_lower]
    if hits:
        findings.append((
            "SOFT",
            f"Over-hedging: {', '.join(repr(h) for h in hits[:3])}. "
            "State the fact. If it has exceptions, name them specifically."
        ))

    hits = [p for p in VERBOSE_CONSTRUCTIONS if p in content_lower]
    if hits:
        findings.append((
            "SOFT",
            f"Verbose construction: {', '.join(repr(h) for h in hits[:3])}. "
            "Replace: 'make use of'→'use', 'in the case of'→'when', "
            "'in terms of'→state the thing directly, 'a number of'→give the number."
        ))

    return findings


# ===== Verbosity budget =====
# Phases come from phase_classifier.py's PHASE_ORDER. writing/research/wrap_up/meta
# are exempt: those phases' own PHASE_DIRECTIVES already ask for varied sentence
# length and full prose (docs, retrospectives, research synthesis) — a word cap
# there would fight a directive that's already correct for the content.
_EXEMPT_PHASES = {"writing", "research", "wrap_up", "meta"}

# A turn that only gathered is research, whatever the classifier named the
# phase from the prompt's own wording. A 16-word question can open a
# cross-repo investigation, and the prompt alone cannot show that.
_READ_ONLY_TOOLS = {
    "Read", "Grep", "Glob", "WebFetch", "WebSearch", "NotebookRead",
    "ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool",
}
_MUTATING_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# multiplier, floor: budget = max(multiplier * prompt_word_count, floor)
_BUDGET_TABLE = {
    "conversational": (3, 40),
    "coding": (6, 120),
}

# A stated number the reader chose on purpose outranks any inferred budget.
# "explain this in under 100 words" carries real intent regardless of phase,
# so this check runs even in an _EXEMPT_PHASES turn. The keyword window
# guards against a plain mention like "he wrote 200 words that day" or
# "list the 5 most common words", neither of which asks for a length cap.
_EXPLICIT_WORD_LIMIT_RE = re.compile(
    r"\b(?:exactly|under|within|no\s+more\s+than|at\s+most|max(?:imum)?\s+of)?\s*"
    r"(\d{1,5})\s*[- ]?words?\b"
    r"(?:\s+or\s+(?:less|fewer))?"
    r"(?:\s+max(?:imum)?)?",
    re.IGNORECASE,
)
_WORD_LIMIT_KEYWORDS = re.compile(
    r"\b(exactly|under|within|no\s+more\s+than|at\s+most|max(?:imum)?|"
    r"or\s+less|or\s+fewer|limit|cap)\b",
    re.IGNORECASE,
)

# Closed set of words that form short continuations when the user is asking
# the model to proceed with a multi-step task and report progress.
_SHORT_CONTINUATION_WORDS = {
    "continue", "go", "ahead", "yes", "yeah", "yep", "ok", "okay",
    "sure", "proceed", "next", "please", "do", "it", "keep", "going",
    "carry", "on",
}


def is_short_continuation(prompt_text: str) -> bool:
    """True if the prompt is a brief acknowledgement or continuation.

    When the user responds to a multi-step task with 'yes', 'continue',
    'go', etc., the budget must be sized from the original task prompt,
    not the continuation. A continuation's brevity is the user asking to
    proceed and report, not the user asking for fewer words.

    Only prompts with at most four words that consist entirely of words
    from the closed set count as continuations.
    """
    if not prompt_text or not prompt_text.strip():
        return False
    words = prompt_text.split()
    if len(words) > 4:
        return False
    normalized_words = {w.lower().rstrip(".,!?;:") for w in words}
    return normalized_words <= _SHORT_CONTINUATION_WORDS


def explicit_word_limit(prompt_text: str) -> int | None:
    """The word cap the user stated, or None if they never stated one.

    Returns the first stated number found with a constraint keyword nearby.
    Ambiguity between two stated numbers in one prompt is not resolved here,
    since real prompts almost never carry more than one.

    Ignores the audit's own phrasing patterns (like "22-word sentence, cap 20"
    or "against a stated limit of 21") which are not user-stated limits.
    """
    if not prompt_text:
        return None

    # Patterns that mark the audit's own phrasing, not user-stated limits
    audit_markers = (
        "word sentence, cap",  # "22-word sentence, cap 20"
        "against a stated limit",  # "against a stated limit of 21"
    )

    for m in _EXPLICIT_WORD_LIMIT_RE.finditer(prompt_text):
        window = prompt_text[max(0, m.start() - 25):m.end() + 15]
        if _WORD_LIMIT_KEYWORDS.search(window):
            # Check if this is audit phrasing in disguise
            if any(marker in window for marker in audit_markers):
                continue
            if _caps_a_unit(prompt_text[max(0, m.start() - 40):m.start()],
                            prompt_text[m.end():m.end() + 25]):
                continue
            return int(m.group(1))
    return None


# A cap on one sentence, paragraph or line is not a cap on the reply. On
# 2026-09-23 "sentences of 20 words or fewer" set a 20-word reply cap, and a
# 191-word answer drew a HARD block.
_UNIT = r"(?:sentences?|paragraphs?|lines?|bullets?|headings?|titles?|items?|clauses?)"
# The unit, then up to three words, then the cap: "sentences stay under 20".
_UNIT_BEFORE = re.compile(rf"\b{_UNIT}\b(?:\s+[\w-]+){{0,3}}\s*$", re.IGNORECASE)
# "in under 100 words" scopes the cap to the whole answer, whatever came before.
_REPLY_SCOPE = re.compile(r"\bin\s*$", re.IGNORECASE)
# "20 words per sentence", "20 words each line".
_UNIT_AFTER = re.compile(rf"^\s*(?:per|each|a|an|every|for\s+each|in\s+each)\s+{_UNIT}\b",
                         re.IGNORECASE)


def _caps_a_unit(before: str, after: str) -> bool:
    """True when the stated cap applies to a unit smaller than the reply."""
    if _UNIT_AFTER.search(after):
        return True
    return bool(_UNIT_BEFORE.search(before)) and not _REPLY_SCOPE.search(before)


def _strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


_INLINE_CODE = re.compile(r"`[^`\n]*`")
_BLOCKQUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.MULTILINE)
_BARE_URL = re.compile(r"https?://\S+")
# Two or more segments after a leading slash. "and/or" has no leading slash,
# so ordinary prose never matches.
_BARE_PATH = re.compile(r"(?<![\w.])/(?:[\w.\-]+/)+[\w.\-]+")


def _strip_evidence(text: str) -> str:
    """Text with cited and quoted material removed, ready for a word count.

    A fenced block already comes out through _strip_code_blocks. An inline
    span, a blockquote line, a URL and an absolute path carry the same class
    of content in a shorter form. The kit injects a grounding directive on
    every turn that demands a source beside each claim. Counting that source
    against a length budget charges the answer for obeying it, and the first
    thing a rewrite drops is the evidence. Fixes issue #23.
    """
    out = _strip_code_blocks(text)
    out = _BLOCKQUOTE_LINE.sub(" ", out)
    out = _INLINE_CODE.sub(" ", out)
    out = _BARE_URL.sub(" ", out)
    return _BARE_PATH.sub(" ", out)


def is_research_turn(tools_used) -> bool:
    """True when the turn read things and changed nothing.

    The phase classifier reads the prompt, so it cannot see that a short
    question opened a long investigation. The tool record can. A turn that
    called a read-only tool and never called a mutating one is research by
    shape, and _EXEMPT_PHASES already exempts research by name.

    Bash is neither: it reads as often as it writes, and treating it as
    either would decide most turns on its own. A Bash-only turn stays under
    the budget.
    """
    if not tools_used:
        return False
    names = set(tools_used)
    if names & _MUTATING_TOOLS:
        return False
    return bool(names & _READ_ONLY_TOOLS)


def check_verbosity_budget(text: str, phase: str, prompt_word_count: int,
                          prompt_text: str = "",
                          tools_used=None) -> list[tuple[str, str]]:
    """Score response length against a word budget.

    A stated limit in the prompt overrides everything else, including phase
    exemption: the user asked directly, so the inferred budget below does
    not get a vote. Without a stated limit, the budget scales off the phase
    and how much the user actually asked. Code blocks never count toward
    either budget (mirrors caveman's own 'code/commits/security: write
    normal' carve-out).
    """
    prose = _strip_code_blocks(text)
    word_count = len(prose.split())

    stated = explicit_word_limit(prompt_text)
    if stated is not None:
        # A model cannot land on an exact count, so a little slack avoids
        # blocking a reply that is close enough to what was asked. Past
        # that slack, severity still scales with how far it drifted.
        ratio = word_count / stated
        if ratio <= 1.2:
            return []
        severity = "HARD" if ratio > 1.75 else "SOFT"
        return [(
            severity,
            f"Verbosity: {word_count} words against a stated limit of {stated}. "
            "The prompt asked for a hard cap. Cut to fit it."
        )]

    if is_research_turn(tools_used):
        return []

    if phase in _EXEMPT_PHASES or phase not in _BUDGET_TABLE:
        return []

    multiplier, floor = _BUDGET_TABLE[phase]
    budget = max(multiplier * prompt_word_count, floor)

    # The inferred budget judges how much prose the turn produced, so cited
    # evidence drops out of the count here. A stated limit above keeps the
    # whole answer in scope, because the user capped the answer, not its prose.
    word_count = len(_strip_evidence(text).split())
    ratio = word_count / budget
    if ratio <= 1.5:
        return []

    severity = "HARD" if ratio > 2.5 else "SOFT"
    return [(
        severity,
        f"Verbosity: {word_count} words in a '{phase}' turn, budget {budget} "
        f"({multiplier}x prompt length or {floor} floor). Cut padding, not substance."
    )]


def is_personal_style_doc(filepath: str) -> bool:
    """Escape hatch for files that document these patterns as examples."""
    path_lower = filepath.lower()
    skip = ["personal-style", "writing-style", "avoid-ai-writing", "anti-ai"]
    return any(p in path_lower for p in skip)
