"""Tests for the Fortran lexer."""

import pytest
from sable.lexer import tokenize, iter_logical_lines
from sable.tokens import TokenKind


def kinds(source: str) -> list[TokenKind]:
    return [t.kind for t in tokenize(source) if t.kind != TokenKind.EOF]


def texts(source: str) -> list[str]:
    return [t.text for t in tokenize(source) if t.kind != TokenKind.EOF]


class TestBasicTokens:
    def test_integer(self):
        assert kinds("42") == [TokenKind.INTEGER]

    def test_real(self):
        assert kinds("3.14") == [TokenKind.REAL]

    def test_real_exponent(self):
        assert kinds("1.0e-3") == [TokenKind.REAL]

    def test_string_single(self):
        assert kinds("'hello'") == [TokenKind.STRING]

    def test_string_double(self):
        assert kinds('"world"') == [TokenKind.STRING]

    def test_logical_true(self):
        toks = tokenize(".TRUE.")
        assert toks[0].kind == TokenKind.LOGICAL
        assert toks[0].text == ".TRUE."

    def test_logical_false(self):
        toks = tokenize(".false.")
        assert toks[0].kind == TokenKind.LOGICAL
        assert toks[0].text == ".FALSE."

    def test_name(self):
        assert kinds("my_var") == [TokenKind.NAME]

    def test_keyword_lower(self):
        toks = tokenize("integer")
        assert toks[0].kind == TokenKind.KEYWORD

    def test_keyword_upper_normalised(self):
        toks = tokenize("INTEGER")
        assert toks[0].kind == TokenKind.KEYWORD
        assert toks[0].text == "integer"


class TestOperators:
    def test_double_star(self):
        assert kinds("a**b") == [TokenKind.NAME, TokenKind.OP_POWER, TokenKind.NAME]

    def test_double_slash(self):
        assert kinds("a//b") == [TokenKind.NAME, TokenKind.OP_CONCAT, TokenKind.NAME]

    def test_arrow(self):
        assert kinds("a=>b") == [TokenKind.NAME, TokenKind.OP_ARROW, TokenKind.NAME]

    def test_double_colon(self):
        assert kinds("::") == [TokenKind.DOUBLE_COLON]

    def test_old_style_eq(self):
        toks = tokenize(".EQ.")
        assert toks[0].kind == TokenKind.OP_EQ

    def test_old_style_ne(self):
        toks = tokenize(".NE.")
        assert toks[0].kind == TokenKind.OP_NEQ

    def test_modern_eq(self):
        assert kinds("==") == [TokenKind.OP_EQ]

    def test_modern_ne(self):
        assert kinds("/=") == [TokenKind.OP_NEQ]


class TestComments:
    def test_inline_comment(self):
        toks = tokenize("x = 1  ! set x")
        comment = next(t for t in toks if t.kind == TokenKind.COMMENT)
        assert comment.text.startswith("!")

    def test_full_line_comment(self):
        assert kinds("! this is a comment") == [TokenKind.COMMENT]


class TestContinuation:
    def test_continuation_joins_lines(self):
        source = "x = 1 &\n    + 2"
        lines = list(iter_logical_lines(tokenize(source)))
        assert len(lines) == 1
        texts_in_line = [t.text for t in lines[0]]
        assert "1" in texts_in_line
        assert "2" in texts_in_line

    def test_no_continuation(self):
        source = "x = 1\ny = 2"
        lines = list(iter_logical_lines(tokenize(source)))
        assert len(lines) == 2

    def test_continuation_across_blank_line(self):
        source = "if (x > 0) &\n\n  y = 1\n"
        lines = list(iter_logical_lines(tokenize(source)))
        assert len(lines) == 1
        texts_in_line = [t.text for t in lines[0]]
        assert "if" in texts_in_line
        assert "y" in texts_in_line
