#!/usr/bin/env python3
"""Build the self-contained raw vs writing-flow comparison page."""

from __future__ import annotations

import argparse
import difflib
import html
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from typing import Any

from ab_metrics import measure_output


REPO = Path(__file__).resolve().parents[1]
RUN_DIR = Path(
    "/home/pc/.claude/state/codex_delegate/runs/"
    "592abff5-1f66-4d54-929a-3130b0e8d778/"
    "20261028-072840-run-the-raw-vs-writing-flow-a-b-and-build-"
)
TEMPLATE = Path("/home/pc/.claude/skills/artifact-base/template.html")


def _text_for(ab_dir: Path, arm: str, run: int, task: dict[str, str]) -> str:
    base = ab_dir / arm / f"run{run}" / task["id"]
    if task["kind"] == "chat":
        path = base / "reply.md"
    else:
        path = base / "files" / task["path"]
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _hook_blocks(meta: dict[str, Any]) -> int:
    if isinstance(meta.get("hook_blocks_met"), int):
        return meta["hook_blocks_met"]
    events = meta.get("hook_events", {})
    return sum(
        count
        for decisions in events.values()
        for decision, count in decisions.items()
        if str(decision).lower() in {"block", "blocked"}
    )


def _arm_time_span(ab_dir: Path, arm: str) -> str:
    stamps = []
    for stream_path in sorted((ab_dir / arm).glob("run*/**/stream.jsonl")):
        for line in stream_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
                stamp = record.get("timestamp")
                if stamp:
                    stamps.append(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")))
            except (ValueError, TypeError):
                continue
    if not stamps:
        return "time unavailable"
    start, end = min(stamps), max(stamps)
    return f"{start.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S}–{end.astimezone(timezone.utc):%H:%M:%S} UTC"


def _diff_tokens(before: str, after: str) -> list[dict[str, str]]:
    tokens_before = re.findall(r"\s+|[^\s]+", before)
    tokens_after = re.findall(r"\s+|[^\s]+", after)
    matcher = difflib.SequenceMatcher(None, tokens_before, tokens_after, autojunk=False)
    output: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "delete", "replace"):
            text = "".join(tokens_before[i1:i2])
            if text:
                output.append({"op": "delete" if tag == "replace" else tag, "text": text})
        if tag in ("insert", "replace"):
            text = "".join(tokens_after[j1:j2])
            if text:
                output.append({"op": "insert", "text": text})
    return output


def build_data(ab_dir: Path, prompts_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = json.loads(prompts_path.read_text(encoding="utf-8"))
    page_tasks = []
    totals = {
        arm: {"words": 0, "sentences": 0, "findings": 0, "outputs": 0}
        for arm in ("raw", "plugin")
    }
    for task in tasks:
        runs = []
        for run in (1, 2):
            pair: dict[str, Any] = {"run": run, "outputs": {}, "diff": []}
            for arm in ("raw", "plugin"):
                text = _text_for(ab_dir, arm, run, task)
                meta_path = ab_dir / arm / f"run{run}" / task["id"] / "meta.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
                metrics = measure_output(text, hook_blocks=_hook_blocks(meta))
                pair["outputs"][arm] = {
                    "text": text,
                    "metrics": {k: v for k, v in metrics.items() if k != "finding_details"},
                    "meta": meta,
                }
                totals[arm]["words"] += metrics["prose_word_count"]
                totals[arm]["sentences"] += metrics["sentence_count"]
                totals[arm]["findings"] += metrics["writing_flow_findings"]
                totals[arm]["outputs"] += 1
            pair["diff"] = _diff_tokens(pair["outputs"]["raw"]["text"], pair["outputs"]["plugin"]["text"])
            runs.append(pair)
        page_tasks.append({"id": task["id"], "kind": task["kind"], "prompt": task["prompt"], "runs": runs})
    summaries = {
        arm: {
            "mean_sentence_length": round(v["words"] / v["sentences"], 2) if v["sentences"] else 0,
            "check_findings": v["findings"],
            "output_count": v["outputs"],
        }
        for arm, v in totals.items()
    }
    summaries["arm_times"] = {arm: _arm_time_span(ab_dir, arm) for arm in ("raw", "plugin")}
    return {"tasks": page_tasks}, summaries


def _template_parts() -> tuple[str, str, str, str]:
    template = TEMPLATE.read_text(encoding="utf-8")
    lines = template.splitlines()
    marker = lines[0]
    token_start = template.index(":root{")
    token_end = template.index("\n*{box-sizing:border-box}")
    token_css = template[token_start:token_end]
    fonts = "\n".join(lines[2:4])
    version_start = template.index("<!-- versioning: the artifact-base publish hook")
    content_start = template.index("<script>\n/* ===================== CONTENT", version_start)
    version_markup = template[version_start:content_start]
    version_js_start = template.index("/* ---------- versioning: pill,", content_start)
    version_js_end = template.rindex("\n</script>")
    version_js = template[version_js_start:version_js_end]
    return marker, token_css, fonts, version_markup + "\n" + version_js


def _page_html(data: dict[str, Any], summaries: dict[str, Any], style: str,
               gate_results: dict[str, Any] | None = None) -> str:
    marker, token_css, fonts, version_parts = _template_parts()
    version_markup, version_js = version_parts.split("\n<script>\n", 1) if "\n<script>\n" in version_parts else ("", "")
    # The template's version markup ends immediately before its content script.
    template = TEMPLATE.read_text(encoding="utf-8")
    version_start = template.index("<!-- versioning: the artifact-base publish hook")
    content_start = template.index("<script>\n/* ===================== CONTENT", version_start)
    version_markup = template[version_start:content_start]
    version_end = template.rindex("\n</script>")
    version_js = template[template.index("/* ---------- versioning: pill,", content_start):version_end]

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    raw_mean = summaries["raw"]["mean_sentence_length"]
    plugin_mean = summaries["plugin"]["mean_sentence_length"]
    raw_findings = summaries["raw"]["check_findings"]
    plugin_findings = summaries["plugin"]["check_findings"]

    css = r"""
*{box-sizing:border-box}
html{overflow-x:clip;scrollbar-color:var(--line) transparent;scrollbar-width:thin}
body{margin:0;min-height:100vh;overflow-x:clip;background:var(--ground);color:var(--ink);font:15px/1.6 var(--sans);font-optical-sizing:auto;-webkit-font-smoothing:antialiased}
h1,h2,h3,p{margin:0;text-wrap:pretty}button{font:inherit;color:inherit;border:0;background:none;cursor:pointer}
a{color:inherit}code,.mono{font-family:var(--mono)}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.frame{position:fixed;inset:0 0 auto;z-index:5;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;padding:calc(12px + env(safe-area-inset-top,0px)) max(16px,env(safe-area-inset-right,0px)) 12px max(16px,env(safe-area-inset-left,0px));pointer-events:none}
.frame::before{content:"";position:absolute;inset:0;height:100px;background:linear-gradient(to bottom,rgb(var(--scrim)/.97),rgb(var(--scrim)/.72) 55%,rgb(var(--scrim)/0));pointer-events:none}
.frame>*{position:relative;pointer-events:auto}.brand{display:flex;gap:12px;align-items:baseline;font:700 11px var(--mono);letter-spacing:.12em;text-transform:uppercase}.brand span{color:var(--ink-3);font-weight:400;letter-spacing:0}
.edge{justify-self:end;color:var(--ink-3);font:11px var(--mono)}.seg{display:flex;gap:3px;padding:4px;border-radius:999px;background:rgb(var(--scrim)/.85);box-shadow:0 0 0 1px var(--line)}
.seg button{padding:6px 13px;border-radius:999px;color:var(--ink-2);font-size:12px}.seg button[aria-pressed=true]{background:var(--ink);color:var(--ground)}
.wrap{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-bottom:64px}
.hero{padding-top:clamp(120px,17vh,180px);padding-bottom:32px;border-bottom:2px solid var(--ink)}.eyebrow{display:flex;justify-content:space-between;gap:12px;color:var(--ink-3);font:11px var(--mono);letter-spacing:.12em;text-transform:uppercase}
.hero h1{padding:22px 0 24px;max-width:13ch;font:220 clamp(54px,10vw,136px)/.86 var(--display);letter-spacing:-.055em}.hero h1 em{color:var(--accent);font-style:normal}
.figs{display:flex;flex-wrap:wrap;gap:24px clamp(22px,5vw,70px)}.fig .label{padding-bottom:6px;color:var(--ink-3);font:10px var(--mono);letter-spacing:.08em;text-transform:uppercase}.fig .value{font:300 clamp(24px,3vw,38px)/1 var(--display);font-variant-numeric:tabular-nums}
.lede{max-width:68ch;padding-top:22px;color:var(--ink-2);font-size:15px}.note{margin-top:14px;color:var(--ink-3);font-size:12px}
.task{max-width:1200px;margin:0 auto;padding:42px 0 48px;border-bottom:1px solid var(--line)}.taskhead{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:14px}.tasknum{color:var(--accent);font:12px var(--mono)}.task h2{font:350 clamp(24px,4vw,42px)/1.05 var(--display);letter-spacing:-.03em}.runs{display:flex;gap:5px}.runs button{padding:5px 10px;border:1px solid var(--line);border-radius:999px;color:var(--ink-2);font:11px var(--mono)}.runs button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
.prompt{margin:17px 0 22px;padding:12px 15px;border-left:2px solid var(--accent);background:var(--raised);color:var(--ink-2);white-space:pre-wrap;overflow-wrap:anywhere}
.outputs{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.out{min-width:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--raised)}.outhead{display:flex;justify-content:space-between;gap:10px;padding:10px 13px;border-bottom:1px solid var(--line);font:11px var(--mono);text-transform:uppercase;letter-spacing:.1em}.arm-plugin{color:var(--accent)}.output{max-height:560px;min-height:90px;margin:0;padding:15px;overflow:auto;white-space:pre;overflow-wrap:normal;color:var(--ink);font:13px/1.65 var(--sans);tab-size:2}.output code{white-space:pre}
.changes{display:none;margin:0;padding:16px;max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--raised);white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 var(--mono)}.task[data-view=changes] .outputs{display:none}.task[data-view=changes] .changes{display:block}.changes del{background:var(--bad-bg);color:var(--bad);text-decoration:line-through}.changes ins{background:var(--good-bg);color:var(--good);text-decoration:none}
.metrics{width:100%;margin-top:20px;border-collapse:collapse;font:12px var(--mono)}.metrics th,.metrics td{padding:8px 10px;border-bottom:1px solid var(--hair);text-align:right;font-weight:400}.metrics th:first-child,.metrics td:first-child{text-align:left;color:var(--ink-2)}.metrics thead th{color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.hooks{margin-top:22px}.hooks h3{margin-bottom:8px;color:var(--ink-3);font:11px var(--mono);letter-spacing:.1em;text-transform:uppercase}.hooks ul{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0}.hooks li{max-width:100%;padding:5px 9px;border:1px solid var(--line);border-radius:999px;color:var(--ink-2);font:11px var(--mono);overflow-wrap:anywhere}.hooks .blocked{border-color:var(--bad);color:var(--bad)}.hooks .empty{color:var(--ink-3)}
.method{max-width:1200px;margin:0 auto;padding:38px 0 26px}.method h2{margin-bottom:12px;font:350 27px var(--display)}.method p{max-width:78ch;color:var(--ink-2)}.method p+p{margin-top:10px}.foot{padding:20px 0 40px;color:var(--ink-3);font:10px var(--mono);text-transform:uppercase;letter-spacing:.1em}
.gates{max-width:1200px;margin:24px auto 0;padding:20px;border:1px solid var(--line);border-radius:12px;background:var(--raised)}.gates h2{margin-bottom:12px;font:350 24px var(--display)}.gates ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;list-style:none;margin:0;padding:0}.gates li{display:flex;justify-content:space-between;gap:12px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font:11px var(--mono)}.gates .pass{color:var(--good)}.gates .fail{color:var(--bad)}
@media(max-width:720px){.frame{grid-template-columns:1fr auto}.edge{display:none}.seg{justify-self:end}.brand span{display:none}.hero{padding-top:112px}.outputs{grid-template-columns:minmax(0,1fr)}.taskhead{grid-template-columns:auto 1fr}.runs{grid-column:2;justify-self:start}.metrics{font-size:10px}.metrics th,.metrics td{padding:7px 4px}.figs{gap:18px 24px}}
"""
    # Colors used by the diff states are still tokens, including their backgrounds.
    theme_extras = """
:root{--good-bg:#E2F4E8;--bad-bg:#FBE5E8}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--good-bg:#183624;--bad-bg:#3A2027}}
:root[data-theme="dark"]{--good-bg:#183624;--bad-bg:#3A2027}
"""
    rendered_figs = (
        "<div class=\"figs\">"
        "<div class=\"fig\"><div class=\"label\">Runs</div><div class=\"value\">20</div></div>"
        "<div class=\"fig\"><div class=\"label\">Tasks</div><div class=\"value\">5</div></div>"
        "<div class=\"fig\"><div class=\"label\">Model</div><div class=\"value\">Sonnet 5.5</div></div>"
        f"<div class=\"fig\"><div class=\"label\">Raw mean sentence length</div><div class=\"value\">{raw_mean:g}</div></div>"
        f"<div class=\"fig\"><div class=\"label\">Plugin mean sentence length</div><div class=\"value\">{plugin_mean:g}</div></div>"
        f"<div class=\"fig\"><div class=\"label\">Raw check findings</div><div class=\"value\">{raw_findings}</div></div>"
        f"<div class=\"fig\"><div class=\"label\">Plugin check findings</div><div class=\"value\">{plugin_findings}</div></div></div>"
    )
    method = (
        "<section class=\"method\"><h2>Method</h2>"
        f"<p>Run times (UTC): raw {html.escape(summaries['arm_times']['raw'])}; plugin {html.escape(summaries['arm_times']['plugin'])}. Each run used a fresh temporary project and Claude config directory. The raw arm loaded no user plugins, skills, project instructions, rules, or memory. The plugin arm loaded the writing-flow plugin from the repository, the user's live config as defaults, its prompt-echo guard, and output style, <code>"
        + html.escape(style)
        + "</code>. The two arms used the same prompts and model.</p>"
        "<p>The plugin cannot load rule files, and MessageDisplay hooks do not fire from plugins. Check findings use writing-flow’s own rules, so those counts favor the plugin by construction.</p></section>"
    )
    frame = (
        "<div class=\"frame\"><div class=\"brand\">WRITING FLOW <span>RAW VS PLUGIN</span></div>"
        "<div class=\"seg\" role=\"group\" aria-label=\"Comparison mode\"><button id=\"mode-side\" type=\"button\" aria-pressed=\"true\">Side by side</button>"
        "<button id=\"mode-changes\" type=\"button\" aria-pressed=\"false\">Changes</button></div><div class=\"edge\">5 TASKS · 2 RUNS</div></div>"
    )
    stamp_match = re.search(r'<script type="application/json" id="artifact-version">.*?</script>', version_markup, re.S)
    if not stamp_match:
        raise ValueError("Template versioning stamp is missing")
    version_html = version_markup
    sections = f"""<main class="wrap">
<header class="hero"><div class="eyebrow"><span>Controlled comparison</span><span>Two arms · five prompts</span></div>
<h1>Raw vs <em>writing-flow</em></h1>{rendered_figs}
<p class="lede">The same five tasks ran twice with and without writing-flow. Compare each output, inspect word-level changes, and see the measured rule findings.</p>
<p class="note">Finding counts come from writing-flow’s own rules and therefore favor the plugin by construction.</p></header>
<div id="tasks"></div>{method}<footer class="foot">Raw output · Writing-flow output · 20 sessions</footer></main>"""
    if gate_results:
        labels = {
            "raw_is_raw": "Raw arm loaded as expected",
            "plugin_loaded": "Writing-flow plugin loaded",
            "hooks_live": "Hooks fired across tasks",
            "no_leaks": "No persistent state or credential leaks",
            "strict_guard_flow_probe": "Strict flow probe blocks topic drift",
        }
        gate_items = []
        for name, gate in gate_results.get("gates", {}).items():
            if name == "raw_copy_unchanged":
                continue
            passed = bool(gate.get("passed"))
            status = "PASS" if passed else "FAIL"
            css_class = "pass" if passed else "fail"
            label = html.escape(labels.get(name, name.replace("_", " ")))
            gate_items.append(f'<li><span>{label}</span><strong class="{css_class}">{status}</strong></li>')
        gate_section = '<section class="gates"><h2>Run gates</h2><ul>' + "".join(gate_items) + "</ul></section>"
        sections = sections.replace('<div id="tasks"></div>', gate_section + '<div id="tasks"></div>')
    html_page = (
        marker
        + '\n<title>Raw vs writing-flow</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
        + fonts
        + "\n<style>\n"
        + token_css
        + theme_extras
        + css
        + "\n</style>\n"
        + frame
        + sections
        + version_html
        + "<script>\n"
        + "const PAGE={key:'writing-flow-ab',changes:[{v:'next',items:['First published: raw vs writing-flow output for five tasks, two runs each']}]};\n"
        + "const DATA=" + payload + ";\n"
        + r"""
const escText = value => String(value ?? '');
const metricNames = [
  ['word_count','Words'],['sentence_count','Sentences'],['mean_sentence_length','Mean sentence length'],
  ['sentences_over_25_words','Sentences over 25 words'],['semicolon_count_outside_code','Semicolons outside code'],
  ['writing_flow_findings','writing-flow check findings'],['hook_blocks_met','Hooks that blocked']
];
const taskState = new Map(DATA.tasks.map(task => [task.id, 1]));
const tasksRoot = document.getElementById('tasks');
function node(tag, cls, value){const el=document.createElement(tag);if(cls)el.className=cls;if(value!==undefined)el.textContent=escText(value);return el;}
function hookItems(meta){const ul=node('ul');const events=meta?.hook_events||{};let count=0;
  Object.entries(events).forEach(([name, decisions])=>Object.entries(decisions||{}).forEach(([decision,n])=>{
    count++;const li=node('li',String(decision).toLowerCase().includes('block')?'blocked':'',`${name} · ${decision} × ${n}`);ul.append(li);
  }));
  if(!count)ul.append(node('li','empty','No hook events recorded'));return ul;
}
function renderTask(task){
  const run=taskState.get(task.id)||1;const pair=task.runs.find(item=>item.run===run);
  const article=node('section','task');article.id=`task-${task.id}`;article.dataset.view='side';
  const head=node('div','taskhead');head.append(node('span','tasknum',task.id.toUpperCase()),node('h2','',task.id==='howto'?'Rotate an API key':task.id==='readme'?'tidy-csv README':task.id==='explain'?'HTTP caching':task.id==='email'?'Team sync email':'Retry decorator'));
  const switcher=node('div','runs');[1,2].forEach(n=>{const b=node('button','',`Run ${n}`);b.type='button';b.dataset.action='run';b.dataset.task=task.id;b.dataset.run=String(n);b.setAttribute('aria-pressed',String(n===run));switcher.append(b);});head.append(switcher);article.append(head);
  article.append(node('div','prompt',task.prompt));
  const outputs=node('div','outputs');
  for(const [arm,label,cls] of [['raw','Raw',''],['plugin','Writing-flow','arm-plugin']]){
    const card=node('div','out');const cardHead=node('div','outhead');cardHead.append(node('span',cls,label),node('span','',`Run ${run}`));
    const output=node('pre','output',pair.outputs[arm].text);card.append(cardHead,output);outputs.append(card);
  }
  article.append(outputs);
  const changes=node('pre','changes');changes.setAttribute('aria-label','Unified word-level diff');
  pair.diff.forEach(part=>{const el=document.createElement(part.op==='delete'?'del':part.op==='insert'?'ins':'span');el.textContent=part.text;changes.append(el);});article.append(changes);
  const table=node('table','metrics');const thead=document.createElement('thead');const tr=document.createElement('tr');['Metric','Raw','Writing-flow'].forEach(v=>tr.append(node('th','',v)));thead.append(tr);table.append(thead);
  const tbody=document.createElement('tbody');metricNames.forEach(([key,label])=>{const row=document.createElement('tr');row.append(node('td','',label));for(const arm of ['raw','plugin'])row.append(node('td','',pair.outputs[arm].metrics[key]??0));tbody.append(row);});table.append(tbody);article.append(table);
  const hooks=node('div','hooks');hooks.append(node('h3','',`Plugin hooks · Run ${run}`),hookItems(pair.outputs.plugin.meta));article.append(hooks);
  return article;
}
function render(){tasksRoot.replaceChildren(...DATA.tasks.map(renderTask));}
function setMode(mode){document.querySelectorAll('.task').forEach(task=>task.dataset.view=mode);document.getElementById('mode-side').setAttribute('aria-pressed',String(mode==='side'));document.getElementById('mode-changes').setAttribute('aria-pressed',String(mode==='changes'));}
document.addEventListener('click',event=>{const target=event.target.closest('[data-action],#mode-side,#mode-changes');if(!target)return;
  if(target.id==='mode-side')setMode('side');else if(target.id==='mode-changes')setMode('changes');else if(target.dataset.action==='run'){taskState.set(target.dataset.task,Number(target.dataset.run));const mode=document.querySelector('.task')?.dataset.view||'side';render();setMode(mode);}
});
render();
"""
        + "\n"
        + version_js
        + "\n</script>\n"
    )
    return html_page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ab", type=Path, default=RUN_DIR / "ab")
    parser.add_argument("--out", type=Path, default=RUN_DIR / "page" / "ab.html")
    parser.add_argument("--prompts", type=Path, default=REPO / "eval" / "prompts.json")
    parser.add_argument("--gates", type=Path)
    args = parser.parse_args()
    style = (args.ab / "confirmed-style.txt").read_text(encoding="utf-8").strip()
    data, summaries = build_data(args.ab, args.prompts)
    gates_path = args.gates or (args.ab.parent / "gate-results.json")
    gate_results = json.loads(gates_path.read_text(encoding="utf-8")) if gates_path.is_file() else None
    page = _page_html(data, summaries, style, gate_results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
