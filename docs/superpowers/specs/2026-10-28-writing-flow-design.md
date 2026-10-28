# writing-flow: standalone writing package design

Date: 2026-10-28. Status: draft for approval.

## Intent

Your writing system shapes every doc, commit and chat reply that an agent writes for you. It lives inside harness-kit today. But harness-kit holds about 114 hooks, so the writing rules cannot travel, version or install without the rest of the kit. This design moves a copy of every writing mechanism and opinion into one private package, `Synx-x/writing-flow`, that runs with no harness-kit installed.

## Decisions you made

1. **STE and flow on everything, plus your standard repo layout.** Every doc in the package passes its own ASD-STE100 and flow checks. The repo also gets the agent-native layout that Pulse-MCP uses.
2. **Copy now, cut over later.** harness-kit stays untouched in this job. A later change makes harness-kit consume the package.
3. **Plugin, Python core and CLI.** One Claude Code plugin sits over a zero-dependency Python core. The same core installs with pip and runs as a CLI.
4. **Scope edges.** The package carries plain mode and the Codex adapter. From `response_audit.py` it carries four gates: chat form, personal style, the flow gate and grounding.

## Goals

- Carry every writing hook, library, output style, rule, skill and agent listed in the inventory below.
- Run with no harness-kit present. No runtime import may reach into harness-kit.
- Give the same verdicts as harness-kit on the same input. The ported tests prove this.
- Pass its own checker on every doc in the repo.

## Non-goals

- No edits to harness-kit. Its branch `fix/issue-82-pulse-setup` holds another session's uncommitted work.
- No commit-attribution guard and no comment-debt guard. Both stay in harness-kit.
- No localization check and no Hermes adapter.
- No copy of `avoid-ai-writing`. Conor Bronsdon owns it under MIT.
- No live install. With harness-kit active, the two would fire every hook twice. The cut-over job installs it.

## Anti-goals

The package fails, even if it runs, in two cases:

- **Rule drift.** Its verdicts differ from harness-kit's on the same text, and nothing flags the difference.
- **Hidden coupling.** It works only because harness-kit sits on the same machine.

## Inventory

### Hooks

| Hook | Event | Change from harness-kit |
| --- | --- | --- |
| `guard_style` | PreToolUse Write, Edit | Imports rewired only |
| `guard_flow` | PreToolUse Write, Edit | Imports rewired only |
| `style_check` | PostToolUse Write, Edit, MultiEdit, NotebookEdit | Imports rewired only |
| `guard_doc_residue` | PostToolUse Write, Edit, MultiEdit, NotebookEdit | Imports rewired only |
| `message_display_audit` | MessageDisplay | Imports rewired only |
| `subagent_style_audit` | SubagentStop | Imports rewired only |
| `flow_reinforce` | UserPromptSubmit | Registered direct, no dispatcher |
| `plain_tracker`, `plain_inject` | UserPromptSubmit | Registered direct, tracker first |
| `violation_feedback` | UserPromptSubmit | Registered direct |
| `response_audit` | Stop | Cut to four gates, see below |

The cut-down `response_audit` keeps the flow gate, the chat-form check, the personal-style check and the grounding check. It drops `check_localization` and the `locale_preset` import. It keeps its background worker and its one-block-per-response marker.

The Codex adapter wires `guard_style`, `guard_flow`, `style_check` and `guard_doc_residue` to `apply_patch` and `write_file`, as harness-kit does now.

### Libraries

The rule engines move unchanged: `prose_rules`, `flow_rules`, `plain_rules`, `personal_style`, `naming_rules`. The state helpers move with them: `flow_state`, `plain_state`, `rewrite_log`, `violations_store`, `edit_scope`, `claude_temp`, `output_style`, `transcript`, `_transcript_utils`, `shell_argv`, `git_command` and `bg_spawn`.

### Opinions

- Output styles: `writing-flow.md` and `technical-english.md`, from `~/.claude/output-styles/`.
- Rules: `human-comms-writing.md` and the scaffold template `writing-style.md`.
- Plain mode: `RULES.md`.
- Skills: `technical-english`, `human-comms-writing`, `guard-style-compliance`.
- Agents: `audit-reader-flow`, `audit-ai-writing`.
- Scripts: `prose_sweep.py` and `flow_report.py`, folded into the CLI.

## Decoupling

The writing hooks touch harness-kit infrastructure in six places. Each gets a small package-owned module with the same function names, so the rule code stays line-for-line comparable.

| harness-kit module | Replacement | Behaviour |
| --- | --- | --- |
| `local_kit` | `writing_flow.config` | Reads `hook_config`, `hook_enabled`, `hook_verbosity`, `bypass_release` and `retro_fix_enabled` from the package config file |
| `kit_paths` | `writing_flow.paths` | State lives in `~/.claude/writing-flow/`. `WRITING_FLOW_STATE_DIR` overrides it for tests |
| `harness_runtime` | `writing_flow.runtime` | Keeps the tool aliases and the session and state fields only |
| `phase_state` | `writing_flow.phase` | Reads a phase file when a classifier wrote one. Otherwise phase is unknown |
| `failopen`, `telemetry_writer` | `writing_flow.failopen` | Notes a swallowed error to a log in the state dir |
| `_hook_utils` | `writing_flow.hookio` | Keeps `read_hook_stdin` and `get_project_root` only |

Phase needs care. In harness-kit, a classifier hook writes the session phase, and grounding skips the coding and meta phases. The package has no classifier. With phase unknown, grounding runs on every reply, as harness-kit does today when its classifier has not written a phase yet.

## Layout

```
writing-flow/
  .claude-plugin/plugin.json
  hooks/hooks.json            Claude Code registrations
  hooks/*.py                  thin entry scripts, one per hook
  adapters/codex/             apply_patch and write_file wiring
  src/writing_flow/           rule engines, state, config, CLI
  output-styles/              writing-flow.md, technical-english.md
  skills/                     technical-english, human-comms-writing, guard-style-compliance, plain-mode
  agents/                     audit-reader-flow.md, audit-ai-writing.md
  rules/                      human-comms-writing.md, writing-style.md
  tests/
  docs/                       rule catalogue, configuration, provenance
  AGENTS.md CLAUDE.md GEMINI.md README.md CHANGELOG.md
  CONTRIBUTING.md SECURITY.md LICENSE pyproject.toml
  .github/workflows/ci.yml
```

Hook scripts put `${CLAUDE_PLUGIN_ROOT}/src` on the import path. The plugin therefore needs no pip install. A pip install adds the `writing-flow` command with three verbs: `check`, `sweep` and `report`.

Two plugin facts shape the layout. Both come from the Claude Code plugin manifest reference.

- **Output style names get a namespace.** Claude Code names every plugin component as `<plugin>:<component>`, so the style can appear as `writing-flow:writing-flow`. `output_style.py` must accept the bare name and the namespaced name. The user-level copy in `~/.claude/output-styles/` stays in place until the cut-over.
- **A root `CLAUDE.md` is not plugin context.** `claude plugin validate` warns about it. The repo keeps a one-line `CLAUDE.md` bridge for work on the repo itself and accepts that warning. CI therefore runs `claude plugin validate` without `--strict`.

## Verification

1. The ported tests pass. They cover every included hook and library. Tests for excluded parts stay behind.
2. A parity run feeds the same fixtures to harness-kit and to the package and diffs the verdicts. The diff must be empty.
3. Each hook script gets a sample event on stdin. A violating Write must deny, and a clean Write must pass.
4. `writing-flow check` flags a known-bad fixture and passes every doc in the repo.
5. A grep shows no import or path that reaches harness-kit.
6. CI runs steps 1, 4 and 5 on every push.

## Delivery

- Location: `~/dev/writing-flow`, which sits on the shared disk.
- Remote: `gh repo create Synx-x/writing-flow --private`, then push `main`.
- Version 0.1.0, MIT licence, Python 3.10 or later.
- Build: your standing rule sends a port of this size to Codex through herdr. I write the brief, run its commands once myself, then audit the report against the logs and diffs.

## Calls I made

- The repo name, its location and the MIT licence.
- The state directory `~/.claude/writing-flow/` and the override variable.
- Unknown phase runs grounding on every reply.
- The CLI verbs `check`, `sweep` and `report`.
- The plugin root is the repo root, so the `CLAUDE.md` bridge stays and `plugin validate` runs without `--strict`.

## Left to the builder

- The config file schema, provided it keeps the five `local_kit` functions.
- The test fixture layout.
- The CI matrix, provided it covers Python 3.10 and the current release.
