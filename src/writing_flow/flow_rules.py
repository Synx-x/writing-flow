#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Reader-expectation flow rules. Companion to prose_rules.py.

prose_rules checks vocabulary and ASD-STE100 form. This module checks where
information sits. Every rule follows the topic and comment split that George
Gopen's Reader Expectation Approach describes and that Writer Science teaches.
The topic runs from the first word through the grammatical subject. The
comment is the verb and what follows. Readers expect old, linking material
in the topic and new material in the comment.

Kinds, with the source that set each rule:

  long_runway        more than LONG_RUNWAY_CAP words before the first verb,
                     after any leading orienting phrase (Emphasis step 1,
                     Write in Fractals sentence level)
  topic_drift        a paragraph of 4+ sentences whose topics share no anchor
                     and do not even link sentence to sentence (video 3:07,
                     Coherence tool diagnostic)
  unanchored_chain   a paragraph of 5+ sentences where each topic picks up the
                     previous comment but nothing recurs and the last sentence
                     does not return to the subject. The Portland failure
                     (video 10:40). Advisory: a legitimate linking pattern can
                     look like this, so this kind is separate from topic_drift.
  new_in_topic       three or more consecutive sentences whose topics share no
                     stem with the sentence before them or with the paragraph
                     index (Flow step 1 and 2). Silent when the paragraph
                     already drifted.
  missing_index      a paragraph of 3+ sentences that opens with a subordinate
                     or participial clause of 10+ words and carries no ordinal
                     signposts (video 17:17, Fractals paragraph rule)
  preview_term_dropped  the index sentence lists 2 to 6 terms, later topics
                     pick up all but one, and that one never returns
                     (video 20:32)
  index_count_mismatch  the index sentence states a count of parts ("three
                     techniques") and the paragraph enumerates a different
                     number (derived-parts completeness, not in the source
                     video directly, extends the missing_index rule at
                     17:17)
  vague_heading      a markdown heading with no concept in it (Big Picture
                     signal 1 names Background and Discussion)
  doc_intro_too_long  a document of 2+ headings and 400+ words whose intro
                     is not much shorter than the body (Index-Discussion at
                     document scale, the output style's own unit table)
  intro_missing_turn  a document of 3+ headings and 400+ words whose intro
                     opens on an unqualified claim and never turns on a
                     contrastive word before the first heading (the
                     status-quo-then-problem introduction shape). In
                     OPT_IN_KINDS, not ALL_KINDS: measured at a 59% false
                     positive rate against this kit's own reference docs,
                     which mostly have no narrative arc to turn on. Pass it
                     explicitly for content built to argue a case.

Pure standard library. No network. Findings share the prose_rules shape:
{"kind", "label", "match", "line"}. Sentence and paragraph rules report line
0, the way prose_rules does for whole-document checks.
"""
import re
from collections import Counter

ALL_KINDS = (
    "long_runway", "topic_drift", "unanchored_chain", "new_in_topic",
    "missing_index", "preview_term_dropped", "vague_heading",
    "index_count_mismatch", "doc_intro_too_long",
)

# Opt-in only (59% false-positive rate against real docs). Pass via flow_kinds
# for content meant to argue a case.
OPT_IN_KINDS = ("intro_missing_turn",)

LONG_RUNWAY_CAP = 10         # Emphasis step 1 says 5 to 8. Ten leaves room for one appositive.
DRIFT_MIN_SENTENCES = 4
CHAIN_MIN_SENTENCES = 5
INDEX_ECHO_SHARE = 0.6       # 60% of later topics echoing the index sentence anchors the paragraph
CHAIN_SHARE = 0.6            # 60% of sentences linking to the previous one is a chain
MISSING_INDEX_CLAUSE_WORDS = 10  # leaves opener is 15, Pinker's is 7, a site paragraph hit 8
NEW_IN_TOPIC_RUN = 3             # two fresh topics in a row is common contrast, three is a pattern
TOPIC_WORD_CAP = 8
LABEL_WORD_CAP = 6               # "Where the thinking happens:" is four words, "Also worth weighing:" three
IMPERATIVE_SHARE = 0.5           # half the sentences imperative and the paragraph is instructions

AUXILIARIES = frozenset("""
is are was were am be been being has have had do does did
can cannot could will would shall should may might must
""".split())

IRREGULAR_PASTS = frozenset("""
arose ate became began bent bit blew bought broke brought built burnt caught
came chose clung crept dealt drew drank drove dug fell fed felt fought found
flew forgot froze gave got grew hung heard held hid hit hurt kept knew laid
lay led left lent let lit lost made meant met paid put quit ran rang rode
rose said sang sank sat saw sent set shook shone shot showed shut slept slid
slipped sold sought spent spoke spread sprang stood stole struck stuck swam
swept swung taught thought threw told took tore understood went woke won
wore wove wrote
""".split())

# Frequent main verbs, base and third person forms. The -ed and -s heuristics
# cover the rest, and a listed word counts as a verb only after the subject slot.
COMMON_VERBS = frozenset("""
accept accepts add adds allow allows appear appears apply applies argue argues
arise arises ask asks assume assumes attach attaches avoid avoids become becomes
begin begins believe believes belong belongs break breaks bring brings build
builds buy buys call calls carry carries cause causes change changes check
checks choose chooses claim claims close closes come comes communicate
communicates compare compares connect connects consider considers contain
contains continue continues control controls cost costs cover covers create
creates cut cuts decide decides define defines deliver delivers demand demands
demonstrate demonstrates depend depends describe describes determine determines
develop develops die dies differ differs discover discovers distribute
distributes draw draws drive drives drop drops eat eats emerge emerges enable
enables encode encodes end ends enter enters examine examines execute executes
exist exists expect expects explain explains export exports face faces fail
fails fall falls feel feels fetch fetches fill fills filter filters find
access accesses cache caches catch catches compile compiles configure
configures count counts delete deletes deploy deploys emit emits import
imports install installs invoke invokes list lists load loads log logs map
maps match matches merge merges parse parses print prints query queries
render renders retry retries scan scans search searches skip skips sort
sorts split splits store stores track tracks validate validates verify
verifies refuse refuses record records block blocks reject rejects fire
fires write writes read reads check checks run runs pass passes inject
injects append appends strip strips spawn spawns dispatch dispatches route
routes register registers override overrides shadow shadows save saves
update updates detect detects trigger triggers flag flags warn warns nudge
nudges surface surfaces capture captures ship ships expose exposes wrap
wraps gate gates guard guards audit audits measure measures tune tunes
call calls exit exits return returns print prints raise raises catch catches
package packages borrow borrows publish publishes collect collects notice
notices answer answers hang hangs land lands miss misses jump jumps drift
drifts anchor anchors echo echoes recur recurs pick picks lean leans

finds fit fits focus focuses follow follows force forces form forms gather
gathers get gets give gives go goes grow grows handle handles happen happens
hear hears help helps hide hides hold holds identify identifies illuminate
illuminates imagine imagines include includes increase increases indicate
indicates introduce introduces involve involves join joins keep keeps know
knows lack lacks lead leads learn learns leave leaves let lets lie lies like
likes limit limits link links live lives look looks lose loses love loves make
makes manage manages matter matters mean means measure measures meet meets
mount mounts move moves name names need needs note notes obscure obscures
occupy occupies occur occurs offer offers open opens organize organizes own
owns pass passes pay pays perform performs pick picks place places plan plans
play plays point points prefer prefers prepare prepares present presents
prevent prevents process processes produce produces propose proposes protect
protects prove proves provide provides pull pulls push pushes put puts raise
raises reach reaches read reads receive receives recognize recognizes reduce
reduces refer refers reflect reflects remain remains remember remembers remind
reminds remove removes repeat repeats replace replaces report reports represent
represents require requires resolve resolves respect respects respond responds
result results return returns reveal reveals rise rises roam roams run runs
save saves say says see sees seem seems sell sells send sends serve serves set
sets shape shapes share shares show shows sit sits solve solves speak speaks
spend spends stand stands start starts state states stay stays stop stops
strengthen strengthens study studies succeed succeeds suggest suggests supply
supplies support supports suppose supposes take takes talk talks teach teaches
tell tells tend tends test tests think thinks throw throws touch touches trace
traces train trains transfer transfers treat treats try tries turn turns
understand understands use uses vary varies wait waits walk walks want wants
watch watches wear wears win wins wonder wonders work works write writes
""".split())

# Words that open an orienting phrase or subordinate clause. A leading phrase
# from one of these to a comma is setup, not the subject, and adds no runway.
CLAUSE_OPENERS = frozenset("""
after although as because before by during for from if in on once since
though through to under unless until upon when whenever where whereas
while with within without according despite given like rather
first second third fourth fifth finally however instead meanwhile moreover
next then therefore thus also still yet
""".split())

# "It's", "they're", "we've": the verb rides on the subject word.
_CONTRACTED_VERB = re.compile(r"[A-Za-z]+'(?:re|m|ve|ll|d)$|^(?:it|that|this|there|here|what|who|he|she|one)'s$", re.I)

# A COMMON_VERBS word right after one of these is a noun: "the first limit",
# "its main call". DETERMINERS already covers the plain articles.
NOUN_SIGNALS = frozenset("""
first second third fourth fifth last next same other only own whole main
final single every each any this that these those its their his her our
your my no
""".split())

ORDINAL_SIGNPOSTS = re.compile(
    r"^(?:first|second|third|fourth|fifth|finally|lastly|next)\b[,:]?", re.I
)

# Broader than ORDINAL_SIGNPOSTS: allows "The first...", not a bare sentence-initial ordinal.
# Confirms a paragraph enumerates parts before index_count_mismatch trusts its sentence count.
_ORDINAL_ANYWHERE = re.compile(
    r"\b(?:the |a |an )?(?:first|second|third|fourth|fifth|sixth)\b", re.I
)

LINK_PRONOUNS = frozenset("""
it its they their them this that these those he his she her such
neither both none either
""".split())

# "that limit is" keeps a noun after the demonstrative, "That removes the"
# does not. The word after the candidate verb decides.
DEMONSTRATIVES = frozenset("this that these those".split())
FIRST_PERSON = frozenset("i we you our us my your me".split())
DETERMINERS = frozenset("the a an of and or to in on at by for with from as".split())

# A subject's head noun ends before one of these. "Support for Truman's
# foreign policy" has the head "support", not "policy".
HEAD_CUTS = frozenset("""
of for in on to that which who whom with from by at than other as into over
under within about
""".split())

STOP_WORDS = frozenset("""
a an the and or but nor so yet is are was were am be been being have has had
do does did can could will would shall should may might must to of in on at
by for with from as about into through during before after above below
between among over under out off up down again further then once here there
when where why how all any both each few more most other some such no not
only own same than too very just now also into onto upon via per while
which who whom whose what that this these those it its they their them
he his she her him i we you our us my your me one ones thing things way
""".split())

VAGUE_HEADINGS = frozenset("""
background discussion overview introduction notes misc miscellaneous
details other summary
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HEADING_LINE = re.compile(r"^\s*#{1,6}\s+")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE_LINE = re.compile(r"^\s*```")
# A coordinate list of 2 to 6 terms: "A and B" through "A, B, C, D, and E".
# Was fixed at exactly three terms. A preview naming two or four strands passed through unseen.
_COORD_LIST = re.compile(
    r"\b([A-Za-z][A-Za-z\-]+(?:\s*,\s*[A-Za-z][A-Za-z\-]+){0,4}\s*,?\s+(?:and|or)\s+"
    r"[A-Za-z][A-Za-z\-]+)\b"
)
# Order matters: try the Oxford-comma-plus-conjunction join first, so ", and"
# splits as one token instead of leaving a stray "and notifications" term.
_COORD_SPLIT = re.compile(r"\s*,\s*(?:and|or)\s+|\s+(?:and|or)\s+|\s*,\s*")


def _coord_terms(span: str) -> list:
    """Split a matched coordinate-list span into its individual terms."""
    return [t for t in _COORD_SPLIT.split(span) if t]


# A count word before a plural noun that names how many parts: "three techniques", "4 steps".
_COUNT_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "a couple of": 2, "a few": 3,
}
_INDEX_COUNT = re.compile(
    r"\b(two|three|four|five|six|a couple of|a few)\s+([a-z][a-z\-]*s)\b", re.I
)


def _strip_leading_yaml_frontmatter(text: str) -> str:
    """Replace leading YAML frontmatter with empty lines, preserving line numbers.

    Frontmatter is a block at the start of the file bounded by exactly three
    dashes on their own lines. Returns the text unchanged if no frontmatter is
    found or if the file starts with a non-frontmatter horizontal rule.
    """
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return text

    for i in range(1, len(lines)):
        if lines[i] == "---":
            lines = [""] * (i + 1) + lines[i + 1:]
            return "\n".join(lines)

    return text


def prose_only(text: str) -> str:
    """Strip fences, frontmatter, headings, tables, list markers, links.

    Inline code keeps its text and loses the backticks. An identifier in the
    topic slot is the sentence's subject, so removing it would leave a hole
    and a false runway or drift. prose_rules removes it because vocabulary
    rules must not judge identifiers. Flow rules must see them.
    """
    result = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    result = re.sub(r"`([^`\n]*)`", r"\1", result)
    result = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", result)
    result = re.sub(r"\[([^\]\n]+)\]\([^)]*\)", r"\1", result)
    result = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", result)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", result)
    result = re.sub(r"(?<![A-Za-z0-9])_([^_\n]+)_(?![A-Za-z0-9])", r"\1", result)
    if result.startswith("---\n"):
        result = re.sub(r"^---\n.*?\n---\n", "", result, count=1, flags=re.DOTALL)
    result = re.sub(r"^#{1,6}\s+.*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "\n\n", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*\|.*\|\s*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", result, flags=re.MULTILINE)
    result = re.sub(r"https?://\S+", "", result)
    return result


_ABBREVIATIONS = re.compile(
    r"\b(e\.g|i\.e|etc|vs|cf|Dr|Mr|Mrs|Ms|No|Fig|Eq|approx|min|max|sec|ver|rev)\.(?=\s)",
    re.I,
)
_SENTENCE_BREAK = re.compile(r"(?<!\s[A-Z]\.)(?<=[.!?])\s+(?=[A-Z(\"'])")
_STARTS_LIKE_PROSE = re.compile(r"^[\"'(\[]?[A-Za-z0-9]")


def is_prose_sentence(sentence: str) -> bool:
    """At least three words, opening on a letter or digit, with one real word."""
    if not _STARTS_LIKE_PROSE.match(sentence):
        return False
    words = sentence.split()
    return len(words) >= 3 and any(len(_clean(w)) >= 3 for w in words)


def split_sentences(text: str) -> list:
    """Per line, then on . ! ? followed by a capital or paren. Mirrors prose_rules.

    Two guards on top of prose_rules: an abbreviation such as e.g. or an
    initial such as George D. Gopen does not end a sentence, and a fragment
    that does not read as a sentence is dropped.
    """
    sentences = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line or not re.search(r"[A-Za-z]", line):
            continue
        line = _ABBREVIATIONS.sub(lambda m: m.group(1), line)
        line = _QUOTED.sub(_shield_quote, line)
        parts = _SENTENCE_BREAK.split(line)
        sentences.extend(
            _unshield(p.strip()) for p in parts if p.strip() and is_prose_sentence(p.strip())
        )
    return sentences


# A period inside a quoted error string is not a sentence end. Shield it for
# the split, then put it back.
_QUOTED = re.compile(r'"[^"\n]{1,200}"')
_SHIELDS = {".": "￰", "!": "￱", "?": "￲"}


def _shield_quote(m: "re.Match") -> str:
    return "".join(_SHIELDS.get(ch, ch) for ch in m.group(0))


def _unshield(text: str) -> str:
    for ch, shield in _SHIELDS.items():
        text = text.replace(shield, ch)
    return text


def paragraph_sentences(para: str) -> list:
    """Sentences of one prose paragraph. Hard-wrapped lines are joined first.

    prose_rules splits per line because a repo may put one paragraph on one
    line. The kit's own docs wrap at 80 columns, and there a per-line split
    turns every wrapped line into a false sentence. A paragraph that reached
    this function is prose with no list, table or heading in it, so joining
    its lines is safe.
    """
    flat = re.sub(r"\s*\n\s*", " ", prose_only(para)).strip()
    return split_sentences(flat)


def prose_paragraphs(text: str) -> list:
    """Blank-line paragraphs that are prose, not lists, tables, headings or code."""
    paragraphs = []
    in_fence = False
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        toggles = sum(1 for ln in lines if _FENCE_LINE.match(ln))
        if in_fence or toggles:
            if toggles % 2 == 1:
                in_fence = not in_fence
            continue
        structural = sum(
            1 for ln in lines
            if _LIST_LINE.match(ln) or _HEADING_LINE.match(ln) or _TABLE_LINE.match(ln)
        )
        if structural:
            continue
        paragraphs.append(block)
    return paragraphs


def _clean(word: str) -> str:
    word = word.strip("\"'([{)]}.,;:!?").lower()
    if word.endswith("'s"):
        word = word[:-2]
    return word


def stem(word: str) -> str:
    """Crude suffix stripping so plurals and inflections match."""
    w = word
    if len(w) > 5 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 5 and w.endswith("es") and w[-3] in "sxz":
        w = w[:-2]
    elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 6 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 5 and w.endswith("ed"):
        w = w[:-2]
    return w


def same_stem(a: str, b: str) -> bool:
    """Equal stems, or a shared prefix of six letters when both words are long."""
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]:
        return True
    return False


def content_stems(words: list) -> set:
    out = set()
    for raw in words:
        w = _clean(raw)
        if not w:
            continue
        if w in FIRST_PERSON:
            out.add("1P")
            continue
        if len(w) < 3 or w in STOP_WORDS:
            continue
        out.add(stem(w))
    return out


def shares(a: set, b: set) -> bool:
    for x in a:
        for y in b:
            if same_stem(x, y):
                return True
    return False


# What follows a third-person verb but rarely follows a plural noun. No
# prepositions here: "patterns over the past five decades" is a noun phrase.
VERB_FOLLOWERS = frozenset("""
a an the its their his her our your my this that these those each every all
any no not only to whether how what which it them him us me you
""".split())

# What follows an imperative or a subjectless opener: "Run the", "Look at",
# "Found a". No "to" or "for", since "Access to the file" opens a noun phrase.
IMPERATIVE_FOLLOWERS = (VERB_FOLLOWERS - {"to"}) | frozenset(
    "at up out through into on in again now first".split()
)


def is_imperative_opener(word: str, nxt: str) -> bool:
    """A verb in the first slot with no subject before it.

    Chat is full of these: an instruction ("Run the tests"), a status line
    ("Found a bug", "Verified on the branch"), or a hedge ("Let me check").
    The topic slot is empty by design, so the sentence has no runway and no
    topic to anchor a paragraph with.
    """
    w = _clean(word)
    nx = _clean(nxt)
    if not w or w in AUXILIARIES or nx in AUXILIARIES:
        return False
    past = w in IRREGULAR_PASTS or (w.endswith("ed") and len(w) >= 4 and not w.endswith("eed"))
    base = w in COMMON_VERBS and not w.endswith("s")
    return (past or base) and nx in IMPERATIVE_FOLLOWERS


def _is_verb(word: str, prev: str, nxt: str = "") -> bool:
    w = _clean(word)
    if not w:
        return False
    if w in AUXILIARIES or w in IRREGULAR_PASTS:
        return True
    if w in COMMON_VERBS:
        # "The first limit is": a listed verb after a determiner-like word, or
        # right before an auxiliary, is the noun sense.
        if nxt in AUXILIARIES or prev in DETERMINERS:
            return False
        if prev in NOUN_SIGNALS and not (prev in DEMONSTRATIVES and nxt in VERB_FOLLOWERS):
            return False
        return True
    # Four letters admits "used" and "owed". The -eed nouns stay out.
    if w.endswith("ed") and len(w) >= 4 and not w.endswith("eed") and prev not in DETERMINERS:
        return True
    # Third person -s: "refuses to", "records the". A plural noun rarely
    # sits right before a determiner or preposition, so the next word decides.
    if (
        len(w) >= 4
        and w.endswith("s")
        and not w.endswith(("ss", "us", "is", "ous"))
        and prev not in DETERMINERS
        and (nxt in VERB_FOLLOWERS or nxt.endswith("ly") or nxt == "")
    ):
        return True
    return False


LEADING_CONJUNCTIONS = frozenset("but and yet so or nor".split())


def leading_phrases(words: list) -> int:
    """Index where the subject starts, after any comma-closed orienting phrases."""
    start = 0
    n = len(words)
    if n and _clean(words[0]) in LEADING_CONJUNCTIONS and not words[0].endswith(","):
        start = 1
    # A short label closed by a colon is a signpost, not a clause: "Day to
    # day:", "Where it lives:", "Also worth weighing:". An imperative stays.
    for i in range(start, min(n, start + LABEL_WORD_CAP)):
        w = words[i]
        if w.endswith(":") and not w.endswith("::") and len(w) > 1:
            nxt = words[start + 1] if start + 1 < n else ""
            if not is_imperative_opener(words[start], nxt) and i + 1 < n:
                start = i + 1
            break
    while start < n:
        first = _clean(words[start])
        opener = first in CLAUSE_OPENERS or first.endswith("ing")
        if not opener:
            break
        end = None
        for i in range(start, min(n, start + 24)):
            if words[i].endswith(","):
                end = i + 1
                break
        if end is None or end >= n:
            break
        # "Reporting from April puts agents at 17 million PRs, up 4x" is a
        # gerund subject with its verb, not a participial phrase. It stays.
        if first not in CLAUSE_OPENERS and any(
            _is_verb(words[i], _clean(words[i - 1]), _clean(words[i + 1]) if i + 1 < n else "")
            for i in range(start + 1, end - 1)
        ):
            break
        start = end
    return start


def analyze_sentence(sentence: str) -> dict:
    """Topic words, orienting phrase words, runway length and verb position."""
    words = sentence.split()
    subject_start = leading_phrases(words)
    verb_at = None
    contracted = False
    imperative = subject_start < len(words) and is_imperative_opener(
        words[subject_start], words[subject_start + 1] if subject_start + 1 < len(words) else ""
    )
    if imperative:
        verb_at = subject_start
    for i in range(subject_start, min(len(words), subject_start + 30)):
        if imperative:
            break
        prev = _clean(words[i - 1]) if i > 0 else ""
        if _CONTRACTED_VERB.match(words[i].strip("\"'([{)]}.,;:!?")):
            verb_at = i
            contracted = True
            break
        if i == subject_start and _clean(words[i]) not in AUXILIARIES:
            continue  # the first word of a clause is the subject, not the verb
        nxt = _clean(words[i + 1]) if i + 1 < len(words) else ""
        if _is_verb(words[i], prev, nxt):
            verb_at = i
            break
    if verb_at is None:
        topic_words = words[: subject_start + TOPIC_WORD_CAP]
        runway = None
    elif contracted:
        topic_words = words[: verb_at + 1]
        runway = verb_at - subject_start + 1
    else:
        topic_words = words[:verb_at]
        runway = verb_at - subject_start
    subject_end = subject_start + TOPIC_WORD_CAP if verb_at is None else verb_at + (1 if contracted else 0)
    subject_words = words[subject_start:subject_end]
    first_subject = _clean(subject_words[0]) if subject_words else ""
    is_link = first_subject in LINK_PRONOUNS
    # First person anchors a paragraph only as the subject itself. An "I"
    # inside a relative clause ("That's why I avoided it") is not the topic.
    stems = {s for s in content_stems(topic_words) if s != "1P"}
    if first_subject in FIRST_PERSON:
        stems.add("1P")
    first_clause_len = 0
    if subject_start:
        for i, w in enumerate(words[:subject_start]):
            if w.endswith(","):
                first_clause_len = i + 1
                break
        else:
            first_clause_len = subject_start
    head = None
    chunk = []
    for w in subject_words:
        c = _clean(w)
        if c in HEAD_CUTS or w.endswith(","):
            if c not in HEAD_CUTS:
                chunk.append(c)
            break
        chunk.append(c)
    for c in reversed(chunk):
        if c and c not in STOP_WORDS and c not in FIRST_PERSON and len(c) >= 3:
            head = stem(c)
            break
    comment_words = words[verb_at + 1:] if verb_at is not None else []
    return {
        "head": head,
        "comment_stems": content_stems(comment_words),
        "words": words,
        "topic_words": topic_words,
        "subject_words": subject_words,
        "orient_words": words[:subject_start],
        "orient_len": subject_start,
        "first_clause_len": first_clause_len,
        "runway": runway,
        "is_link": is_link,
        "imperative": imperative,
        "stems": stems,
        "all_stems": content_stems(words),
    }


def topics(text: str) -> list:
    """The topic string of each sentence, for debugging."""
    out = []
    for para in prose_paragraphs(text):
        for s in paragraph_sentences(para):
            out.append(" ".join(analyze_sentence(s)["topic_words"]))
    if not out:
        for s in split_sentences(prose_only(text)):
            out.append(" ".join(analyze_sentence(s)["topic_words"]))
    return out


def _short(words: list, n: int = 5) -> str:
    return " ".join(words[:n]) + ("..." if len(words) > n else "")


def _effective_stems(infos: list) -> list:
    """Topic stems with pronoun topics inheriting the nearest earlier topic.

    "The skill is stale. ... I did the work by hand. Its premise was outdated."
    The "Its" points at the skill, not at the first-person aside between, so a
    link skips back over sentences whose only topic stem is the speaker.
    """
    out = []
    for i, info in enumerate(infos):
        stems = set(info["stems"])
        if info["is_link"]:
            # Own stems only, so a chain of links does not pile up into a
            # false anchor. Portland's chain must still read as a chain.
            for j in range(i - 1, -1, -1):
                earlier = set(infos[j]["stems"]) - {"1P"}
                if earlier:
                    stems |= earlier
                    break
        out.append(stems)
    return out


def _anchored(effective: list, infos: list) -> bool:
    """Majority stem across topics, or most subject heads echo the index comment."""
    n = len(effective)
    counts = Counter()
    seen_keys = []
    for stems in effective:
        matched = set()
        for s in stems:
            key = next((k for k in seen_keys if same_stem(k, s)), None)
            if key is None:
                seen_keys.append(s)
                key = s
            matched.add(key)
        for k in matched:
            counts[k] += 1
    # A stem in a strict majority of topics anchors the paragraph. Two of six
    # does not: Truman's original names Truman twice and still drifts.
    if counts and max(counts.values()) >= n // 2 + 1:
        return True
    # Derived parts: later subject heads echo the index comment. Only the
    # head counts, since Truman's original echoes through modifiers and drifts.
    comment = infos[0]["comment_stems"]
    later = infos[1:]
    echo = 0
    for info in later:
        head = info["head"]
        if info["is_link"] or (head and shares({head}, comment)):
            echo += 1
    return bool(later) and echo >= INDEX_ECHO_SHARE * len(later)


def _chained(infos: list) -> float:
    """Share of sentences whose topic echoes any part of the previous sentence."""
    if len(infos) < 2:
        return 0.0
    linked = 0
    for prev, cur in zip(infos, infos[1:]):
        if cur["is_link"] or shares(cur["stems"], prev["all_stems"]):
            linked += 1
    return linked / (len(infos) - 1)


def _suggest_anchor(sentences: list) -> str:
    """The content word the most sentences already carry.

    A drift finding that only lists the drifting topics leaves the writer to
    guess which one should win, so the rewrite is a coin flip and often
    drifts again. The word already present in the most sentences is the
    paragraph's real subject. Naming it turns one block into one fix.
    """
    counts: dict = {}
    surface: dict = {}
    order: dict = {}
    for pos, sent in enumerate(sentences):
        seen = set()
        for raw in sent.split():
            w = _clean(raw)
            if not w or len(w) < 3 or w in STOP_WORDS or w in FIRST_PERSON:
                continue
            s = stem(w)
            if s in seen:
                continue
            seen.add(s)
            counts[s] = counts.get(s, 0) + 1
            surface.setdefault(s, w)
            order.setdefault(s, pos)
    if not counts:
        return ""
    best = max(counts, key=lambda s: (counts[s], -order[s]))
    if counts[best] < 2:
        return ""
    return surface.get(best, "")


def _anchor_hint(sentences: list) -> str:
    word = _suggest_anchor(sentences)
    if not word:
        return " Name one anchor and open most sentences on it."
    return f' Most sentences already mention "{word}". Open most of them on it.'


def _scan_paragraph(para: str, kinds: tuple, findings: list) -> None:
    sentences = paragraph_sentences(para)
    if len(sentences) < 2:
        return
    infos = [analyze_sentence(s) for s in sentences]
    index = infos[0]
    effective = _effective_stems(infos)
    n = len(sentences)
    topic_labels = [_short(i["subject_words"] or i["topic_words"], 3) for i in infos]

    drifted = False
    # Instructions have no topic slot to anchor with, so a paragraph of
    # mostly imperatives skips the drift rules and keeps the runway rule.
    instructions = sum(1 for i in infos if i["imperative"]) >= IMPERATIVE_SHARE * n
    if (
        ("topic_drift" in kinds or "unanchored_chain" in kinds)
        and n >= DRIFT_MIN_SENTENCES
        and not instructions
    ):
        if not _anchored(effective, infos):
            drifted = True
            chain = _chained(infos)
            closes = shares(infos[-1]["all_stems"], index["stems"])
            if chain >= CHAIN_SHARE:
                if "unanchored_chain" in kinds and n >= CHAIN_MIN_SENTENCES and not closes:
                    findings.append({
                        "kind": "unanchored_chain",
                        "label": (
                            f"unanchored chain: {n} sentences each pick up the one before "
                            f"({' / '.join(topic_labels[:5])}) but no topic recurs and the last "
                            "sentence does not return to the subject. Close the loop by ending on "
                            "the opening subject." + _anchor_hint(sentences)
                        ),
                        "match": _short(index["words"], 8),
                        "line": 0,
                    })
            elif "topic_drift" in kinds:
                findings.append({
                    "kind": "topic_drift",
                    "label": (
                        f"topic drift: {n} sentences, topics {' / '.join(topic_labels[:5])} "
                        "share no anchor." + _anchor_hint(sentences)
                    ),
                    "match": _short(index["words"], 8),
                    "line": 0,
                })

    # A drifting paragraph already got one finding. A second one for the same
    # sentences would only repeat it.
    if "new_in_topic" in kinds and n >= 3 and not drifted:
        run = []
        runs = []
        for i in range(1, n):
            cur = infos[i]
            fresh = (
                not cur["is_link"]
                and len(cur["subject_words"]) >= 2
                and not shares(cur["stems"], infos[i - 1]["all_stems"])
                and not shares(cur["stems"], index["all_stems"])
            )
            if fresh:
                run.append(i)
            else:
                if len(run) >= NEW_IN_TOPIC_RUN:
                    runs.append(run)
                run = []
        if len(run) >= NEW_IN_TOPIC_RUN:
            runs.append(run)
        for run in runs:
            shown = " / ".join(topic_labels[i] for i in run[:3])
            findings.append({
                "kind": "new_in_topic",
                "label": (
                    f"new information in the topic slot for sentences {run[0] + 1} to {run[-1] + 1} "
                    f"({shown}). Open each sentence with something the reader already holds."
                ),
                "match": _short(infos[run[0]]["words"], 8),
                "line": 0,
            })

    if "missing_index" in kinds and n >= 3:
        first_word = _clean(index["words"][0]) if index["words"] else ""
        opens_clause = first_word in CLAUSE_OPENERS or first_word.endswith("ing")
        signposted = any(ORDINAL_SIGNPOSTS.match(s) for s in sentences[1:])
        if (
            opens_clause
            and index["first_clause_len"] >= MISSING_INDEX_CLAUSE_WORDS
            and not signposted
            and not ORDINAL_SIGNPOSTS.match(sentences[0])
        ):
            findings.append({
                "kind": "missing_index",
                "label": (
                    f"missing index: the paragraph opens with a {index['first_clause_len']}-word clause "
                    f"('{_short(index['orient_words'], 6)}') before any subject. Add a short first "
                    "sentence that names the whole the paragraph breaks down."
                ),
                "match": _short(index["words"], 8),
                "line": 0,
            })

    if "preview_term_dropped" in kinds and n >= 3:
        m = None
        for cand in _COORD_LIST.finditer(sentences[0]):
            m = cand
        if m:
            terms = [_clean(t) for t in _coord_terms(m.group(1))]
            terms = [t for t in terms if t and t not in STOP_WORDS and len(t) >= 4]
            # Floor stays at 3. Widening to 2 measured a false positive on real docs, an
            # ordinary "X and Y" clause reading as a two-term preview far more often than a real list does.
            if 3 <= len(terms) <= 6:
                later_topics = [i["stems"] for i in infos[1:]]
                later_all = set().union(*[i["all_stems"] for i in infos[1:]])
                in_topics = [any(shares({stem(t)}, s) for s in later_topics) for t in terms]
                anywhere = [shares({stem(t)}, later_all) for t in terms]
                # Require all but one term as a topic first, so a coincidental list
                # of names does not count as a genuine preview the paragraph tracks.
                if sum(in_topics) >= len(terms) - 1 and not all(anywhere):
                    dropped = [t for t, a in zip(terms, anywhere) if not a]
                    findings.append({
                        "kind": "preview_term_dropped",
                        "label": (
                            f"theme preview lists {', '.join(terms)} but '{dropped[0]}' never returns. "
                            "Repeat the listed term itself, not a synonym, when its turn comes."
                        ),
                        "match": m.group(0),
                        "line": 0,
                    })

    if "index_count_mismatch" in kinds and n >= 3 and not drifted:
        m = _INDEX_COUNT.search(sentences[0])
        if m:
            claimed = _COUNT_WORDS.get(m.group(1).lower())
            # "Two axes replace one" with no ordinal after it is not an enumeration.
            # Require one, so this only fires on a paragraph that walks through its parts.
            signposted = sum(
                1 for s in sentences[1:] if _ORDINAL_ANYWHERE.search(s)
            )
            parts_seen = n - 1
            if claimed and signposted >= 2 and abs(parts_seen - claimed) >= 1:
                findings.append({
                    "kind": "index_count_mismatch",
                    "label": (
                        f"index sentence claims {m.group(1)} {m.group(2)}, but the paragraph "
                        f"gives {parts_seen}. Match the count, or drop the number from the index."
                    ),
                    "match": m.group(0),
                    "line": 0,
                })


DOC_MIN_WORDS = 400
DOC_MIN_HEADINGS = 2
DOC_INTRO_RATIO = 0.35
DOC_TURN_MIN_HEADINGS = 3
DOC_TURN_MIN_SENTENCES = 2
_CONTRASTIVE_TURN = re.compile(
    r"\b(but|however|yet|though|although|still|nonetheless|nevertheless)\b", re.I
)


def _scan_document(text: str, kinds: tuple, findings: list) -> None:
    """Index-Discussion at document scale, and the introduction's turn.

    Both need the whole document, not one paragraph, so they run once per
    scan_flow call rather than inside _scan_paragraph. Both stay narrow: a
    short file or a flat one-section doc never has an intro to judge.
    """
    heading_pos = [m.start() for m in re.finditer(r"^\s*#{1,6}\s+", text, re.MULTILINE)]
    if len(heading_pos) < DOC_MIN_HEADINGS:
        return
    total_words = len(prose_only(text).split())
    if total_words < DOC_MIN_WORDS:
        return

    # The intro is between the title heading and the next one, not before the
    # title. A doc that opens "# Title" has nothing before that line at all.
    intro = text[heading_pos[0]: heading_pos[1]]
    intro_words = len(prose_only(intro).split())
    if not intro_words:
        return
    headings = [ln for ln in text.splitlines() if _HEADING_LINE.match(ln)]

    if "doc_intro_too_long" in kinds:
        ratio = intro_words / total_words
        if ratio > DOC_INTRO_RATIO:
            findings.append({
                "kind": "doc_intro_too_long",
                "label": (
                    f"intro runs {intro_words} of {total_words} words ({ratio:.0%}) before the "
                    "first heading. The introduction should run much shorter than the body."
                ),
                "match": "",
                "line": 0,
            })

    if "intro_missing_turn" in kinds and len(headings) >= DOC_TURN_MIN_HEADINGS:
        intro_sentences = split_sentences(prose_only(intro))
        if len(intro_sentences) >= DOC_TURN_MIN_SENTENCES and not _CONTRASTIVE_TURN.search(intro):
            findings.append({
                "kind": "intro_missing_turn",
                "label": (
                    "introduction states a claim across "
                    f"{len(intro_sentences)} sentences with no contrastive turn ('but', 'however') "
                    "before the first heading. State the status quo, then turn to the problem it costs."
                ),
                "match": _short(intro_sentences[0].split(), 8),
                "line": 0,
            })


def scan_flow(text: str, kinds: tuple = ALL_KINDS) -> list:
    """Scan text for reader-expectation flow findings."""
    findings = []
    if not text or not text.strip():
        return findings

    text = _strip_leading_yaml_frontmatter(text)
    _scan_document(text, kinds, findings)

    if "vague_heading" in kinds:
        for line_num, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
            if m and m.group(1).strip().lower() in VAGUE_HEADINGS:
                findings.append({
                    "kind": "vague_heading",
                    "label": f"vague heading '{m.group(1).strip()}'. Name the key concept the section develops.",
                    "match": m.group(1).strip(),
                    "line": line_num,
                })

    paragraphs = prose_paragraphs(text)
    if not paragraphs and not any(
        _LIST_LINE.match(ln) or _TABLE_LINE.match(ln) for ln in text.splitlines()
    ):
        paragraphs = [text]

    if "long_runway" in kinds:
        for para in paragraphs:
            for s in paragraph_sentences(para):
                info = analyze_sentence(s)
                if info["runway"] is not None and info["runway"] > LONG_RUNWAY_CAP:
                    findings.append({
                        "kind": "long_runway",
                        "label": (
                            f"long runway: {info['runway']} words before the verb, cap {LONG_RUNWAY_CAP}. "
                            f"Move \"{_short(info['subject_words'], 6)}\" after the verb, or split the "
                            "sentence so a short familiar subject comes first."
                        ),
                        "match": _short(info["subject_words"], 8),
                        "line": 0,
                    })

    paragraph_kinds = tuple(k for k in kinds if k not in ("long_runway", "vague_heading"))
    if paragraph_kinds:
        for para in paragraphs:
            _scan_paragraph(para, paragraph_kinds, findings)
    return findings


if __name__ == "__main__":
    import sys
    sample = sys.stdin.read()
    for f in scan_flow(sample):
        print(f"{f['kind']}: {f['label']}")
    print("topics:", *topics(sample), sep="\n  ")
