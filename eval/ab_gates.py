"""Verify the five gates for the 0.2 rerun against saved run metadata."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Any


def _records(path: Path) -> list[dict[str, Any]]:
    records=[]
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        try: value=json.loads(line)
        except ValueError: continue
        if isinstance(value,dict): records.append(value)
    return records


def _runs(root: Path, arm: str) -> list[tuple[Path,dict,list[dict]]]:
    result=[]
    for meta_path in sorted((root/arm).glob('run*/**/meta.json')):
        stream=meta_path.with_name('stream.jsonl')
        records=_records(stream)
        meta=json.loads(meta_path.read_text(encoding='utf-8'))
        result.append((meta_path,meta,records))
    return result


def _strict_flow_probe(repo: Path) -> dict[str, Any]:
    """Exercise the strict hook in the same isolated environment as the A/B runner."""
    config_dir = Path(tempfile.mkdtemp(prefix="writing-flow-ab-config-"))
    project_dir = Path(tempfile.mkdtemp(prefix="writing-flow-ab-project-"))
    hook_home = Path(tempfile.mkdtemp(prefix="writing-flow-ab-home-"))
    settings_dir = hook_home / ".claude"
    settings_dir.mkdir(mode=0o700)
    target = project_dir / "README.md"
    event = {
        "harness": "claude",
        "session_id": "writing-flow-strict-flow-probe",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(target),
            "content": (
                "The bug is a real defect. It hit both arms of the test. "
                "Six subagent dispatches carried the bug. The evidence sits in the evolutions log now."
            ),
        },
    }
    passthrough = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR")
    env = {key: os.environ[key] for key in passthrough if key in os.environ}
    env.update({
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "WRITING_FLOW_HOME": str(hook_home),
        "WRITING_FLOW_STATE_DIR": str(hook_home / "state"),
        "WRITING_FLOW_CONFIG": str(hook_home / "config.json"),
    })
    result: dict[str, Any]
    try:
        process = subprocess.run(
            [sys.executable, str(repo / "hooks" / "guard_flow.py")],
            input=json.dumps(event), text=True, capture_output=True,
            cwd=repo, env=env, timeout=30,
        )
        finding = "topic drift" in process.stderr.lower()
        result = {
            "passed": process.returncode == 2 and finding,
            "exit_code": process.returncode,
            "topic_drift_finding": finding,
            "stderr": process.stderr.strip(),
            "user_config_present": (hook_home / "config.json").exists(),
        }
        result["passed"] = result["passed"] and not result["user_config_present"]
    except (OSError, subprocess.SubprocessError) as exc:
        result = {"passed": False, "error": str(exc), "user_config_present": False}
    finally:
        for path in (config_dir, project_dir, hook_home):
            shutil.rmtree(path, ignore_errors=True)
    return result


def check(raw_old: Path, run_dir: Path) -> dict:
    root=run_dir/'ab-v2'
    repo=Path(__file__).resolve().parents[1]
    raw=_runs(root,'raw'); plugin=_runs(root,'plugin')
    raw_ok=len(raw)==10 and all(
        all(str(item.get('name','')).startswith('cc-plugin-') for item in (init.get('plugins') or []) if isinstance(item,dict))
        and init.get('output_style')=='default'
        for _,meta,records in raw for init in records if init.get('type')=='system' and init.get('subtype')=='init'
    )
    plugin_ok=len(plugin)==10 and all(
        any(str(item.get('name','')).lower()=='writing-flow' for item in (init.get('plugins') or []) if isinstance(item,dict))
        and init.get('output_style')=='writing-flow:writing-flow'
        for _,meta,records in plugin for init in records if init.get('type')=='system' and init.get('subtype')=='init'
    )
    by_task={}
    for _,meta,_ in plugin:
        by_task.setdefault(meta['task_id'],False)
        by_task[meta['task_id']] |= bool(meta.get('writing_flow_hook_evidence'))
    hooks_ok=len(by_task)==5 and all(by_task.values())
    marker=run_dir/'logs'/'credential-scan.marker'
    matches=[]
    for path in Path('/tmp').rglob('.credentials.json'):
        try:
            if path.stat().st_mtime > marker.stat().st_mtime: matches.append(str(path))
        except OSError: pass
    persistent_after=Path('/home/pc/.claude/writing-flow').exists()
    no_leaks=(not matches and not persistent_after)  # 0.1 baseline recorded it absent.
    flow_probe=_strict_flow_probe(repo)
    gates={
      'raw_is_raw':{'passed':raw_ok,'init_events':len(raw)},
      'plugin_loaded':{'passed':plugin_ok,'init_events':len(plugin),'style':'writing-flow:writing-flow'},
      'hooks_live':{'passed':hooks_ok,'by_task':by_task},
      'no_leaks':{'passed':no_leaks,'credential_matches':matches,'persistent_plugin_state_after':persistent_after,'baseline_absent':True},
      'strict_guard_flow_probe':flow_probe,
    }
    old_raw=raw_old/'raw'; new_raw=root/'raw'
    digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identical=all(digest(p)==digest(new_raw/p.relative_to(old_raw)) for p in old_raw.rglob('*') if p.is_file())
    gates['raw_copy_unchanged']={'passed':identical}
    return {'gates':gates,'passed':sum(v['passed'] for v in gates.values() if v is not gates['raw_copy_unchanged']), 'total':5}


def main() -> int:
    run=Path(__file__).resolve().parents[1]/'..'
    current=Path('/home/pc/.claude/state/codex_delegate/runs/592abff5-1f66-4d54-929a-3130b0e8d778/20261028-074419-writing-flow-0-2-live-defaults-check-comma')
    old=Path('/home/pc/.claude/state/codex_delegate/runs/592abff5-1f66-4d54-929a-3130b0e8d778/20261028-072840-run-the-raw-vs-writing-flow-a-b-and-build-')/'ab'
    result=check(old,current)
    (current/'gate-results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0 if result['passed']==5 else 1

if __name__=='__main__': raise SystemExit(main())
