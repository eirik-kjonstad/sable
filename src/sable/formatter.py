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
from dataclasses import dataclass

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

# These operators do NOT get spaces (tightly bound)
_NO_SPACE_KINDS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.OP_PERCENT,  # a%b
        TokenKind.OP_POWER,  # a**b  (debatable, sable chooses no-space)
    }
)

# Control-flow keywords that must be followed by a space before '('
# (excludes type keywords like integer, real, type, class where 'integer(8)' is correct)
_KEYWORD_SPACE_BEFORE_PAREN: frozenset[str] = frozenset(
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
    "endteam": "end team",
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
        "<": TokenKind.OP_LT,
        "<=": TokenKind.OP_LE,
        ">": TokenKind.OP_GT,
        ">=": TokenKind.OP_GE,
    }
    return Token(kind_map[replacement], replacement, token.line, token.col)


# ---------------------------------------------------------------------------
# Spacing rules
# ---------------------------------------------------------------------------


def _needs_space_before(
    prev: Token | None,
    curr: Token,
    paren_depth: int = 0,
    prev_prev: Token | None = None,
) -> bool:
    """Return True if a space is required before *curr*.

    *paren_depth* is the number of currently open parentheses/brackets.  It is
    used to distinguish a slice colon (inside parens, no space either side) from
    a top-level colon such as ``only:`` in a USE statement or a construct label
    (space after, no space before).
    """
    if prev is None:
        return False
    pk, ck = prev.kind, curr.kind

    # Space between control-flow keyword and opening paren: if (cond), case (val), …
    if (
        ck == TokenKind.LPAREN
        and pk == TokenKind.KEYWORD
        and prev.text.lower() in _KEYWORD_SPACE_BEFORE_PAREN
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

    # No space before ':' in any context.
    if ck == TokenKind.COLON:
        return False
    # Space after ':' only at the top level (USE only:, construct labels, …).
    # Inside parens/brackets ':' is a slice/subscript operator — no space.
    if pk == TokenKind.COLON:
        return paren_depth == 0

    # Default: space between distinct tokens
    if pk not in (TokenKind.LPAREN, TokenKind.LBRACKET) and ck not in (
        TokenKind.RPAREN,
        TokenKind.RBRACKET,
        TokenKind.COMMA,
        TokenKind.COLON,
        TokenKind.DOUBLE_COLON,
    ):
        # Names/keywords/literals separated by space
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


# ---------------------------------------------------------------------------
# Indentation tracking
# ---------------------------------------------------------------------------

# Keywords that increase indentation on the *next* line
_INDENT_OPEN: frozenset[str] = frozenset(
    {
        "then",
        "do",
        "else",
        "contains",
        "module",
        "submodule",
        "program",
        "function",
        "subroutine",
        "interface",
        "type",
        "associate",
        "block",
        "critical",
        "change",
        "where",
        "forall",
        "select",
        "case",
        "class",
        "rank",
        "enum",
    }
)

# Prefix attributes that may precede `function` or `subroutine` in a
# procedure header, e.g. `pure function f(...)` or `recursive subroutine s()`
_PROCEDURE_PREFIXES: frozenset[str] = frozenset(
    {
        "pure",
        "recursive",
        "elemental",
        "impure",
        "non_recursive",
    }
)

# Type-spec keywords that may prefix a function header, e.g.
# `integer function f(...)` or `type(my_t) function f(...)`.
_FUNCTION_TYPE_PREFIXES: frozenset[str] = frozenset(
    {
        "integer",
        "real",
        "complex",
        "logical",
        "character",
        "type",
        "class",
        "double",
        "precision",
    }
)

# Keywords that close an indentation level (decrease before rendering)
_INDENT_CLOSE: frozenset[str] = frozenset(
    {
        "end",
        "endif",
        "enddo",
        "endfunction",
        "endsubroutine",
        "endmodule",
        "endprogram",
        "endwhere",
        "endselect",
        "endinterface",
        "endtype",
        "endassociate",
        "endblock",
        "endcritical",
        "endteam",
        "endenum",
        "end if",
        "end do",
        "end function",
        "end subroutine",
        "end module",
        "end program",
        "end where",
        "end select",
        "end interface",
        "end type",
        "end associate",
        "end block",
        "end critical",
        "end team",
        "end enum",
        "else",
        "elseif",
        "case",
        "contains",
    }
)


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

        non_comment = self._core_tokens(line_tokens)
        first = self._first_keyword(line_tokens)
        did_close = first in _INDENT_CLOSE or self._is_select_guard(non_comment)
        if not did_close and self._is_labelled_continue(line_tokens):
            # Legacy labelled-do termination: `10 continue` closes one DO level.
            did_close = True
        if did_close:
            self.close()

        ind = self.indent()

        last = line_tokens[-1].text.lower() if line_tokens else ""
        if non_comment:
            last_tok = non_comment[-1]
            last = last_tok.text.lower()
            # `end …` constructs (both compact `enddo` and spaced `end do`)
            # are pure closers.  The trailing keyword (`do`, `associate`, …)
            # names what is being ended, NOT a new block opener.  Other
            # closing keywords (`else`, `elseif`, `case`, `contains`)
            # legitimately re-open via their last token (e.g. `then`).
            can_open_via_last = not (did_close and first.startswith("end"))
            # A trailing opener is only needed for `if (...) then` constructs.
            opens_via_last = (
                can_open_via_last
                and last_tok.kind == TokenKind.KEYWORD
                and last == "then"
            )
            if opens_via_last or self._is_block_opener(first, non_comment):
                self.open()

        return ind, did_close

    @staticmethod
    def _core_tokens(line_tokens: list[Token]) -> list[Token]:
        """Return statement tokens with labels and construct names removed."""
        non_comment = [t for t in line_tokens if t.kind != TokenKind.COMMENT]
        if not non_comment:
            return []
        i = 0
        if non_comment[i].kind in (TokenKind.INTEGER, TokenKind.LABEL):
            i += 1
        if (
            i + 1 < len(non_comment)
            and non_comment[i].kind == TokenKind.NAME
            and non_comment[i + 1].kind == TokenKind.COLON
        ):
            i += 2
        return non_comment[i:]

    @staticmethod
    def _first_keyword(line_tokens: list[Token]) -> str:
        """Return the first keyword text, skipping optional leading labels.

        Supported prefixes before the first executable keyword:
        - numeric statement labels (``10 do i = ...``)
        - construct names (``FindPos: do i = ...``)
        - a numeric label followed by a construct name
          (``10 FindPos: do i = ...``)
        """
        core = IndentTracker._core_tokens(line_tokens)
        if core and core[0].kind == TokenKind.KEYWORD:
            return core[0].text.lower()
        return ""

    @staticmethod
    def _is_select_guard(non_comment: list[Token]) -> bool:
        """Return True for select-type/rank branch selector lines."""
        if not non_comment:
            return False
        first = non_comment[0].text.lower()
        second = non_comment[1].text.lower() if len(non_comment) > 1 else ""
        second_kind = non_comment[1].kind if len(non_comment) > 1 else None
        if first == "type" and second == "is":
            return True
        if first == "class" and second in ("is", "default"):
            return True
        if first == "rank" and (second_kind == TokenKind.LPAREN or second == "default"):
            return True
        return False

    @staticmethod
    def _is_labelled_continue(line_tokens: list[Token]) -> bool:
        """Return True for lines like `15 continue` (legacy labelled-DO terminator)."""
        non_comment = [t for t in line_tokens if t.kind != TokenKind.COMMENT]
        return (
            len(non_comment) >= 2
            and non_comment[0].kind in (TokenKind.INTEGER, TokenKind.LABEL)
            and non_comment[1].kind == TokenKind.KEYWORD
            and non_comment[1].text.lower() == "continue"
        )

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
        if first in _FUNCTION_TYPE_PREFIXES:
            # Typed function headers: integer function f(...), type(t) function f(...)
            function_idx: int | None = None
            for i, tok in enumerate(non_comment):
                if tok.kind == TokenKind.KEYWORD and tok.text.lower() == "function":
                    function_idx = i
                    break
            if function_idx is not None:
                before = non_comment[:function_idx]
                has_decl_marker = any(t.kind == TokenKind.DOUBLE_COLON for t in before)
                has_assignment = any(t.kind == TokenKind.OP_ASSIGN for t in before)
                if not has_decl_marker and not has_assignment:
                    return True
        if first not in _INDENT_OPEN:
            return False
        if first == "change":
            # `change team (...)` opens a team block.
            return (
                len(non_comment) > 1
                and non_comment[1].kind == TokenKind.KEYWORD
                and non_comment[1].text.lower() == "team"
            )
        if first == "module":
            # `module procedure ...` within an interface block is a declaration,
            # not a block opener.
            for i, tok in enumerate(non_comment):
                if tok.kind == TokenKind.KEYWORD and tok.text.lower() == "module":
                    if i + 1 < len(non_comment):
                        if non_comment[i + 1].text.lower() == "procedure":
                            return False
                    break
        if first == "type":
            # `type = ...` can be a regular assignment when TYPE is a variable name.
            if any(t.kind == TokenKind.OP_ASSIGN for t in non_comment):
                return False
            # type is (...) inside select type is a selector branch opener.
            if len(non_comment) > 1 and non_comment[1].text.lower() == "is":
                return True
            # type(kind_param) :: var  →  variable declaration, not a block opener
            if len(non_comment) > 1 and non_comment[1].kind == TokenKind.LPAREN:
                return False
        if first == "class":
            # class(*) :: var / class(t) :: var are declarations, not blocks.
            if len(non_comment) > 1 and non_comment[1].kind == TokenKind.LPAREN:
                return False
            # class is/default inside select type are selector branch openers.
            return len(non_comment) > 1 and non_comment[1].text.lower() in (
                "is",
                "default",
            )
        if first == "rank":
            # rank (...) / rank default inside select rank are branch openers.
            return len(non_comment) > 1 and (
                non_comment[1].kind == TokenKind.LPAREN
                or non_comment[1].text.lower() == "default"
            )
        return True


_DIRECTIVE_BRANCH_RE = re.compile(
    r"^#\s*(if|ifdef|ifndef|elif|else|endif)\b", flags=re.IGNORECASE
)
"""Match branch-forming preprocessor directives."""

_FORMAT_CONTROL_RE = re.compile(r"^\s*!\s*sable:\s*(off|on)\b", flags=re.IGNORECASE)
"""Match formatting control comments: `! sable: off` / `! sable: on`."""

_LOW_PRECEDENCE_SPLIT_OPS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.OP_OR,
        TokenKind.OP_AND,
        TokenKind.OP_EQV,
        TokenKind.OP_NEQV,
        TokenKind.OP_PLUS,
        TokenKind.OP_MINUS,
        TokenKind.OP_SLASH,
        TokenKind.OP_CONCAT,
    }
)
"""Operators preferred as line-break boundaries after commas/assignment."""


_DECL_TYPE_KEYWORDS: frozenset[str] = frozenset(
    {
        "integer",
        "real",
        "complex",
        "logical",
        "character",
        "type",
        "class",
        "double",
    }
)

_DECL_ATTRIBUTE_ORDER: dict[str, int] = {
    "intent": 0,
    "optional": 1,
    "parameter": 2,
    "allocatable": 3,
    "pointer": 4,
    "target": 5,
    "value": 6,
    "save": 7,
    "public": 8,
    "private": 9,
    "protected": 10,
    "volatile": 11,
    "asynchronous": 12,
    "contiguous": 13,
    "dimension": 14,
    "codimension": 15,
    "external": 16,
    "intrinsic": 17,
    "bind": 18,
    "pass": 19,
    "nopass": 20,
    "deferred": 21,
    "non_overridable": 22,
}
_DECL_ATTRIBUTE_DEFAULT_ORDER = len(_DECL_ATTRIBUTE_ORDER)


@dataclass
class _DeclarationParts:
    prefix_tokens: list[Token]
    entities: list[list[Token]]
    has_attributes: bool
    anchor: Token


def _make_token(kind: TokenKind, text: str, anchor: Token) -> Token:
    return Token(kind, text, anchor.line, anchor.col)


def _split_top_level_commas(tokens: list[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for tok in tokens:
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
            current.append(tok)
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
            current.append(tok)
        elif tok.kind == TokenKind.COMMA and depth == 0:
            if current:
                parts.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        parts.append(current)
    return parts


def _consume_paren_group(tokens: list[Token], start: int) -> int:
    if start >= len(tokens) or tokens[start].kind != TokenKind.LPAREN:
        return start
    depth = 0
    i = start
    while i < len(tokens):
        if tokens[i].kind == TokenKind.LPAREN:
            depth += 1
        elif tokens[i].kind == TokenKind.RPAREN:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return start


def _type_spec_end(tokens: list[Token]) -> int | None:
    if not tokens or tokens[0].kind != TokenKind.KEYWORD:
        return None

    first = tokens[0].text.lower()
    if first not in _DECL_TYPE_KEYWORDS:
        return None

    i = 1
    if first == "double":
        if (
            len(tokens) < 2
            or tokens[1].kind != TokenKind.KEYWORD
            or tokens[1].text.lower() != "precision"
        ):
            return None
        i = 2

    if i < len(tokens) and tokens[i].kind == TokenKind.LPAREN:
        next_i = _consume_paren_group(tokens, i)
        if next_i == i:
            return None
        i = next_i

    return i


def _is_attribute_segment(segment: list[Token]) -> bool:
    if not segment:
        return False
    if segment[0].kind not in (TokenKind.KEYWORD, TokenKind.NAME):
        return False
    return segment[0].text.lower() in _DECL_ATTRIBUTE_ORDER


def _attribute_sort_key(segment: list[Token], original_index: int) -> tuple[int, int]:
    if segment and segment[0].kind in (TokenKind.KEYWORD, TokenKind.NAME):
        key = _DECL_ATTRIBUTE_ORDER.get(
            segment[0].text.lower(), _DECL_ATTRIBUTE_DEFAULT_ORDER
        )
        return (key, original_index)
    return (_DECL_ATTRIBUTE_DEFAULT_ORDER, original_index)


def _join_comma_segments(segments: list[list[Token]], anchor: Token) -> list[Token]:
    out: list[Token] = []
    for i, segment in enumerate(segments):
        if i > 0:
            out.append(_make_token(TokenKind.COMMA, ",", anchor))
        out.extend(segment)
    return out


def _parse_declaration(tokens: list[Token]) -> _DeclarationParts | None:
    core = IndentTracker._core_tokens(tokens)
    if not core or len(core) != len(tokens):
        return None
    if core[0].kind != TokenKind.KEYWORD:
        return None

    first = core[0].text.lower()
    if first not in _DECL_TYPE_KEYWORDS:
        return None
    if IndentTracker._is_block_opener(first, core):
        return None

    type_end = _type_spec_end(core)
    if type_end is None:
        return None

    anchor = core[0]
    colon_idx = next(
        (i for i, tok in enumerate(core) if tok.kind == TokenKind.DOUBLE_COLON), None
    )

    attributes: list[list[Token]] = []
    entity_tokens: list[Token] = []

    has_explicit_colon = colon_idx is not None

    if has_explicit_colon:
        attributes = _split_top_level_commas(core[type_end:colon_idx])
        entity_tokens = core[colon_idx + 1 :]
    else:
        i = type_end
        entity_start: int | None = None

        while i < len(core):
            if core[i].kind != TokenKind.COMMA:
                entity_start = i
                break

            j = i + 1
            depth = 0
            while j < len(core):
                tok = core[j]
                if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
                    depth += 1
                elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
                    depth = max(0, depth - 1)
                elif tok.kind == TokenKind.COMMA and depth == 0:
                    break
                j += 1

            segment = core[i + 1 : j]
            if _is_attribute_segment(segment):
                attributes.append(segment)
                i = j
                continue

            entity_start = i + 1
            break

        if entity_start is None:
            return None
        entity_tokens = core[entity_start:]

    entities = _split_top_level_commas(entity_tokens)
    if not entities:
        return None
    if not has_explicit_colon and entities[0][0].kind != TokenKind.NAME:
        return None

    indexed_attrs = list(enumerate(attributes))
    sorted_attrs = [
        seg
        for _idx, seg in sorted(
            indexed_attrs, key=lambda x: _attribute_sort_key(x[1], x[0])
        )
    ]

    prefix_tokens = list(core[:type_end])
    if sorted_attrs:
        prefix_tokens.append(_make_token(TokenKind.COMMA, ",", anchor))
        prefix_tokens.extend(_join_comma_segments(sorted_attrs, anchor))

    return _DeclarationParts(
        prefix_tokens=prefix_tokens,
        entities=entities,
        has_attributes=bool(sorted_attrs),
        anchor=anchor,
    )


def _canonicalise_declaration_tokens(tokens: list[Token]) -> list[Token]:
    comment: Token | None = None
    body = tokens
    if body and body[-1].kind == TokenKind.COMMENT:
        comment = body[-1]
        body = body[:-1]

    decl = _parse_declaration(body)
    if decl is None:
        return tokens

    canonical = list(decl.prefix_tokens)
    canonical.append(_make_token(TokenKind.DOUBLE_COLON, "::", decl.anchor))
    canonical.extend(_join_comma_segments(decl.entities, decl.anchor))
    if comment is not None:
        canonical.append(comment)
    return canonical


# ---------------------------------------------------------------------------
# Line rendering
# ---------------------------------------------------------------------------


def _render_tokens(tokens: list[Token]) -> str:
    """Render a token list to a string, inserting spaces via the spacing rules."""
    parts: list[str] = []
    prev: Token | None = None
    prev_prev: Token | None = None
    depth = 0
    for tok in tokens:
        if _needs_space_before(prev, tok, depth, prev_prev):
            parts.append(" ")
        parts.append(tok.text)
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        prev_prev = prev
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


def _find_top_level_assignment_index(tokens: list[Token]) -> int | None:
    """Return index of the first top-level assignment operator, if any."""
    depth = 0
    for i, tok in enumerate(tokens):
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        elif tok.kind == TokenKind.OP_ASSIGN and depth == 0:
            return i
    return None


def _is_lhs_subscript_paren_group(
    tokens: list[Token], open_idx: int, close_idx: int
) -> bool:
    """Return True when `( ... )` is part of the assignment LHS designator."""
    assignment_idx = _find_top_level_assignment_index(tokens)
    return assignment_idx is not None and close_idx < assignment_idx


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


def _avoid_array_constructor_split(tokens: list[Token], split_at: int) -> int:
    """Adjust *split_at* to avoid invalid splits in ``(/ ... /)`` delimiters.

    Free-form Fortran array constructors use paired delimiters ``(/`` and ``/)``.
    A continuation boundary between those two-character delimiter pairs is
    invalid (e.g. ``( &`` then ``/ ...``). When a split would land there, prefer
    keeping the pair together by advancing the boundary past the slash.
    """
    if split_at <= 0 or split_at >= len(tokens):
        return split_at
    left = tokens[split_at - 1].kind
    right = tokens[split_at].kind
    if left == TokenKind.LPAREN and right == TokenKind.OP_SLASH:
        return split_at + 1
    if left == TokenKind.OP_SLASH and right == TokenKind.RPAREN:
        return split_at + 1
    return split_at


def _avoid_leading_comma_split(tokens: list[Token], split_at: int) -> int:
    """Adjust *split_at* so the next physical line does not start with a comma."""
    if split_at <= 0 or split_at >= len(tokens):
        return split_at
    if tokens[split_at].kind != TokenKind.COMMA:
        return split_at

    # Prefer moving the boundary left so the comma stays with the preceding item.
    if split_at > 1:
        return split_at - 1

    # If the split is right after the first token, include the comma on this line.
    # This avoids a leading comma on the continuation line.
    return split_at + 1


def _is_paren_slash_array_constructor(inner: list[Token]) -> bool:
    """Return True when *inner* is the body of a ``(/ ... /)`` constructor."""
    if len(inner) < 2:
        return False
    return inner[0].kind == TokenKind.OP_SLASH and inner[-1].kind == TokenKind.OP_SLASH


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
    current_depth = 0  # paren depth carried across physical-line splits

    while remaining:
        budget = cfg.line_length - len(current_indent) - 2  # room for ' &'
        split_at = _pick_split_index(remaining, budget, current_depth)
        parts_acc = _render_prefix(remaining[:split_at], current_depth)

        for tok in remaining[:split_at]:
            if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
                current_depth += 1
            elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
                current_depth = max(0, current_depth - 1)

        chunk = "".join(parts_acc[:split_at])
        remaining = remaining[split_at:]

        if remaining:
            lines.append(current_indent + chunk)
        else:
            lines.append(current_indent + chunk + suffix)

        current_indent = cont_indent

    return lines if lines else [first_indent + _render_tokens(arg_toks) + suffix]


def _render_prefix(tokens: list[Token], start_depth: int) -> list[str]:
    """Render token prefix to spacing-aware string chunks."""
    parts: list[str] = []
    prev: Token | None = None
    prev_prev: Token | None = None
    depth = start_depth
    for tok in tokens:
        space = " " if _needs_space_before(prev, tok, depth, prev_prev) else ""
        parts.append(space + tok.text)
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        prev_prev = prev
        prev = tok
    return parts


def _pick_split_index(tokens: list[Token], budget: int, start_depth: int) -> int:
    """Pick a split boundary using precedence: comma > '=' > low-precedence ops."""
    if not tokens:
        return 0

    prev: Token | None = None
    prev_prev: Token | None = None
    depth = start_depth
    char_count = 0
    fit_upto = len(tokens)
    depth_after: list[int] = []

    for idx, tok in enumerate(tokens):
        space = " " if _needs_space_before(prev, tok, depth, prev_prev) else ""
        token_str = space + tok.text
        if char_count + len(token_str) > budget and idx > 0:
            fit_upto = idx
            break
        char_count += len(token_str)
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        depth_after.append(depth)
        prev_prev = prev
        prev = tok

    if fit_upto == len(tokens):
        return len(tokens)

    protected_end: int | None = None
    if fit_upto <= 1:
        split_at = fit_upto
    else:
        leading_paren = _find_outermost_paren_group(tokens)
        if (
            leading_paren is not None
            and leading_paren[0] > 0
            and tokens[0].kind in (TokenKind.NAME, TokenKind.KEYWORD)
            and tokens[leading_paren[0]].kind == TokenKind.LPAREN
            and leading_paren[1] <= fit_upto
        ):
            protected_end = leading_paren[1]

        boundary_depths = [depth_after[i - 1] for i in range(1, fit_upto + 1)]
        unique_depths = sorted(set(boundary_depths))
        best_boundary: int | None = None
        for target_depth in unique_depths:
            priorities: list[list[int]] = [[], [], [], []]
            for boundary in range(1, fit_upto + 1):
                left = tokens[boundary - 1]
                right = tokens[boundary] if boundary < len(tokens) else None
                boundary_depth = depth_after[boundary - 1]
                same_depth = boundary_depth == target_depth

                if left.kind == TokenKind.COMMA and same_depth:
                    priorities[0].append(boundary)
                elif left.kind == TokenKind.OP_ASSIGN and same_depth:
                    priorities[1].append(boundary)
                elif same_depth and left.kind in _LOW_PRECEDENCE_SPLIT_OPS:
                    priorities[2].append(boundary)
                elif (
                    same_depth
                    and right is not None
                    and right.kind in _LOW_PRECEDENCE_SPLIT_OPS
                ):
                    priorities[3].append(boundary)

            # For a leading designator/function-like prefix `name(...)`, avoid
            # splitting inside that first parenthesised segment when there are
            # viable boundaries after the closing parenthesis.
            if protected_end is not None:
                filtered: list[list[int]] = []
                for group in priorities:
                    post = [b for b in group if b > protected_end]
                    filtered.append(post if post else group)
                priorities = filtered

            best = next((p for p in priorities if p), None)
            if best:
                best_boundary = best[-1]
                break

        split_at = best_boundary if best_boundary is not None else fit_upto

    # If we still chose a split inside a protected leading designator segment,
    # move the split right after the closing ')' when possible.
    if (
        protected_end is not None
        and split_at <= protected_end
        and protected_end < fit_upto
    ):
        split_at = protected_end + 1

    # Keep low-precedence operators at line end when they fit. This avoids
    # continuation lines that start with `.or.` / `.and.`.
    if split_at < fit_upto and tokens[split_at].kind in _LOW_PRECEDENCE_SPLIT_OPS:
        split_at += 1

    adjusted = _avoid_percent_split(tokens, split_at)
    split_at = adjusted if adjusted > 0 else split_at
    split_at = _avoid_array_constructor_split(tokens, split_at)
    split_at = _avoid_leading_comma_split(tokens, split_at)
    return split_at


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

    quote = tok_text[0]  # ' or "
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

    def _is_word_char(ch: str) -> bool:
        return ch.isalnum() or ch == "_"

    def _safe_pos(s: str, max_pos: int) -> int:
        """Pick a safe split boundary near *max_pos*.

        Preference order:
        1. avoid splitting inside words (alnum/underscore boundaries),
        2. avoid trailing whitespace before the in-string continuation '&',
        3. avoid splitting a doubled-quote escape.
        """
        p = min(max_pos, len(s))
        if p <= 0 or p >= len(s):
            return p

        # Move left while we'd split between two word characters.
        while 0 < p < len(s) and _is_word_char(s[p - 1]) and _is_word_char(s[p]):
            p -= 1

        # Prefer placing whitespace at the start of the next fragment rather
        # than leaving trailing spaces before '&' in the current fragment.
        while p > 0 and s[p - 1].isspace():
            p -= 1

        # Fallback: if no non-word boundary exists within budget, keep the
        # original budgeted split rather than producing an empty chunk.
        if p == 0:
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
    inner = body[open_idx + 1 : close_idx]

    # Assignment LHS designators such as arr(i, j) are index lists, not
    # call-like argument lists. Prefer keeping them compact and wrapping RHS.
    if _is_lhs_subscript_paren_group(body, open_idx, close_idx):
        return None

    # If the selected parenthesised segment is followed by a top-level binary
    # operator, expression-level splitting is usually clearer than exploding
    # this list first (e.g. `f(a, b) / g(...)`).
    suffix_depth = 0
    for tok in body[close_idx + 1 :]:
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            suffix_depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            suffix_depth = max(0, suffix_depth - 1)
        elif suffix_depth == 0 and tok.kind in (
            TokenKind.OP_SLASH,
            TokenKind.OP_STAR,
            TokenKind.OP_PLUS,
            TokenKind.OP_MINUS,
            TokenKind.OP_CONCAT,
            TokenKind.OP_AND,
            TokenKind.OP_OR,
            TokenKind.OP_EQV,
            TokenKind.OP_NEQV,
        ):
            return None

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

    # ``(/.../)`` array constructors are not ordinary argument lists. Exploding
    # them as "( ... )" arguments can separate "( /" across continuation lines.
    if _is_paren_slash_array_constructor(inner):
        return None

    # Do not explode control-flow constructs: if (…), while (…), select (…), …
    if open_idx > 0:
        prev_tok = body[open_idx - 1]
        if (
            prev_tok.kind == TokenKind.KEYWORD
            and prev_tok.text.lower() in _KEYWORD_SPACE_BEFORE_PAREN
        ):
            return None

    continuation_indent = indent + " " * cfg.indent_width
    arg_continuation_indent = continuation_indent + " " * cfg.indent_width
    arg_groups = _split_at_top_commas(inner)

    # Build content strings for every physical line that will carry a ' &'.
    #   - the opening line: prefix + (
    #   - each argument: one line if it fits, or greedy-split into several lines
    # The closing ) goes on its own line at the original indent level.
    prefix_with_open = _render_tokens(body[: open_idx + 1])
    content_lines: list[str] = [indent + prefix_with_open]

    for i, arg_toks in enumerate(arg_groups):
        is_last = i == len(arg_groups) - 1
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
                continuation_indent,  # continuation lines align with the opening quote
                cfg.line_length,
            )
            if len(frags) > 1:
                content_lines.append(continuation_indent + frags[0])  # ends with &
                for frag in frags[1:-1]:
                    content_lines.append(frag)  # ends with &
                content_lines.append(frags[-1] + suffix)  # ends with quote
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
    non_raw = [line for line in content_lines if not line.endswith("&")]
    fitting = [len(line) for line in non_raw if len(line) <= cfg.line_length - 2]
    align_width = (
        max(fitting)
        if fitting
        else (max(len(line) for line in non_raw) if non_raw else 0)
    )
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
    close_tokens = [body[close_idx]] + body[close_idx + 1 :]
    if comment is not None:
        close_tokens.append(comment)
    lines.extend(render_logical_line(close_tokens, indent, cfg))

    return lines


def _prefer_exploded_arg_list(tokens: list[Token]) -> bool:
    """Return True when an argument list was authored across multiple lines.

    This is Sable's equivalent of Black's "magic trailing comma": if the user has
    already made an argument list multiline, keep it exploded even when it would
    fit within the configured line length.
    """
    paren_span = _find_outermost_paren_group(tokens)
    if paren_span is None:
        return False

    open_idx, close_idx = paren_span
    inner = tokens[open_idx + 1 : close_idx]

    if _is_lhs_subscript_paren_group(tokens, open_idx, close_idx):
        return False

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
        return False

    paren_lines = {
        tok.line
        for tok in tokens[open_idx : close_idx + 1]
        if tok.kind != TokenKind.COMMENT
    }
    return len(paren_lines) > 1


def render_logical_line(
    tokens: list[Token],
    indent: str,
    cfg: FormatConfig,
    continuation_step: int | None = None,
    prefer_exploded_arg_list: bool = False,
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

    force_trailing_continuation = False
    while body and body[-1].kind == TokenKind.CONTINUATION:
        force_trailing_continuation = True
        body = body[:-1]

    # Normalise away any leading continuation marker. Sable emits continuation
    # markers in trailing position only.
    while body and body[0].kind == TokenKind.CONTINUATION:
        body = body[1:]

    # Build the token string with spacing
    line_body = _render_tokens(body)
    comment_str = ("  " + comment.text) if comment else ""
    trailing = " &" if force_trailing_continuation else ""
    full_line = indent + line_body + trailing + comment_str

    decl = _parse_declaration(body)
    if decl is not None and len(decl.entities) > 1:
        should_explode = decl.has_attributes or len(full_line) > cfg.line_length
        if should_explode:
            step = cfg.indent_width if continuation_step is None else continuation_step
            continuation_indent = indent + " " * step
            header_tokens = decl.prefix_tokens + [
                _make_token(TokenKind.DOUBLE_COLON, "::", decl.anchor)
            ]
            lines = [indent + _render_tokens(header_tokens) + " &"]

            for i, entity in enumerate(decl.entities):
                is_last = i == len(decl.entities) - 1
                suffix = "" if is_last else ","
                entity_line = continuation_indent + _render_tokens(entity) + suffix
                if is_last:
                    if force_trailing_continuation:
                        entity_line += " &"
                    entity_line += comment_str
                else:
                    entity_line += " &"
                lines.append(entity_line)
            return lines

    # Preserve manually multiline argument lists even when they fit on one line.
    if prefer_exploded_arg_list:
        expanded = _try_expand_arg_list(body, comment, indent, cfg)
        if expanded is not None:
            if force_trailing_continuation and expanded:
                expanded[-1] = expanded[-1] + " &"
            return expanded

    if len(full_line) <= cfg.line_length:
        return [full_line]

    # Try the one-argument-per-line expansion first (Black-style)
    expanded = _try_expand_arg_list(body, comment, indent, cfg)
    if expanded is not None:
        if force_trailing_continuation and expanded:
            expanded[-1] = expanded[-1] + " &"
        return expanded

    # Fall back to a greedy split: pack as many tokens per physical line as possible
    lines: list[str] = []
    remaining = list(body)
    current_indent = indent
    if continuation_step is None:
        continuation_step = cfg.indent_width
    continuation_indent = indent + " " * continuation_step
    current_depth = 0  # paren depth carried across physical-line splits

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
                        if (
                            remaining[0].kind == TokenKind.COMMA
                            and len(frags[-1]) + 3 <= cfg.line_length
                        ):
                            # Keep "," with the preceding fragment to avoid
                            # leading-comma continuation lines.
                            lines.append(frags[-1] + ", &")
                            remaining = remaining[1:]
                        else:
                            lines.append(frags[-1] + " &")
                        # If the next token closes the call/group opened on the
                        # original line, emit that close at the original indent.
                        # This avoids over-indenting a lone closing ')' after a
                        # continued long string argument.
                        if remaining and remaining[0].kind in (
                            TokenKind.RPAREN,
                            TokenKind.RBRACKET,
                        ):
                            current_indent = indent
                        else:
                            current_indent = continuation_indent
                    else:
                        tail = " &" if force_trailing_continuation else ""
                        lines.append(frags[-1] + tail + comment_str)
                        break
                    continue

        # Budget: line_length - len(current_indent) - 2 (for ' &')
        budget = cfg.line_length - len(current_indent) - 2
        split_at = _pick_split_index(remaining, budget, current_depth)
        parts_acc = _render_prefix(remaining[:split_at], current_depth)

        for tok in remaining[:split_at]:
            if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
                current_depth += 1
            elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
                current_depth = max(0, current_depth - 1)

        chunk = "".join(parts_acc)
        remaining = remaining[split_at:]

        if remaining:
            lines.append(current_indent + chunk + " &")
        else:
            tail = " &" if force_trailing_continuation else ""
            lines.append(current_indent + chunk + tail + comment_str)

        current_indent = continuation_indent

    return lines if lines else [indent + line_body + comment_str]


# ---------------------------------------------------------------------------
# Multi-token normalisation
# ---------------------------------------------------------------------------

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

    action = tokens[close_idx + 1 :]
    # Strip leading whitespace-only tokens; if nothing remains it's just if(cond)
    action_nc = [t for t in action if t.kind != TokenKind.COMMENT]
    if not action_nc:
        return None

    return tokens[: close_idx + 1], action


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
    raw_lines = source.splitlines()
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
        return (
            first == "end"
            and len(toks) > 1
            and toks[1].text.lower() in ("subroutine", "function")
        )

    def _is_start_routine(toks: list[Token]) -> bool:
        if not toks or _is_end_routine(toks):
            return False
        return any(
            t.kind == TokenKind.KEYWORD and t.text.lower() in ("subroutine", "function")
            for t in toks
        )

    last_was_end_routine = False
    continuation_chain_indent: str | None = None
    saw_directive_after_continuation = False
    branch_base_levels: list[int] = []
    format_enabled = True
    next_line_no = 1

    def _has_explicit_trailing_continuation(line_tokens: list[Token]) -> bool:
        non_comment = [t for t in line_tokens if t.kind != TokenKind.COMMENT]
        return bool(non_comment and non_comment[-1].kind == TokenKind.CONTINUATION)

    def _is_compiler_directive_comment(line_tokens: list[Token]) -> bool:
        """True for standalone directive comments like `!$OMP ...`."""
        return (
            len(line_tokens) == 1
            and line_tokens[0].kind == TokenKind.COMMENT
            and line_tokens[0].text.startswith("!$")
        )

    for logical_line in iter_logical_lines(tokens):
        if logical_line:
            start_line = min(tok.line for tok in logical_line)
            end_line = max(tok.line for tok in logical_line)
            next_line_no = end_line + 1
        else:
            start_line = next_line_no
            end_line = next_line_no
            next_line_no += 1

        if start_line <= len(raw_lines):
            raw_span = raw_lines[start_line - 1 : min(end_line, len(raw_lines))]
        else:
            raw_span = [""]

        logical_line = merge_end_keywords(logical_line, cfg)
        normalised = [normalise(t) for t in logical_line]
        normalised = _canonicalise_declaration_tokens(normalised)

        first_raw = raw_span[0] if raw_span else ""
        control_match = _FORMAT_CONTROL_RE.match(first_raw)
        if format_enabled and control_match and control_match.group(1).lower() == "off":
            flush_pending(tracker.indent())
            output_lines.extend(raw_span)
            format_enabled = False
            continuation_chain_indent = None
            saw_directive_after_continuation = False
            last_was_end_routine = False
            continue

        if not format_enabled:
            output_lines.extend(raw_span)
            non_comment_disabled = [
                t for t in normalised if t.kind != TokenKind.COMMENT
            ]
            if non_comment_disabled:
                tracker.process_line(normalised)
            if control_match and control_match.group(1).lower() == "on":
                format_enabled = True
            continuation_chain_indent = None
            saw_directive_after_continuation = False
            last_was_end_routine = False
            continue

        # Preprocessor directives: flush buffer at current level, emit at column 0
        if normalised and normalised[0].kind == TokenKind.DIRECTIVE:
            flush_pending(tracker.indent())
            directive_text = normalised[0].text
            match = _DIRECTIVE_BRANCH_RE.match(directive_text.lstrip())
            if match is not None:
                directive = match.group(1).lower()
                if directive in ("if", "ifdef", "ifndef"):
                    branch_base_levels.append(tracker.level)
                elif directive in ("elif", "else") and branch_base_levels:
                    # Each sibling branch starts from the indentation level that
                    # existed before the opening #if-like directive.
                    tracker.level = branch_base_levels[-1]
                elif directive == "endif" and branch_base_levels:
                    branch_base_levels.pop()

            output_lines.append(directive_text)
            if continuation_chain_indent is not None:
                saw_directive_after_continuation = True
            last_was_end_routine = False
            continue

        non_comment = [t for t in normalised if t.kind != TokenKind.COMMENT]
        if not non_comment:
            if _is_compiler_directive_comment(normalised):
                flush_pending(tracker.indent())
                output_lines.append(tracker.indent() + normalised[0].text)
                last_was_end_routine = False
                continue
            # Comment-only or blank line: buffer until we know the next code indent
            pending.append(normalised[0].text if normalised else None)
            continue

        # Code line: emit buffered comments/blanks at this line's indentation level
        indent, _ = tracker.process_line(normalised)
        used_chain_indent = False
        if continuation_chain_indent is not None and saw_directive_after_continuation:
            indent = continuation_chain_indent
            used_chain_indent = True
        continuation_step = 0 if used_chain_indent else None

        # Normalise blank lines between consecutive routines to exactly two,
        # but only when there are no comments in the gap.
        if (
            last_was_end_routine
            and _is_start_routine(non_comment)
            and all(item is None for item in pending)
        ):
            pending.clear()
            output_lines.extend(["", ""])
        else:
            flush_pending(indent)

        split = _split_single_line_if(normalised)
        prefer_exploded = _prefer_exploded_arg_list(normalised)
        if split is not None:
            physical = render_logical_line(
                normalised,
                indent,
                cfg,
                continuation_step=continuation_step,
                prefer_exploded_arg_list=prefer_exploded,
            )
            if len(physical) == 1:
                # Fits on one line — keep the action on the same line as the if.
                output_lines.extend(physical)
            else:
                # Too long — split at the if/action boundary.
                cond_tokens, action_tokens = split
                cond_lines = render_logical_line(
                    cond_tokens,
                    indent,
                    cfg,
                    continuation_step=continuation_step,
                )
                cond_lines[-1] += " &"
                action_indent = indent + " " * cfg.indent_width
                action_lines = render_logical_line(action_tokens, action_indent, cfg)
                output_lines.extend(cond_lines)
                output_lines.extend(action_lines)
        else:
            physical = render_logical_line(
                normalised,
                indent,
                cfg,
                continuation_step=continuation_step,
                prefer_exploded_arg_list=prefer_exploded,
            )
            output_lines.extend(physical)

        if _has_explicit_trailing_continuation(normalised):
            if used_chain_indent:
                # Keep chained continuation segments aligned when directives
                # split a statement across multiple physical chunks.
                continuation_chain_indent = indent
            else:
                continuation_chain_indent = indent + " " * cfg.indent_width
        else:
            continuation_chain_indent = None
        saw_directive_after_continuation = False
        last_was_end_routine = _is_end_routine(non_comment)

    # Flush any trailing comments/blanks at the current (final) indent level
    flush_pending(tracker.indent())

    result = "\n".join(output_lines)

    if cfg.trailing_newline:
        result = result.rstrip("\n") + "\n"

    return result
