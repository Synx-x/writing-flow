"""Input collection and rule evaluation for the writing-flow check command."""
from __future__ import annotations

import html.parser
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, flow_rules, prose_rules

MAX_BYTES = 5 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "virtualenv", ".tox", "env", "__pycache__", "__pypackages__"}


class MainText(html.parser.HTMLParser):
    DROP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"}
    BLOCK = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "br"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.chunks = {0: [], 1: [], 2: [], 3: []}
    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        if tag in self.BLOCK and not (set(self.stack) & self.DROP):
            marker = "#" * int(tag[1:]) + " " if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit() else "- " if tag == "li" else "\n"
            self.chunks[self._rank()].append("\n" + marker)
    def handle_endtag(self, tag):
        if tag in self.BLOCK and not (set(self.stack) & self.DROP):
            self.chunks[self._rank()].append("\n")
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]
    def handle_data(self, data):
        if not (set(self.stack) & self.DROP):
            self.chunks[self._rank()].append(data)
    def _rank(self):
        return 3 if "article" in self.stack else 2 if "main" in self.stack else 1 if "body" in self.stack else 0
    def text(self):
        rank = max((n for n, chunks in self.chunks.items() if "".join(chunks).strip()), default=0)
        raw = "".join(self.chunks[rank])
        return re.sub(r"[ \t]+", " ", "\n".join(x.strip() for x in raw.splitlines() if x.strip())).strip()


def _direct(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "writing-flow/0.2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"direct reader HTTP status {response.status}")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("direct reader response exceeds 5 MB")
        charset = response.headers.get_content_charset() or "utf-8"
    parser = MainText()
    parser.feed(raw.decode(charset, errors="replace"))
    text = parser.text()
    if not text:
        raise ValueError("direct reader found no main text")
    return text


def _jina(url: str) -> str:
    endpoint = "https://r.jina.ai/" + url
    headers = {"Accept": "application/json", "X-Retain-Images": "none", "User-Agent": "writing-flow/0.2"}
    key = os.environ.get("JINA_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(endpoint, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"Jina HTTP status {response.status}")
        payload = json.loads(response.read(MAX_BYTES + 1).decode("utf-8"))
    return _parse_jina_response(payload)


def _parse_jina_response(payload: dict) -> str:
    data = payload.get("data") or {}
    if payload.get("code") != 200:
        raise ValueError(f"Jina code {payload.get('code')}")
    if int(data.get("httpStatus") or 0) >= 400:
        raise ValueError(f"Jina source HTTP status {data['httpStatus']}")
    content = str(data.get("content") or "")
    if len(content) < 200:
        raise ValueError("Jina content under 200 characters")
    return content


def fetch_url(url: str, reader: str) -> tuple[str, dict]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must use http or https and include a host")
    if reader == "direct":
        return _direct(url), {"reader": "direct", "fallback_reason": None}
    try:
        return _jina(url), {"reader": "jina", "fallback_reason": None}
    except Exception as exc:
        if reader == "jina":
            raise
        reason = f"Jina failed: {type(exc).__name__}: {exc}"
        return _direct(url), {"reader": "direct", "fallback_reason": reason}


def _self_reference(path: Path) -> bool:
    try:
        import sys
        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        from hooks.guard_style import SELF_REF_PATTERNS
        normalized = str(path.resolve()).replace("\\", "/")
        return any(pattern in normalized for pattern in SELF_REF_PATTERNS)
    except Exception:
        return False


def _files(paths: list[str]) -> list[Path]:
    output = []
    for arg in paths:
        p = Path(arg)
        if p.is_file():
            output.append(p)
        elif p.is_dir():
            for current, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                output.extend(Path(current) / name for name in sorted(files))
    return output


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def _check_text(target: str, text: str, mode: str, filepath: str = "") -> list[dict]:
    import sys
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    if mode == "chat":
        from hooks import response_audit
        raw = response_audit.check_response_flow(text) + response_audit.check_chat_form(text)
        return [{"line": 1, "rule": detail.split(":", 1)[0], "message": detail, "sentence": detail, "blocking": severity == "HARD"}
                for severity, detail in raw]
    source = text
    if filepath:
        family = prose_rules.grammar_for(filepath, text)
        if family is None:
            return []
        if family != prose_rules.PROSE_ROUTE and prose_rules.grammar_is_known(filepath):
            source = prose_rules.extract_comments_and_strings(text, filepath)
    findings = []
    kinds = prose_rules.get_rule_kinds(config.retro_fix_enabled())
    for item in prose_rules.scan(source, kinds=kinds, filepath=filepath):
        kind = item.get("kind", "style")
        blocking = kind in {"ai_ism", "tier1", *prose_rules.STE_STRICT, *prose_rules.COMMENT_STRUCTURE_KINDS}
        blocking = blocking or (kind == "residue" and item.get("label") in prose_rules.RESIDUE_BLOCKING_LABELS)
        findings.append({"line": item.get("line", 1), "rule": kind, "message": item.get("label", ""), "sentence": _line(source, item.get("line", 1)), "blocking": blocking})
    for item in flow_rules.scan_flow(source, kinds=tuple(config.hook_config("guard_flow").get("kinds") or flow_rules.ALL_KINDS)):
        findings.append({"line": item.get("line") or 1, "rule": item.get("kind", "flow"), "message": item.get("label", ""), "sentence": _line(source, item.get("line") or 1), "blocking": config.hook_config("guard_flow").get("mode") == "strict"})
    return findings


def _line(text: str, number: int) -> str:
    lines = text.splitlines()
    return lines[number - 1].strip() if 0 < number <= len(lines) else ""


def run_check(paths: list[str], text_value: str | None = None, clip: bool = False,
              as_mode: str = "doc", reader: str = "auto", use_stdin: bool = False) -> tuple[list[dict], int]:
    targets = []
    try:
        if clip:
            try:
                proc = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, check=False, timeout=5)
            except FileNotFoundError:
                raise ValueError("--clip requires wl-paste, which is not installed")
            content = proc.stdout.decode("utf-8", errors="replace")
            if not content:
                raise ValueError("clipboard is empty")
            targets.append(("clipboard", content, {}))
        if text_value is not None:
            targets.append(("<text>", text_value, {}))
        if use_stdin:
            content = __import__("sys").stdin.read()
            targets.append(("-", content, {}))
        for arg in paths:
            if arg == "-":
                continue
            if arg.startswith(("http://", "https://")):
                content, meta = fetch_url(arg, reader)
                targets.append((arg, content, meta))
            else:
                p = Path(arg)
                if p.is_dir():
                    for file in _files([arg]):
                        with file.open("rb") as stream:
                            header = stream.read(8192)
                        if _is_binary(header):
                            continue
                        if _self_reference(file):
                            targets.append((str(file), "", {"exempt": True, "reason": "guard_style self-reference exemption"}))
                            continue
                        targets.append((str(file), file.read_text(encoding="utf-8", errors="replace"), {}))
                elif p.is_file():
                    with p.open("rb") as stream:
                        header = stream.read(8192)
                    if _is_binary(header):
                        continue
                    exempt = _self_reference(p)
                    targets.append((str(p), p.read_text(encoding="utf-8", errors="replace"), {"exempt": exempt, "explicit": True, "reason": "checked despite self-reference exemption" if exempt else None}))
                else:
                    raise ValueError(f"target does not exist: {arg}")
        reports = []
        for target, content, meta in targets:
            findings = _check_text(target, content, as_mode, target if target not in {"-", "<text>", "clipboard"} else "") if content and (not meta.get("exempt") or meta.get("explicit")) else []
            reports.append({"target": target, **meta, "findings": findings})
        return reports, 0
    except Exception as exc:
        return [{"error": str(exc)}], 2
