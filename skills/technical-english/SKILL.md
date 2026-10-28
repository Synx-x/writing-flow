---
name: technical-english
description: >
  Distilled, ASD-STE100-derived writing rules for docs, commit messages, error
  messages, and code comments — surfaces the writing system the model should
  follow BEFORE writing, as the companion to the structural checks in
  hooks/lib/prose_rules.py (STE_STRICT/STE_FLAVORED). Use when writing
  markdown docs, commit bodies, PR descriptions, or code comments; skip for
  chat replies and prose that needs personality.
---

# technical-english: give the model the writing system, not a blacklist

Intended for the model to load before writing, not for a user to invoke
directly. This file previously declared `user_invocable: false` to say so.
Nothing reads that field, and https://code.claude.com/docs/en/skills does not
define it, so the declaration enforced nothing and the skill stayed invocable.
The intent is recorded here instead of in frontmatter that does not work. The
documented field, `disable-model-invocation`, expresses the opposite of what
this skill wants.

## Why this exists

A banned-word list (harness-kit's `_TIER1_WORDS`/`_BANNED_PHRASES`) catches
vocabulary. It does not catch structure: a sentence can pass every ban and
still be run-on, nominalized, passive, and hedged into mush. A published
experiment measured this directly — see `harness-kit@c48f5e6:docs/harness-kit.md` for the source
and numbers. Banning words scored a 3-40% slop reduction depending on model.
Giving the model ASD-STE100 (Simplified Technical English, an aerospace
maintenance-manual writing standard, first published 1986, current Issue 9
released 2025-01-15) scored 74%. The lesson: a checkable system beats a
blacklist. This skill is that system, distilled to what harness-kit's linter
can actually verify — not the 434-page standard, which is copyrighted and
would burn context for nothing.

Every rule below names the `src/writing_flow/prose_rules.py` kind that checks it, so
the skill and the linter cannot drift apart.

## Two modes

**Strict** — procedures, error messages, docs, commit messages, code
comments. Anywhere a wrong reading has a cost and nothing needs a voice.

**Flavored** — chat replies, subagent narration, anything that needs range.
Drops the word caps and the semicolon ban; keeps the structural rules, which
never hurt readability.

## Strict rules

1. **One name per thing.** Don't call the same entity "the user," "the
   customer," and "the client" in one document. Pick one and keep it.
   (`synonym_rotation`)
2. **Instruction sentences: 20 words max. Descriptive sentences: 25 words
   max.** If a sentence needs more, it's two sentences. (`long_sentence`)
3. **No semicolons.** Split into two sentences. (`semicolon`)
4. **Use the verb, not the frozen noun.** "Analyze the data," not "perform an
   analysis of the data." "Help," not "provide assistance." (`nominalization`)
5. **No decorative phrasal verbs.** "Contact," not "reach out to." "Retry,"
   not "circle back." "Investigate," not "drill down into." (`phrasal_verb`)
6. **Prefer active voice.** "The tool writes the file," not "the file is
   written by the tool." Passive is fine when the actor genuinely doesn't
   matter; the check flags a document, not a sentence, once passive crosses
   ~20% of it. (`passive`)

## Flavored rules (everywhere else)

Rules 1, 4, 5, 6 above apply without the word caps or semicolon ban. Chat
needs to breathe; slop doesn't come from sentence length there, it comes from
nominalized verbs, decorative phrasal verbs, and passive hedging.

## What this does not fix

ASD-STE100 fixes form: ambiguity, run-ons, decoration. It does not fix
substance. A false claim written in short, active, one-name-per-thing
sentences is still false. Verify facts first; this skill governs how to state
a fact plainly, not whether the fact holds.

## Dial

`HARNESS_KIT_STE` controls how hard the linter enforces this: `strict`
(default) blocks docs/commit violations and warns on chat; `warn` downgrades
every surface to a notice; `off` disables the structural checks entirely.
`ai_ism` and `tier1` checks are unaffected by this variable.
