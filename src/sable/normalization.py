"""Token-level normalization for formatter input."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import analysis as _analysis
from .tokens import Token, TokenKind

if TYPE_CHECKING:
    from .config import FormatConfig

_OLD_TO_NEW_OP: dict[str, str] = {
    ".eq.": "==",
    ".ne.": "/=",
    ".lt.": "<",
    ".le.": "<=",
    ".gt.": ">",
    ".ge.": ">=",
}
_NEW_OP_TO_KIND: dict[str, TokenKind] = {
    "==": TokenKind.OP_EQ,
    "/=": TokenKind.OP_NEQ,
    "<": TokenKind.OP_LT,
    "<=": TokenKind.OP_LE,
    ">": TokenKind.OP_GT,
    ">=": TokenKind.OP_GE,
}


def normalise_keyword_case(token: Token, cfg: FormatConfig) -> Token:
    """Apply configured keyword casing."""
    if not cfg.normalize_keyword_case:
        return token
    if token.kind != TokenKind.KEYWORD:
        return token
    text = token.text.lower() if cfg.keyword_case == "lower" else token.text.upper()
    return Token(token.kind, text, token.line, token.col)


def normalise_end_keyword(token: Token, cfg: FormatConfig) -> Token:
    """Normalise compact/spaced END keyword forms."""
    if not cfg.normalize_end_keywords:
        return token
    if token.kind != TokenKind.KEYWORD:
        return token
    text = token.text.lower()
    if (
        cfg.end_keyword_form == "spaced"
        and text in _analysis.COMPACT_TO_SPACED_END_KEYWORDS
    ):
        new_text = _analysis.COMPACT_TO_SPACED_END_KEYWORDS[text]
        if cfg.keyword_case == "upper":
            new_text = new_text.upper()
        return Token(token.kind, new_text, token.line, token.col)
    if (
        cfg.end_keyword_form == "compact"
        and text in _analysis.SPACED_TO_COMPACT_END_KEYWORDS
    ):
        new_text = _analysis.SPACED_TO_COMPACT_END_KEYWORDS[text]
        if cfg.keyword_case == "upper":
            new_text = new_text.upper()
        return Token(token.kind, new_text, token.line, token.col)
    return token


def normalise_operator(token: Token, cfg: FormatConfig) -> Token:
    """Replace old-style relational operators with modern equivalents."""
    if not cfg.normalize_operators:
        return token
    replacement = _OLD_TO_NEW_OP.get(token.text.lower())
    if replacement is None:
        return token
    return Token(_NEW_OP_TO_KIND[replacement], replacement, token.line, token.col)


def normalise_logical_literal(token: Token) -> Token:
    """Canonicalize logical literals to lowercase (.true./.false.)."""
    if token.kind != TokenKind.LOGICAL:
        return token
    return Token(token.kind, token.text.lower(), token.line, token.col)


def normalise_line(line_tokens: list[Token], cfg: FormatConfig) -> list[Token]:
    """Apply token-level normalization to one logical line."""
    normalised: list[Token] = []
    keyword_upper = cfg.keyword_case == "upper"

    for tok in line_tokens:
        kind = tok.kind
        text = tok.text

        if kind == TokenKind.KEYWORD:
            if cfg.normalize_keyword_case:
                text = text.upper() if keyword_upper else text.lower()
            if cfg.normalize_end_keywords:
                lower = text.lower()
                if (
                    cfg.end_keyword_form == "spaced"
                    and lower in _analysis.COMPACT_TO_SPACED_END_KEYWORDS
                ):
                    text = _analysis.COMPACT_TO_SPACED_END_KEYWORDS[lower]
                    if keyword_upper:
                        text = text.upper()
                elif (
                    cfg.end_keyword_form == "compact"
                    and lower in _analysis.SPACED_TO_COMPACT_END_KEYWORDS
                ):
                    text = _analysis.SPACED_TO_COMPACT_END_KEYWORDS[lower]
                    if keyword_upper:
                        text = text.upper()
        elif kind == TokenKind.LOGICAL:
            text = text.lower()
        elif cfg.normalize_operators:
            replacement = _OLD_TO_NEW_OP.get(text.lower())
            if replacement is not None:
                kind = _NEW_OP_TO_KIND[replacement]
                text = replacement

        if kind is tok.kind and text == tok.text:
            normalised.append(tok)
        else:
            normalised.append(Token(kind, text, tok.line, tok.col))

    return normalised


# Keywords that can follow `end` to form a compound end-keyword
_END_CONTINUATIONS: frozenset[str] = frozenset(
    {
        "if",
        "do",
        "function",
        "subroutine",
        "module",
        "program",
        "where",
        "select",
        "interface",
        "type",
        "associate",
        "block",
        "critical",
        "team",
        "forall",
        "enum",
    }
)


def merge_end_keywords(tokens: list[Token], cfg: FormatConfig) -> list[Token]:
    """Merge adjacent `end` + `<keyword>` pairs into compact form when configured.

    This is needed for compact mode because spaced forms (`end if`) are two
    separate tokens in the stream.
    """
    if cfg.end_keyword_form != "compact":
        return tokens

    result: list[Token] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if (
            tok.kind == TokenKind.KEYWORD
            and tok.text.lower() == "end"
            and i + 1 < len(tokens)
            and tokens[i + 1].kind == TokenKind.KEYWORD
            and tokens[i + 1].text.lower() in _END_CONTINUATIONS
        ):
            merged_text = "end" + tokens[i + 1].text.lower()
            if cfg.keyword_case == "upper":
                merged_text = merged_text.upper()
            result.append(Token(TokenKind.KEYWORD, merged_text, tok.line, tok.col))
            i += 2
        else:
            result.append(tok)
            i += 1
    return result
