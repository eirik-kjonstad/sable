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

    indent_width: int = 3
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

    # Space between closing paren and a following identifier or keyword:
    # ) then, ) result, if (cond) action, …
    if pk == TokenKind.RPAREN and ck in (TokenKind.KEYWORD, TokenKind.NAME):
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

# Prefix attributes that may precede `function` or `subroutine` in a
# procedure header, e.g. `pure function f(...)` or `recursive subroutine s()`
_PROCEDURE_PREFIXES: frozenset[str] = frozenset({
    "pure", "recursive", "elemental", "impure", "non_recursive",
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
            # `end …` constructs (both compact `enddo` and spaced `end do`)
            # are pure closers.  The trailing keyword (`do`, `associate`, …)
            # names what is being ended, NOT a new block opener.  Other
            # closing keywords (`else`, `elseif`, `case`, `contains`)
            # legitimately re-open via their last token (e.g. `then`).
            can_open_via_last = not (did_close and first.startswith("end"))
            if (can_open_via_last and last in _INDENT_OPEN) or self._is_block_opener(first, non_comment):
                self.open()

        return ind, did_close

    @staticmethod
    def _is_block_opener(first: str, non_comment: list[Token]) -> bool:
        """Return True if the first keyword opens a new indentation block.

        Handles ambiguous keywords like ``type``, which can introduce either a
        type definition (``type :: name`` – block opener) or a variable
        declaration (``type(kind) :: var`` – not a block opener).

        Also handles procedure prefix attributes (``pure``, ``recursive``,
        ``elemental``, ``impure``) that may appear before ``function`` or
        ``subroutine``, e.g. ``pure function f(x) result(y)``.
        """
        if first in _PROCEDURE_PREFIXES:
            # pure/recursive/elemental/… function|subroutine …
            return any(
                t.kind == TokenKind.KEYWORD
                and t.text.lower() in ("function", "subroutine")
                for t in non_comment
            )
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

def _render_tokens(tokens: list[Token]) -> str:
    """Render a token list to a string, inserting spaces via the spacing rules."""
    parts: list[str] = []
    prev: Token | None = None
    for tok in tokens:
        if _needs_space_before(prev, tok):
            parts.append(" ")
        parts.append(tok.text)
        prev = tok
    return "".join(parts)


def _find_outermost_paren_group(tokens: list[Token]) -> tuple[int, int] | None:
    """Return (open_idx, close_idx) of the first top-level '(…)' group, or None."""
    depth = 0
    open_idx: int | None = None
    for i, tok in enumerate(tokens):
        if tok.kind == TokenKind.LPAREN:
            if depth == 0:
                open_idx = i
            depth += 1
        elif tok.kind == TokenKind.RPAREN:
            depth -= 1
            if depth == 0 and open_idx is not None:
                return open_idx, i
    return None


def _split_at_top_commas(tokens: list[Token]) -> list[list[Token]]:
    """Split *tokens* at top-level commas, returning one group per argument."""
    groups: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for tok in tokens:
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
            current.append(tok)
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth -= 1
            current.append(tok)
        elif tok.kind == TokenKind.COMMA and depth == 0:
            groups.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        groups.append(current)
    return groups


def _avoid_percent_split(tokens: list[Token], split_at: int) -> int:
    """Back up *split_at* to avoid splitting in the middle of a ``%`` chain.

    ``obj%field`` and ``a%b%c`` are logical units; splitting between them
    produces awkward continuations like ``obj% &\\n   field``.  Walk backward
    from *split_at* until neither side of the proposed split boundary is
    adjacent to a ``%`` token.

    Returns the adjusted index.  A return value of 0 means the chain starts
    at the very beginning of *tokens*; the caller should fall back to the
    original *split_at* to avoid emitting an empty physical line.
    """
    idx = split_at
    while idx > 0:
        if tokens[idx].kind == TokenKind.OP_PERCENT:
            # Would split before %; back up past the left-hand operand.
            idx -= 1
        elif tokens[idx - 1].kind == TokenKind.OP_PERCENT:
            # Would split after %; back up past % and its left-hand operand.
            idx -= 2
        else:
            break
    return idx


def _greedy_split_arg(
    arg_toks: list[Token],
    first_indent: str,
    cont_indent: str,
    suffix: str,
    cfg: FormatConfig,
) -> list[str]:
    """Split a long argument across multiple content lines using greedy splitting.

    Each returned string is a content line *without* the trailing ' &'.
    The *suffix* (e.g. ',') is appended only to the last line.
    Continuation lines are placed at *cont_indent* (one level deeper than
    *first_indent*).
    """
    lines: list[str] = []
    remaining = list(arg_toks)
    current_indent = first_indent

    while remaining:
        budget = cfg.line_length - len(current_indent) - 2  # room for ' &'
        parts_acc: list[str] = []
        prev: Token | None = None
        char_count = 0
        split_at = len(remaining)

        for idx, tok in enumerate(remaining):
            space = " " if _needs_space_before(prev, tok) else ""
            token_str = space + tok.text
            if char_count + len(token_str) > budget and idx > 0:
                adjusted = _avoid_percent_split(remaining, idx)
                split_at = adjusted if adjusted > 0 else idx
                break
            parts_acc.append(token_str)
            char_count += len(token_str)
            prev = tok

        chunk = "".join(parts_acc[:split_at])
        remaining = remaining[split_at:]

        if remaining:
            lines.append(current_indent + chunk)
        else:
            lines.append(current_indent + chunk + suffix)

        current_indent = cont_indent

    return lines if lines else [first_indent + _render_tokens(arg_toks) + suffix]


def _split_string_literal(
    tok_text: str,
    prefix_len: int,
    cont_indent: str,
    line_length: int,
) -> list[str]:
    """Split a too-long string literal using Fortran in-string continuation.

    *tok_text*   — full STRING token text including surrounding quotes.
    *prefix_len* — characters already used on the first physical line before
                   this string (indent + preceding tokens).
    *cont_indent* — indentation to use on continuation lines.
    *line_length* — maximum physical line length.

    Returns a list of fragments:
      [0]    first fragment: ``quote + content_chunk + " &"``
             (caller prepends the prefix for the first physical line)
      [1:-1] complete middle lines: ``cont_indent + "&" + chunk + " &"``
      [-1]   last line: ``cont_indent + "&" + chunk + closing_quote``

    If the string already fits within the available space, returns
    ``[tok_text]`` unchanged.
    """
    if len(tok_text) < 2:
        return [tok_text]

    quote = tok_text[0]       # ' or "
    content = tok_text[1:-1]  # strip surrounding quotes

    avail = line_length - prefix_len
    # Need at least: quote(1) + one char + "&"(1)
    first_content_max = avail - 2
    if first_content_max <= 0 or avail >= len(tok_text):
        return [tok_text]

    # Content budget per continuation line:
    #   middle: line_length - len(cont_indent) - "&"(1) - "&"(1) = - 2
    #   last:   line_length - len(cont_indent) - "&"(1) - quote(1) = - 2
    # (No space before the trailing & — space would become part of string value.)
    mid_budget = line_length - len(cont_indent) - 2
    last_budget = mid_budget
    if mid_budget <= 0:
        return [tok_text]

    def _safe_pos(s: str, max_pos: int) -> int:
        """Back up one if splitting here would cut through a doubled-quote escape."""
        p = min(max_pos, len(s))
        if 0 < p < len(s) and s[p - 1] == quote and s[p] == quote:
            p -= 1
        return p

    frags: list[str] = []
    remaining = content

    p = _safe_pos(remaining, first_content_max)
    frags.append(quote + remaining[:p] + "&")
    remaining = remaining[p:]

    while remaining:
        if len(remaining) <= last_budget:
            frags.append(cont_indent + "&" + remaining + quote)
            break
        p = _safe_pos(remaining, mid_budget)
        frags.append(cont_indent + "&" + remaining[:p] + "&")
        remaining = remaining[p:]

    return frags if len(frags) > 1 else [tok_text]


def _try_expand_arg_list(
    body: list[Token],
    comment: Token | None,
    indent: str,
    cfg: FormatConfig,
) -> list[str] | None:
    """Try to render the line with one argument per line (Black-style explosion).

    Returns a list of physical lines if the line contains a parenthesised
    argument list with multiple arguments and is not a control-flow construct.
    Returns *None* when expansion is not applicable.

    If an individual argument is itself too long to fit on one continuation
    line, it is split further using greedy continuation at a deeper indent.
    """
    paren_span = _find_outermost_paren_group(body)
    if paren_span is None:
        return None

    open_idx, close_idx = paren_span
    inner = body[open_idx + 1:close_idx]

    # Require at least one top-level comma (two or more arguments)
    depth = 0
    has_top_comma = False
    for tok in inner:
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth -= 1
        elif tok.kind == TokenKind.COMMA and depth == 0:
            has_top_comma = True
            break
    if not has_top_comma:
        return None

    # Do not explode control-flow constructs: if (…), while (…), select (…), …
    if open_idx > 0:
        prev_tok = body[open_idx - 1]
        if (prev_tok.kind == TokenKind.KEYWORD
                and prev_tok.text.lower() in _KEYWORD_SPACE_BEFORE_PAREN):
            return None

    continuation_indent = indent + " " * cfg.indent_width
    arg_continuation_indent = continuation_indent + " " * cfg.indent_width
    arg_groups = _split_at_top_commas(inner)

    # Build content strings for every physical line that will carry a ' &'.
    #   - the opening line: prefix + (
    #   - each argument: one line if it fits, or greedy-split into several lines
    # The closing ) goes on its own line at the original indent level.
    prefix_with_open = _render_tokens(body[:open_idx + 1])
    content_lines: list[str] = [indent + prefix_with_open]

    for i, arg_toks in enumerate(arg_groups):
        is_last = (i == len(arg_groups) - 1)
        suffix = "" if is_last else ","

        single_line = continuation_indent + _render_tokens(arg_toks) + suffix
        # + 2 reserves space for the trailing ' &' that will be appended later.
        if len(single_line) + 2 <= cfg.line_length:
            content_lines.append(single_line)
        elif len(arg_toks) == 1 and arg_toks[0].kind == TokenKind.STRING:
            # Single string arg too long: split using Fortran in-string continuation.
            # In-string & must be the last character on the physical line — no space
            # before it — so these lines cannot receive a statement & via the alignment
            # loop below.  They are tagged by ending with "&" (no space) and emitted
            # as-is; only the closing fragment (ends with the quote) participates in
            # alignment and gets a statement " &".
            frags = _split_string_literal(
                arg_toks[0].text,
                len(continuation_indent),
                continuation_indent,   # continuation lines align with the opening quote
                cfg.line_length,
            )
            if len(frags) > 1:
                content_lines.append(continuation_indent + frags[0])  # ends with &
                for frag in frags[1:-1]:
                    content_lines.append(frag)                         # ends with &
                content_lines.append(frags[-1] + suffix)               # ends with quote
            else:
                content_lines.append(single_line)
        else:
            split = _greedy_split_arg(
                arg_toks, continuation_indent, arg_continuation_indent, suffix, cfg
            )
            content_lines.extend(split)

    # Align & markers.  Lines that end with a bare "&" are in-string continuation
    # lines: they must NOT receive an additional statement "&" (invalid Fortran).
    # Only lines that don't end with "&" participate in alignment.
    non_raw = [l for l in content_lines if not l.endswith("&")]
    fitting = [len(l) for l in non_raw if len(l) <= cfg.line_length - 2]
    align_width = (max(fitting) if fitting
                   else (max(len(l) for l in non_raw) if non_raw else 0))
    lines: list[str] = []
    for content in content_lines:
        if content.endswith("&"):
            # In-string continuation: emit without adding a statement &
            lines.append(content)
        else:
            padding = " " * max(0, align_width - len(content))
            lines.append(content + padding + " &")

    # Closing line(s): start with ')' at original indent, then any suffix tokens
    # (e.g. result(r) or chained expressions). Reuse the normal line renderer so
    # long suffixes are also split to respect line_length.
    close_tokens = [body[close_idx]] + body[close_idx + 1:]
    if comment is not None:
        close_tokens.append(comment)
    lines.extend(render_logical_line(close_tokens, indent, cfg))

    return lines


def render_logical_line(
    tokens: list[Token],
    indent: str,
    cfg: FormatConfig,
) -> list[str]:
    """Render a logical line (already normalised) to one or more physical lines.

    If the line exceeds *cfg.line_length*, continuation markers (&) are inserted.
    When the line contains a multi-argument parenthesised list (a call, definition,
    or similar), the list is exploded one-argument-per-line before falling back to
    the greedy split strategy.  Comments are always kept at the end of their line.
    """
    # Separate trailing comment (if any)
    comment: Token | None = None
    body = tokens
    if tokens and tokens[-1].kind == TokenKind.COMMENT:
        comment = tokens[-1]
        body = tokens[:-1]

    # Build the token string with spacing
    line_body = _render_tokens(body)
    comment_str = ("  " + comment.text) if comment else ""

    full_line = indent + line_body + comment_str

    if len(full_line) <= cfg.line_length:
        return [full_line]

    # Try the one-argument-per-line expansion first (Black-style)
    expanded = _try_expand_arg_list(body, comment, indent, cfg)
    if expanded is not None:
        return expanded

    # Fall back to a greedy split: pack as many tokens per physical line as possible
    lines: list[str] = []
    remaining = list(body)
    current_indent = indent
    continuation_indent = indent + " " * cfg.indent_width

    while remaining:
        # If the first remaining token is a STRING too long for the current
        # physical line, split it using Fortran in-string continuation.
        lead = remaining[0]
        if lead.kind == TokenKind.STRING:
            prefix_len = len(current_indent)
            if prefix_len + len(lead.text) > cfg.line_length:
                frags = _split_string_literal(
                    lead.text, prefix_len, continuation_indent, cfg.line_length
                )
                if len(frags) > 1:
                    remaining = remaining[1:]
                    lines.append(current_indent + frags[0])
                    for frag in frags[1:-1]:
                        lines.append(frag)
                    if remaining:
                        lines.append(frags[-1] + " &")
                        current_indent = continuation_indent
                    else:
                        lines.append(frags[-1] + comment_str)
                        break
                    continue

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
                adjusted = _avoid_percent_split(remaining, idx)
                split_at = adjusted if adjusted > 0 else idx
                break
            parts_acc.append(token_str)
            char_count += len(token_str)
            prev2 = tok

        chunk = "".join(parts_acc[:split_at])
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
            physical = render_logical_line(normalised, indent, cfg)
            if len(physical) == 1:
                # Fits on one line — keep the action on the same line as the if.
                output_lines.extend(physical)
            else:
                # Too long — split at the if/action boundary.
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
