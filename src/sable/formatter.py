"""Core formatting engine for sable.

The formatter operates in two passes:
  1. *Normalise*: walk the token stream and apply token-level rules
     (keyword casing, operator spacing, etc.) producing a normalised
     token sequence.
  2. *Layout*: reconstruct source lines respecting indentation and the
     configured line-length limit, inserting continuation markers where
     needed.

All formatting decisions are encoded as small, composable rule functions
so they can be individually toggled and tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .tokens import Token, TokenKind


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class FormatConfig:
    """All knobs exposed to the user (Black-style: mostly zero knobs)."""

    line_length: int = 100
    """Maximum line length before continuation is inserted."""

    indent_width: int = 2
    """Spaces per indentation level."""

    keyword_case: str = "lower"
    """How to case Fortran keywords: 'lower' | 'upper'."""

    end_keyword_form: str = "spaced"
    """How to emit compound END keywords.

    'spaced'  →  end if / end do / end subroutine / …
    'compact' →  endif / enddo / endsubroutine / …
    """

    normalize_operators: bool = True
    """Replace old-style relational operators (.EQ., .GT., …) with modern (==, >, …)."""

    trailing_newline: bool = True
    """Ensure the file ends with exactly one newline."""

    double_colon_declarations: bool = True
    """Always emit '::' in type declarations."""


DEFAULT_CONFIG = FormatConfig()


# ---------------------------------------------------------------------------
# Operator normalisation map
# ---------------------------------------------------------------------------

_OLD_TO_NEW_OP: dict[str, str] = {
    ".eq.": "==",
    ".ne.": "/=",
    ".lt.": "<",
    ".le.": "<=",
    ".gt.": ">",
    ".ge.": ">=",
}

# Operators that require spaces on both sides
_BINARY_OP_KINDS: frozenset[TokenKind] = frozenset({
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
})

# These operators do NOT get spaces (tightly bound)
_NO_SPACE_KINDS: frozenset[TokenKind] = frozenset({
    TokenKind.OP_PERCENT,  # a%b
    TokenKind.OP_POWER,    # a**b  (debatable, sable chooses no-space)
})

# Control-flow keywords that must be followed by a space before '('
# (excludes type keywords like integer, real, type, class where 'integer(8)' is correct)
_KEYWORD_SPACE_BEFORE_PAREN: frozenset[str] = frozenset({
    "if", "elseif", "else if", "while", "select", "case", "where", "forall",
})

# Compound end-keyword forms
_COMPACT_TO_SPACED: dict[str, str] = {
    "endif": "end if",
    "enddo": "end do",
    "endforall": "end forall",
    "endfunction": "end function",
    "endmodule": "end module",
    "endprogram": "end program",
    "endsubroutine": "end subroutine",
    "endwhere": "end where",
    "endselect": "end select",
    "endinterface": "end interface",
    "endassociate": "end associate",
    "endblock": "end block",
    "endcritical": "end critical",
    "endtype": "end type",
    "endenum": "end enum",
    "endblockdata": "end block data",
}
_SPACED_TO_COMPACT: dict[str, str] = {v: k for k, v in _COMPACT_TO_SPACED.items()}


# ---------------------------------------------------------------------------
# Token-level normalisation
# ---------------------------------------------------------------------------

def normalise_keyword_case(token: Token, cfg: FormatConfig) -> Token:
    """Apply configured keyword casing."""
    if token.kind != TokenKind.KEYWORD:
        return token
    text = token.text.lower() if cfg.keyword_case == "lower" else token.text.upper()
    return Token(token.kind, text, token.line, token.col)


def normalise_end_keyword(token: Token, cfg: FormatConfig) -> Token:
    """Normalise compact/spaced END keyword forms."""
    if token.kind != TokenKind.KEYWORD:
        return token
    text = token.text.lower()
    if cfg.end_keyword_form == "spaced" and text in _COMPACT_TO_SPACED:
        new_text = _COMPACT_TO_SPACED[text]
        if cfg.keyword_case == "upper":
            new_text = new_text.upper()
        return Token(token.kind, new_text, token.line, token.col)
    if cfg.end_keyword_form == "compact" and text in _SPACED_TO_COMPACT:
        new_text = _SPACED_TO_COMPACT[text]
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
    kind_map = {
        "==": TokenKind.OP_EQ,
        "/=": TokenKind.OP_NEQ,
        "<":  TokenKind.OP_LT,
        "<=": TokenKind.OP_LE,
        ">":  TokenKind.OP_GT,
        ">=": TokenKind.OP_GE,
    }
    return Token(kind_map[replacement], replacement, token.line, token.col)


# ---------------------------------------------------------------------------
# Spacing rules
# ---------------------------------------------------------------------------

def _needs_space_before(prev: Token | None, curr: Token) -> bool:
    """Return True if a space is required before *curr*."""
    if prev is None:
        return False
    pk, ck = prev.kind, curr.kind

    # Space between control-flow keyword and opening paren: if (cond), case (val), …
    if ck == TokenKind.LPAREN and pk == TokenKind.KEYWORD \
            and prev.text.lower() in _KEYWORD_SPACE_BEFORE_PAREN:
        return True

    # Space between closing paren and keyword: ) then, ) result, …
    if pk == TokenKind.RPAREN and ck == TokenKind.KEYWORD:
        return True

    # Never space inside parens / brackets at boundary
    if pk in (TokenKind.LPAREN, TokenKind.LBRACKET):
        return False
    if ck in (TokenKind.RPAREN, TokenKind.RBRACKET, TokenKind.COMMA):
        return False

    # No space around % and **
    if pk == TokenKind.OP_PERCENT or ck == TokenKind.OP_PERCENT:
        return False
    if pk == TokenKind.OP_POWER or ck == TokenKind.OP_POWER:
        return False

    # Space after comma
    if pk == TokenKind.COMMA:
        return True

    # Space around binary operators (but not unary minus/plus)
    if ck in _BINARY_OP_KINDS and ck not in _NO_SPACE_KINDS:
        return True
    if pk in _BINARY_OP_KINDS and pk not in _NO_SPACE_KINDS:
        return True

    # Space before/after ::
    if pk == TokenKind.DOUBLE_COLON or ck == TokenKind.DOUBLE_COLON:
        return True

    # No space before colon in slice (heuristic: adjacent to integers/names)
    if ck == TokenKind.COLON or pk == TokenKind.COLON:
        return False

    # Default: space between distinct tokens
    if pk not in (TokenKind.LPAREN, TokenKind.LBRACKET) and \
       ck not in (TokenKind.RPAREN, TokenKind.RBRACKET, TokenKind.COMMA,
                  TokenKind.COLON, TokenKind.DOUBLE_COLON):
        # Names/keywords/literals separated by space
        if pk in (TokenKind.NAME, TokenKind.KEYWORD, TokenKind.INTEGER,
                  TokenKind.REAL, TokenKind.STRING, TokenKind.LOGICAL) and \
           ck in (TokenKind.NAME, TokenKind.KEYWORD, TokenKind.INTEGER,
                  TokenKind.REAL, TokenKind.STRING, TokenKind.LOGICAL):
            return True

    return False


# ---------------------------------------------------------------------------
# Indentation tracking
# ---------------------------------------------------------------------------

# Keywords that increase indentation on the *next* line
_INDENT_OPEN: frozenset[str] = frozenset({
    "then", "do", "else", "contains",
    "module", "program", "function", "subroutine",
    "interface", "type", "associate", "block",
    "critical", "where", "forall",
    "select", "case",
})

# Keywords that close an indentation level (decrease before rendering)
_INDENT_CLOSE: frozenset[str] = frozenset({
    "end", "endif", "enddo", "endfunction", "endsubroutine",
    "endmodule", "endprogram", "endwhere", "endselect",
    "endinterface", "endtype", "endassociate", "endblock",
    "endcritical", "end if", "end do", "end function",
    "end subroutine", "end module", "end program", "end where",
    "end select", "end interface", "end type", "end associate",
    "end block", "end critical",
    "else", "elseif", "case",
    "contains",
})


class IndentTracker:
    """Track indentation level as we walk logical lines."""

    def __init__(self, indent_width: int) -> None:
        self.level = 0
        self.width = indent_width

    def indent(self) -> str:
        return " " * (self.level * self.width)

    def open(self) -> None:
        self.level += 1

    def close(self) -> None:
        self.level = max(0, self.level - 1)

    def process_line(self, line_tokens: list[Token]) -> tuple[str, bool]:
        """Return (indentation_string, did_close) for a logical line."""
        if not line_tokens:
            return self.indent(), False

        first = line_tokens[0].text.lower()
        did_close = first in _INDENT_CLOSE
        if did_close:
            self.close()

        ind = self.indent()

        last = line_tokens[-1].text.lower() if line_tokens else ""
        # Comments don't count for indent
        non_comment = [t for t in line_tokens if t.kind != TokenKind.COMMENT]
        if non_comment:
            last = non_comment[-1].text.lower()
            if last in _INDENT_OPEN or self._is_block_opener(first, non_comment):
                self.open()

        return ind, did_close

    @staticmethod
    def _is_block_opener(first: str, non_comment: list[Token]) -> bool:
        """Return True if the first keyword opens a new indentation block.

        Handles ambiguous keywords like ``type``, which can introduce either a
        type definition (``type :: name`` – block opener) or a variable
        declaration (``type(kind) :: var`` – not a block opener).
        """
        if first not in _INDENT_OPEN:
            return False
        if first == "type":
            # type(kind_param) :: var  →  variable declaration, not a block opener
            if len(non_comment) > 1 and non_comment[1].kind == TokenKind.LPAREN:
                return False
        return True


# ---------------------------------------------------------------------------
# Line rendering
# ---------------------------------------------------------------------------

def render_logical_line(
    tokens: list[Token],
    indent: str,
    cfg: FormatConfig,
) -> list[str]:
    """Render a logical line (already normalised) to one or more physical lines.

    If the line exceeds *cfg.line_length*, continuation markers (&) are inserted.
    Comments are always kept at the end of their line.
    """
    # Separate trailing comment (if any)
    comment: Token | None = None
    body = tokens
    if tokens and tokens[-1].kind == TokenKind.COMMENT:
        comment = tokens[-1]
        body = tokens[:-1]

    # Build the token string with spacing
    parts: list[str] = []
    prev: Token | None = None
    for tok in body:
        if _needs_space_before(prev, tok):
            parts.append(" ")
        parts.append(tok.text)
        prev = tok

    line_body = "".join(parts)
    comment_str = ("  " + comment.text) if comment else ""

    full_line = indent + line_body + comment_str

    if len(full_line) <= cfg.line_length:
        return [full_line]

    # Split at a sensible point: after a comma or before a binary operator
    # Simple greedy split strategy
    lines: list[str] = []
    remaining = list(body)
    current_indent = indent
    continuation_indent = indent + " " * cfg.indent_width

    while remaining:
        # Try to fit as many tokens as possible on one physical line
        # Budget: line_length - len(current_indent) - 2 (for ' &')
        budget = cfg.line_length - len(current_indent) - 2
        parts_acc: list[str] = []
        prev2: Token | None = None
        char_count = 0
        split_at = len(remaining)  # default: all remaining tokens

        for idx, tok in enumerate(remaining):
            space = " " if _needs_space_before(prev2, tok) else ""
            token_str = space + tok.text
            if char_count + len(token_str) > budget and idx > 0:
                split_at = idx
                break
            parts_acc.append(token_str)
            char_count += len(token_str)
            prev2 = tok

        chunk = "".join(parts_acc)
        remaining = remaining[split_at:]

        if remaining:
            lines.append(current_indent + chunk + " &")
        else:
            lines.append(current_indent + chunk + comment_str)

        current_indent = continuation_indent

    return lines if lines else [indent + line_body + comment_str]


# ---------------------------------------------------------------------------
# Multi-token normalisation
# ---------------------------------------------------------------------------

# Keywords that can follow `end` to form a compound end-keyword
_END_CONTINUATIONS: frozenset[str] = frozenset({
    "if", "do", "function", "subroutine", "module", "program",
    "where", "select", "interface", "type", "associate", "block",
    "critical", "forall", "enum",
})


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


# ---------------------------------------------------------------------------
# Single-line if splitting
# ---------------------------------------------------------------------------

def _split_single_line_if(
    tokens: list[Token],
) -> tuple[list[Token], list[Token]] | None:
    """If *tokens* form a single-line if statement, return (condition, action).

    A single-line if has the form ``if (cond) action`` with no trailing ``then``.
    Returns *None* for block-if statements and for anything that is not an if.
    """
    non_comment = [t for t in tokens if t.kind != TokenKind.COMMENT]
    if not non_comment or non_comment[0].text.lower() != "if":
        return None
    # Block-if ends with 'then' — leave those alone
    if non_comment[-1].text.lower() == "then":
        return None
    # Second non-comment token must open the condition
    if len(non_comment) < 2 or non_comment[1].kind != TokenKind.LPAREN:
        return None

    # Walk the full token list (including comments) to find the matching ')'
    depth = 0
    close_idx = None
    for i, tok in enumerate(tokens):
        if tok.kind == TokenKind.LPAREN:
            depth += 1
        elif tok.kind == TokenKind.RPAREN:
            depth -= 1
            if depth == 0:
                close_idx = i
                break

    if close_idx is None:
        return None

    action = tokens[close_idx + 1:]
    # Strip leading whitespace-only tokens; if nothing remains it's just if(cond)
    action_nc = [t for t in action if t.kind != TokenKind.COMMENT]
    if not action_nc:
        return None

    return tokens[:close_idx + 1], action


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_source(source: str, cfg: FormatConfig | None = None) -> str:
    """Format *source* and return the formatted string.

    This is the main entry point for sable's formatter.
    """
    from .lexer import iter_logical_lines, tokenize

    if cfg is None:
        cfg = DEFAULT_CONFIG

    tokens = tokenize(source)
    tracker = IndentTracker(cfg.indent_width)
    output_lines: list[str] = []

    # Normalise token-level rules
    def normalise(tok: Token) -> Token:
        tok = normalise_keyword_case(tok, cfg)
        tok = normalise_end_keyword(tok, cfg)
        tok = normalise_operator(tok, cfg)
        return tok

    # Buffer for comment/blank lines awaiting the indentation of the next code line.
    # None entries represent blank lines; str entries are raw comment texts.
    pending: list[str | None] = []

    def flush_pending(indent: str) -> None:
        for item in pending:
            output_lines.append("" if item is None else indent + item)
        pending.clear()

    def _is_end_routine(toks: list[Token]) -> bool:
        if not toks:
            return False
        first = toks[0].text.lower()
        if first in ("end subroutine", "end function", "endsubroutine", "endfunction"):
            return True
        return (first == "end" and len(toks) > 1
                and toks[1].text.lower() in ("subroutine", "function"))

    def _is_start_routine(toks: list[Token]) -> bool:
        if not toks or _is_end_routine(toks):
            return False
        return any(t.kind == TokenKind.KEYWORD
                   and t.text.lower() in ("subroutine", "function")
                   for t in toks)

    last_was_end_routine = False

    for logical_line in iter_logical_lines(tokens):
        logical_line = merge_end_keywords(logical_line, cfg)
        normalised = [normalise(t) for t in logical_line]

        # Preprocessor directives: flush buffer at current level, emit at column 0
        if normalised and normalised[0].kind == TokenKind.DIRECTIVE:
            flush_pending(tracker.indent())
            output_lines.append(normalised[0].text)
            last_was_end_routine = False
            continue

        non_comment = [t for t in normalised if t.kind != TokenKind.COMMENT]
        if not non_comment:
            # Comment-only or blank line: buffer until we know the next code indent
            pending.append(normalised[0].text if normalised else None)
            continue

        # Code line: emit buffered comments/blanks at this line's indentation level
        indent, _ = tracker.process_line(normalised)

        # Normalise blank lines between consecutive routines to exactly two,
        # but only when there are no comments in the gap.
        if (last_was_end_routine
                and _is_start_routine(non_comment)
                and all(item is None for item in pending)):
            pending.clear()
            output_lines.extend(["", ""])
        else:
            flush_pending(indent)

        split = _split_single_line_if(normalised)
        if split is not None:
            cond_tokens, action_tokens = split
            cond_lines = render_logical_line(cond_tokens, indent, cfg)
            cond_lines[-1] += " &"
            action_indent = indent + " " * cfg.indent_width
            action_lines = render_logical_line(action_tokens, action_indent, cfg)
            output_lines.extend(cond_lines)
            output_lines.extend(action_lines)
        else:
            physical = render_logical_line(normalised, indent, cfg)
            output_lines.extend(physical)
        last_was_end_routine = _is_end_routine(non_comment)

    # Flush any trailing comments/blanks at the current (final) indent level
    flush_pending(tracker.indent())

    result = "\n".join(output_lines)

    if cfg.trailing_newline:
        result = result.rstrip("\n") + "\n"

    return result
