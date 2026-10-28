# Configuration

The config file defaults to `~/.claude/writing-flow/config.json`. Set
`WRITING_FLOW_CONFIG` to use another file. A missing or invalid file uses
built-in defaults.

## Config keys

| Key | Location | Default |
| --- | --- | --- |
| `bypass_all` | Top level | `false` |
| `retro_fix_conformance` | Top level | `true` |
| `enabled` | `hooks.<hook>` | `true` |
| `verbosity` | `hooks.<hook>` | `auto` |
| `mode` | `hooks.guard_flow` | `warn` |
| `kinds` | `hooks.guard_flow` | All standard flow kinds |
| `exempted_paths` | `hooks.guard_flow` | Empty list |
| `exempt_marker` | `hooks.guard_flow` | `flow-exempt` |
| `allow_override` | `hooks.guard_flow` | `true` |
| `block_cap` | `hooks.guard_flow` | `2` |
| `flow_mode` | `hooks.response_audit` | `strict` |
| `chat_form` | `hooks.response_audit` | `strict` |

## Environment variables

Each `WRITING_FLOW_<NAME>` variable takes priority over its
`HARNESS_KIT_<NAME>` compatibility name.

| Variable | Default | Purpose |
| --- | --- | --- |
| `WRITING_FLOW_HOME` | Current user home | Home base for package-owned paths |
| `WRITING_FLOW_CONFIG` | `~/.claude/writing-flow/config.json` | Config file path |
| `WRITING_FLOW_STATE_DIR` | `~/.claude/writing-flow/state/` in Claude Code; `~/.codex/writing-flow/state/` in Codex | State directory |
| `WRITING_FLOW_HARNESS` | `claude` | Runtime name; the Codex adapter sets `codex` |
| `WRITING_FLOW_SESSION_ID` | No value; runtime uses `unknown-session` | Session identifier fallback |
| `WRITING_FLOW_PLUGIN_ROOT` | No value | Plugin root fallback for Codex events |
| `WRITING_FLOW_STE` | `default` | Structural English mode: `off`, `warn` or `strict` |
| `WRITING_FLOW_FLOW` | `warn` | File flow gate mode |
| `WRITING_FLOW_SKIP_FLOW_CHECK` | `0` | Skip the file flow gate when set to `1` |
| `WRITING_FLOW_ALLOW_VERBATIM` | `0` | Allow a verbatim file when set to `1` |
| `WRITING_FLOW_ALLOW_RESIDUE` | `0` | Skip the residue check when set to `1` |
| `WRITING_FLOW_PLAIN_RULES` | Package `skills/plain-mode/RULES.md` | Plain-mode rules file |
| `WRITING_FLOW_RESPONSE_FLOW` | `strict` | Response flow gate mode |
| `WRITING_FLOW_CHAT_FORM` | `strict` | Chat form gate mode |
| `WRITING_FLOW_SUBAGENT_FLOW` | `warn` | Subagent flow audit mode |
| `WRITING_FLOW_BYPASS` | `0` | Release a bypassable hook when set to `1` |
| `WRITING_FLOW_RETRO_FIX` | Config default: `true` | Disable retroactive checks when set to `0` |
| `WRITING_FLOW_TELEMETRY_LOG` | System temp directory plus `writing-flow-telemetry.jsonl` | Codex adapter telemetry file |

The markers `[writing-flow-bypass]` and `[kit-bypass]` release a bypassable
hook for one content item. Every bypass is recorded in the state directory.
