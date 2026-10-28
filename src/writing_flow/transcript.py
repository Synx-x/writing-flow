#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""Bounded transcript readers for hooks.

Session transcripts (the JSONL at `transcript_path`) grow unbounded during a
session — real ones reach tens of MB. Hooks that `read_text()` the whole file on
every UserPromptSubmit scale linearly with session length and blow their timeout
on long sessions or slow machines, after which Claude Code discards the hook's
injected context (https://code.claude.com/docs/en/hooks).

Three helpers cover every hook read pattern:

- `tail_lines`  — last N lines via a seek from EOF (for "recent tools" / "last
  model" style reads that only need the end).
- `count_tool_turns` — streamed line scan with early-exit once a threshold is hit
  (for "has the session done >= N tool turns?" gates).
- `iter_session_transcripts` — every session transcript inside a day window,
  across all project directories.

None of them loads a whole file into memory.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import paths

DEFAULT_TAIL_BYTES = 262144  # 256 KiB is far more than 200 lines of JSONL

# Claude Code slugs each session's cwd into its own directory under projects/,
# so a single pinned slug hides every session that ran elsewhere. Audited
# 2026-08-10 in hooks/session_scan.py: pinning "-home-pc" left 43 of 106
# transcripts invisible, 41% overall and 67% of the trailing 14 days.
PROJECTS_DIR = paths.claude_code_dir() / "projects"


def tail_lines(path, n, max_bytes=DEFAULT_TAIL_BYTES):
    """Return the last `n` lines of `path` without reading the whole file.

    Seeks to `max(0, size - max_bytes)` and decodes only that window. When the
    window starts mid-file the first (possibly partial) line is dropped so callers
    never see a truncated record. Returns [] on any error or missing file.
    """
    try:
        p = Path(path)
        if not p.exists():
            return []
        size = p.stat().st_size
        with p.open("rb") as fh:
            seeked = size > max_bytes
            if seeked:
                fh.seek(size - max_bytes)
            data = fh.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if seeked and lines:
            # First line may be a partial record from the seek boundary.
            lines = lines[1:]
        return lines[-n:] if n else lines
    except Exception:
        return []


def user_prose(record):
    """Text the user actually typed, or None for every other record.

    Record type alone is not enough. Tool results are stored as `type: "user"`
    records too, so a shell command that merely prints text reads back as a
    user prompt. Content shape decides. Real prompts carry a string or text
    blocks, and hook injections carry `isMeta`. Same logic as `_user_prose` in
    scripts/herdr_model_router.py, which documents the
    shape against a sampled live transcript.

    Two more records carry no flag a hook can trust. A compaction summary
    carries `isCompactSummary`, and a background agent's result arrives as a
    `<task-notification>` envelope. On 2026-09-23 response_audit read a summary
    as the prompt, and its "sentences of 20 words or fewer" capped the reply.
    """
    if not isinstance(record, dict):
        return None
    if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary"):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if not parts:
            return None
        text = "\n".join(parts)
    else:
        return None
    if text.lstrip().startswith(_INJECTED_ENVELOPES):
        return None
    return text


def current_turn_assistant_text(path, max_lines=400):
    """Assistant text written since the latest genuine user prompt.

    Reads a bounded tail, so a long session costs the same as a short one.
    A turn longer than the tail window returns only its newest part.
    """
    parts = []
    for line in reversed(tail_lines(path, max_lines)):
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if user_prose(rec) is not None:
            break
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(reversed(parts))


# Envelopes Claude Code writes as user prose on the agent's behalf. The 60 most
# recent transcripts on this machine held 156 of these on 2026-09-23.
_INJECTED_ENVELOPES = ("<task-notification",)


# Claude Code writes slash commands, their output and `!` shell runs as user
# prose. None of them is a prompt for the model.
_COMMAND_ENVELOPES = ("<command-", "<local-command-", "<bash-")


def typed_prompt(record):
    """A prompt sent to the model, or None. scripts/statusline.py mirrors this rule."""
    prose = user_prose(record)
    if not prose or prose.lstrip().startswith(_COMMAND_ENVELOPES):
        return None
    return prose


def session_shape(path, max_tools=40):
    """Summarize one transcript: session id, first real prompt, tool sequence.

    Streams the file. Returns None when the transcript holds no user prose at
    all, which is what an empty or not-yet-flushed transcript looks like.
    A zero count here means "nothing to read", never "routine session" — the
    review log records a real case where that conflation produced a false
    no-action for a session with 281 lines of work.
    """
    try:
        p = Path(path)
        if not p.exists():
            return None
        session_id = ""
        first_prompt = None
        started = None
        tools = []
        user_turns = 0
        typed_prompt = None
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(rec, dict):
                    continue
                if not session_id and rec.get("sessionId"):
                    session_id = str(rec["sessionId"])
                prose = user_prose(rec)
                if prose and prose.strip():
                    user_turns += 1
                    if first_prompt is None:
                        first_prompt = prose.strip()
                        started = str(rec.get("timestamp", ""))[:10]
                    if typed_prompt is None and not prose.lstrip().startswith(_COMMAND_ENVELOPES):
                        typed_prompt = prose.strip()
                if len(tools) < max_tools:
                    content = (rec.get("message") or {}).get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                name = block.get("name")
                                if name:
                                    tools.append(str(name))
        if first_prompt is None:
            return None
        return {
            "path": str(p),
            "session_id": session_id,
            "first_prompt": first_prompt,
            "date": started or date.fromtimestamp(p.stat().st_mtime).isoformat(),
            "tools": tools,
            "user_turns": user_turns,
            "typed_prompt": typed_prompt,
        }
    except Exception:
        return None


# A transcript under projects/ is not necessarily a person working. Headless
# `claude -p` calls from hooks, scheduled agents, and dispatched subagents all
# land here with the same shape. Measured against this host's corpus on
# 2026-08-14: of 112 transcripts in a 60-day window, 24 were slash-command
# wrappers and 16 had no tool calls at all. Three of those 16 were the
# identical string 'Reply with only: {"complexity":"high"}', a latency
# benchmark run minutes earlier, which any frequency count would have promoted
# to a high-confidence repeated pattern.
MACHINE_PROMPT_MARKERS = (
    "reply with only",
    "return only",
    "you are running as",
    "you break a tie",
    "you are a detached",
    "you are the harness-kit",
    "you are a background",
    "independent read-only review",
    "return only a single json",
    # Compaction rewrites the first user record into a summary envelope, so the
    # person's actual opening request is no longer the first prose in the file.
    "this session is being continued from a previous conversation",
)


def is_machine_session(shape):
    """True when a transcript is a tool's own invocation, not a person working.

    Three structural tests, cheapest first. A command wrapper is Claude Code's
    own slash-command envelope. No tool calls means no work happened. A prompt
    that opens by addressing a model is a dispatch, not a request.

    A wrapper alone does not decide it. A person often opens with /clear or
    /model and then types the request. Measured on 2026-09-23: 20 of the last
    400 transcripts on this host opened with /clear or /model, and one of
    those held 9,620 edited lines. So a wrapper counts as machine-made only
    when nothing typed follows it, and otherwise the typed prompt is tested.
    """
    if not shape:
        return True
    prompt = shape.get("first_prompt", "")
    if prompt.startswith("<command-") or "<command-name>" in prompt[:200]:
        prompt = shape.get("typed_prompt") or ""
        if not prompt:
            return True
    if not shape.get("tools"):
        return True
    lowered = prompt[:200].lower()
    return any(marker in lowered for marker in MACHINE_PROMPT_MARKERS)


def iter_session_transcripts(days=30, projects_dir=None):
    """Yield `session_shape` dicts for transcripts modified in the last `days`.

    Walks every project directory, not one of them, for the reason recorded on
    PROJECTS_DIR above. Newest first. Transcripts that yield no user prose are
    skipped rather than reported as empty sessions.
    """
    root = Path(projects_dir) if projects_dir else PROJECTS_DIR
    if not root.exists():
        return []
    cutoff = date.today() - timedelta(days=days)
    paths = []
    for jl in root.glob("*/*.jsonl"):
        try:
            mtime = jl.stat().st_mtime
        except OSError:
            continue
        if date.fromtimestamp(mtime) < cutoff:
            continue
        paths.append((mtime, jl))
    shapes = []
    for _, jl in sorted(paths, reverse=True):
        shape = session_shape(jl)
        if shape is not None:
            shapes.append(shape)
    return shapes


def count_tool_turns(path, tool_names, threshold=None):
    """Count lines containing a `"name":"<tool>"` marker, streaming the file.

    Iterates line by line (buffered, not a full `read_text()`) and returns early
    once `threshold` is reached, so a "has this session done >= N tool turns?"
    gate on a huge transcript stops near the top instead of scanning it all.
    Returns 0 on any error or missing file. Match logic mirrors the serialized
    JSONL shape (no spaces around the colon).
    """
    try:
        p = Path(path)
        if not p.exists():
            return 0
        markers = tuple(f'"name":"{name}"' for name in tool_names)
        n = 0
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for marker in markers:
                    if marker in line:
                        n += 1
                        break
                if threshold is not None and n >= threshold:
                    return n
        return n
    except Exception:
        return 0


def count_browser_turns(path, threshold=None):
    """Count browser-automation tool turns, streaming the file.

    Unlike count_tool_turns, this isn't one exact tool name: it's any
    mcp__claude-in-chrome__* tool call, plus any Bash call whose command
    invokes chrome-agent or agent-browser. A Bash line's "name" marker is
    generic ("Bash"), so detection here matches on the command substrings
    instead, applied to the same raw line count_tool_turns already scans.
    Returns 0 on any error or missing file.
    """
    return sum(1 for _ in iter_browser_events(path, threshold=threshold))


def _browser_driver(tool_name: str, command: str = "") -> str | None:
    """Return a driver name for an actual browser tool invocation.

    This deliberately examines parsed tool-use records, never arbitrary prose.
    CLI detection is restricted to a Bash command's executable tokens so a
    source file or explanation mentioning a driver is not activity.
    """
    name = str(tool_name or "")
    lowered = name.lower()
    if lowered.startswith("mcp__claude-in-chrome__"):
        return "claude-in-chrome"
    if lowered.startswith("mcp__agent-browser__"):
        return "agent-browser"
    if lowered.startswith("mcp__playwright__") or "playwright" in lowered:
        return "playwright"
    if lowered.startswith("mcp__chrome-agent__"):
        return "chrome-agent"
    if name in {"Bash", "shell", "exec_command", "command_execution"}:
        import re
        # Only an executable position counts. `echo agent-browser` and a
        # quoted source/example mention are ordinary shell activity.
        executable = r"(?:^|[;&|]\s*)(?:env\s+)?(?:npx\s+)?"
        if re.search(executable + r"agent-browser(?:\s|$)", command):
            return "agent-browser"
        if re.search(executable + r"chrome-agent(?:\s|$)", command):
            return "chrome-agent"
        if re.search(executable + r"playwright(?:\s|$)", command):
            return "playwright"
    return None


def browser_events_in(record):
    """Browser tool events in one parsed transcript record, without the line number."""
    blocks = []
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        blocks.extend(
            block for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
    # Codex JSONL stores model calls as response_item records,
    # with the actual call under payload. Keep this extraction
    # local to browser counting so the Claude transcript contract
    # remains unchanged.
    payload = record.get("payload")
    if isinstance(payload, dict) and payload.get("type") in {"function_call", "custom_tool_call"}:
        blocks.append(payload)
    item = record.get("item")
    if isinstance(item, dict) and item.get("type") in {"function_call", "custom_tool_call"}:
        blocks.append(item)
    for block in blocks:
        name = str(block.get("name") or block.get("tool_name") or "")
        tool_input = block.get("input") or block.get("arguments") or block.get("parameters") or {}
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        elif tool_input:
            command = str(tool_input)
        driver = _browser_driver(name, command)
        if not driver:
            continue
        yield {
            "driver": driver,
            "tool_name": name,
            "command": command,
            "timestamp": record.get("timestamp", ""),
        }


def iter_browser_events(path, threshold=None):
    """Yield parsed browser tool events from a JSONL transcript.

    The iterator accepts compact or spaced JSON and tolerates malformed lines.
    Each yielded value is a small record with the driver, tool name, command,
    timestamp, and source line. It never treats assistant prose or tool-result
    text as a browser operation.
    """
    try:
        p = Path(path)
        if not p.exists():
            return
        yielded = 0
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line_number, raw in enumerate(fh, 1):
                try:
                    record = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                for event in browser_events_in(record):
                    yielded += 1
                    yield {**event, "line": line_number}
                    if threshold is not None and yielded >= threshold:
                        return
    except Exception:
        return


# A correction that means the user rejected what the agent did. A loose word
# list ("instead", "should be", "don't") matched ordinary prompts, so nearly
# every session counted as corrected.
_STRICT_CORRECTION = re.compile(
    r"^\s*(?:no|nope|wrong|revert|undo|stop)\b"
    r"|\bthat'?s (?:wrong|not (?:it|right|what i))\b"
    r"|\bnot what i (?:asked|meant|wanted)\b|\byou broke\b"
    r"|\bstill (?:broken|failing|wrong)\b",
    re.I,
)
_EDIT_TOOLS = ("Edit", "Write", "MultiEdit")


def _tool_uses(record):
    """tool_use blocks of one real assistant record."""
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return []
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def _edited_lines(block) -> int:
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return 0
    if block.get("name") == "Write":
        return len(str(inp.get("content", "")).splitlines())
    edits = inp.get("edits") if block.get("name") == "MultiEdit" else [inp]
    return sum(
        max(len(str(e.get("new_string", "")).splitlines()), len(str(e.get("old_string", "")).splitlines()))
        for e in edits or [] if isinstance(e, dict)
    )


def session_work(transcript_path) -> dict:
    """What a session did: files_changed, edit_lines, tool_turns, corrections, files.

    Reads real Claude Code records, where tool calls sit in
    {"type": "assistant", "message": {"content": [{"type": "tool_use", ...}]}}.
    A first version read {"type": "toolCall"} and {"role": "assistant"}, shapes
    no real transcript has, so it saw no edits in any session.
    """
    work = {"files_changed": 0, "edit_lines": 0, "tool_turns": 0, "corrections": 0, "files": []}
    files = set()
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
                prose = user_prose(rec)
                if prose and _STRICT_CORRECTION.search(prose):
                    work["corrections"] += 1
                for block in _tool_uses(rec):
                    work["tool_turns"] += 1
                    if block.get("name") not in _EDIT_TOOLS:
                        continue
                    path = str((block.get("input") or {}).get("file_path", "") or "")
                    if path:
                        files.add(path.replace("\\", "/"))
                    work["edit_lines"] += _edited_lines(block)
    except (OSError, ValueError):
        pass
    work["files"] = sorted(files)
    work["files_changed"] = len(files)
    return work
