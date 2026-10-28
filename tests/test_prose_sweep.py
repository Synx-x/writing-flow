"""prose_sweep.py: mtime-scoped file discovery, deterministic tier-1 rewrite,
journalled apply, dry-run by default.
"""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
sys.path.insert(0, str(ROOT / "hooks"))

from writing_flow import sweep as ps


# ---- discover_files: mtime scope and exclusions ----

def test_discovers_recent_markdown(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() in found


def test_skips_old_file(tmp_path):
    f = tmp_path / "old.md"
    f.write_text("hello\n", encoding="utf-8")
    old = time.time() - 30 * 86400
    import os
    os.utime(f, (old, old))
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


def test_skips_non_markdown(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


@pytest.mark.parametrize("subdir", [".git", "node_modules", "__pycache__"])
def test_skips_excluded_directories(tmp_path, subdir):
    d = tmp_path / subdir
    d.mkdir()
    f = d / "a.md"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


def test_skips_plugin_cache_glob(tmp_path):
    d = tmp_path / ".claude" / "plugins" / "cache" / "x"
    d.mkdir(parents=True)
    f = d / "a.md"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


def test_skips_retrospective_md(tmp_path):
    f = tmp_path / "retrospective.md"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


def test_skips_archive_directory(tmp_path):
    d = tmp_path / "docs" / "archive"
    d.mkdir(parents=True)
    f = d / "old-snapshot.md"
    f.write_text("hello\n", encoding="utf-8")
    found = ps.discover_files([str(tmp_path)], days=15)
    assert f.resolve() not in found


# ---- rewrite_tier1: deterministic stage ----

def test_rewrite_tier1_swaps_literal_word():
    body = "We should leverage the new tool.\n"
    new_body, count = ps.rewrite_tier1(body)
    assert count == 1
    assert "use the new tool" in new_body


def test_rewrite_tier1_fixes_article_agreement():
    body = "This is an actionable plan.\n"
    new_body, count = ps.rewrite_tier1(body)
    assert count == 1
    assert new_body == "This is a practical plan.\n"


def test_rewrite_tier1_skips_fenced_code():
    body = "```\nleverage_ratio = 2\n```\n"
    new_body, count = ps.rewrite_tier1(body)
    assert count == 0
    assert new_body == body


def test_rewrite_tier1_skips_inline_code_span():
    body = "The `leverage` variable is named that on purpose.\n"
    new_body, count = ps.rewrite_tier1(body)
    assert count == 0
    assert new_body == body


def test_rewrite_tier1_no_change_returns_same_text():
    body = "Clean prose with nothing to fix.\n"
    new_body, count = ps.rewrite_tier1(body)
    assert count == 0
    assert new_body == body


# ---- scan_file: em-dash and residue are reported, never rewritten ----

def test_scan_file_reports_but_does_not_rewrite_em_dash(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("a—b c—d e—f g—h i—j k—l m—n o—p q—r s—t.\n" * 3, encoding="utf-8")
    r = ps.scan_file(f)
    assert r["em_dash_findings"]
    assert r["_rewritten"] == r["_original"]


def test_scan_file_reports_but_does_not_rewrite_residue(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("We decided to keep this pattern.\n", encoding="utf-8")
    r = ps.scan_file(f)
    assert r["residue_findings"]
    assert r["_rewritten"] == r["_original"]


# ---- apply: dry-run default, journalled write ----

def test_apply_writes_only_when_apply_flag_given(tmp_path, monkeypatch):
    f = tmp_path / "a.md"
    f.write_text("We should leverage this.\n", encoding="utf-8")
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path / "local"))

    import subprocess
    dry = subprocess.run(
        [sys.executable, "-c", "from writing_flow.sweep import main; raise SystemExit(main())",
         "--roots", str(tmp_path), "--days", "15"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "WRITING_FLOW_STATE_DIR": str(tmp_path / "local"),
             "PYTHONPATH": str(ROOT / "src")},
    )
    assert "leverage" in f.read_text(encoding="utf-8")
    assert "dry-run only" in dry.stdout

    applied = subprocess.run(
        [sys.executable, "-c", "from writing_flow.sweep import main; raise SystemExit(main())",
         "--roots", str(tmp_path), "--days", "15", "--apply"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "WRITING_FLOW_STATE_DIR": str(tmp_path / "local"),
             "PYTHONPATH": str(ROOT / "src")},
    )
    assert "leverage" not in f.read_text(encoding="utf-8")
    assert "applied" in applied.stdout


def test_apply_journals_before_and_after(tmp_path, monkeypatch):
    f = tmp_path / "a.md"
    original = "We should leverage this.\n"
    f.write_text(original, encoding="utf-8")
    local_dir = tmp_path / "local"
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(local_dir))
    sys.path.insert(0, str(ROOT / "src"))
    import writing_flow.config as local_config
    import importlib
    importlib.reload(local_config)
    importlib.reload(ps)

    r = ps.scan_file(f)
    ps.apply_one(r)

    reverts = (local_dir / "reverts.jsonl").read_text(encoding="utf-8")
    rec = json.loads(reverts.strip().splitlines()[-1])
    assert rec["target"] == str(f)
    assert rec["before"] == original
    assert "use this" in rec["after"]


def test_apply_skips_unchanged_files(tmp_path, monkeypatch):
    f = tmp_path / "a.md"
    f.write_text("Nothing to fix here.\n", encoding="utf-8")
    local_dir = tmp_path / "local"
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(local_dir))
    r = ps.scan_file(f)
    ps.apply_one(r)
    assert not (local_dir / "reverts.jsonl").exists()
