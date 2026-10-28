#!/usr/bin/env python3
# @schema-version: 1
# @portable: true
"""
SubagentStop hook: audit subagent final output for prose and flow rule violations.

Reads the subagent transcript from the event payload, extracts the final assistant
message, and runs prose_rules.scan and flow_rules.scan_flow on it. Prose findings
are non-blocking (notice). Flow findings block (exit 2) by default, matching the
parent session's response_audit contract. Respects config for flow mode and override.

Best-effort: never errors the event. If transcript read fails, silently skips.

issue #4: a subagent normally ends at SubagentStop, so this hook's own note is
the last thing in its context until a caller resumes it later via SendMessage.
A reproduction on 1.29.24 matched the non-blocking note's own vocabulary
almost verbatim: asked to resend its findings, the subagent instead described
"a non-blocking style notice" -- it read the stale note as the live subject of
the new turn. Both messages below now say plainly that they are closed and
carry no action, so a later resume has nothing ambiguous to misread.

The closure wording was not enough. Live run v60 on 2026-09-23: Claude Code
hands a SubagentStop additionalContext back to the finished subagent as a new
turn. The subagent answered "Understood, no action needed on that note", and
that reply replaced its function list as the result the parent received. It
happened on both of its runs, so the parent gave up and read the files itself.
The non-blocking findings now go to a journal under the state dir instead.

The blocking path went the same way. Issue #53 counted 18 stranded subagent
returns, and its evidence is a subagent answering a flow block with "The
report I posted earlier in this conversation is final" instead of the report.
A subagent's prose style is never worth its deliverable, and the parent's own
reply is audited before the user reads it. Flow findings are journaled too.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow import config as wf_config

try:
    from writing_flow.prose_rules import scan as scan_prose, STE_FLAVORED, ste_mode
except ImportError:
    def scan_prose(text, kinds=None, **_kwargs):
        return []
    STE_FLAVORED = ()
    def ste_mode():
        return "default"

try:
    from writing_flow import flow_rules
except ImportError:
    flow_rules = None

try:
    from writing_flow import config as local_kit
except ImportError:
    local_kit = None

try:
    from writing_flow import paths as kit_paths
except ImportError:
    kit_paths = None


def record_findings(data: dict, prose_findings: list, soft_flow: list) -> None:
    """Journal non-blocking findings. Nothing reaches the subagent's context."""
    if kit_paths is None:
        return
    try:
        import datetime
        path = kit_paths.state_dir() / "subagent_style_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        kinds = {}
        for finding in prose_findings:
            kinds[finding.get("kind", "prose")] = kinds.get(finding.get("kind", "prose"), 0) + 1
        if soft_flow:
            kinds["reader_flow"] = len(soft_flow)
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "session_id": data.get("session_id", ""),
            "agent_id": data.get("agent_id", ""),
            "agent_type": data.get("agent_type", ""),
            "kinds": kinds,
            "samples": [f.get("label", "") for f in prose_findings[:3]] + soft_flow[:2],
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    except Exception:
        pass


def get_subagent_final_text(transcript_path: str) -> str:
    """Extract text from the last assistant message in a subagent transcript JSONL.

    Mirror of response_audit.py's get_last_assistant_text.
    """
    last_text = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                parts = []
                for block in rec.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if t:
                            parts.append(t)
                if parts:
                    last_text = "\n".join(parts)
    except OSError:
        pass
    return last_text


def subagent_flow_mode() -> str:
    """How hard flow rules push on subagent output.

    Default is strict (block). Config: hooks.subagent_style_audit.flow_mode,
    one of off, warn, strict. Env override: HARNESS_KIT_SUBAGENT_FLOW.
    """
    val = (wf_config.env("SUBAGENT_FLOW") or "").strip().lower()
    if val in ("off", "warn", "strict"):
        return val
    if local_kit is None:
        return "strict"
    try:
        cfg = local_kit.hook_config("subagent_style_audit") or {}
    except Exception:
        return "strict"
    val = str(cfg.get("flow_mode", "")).strip().lower()
    return val if val in ("off", "warn", "strict") else "strict"


def _flow_cfg() -> dict:
    if local_kit is None:
        return {}
    try:
        return local_kit.hook_config("subagent_style_audit") or {}
    except Exception:
        return {}


def check_subagent_flow(text: str, session_id: str = "", target: str = "") -> list[tuple[str, str]]:
    """Reader-flow findings on subagent output, severity set by mode."""
    mode = subagent_flow_mode()
    if mode == "off" or flow_rules is None or not text:
        return []
    cfg = _flow_cfg()
    kinds = tuple(cfg.get("flow_kinds") or flow_rules.ALL_KINDS)
    try:
        findings = flow_rules.scan_flow(text, kinds=kinds)
    except Exception:
        return []
    if mode == "strict":
        return [("HARD", f"Reader flow: {f['label']}") for f in findings[:6]]
    return [("SOFT", f['label']) for f in findings[:6]]


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    transcript_path = data.get("agent_transcript_path", "")
    if not transcript_path or not os.path.isfile(transcript_path):
        sys.exit(0)

    session_id = data.get("session_id", "")
    target = transcript_path

    text = get_subagent_final_text(transcript_path)
    if not text or len(text) < 20:
        sys.exit(0)

    prose_findings = []
    kinds = ("ai_ism", "tier1", "em_dash", "residue")
    if ste_mode() != "off":
        kinds = kinds + STE_FLAVORED
    prose_findings = scan_prose(text, kinds=kinds)

    flow_findings = check_subagent_flow(text, session_id, target)

    # Every flow finding is journaled, HARD or SOFT. See the module docstring:
    # a block made the subagent defend its report instead of resending it.
    soft_flow = [d for _severity, d in flow_findings]

    if prose_findings or soft_flow:
        # Journal only. See the module docstring: a SubagentStop note reopens
        # the finished subagent and its reply replaces the deliverable.
        record_findings(data, prose_findings, soft_flow)

    sys.exit(0)


if __name__ == "__main__":
    main()
