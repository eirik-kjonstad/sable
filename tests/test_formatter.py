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


class TestDirectives:
    def test_directive_at_column_zero(self):
        source = "subroutine foo()\n#ifdef USE_LIBINT\n  call bar()\n#endif\nend subroutine foo\n"
        result = fmt(source)
        lines = result.splitlines()
        ifdef_line = next(l for l in lines if "#ifdef" in l)
        endif_line = next(l for l in lines if "#endif" in l)
        assert ifdef_line == "#ifdef USE_LIBINT"
        assert endif_line == "#endif"

    def test_directive_not_mangled(self):
        source = "#ifdef USE_LIBINT\nx = 1\n#endif\n"
        result = fmt(source)
        assert "#ifdef USE_LIBINT" in result
        assert "#endif" in result
        assert "#end if" not in result

    def test_define_at_column_zero(self):
        source = "module m\n#define MAX 100\nend module m\n"
        result = fmt(source)
        lines = result.splitlines()
        define_line = next(l for l in lines if "#define" in l)
        assert define_line == "#define MAX 100"


class TestKeywordParenSpacing:
    def test_if_space_before_paren(self):
        assert "if (a)" in fmt("if(a) x = 1")

    def test_if_space_before_then(self):
        result = fmt("if(x > 0)then\ny = 1\nend if")
        assert "if (x > 0) then" in result

    def test_elseif_space(self):
        result = fmt("if(a)then\nx=1\nelseif(b)then\nx=2\nend if")
        assert "elseif (b) then" in result

    def test_do_while_space(self):
        assert "do while (n > 0)" in fmt("do while(n > 0)\nend do")

    def test_no_space_in_type_declaration(self):
        assert "integer(8)" in fmt("integer(8) :: n")

    def test_no_space_in_real_kind(self):
        assert "real(8)" in fmt("real(8) :: x")

    def test_no_space_in_type_variable(self):
        assert "type(mytype)" in fmt("type(mytype) :: obj")

    def test_function_result_clause_space(self):
        result = fmt("function foo(x)result(y)\nend function foo\n")
        assert "function foo(x) result(y)" in result

    def test_result_assignment_unaffected(self):
        # 'result' used as a variable name inside a body should not gain extra spaces
        result = fmt("result = x + 1")
        assert "result = x + 1" in result


class TestSingleLineIf:
    def test_short_if_stays_on_one_line(self):
        # Fits within the default line length — no split applied.
        result = fmt("if (x > 0) x = x + 1")
        assert result.strip() == "if (x > 0) x = x + 1"

    def test_compact_if_normalised_stays_on_one_line(self):
        # After normalisation "if(x>0)x=1" is short enough to stay on one line.
        result = fmt("if(x>0)x=1")
        assert result.strip() == "if (x > 0) x = 1"

    def test_long_if_split_with_continuation(self):
        # The action pushes the line over the limit — split at the if/action boundary.
        result = fmt("if (x > 0) x = x + 1", line_length=15)
        lines = result.splitlines()
        assert lines[0] == "if (x > 0) &"
        assert lines[1].strip() == "x = x + 1"

    def test_action_indented_one_level(self):
        result = fmt("if (x > 0) x = x + 1", line_length=15)
        lines = result.splitlines()
        assert lines[1].startswith("   ")  # one indent_width (3 spaces) deeper than 'if'

    def test_block_if_not_split(self):
        source = "if (x > 0) then\n  y = 1\nend if\n"
        result = fmt(source)
        assert " &" not in result.splitlines()[0]

    def test_call_action_long(self):
        result = fmt("if (n == 1) call foo()", line_length=15)
        assert result.splitlines()[0] == "if (n == 1) &"
        assert "call foo()" in result.splitlines()[1]

    def test_nested_parens_in_condition_long(self):
        result = fmt("if (a .and. (b .or. c)) x = 1", line_length=25)
        assert result.splitlines()[0] == "if (a .and. (b .or. c)) &"

    def test_blank_line_after_action_preserved(self):
        # Blank line after the action must survive regardless of whether the if
        # was already written in split form or as a single line.
        src_inline = "if (x > 0) x = 1\n\ny = 2\n"
        src_split  = "if (x > 0) &\n   x = 1\n\ny = 2\n"
        for src in (src_inline, src_split):
            result = fmt(src)
            lines = result.splitlines()
            action_idx = next(i for i, l in enumerate(lines) if "x = 1" in l)
            assert lines[action_idx + 1] == "", f"blank line missing in: {result!r}"


class TestRoutineSeparation:
    _base = (
        "module m\ncontains\n"
        "  subroutine foo()\n  end subroutine foo\n"
        "{gap}"
        "  subroutine bar()\n  end subroutine bar\n"
        "end module m\n"
    )

    def _between(self, result: str) -> list[str]:
        """Lines between end subroutine foo and subroutine bar."""
        lines = result.splitlines()
        a = next(i for i, l in enumerate(lines) if "end subroutine foo" in l)
        b = next(i for i, l in enumerate(lines) if "subroutine bar" in l)
        return lines[a + 1:b]

    def test_one_blank_normalized_to_two(self):
        src = self._base.format(gap="\n")
        between = self._between(fmt(src))
        assert between == ["", ""]

    def test_three_blanks_normalized_to_two(self):
        src = self._base.format(gap="\n\n\n")
        between = self._between(fmt(src))
        assert between == ["", ""]

    def test_zero_blanks_normalized_to_two(self):
        src = self._base.format(gap="")
        between = self._between(fmt(src))
        assert between == ["", ""]

    def test_comment_gap_preserved(self):
        src = self._base.format(gap="  ! note\n")
        between = self._between(fmt(src))
        # comment present: blank lines not forced
        assert any("! note" in l for l in between)
        assert len(between) == 1  # just the comment, no extra blanks injected

    def test_pure_function_detected(self):
        src = (
            "module m\ncontains\n"
            "  subroutine foo()\n  end subroutine foo\n"
            "  pure function bar(x) result(y)\n"
            "    real, intent(in) :: x\n    real :: y\n    y = x\n"
            "  end function bar\n"
            "end module m\n"
        )
        result = fmt(src)
        lines = result.splitlines()
        a = next(i for i, l in enumerate(lines) if "end subroutine foo" in l)
        b = next(i for i, l in enumerate(lines) if "pure function bar" in l)
        assert lines[a + 1:b] == ["", ""]


class TestCommentIndentation:
    def test_comment_follows_next_code_indent(self):
        source = "subroutine foo()\n! doc\nimplicit none\nend subroutine foo\n"
        result = fmt(source)
        lines = result.splitlines()
        comment_line = next(l for l in lines if "! doc" in l)
        implicit_line = next(l for l in lines if "implicit none" in l)
        assert comment_line.index("!") == implicit_line.index("i")

    def test_comment_before_end_dedents(self):
        source = "if (x) then\n  y = 1\n  ! done\nend if\n"
        result = fmt(source)
        lines = result.splitlines()
        comment_line = next(l for l in lines if "! done" in l)
        end_line = next(l for l in lines if "end if" in l)
        assert len(comment_line) - len(comment_line.lstrip()) == \
               len(end_line) - len(end_line.lstrip())

    def test_blank_line_between_comment_and_code_preserved(self):
        source = "! note\n\nx = 1\n"
        result = fmt(source)
        lines = result.splitlines()
        comment_idx = next(i for i, l in enumerate(lines) if "! note" in l)
        code_idx = next(i for i, l in enumerate(lines) if "x = 1" in l)
        assert code_idx - comment_idx == 2  # blank line between them


class TestBlankLines:
    def test_blank_lines_preserved(self):
        source = "x = 1\n\ny = 2\n"
        result = fmt(source)
        assert "\n\n" in result

    def test_multiple_blank_lines_preserved(self):
        source = "x = 1\n\n\ny = 2\n"
        result = fmt(source)
        lines = result.splitlines()
        blank_count = sum(1 for l in lines if l.strip() == "")
        assert blank_count >= 2

    def test_blank_lines_not_added(self):
        source = "x = 1\ny = 2\n"
        result = fmt(source)
        assert "\n\n" not in result


class TestArgListExpansion:
    """One-argument-per-line explosion for long parenthesised argument lists."""

    def test_long_call_explodes(self):
        src = "call some_subroutine(argument_alpha, argument_beta, argument_gamma, argument_delta)\n"
        result = fmt(src, line_length=60)
        lines = result.splitlines()
        # Opening line ends with &
        assert lines[0].startswith("call some_subroutine(") and lines[0].endswith(" &")
        # Each argument on its own line with , and &
        assert "argument_alpha," in lines[1] and lines[1].endswith(" &")
        assert "argument_beta," in lines[2] and lines[2].endswith(" &")
        assert "argument_gamma," in lines[3] and lines[3].endswith(" &")
        # Last argument has no comma, still has &
        assert "argument_delta" in lines[4] and lines[4].endswith(" &")
        # Closing ) on its own line at original indent
        assert lines[5] == ")"
        # All & symbols are vertically aligned (same column)
        amp_cols = [line.rindex("&") for line in lines[:5]]
        assert len(set(amp_cols)) == 1

    def test_short_call_stays_single_line(self):
        result = fmt("call foo(a, b, c)\n")
        assert result.strip() == "call foo(a, b, c)"

    def test_single_arg_not_exploded(self):
        # Only one argument — no comma, so explosion does not apply.
        # The greedy splitter is used instead; no ", &" continuation lines appear.
        src = "x = some_very_long_function_name(some_very_long_argument_name_that_makes_it_too_long)\n"
        result = fmt(src, line_length=60)
        assert ", &" not in result

    def test_if_condition_not_exploded(self):
        # Control-flow parens must never be exploded
        src = "if (alpha .and. beta .and. gamma .and. delta .and. epsilon) then\n  x = 1\nend if\n"
        result = fmt(src, line_length=40)
        assert "( &" not in result

    def test_function_definition_explodes(self):
        src = "function compute(alpha_in, beta_in, gamma_in, delta_in) result(out)\n  out = 0.0\nend function compute\n"
        result = fmt(src, line_length=60)
        lines = result.splitlines()
        assert lines[0].startswith("function compute(") and lines[0].endswith(" &")
        # Closing ) with result clause at original indent, on its own line
        close_line = next(l for l in lines if l.startswith(") result"))
        assert close_line == ") result(out)"

    def test_trailing_comment_on_close_line(self):
        src = "call foo(long_arg_one, long_arg_two, long_arg_three) ! important\n"
        result = fmt(src, line_length=40)
        lines = result.splitlines()
        # Comment goes on the closing ) line
        assert lines[-1].startswith(")") and "! important" in lines[-1]

    def test_expanded_is_idempotent(self):
        src = "call some_subroutine(argument_alpha, argument_beta, argument_gamma, argument_delta)\n"
        once = fmt(src, line_length=60)
        twice = fmt(once, line_length=60)
        assert once == twice


class TestStringHandling:
    """String literals must never be reformatted."""

    def test_instring_continuation_preserved_single_arg(self):
        # A string with Fortran & continuation inside must be output verbatim.
        src = 'call log("Hello this is a string &\n&that continues on a new line")\n'
        result = fmt(src, line_length=60)
        assert '"Hello this is a string &' in result
        assert "&that continues on a new line" in result
        # The closing ) must appear on the last line, not pushed to its own line
        # by the formatter's greedy splitter.
        assert result.rstrip("\n").endswith('")')

    def test_instring_continuation_preserved_multi_arg(self):
        # When mixed with other args the whole statement is output verbatim.
        src = 'call log(level, "Hello this is a string &\n&that continues")\n'
        result = fmt(src, line_length=60)
        assert '"Hello this is a string &' in result
        assert "&that continues" in result

    def test_instring_continuation_idempotent(self):
        src = 'call log(level, "first part &\n&second part")\n'
        once = fmt(src, line_length=60)
        twice = fmt(once, line_length=60)
        assert once == twice

    def test_long_string_does_not_dominate_alignment(self):
        # A 70-char string arg must not push & for shorter args to column 70+.
        src = 'call log(level, "' + "x" * 70 + '")\n'
        result = fmt(src, line_length=60)
        lines = result.splitlines()
        level_line = next(l for l in lines if "level" in l)
        assert level_line.rindex("&") < 60


class TestLongArgContinuation:
    """Long individual arguments inside an exploded list are split with greedy continuation."""

    def test_long_arg_split_with_continuation(self):
        # The second argument is a long expression that exceeds the line limit.
        src = (
            "call foo(short, alpha_var + beta_var + gamma_var + delta_var + epsilon_var, other)\n"
        )
        result = fmt(src, line_length=40)
        lines = result.splitlines()
        # The long argument must be split across multiple lines
        assert sum(1 for l in lines if "alpha_var" in l or "beta_var" in l
                   or "gamma_var" in l or "delta_var" in l or "epsilon_var" in l) > 1
        # Continuation lines for the long arg are at a deeper indent than the other args
        arg_lines = [l for l in lines if any(
            v in l for v in ("alpha_var", "beta_var", "gamma_var", "delta_var", "epsilon_var")
        )]
        indents = [len(l) - len(l.lstrip()) for l in arg_lines]
        assert max(indents) > min(indents)  # deeper lines exist

    def test_long_arg_all_lines_end_with_continuation(self):
        src = (
            "call foo(short, alpha_var + beta_var + gamma_var + delta_var + epsilon_var, other)\n"
        )
        result = fmt(src, line_length=40)
        lines = result.splitlines()
        # Every line except the closing ) must end with ' &'
        for line in lines[:-1]:
            assert line.endswith(" &"), f"Expected ' &' at end of: {line!r}"

    def test_long_arg_comma_on_last_piece(self):
        # The comma for a split argument must appear on its final piece, not before.
        src = (
            "call foo(short, alpha_beta_gamma_delta + epsilon_zeta_eta_theta, other)\n"
        )
        result = fmt(src, line_length=40)
        lines = result.splitlines()
        # Find all lines containing parts of the long arg expression
        expr_lines = [l for l in lines if any(
            t in l for t in ("alpha_beta", "epsilon_zeta")
        )]
        # Only the last piece of the expression should have a comma
        last = expr_lines[-1]
        others = expr_lines[:-1]
        assert "," in last
        for line in others:
            # Strip trailing ' &' before checking — no comma should appear there
            assert "," not in line.rstrip(" &")

    def test_long_arg_continuation_idempotent(self):
        src = (
            "call foo(short, alpha_var + beta_var + gamma_var + delta_var + epsilon_var, other)\n"
        )
        once = fmt(src, line_length=40)
        twice = fmt(once, line_length=40)
        assert once == twice


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
