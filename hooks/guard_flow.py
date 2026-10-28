#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""PreToolUse (Write|Edit): reader-expectation checks on prose files.

Companion to guard_style. That hook checks vocabulary and ASD-STE100 form.
This one checks information flow with the rules in lib/flow_rules.py:
long runway before the verb, topic drift across a paragraph, new material
in the topic slot, a paragraph with no index sentence, a previewed term
that never returns, and a vague heading.

Prose files only (.md .txt .rst .mdx .adoc .org). Code comments are skipped
on purpose. Comment fragments rarely form paragraphs, so the paragraph rules
would only add noise there.

Mode comes from HARNESS_KIT_FLOW, then local config, then the default:
  off     do nothing
  warn    emit hookSpecificOutput.additionalContext and exit 0 (default)
  strict  print the findings to stderr and exit 2, which blocks the write

The default is warn because every rule here is a heuristic over surface
syntax. A heuristic that blocks trains the model to route around it.

Strict mode carries three escapes, so a wrong finding costs one line rather
than a rewrite of prose that was already right:

  exempt marker   a file states its shape is mandated elsewhere, by carrying
                  `flow-exempt: <why>` anywhere in its content
  override file   the model writes a reason to
                  <state>/flow-override-<session id>-<target key>, which passes
                  one write and is then consumed
  block cap       after `block_cap` blocks on the same file, the next write
                  goes through and the log records `capped`

The cap exists because a rule the model cannot satisfy is a loop, not a gate.
Confirmed live on 2026-09-10: a subagent took five blocks on one SKILL.md,
every block naming long_runway, and it exited without ever writing the file.

Both escapes land in guard_flow_log.jsonl with `outcome`, so the override count
is the false-positive rate. Config keys, all under hooks.guard_flow:

  mode            off | warn | strict
  kinds           which rules run, defaults to every kind
  exempted_paths  substrings of paths to leave alone
  exempt_marker   the in-file token, defaults to flow-exempt
  allow_override  false removes the override file escape
  block_cap       consecutive blocks on one file before the write passes,
                  defaults to 2

Escape hatch for a whole session: HARNESS_KIT_SKIP_FLOW_CHECK=1.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config as wf_config
from writing_flow import flow_rules
from writing_flow import flow_state
from writing_flow import paths as kit_paths
from writing_flow.claude_temp import is_machine_path

try:
    from writing_flow import config as local_kit
except Exception:
    local_kit = None

STATE_DIR = kit_paths.state_dir()
LOG = STATE_DIR / "guard_flow_log.jsonl"

PROSE_EXTS = (".md", ".txt", ".rst", ".mdx", ".adoc", ".org")

# Paths that describe the writing rules themselves. They quote bad passages
# as examples and must not be judged on them.
SKIP_PATTERNS = (
    "/CLAUDE.md",
    "/rules/",
    "/avoid-ai-writing/",
    "/technical-english/",
    "/output-styles/",
    "/hooks/guard_style",
    "/hooks/guard_flow",
    "/hooks/style_check",
    "/hooks/lib/prose_rules",
    "/hooks/lib/flow_rules",
    "response_audit",
    "fixtures",
)

MAX_SHOWN = 8


def _config() -> dict:
    if local_kit is None:
        return {}
    try:
        return local_kit.hook_config("guard_flow") or {}
    except Exception:
        return {}


def mode(cfg: dict) -> str:
    val = (wf_config.env("FLOW") or "").strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    val = str(cfg.get("mode", "")).strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    return "warn"


def in_vendored_tree(path: str) -> bool:
    current = Path(path).resolve().parent
    for _ in range(12):
        if (current / "NOTICE").exists():
            return True
        parent = current.parent
        if parent == current:
            break
        current = parent
    return False


def should_skip(path: str, cfg: dict) -> bool:
    if Path(path).suffix.lower() not in PROSE_EXTS:
        return True
    # SKIP_PATTERNS are written with forward slashes, so a Windows path like
    # C:\...\.claude\output-styles\flow.md matched none of them and the guard
    # judged the file that documents the rules against those rules.
    norm = str(path).replace("\\", "/")
    for pat in SKIP_PATTERNS:
        if pat in norm:
            return True
    for pat in cfg.get("exempted_paths", []):
        if str(pat).replace("\\", "/") in norm:
            return True
    return in_vendored_tree(path)


def render(findings: list, path: str) -> list:
    lines = []
    for f in findings[:MAX_SHOWN]:
        where = f"line {f['line']}: " if f.get("line") else ""
        lines.append(f"  {where}{f['label']}")
    if len(findings) > MAX_SHOWN:
        lines.append(f"  ... {len(findings) - MAX_SHOWN} more")
    lines.append(
        "Fix the structure, not the words: short familiar subject first, verb within "
        "eight words, one anchor named in each paragraph's first sentence, previewed "
        "terms repeated verbatim."
    )
    return lines


def log(path: str, current_mode: str, findings: list,
        outcome: str = "", reason: str = "") -> None:
    """Append one record per scan.

    `outcome` is what the finding led to, which is the whole point of the log.
    A count of findings measures how loud the rules are. A count of overrides
    measures how often they were wrong, and only the second number decides
    whether strict mode is worth keeping.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        counts = {}
        for f in findings:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "mode": current_mode,
            "counts": counts,
        }
        if outcome:
            record["outcome"] = outcome
        if reason:
            record["reason"] = reason[:400]
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def exempt_marker(cfg: dict) -> str:
    """Token a file carries to declare its shape is mandated elsewhere.

    A retrospective entry, an issue template and a commit body all have a fixed
    form somebody else owns. Flow rules judge free prose, so a file carrying
    this marker opts out and states why on the same line.
    """
    return str(cfg.get("exempt_marker") or "flow-exempt")


def override_path(session_id: str, target: str = "") -> Path:
    """One escape slot per session and per target file.

    Keyed on the session alone, two subagents writing different files drew
    from the same slot. The first to spend it left the second with none.
    """
    return flow_state.override_path(session_id, target)


def take_override(session_id: str, cfg: dict, target: str = "") -> str | None:
    """Consume a one-shot override, returning its reason.

    The model writes this file when it judges a finding wrong for the passage in
    hand. Consuming it here makes the escape single-use, so an override covers
    one write rather than opening the gate for the session. Set
    `allow_override: false` in config to remove the escape entirely.
    """
    return flow_state.take_override(
        session_id, target, bool(cfg.get("allow_override", True))
    )


def block_cap(cfg: dict) -> int:
    """Consecutive blocks on one file before the write is let through.

    A rule the model cannot satisfy holds the file hostage instead of
    improving it. Two rewrites carry the signal, so the third write passes
    and the log records `capped` rather than a fourth `blocked`.
    """
    try:
        return max(0, int(cfg.get("block_cap", 2)))
    except (TypeError, ValueError):
        return 2


def main():
    if wf_config.env("SKIP_FLOW_CHECK") == "1":
        sys.exit(0)
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)
    if is_machine_path(str((data.get("tool_input") or {}).get("file_path", ""))):
        sys.exit(0)

    cfg = _config()
    if local_kit is not None:
        try:
            if not local_kit.hook_enabled("guard_flow"):
                sys.exit(0)
        except Exception:
            pass
    current_mode = mode(cfg)
    if current_mode == "off":
        sys.exit(0)

    tin = data.get("tool_input") or {}
    path = tin.get("file_path", "")
    if not path or should_skip(path, cfg):
        sys.exit(0)

    content = tin.get("content") if data["tool_name"] == "Write" else tin.get("new_string", "")
    if not content or not content.strip():
        sys.exit(0)

    marker = exempt_marker(cfg)
    if marker and marker in content:
        log(path, current_mode, [], outcome="exempt", reason=marker)
        sys.exit(0)

    session_id = str(data.get("session_id", ""))
    allow_override = bool(cfg.get("allow_override", True))

    kinds = tuple(cfg.get("kinds") or flow_rules.ALL_KINDS)
    try:
        findings = flow_rules.scan_flow(content, kinds=kinds)
    except Exception:
        sys.exit(0)  # a linter bug must never break a write
    if not findings:
        # A clean write settles this file. Drop both pieces of carried state,
        # so a stale count cannot cap a later real block and an unspent reason
        # cannot forgive one.
        flow_state.reset_block_count(session_id, path)
        flow_state.discard_override(session_id, path, allow_override)
        sys.exit(0)

    body = render(findings, path)
    name = Path(path).name

    if current_mode == "strict":
        reason = take_override(session_id, cfg, path)
        if reason is not None:
            flow_state.reset_block_count(session_id, path)
            log(path, current_mode, findings, outcome="override", reason=reason)
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        f"FLOW OVERRIDE accepted on {name}: {reason}\n"
                        "Recorded as a claimed false positive in guard_flow_log.jsonl."
                    ),
                }
            }))
            sys.exit(0)

        blocks = flow_state.read_block_count(session_id, path)
        cap = block_cap(cfg)
        if blocks >= cap:
            flow_state.reset_block_count(session_id, path)
            log(path, current_mode, findings, outcome="capped",
                reason=f"{blocks} consecutive blocks")
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        f"FLOW CAP reached on {name} after {blocks} blocks. This write "
                        "goes through unchanged. Findings still standing:\n"
                        + "\n".join(body)
                    ),
                }
            }))
            sys.exit(0)

        flow_state.write_block_count(session_id, blocks + 1, path)
        log(path, current_mode, findings, outcome="blocked")
        print(f"FLOW VIOLATION blocked by guard_flow.py in {name}", file=sys.stderr)
        print("\n".join(body), file=sys.stderr)
        print(
            "Rewrite the passage first. Two escapes exist when the shape is not yours "
            "to change:\n"
            f"  1. Format mandated elsewhere: put `{marker}: <why>` in the file itself.\n"
            f"  2. One-off judgement call: write the reason to "
            f"{override_path(session_id, path)} then retry the write once.\n"
            "Both are logged as claimed false positives, which is how the rules get "
            f"tuned. After {cap} blocks on this file the next write passes anyway. "
            "HARNESS_KIT_FLOW=warn downgrades this to a notice.",
            file=sys.stderr,
        )
        if local_kit and local_kit.bypass_release("guard_flow"):
            print("  (kit bypass active -- reported, not enforced)",
                  file=sys.stderr)
            sys.exit(0)
        sys.exit(2)

    log(path, current_mode, findings, outcome="notice")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"FLOW NOTICE from guard_flow.py (advisory) on {name}:\n" + "\n".join(body)
            ),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
