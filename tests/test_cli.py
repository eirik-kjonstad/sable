"""CLI behavior tests."""

from click.testing import CliRunner

import sable.cli as cli
from sable.cli import main


def test_formats_file_in_place_and_reports_changed(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("INTEGER::X\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [str(src)])

    assert result.exit_code == 0
    assert "example.f90" in result.output
    assert "1 file reformatted" in result.output
    assert src.read_text(encoding="utf-8") == "integer :: X\n"


def test_check_mode_reports_would_change_and_does_not_write(tmp_path):
    src = tmp_path / "example.f90"
    original = "INTEGER::X\n"
    src.write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["--check", str(src)])

    assert result.exit_code == 1
    assert "example.f90" in result.output
    assert "would be reformatted" in result.output
    assert src.read_text(encoding="utf-8") == original


def test_check_mode_success_for_preformatted_file(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("integer :: x\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["--check", str(src)])

    assert result.exit_code == 0
    assert "already formatted" in result.output


def test_diff_mode_prints_unified_diff_without_writing(tmp_path):
    src = tmp_path / "example.f90"
    original = "INTEGER::X\n"
    src.write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["--diff", str(src)])

    assert result.exit_code == 0
    assert "--- a/" in result.output
    assert "+++ b/" in result.output
    assert "-INTEGER::X" in result.output
    assert "+integer :: X" in result.output
    assert src.read_text(encoding="utf-8") == original


def test_formats_stdin_to_stdout_without_summary():
    runner = CliRunner()
    result = runner.invoke(main, [], input="INTEGER::X\n")

    assert result.exit_code == 0
    assert result.output == "integer :: X\n"
    assert "All done!" not in result.output


def test_stdin_filename_used_in_check_output():
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--check", "--stdin-filename", "stdin_file.f90"],
        input="INTEGER::X\n",
    )

    assert result.exit_code == 1
    assert "stdin_file.f90" in result.output
    assert "would be reformatted" in result.output


def test_directory_walk_formats_supported_suffixes_recursively(tmp_path):
    root = tmp_path / "src"
    nested = root / "nested"
    nested.mkdir(parents=True)

    f90 = root / "a.f90"
    f95 = nested / "b.f95"
    txt = nested / "notes.txt"

    f90.write_text("INTEGER::X\n", encoding="utf-8")
    f95.write_text("INTEGER::Y\n", encoding="utf-8")
    txt_original = "INTEGER::Z\n"
    txt.write_text(txt_original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [str(root)])

    assert result.exit_code == 0
    assert "a.f90" in result.output
    assert "b.f95" in result.output
    assert "notes.txt" not in result.output
    assert f90.read_text(encoding="utf-8") == "integer :: X\n"
    assert f95.read_text(encoding="utf-8") == "integer :: Y\n"
    assert txt.read_text(encoding="utf-8") == txt_original


def test_formatter_exception_is_reported_without_traceback(tmp_path, monkeypatch):
    src = tmp_path / "bad.f90"
    src.write_text("integer :: x\n", encoding="utf-8")

    def boom(_source, _cfg):
        raise RuntimeError("format explode")

    monkeypatch.setattr(cli, "format_source", boom)

    runner = CliRunner()
    result = runner.invoke(main, [str(src)])

    assert result.exit_code == 123
    assert "bad.f90" in result.output
    assert "format explode" in result.output
    assert "Traceback" not in result.output


def test_non_utf8_file_is_reported_without_traceback(tmp_path):
    good = tmp_path / "good.f90"
    bad = tmp_path / "bad.f90"

    good.write_text("INTEGER :: X\n", encoding="utf-8")
    bad.write_bytes(b"integer :: x\n! invalid: \xe6\n")

    runner = CliRunner()
    result = runner.invoke(main, [str(tmp_path)])

    assert result.exit_code == 123
    assert "bad.f90" in result.output
    assert "can't decode byte" in result.output
    assert "Traceback" not in result.output
    assert "good.f90" in result.output
