#!/usr/bin/env python3
"""Run isolated raw vs writing-flow Claude Code sessions."""

from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

from ab_metrics import count_hook_blocks


REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = Path(
    "/home/pc/.claude/state/codex_delegate/runs/"
    "592abff5-1f66-4d54-929a-3130b0e8d778/"
    "20261028-072840-run-the-raw-vs-writing-flow-a-b-and-build-"
)
PLUGIN_DIR = Path("/home/pc/dev/writing-flow")
STYLE_CANDIDATES = ("writing-flow:writing-flow", "writing-flow")
PASSTHROUGH_ENV = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR")
ARMS = ("raw", "plugin")


def _read_prompts(path: Path) -> list[dict[str, str]]:
    prompts = json.loads(path.read_text(encoding="utf-8"))
    if len(prompts) != 5:
        raise ValueError(f"Expected exactly five prompts, got {len(prompts)}")
    return prompts


def _event_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _init_event(records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if record.get("type") == "system" and record.get("subtype") == "init":
            return record
    raise RuntimeError("Claude stream has no system init event")


def _final_result(records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in reversed(records):
        if record.get("type") == "result":
            return record
    raise RuntimeError("Claude stream has no result event")


def _hook_counts(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for record in records:
        subtype = str(record.get("subtype", ""))
        if "hook" not in str(record.get("type", "")).lower() and subtype not in {"hook_started", "hook_response"}:
            continue
        payloads = [record]
        payloads.extend(value for value in record.values() if isinstance(value, dict))
        for payload in payloads:
            hook = payload.get("hook_name") or payload.get("hookName") or payload.get("name")
            decision = payload.get("decision") or payload.get("hook_decision") or payload.get("outcome") or subtype or "unknown"
            if hook:
                bucket = counts.setdefault(str(hook), {})
                bucket[str(decision)] = bucket.get(str(decision), 0) + 1
                break
    return counts


def _writing_flow_hook_evidence(records: list[dict[str, Any]]) -> bool:
    return any(
        record.get("subtype") == "hook_response"
        and "FLOW CHECK" in str(record.get("output", ""))
        for record in records
    )


def _strict_guard_flow_evidence(records: list[dict[str, Any]]) -> bool:
    return any(
        record.get("subtype") == "hook_response"
        and "guard_flow.py" in str(record.get("stderr", ""))
        and "blocked" in str(record.get("stderr", "")).lower()
        for record in records
    )


def _fresh_dirs(arm: str) -> tuple[Path, Path, Path | None]:
    config_dir = Path(tempfile.mkdtemp(prefix="writing-flow-ab-config-"))
    os.chmod(config_dir, 0o700)
    project_dir = Path(tempfile.mkdtemp(prefix="writing-flow-ab-project-"))
    hook_home = Path(tempfile.mkdtemp(prefix="writing-flow-ab-home-")) if arm == "plugin" else None
    credentials = Path("/home/pc/.claude/.credentials.json")
    if not credentials.is_file():
        raise FileNotFoundError("Claude credentials file is not present")
    shutil.copyfile(credentials, config_dir / ".credentials.json")
    if hook_home:
        settings_dir = hook_home / ".claude"
        settings_dir.mkdir(mode=0o700)
    return config_dir, project_dir, hook_home


def _environment(config_dir: Path, arm: str, hook_home: Path | None) -> dict[str, str]:
    env = {key: os.environ[key] for key in PASSTHROUGH_ENV if key in os.environ}
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    if hook_home is not None:
        env["WRITING_FLOW_HOME"] = str(hook_home)
    if arm == "plugin":
        assert hook_home is not None
        env["WRITING_FLOW_STATE_DIR"] = str(hook_home / "state")
        env["WRITING_FLOW_CONFIG"] = str(hook_home / "config.json")
    return env


def _command(prompt: str, arm: str, style: str | None) -> list[str]:
    command = [
        "claude", "-p", prompt, "--model", "sonnet", "--output-format", "stream-json",
        "--verbose", "--include-hook-events", "--permission-mode", "acceptEdits",
        "--no-session-persistence",
    ]
    if arm == "plugin":
        if not style:
            raise ValueError("Plugin runs need a confirmed output style")
        command += ["--plugin-dir", str(PLUGIN_DIR), "--settings", json.dumps({"outputStyle": style})]
    return command


def _run_once(
    prompt: str,
    arm: str,
    style: str | None,
    run_dir: Path,
    log_path: Path,
    task_id: str,
    run_number: int,
    probe: bool = False,
) -> dict[str, Any]:
    config_dir: Path | None = None
    project_dir: Path | None = None
    hook_home: Path | None = None
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        config_dir, project_dir, hook_home = _fresh_dirs(arm)
        if arm == "plugin":
            assert hook_home is not None
            settings_path = hook_home / ".claude" / "settings.json"
            settings_path.write_text(json.dumps({"outputStyle": style}), encoding="utf-8")
        env = _environment(config_dir, arm, hook_home)
        command = _command(prompt, arm, style)
        stream_path = run_dir / "stream.jsonl"
        with stream_path.open("wb") as stream, log_path.open("wb") as stderr:
            completed = subprocess.run(
                command,
                cwd=project_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=stderr,
                timeout=900,
                check=False,
            )
        duration_ms = round((time.monotonic() - started) * 1000)
        records = _event_records(stream_path)
        init = _init_event(records)
        result = _final_result(records)
        reply = result.get("result", "")
        if not isinstance(reply, str):
            reply = json.dumps(reply, ensure_ascii=False)
        (run_dir / "reply.md").write_text(reply, encoding="utf-8")
        files_dir = run_dir / "files"
        files_dir.mkdir(exist_ok=True)
        for item in project_dir.rglob("*"):
            if item.is_file():
                target = files_dir / item.relative_to(project_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        meta = {
            "arm": arm,
            "run": run_number,
            "task_id": task_id,
            "exit_code": completed.returncode,
            "duration_ms": duration_ms,
            "total_cost_usd": result.get("total_cost_usd"),
            "num_turns": result.get("num_turns"),
            "plugins": init.get("plugins", []),
            "skills": init.get("skills", []),
            "output_style": init.get("output_style"),
            "model": init.get("model") or init.get("model_id"),
            "hook_events": _hook_counts(records),
            "writing_flow_hook_evidence": _writing_flow_hook_evidence(records),
            "strict_guard_flow_evidence": _strict_guard_flow_evidence(records),
            "hook_blocks_met": count_hook_blocks(records),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "probe": probe,
        }
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"meta": meta, "reply": reply, "files": [str(p.relative_to(files_dir)) for p in files_dir.rglob("*") if p.is_file()]}
    except subprocess.TimeoutExpired as exc:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            log.write(f"\nTIMEOUT after {exc.timeout} seconds\n".encode())
        raise
    finally:
        for path in (config_dir, project_dir, hook_home):
            if path is not None:
                shutil.rmtree(path, ignore_errors=True)


def _probe(out_dir: Path, logs_dir: Path, prompt: dict[str, str]) -> str:
    errors = []
    for candidate in STYLE_CANDIDATES:
        probe_dir = out_dir / "probe" / candidate.replace(":", "_") / prompt["id"]
        try:
            outcome = _run_once(
                prompt["prompt"], "plugin", candidate, probe_dir,
                logs_dir / f"probe-{candidate.replace(':', '_')}.stderr.log",
                prompt["id"], 0, probe=True,
            )
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
            continue
        actual = outcome["meta"].get("output_style")
        plugins = outcome["meta"].get("plugins", [])
        if actual == candidate and any("writing-flow" in str(plugin).lower() for plugin in plugins):
            return candidate
        errors.append(f"{candidate}: init reported style={actual!r}, plugins={plugins!r}")
    raise RuntimeError("Neither plugin style candidate loaded: " + "; ".join(errors))


def run_batch(out_dir: Path, jobs: int, prompts_path: Path) -> dict[str, Any]:
    prompts = _read_prompts(prompts_path)
    logs_dir = DEFAULT_RUN_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    marker = logs_dir / "credential-scan.marker"
    marker.touch()
    style = None
    style = _probe(out_dir, logs_dir, prompts[0])
    (out_dir / "confirmed-style.txt").write_text(style + "\n", encoding="utf-8")
    batch_started = time.monotonic()
    tasks = []
    # Submit in run, prompt, arm order. Each pair uses the same prompt and run index.
    for run_number in (1, 2):
        for prompt in prompts:
            for arm in ARMS:
                tasks.append((run_number, prompt, arm))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        future_map = {}
        for run_number, prompt, arm in tasks:
            target = out_dir / arm / f"run{run_number}" / prompt["id"]
            log = logs_dir / f"{arm}-run{run_number}-{prompt['id']}.stderr.log"
            future = pool.submit(
                _run_once, prompt["prompt"], arm, style if arm == "plugin" else None,
                target, log, prompt["id"], run_number,
            )
            future_map[future] = (run_number, prompt["id"], arm)
        for future in concurrent.futures.as_completed(future_map):
            key = future_map[future]
            result = future.result()
            results.append({"run": key[0], "task_id": key[1], "arm": key[2], **result})
    return {"style": style, "results": results, "wall_time_ms": round((time.monotonic() - batch_started) * 1000)}


def run_plugin_batch(out_dir: Path, jobs: int, prompts_path: Path,
                     style: str, logs_dir: Path) -> dict[str, Any]:
    """Rerun only the plugin arm using the previously probed style."""
    prompts = _read_prompts(prompts_path)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "credential-scan.marker").touch()
    started = time.monotonic()
    tasks = [(n, prompt) for n in (1, 2) for prompt in prompts]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        future_map = {}
        for run_number, prompt in tasks:
            target = out_dir / "plugin" / f"run{run_number}" / prompt["id"]
            log = logs_dir / f"plugin-run{run_number}-{prompt['id']}.stderr.log"
            future = pool.submit(_run_once, prompt["prompt"], "plugin", style,
                                 target, log, prompt["id"], run_number)
            future_map[future] = (run_number, prompt["id"])
        for future in concurrent.futures.as_completed(future_map):
            run_number, task_id = future_map[future]
            results.append({"run": run_number, "task_id": task_id,
                            "arm": "plugin", **future.result()})
    (out_dir / "confirmed-style.txt").write_text(style + "\n", encoding="utf-8")
    return {"style": style, "results": results,
            "wall_time_ms": round((time.monotonic() - started) * 1000)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_RUN_DIR / "ab")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--prompts", type=Path, default=REPO / "eval" / "prompts.json")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    args.out.mkdir(parents=True, exist_ok=True)
    result = run_batch(args.out, args.jobs, args.prompts)
    summary = {
        "style": result["style"],
        "runs": len(result["results"]),
        "total_cost_usd": sum((r["meta"].get("total_cost_usd") or 0) for r in result["results"]),
        "wall_time_ms": result["wall_time_ms"],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
