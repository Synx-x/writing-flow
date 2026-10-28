"""Command line interface for writing-flow."""
import argparse
import sys
from pathlib import Path

from . import config, flow_rules, prose_rules


def _markdown_files(paths: list[str]) -> list[Path]:
    found = []
    for value in paths:
        path = Path(value)
        if path.is_file() and path.suffix.lower() == ".md":
            found.append(path)
        elif path.is_dir():
            found.extend(item for item in path.rglob("*.md") if item.is_file())
    return sorted(set(found), key=lambda item: str(item))


def _check(paths: list[str]) -> int:
    findings = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from hooks.guard_style import SELF_REF_PATTERNS

    kinds = prose_rules.get_rule_kinds(config.retro_fix_enabled())
    for path in _markdown_files(paths):
        resolved_path = str(path.resolve())
        if any(pattern in resolved_path for pattern in SELF_REF_PATTERNS):
            print(f"{path}: skipped (guard_style self-reference exemption)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"{path}:1: read_error: {exc}")
            findings.append((path, 1, "read_error", str(exc)))
            continue
        for item in prose_rules.scan(text, kinds=kinds, filepath=str(path)):
            findings.append((path, item.get("line", 1), item.get("kind", "style"), item.get("label", "")))
        for item in flow_rules.scan_flow(text):
            findings.append((path, item.get("line") or 1, item.get("kind", "flow"), item.get("label", "")))
    for path, line, rule, message in findings:
        print(f"{path}:{line}: {rule}: {message}")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="writing-flow", description="Check and report writing rules.")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    check_parser = subparsers.add_parser("check", help="check Markdown files and directories")
    check_parser.add_argument("paths", nargs="+")
    subparsers.add_parser("sweep", help="run the prose sweep")
    subparsers.add_parser("report", help="report flow gate outcomes")
    if not args or args[0] not in {"check", "sweep", "report"}:
        parser.parse_args(args)
    verb = args[0]
    if verb == "check":
        parsed = parser.parse_args(args)
        return _check(parsed.paths)
    original = sys.argv
    try:
        sys.argv = [f"writing-flow {verb}", *args[1:]]
        if verb == "sweep":
            from .sweep import main as sweep_main
            return sweep_main()
        from .report import main as report_main
        report_main()
        return 0
    finally:
        sys.argv = original
