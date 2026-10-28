#!/usr/bin/env python3
"""Score prompt-echo blocking and advisory behaviour on labelled pairs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from writing_flow.prompt_echo import find_echo, find_narration, guidance_clauses

CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/prompt_echo/cases.jsonl"


def evaluate(path: Path = CASES) -> dict:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_source: dict[str, dict[str, int]] = {}
    block_tp = block_fp = leak_total = leak_detected = advisory_detected = 0
    for case in cases:
        clauses = guidance_clauses([case["prompt"]])
        found = find_echo(case["sentence"], clauses)
        narration = find_narration(case["sentence"])
        sure = any(item["sure"] for item in found) or bool(narration)
        any_hit = bool(found) or bool(narration)
        leak = case["label"] == "leak"
        source = str(case.get("source", "unspecified"))
        counts = by_source.setdefault(source, {"cases": 0, "leaks": 0, "block_tp": 0,
                                               "block_fp": 0, "block_fn": 0,
                                               "advisory_detected": 0})
        counts["cases"] += 1
        counts["leaks"] += int(leak)
        counts["advisory_detected"] += int(any_hit)
        if leak:
            leak_total += 1
            leak_detected += sure
            block_tp += sure
            counts["block_tp"] += int(sure)
            counts["block_fn"] += int(not sure)
        if sure and not leak:
            block_fp += 1
            counts["block_fp"] += 1
        if any_hit:
            advisory_detected += 1
    precision = block_tp / (block_tp + block_fp) if block_tp + block_fp else 1.0
    block_recall = leak_detected / leak_total if leak_total else 0.0
    advisory_recall = advisory_detected / len(cases) if cases else 0.0
    sources = {}
    for source, counts in sorted(by_source.items()):
        predicted = counts["block_tp"] + counts["block_fp"]
        sources[source] = {
            "cases": counts["cases"],
            "leaks": counts["leaks"],
            "block_precision": counts["block_tp"] / predicted if predicted else 1.0,
            "block_recall": counts["block_tp"] / counts["leaks"] if counts["leaks"] else 0.0,
            "advisory_recall": counts["advisory_detected"] / counts["cases"] if counts["cases"] else 0.0,
        }
    return {"cases": len(cases), "leaks": leak_total, "block_precision": precision,
            "block_recall": block_recall, "advisory_recall": advisory_recall,
            "sources": sources}


def main() -> int:
    result = evaluate()
    print(f"cases: {result['cases']}")
    print(f"block precision: {result['block_precision']:.3f}")
    print(f"block recall: {result['block_recall']:.3f}")
    print(f"advisory recall: {result['advisory_recall']:.3f}")
    for source, metrics in result["sources"].items():
        print(f"{source}: cases {metrics['cases']}, leaks {metrics['leaks']}, "
              f"block precision {metrics['block_precision']:.3f}, "
              f"block recall {metrics['block_recall']:.3f}, "
              f"advisory recall {metrics['advisory_recall']:.3f}")
    return 0 if result["block_precision"] >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
