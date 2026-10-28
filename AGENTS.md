# Agent guide

## Layout

- `hooks/` contains the Claude Code entry scripts and hook registrations.
- `src/writing_flow/` contains rule engines, state helpers and the CLI.
- `adapters/codex/` contains Codex event normalization and hook wiring.
- `skills/`, `rules/`, `output-styles/` and `agents/` hold shipped guidance.
- `docs/` records rules, configuration, parity and source history.

## Commands

Run the suite with `python3 -m pytest -q`.
Check shipped Markdown with `writing-flow check README.md AGENTS.md docs/rules.md docs/configuration.md docs/provenance.md docs/parity.md skills rules output-styles agents commands`.

Keep runtime imports and paths inside this repository. Do not depend on
harness-kit at runtime. Change copied rule logic only through a separately
reviewed design and parity update.
