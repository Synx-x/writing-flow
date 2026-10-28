from writing_flow import cli


def test_check_flags_bad_fixture(capsys):
    assert cli.main(["check", "tests/fixtures/bad.md"]) == 1
    assert "bad.md:" in capsys.readouterr().out


def test_check_passes_good_fixture():
    assert cli.main(["check", "tests/fixtures/good.md"]) == 0


def test_check_skips_every_output_style(capsys):
    from pathlib import Path

    styles = sorted(Path("output-styles").glob("*.md"))
    assert styles
    assert cli.main(["check", "output-styles"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(styles)
    assert all(": skipped (guard_style self-reference exemption)" in line for line in lines)
