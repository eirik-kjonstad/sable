"""Shared token rendering helpers."""

from __future__ import annotations

from .analysis import DECL_TYPE_KEYWORDS, is_legacy_type_selector_boundary
from .tokens import Token, TokenKind

KEYWORD_SPACE_BEFORE_PAREN: frozenset[str] = frozenset(
    {
        "if",
        "elseif",
        "else if",
        "while",
        "select",
        "case",
        "where",
        "forall",
        "submodule",
        "associate",
        "concurrent",
        "is",
        "rank",
        "team",
    }
)

NON_CALL_PAREN_KEYWORDS: frozenset[str] = frozenset(
    {
        "dimension",
        "codimension",
        "intent",
        "kind",
        "len",
    }
)

_BINARY_OP_KINDS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.OP_PLUS,
        TokenKind.OP_MINUS,
        TokenKind.OP_STAR,
        TokenKind.OP_SLASH,
        TokenKind.OP_POWER,
        TokenKind.OP_CONCAT,
        TokenKind.OP_EQ,
        TokenKind.OP_NEQ,
        TokenKind.OP_LT,
        TokenKind.OP_LE,
        TokenKind.OP_GT,
        TokenKind.OP_GE,
        TokenKind.OP_AND,
        TokenKind.OP_OR,
        TokenKind.OP_NOT,
        TokenKind.OP_EQV,
        TokenKind.OP_NEQV,
        TokenKind.OP_ASSIGN,
        TokenKind.OP_ARROW,
        TokenKind.OP_PERCENT,
    }
)

_NO_SPACE_KINDS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.OP_PERCENT,
        TokenKind.OP_POWER,
    }
)


def needs_space_before(
    prev: Token | None,
    curr: Token,
    paren_depth: int = 0,
    prev_prev: Token | None = None,
    compact_named_assign: bool = False,
) -> bool:
    """Return True if a space is required before *curr*."""
    if prev is None:
        return False
    pk, ck = prev.kind, curr.kind

    if (
        ck == TokenKind.LPAREN
        and pk == TokenKind.KEYWORD
        and prev.text.lower() in KEYWORD_SPACE_BEFORE_PAREN
    ):
        return True
    if (
        ck == TokenKind.LPAREN
        and pk == TokenKind.KEYWORD
        and prev.text.lower() == "type"
        and prev_prev is not None
        and prev_prev.kind == TokenKind.KEYWORD
        and prev_prev.text.lower() == "select"
    ):
        return True

    if pk == TokenKind.RPAREN and ck in (TokenKind.KEYWORD, TokenKind.NAME):
        return True

    if pk in (TokenKind.LPAREN, TokenKind.LBRACKET):
        return False
    if ck in (TokenKind.RPAREN, TokenKind.RBRACKET, TokenKind.COMMA):
        return False

    if pk == TokenKind.OP_PERCENT or ck == TokenKind.OP_PERCENT:
        return False
    if pk == TokenKind.OP_POWER or ck == TokenKind.OP_POWER:
        return False
    if is_legacy_type_selector_boundary(prev_prev, prev, curr):
        return False

    if pk == TokenKind.COMMA:
        return True

    if compact_named_assign and (
        ck == TokenKind.OP_ASSIGN or pk == TokenKind.OP_ASSIGN
    ):
        return False

    if ck in _BINARY_OP_KINDS and ck not in _NO_SPACE_KINDS:
        return True
    if pk in _BINARY_OP_KINDS and pk not in _NO_SPACE_KINDS:
        return True

    if pk == TokenKind.DOUBLE_COLON or ck == TokenKind.DOUBLE_COLON:
        return True

    if ck == TokenKind.COLON:
        return False
    if pk == TokenKind.COLON:
        if (
            paren_depth == 0
            and prev_prev is not None
            and prev_prev.kind
            in {
                TokenKind.NAME,
                TokenKind.INTEGER,
                TokenKind.REAL,
                TokenKind.RPAREN,
                TokenKind.RBRACKET,
            }
            and ck
            in {
                TokenKind.NAME,
                TokenKind.INTEGER,
                TokenKind.REAL,
                TokenKind.LPAREN,
                TokenKind.OP_PLUS,
                TokenKind.OP_MINUS,
            }
            and not (
                prev_prev.kind == TokenKind.NAME and prev_prev.text.lower() == "only"
            )
        ):
            return False
        return paren_depth == 0

    if pk not in (TokenKind.LPAREN, TokenKind.LBRACKET) and ck not in (
        TokenKind.RPAREN,
        TokenKind.RBRACKET,
        TokenKind.COMMA,
        TokenKind.COLON,
        TokenKind.DOUBLE_COLON,
    ):
        if pk in (
            TokenKind.NAME,
            TokenKind.KEYWORD,
            TokenKind.INTEGER,
            TokenKind.REAL,
            TokenKind.STRING,
            TokenKind.LOGICAL,
        ) and ck in (
            TokenKind.NAME,
            TokenKind.KEYWORD,
            TokenKind.INTEGER,
            TokenKind.REAL,
            TokenKind.STRING,
            TokenKind.LOGICAL,
        ):
            return True

    return False


def _is_compact_equals_paren_open(tokens: list[Token], open_idx: int) -> bool:
    """Return True when '=' should be compact inside this parenthesized group."""
    if open_idx <= 0 or tokens[open_idx].kind != TokenKind.LPAREN:
        return False

    prev = tokens[open_idx - 1]
    prev_prev = tokens[open_idx - 2] if open_idx >= 2 else None

    if prev.kind == TokenKind.NAME:
        return True

    if prev.kind != TokenKind.KEYWORD:
        return False

    word = prev.text.lower()
    if word in KEYWORD_SPACE_BEFORE_PAREN:
        return False
    if word in NON_CALL_PAREN_KEYWORDS:
        return True
    if word in DECL_TYPE_KEYWORDS:
        if (
            word == "type"
            and prev_prev is not None
            and prev_prev.kind == TokenKind.KEYWORD
            and prev_prev.text.lower() == "select"
        ):
            return False
        return True
    return False


def render_tokens(tokens: list[Token], compact_named_assign: bool = False) -> str:
    """Render a token list to a string, inserting canonical spaces."""
    parts: list[str] = []
    prev: Token | None = None
    prev_prev: Token | None = None
    depth = 0
    paren_compact_stack: list[bool] = []
    compact_depth = 1 if compact_named_assign else 0
    for idx, tok in enumerate(tokens):
        if needs_space_before(
            prev, tok, depth, prev_prev, compact_named_assign=compact_depth > 0
        ):
            parts.append(" ")
        parts.append(tok.text)
        if tok.kind == TokenKind.LPAREN:
            compact = _is_compact_equals_paren_open(tokens, idx)
            paren_compact_stack.append(compact)
            if compact:
                compact_depth += 1
            depth += 1
        elif tok.kind == TokenKind.LBRACKET:
            depth += 1
        elif tok.kind == TokenKind.RPAREN:
            if paren_compact_stack:
                compact = paren_compact_stack.pop()
                if compact:
                    compact_depth = max(0, compact_depth - 1)
            depth = max(0, depth - 1)
        elif tok.kind == TokenKind.RBRACKET:
            depth = max(0, depth - 1)
        prev_prev = prev
        prev = tok
    return "".join(parts)
