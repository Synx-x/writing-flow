#!/usr/bin/env python3
"""Compare standalone writing scans with a pinned source archive."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

WORKER = r'''
import json
import sys
from pathlib import Path
side, root = sys.argv[1:]
root = Path(root)
if side == "source":
    sys.path.insert(0, str(root / "hooks" / "lib"))
    import prose_rules, flow_rules, plain_rules, personal_style
else:
    sys.path.insert(0, str(root / "src"))
    from writing_flow import prose_rules, flow_rules, plain_rules, personal_style
corpus = json.load(sys.stdin)
out = {}
for item in corpus:
    text, path = item["text"], item["path"]
    plain, _seen = plain_rules.scan_plain(text, set())
    out[path] = {
        "prose": prose_rules.scan(text, filepath=path),
        "flow": flow_rules.scan_flow(text),
        "plain": plain,
        "personal": personal_style.check_personal_style(text),
    }
print(json.dumps(out, sort_keys=True, default=str))
'''


def corpus_for(source: Path, repo: Path) -> list[dict]:
    paths = sorted((source / "docs").rglob("*.md"))
    paths += sorted((repo / "tests" / "fixtures").rglob("*"))
    items = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        label = path.relative_to(source).as_posix() if source in path.parents else path.relative_to(repo).as_posix()
        items.append({"path": label, "text": text})
    return items


def run_worker(side: str, root: Path, corpus: list[dict]) -> dict:
    result = subprocess.run(
        [sys.executable, "-I", "-c", WORKER, side, str(root)],
        input=json.dumps(corpus), text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{side} worker exited {result.returncode}")
    return json.loads(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    corpus = corpus_for(source, repo)
    try:
        expected = run_worker("source", source, corpus)
        actual = run_worker("package", repo, corpus)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"PARITY ERROR {exc}")
        return 1
    differences = []
    for path in sorted(set(expected) | set(actual)):
        for family in ("prose", "flow", "plain", "personal"):
            left = sorted(expected.get(path, {}).get(family, []), key=lambda value: json.dumps(value, sort_keys=True, default=str))
            right = sorted(actual.get(path, {}).get(family, []), key=lambda value: json.dumps(value, sort_keys=True, default=str))
            if left != right:
                differences.append((path, family, left, right))
    if differences:
        for path, family, left, right in differences:
            print(f"DIFF {path} [{family}]")
            print(f"  source:  {json.dumps(left, ensure_ascii=False, default=str)}")
            print(f"  package: {json.dumps(right, ensure_ascii=False, default=str)}")
        return 1
    print(f"PARITY OK {len(corpus)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
