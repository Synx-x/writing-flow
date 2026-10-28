# Rule catalogue

## Prose rules

`prose_rules` checks chatbot phrases, tier-one word choices, em-dash density,
conversation residue, sentence length, semicolons, nominalizations, phrasal
verbs, passive voice and synonym rotation. Structural checks use strict mode
for documents and a flavored mode for chat.

## Flow rules

`flow_rules` checks long runways, topic drift, unanchored chains, new material
in the topic slot, missing index sentences, dropped preview terms, vague
headings, index-count mismatch and long document introductions. The
`intro_missing_turn` check is opt-in because it produces too many false
positives on ordinary documents.

## Plain-mode rules

`plain_rules` checks sentence length, paragraph sentence and word counts,
paragraph chains and first-use glosses for tracked terms. Code blocks and
inline code do not count as prose.

## Personal style

`personal_style` checks academic setup phrases, expository transitions,
indirect instructions, over-hedging, verbose constructions and response
verbosity budgets. Response audits also check chat form, reader flow and
grounding.
