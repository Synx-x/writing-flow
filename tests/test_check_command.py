import http.server
import json
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest

from writing_flow import check, cli

ROOT = Path(__file__).resolve().parents[1]
JINA = json.loads((ROOT / "tests/fixtures/jina-example-com.json").read_text())


@pytest.fixture
def html_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><body><nav>menu noise</nav><main><h1>Page title</h1><p>Readable main text is here.</p></main><footer>footer noise</footer></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_file_folder_text_and_stdin(tmp_path, monkeypatch, capsys):
    file = tmp_path / "note.txt"
    file.write_text("Run it; then stop.")
    assert cli.main(["check", str(file)]) == 1
    assert "note.txt:" in capsys.readouterr().out
    unknown_text = tmp_path / "note.custom"
    unknown_text.write_text("Run it; then stop.")
    assert cli.main(["check", str(unknown_text)]) == 1
    capsys.readouterr()
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "plain.txt").write_text("Run it; then stop.")
    (sub / "ignored.bin").write_bytes(b"\0binary")
    (sub / ".git").mkdir()
    (sub / ".git" / "secret.txt").write_text("Run it; then stop.")
    assert cli.main(["check", str(sub)]) == 1
    assert "ignored.bin" not in capsys.readouterr().out
    assert cli.main(["check", "--text", "A clear line."]) == 0
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("Run it; then stop."))
    assert cli.main(["check", "-"]) == 1


def test_self_reference_direct_is_reported_and_checked(tmp_path, capsys):
    target = tmp_path / "hooks" / "guard_style.md"
    target.parent.mkdir()
    target.write_text("Run it; then stop.")
    assert cli.main(["check", str(target)]) == 1
    output = capsys.readouterr().out
    assert "checked despite self-reference exemption" in output
    assert "findings:" in output


def test_direct_reader_uses_local_html_server(html_server):
    text = check._direct(html_server)
    assert "# Page title" in text
    assert "Readable main text" in text
    assert "menu noise" not in text and "footer noise" not in text


def test_reader_selection_and_fallback(monkeypatch):
    monkeypatch.setattr(check, "_jina", lambda _url: "J" * 210)
    monkeypatch.setattr(check, "_direct", lambda _url: "direct text")
    content, meta = check.fetch_url("https://example.test", "auto")
    assert content.startswith("J") and meta["reader"] == "jina"
    monkeypatch.setattr(check, "_jina", lambda _url: (_ for _ in ()).throw(OSError("offline")))
    content, meta = check.fetch_url("https://example.test", "auto")
    assert content == "direct text" and meta["fallback_reason"].startswith("Jina failed")
    with pytest.raises(OSError):
        check.fetch_url("https://example.test", "jina")
    monkeypatch.setattr(check, "_jina", lambda _url: pytest.fail("direct must not call Jina"))
    assert check.fetch_url("https://example.test", "direct")[1]["reader"] == "direct"


@pytest.mark.parametrize("failure", [
    lambda: (_ for _ in ()).throw(OSError("network")),
    lambda: (_ for _ in ()).throw(ValueError("HTTP 503")),
    lambda: (_ for _ in ()).throw(ValueError("Jina code 500")),
    lambda: (_ for _ in ()).throw(ValueError("source HTTP status 404")),
    lambda: (_ for _ in ()).throw(ValueError("content under 200 characters")),
])
def test_auto_fallback_reasons(monkeypatch, failure):
    monkeypatch.setattr(check, "_jina", lambda _url: failure())
    monkeypatch.setattr(check, "_direct", lambda _url: "fallback")
    assert check.fetch_url("https://example.test", "auto")[0] == "fallback"


@pytest.mark.parametrize("change", ["code", "httpStatus", "short"])
def test_auto_fallbacks_for_jina_payload_status_and_content(monkeypatch, change):
    payload = json.loads(json.dumps(JINA))
    if change == "code":
        payload["code"] = 503
    elif change == "httpStatus":
        payload["data"]["httpStatus"] = 404
    else:
        payload["data"]["content"] = "too short"
    monkeypatch.setattr(check, "_jina", lambda _url: check._parse_jina_response(payload))
    monkeypatch.setattr(check, "_direct", lambda _url: "direct fallback")
    content, meta = check.fetch_url("https://example.test", "auto")
    assert content == "direct fallback"
    assert meta["reader"] == "direct" and meta["fallback_reason"]


def test_jina_fixture_shape_and_json_output(monkeypatch, capsys):
    data = JINA.get("data", {})
    assert isinstance(data.get("content"), str)
    monkeypatch.setattr(check, "_jina", lambda _url: data["content"])
    monkeypatch.setattr(check, "_direct", lambda _url: pytest.fail("unexpected fallback"))
    assert cli.main(["check", "--reader", "jina", "https://example.com", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["targets"][0]["reader"] == "jina"
    assert payload["blocking"] == 1


def test_chat_mode_and_exit_codes(capsys):
    assert cli.main(["check", "--as", "chat", "--text", "# Background\n\nA short detail."]) == 1
    assert "findings:" in capsys.readouterr().out
    assert cli.main(["check", "--text", "A clear sentence."]) == 0


def test_code_checks_comments_and_docstrings_only(tmp_path, capsys):
    path = tmp_path / "sample.py"
    path.write_text('''"""This docstring is definitely very very long and contains extra words; it explains the module."""\nutilize_value = 1\n# Use the value; then return it.\n''')
    assert cli.main(["check", str(path)]) == 1
    assert "utilize_value" not in capsys.readouterr().out


def test_clipboard_is_mocked(monkeypatch, capsys):
    class Result:
        stdout = b"A clear sentence."
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    assert cli.main(["check", "--clip"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("Result", (), {"stdout": b""})())
    assert cli.main(["check", "--clip"]) == 2
    assert "clipboard is empty" in capsys.readouterr().err
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert cli.main(["check", "--clip"]) == 2
    assert "wl-paste" in capsys.readouterr().err
