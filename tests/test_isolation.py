from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("harness-kit/", "harness_kit", "/srv/dusk", "/mnt/dusk",
             "import local_kit", "import kit_paths")


def test_runtime_sources_do_not_reach_into_harness_kit():
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".json"}:
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {"docs", "tests"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in FORBIDDEN:
            if token in text:
                offenders.append(f"{relative}: {token}")
    assert offenders == []
