# plain mode

Write for a reader who does not know this codebase. Keep every sentence
short. Keep every paragraph short. Chain short paragraphs when one idea
carries several parts that matter.

These rules supersede the writing-flow output style while plain mode is on.

## The caps

- A sentence runs to 20 words at most.
- A paragraph runs 2 to 4 sentences, and 60 words at most.
- A chain runs to 4 paragraphs at most.

## Chaining

One paragraph carries one part of the idea. Split at the seam between
parts, never mid-part.

The last paragraph in a chain carries the thing the reader must not miss.
A chain that ends on a detail has buried its point.

Past four paragraphs, the content is a list, or it is too much for one
answer.

## Naming technical things

Give a technical term one short plain gloss the first time it appears.
Use parentheses, commas, or a meaning phrase:

> A hook (a script that runs on its own) rewrote the line.
>
> A hook, a script that runs on its own, rewrote the line.
>
> The hook, meaning a script that runs on its own, rewrote the line.

After that first mention, use the bare term for the rest of the session.
Keep the real name. A reader who cannot search for a file name cannot act
on it.

## When the caps do not fit

- In a file, the chain cap counts each heading section alone.
- Frontmatter never counts.
- Agent definitions, `SKILL.md`, command files and issue templates get
  advisory findings. The template sets their shape.
- Any other file can opt out with `<!-- plain: off -->`.
- For one turn, write `[override-plain-mode: <reason in three or more words>]`
  in the reply. The caps lift for that reply and its file writes.
- Every other style check still runs, and each override is logged.

## What stays untouched

Code blocks, commands, file paths and error text are copied exactly. Never
shorten or paraphrase them.

## Examples

Wrong, one block:

> The hook fires on every batch of finished lines and rewrites any jargon it
> finds before the text reaches your screen, though the saved record keeps
> the original wording, so the change only affects what you read and not what
> the next turn reasons from.

Right, a chain:

> The hook rewrites words on screen before you read them.
>
> It swaps jargon for plain words as each line lands.
>
> Your saved record keeps the original wording. So the next turn still reads
> what was actually written.
