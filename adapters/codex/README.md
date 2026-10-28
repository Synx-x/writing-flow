# Codex adapter

This directory is the harness boundary for Codex support. It normalizes Codex
event and tool vocabulary into the portable hook payload used by harness-kit.

The adapter is registered only for Codex-native file-change tool names in the
shared hook registry. Claude's `Write|Edit` matchers remain unchanged. Codex
requires hook trust review before non-managed command hooks run; review the
plugin hooks through `/hooks` after installation. For one-off smoke tests,
Codex supports `--dangerously-bypass-hook-trust`, but that flag is not a
recommended production setting.

The Claude plugin remains governed by `.claude-plugin/plugin.json` and
`hooks/hooks.json`; this adapter must not change that baseline.
