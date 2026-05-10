"""Tests for the `sable check` command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from sable.cli import main


def test_check_reports_old_relational_operator(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL001" in result.output


def test_check_fix_rewrites_relational_operator(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "if (A == B) then\nend if\n"


def test_check_reports_end_keyword_form(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A == B) then\nendif\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL002" in result.output


def test_check_fix_rewrites_end_keyword_form(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A == B) then\nendif\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "if (A == B) then\nend if\n"


def test_check_reports_missing_double_colon(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("integer x\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL003" in result.output


def test_check_fix_inserts_double_colon(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("integer x\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "integer :: x\n"


def test_check_reports_semicolon_split(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("x = 1; y = 2\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL004" in result.output


def test_check_fix_splits_semicolon_statement(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("x = 1; y = 2\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "x = 1\ny = 2\n"


def test_check_reports_trailing_whitespace_and_newline_style(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("x = 1  ", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL005" in result.output


def test_check_fix_normalizes_trailing_whitespace_and_newline(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("x = 1  ", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "x = 1\n"


def test_check_reports_tab_indentation(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("\tif (A == B) then\n\tend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL009" in result.output


def test_check_fix_replaces_tab_indentation(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("\tif (A == B) then\n\tend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "   if (A == B) then\n   end if\n"


def test_check_reports_stray_leading_continuation(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("&x = 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL010" in result.output


def test_check_fix_removes_stray_leading_continuation(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("& x = 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "x = 1\n"


def test_check_allows_valid_leading_continuation_with_previous_ampersand(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("call foo( &\n& x)\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL010", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_valid_string_continuation_with_exclamation_mark(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "call output%error_msg('Tried to initialize memory tracker for "
        "batching loop, &\n"
        "                      &but the memory manager is already in "
        "batching mode! &\n"
        "                      &Have you forgotten to finalize the previous "
        "batching loop?')\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL010", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_reports_unused_use_only_import(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: dp, unused_kind\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(src)])

    assert result.exit_code == 1
    assert "SBL201" in result.output
    assert "unused_kind" in result.output
    assert "dp" not in result.output


def test_check_fix_keeps_unused_use_only_import_without_unsafe(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: dp, unused_kind\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", "--select", "SBL201", str(src)])

    assert result.exit_code == 1
    assert "unused_kind" in src.read_text(encoding="utf-8")


def test_check_unsafe_fix_removes_unused_use_only_import_item(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: dp, unused_kind, wp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "   real(wp) :: y\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--fix", "--unsafe-fixes", "--select", "SBL201", str(src)]
    )

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == (
        "module example\n"
        "   use constants, only: dp, wp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "   real(wp) :: y\n"
        "end module example\n"
    )


def test_check_unsafe_fix_removes_adjacent_unused_use_only_import_items(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: unused_a, unused_b, dp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--fix", "--unsafe-fixes", "--select", "SBL201", str(src)]
    )

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == (
        "module example\n"
        "   use constants, only: dp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "end module example\n"
    )


def test_check_unsafe_fix_removes_adjacent_middle_use_only_import_items(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: dp, unused_a, unused_b, wp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "   real(wp) :: y\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--fix", "--unsafe-fixes", "--select", "SBL201", str(src)]
    )

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == (
        "module example\n"
        "   use constants, only: dp, wp\n"
        "   implicit none\n"
        "   real(dp) :: x\n"
        "   real(wp) :: y\n"
        "end module example\n"
    )


def test_check_unsafe_fix_removes_unused_use_only_import_statement(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: unused_kind\n"
        "   implicit none\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--fix", "--unsafe-fixes", "--select", "SBL201", str(src)]
    )

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == (
        "module example\n" "   implicit none\n" "end module example\n"
    )


def test_check_allows_renamed_use_only_import_when_local_name_is_used(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use constants, only: wp => working_precision\n"
        "   implicit none\n"
        "   real(wp) :: x\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_use_only_import_used_in_extends(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use base_class, only: base_type\n"
        "   implicit none\n"
        "   type, extends(base_type) :: derived_type\n"
        "   end type derived_type\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_use_only_import_used_as_binding_interface(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "module example\n"
        "   use interfaces, only: execute\n"
        "   implicit none\n"
        "   type :: worker\n"
        "   contains\n"
        "      procedure(execute), deferred :: run\n"
        "   end type worker\n"
        "end module example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_use_only_import_used_in_openmp_sentinel(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "subroutine example()\n"
        "   use omp_lib, only: omp_get_thread_num\n"
        "   implicit none\n"
        "   integer :: i_thread\n"
        "   i_thread = 1\n"
        "   !$ i_thread = omp_get_thread_num() + 1\n"
        "end subroutine example\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_use_only_import_used_by_submodule(tmp_path):
    parent = tmp_path / "parent.F90"
    child = tmp_path / "child.F90"
    parent.write_text(
        "module parent_module\n"
        "   use timings_class, only: timings\n"
        "   implicit none\n"
        "   interface\n"
        "      module subroutine run()\n"
        "      end subroutine run\n"
        "   end interface\n"
        "end module parent_module\n",
        encoding="utf-8",
    )
    child.write_text(
        "submodule (parent_module) child_module\n"
        "   implicit none\n"
        "contains\n"
        "   module procedure run\n"
        "      type(timings) :: timer\n"
        "   end procedure run\n"
        "end submodule child_module\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(tmp_path)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_allows_use_only_import_reexported_to_another_module(tmp_path):
    provider = tmp_path / "provider.F90"
    forwarded = tmp_path / "forwarded.F90"
    consumer = tmp_path / "consumer.F90"
    provider.write_text(
        "module provider\n"
        "   implicit none\n"
        "   integer, parameter :: exported_kind = 4\n"
        "end module provider\n",
        encoding="utf-8",
    )
    forwarded.write_text(
        "module forwarded\n"
        "   use provider, only: exported_kind\n"
        "   implicit none\n"
        "end module forwarded\n",
        encoding="utf-8",
    )
    consumer.write_text(
        "module consumer\n"
        "   use forwarded, only: exported_kind\n"
        "   implicit none\n"
        "   real(exported_kind) :: x\n"
        "end module consumer\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL201", str(tmp_path)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_json_output(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--output-format", "json", str(src)])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["diagnostics"][0]["rule_id"] == "SBL001"
    assert payload["diagnostics"][0]["path"].endswith("example.f90")


def test_check_select_and_ignore_controls(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nendif\n", encoding="utf-8")

    runner = CliRunner()
    selected = runner.invoke(main, ["check", "--select", "SBL001", str(src)])
    ignored = runner.invoke(main, ["check", "--ignore", "SBL001", str(src)])

    assert selected.exit_code == 1
    assert "SBL001" in selected.output
    assert "SBL002" not in selected.output
    assert ignored.exit_code == 1
    assert "SBL001" not in ignored.output
    assert "SBL002" in ignored.output


def test_check_rule_set_style_only_reports_style_rules(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--rule-set", "style", str(src)])

    assert result.exit_code == 1
    assert "SBL001" in result.output
    assert "SBL101" not in result.output


def test_check_rule_set_lint_only_reports_lint_rules(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--rule-set", "lint", str(src)])

    assert result.exit_code == 1
    assert "SBL101" in result.output
    assert "SBL001" not in result.output


def test_check_rule_set_all_reports_style_and_lint_rules(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--rule-set", "all", str(src)])

    assert result.exit_code == 1
    assert "SBL001" in result.output
    assert "SBL101" in result.output


def test_check_select_overrides_rule_set(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--rule-set", "lint", "--select", "SBL001", str(src)]
    )

    assert result.exit_code == 1
    assert "SBL001" in result.output
    assert "SBL101" not in result.output


def test_check_reports_missing_implicit_none(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("program p\nprint *, 1\nend program p\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL101" in result.output


def test_check_reports_missing_implicit_none_for_module_with_contained_procedure(
    tmp_path,
):
    src = tmp_path / "example.f90"
    src.write_text(
        (
            "module m\n"
            "contains\n"
            "   subroutine s()\n"
            "      implicit none\n"
            "   end subroutine s\n"
            "end module m\n"
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL101", str(src)])

    assert result.exit_code == 1
    assert "SBL101" in result.output


def test_check_reports_missing_implicit_none_for_program_with_internal_procedure(
    tmp_path,
):
    src = tmp_path / "example.f90"
    src.write_text(
        (
            "program p\n"
            "contains\n"
            "   subroutine s()\n"
            "      implicit none\n"
            "   end subroutine s\n"
            "end program p\n"
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL101", str(src)])

    assert result.exit_code == 1
    assert "SBL101" in result.output


def test_check_fix_does_not_apply_unsafe_without_flag(tmp_path):
    src = tmp_path / "example.f90"
    original = "program p\nprint *, 1\nend program p\n"
    src.write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", str(src)])

    assert result.exit_code == 1
    assert src.read_text(encoding="utf-8") == original


def test_check_fix_applies_unsafe_with_flag(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("program p\nprint *, 1\nend program p\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--fix", "--unsafe-fixes", str(src)])

    assert result.exit_code == 0
    assert (
        src.read_text(encoding="utf-8")
        == "program p\n   implicit none\nprint *, 1\nend program p\n"
    )


def test_check_reports_missing_implicit_none_in_procedure(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "subroutine foo(x)\nreal :: x\nend subroutine foo\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL102" in result.output
    assert "SBL101" not in result.output


def test_check_fix_applies_unsafe_procedure_rule(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "subroutine foo(x)\nreal :: x\nend subroutine foo\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--select", "SBL102", "--fix", "--unsafe-fixes", str(src)]
    )

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == (
        "subroutine foo(x)\n   implicit none\nreal :: x\nend subroutine foo\n"
    )


def test_check_reports_missing_intent_on_dummy_argument(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "subroutine foo(x)\nreal :: x\nend subroutine foo\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL103", str(src)])

    assert result.exit_code == 1
    assert "SBL103" in result.output
    assert "x" in result.output


def test_check_accepts_intent_on_all_dummy_arguments(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        (
            "subroutine foo(x, y)\n"
            "real, intent(in) :: x\n"
            "real, intent(out) :: y\n"
            "end subroutine foo\n"
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL103", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_check_reports_only_arguments_missing_intent(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        (
            "subroutine foo(x, y)\n"
            "real, intent(in) :: x\n"
            "real :: y\n"
            "end subroutine foo\n"
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL103", str(src)])

    assert result.exit_code == 1
    assert "Dummy argument 'y'" in result.output
    assert "Dummy argument 'x'" not in result.output


def test_inline_suppression_ignores_rule_on_line(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "if (A .EQ. B) then ! sable: ignore SBL001\nend if\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_file_suppression_ignores_rule(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "! sable: ignore-file SBL001\nif (A .EQ. B) then\nend if\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 0
    assert result.output == ""


def test_baseline_generation_and_filtering(tmp_path):
    src = tmp_path / "example.f90"
    baseline = tmp_path / "sable-baseline.json"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    gen = runner.invoke(
        main,
        ["check", "--generate-baseline", "--baseline", str(baseline), str(src)],
    )
    assert gen.exit_code == 0
    assert baseline.exists()

    filtered = runner.invoke(main, ["check", "--baseline", str(baseline), str(src)])
    assert filtered.exit_code == 0
    assert filtered.output == ""

    src.write_text("if (A .EQ. B) then; x = 1\nend if\n", encoding="utf-8")
    new_findings = runner.invoke(main, ["check", "--baseline", str(baseline), str(src)])
    assert new_findings.exit_code == 1
    assert "SBL004" in new_findings.output


def test_sarif_output(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--output-format", "sarif", str(src)])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["tool"]["driver"]["name"] == "sable"
    run = payload["runs"][0]
    assert run["artifacts"]
    assert run["tool"]["driver"]["rules"][0]["name"] == (
        "Old-style relational operator can be modernized."
    )
    assert run["tool"]["driver"]["rules"][0]["shortDescription"]["text"] == (
        "Old-style relational operator can be modernized."
    )
    sarif_result = run["results"][0]
    assert sarif_result["ruleId"] == "SBL001"
    replacement = sarif_result["fixes"][0]["artifactChanges"][0]["replacements"][0]
    assert replacement["insertedContent"]["text"] == "=="
    assert replacement["deletedRegion"]["startLine"] == 1
    assert (
        "index" in sarif_result["locations"][0]["physicalLocation"]["artifactLocation"]
    )


def test_gitlab_codequality_output(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main, ["check", "--output-format", "gitlab-codequality", str(src)]
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert payload[0]["check_name"] == "SBL001"
    assert payload[0]["severity"] == "major"
    assert payload[0]["location"]["path"].endswith("example.f90")
    assert payload[0]["location"]["lines"]["begin"] == 1
    assert payload[0]["fingerprint"]
    assert "(fix: Replace .eq. with ==)" in payload[0]["description"]


def test_check_uses_pyproject_select_default(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.sable.check]
select = ["SBL002"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nendif\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL002" in result.output
    assert "SBL001" not in result.output


def test_cli_select_overrides_pyproject_select(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.sable.check]
select = ["SBL002"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nendif\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--select", "SBL001", str(src)])

    assert result.exit_code == 1
    assert "SBL001" in result.output
    assert "SBL002" not in result.output


def test_check_uses_pyproject_fix_defaults(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.sable.check]
fix = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "example.f90"
    src.write_text("if (A .EQ. B) then\nend if\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 0
    assert src.read_text(encoding="utf-8") == "if (A == B) then\nend if\n"


def test_check_uses_pyproject_rule_set_default(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.sable.check]
rule_set = "lint"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 1
    assert "SBL101" in result.output
    assert "SBL001" not in result.output


def test_check_fix_only_applies_enabled_rule_set(tmp_path):
    src = tmp_path / "example.f90"
    src.write_text(
        "program p\nif (A .EQ. B) print *, 1\nend program p\n", encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(main, ["check", "--rule-set", "style", "--fix", str(src)])

    assert result.exit_code == 0
    assert (
        src.read_text(encoding="utf-8")
        == "program p\nif (A == B) print *, 1\nend program p\n"
    )


def test_check_uses_pyproject_unsafe_fix_defaults(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.sable.check]
fix = true
unsafe_fixes = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "example.f90"
    src.write_text("program p\nprint *, 1\nend program p\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(src)])

    assert result.exit_code == 0
    assert "implicit none" in src.read_text(encoding="utf-8")
