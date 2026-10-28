# Configuration

The config file defaults to `~/.claude/writing-flow/config.json`. Set
`WRITING_FLOW_CONFIG` to use another file. A missing or invalid file uses
built-in defaults.

## Config keys

| Key | Location | Default |
| --- | --- | --- |
| `bypass_all` | Top level | `false` |
| `retro_fix_conformance` | Top level | `true` |
| `enabled` | `hooks.guard_style` | `true` |
| `verbosity` | `hooks.guard_style` | `auto` |
| `skip_env` | `hooks.guard_style` | `WRITING_FLOW_SKIP_STYLE_CHECK` |
| `skip_reason` | `hooks.guard_style` | Explains when the style skip switch applies |
| `reason` | `hooks.guard_style` | Retires caveman mode in favour of the technical-English output style |
| `enabled` | `hooks.guard_flow` | `true` |
| `mode` | `hooks.guard_flow` | `strict` |
| `kinds` | `hooks.guard_flow` | Eight live flow kinds; excludes `long_runway` |
| `allow_override` | `hooks.guard_flow` | `true` |
| `exempt_marker` | `hooks.guard_flow` | `flow-exempt` |
| `reason` | `hooks.guard_flow` | Documents why `long_runway` is excluded |
| `enabled` | `hooks.response_audit` | `true` |
| `flow_mode` | `hooks.response_audit` | `strict` |
| `flow_kinds` | `hooks.response_audit` | Eight live chat flow kinds; excludes `long_runway` |
| `allow_override` | `hooks.response_audit` | `true` |
| `conversational_multiplier` | `hooks.response_audit` | `2` |
| `conversational_floor` | `hooks.response_audit` | `25` |
| `soft_ratio` | `hooks.response_audit` | `1.2` |
| `hard_ratio` | `hooks.response_audit` | `1.8` |
| `reason` | `hooks.response_audit` | Documents why `long_runway` is excluded |
| `enabled` | `hooks.guard_prompt_echo` | `true` |
| `exempt_paths` | `hooks.guard_prompt_echo` | Empty list |
| `verbosity` | `hooks.<hook>` | `auto` unless a hook defines another default |
| `block_cap` | `hooks.guard_flow` and response audit | `2` blocks per target/reply |
| `exempted_paths` | `hooks.guard_flow` | Empty list |
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
| `WRITING_FLOW_FLOW` | `strict` from the package default | File flow gate mode |
| `WRITING_FLOW_SKIP_FLOW_CHECK` | `0` | Skip the file flow gate when set to `1` |
| `WRITING_FLOW_ALLOW_VERBATIM` | `0` | Allow a verbatim file when set to `1` |
| `WRITING_FLOW_ALLOW_RESIDUE` | `0` | Skip the residue check when set to `1` |
| `WRITING_FLOW_PLAIN_RULES` | Package `skills/plain-mode/RULES.md` | Plain-mode rules file |
| `WRITING_FLOW_RESPONSE_FLOW` | `strict` | Response flow gate mode |
| `WRITING_FLOW_CHAT_FORM` | `strict` | Chat form gate mode |
| `WRITING_FLOW_SKIP_STYLE_CHECK` | `0` | Skip the style check when set to `1` |
| `WRITING_FLOW_SUBAGENT_FLOW` | `warn` | Subagent flow audit mode |
| `WRITING_FLOW_BYPASS` | `0` | Release a bypassable hook when set to `1` |
| `WRITING_FLOW_RETRO_FIX` | Config default: `true` | Disable retroactive checks when set to `0` |
| `WRITING_FLOW_TELEMETRY_LOG` | System temp directory plus `writing-flow-telemetry.jsonl` | Codex adapter telemetry file |

The markers `[writing-flow-bypass]` and `[kit-bypass]` release a bypassable
hook for one content item. Every bypass is recorded in the state directory.
