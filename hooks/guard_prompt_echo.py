#!/usr/bin/env python3
"""Claude Code PreToolUse guard for prompt echoes and document narration."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config, guard_format, paths, prompt_echo_state
from writing_flow.edit_scope import blank_unchanged, changed_lines
from writing_flow.prose_rules import extract_comments_and_strings, grammar_for, PROSE_ROUTE
from writing_flow.prompt_echo import find_echo, find_narration, guidance_clauses
from writing_flow.runtime import HarnessRuntime
from writing_flow.transcript import tail_lines, typed_prompt
from hooks.guard_style import SELF_REF_PATTERNS

_LOG = paths.state_dir() / "guard_prompt_echo_log.jsonl"
_INSTRUCTION_NAMES = {"claude.md", "agents.md", "gemini.md", "brief.md"}
_INSTRUCTION_DIRS = ("/agents/", "/skills/", "/commands/", "/codex_delegate/runs/", "/agent_briefs/")


def prompt_history(transcript_path: str) -> list[str]:
    prompts = []
    for raw in reversed(tail_lines(transcript_path, 3000)):
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        prompt = typed_prompt(record)
        if not prompt:
            continue
        lower = prompt.lstrip().lower()
        if lower.startswith(("system reminder", "<task-notification", "this session is being continued from a previous conversation")):
            continue
        if lower.startswith(("stop hook feedback:", "writing-flow[", "response audit")):
            continue
        prompts.append(prompt)
        if len(prompts) == 3:
            break
    return list(reversed(prompts))


def _instruction_path(path: str, cfg: dict) -> bool:
    norm = "/" + str(Path(path).resolve()).replace("\\", "/").lstrip("/")
    if Path(path).name.lower() in _INSTRUCTION_NAMES:
        return True
    if any(part in norm.lower() for part in _INSTRUCTION_DIRS):
        return True
    if any(pattern.replace("\\", "/") in norm for pattern in SELF_REF_PATTERNS):
        return True
    return any(str(item).replace("\\", "/").lower() in norm.lower() for item in cfg.get("exempt_paths", []))


def _log(path: str, outcome: str, count: int = 0, reason: str = "") -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        item = {"time": datetime.now(timezone.utc).isoformat(), "path": path,
                "outcome": outcome, "findings": count}
        if reason:
            item["reason"] = reason[:400]
        with _LOG.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _target_text(tool: str, tin: dict, path: str) -> str:
    if tool == "Write":
        content = str(tin.get("content") or "")
    elif tool == "Edit":
        content = str(tin.get("new_string") or "")
        content = blank_unchanged(content, changed_lines(str(tin.get("old_string") or ""), content))
    else:
        edits = tin.get("edits") or []
        content = "\n".join(str(item.get("new_string") or "") for item in edits if isinstance(item, dict))
    family = grammar_for(path, content)
    if family is not None and family != PROSE_ROUTE:
        return extract_comments_and_strings(content, path)
    return content


def scan_event(event: dict) -> tuple[str, list[dict], list[dict], dict]:
    tool = event.get("tool_name")
    tin = event.get("tool_input") or {}
    path = str(tin.get("file_path") or "")
    cfg = config.hook_config("guard_prompt_echo")
    if not path or _instruction_path(path, cfg):
        return path, [], [], {"exempt": True}
    runtime = HarnessRuntime.from_event(event)
    if not runtime.is_claude():
        return path, [], [], {"exempt": True, "reason": "Claude Code only"}
    text = _target_text(str(tool), tin, path)
    prompts = prompt_history(str(event.get("transcript_path") or ""))
    clauses = guidance_clauses(prompts)
    echoes = find_echo(text, clauses)
    narration = find_narration(text)
    return path, echoes, narration, {"session_id": runtime.session_id, "text": text}


def main() -> None:
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        return
    if not isinstance(event, dict) or event.get("tool_name") not in {"Write", "Edit", "MultiEdit"}:
        return
    path, echoes, narration, meta = scan_event(event)
    if meta.get("exempt"):
        _log(path, "exempt", reason=meta.get("reason", "instruction or self-reference path"))
        return
    sure = [item for item in echoes if item["sure"]] + narration
    advisory = [item for item in echoes if not item["sure"]]
    sid = meta["session_id"]
    override_file = prompt_echo_state.override_path(sid, path)
    if sure:
        reason = prompt_echo_state.take_override(sid, path)
        if reason is not None:
            _log(path, "waive", len(sure), reason)
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": f"Prompt-echo waiver accepted for this write: {reason}"}}))
            return
        items = []
        for finding in sure:
            if "clause" in finding:
                label = f"line {finding['line']}: echoes {finding['kind']} guidance '{finding['clause']}' in: {finding['sentence']}"
            else:
                label = f"line {finding['line']}: {finding['rule']} in: {finding['sentence']}"
            items.append((label, "rewrite as reader-facing content; remove the prompt narration"))
        advice = [f"advisory echo: {item['sentence']} (matches '{item['clause']}')" for item in advisory]
        rendered = guard_format.render("echo", guard_format.short_path(path), items,
                                       advice=advice,
                                       notes=[f"If this wording must stay for reader context, write a one-line reason to {override_file}; the next write to this target passes once."])
        print(rendered, file=sys.stderr)
        _log(path, "block", len(sure))
        raise SystemExit(2)
    _log(path, "pass", len(advisory))
    if advisory:
        print(guard_format.render("echo", guard_format.short_path(path), [],
                                  advice=[f"possible prompt echo: {item['sentence']} (matches '{item['clause']}')" for item in advisory],
                                  stage="notice"), file=sys.stderr)


if __name__ == "__main__":
    main()
