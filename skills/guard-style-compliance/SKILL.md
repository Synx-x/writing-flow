---
name: guard-style-compliance
description: "Use when writing docs to pass guard_style ASD-STE100 checks and avoid Edit blocks."
category: communication
allowed-tools: [Read, Edit, Bash]
---

# Guard Style Compliance

## When to use

Writing or editing skill documentation, design documents, or retrospectives that run through guard_style.py.

Risk: guard_style enforces ASD-STE100 Simplified Technical English rules. Multiple violations block Write or Edit until fixed.

Guard_style blocks writes for four common cases: `semicolons in prose`, `two verbs per sentence`, `sentences exceeding 25 words`, and `long anchor text` in Edit operations.

## Method

### 1. Identify which rules fire

Common violations:

- **Semicolons in prose** (STE 6.3): Cannot use `;` to join independent clauses. Rewrite as two sentences or use a dash.
- **Two verbs per action** (STE 1.11): Each sentence states one action. No "has and is" or "verify and apply".
- **25-word sentence limit** (STE 4.1): Count words. Split into two if over 25.
- **Long anchor text** in Edit operations: guard_style scans the entire old_string. Long pre-existing sentences can trigger violations.

### 2. Rewrite prose rules

**Semicolon → period or dash:**

```
Bad: The list is REMOVE_PACKAGES; adding to it uninstalls the item.
Good: The list is REMOVE_PACKAGES. Adding to it uninstalls the item.
Also OK: The list is REMOVE_PACKAGES – adding to it uninstalls the item.
```

**Two verbs → one verb per sentence:**

```
Bad: This check finds the list and applies the change.
Good: This check finds the list. Then apply the change.
```

**Long sentence → split at logical break:**

```
Bad: When the list name includes REMOVE, BLOCK, IGNORE, or EXCLUDE, the
script logic determines what effect adding an item has on the target system.

Good: When the list name includes REMOVE, BLOCK, IGNORE, or EXCLUDE,
check the script logic. It determines what effect adding an item has.
```

### 3. For Edit operations, use short anchors

If an Edit operation is blocked, the old_string may contain a long pre-existing sentence. Find a shorter line boundary instead. The guard scans the entire old_string, so anchor on short line segments.

Example:

```markdown
old_string: |
  multiple clauses that may violate
  the word limit. Add new text here.
```

### 4. Check word count

For sentences longer than 15 words, count them.

```bash
echo "Your sentence here." | wc -w
```

Split if over 25.

### 5. Check for STE violations before writing

Run a quick check on your file.

```bash
grep -E ";" your_file.md
grep -E "[A-Z][a-z]+ and [a-z]+" your_file.md | head -5
```

These catch common patterns but are not exhaustive.

## Failure modes

| Symptom | Root cause | Fix |
|---------|-----------|-----|
| Edit blocked but old_string short | Anchor includes part of long pre-existing text | Find a shorter boundary. Move anchor. |
| "One verb" violation on one-verb sentence | Compound verb counts as two | Reword. Split into two sentences. |
| Semicolon violation I did not write | Pre-existing text in old_string | Shorten old_string to avoid the semicolon. |

## Example

**Bad (blocks Write):**

```markdown
old_string: |
  This document describes the system architecture, which includes
  the inference bridge, the workflow engine, and the container worker;
  all three components are essential to understand before designing.
```

Violation: semicolon in prose (STE 6.3). The semicolon is pre-existing context.

**Good (passes Write):**

```markdown
old_string: |
  Add the probe method here.
```

Then write:

```markdown
new_string: |
  ## Probe Method
  
  [Your content here. Watch for semicolons.]
  
  Add the probe method here.
```

## Watch out for

- **Guard_style scans the entire old_string.** Long unchanged sentences block the Edit. Anchor on short lines.
- **Compound verbs are invisible.** "This is and is not" has two verbs. Reword as separate sentences.
- **Abbreviations count as words.** "API call" is two words, not one.
- **Words in code blocks count toward prose limits.** Code inside a sentence like "Use the `process_list` function" counts as words. Keep prose short around code.
- **A no-extension state file still counts as prose.** `guard_style.py` routes an unmatched-suffix path through `grammar_for()` (`src/writing_flow/prose_rules.py:353-380`). A suffix-less name with no shebang line falls back to `PROSE_ROUTE`. That is the same route a `.md` file takes (`src/writing_flow/prose_rules.py:369-378`). Example: `/home/pc/.claude/state/flow-override-<session_id>`. `response_audit.py`'s reader-flow gate reads that file as a one-shot escape (`hooks/response_audit.py:449-477`). A `Write` to it gets the full STE structural scan. Passive voice is part of that scan, same as a doc edit (`hooks/guard_style.py:81-93`). Verified live in session `28f78b27-2cd5-4689-aa67-b29647432193`: a flow-override Write hit a passive-voice ratio over 20% there and needed a rewrite before it could land. Draft any such marker note in short, active-voice sentences from the start.

## guard_flow chains right after guard_style

guard_flow runs right after guard_style, on the same Write or Edit call.
guard_flow checks a different thing than guard_style checks. guard_flow
wants one shared subject across most sentences in a paragraph. guard_flow
wants the verb within about eight words of that subject. A guard_style fix
can still fail guard_flow. Splitting one long sentence into several short
ones removes the shared subject guard_flow is looking for.

This session hit both guards on the same file, twice. Session transcript
`/tmp/flow-eval2/before-claude/projects/-tmp-flow-eval2-before-work/e45ec800-fd69-4a32-9c92-a5ff1be0bdab.jsonl`
lines 60-93 show a SKILL.md write blocked by guard_style, then by
guard_flow on the next attempt. The same transcript, lines 297-361, show a
notes.md write blocked four times, alternating between the two guards.
`/home/pc/docs/retrospective.md`'s 2026-09-11 14:11 entry covers the same
session.

guard_flow offers two escape hatches for a false positive. Write
`flow-exempt: <why>` directly into the file. Or write one line to the
state directory's `flow-override-<session_id>` file, then retry the write
once. That second escape is single use. `HARNESS_KIT_FLOW=warn` downgrades
every guard_flow finding in the current process to a notice instead of a
block.

A local shadow copy of guard_flow can skip both escapes. `harness-kit-local-hook-authoring`
covers a verified case of that gap.

## guard_style's sentence splitter merges a quote-terminated sentence with the next one

guard_style's splitter looks for a period, an exclamation mark, or a
question mark right before a run of whitespace. guard_style's splitter
treats a closing quote mark differently. guard_style's splitter sees the
quote mark before the whitespace, not the punctuation, when a quoted
sentence ends in `inconsistency." A crash...`. guard_style's splitter then
skips the split at that point. guard_style's splitter counts two real
sentences as one long sentence there, against the 25-word cap.

The installed splitter confirms this directly. File
`src/writing_flow/prose_rules.py`,
line 570, ran against this sample:

```
python3 -c "
import sys; sys.path.insert(0, 'src')
import prose_rules as pr
s = 'Turning it off \"does not create any risk of database inconsistency.\" A crash can still lose \"some recent allegedly-committed transactions\" after a crash.'
print(pr._split_sentences(s))
"
```

The two sentences above come back joined into one 23-word span. The
transcript named above shows the live effect. A notes.md write hit this
block twice, at lines 333 and 340, while quoting Postgres and MySQL
documentation verbatim.

One fix closes the quote before the period. One fix reads
`... inconsistency", the docs say.` instead of ending the quote after the
period. One fix keeps the sentence boundary visible to the splitter.

Word count itself is not the deeper problem here. Word count comes from
splitting a sentence on whitespace. Word count treats a markdown link as
plain text. Word count adds exactly as many words as the link's own
visible anchor text, confirmed against a sample sentence.

## A chat reply has its own override target, separate from a file's

The escapes above cover a Write or Edit to a document. A chat-form reply
gets checked by the same family of code, `response_audit.py`
(`hooks/response_audit.py`),
but through its own override slot. `flow_state.CHAT_TARGET` names that slot
`"chat"`
(`src/writing_flow/flow_state.py`,
line 28). `take_flow_override()` in `response_audit.py` reads this target
specifically, so a chat override never consumes the same one-shot slot a
file-target override would use, and the reverse holds too.

The marker path itself carries a `-chat` suffix for this target:
`flow-override-<session_id>-chat`, built by `flow_state.override_path()`.
That differs from the plain `flow-override-<session_id>` name a file-target
override uses. Session `5de3a553-cbf3-4dc3-8b9d-45702f54f10d`
(`/home/pc/.claude/projects/-/5de3a553-cbf3-4dc3-8b9d-45702f54f10d.jsonl`)
wrote to
`/home/pc/.claude/state/flow-override-5de3a553-cbf3-4dc3-8b9d-45702f54f10d-chat`
to answer a "Verbosity finding (546 words, budget 40)" block on a
`research-grid`-formatted reply, and hit the same `guard_style` structural
scan documented above (a 42-word sentence) before the override text itself
was accepted.

`response_audit.py`'s own comment states the scope of this one slot: "Both
chat gates share one override, one block budget and one log line" (source
file, line 842). Both draw from the same `-chat` override slot: a
verbosity-budget finding, and a paragraph-subject `guard_flow` finding on a
chat reply. Neither is a separate mechanism from the other. Writing one
reasoned override line clears whichever of the two tripped.

## A brevity rewrite can drop a literal phrase another consumer keys off

Verified 2026-09-12, session `f6e65b65-7c19-44c1-8c25-d09abb93b06d`
(`/home/pc/.claude/projects/-/f6e65b65-7c19-44c1-8c25-d09abb93b06d.jsonl`).

- The session rewrote `harness-kit@c48f5e6:hooks/lib/spawn_skill.py`'s
  `build_agent_dispatch_instruction()` for brevity and style. The old text
  read `Dispatch this now via the Agent tool: subagent_type="{subtype}"...`.
  The new text dropped "via the Agent tool" and read only `Action: dispatch
  {subtype} — background, {model_clause}.`
- That exact phrase, "call the Agent tool", names the one tool a standing,
  per-session dispatch authorization on this host keys off. A hook message
  is the very thing that authorization is meant to recognize and act on.
- The same session caught this later, in the same transcript, and restored
  the phrase before committing: "that phrase is load-bearing, it names the
  exact tool to call, and I shouldn't have dropped it purely for brevity."

Watch for this whenever a rewrite targets a machine-read or
authorization-keyed message, not ordinary human-facing prose:

- Diff old text against new text for named tools, function names, and API
  identifiers, not only grammar and word count.
- A downstream consumer (a standing instruction, a regex, a parser) can key
  off one exact phrase. Style compliance does not know that phrase matters.
- Check this before commit, not only against the sentence-length and
  semicolon rules a style guard already enforces.

## A plan-mode document needs a list AND a flow-exempt comment, not either alone

<!-- flow-exempt: this section cites one distinct file:line fact per bullet by design. -->

- Verified live in session `089b7234-fbce-453a-b404-2c5a983484db`
  (`/home/pc/.claude/projects/-/089b7234-fbce-453a-b404-2c5a983484db.jsonl`).
- The target was `/home/pc/.claude/plans/bright-mixing-thacker.md`.
- That file is a plan produced by `ExitPlanMode`.
- ExitPlanMode saves through the same guarded Write path as any other file.
- The write took nine attempts across guard_style and guard_flow.
- A dense reference document trips both guards, and the two fixes do not overlap.

#### Why a list block clears guard_style's plain-mode caps

- Source: `src/writing_flow/plain_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/plain_rules.py`.
- Path: `src/writing_flow/plain_rules.py`.
- Line 26 sets `PARAGRAPH_SENTENCE_CAP = 4`.
- Line 27 sets `PARAGRAPH_WORD_CAP = 60`.
- Line 28 sets `CHAIN_CAP = 4`.
- `_paragraphs()` (lines 59-75) builds the block list these caps score.
- It skips any block `_is_list_block()` (line 56) matches.
- A matching block has at least one bullet or numbered line.
- Lines 64-67 give the reason in the docstring.
- Quote: "a list cannot also be judged as an oversized paragraph or another link in the chain it replaces."
- A flat bullet list drops out of paragraph, sentence, word, and chain scoring.

#### Why that same list block still fails guard_flow

- Source: `src/writing_flow/flow_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/flow_rules.py`.
- `grep -n "_is_list_block\|bullet" flow_rules.py` returns no hits.
- No list exemption exists in this file.
- Line 72 sets `LONG_RUNWAY_CAP = 10`.
- The topic-drift check sits near line 751.
- Both checks scan raw sentences.
- A markdown bullet line still counts as one sentence to that scanner.
- A bullet list where each line opens on a different subject reads as a chain with no shared anchor.
- guard_flow fires "topic drift" and "long runway" on the exact block that just cleared guard_style.

#### The fix

- guard_flow accepts the `flow-exempt: <reason>` comment shown above.
- `flow_state.py` in scaffold 1.21.0 is the source for that hatch.
- State plainly that the topic change per line is by design.
- Write the list conversion and the comment in the same draft.
- Do not restructure first and add the comment only after guard_flow blocks again.
- That second-pass ordering is what produced the nine-attempt sequence above.

## A hard-wrapped line inflates plain mode's sentence count per paragraph

Verified in session `855721cc-8b06-4c3d-b07e-82a7affd37b2`, writing a
verification-evidence file under plain mode. `prose_rules._split_sentences()`
splits per physical line first, by design.

- Source: `src/writing_flow/prose_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/prose_rules.py`, line
  589. The docstring states the reason directly: markdown here is written
  one paragraph per line, so joining lines first used to glue a bullet or
  a stray heading into a false run-on sentence.
- A paragraph typed as a hard-wrapped heredoc (each line under ~80 chars,
  manual newlines) breaks that assumption. Each wrapped line becomes its
  own "sentence" fragment, since most carry no terminal `.`, `!`, or `?`.
- A four-sentence paragraph, hard-wrapped across six lines, then reads as
  six sentences to `plain_rules.paragraph_cap()`, tripping "Plain: 6
  sentences in one paragraph, cap 4" on prose that was never that long.

Fix: type each paragraph as one long logical line (let the editor
soft-wrap) rather than hard-wrapping it. Before the real Write or Edit,
test the exact draft locally:

```bash
python3 -c "
import sys; sys.path.insert(0, '<hooks/lib dir>')
import plain_rules
text = open('<scratch draft path>').read()
print('sentence_cap:', plain_rules.sentence_cap(text))
print('paragraph_cap:', plain_rules.paragraph_cap(text))
print('chain_cap:', plain_rules.chain_cap(text))
"
```

All three returning `[]` means the draft clears plain mode before it ever
reaches the Write hook.

## health_check.py can report guard_style blocking a shipped harness file

`health_check.py --installed` runs a `style-guard-would-block-shipped-file`
probe. Session `0fdd6bfc-1efb-41a3-8c27-62175e961505`
(`/home/pc/.claude/projects/-/0fdd6bfc-1efb-41a3-8c27-62175e961505.jsonl`,
2026-09-17) hit this live, verbatim:

```
NEEDS MAINTAINER (shipped-plugin defect, not user-fixable)
  [warn] style-guard-would-block-shipped-file: guard_style would block
  writing `harness-kit@c48f5e6:hooks/completion_gate.py` as it exists today: semicolon in prose
  (STE 6.3 bans it)
```

The finding names a semicolon already present in the shipped copy of
`harness-kit@c48f5e6:hooks/completion_gate.py`, a file this session never opened or edited.
`guard_style.py` would refuse a fresh Write of that exact file today, since
its own shipped prose fails its own STE 6.3 check. This is a maintainer-side
defect in the harness-kit plugin release, not a violation this session
introduced.

Do not spend a turn trying to fix the shipped file in place. Editing a
vendored plugin file under `.claude/plugins/cache/` does not change the
next install and does not stop the health check from reporting it again.
Note the finding, move on, and let a harness-kit maintainer fix the source
file's prose or the guard's extraction logic upstream.

## Source

Session 2026-08-06 21:48 "Agent farm on Muse Spark": Writing /home/pc/docs/agent-farm-musespark.md triggered three guard_style blocks. Violations: semicolons, two verbs per sentence, sentences over 25 words. Rewriting to STE 6.3, 1.11, 4.1 standards resolved all. See /home/pc/docs/retrospective.md.
