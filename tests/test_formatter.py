"""Tests for the sable formatting engine."""

import pytest
from sable.formatter import format_source, FormatConfig


def fmt(source: str, **kwargs) -> str:
    cfg = FormatConfig(**kwargs) if kwargs else None
    return format_source(source, cfg)


class TestKeywordCasing:
    def test_keywords_lowercased_by_default(self):
        result = fmt("INTEGER :: x")
        assert "integer" in result
        assert "INTEGER" not in result

    def test_keywords_upper_when_configured(self):
        result = fmt("integer :: x", keyword_case="upper")
        assert "INTEGER" in result

    def test_name_case_preserved(self):
        result = fmt("MyVariable = 1")
        assert "MyVariable" in result


class TestEndKeywords:
    def test_compact_to_spaced_endif(self):
        source = "if (x) then\n  y = 1\nendif"
        result = fmt(source)
        assert "end if" in result
        assert "endif" not in result

    def test_compact_to_spaced_enddo(self):
        source = "do i = 1, 10\nenddo"
        result = fmt(source)
        assert "end do" in result
        assert "enddo" not in result

    def test_spaced_stays_spaced(self):
        source = "do i = 1, 10\nend do"
        result = fmt(source)
        assert "end do" in result

    def test_compact_form_when_configured(self):
        source = "if (x) then\n  y = 1\nend if"
        result = fmt(source, end_keyword_form="compact")
        assert "endif" in result
        assert "end if" not in result


class TestOperatorNormalisation:
    def test_old_eq_becomes_modern(self):
        result = fmt("if (a .EQ. b)")
        assert "==" in result
        assert ".EQ." not in result
        assert ".eq." not in result

    def test_old_ne_becomes_modern(self):
        result = fmt("if (a .NE. b)")
        assert "/=" in result

    def test_old_lt_becomes_modern(self):
        result = fmt("if (a .LT. b)")
        assert "<" in result

    def test_old_ge_becomes_modern(self):
        result = fmt("if (a .GE. b)")
        assert ">=" in result

    def test_no_normalise_when_disabled(self):
        result = fmt("if (a .EQ. b)", normalize_operators=False)
        assert ".eq." in result


class TestTrailingNewline:
    def test_adds_trailing_newline(self):
        result = fmt("x = 1")
        assert result.endswith("\n")

    def test_no_double_newline(self):
        result = fmt("x = 1\n")
        assert result == result.rstrip("\n") + "\n"


class TestSpacing:
    def test_space_around_assignment(self):
        result = fmt("x=1")
        assert "x = 1" in result

    def test_space_after_comma(self):
        result = fmt("call foo(a,b,c)")
        assert "a, b, c" in result

    def test_no_space_inside_parens(self):
        result = fmt("call foo( a, b )")
        # Should not have space right inside the parens
        assert "foo(a" in result

    def test_no_space_around_percent(self):
        result = fmt("x = obj%field")
        assert "obj%field" in result

    def test_no_space_around_power(self):
        result = fmt("y = x**2")
        assert "x**2" in result


class TestIndentation:
    def test_do_body_indented(self):
        source = "do i = 1, 10\nx = i\nend do"
        result = fmt(source)
        lines = result.splitlines()
        # The body line should be indented
        body_line = next(l for l in lines if "x = i" in l)
        assert body_line.startswith("  ")

    def test_if_body_indented(self):
        source = "if (x > 0) then\ny = 1\nend if"
        result = fmt(source)
        lines = result.splitlines()
        body_line = next(l for l in lines if "y = 1" in l)
        assert body_line.startswith("  ")

    def test_nested_indentation(self):
        source = "do i = 1, 10\ndo j = 1, 10\nx = i + j\nend do\nend do"
        result = fmt(source)
        lines = result.splitlines()
        body_line = next(l for l in lines if "x = i + j" in l)
        assert body_line.startswith("    ")  # 2 levels * 2 spaces

    def test_type_contains_end_type_same_indent(self):
        source = (
            "type :: mytype\n"
            "  integer :: x\n"
            "contains\n"
            "  procedure :: foo\n"
            "end type mytype\n"
        )
        result = fmt(source)
        lines = result.splitlines()
        type_line = next(l for l in lines if l.lstrip().startswith("type ::"))
        contains_line = next(l for l in lines if l.strip() == "contains")
        end_type_line = next(l for l in lines if "end type" in l)
        type_indent = len(type_line) - len(type_line.lstrip())
        assert len(contains_line) - len(contains_line.lstrip()) == type_indent
        assert len(end_type_line) - len(end_type_line.lstrip()) == type_indent

    def test_module_contains_end_module_same_indent(self):
        source = (
            "module mymod\n"
            "  implicit none\n"
            "contains\n"
            "  subroutine foo()\n"
            "  end subroutine foo\n"
            "end module mymod\n"
        )
        result = fmt(source)
        lines = result.splitlines()
        module_line = next(l for l in lines if l.lstrip().startswith("module "))
        contains_line = next(l for l in lines if l.strip() == "contains")
        end_module_line = next(l for l in lines if "end module" in l)
        module_indent = len(module_line) - len(module_line.lstrip())
        assert len(contains_line) - len(contains_line.lstrip()) == module_indent
        assert len(end_module_line) - len(end_module_line.lstrip()) == module_indent


class TestIdempotency:
    """Formatting the output of format_source should produce the same result."""

    def test_simple_assignment(self):
        source = "x = 1"
        once = fmt(source)
        twice = fmt(once)
        assert once == twice

    def test_do_loop(self):
        source = "do i = 1, n\n  result = result + array(i)\nend do\n"
        once = fmt(source)
        twice = fmt(once)
        assert once == twice

    def test_subroutine(self):
        source = (
            "subroutine foo(x, y)\n"
            "  implicit none\n"
            "  integer, intent(in) :: x\n"
            "  integer, intent(out) :: y\n"
            "  y = x * 2\n"
            "end subroutine foo\n"
        )
        once = fmt(source)
        twice = fmt(once)
        assert once == twice
