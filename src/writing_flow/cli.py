"""Command line interface for writing-flow."""
import argparse
import json
import sys

from . import check as checker


def _check(args) -> int:
    reports, status = checker.run_check(args.paths, args.text, args.clip,
                                        args.as_mode, args.reader,
                                        "-" in args.paths)
    if status:
        message = reports[0].get("error", "check failed")
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(f"writing-flow check: {message}", file=sys.stderr)
        return 2
    flat = []
    for report in reports:
        if report.get("exempt"):
            report["note"] = (
                report.get("reason") or "self-reference exemption"
                if report.get("explicit") else
                f"skipped ({report.get('reason') or 'self-reference exemption'})"
            )
        if report.get("reader"):
            report["note"] = f"reader: {report['reader']}" + (f"; fallback: {report['fallback_reason']}" if report.get("fallback_reason") else "")
        for finding in report["findings"]:
            flat.append(finding)
    blocking = sum(bool(f["blocking"]) for f in flat)
    advisory = len(flat) - blocking
    if args.json:
        print(json.dumps({"targets": reports, "findings": len(flat), "blocking": blocking, "advisory": advisory}, ensure_ascii=False))
    else:
        for report in reports:
            if report.get("note"):
                print(f"{report['target']}: {report['note']}")
            for finding in report["findings"]:
                sentence = finding.get("sentence", "")[:120]
                print(f"{report['target']}:{finding['line']}: {finding['rule']}: {finding['message']}\n  {sentence}")
        print(f"{len(flat)} findings: {blocking} blocking, {advisory} advisory")
    return 1 if blocking else 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="writing-flow", description="Check and report writing rules.")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    check_parser = subparsers.add_parser("check", help="check Markdown files and directories")
    check_parser.add_argument("paths", nargs="*")
    check_parser.add_argument("--as", dest="as_mode", choices=("doc", "chat"), default="doc")
    check_parser.add_argument("--reader", choices=("auto", "jina", "direct"), default="auto")
    check_parser.add_argument("--text")
    check_parser.add_argument("--clip", action="store_true")
    check_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("sweep", help="run the prose sweep")
    subparsers.add_parser("report", help="report flow gate outcomes")
    if not args or args[0] not in {"check", "sweep", "report"}:
        parser.parse_args(args)
    verb = args[0]
    if verb == "check":
        parsed = parser.parse_args(args)
        if not (parsed.paths or parsed.text is not None or parsed.clip):
            parser.error("check needs a path, URL, -, --text STRING, or --clip")
        return _check(parsed)
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
