# writing-flow

`writing-flow` checks writing style and information flow for Claude Code and
Codex. It runs as a Claude Code plugin, a Codex hook adapter, or a Python CLI.
The runtime uses only the Python standard library.

## Install as a Claude Code plugin

Install the repository through Claude Code's plugin manager. Validate the
plugin from its repository root with `claude plugin validate .`. The plugin
loads its hook scripts from its own directory, so it does not need a pip
install.

## Install with pip

Use Python 3.10 or later:

```sh
python3 -m pip install .
```

The package installs the `writing-flow` command.

## CLI

Run the checker on files or directories:

```sh
writing-flow check README.md AGENTS.md docs/rules.md docs/configuration.md docs/provenance.md docs/parity.md skills rules output-styles agents commands
```

The checker prints each finding with its file and line. It returns 1 when it
finds an issue and 0 when the checked Markdown passes. Run `writing-flow sweep`
to review older prose, or `writing-flow report` to review flow-gate outcomes.

## Hooks

Claude Code hooks are registered in `hooks/hooks.json`. Codex file changes run
through `adapters/codex/run_hook.py`. The standalone state directory defaults
to `~/.claude/writing-flow/state/` in Claude Code and
`~/.codex/writing-flow/state/` in Codex.

Do not install this plugin while harness-kit remains active. Both packages
would run the same writing hooks in one turn.

See [configuration](docs/configuration.md), [rules](docs/rules.md), and
[source provenance](docs/provenance.md) for details.
