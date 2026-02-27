"""Fortran free-form lexer for sable.

Produces a flat list of Tokens from a source string. The lexer handles:
  - Free-form source (Fortran 90+)
  - Case-insensitive keywords (emitted as lower-case)
  - Line continuations via trailing &
  - Inline comments starting with !
  - Both old-style (.EQ., .AND., …) and modern (==, &&, …) operators
"""

from __future__ import annotations

import re
from typing import Iterator

from .tokens import KEYWORDS, Token, TokenKind


# ---------------------------------------------------------------------------
# Token patterns (order matters – more specific patterns first)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<DIRECTIVE> \#[^\n]*    )  |  # preprocessor directive (#ifdef, #endif, …)
    (?P<COMMENT>  !.*          )  |  # ! comment to end of line
    (?P<REAL>
        [0-9]+\.[0-9]*(?:[eEdD][+-]?[0-9]+)?   # 1.0  1.0e3
      | \.[0-9]+(?:[eEdD][+-]?[0-9]+)?          # .5   .5e-2
      | [0-9]+[eEdD][+-]?[0-9]+                 # 1e3  (no dot)
    )                          |
    (?P<INTEGER>  [0-9]+       )  |
    (?P<STRING>
        '[^']*(?:''[^']*)*'    |  # single-quoted, '' escape
        "[^"]*(?:""[^"]*)*"       # double-quoted, "" escape
    )                          |
    (?P<LOGICAL>
        \.(?:TRUE|FALSE|true|false)\.
    )                          |
    (?P<NAMED_OP>
        \.(?:AND|OR|NOT|EQV|NEQV|EQ|NE|LT|LE|GT|GE)\.
    )                          |  # old-style operators (case-insensitive via flag)
    (?P<POWER>    \*\*          )  |
    (?P<CONCAT>   \/\/          )  |
    (?P<ARROW>    =>            )  |
    (?P<DOUBLE_COLON> ::       )  |
    (?P<LE>       <=            )  |
    (?P<GE>       >=            )  |
    (?P<NEQ>      \/=           )  |
    (?P<EQ>       ==            )  |
    (?P<LT>       <             )  |
    (?P<GT>       >             )  |
    (?P<PLUS>     \+            )  |
    (?P<MINUS>    -             )  |
    (?P<STAR>     \*            )  |
    (?P<SLASH>    \/            )  |
    (?P<PERCENT>  %             )  |
    (?P<ASSIGN>   =             )  |
    (?P<LPAREN>   \(            )  |
    (?P<RPAREN>   \)            )  |
    (?P<LBRACKET> \[            )  |
    (?P<RBRACKET> \]            )  |
    (?P<COMMA>    ,             )  |
    (?P<SEMICOLON>;             )  |
    (?P<CONTINUATION> &        )  |
    (?P<COLON>    :             )  |
    (?P<NAME>     [A-Za-z_][A-Za-z0-9_]*  )  |
    (?P<NEWLINE>  \n            )  |
    (?P<SKIP>     [ \t\r]+      )  |  # whitespace to ignore
    (?P<UNKNOWN>  .             )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_NAMED_OP_MAP: dict[str, TokenKind] = {
    ".and.": TokenKind.OP_AND,
    ".or.": TokenKind.OP_OR,
    ".not.": TokenKind.OP_NOT,
    ".eqv.": TokenKind.OP_EQV,
    ".neqv.": TokenKind.OP_NEQV,
    ".eq.": TokenKind.OP_EQ,
    ".ne.": TokenKind.OP_NEQ,
    ".lt.": TokenKind.OP_LT,
    ".le.": TokenKind.OP_LE,
    ".gt.": TokenKind.OP_GT,
    ".ge.": TokenKind.OP_GE,
}

_PATTERN_TO_KIND: dict[str, TokenKind] = {
    "REAL": TokenKind.REAL,
    "INTEGER": TokenKind.INTEGER,
    "STRING": TokenKind.STRING,
    "LOGICAL": TokenKind.LOGICAL,
    "POWER": TokenKind.OP_POWER,
    "CONCAT": TokenKind.OP_CONCAT,
    "ARROW": TokenKind.OP_ARROW,
    "DOUBLE_COLON": TokenKind.DOUBLE_COLON,
    "LE": TokenKind.OP_LE,
    "GE": TokenKind.OP_GE,
    "NEQ": TokenKind.OP_NEQ,
    "EQ": TokenKind.OP_EQ,
    "LT": TokenKind.OP_LT,
    "GT": TokenKind.OP_GT,
    "PLUS": TokenKind.OP_PLUS,
    "MINUS": TokenKind.OP_MINUS,
    "STAR": TokenKind.OP_STAR,
    "SLASH": TokenKind.OP_SLASH,
    "PERCENT": TokenKind.OP_PERCENT,
    "ASSIGN": TokenKind.OP_ASSIGN,
    "LPAREN": TokenKind.LPAREN,
    "RPAREN": TokenKind.RPAREN,
    "LBRACKET": TokenKind.LBRACKET,
    "RBRACKET": TokenKind.RBRACKET,
    "COMMA": TokenKind.COMMA,
    "SEMICOLON": TokenKind.SEMICOLON,
    "CONTINUATION": TokenKind.CONTINUATION,
    "COLON": TokenKind.COLON,
    "NEWLINE": TokenKind.NEWLINE,
    "UNKNOWN": TokenKind.UNKNOWN,
}


class LexError(Exception):
    def __init__(self, msg: str, line: int, col: int) -> None:
        super().__init__(f"{msg} at line {line}, col {col}")
        self.line = line
        self.col = col


def tokenize(source: str) -> list[Token]:
    """Lex *source* and return a flat list of Tokens."""
    tokens: list[Token] = []
    line = 1
    line_start = 0

    for m in _TOKEN_RE.finditer(source):
        col = m.start() - line_start + 1
        kind_name = m.lastgroup
        text = m.group()

        if kind_name == "SKIP":
            continue

        if kind_name == "NEWLINE":
            tokens.append(Token(TokenKind.NEWLINE, text, line, col))
            line += 1
            line_start = m.end()
            continue

        if kind_name == "DIRECTIVE":
            tokens.append(Token(TokenKind.DIRECTIVE, text, line, col))
            continue

        if kind_name == "COMMENT":
            tokens.append(Token(TokenKind.COMMENT, text, line, col))
            continue

        if kind_name == "NAMED_OP":
            kind = _NAMED_OP_MAP[text.lower()]
            tokens.append(Token(kind, text.lower(), line, col))
            continue

        if kind_name == "NAME":
            lower = text.lower()
            kind = TokenKind.KEYWORD if lower in KEYWORDS else TokenKind.NAME
            tokens.append(Token(kind, lower if kind == TokenKind.KEYWORD else text, line, col))
            continue

        if kind_name == "LOGICAL":
            tokens.append(Token(TokenKind.LOGICAL, text.upper(), line, col))
            continue

        if kind_name in _PATTERN_TO_KIND:
            tokens.append(Token(_PATTERN_TO_KIND[kind_name], text, line, col))
            continue

    tokens.append(Token(TokenKind.EOF, "", line, 0))
    return tokens


def iter_logical_lines(tokens: list[Token]) -> Iterator[list[Token]]:
    """Group tokens into logical lines, joining continuations.

    A trailing & means the next physical line is a continuation.
    Leading & on a continuation line is consumed (optional per standard).
    Inline comments are preserved on the logical line that owns them.
    """
    current: list[Token] = []
    continued = False

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        if tok.kind == TokenKind.EOF:
            if current:
                yield current
            return

        if tok.kind == TokenKind.CONTINUATION:
            # Look ahead: if the next non-whitespace on this physical line is
            # NEWLINE (or COMMENT then NEWLINE), this is a line continuation.
            j = i + 1
            while j < len(tokens) and tokens[j].kind == TokenKind.COMMENT:
                j += 1
            if j < len(tokens) and tokens[j].kind == TokenKind.NEWLINE:
                continued = True
                i = j + 1  # skip continuation & and newline
                # Consume optional leading & on next line
                if i < len(tokens) and tokens[i].kind == TokenKind.CONTINUATION:
                    i += 1
                continue
            else:
                current.append(tok)
        elif tok.kind == TokenKind.NEWLINE:
            if not continued:
                if current:
                    yield current
                else:
                    yield []  # blank line — preserve as empty logical line
                current = []
            else:
                # End of a continuation line: the logical line is now complete.
                # Yield it here so that a following blank NEWLINE can be yielded
                # as an empty logical line rather than being consumed by this one.
                if current:
                    yield current
                    current = []
            continued = False
        elif tok.kind == TokenKind.SEMICOLON:
            # Semicolon acts as statement separator
            if current:
                yield current
            current = []
        else:
            current.append(tok)

        i += 1

    if current:
        yield current
