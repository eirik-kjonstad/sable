"""Shared token-level source analysis helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import Token, TokenKind

COMPACT_TO_SPACED_END_KEYWORDS: dict[str, str] = {
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
SPACED_TO_COMPACT_END_KEYWORDS: dict[str, str] = {
    v: k for k, v in COMPACT_TO_SPACED_END_KEYWORDS.items()
}

DECL_TYPE_KEYWORDS: frozenset[str] = frozenset(
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

_LEGACY_STAR_TYPE_KEYWORDS: frozenset[str] = frozenset(
    {
        "integer",
        "real",
        "complex",
        "logical",
        "character",
    }
)

_DECL_ATTRIBUTE_ORDER: dict[str, int] = {
    "dimension": 0,
    "codimension": 1,
    "allocatable": 2,
    "pointer": 3,
    "intent": 4,
    "target": 5,
    "contiguous": 6,
    "optional": 7,
    "parameter": 8,
    "value": 9,
    "save": 10,
    "public": 11,
    "private": 12,
    "protected": 13,
    "volatile": 14,
    "asynchronous": 15,
    "external": 16,
    "intrinsic": 17,
    "bind": 18,
    "pass": 19,
    "nopass": 20,
    "deferred": 21,
    "non_overridable": 22,
}
_DECL_ATTRIBUTE_DEFAULT_ORDER = len(_DECL_ATTRIBUTE_ORDER)

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

_PROCEDURE_PREFIXES: frozenset[str] = frozenset(
    {
        "pure",
        "recursive",
        "elemental",
        "impure",
        "non_recursive",
    }
)

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


@dataclass
class DeclarationParts:
    prefix_tokens: list[Token]
    entities: list[list[Token]]
    has_attributes: bool
    anchor: Token


def make_token(kind: TokenKind, text: str, anchor: Token) -> Token:
    return Token(kind, text, anchor.line, anchor.col)


def core_tokens(line_tokens: list[Token]) -> list[Token]:
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


def first_keyword(line_tokens: list[Token]) -> str:
    """Return the first keyword text, skipping optional leading labels."""
    core = core_tokens(line_tokens)
    if core and core[0].kind == TokenKind.KEYWORD:
        return core[0].text.lower()
    return ""


def is_select_guard(non_comment: list[Token]) -> bool:
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


def is_select_branch(non_comment: list[Token]) -> bool:
    """Return True for selector branch lines within SELECT constructs."""
    if not non_comment:
        return False
    if (
        non_comment[0].kind == TokenKind.KEYWORD
        and non_comment[0].text.lower() == "case"
    ):
        return True
    return is_select_guard(non_comment)


def is_end_select(non_comment: list[Token]) -> bool:
    """Return True for both `endselect` and `end select`."""
    if not non_comment:
        return False
    if (
        non_comment[0].kind == TokenKind.KEYWORD
        and non_comment[0].text.lower() == "endselect"
    ):
        return True
    return (
        len(non_comment) > 1
        and non_comment[0].kind == TokenKind.KEYWORD
        and non_comment[0].text.lower() == "end"
        and non_comment[1].kind == TokenKind.KEYWORD
        and non_comment[1].text.lower() == "select"
    )


def is_labelled_continue(line_tokens: list[Token]) -> bool:
    """Return True for lines like `15 continue`."""
    non_comment = [t for t in line_tokens if t.kind != TokenKind.COMMENT]
    return (
        len(non_comment) >= 2
        and non_comment[0].kind in (TokenKind.INTEGER, TokenKind.LABEL)
        and non_comment[1].kind == TokenKind.KEYWORD
        and non_comment[1].text.lower() == "continue"
    )


def is_block_opener(first: str, non_comment: list[Token]) -> bool:
    """Return True if the first keyword opens a new indentation block."""
    if first in _PROCEDURE_PREFIXES:
        return any(
            t.kind == TokenKind.KEYWORD and t.text.lower() in ("function", "subroutine")
            for t in non_comment
        )
    if first in _FUNCTION_TYPE_PREFIXES:
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
    if first == "abstract":
        return (
            len(non_comment) > 1
            and non_comment[1].kind == TokenKind.KEYWORD
            and non_comment[1].text.lower() == "interface"
        )
    if first not in _INDENT_OPEN:
        return False
    if first == "change":
        return (
            len(non_comment) > 1
            and non_comment[1].kind == TokenKind.KEYWORD
            and non_comment[1].text.lower() == "team"
        )
    if first == "module":
        for i, tok in enumerate(non_comment):
            if tok.kind == TokenKind.KEYWORD and tok.text.lower() == "module":
                if i + 1 < len(non_comment):
                    if non_comment[i + 1].text.lower() == "procedure":
                        return False
                break
    if first == "type":
        if any(t.kind == TokenKind.OP_ASSIGN for t in non_comment):
            return False
        if len(non_comment) > 1 and non_comment[1].text.lower() == "is":
            return True
        if len(non_comment) > 1 and non_comment[1].kind == TokenKind.LPAREN:
            return False
    if first == "class":
        if len(non_comment) > 1 and non_comment[1].kind == TokenKind.LPAREN:
            return False
        return len(non_comment) > 1 and non_comment[1].text.lower() in (
            "is",
            "default",
        )
    if first == "rank":
        return len(non_comment) > 1 and (
            non_comment[1].kind == TokenKind.LPAREN
            or non_comment[1].text.lower() == "default"
        )
    return True


def split_top_level_commas(tokens: list[Token]) -> list[list[Token]]:
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


def _is_legacy_type_keyword(token: Token | None) -> bool:
    return (
        token is not None
        and token.kind == TokenKind.KEYWORD
        and token.text.lower() in _LEGACY_STAR_TYPE_KEYWORDS
    )


def _is_double_precision_keyword_pair(
    first: Token | None, second: Token | None
) -> bool:
    return (
        first is not None
        and second is not None
        and first.kind == TokenKind.KEYWORD
        and second.kind == TokenKind.KEYWORD
        and first.text.lower() == "double"
        and second.text.lower() == "precision"
    )


def _consume_legacy_type_selector(tokens: list[Token], start: int) -> int | None:
    """Consume legacy ``*kind``/``*len`` selectors like ``real*8``."""
    if start >= len(tokens) or tokens[start].kind != TokenKind.OP_STAR:
        return None
    if start + 1 >= len(tokens):
        return None

    next_tok = tokens[start + 1]
    if next_tok.kind == TokenKind.INTEGER:
        return start + 2
    if next_tok.kind == TokenKind.LPAREN:
        next_i = _consume_paren_group(tokens, start + 1)
        return next_i if next_i != start + 1 else None
    return None


def is_legacy_type_selector_boundary(
    prev_prev: Token | None, prev: Token | None, curr: Token
) -> bool:
    if prev is None:
        return False
    if curr.kind == TokenKind.OP_STAR:
        return _is_legacy_type_keyword(prev) or _is_double_precision_keyword_pair(
            prev_prev, prev
        )
    if prev.kind == TokenKind.OP_STAR:
        return _is_legacy_type_keyword(prev_prev) or (
            prev_prev is not None
            and prev_prev.kind == TokenKind.KEYWORD
            and prev_prev.text.lower() == "precision"
        )
    return False


def _type_spec_end(tokens: list[Token]) -> int | None:
    if not tokens or tokens[0].kind != TokenKind.KEYWORD:
        return None

    first = tokens[0].text.lower()
    if first not in DECL_TYPE_KEYWORDS:
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
    elif i < len(tokens) and tokens[i].kind == TokenKind.OP_STAR:
        next_i = _consume_legacy_type_selector(tokens, i)
        if next_i is None:
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


def join_comma_segments(segments: list[list[Token]], anchor: Token) -> list[Token]:
    out: list[Token] = []
    for i, segment in enumerate(segments):
        if i > 0:
            out.append(make_token(TokenKind.COMMA, ",", anchor))
        out.extend(segment)
    return out


def parse_declaration(tokens: list[Token]) -> DeclarationParts | None:
    if not tokens or tokens[0].kind != TokenKind.KEYWORD:
        return None
    if tokens[0].text.lower() not in DECL_TYPE_KEYWORDS:
        return None

    core = core_tokens(tokens)
    if not core or len(core) != len(tokens):
        return None

    first = core[0].text.lower()
    if is_block_opener(first, core):
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
        attributes = split_top_level_commas(core[type_end:colon_idx])
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

    entities = split_top_level_commas(entity_tokens)
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
        prefix_tokens.append(make_token(TokenKind.COMMA, ",", anchor))
        prefix_tokens.extend(join_comma_segments(sorted_attrs, anchor))

    return DeclarationParts(
        prefix_tokens=prefix_tokens,
        entities=entities,
        has_attributes=bool(sorted_attrs),
        anchor=anchor,
    )


def canonicalise_declaration_tokens(tokens: list[Token]) -> list[Token]:
    comment: Token | None = None
    body = tokens
    if body and body[-1].kind == TokenKind.COMMENT:
        comment = body[-1]
        body = body[:-1]

    decl = parse_declaration(body)
    if decl is None:
        return tokens

    canonical = list(decl.prefix_tokens)
    canonical.append(make_token(TokenKind.DOUBLE_COLON, "::", decl.anchor))
    canonical.extend(join_comma_segments(decl.entities, decl.anchor))
    if comment is not None:
        canonical.append(comment)
    return canonical
