# Source provenance

The copied hooks, libraries, adapters, scripts, skills, agents and tests come
from harness-kit commit `c48f5e6`. The source archive was read through
`git archive`. no harness-kit working-tree files were used.

## Source-to-package mapping

- `hooks/*.py` writing hooks map to `hooks/` with their original names.
- `hooks/lib/*.py` rule modules map to `src/writing_flow/`. `_transcript_utils.py`
  maps to `transcript_utils.py`.
- `adapters/codex/` maps to `adapters/codex/`.
- `scripts/prose_sweep.py` and `scripts/flow_report.py` map to `sweep.py` and
  `report.py` in `src/writing_flow/`. `scripts/plain_log.py` and the plain-log
  command map to `scripts/` and `commands/`.
- `skills/technical-english/`, `skills/scaffold/plain-mode/RULES.md`,
  `skills/scaffold/templates/.claude/rules/writing-style.md`, and the two
  audit agents map to the matching package directories.
- `test_*.py` files for included writing modules map to `tests/`. The four
  tests below remain out of this package because they cover excluded features.

The user-owned output styles, human communications rule and two skills were
copied from their installed source locations. The package does not modify those
source copies.

## Tests left behind

- `test_locale_preset.py`: tests the excluded localization preset.
- `test_manifest_check.py`: tests harness-kit manifest validation.
- `test_health_check_style_guard.py`: tests a harness-kit health script.
- `test_usage_report.py`: tests a harness-kit usage reporting script.

Additional source tests and cases left behind:

- `test_guard_grounding.py` and `test_guard_grounding_paths.py`: exercise the
  separate `guard_grounding.py` hook, which is outside the approved hook list.
- `test_guard_false_positives.py`: exercises workflow detection, shell write
  routing and system-change guards, all outside the package inventory.
- `test_code_comment_guard.py`: its integration assertions depend on the
  excluded comment-debt hook. Comment parsing remains covered by prose-rule
  tests and included guard-style tests.
- `test_personal_style_wired.py`: asserts the old `hooks/lib` location and
  imports `workflow_detect.py`, both outside the new package layout.
- Three `test_guard_style_gaps.py` cases cover commit attribution and
  `gh`-command scanning, which this package does not include.
- Three response-audit cases require `clean_reply_handoff`, which is not in the
  approved inventory. The included flow, chat, personal-style and grounding
  gates remain covered.

The xfailed ported source test remains marked xfail by its source. All other
included source test assertions are retained.

## Doc edits

The source and replacement sentences below record reference fixes and checker edits.

- **File:** `skills/technical-english/SKILL.md`
  **Source sentence:**
  ```text
  A published experiment measured this directly — see `docs/harness-kit.md` for the source and numbers.
  ```
  **New sentence:**
  ```text
  A published experiment measured this directly — see `harness-kit@c48f5e6:docs/harness-kit.md` for the source and numbers.
  ```

- **File:** `skills/technical-english/SKILL.md`
  **Source sentence:**
  ```text
  Every rule below names the `hooks/lib/prose_rules.py` kind that checks it, so the skill and the linter cannot drift apart.
  ```
  **New sentence:**
  ```text
  Every rule below names the `src/writing_flow/prose_rules.py` kind that checks it, so the skill and the linter cannot drift apart.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  The session rewrote `hooks/lib/spawn_skill.py`'s `build_agent_dispatch_instruction()` for brevity and style.
  ```
  **New sentence:**
  ```text
  The session rewrote `harness-kit@c48f5e6:hooks/lib/spawn_skill.py`'s `build_agent_dispatch_instruction()` for brevity and style.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  Source: `hooks/lib/plain_rules.py`, harness-kit scaffold 1.24.1.
  ```
  **New sentence:**
  ```text
  Source: `src/writing_flow/plain_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/plain_rules.py`.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  Source: `hooks/lib/flow_rules.py`, same scaffold version, same directory.
  ```
  **New sentence:**
  ```text
  Source: `src/writing_flow/flow_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/flow_rules.py`.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  Source: `hooks/lib/prose_rules.py`, harness-kit scaffold 1.29.24, line 589.
  ```
  **New sentence:**
  ```text
  Source: `src/writing_flow/prose_rules.py`, copied from `harness-kit@c48f5e6:hooks/lib/prose_rules.py`, line 589.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  writing hooks/completion_gate.py as it exists today: semicolon in prose
  ```
  **New sentence:**
  ```text
  writing `harness-kit@c48f5e6:hooks/completion_gate.py` as it exists today: semicolon in prose
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  The finding names a semicolon already present in the shipped copy of `hooks/completion_gate.py`, a file this session never opened or edited.
  ```
  **New sentence:**
  ```text
  The finding names a semicolon already present in the shipped copy of `harness-kit@c48f5e6:hooks/completion_gate.py`, a file this session never opened or edited.
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Words that appear 5-20x more often in AI text than human text.
  ```
  **New sentence:**
  ```text
  Tier 1 words appear 5-20x more often in AI text than human text.
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Examples: landscape (metaphor), tapestry, beacon, nestled, showcasing. Also avoid: "look" + "at" (not del+ve), approach (not para+digm), start (not em+bark). Same for shows (not tes+tament to), solid (not ro+bust), thorough (not compre+hensive), complete (not hol+istic), practical (not action+able), smooth (not seam+less), and key (not piv+otal).
  ```
  **New sentence:**
  ```text
  Tier 1 examples include `landscape (metaphor)`, `tapestry`, `beacon`, `nestled`, and `showcasing`. Tier 1 also includes `look` + `at` (not `del+ve`), `approach` (not `para+digm`), and `start` (not `em+bark`). Tier 1 also includes `shows` (not `tes+tament to`), `solid` (not `ro+bust`), `thorough` (not `compre+hensive`), `complete` (not `hol+istic`), `practical` (not `action+able`), `smooth` (not `seam+less`), and `key` (not `piv+otal`).
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Individually fine, but two or more in the same paragraph signals AI origin.
  ```
  **New sentence:**
  ```text
  Tier 2 terms are fine alone. Tier 2 signals AI origin when two or more terms appear in one paragraph.
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Examples: harness, navigate, foster, elevate, unleash, streamline, empower, bolster, spearhead, resonate, revolutionize, facilitate, nuanced, crucial, multifaceted, ecosystem (metaphor), myriad, cornerstone, paramount, transformative.
  ```
  **New sentence:**
  ```text
  Tier 2 examples include `harness`, `navigate`, `foster`, `elevate`, `unleash`, `streamline`, `empower`, `bolster`, `spearhead`, `resonate`, `revolutionize`, `facilitate`, `nuanced`, `crucial`, `multifaceted`, `ecosystem (metaphor)`, `myriad`, `cornerstone`, `paramount`, and `transformative`.
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Common words AI overuses. Flag when they exceed roughly 3% of total word count.
  ```
  **New sentence:**
  ```text
  Tier 3 covers common words AI overuses. Tier 3 words need a flag when they exceed roughly 3% of the total word count.
  ```

- **File:** `agents/audit-ai-writing.md`
  **Source sentence:**
  ```text
  Examples: significant, innovative, effective, dynamic, scalable, compelling, unprecedented, exceptional, remarkable, sophisticated, instrumental, world-class.
  ```
  **New sentence:**
  ```text
  Tier 3 examples include `significant`, `innovative`, `effective`, `dynamic`, `scalable`, `compelling`, `unprecedented`, `exceptional`, `remarkable`, `sophisticated`, `instrumental`, and `world-class`.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  Common blockers: semicolons in prose, two verbs per sentence, sentences exceeding 25 words, long anchor text in Edit operations.
  ```
  **New sentence:**
  ```text
  Guard_style blocks writes for four common cases: `semicolons in prose`, `two verbs per sentence`, `sentences exceeding 25 words`, and `long anchor text` in Edit operations.
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  "I wanted to reach out"
  ```
  **New sentence:**
  ```text
  `"I wanted to reach out"`
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  One adjective before any noun that might create an objection. "Short deck" answers "do I have time for this?" before the reader asks. "Quick question" pre-empts "is this going to take long?"
  ```
  **New sentence:**
  ```text
  Add one adjective before a noun that might create an objection. A short deck answers "do I have time for this?" before the reader asks. A quick question pre-empts "is this going to take long?"
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  No "Kind regards." No "Please don't hesitate to reach out." No "Looking forward to your response."
  ```
  **New sentence:**
  ```text
  No "Kind regards." No `"Please don't hesitate to reach out."` No "Looking forward to your response."
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  "Touch base"
  ```
  **New sentence:**
  ```text
  `"Touch base"`
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  The first removes friction; the second creates it by implying the message should not have been sent.
  ```
  **New sentence:**
  ```text
  The first removes friction. The second creates it by implying the message should not have been sent.
  ```

- **File:** `skills/human-comms-writing/SKILL.md`
  **Source sentence:**
  ```text
  For a first contact or a senior stakeholder you have not met, a single sentence closer is safer: "Happy to answer questions if anything needs more context."
  ```
  **New sentence:**
  ```text
  For a first contact or a senior stakeholder you have not met, use a single sentence closer. This is safer: "Happy to answer questions if anything needs more context."
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  **A no-extension state file still counts as prose.** `guard_style.py` routes an unmatched-suffix path through `grammar_for()` (`/mnt/dusk/home/pc/harness-kit/hooks/lib/prose_rules.py:353-380`). A suffix-less name with no shebang line falls back to `PROSE_ROUTE`. That is the same route a `.md` file takes (`/mnt/dusk/home/pc/harness-kit/hooks/lib/prose_rules.py:369-378`). Example: `/home/pc/.claude/state/flow-override-<session_id>`. `response_audit.py`'s reader-flow gate reads that file as a one-shot escape (`/mnt/dusk/home/pc/harness-kit/hooks/response_audit.py:449-477`). A `Write` to it gets the full STE structural scan. Passive voice is part of that scan, same as a doc edit (`/mnt/dusk/home/pc/harness-kit/hooks/guard_style.py:81-93`). Verified live in session `28f78b27-2cd5-4689-aa67-b29647432193`: a flow-override Write hit a passive-voice ratio over 20% there and needed a rewrite before it could land. Draft any such marker note in short, active-voice sentences from the start.
  ```
  **New sentence:**
  ```text
  **A no-extension state file still counts as prose.** `guard_style.py` routes an unmatched-suffix path through `grammar_for()` (`src/writing_flow/prose_rules.py:353-380`). A suffix-less name with no shebang line falls back to `PROSE_ROUTE`. That is the same route a `.md` file takes (`src/writing_flow/prose_rules.py:369-378`). Example: `/home/pc/.claude/state/flow-override-<session_id>`. `response_audit.py`'s reader-flow gate reads that file as a one-shot escape (`hooks/response_audit.py:449-477`). A `Write` to it gets the full STE structural scan. Passive voice is part of that scan, same as a doc edit (`hooks/guard_style.py:81-93`). Verified live in session `28f78b27-2cd5-4689-aa67-b29647432193`: a flow-override Write hit a passive-voice ratio over 20% there and needed a rewrite before it could land. Draft any such marker note in short, active-voice sentences from the start.
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  The installed splitter confirms this directly. File `/tmp/flow-eval2/before-claude/plugins/cache/harness-kit/scaffold/1.21.0/hooks/lib/prose_rules.py`, line 570, ran against this sample:
  ```
  **New sentence:**
  ```text
  The installed splitter confirms this directly. File `src/writing_flow/prose_rules.py`, line 570, ran against this sample:
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  import sys; sys.path.insert(0, '/tmp/flow-eval2/before-claude/plugins/cache/harness-kit/scaffold/1.21.0/hooks/lib')
  ```
  **New sentence:**
  ```text
  import sys; sys.path.insert(0, 'src')
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  gets checked by the same family of code, `response_audit.py` (`/home/pc/.claude/plugins/cache/harness-kit/scaffold/1.21.0/hooks/response_audit.py`),
  ```
  **New sentence:**
  ```text
  gets checked by the same family of code, `response_audit.py` (`hooks/response_audit.py`),
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  (`/home/pc/.claude/plugins/cache/harness-kit/scaffold/1.21.0/hooks/lib/flow_state.py`, line 28).
  ```
  **New sentence:**
  ```text
  (`src/writing_flow/flow_state.py`, line 28).
  ```

- **File:** `skills/guard-style-compliance/SKILL.md`
  **Source sentence:**
  ```text
  Path: `/home/pc/.claude/plugins/cache/harness-kit/scaffold/1.24.1/hooks/lib/plain_rules.py`.
  ```
  **New sentence:**
  ```text
  Path: `src/writing_flow/plain_rules.py`.
  ```

- **File:** `src/writing_flow/prose_rules.py`
  **Source sentence:**
  ```text
  under-perform: see docs/harness-kit.md for the source experiment. These check sentence structure rather than word choice, so they catch slop a banned-word list cannot (nominalization, passive voice, run-ons, synonym drift).
  ```
  **New sentence:**
  ```text
  under-perform: see harness-kit@c48f5e6:docs/harness-kit.md for the source experiment. These check sentence structure rather than word choice, so they catch slop a banned-word list cannot (nominalization, passive voice, run-ons, synonym drift).
  ```
