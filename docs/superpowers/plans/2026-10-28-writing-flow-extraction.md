# writing-flow Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `writing-flow`, a standalone copy of the harness-kit writing system that runs as a Claude Code plugin, a Codex adapter and a Python CLI.

**Architecture:** Copy the writing hooks and libraries verbatim from one pinned harness-kit commit. Replace six harness-kit infrastructure modules with small package-owned modules that keep the same function names. Then change only imports in the copied code, and prove parity against harness-kit on the same fixtures.

**Tech Stack:** Python 3.10 or later, standard library only at runtime, pytest for tests, Claude Code plugin manifest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-28-writing-flow-design.md`

## Global Constraints

- Repo root: `/home/pc/dev/writing-flow`. The plugin root is the repo root.
- Source: harness-kit at commit `c48f5e6` (`origin/main`). Read it only through `git -C /home/pc/harness-kit archive c48f5e6 <paths>` or `git -C /home/pc/harness-kit show c48f5e6:<path>`. Never read or write the harness-kit working tree.
- Runtime dependencies: none. The standard library only.
- Python: 3.10 or later. Local runs use `python3` (3.14).
- No runtime import, `sys.path` entry or file path may reach harness-kit or `/srv/dusk`.
- Plugin name `writing-flow`, version `0.1.0`, licence MIT, author `Synx-x`.
- Config file: `~/.claude/writing-flow/config.json`. `WRITING_FLOW_CONFIG` overrides the path.
- State directory: `~/.claude/writing-flow/state/` under Claude Code, `~/.codex/writing-flow/state/` under Codex. `WRITING_FLOW_STATE_DIR` overrides both.
- Environment names: every `HARNESS_KIT_<X>` the copied code reads becomes `WRITING_FLOW_<X>`, with `HARNESS_KIT_<X>` as the fallback. `CLAUDE_STATE_DIR` is no longer read.
- Bypass sources: `WRITING_FLOW_BYPASS=1`, config `bypass_all: true`, or the marker `[writing-flow-bypass]` or `[kit-bypass]` in content. Bypassable hooks: `guard_style`, `guard_flow`, `subagent_style_audit`, `response_audit`.
- Every Markdown file the package ships passes `writing-flow check`.
- The executor runs no git command that writes: no commit, add, reset, stash, checkout or branch.

## Review Focus

1. **A missing or corrupt config file.** Every config function returns its default and no hook crashes. Task 2 pins it.
2. **The namespaced style name.** With `outputStyle` set to `writing-flow:writing-flow`, `flow_reinforce` finds the plugin's own style file. Task 4 pins it.
3. **An unwritable state directory.** A hook whose state write fails still returns its verdict and exits 0 or 2, never with a traceback. Task 4 pins it.
4. **A plugin path with a space.** Every hook command in `hooks/hooks.json` quotes `${CLAUDE_PLUGIN_ROOT}`. Task 5 pins it.
5. **Old environment settings.** A shell that still exports `HARNESS_KIT_STE=strict` gets strict STE checks. Task 2 pins it.

---

### Task 1: Scaffold and verbatim import

**Files:**
- Create: `pyproject.toml`, `src/writing_flow/__init__.py`, `tests/conftest.py`, `docs/provenance.md`
- Create by copy: every row of the mapping table below

| Source at `c48f5e6` | Target |
| --- | --- |
| `hooks/{guard_style,guard_flow,style_check,guard_doc_residue,message_display_audit,subagent_style_audit,flow_reinforce,plain_inject,plain_tracker,violation_feedback,response_audit}.py` | `hooks/` with the same names |
| `hooks/lib/{prose_rules,flow_rules,flow_state,plain_rules,plain_state,personal_style,output_style,naming_rules,rewrite_log,violations_store,edit_scope,claude_temp,transcript,scope,bg_spawn,shell_argv,git_command}.py` | `src/writing_flow/` with the same names |
| `hooks/lib/_transcript_utils.py` | `src/writing_flow/transcript_utils.py` |
| `adapters/codex/{run_hook.py,events.py,README.md}` | `adapters/codex/` |
| `scripts/{prose_sweep,flow_report}.py` | `src/writing_flow/sweep.py`, `src/writing_flow/report.py` |
| `scripts/plain_log.py`, `skills/scaffold/commands/plain-log.md` | `scripts/plain_log.py`, `commands/plain-log.md` |
| `skills/technical-english/` | `skills/technical-english/` |
| `skills/scaffold/plain-mode/RULES.md` | `skills/plain-mode/RULES.md` |
| `skills/scaffold/templates/.claude/rules/writing-style.md` | `rules/writing-style.md` |
| `agents/{audit-reader-flow,audit-ai-writing}.md` | `agents/` |
| the 33 port-set tests, less the four in the note below | `tests/` with the same names |

Copy these from outside harness-kit:

| Source | Target |
| --- | --- |
| `/home/pc/.claude/output-styles/{writing-flow,technical-english}.md` | `output-styles/` |
| `/home/pc/.claude/rules/human-comms-writing.md` | `rules/human-comms-writing.md` |
| `/home/pc/shared/skills/{human-comms-writing,guard-style-compliance}/` | `skills/` |

The port set is every test file at `c48f5e6` that names only included modules. Leave out `test_locale_preset.py`, `test_manifest_check.py`, `test_health_check_style_guard.py` and `test_usage_report.py`. They cover the dropped localization check and harness-kit scripts.

- [ ] **Step 1: Copy every row.** For harness-kit rows, run `git archive c48f5e6 <paths> | tar -x -C <staging>`. Then move each file to its target.
- [ ] **Step 2: Write `pyproject.toml`.** Set name `writing-flow`, version `0.1.0` and `requires-python = ">=3.10"`. Use the src layout with no dependencies. Add the console script `writing-flow = "writing_flow.cli:main"` and pytest `testpaths = ["tests"]`.
- [ ] **Step 3: Write `tests/conftest.py`.** Point `TMPDIR`, `WRITING_FLOW_STATE_DIR` and `WRITING_FLOW_CONFIG` into one `tempfile.mkdtemp()` sandbox before any test module loads. Pop every `WRITING_FLOW_*` and `HARNESS_KIT_*` variable first. Port the `_restore_environ` fixture from the harness-kit conftest.
- [ ] **Step 4: Write `docs/provenance.md`.** Record the source commit `c48f5e6`, the two mapping tables and the four tests left behind with the reason for each.
- [ ] **Step 5: Verify the copy.** Run a loop that compares `git show c48f5e6:<src> | sha256sum` with `sha256sum <target>` for every harness-kit row. Expected: every hash matches. Save the output to `logs/task1-hashes.log`.

### Task 2: Infrastructure modules

**Files:**
- Create: `src/writing_flow/{config,paths,runtime,phase,failopen,hookio}.py`
- Test: `tests/test_infra.py`

**Interfaces:**
- Produces, in `writing_flow.config`:
  - `env(name: str, default: str | None = None) -> str | None` reads `WRITING_FLOW_<name>`, then `HARNESS_KIT_<name>`
  - `config() -> dict`
  - `hook_config(hook_name: str) -> dict`
  - `hook_enabled(hook_name: str) -> bool`
  - `hook_verbosity(hook_name: str, default: str = "auto") -> str`
  - `retro_fix_enabled() -> bool`
  - `bypass_release(hook_name: str, content: str = "", findings: int = 0) -> str | None`
- Produces, in `writing_flow.paths`: `home() -> Path`, `claude_code_dir() -> Path`, `config_path() -> Path`, `state_dir() -> Path`, `state_override() -> Path | None`, `HARNESS_STATE_DIRS = {"claude": ".claude", "codex": ".codex"}`
- Produces, in `writing_flow.runtime`: `canonical_tool_name(name) -> str` and the `HarnessRuntime` dataclass with `name`, `project_root`, `state_dir`, `session_id`, `plugin_root`, plus `from_event(event)`, `is_claude()` and `is_codex()`
- Produces, in `writing_flow.phase`: `get_phase_file_path(state_dir: Path, session_id: str | None) -> Path` and `read_current_phase(state_dir: Path, session_id: str | None) -> dict`
- Produces, in `writing_flow.failopen`: `note_swallowed(where: str, exc: BaseException) -> None`
- Produces, in `writing_flow.hookio`: `read_hook_stdin() -> dict` and `get_project_root(hook_input: dict | None = None) -> Path`

Copy each body from its harness-kit counterpart at `c48f5e6`, then cut it to these names. `failopen.note_swallowed` appends one JSON line to `state_dir() / "swallowed.jsonl"` and never raises. `bypass_release` journals to `state_dir() / "bypasses.jsonl"`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_env_prefers_new_name(monkeypatch):
    monkeypatch.setenv("HARNESS_KIT_STE", "strict")
    monkeypatch.setenv("WRITING_FLOW_STE", "off")
    assert config.env("STE") == "off"

def test_env_falls_back_to_legacy_name(monkeypatch):
    monkeypatch.setenv("HARNESS_KIT_STE", "strict")
    assert config.env("STE") == "strict"

def test_corrupt_config_gives_defaults(tmp_path, monkeypatch):
    bad = tmp_path / "config.json"
    bad.write_text("{not json")
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(bad))
    assert config.hook_config("guard_style") == {}
    assert config.hook_enabled("guard_style") is True
    assert config.hook_verbosity("guard_style") == "auto"
    assert config.retro_fix_enabled() is True

def test_hook_disabled_by_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"hooks": {"guard_flow": {"enabled": false}}}')
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(cfg))
    assert config.hook_enabled("guard_flow") is False

def test_bypass_marker_releases_bypassable_hook():
    assert config.bypass_release("guard_style", "x [writing-flow-bypass]") is not None
    assert config.bypass_release("guard_style", "x [kit-bypass]") is not None

def test_bypass_ignored_for_other_hooks():
    assert config.bypass_release("style_check", "x [writing-flow-bypass]") is None

def test_state_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert paths.state_dir() == tmp_path

def test_unknown_phase_is_empty(tmp_path):
    assert phase.read_current_phase(tmp_path, "nosuchsession") == {}
```

- [ ] **Step 2: Run them.** Run: `python3 -m pytest tests/test_infra.py -q`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement the six modules.**
- [ ] **Step 4: Run them again.** Expected: 8 passed.

### Task 3: Rewire the library and pass its tests

**Files:**
- Modify: every module under `src/writing_flow/` from Task 1
- Test: the library tests from Task 1, such as `test_prose_rules*.py`, `test_flow_rules_chat.py`, `test_plain_rules.py`, `test_plain_state.py`, `test_rewrite_log.py`, `test_residue_*.py`

**Interfaces:**
- Consumes: every name from Task 2
- Produces: `from writing_flow import prose_rules` and the same form for every other module. Public names inside each module stay unchanged.

- [ ] **Step 1: Run the library tests.** Expected: FAIL on imports.
- [ ] **Step 2: Rewire the imports.** Use relative imports between package modules. Replace `local_kit`, `kit_paths`, `harness_runtime`, `phase_state`, `failopen` and `_hook_utils` with the Task 2 modules. Replace each `os.environ.get("HARNESS_KIT_<X>"...)` with `config.env("<X>"...)`. Change no rule logic.
- [ ] **Step 3: Change `output_style.py`.** Accept a bare name and a `writing-flow:` prefixed name. Look in the plugin's own `output-styles/` first, then in `~/.claude/output-styles/`.
- [ ] **Step 4: Change the test imports only.** Never edit an assertion. Where a test case needs an excluded module, delete only that case, and list it in `docs/provenance.md`.
- [ ] **Step 5: Run the library tests.** Expected: all pass.

### Task 4: Rewire the hooks and cut `response_audit`

**Files:**
- Modify: every file under `hooks/`
- Test: the hook tests from Task 1, plus the hook cases you port from the mixed files named below, plus `tests/test_hook_edges.py`

**Interfaces:**
- Consumes: the Task 2 and Task 3 modules
- Produces: hook scripts that run as `python3 "<root>/hooks/<name>.py"` with the event JSON on stdin. Each script inserts `Path(__file__).resolve().parents[1] / "src"` at the front of `sys.path`.

The mixed files with hook cases worth porting are `test_guard_flow.py`, `test_response_audit.py`, `test_message_display_audit.py`, `test_guard_style_gaps.py`, `test_personal_style_wired.py`, `test_flow_rules_extended.py`, `test_guard_rule_sync.py` and `test_code_comment_guard.py`. Port the cases that exercise included code. Leave the cases that need excluded modules, and list them in `docs/provenance.md`.

- [ ] **Step 1: Write `tests/test_hook_edges.py`.**

```python
def test_namespaced_style_reaches_flow_reinforce(tmp_path, monkeypatch):
    # settings.json with outputStyle "writing-flow:writing-flow"
    # flow_reinforce output names the writing-flow style and is non-empty
    ...

def test_unwritable_state_dir_fails_open(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    # run hooks/guard_style.py on a clean Write event with
    # WRITING_FLOW_STATE_DIR=blocker / "state"
    assert proc.returncode in (0, 2)
    assert "Traceback" not in proc.stderr

def test_unknown_phase_runs_grounding():
    # response_audit.check_grounded_response on an ungrounded claim
    # with phase "" returns at least one finding
    ...
```

Fill each body. Each test asserts what its comments name.
- [ ] **Step 2: Run the hook tests.** Expected: FAIL on imports.
- [ ] **Step 3: Rewire every hook's imports, as in Task 3.** Change `plain_inject.DEFAULT_RULES` to `<root>/skills/plain-mode/RULES.md`.
- [ ] **Step 4: Cut `response_audit.py`.** Delete `check_localization`, its call in `compute_findings` and the `locale_preset` import. Keep the flow gate, chat form, personal style, grounding, the background worker and the block marker.
- [ ] **Step 5: Run every test.** Run: `python3 -m pytest -q`. Expected: all pass.

### Task 5: Plugin wiring and Codex adapter

**Files:**
- Create: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `adapters/codex/hooks.json`
- Modify: `adapters/codex/run_hook.py`
- Test: `tests/test_plugin_wiring.py`

**Interfaces:**
- Consumes: the hook scripts from Task 4
- Produces: these registrations, all as shell form `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py"`

| Event | Matcher | Hooks, in order |
| --- | --- | --- |
| PreToolUse | `Write\|Edit` | `guard_style`, `guard_flow` |
| PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | `style_check`, `guard_doc_residue` |
| MessageDisplay | none | `message_display_audit` |
| SubagentStop | none | `subagent_style_audit` |
| UserPromptSubmit | none | `flow_reinforce`, `plain_tracker`, `plain_inject`, `violation_feedback` |
| Stop | none | `response_audit` |

The Codex `hooks.json` registers `guard_style` and `guard_flow` on PreToolUse, and `style_check` and `guard_doc_residue` on PostToolUse. Its matcher is `apply_patch|write_file`. `run_hook.py` resolves `ROOT` as the repo root and runs `ROOT / "hooks" / <name>.py`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_every_registered_script_exists(): ...
def test_plugin_root_is_quoted():
    for cmd in all_commands("hooks/hooks.json"):
        assert '"${CLAUDE_PLUGIN_ROOT}' in cmd
def test_violating_write_denies(): ...   # a Write with a semicolon sentence in README.md
def test_clean_write_passes(): ...       # a Write of one short STE sentence
def test_codex_adapter_runs_guard_style(): ...
```

Each event must target a file under pytest `tmp_path`. `guard_style` skips every path under `/tmp/claude-<uid>/`, so an event there always passes. The precheck confirmed both verdicts on the pinned hooks: the bad Write exits 2, and the clean Write exits 0.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the three JSON files and adjust `run_hook.py`.**
- [ ] **Step 4: Run the tests and the validator.** Run: `python3 -m pytest tests/test_plugin_wiring.py -q`, then `claude plugin validate .`. Expected: all pass, and the validator prints `Validation passed` or `Validation passed with warnings`. The one allowed warning names the root `CLAUDE.md`.

### Task 6: The CLI

**Files:**
- Create: `src/writing_flow/cli.py`
- Modify: `src/writing_flow/sweep.py`, `src/writing_flow/report.py`
- Test: `tests/test_cli.py`, `tests/fixtures/bad.md`, `tests/fixtures/good.md`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int` with three verbs.
  - `check PATH...` scans each Markdown file, or each Markdown file under each directory, with the `guard_style` and `guard_flow` rules. It prints one line per finding as `path:line: rule: message`. It returns 1 on any finding, else 0.
  - `sweep` runs the old `prose_sweep.py` behaviour.
  - `report` runs the old `flow_report.py` behaviour.

- [ ] **Step 1: Write the failing tests.**

```python
def test_check_flags_bad_fixture(capsys):
    assert cli.main(["check", "tests/fixtures/bad.md"]) == 1
    assert "bad.md:" in capsys.readouterr().out

def test_check_passes_good_fixture():
    assert cli.main(["check", "tests/fixtures/good.md"]) == 0
```

`bad.md` holds a semicolon sentence and a 40-word sentence. `good.md` holds two short STE sentences.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `cli.py`.** Reuse `guard_style` and `guard_flow` rule functions from the package. Do not copy their logic.
- [ ] **Step 4: Run them.** Expected: 2 passed. Then create a venv under `logs/`, run `<venv>/bin/pip install -e .`, and check that `<venv>/bin/writing-flow --help` prints the three verbs. System pip refuses installs on this machine.

### Task 7: Parity with harness-kit

**Files:**
- Create: `scripts/parity_check.py`, `docs/parity.md`

**Interfaces:**
- Produces: `python3 scripts/parity_check.py --source <dir>` prints `PARITY OK <n> files` and exits 0, or prints each differing verdict and exits 1.

`--source` names a directory that holds `git archive c48f5e6 hooks` output. The script loads `prose_rules`, `flow_rules`, `plain_rules` and `personal_style` from that directory in a subprocess with `-I`, and the package versions in a second subprocess. It runs each scan function over the corpus and compares the sorted findings. The corpus is every `.md` file in that archive's `docs/` plus every file under `tests/fixtures/` in this repo.

- [ ] **Step 1: Write the script.**
- [ ] **Step 2: Run it.** Extract `git -C /home/pc/harness-kit archive c48f5e6 hooks docs` into a scratch directory, then run the script on it. Expected: `PARITY OK`. Save the output to `logs/task7-parity.log`, and copy the summary into `docs/parity.md`.

### Task 8: Isolation, repo files and CI

**Files:**
- Create: `tests/test_isolation.py`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `.gitignore`, `docs/rules.md`, `docs/configuration.md`, `.github/workflows/ci.yml`

- [ ] **Step 1: Write `tests/test_isolation.py`.** It scans every `.py` and `.json` file outside `docs/` and `tests/`. It fails on `harness-kit/`, `harness_kit`, `/srv/dusk`, `/mnt/dusk`, `import local_kit` or `import kit_paths`. `docs/provenance.md` may name the source repo.
- [ ] **Step 2: Run it.** Expected: pass.
- [ ] **Step 3: Write the repo files.** `CLAUDE.md` and `GEMINI.md` hold one line, `@AGENTS.md`. `AGENTS.md` names the layout, the test command, the check command and the no-harness-kit rule. `docs/configuration.md` lists every config key and every `WRITING_FLOW_*` variable with its default. `docs/rules.md` lists every rule family that `prose_rules`, `flow_rules`, `plain_rules` and `personal_style` enforce. `README.md` covers install as a plugin, install with pip, the CLI, and the double-fire warning while harness-kit stays installed. `CHANGELOG.md` opens at `0.1.0`. `LICENSE` is MIT, 2026, Synx-x.
- [ ] **Step 4: Write `ci.yml`.** Run it on push and pull request, on Python 3.10 and 3.14. It installs the package and runs `python3 -m pytest -q`. Then it runs `writing-flow check README.md AGENTS.md docs skills rules output-styles agents`.
- [ ] **Step 5: Fix shipped docs that fail the check.** Rewrite a failing sentence so it passes and still says the same thing. Never delete a rule or an opinion to pass. Put a deliberately bad example in a code span or a code fence.
- [ ] **Step 6: Run the full gate.** Run: `python3 -m pytest -q`, then the same `writing-flow check` command. Expected: all tests pass, and the check exits 0. Save both outputs under `logs/`.

## Done line

The report ends with `DONE: <tests passed>/<tests total>, parity OK, check clean, validate <result>`.

The auditing session owns everything after that line: the audit, the commits, `gh repo create Synx-x/writing-flow --private` and the push.
