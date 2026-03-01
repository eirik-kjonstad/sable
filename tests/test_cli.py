"""CLI behavior tests."""

from click.testing import CliRunner

from sable.cli import main


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
