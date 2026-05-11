"""File-local semantic facts extracted from Fortran tokens.

This module deliberately stops short of being a full parser.  It collects the
stable facts dead-code rules need first: scopes, declarations, imports,
procedures, type-bound procedure bindings, and simple call references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..formatter import _parse_declaration
from ..tokens import Token, TokenKind


@dataclass(frozen=True, slots=True)
class Scope:
    kind: str
    name: str | None
    line: int
    col: int
    parent: int | None = None
    default_visibility: str = "public"
    host_name: str | None = None


@dataclass(frozen=True, slots=True)
class Declaration:
    name: str
    line: int
    col: int
    scope: int | None
    type_spec: str


@dataclass(frozen=True, slots=True)
class UseImport:
    module: str
    name: str
    line: int
    col: int
    scope: int | None
    imported_name: str | None = None
    end_line: int | None = None
    end_col: int | None = None
    statement_line: int | None = None
    statement_col: int | None = None
    item_index: int = 0
    item_count: int = 1
    remove_start_line: int | None = None
    remove_start_col: int | None = None
    remove_end_line: int | None = None
    remove_end_col: int | None = None


@dataclass(frozen=True, slots=True)
class Procedure:
    kind: str
    name: str
    line: int
    col: int
    scope: int | None
    visibility: str = "public"
    body_scope: int | None = None
    end_line: int | None = None
    end_col: int | None = None


@dataclass(frozen=True, slots=True)
class TypeBinding:
    name: str
    line: int
    col: int
    scope: int | None
    target: str | None = None
    visibility: str = "public"
    nopass: bool = False
    explicit_pass: bool = False
    end_line: int | None = None
    end_col: int | None = None
    statement_line: int | None = None
    statement_col: int | None = None
    item_index: int = 0
    item_count: int = 1
    remove_start_line: int | None = None
    remove_start_col: int | None = None
    remove_end_line: int | None = None
    remove_end_col: int | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    name: str
    line: int
    col: int
    scope: int | None
    kind: str
    qualifier: str | None = None


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    path: Path | None
    scopes: tuple[Scope, ...]
    declarations: tuple[Declaration, ...]
    use_imports: tuple[UseImport, ...]
    procedures: tuple[Procedure, ...]
    type_bindings: tuple[TypeBinding, ...]
    references: tuple[Reference, ...]


_STRUCTURAL_KINDS = {
    TokenKind.COMMENT,
    TokenKind.CONTINUATION,
    TokenKind.DIRECTIVE,
    TokenKind.NEWLINE,
    TokenKind.EOF,
}

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _core_tokens(tokens: list[Token]) -> list[Token]:
    return [tok for tok in tokens if tok.kind not in _STRUCTURAL_KINDS]


def _text(tok: Token) -> str:
    return tok.text.lower()


def _is_word(tok: Token, word: str) -> bool:
    return tok.kind in (TokenKind.KEYWORD, TokenKind.NAME) and _text(tok) == word


def _first_name(tokens: list[Token], start: int = 0) -> Token | None:
    for tok in tokens[start:]:
        if tok.kind == TokenKind.NAME:
            return tok
    return None


def _find_word(tokens: list[Token], word: str) -> int | None:
    return next((i for i, tok in enumerate(tokens) if _is_word(tok, word)), None)


def _top_level_commas(tokens: list[Token]) -> list[list[Token]]:
    segments: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for tok in tokens:
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        elif tok.kind == TokenKind.COMMA and depth == 0:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(tok)
    if current:
        segments.append(current)
    return segments


def _top_level_comma_spans(tokens: list[Token]) -> list[tuple[list[Token], int, int]]:
    segments: list[tuple[list[Token], int, int]] = []
    start = 0
    depth = 0
    for i, tok in enumerate(tokens):
        if tok.kind in (TokenKind.LPAREN, TokenKind.LBRACKET):
            depth += 1
        elif tok.kind in (TokenKind.RPAREN, TokenKind.RBRACKET):
            depth = max(0, depth - 1)
        elif tok.kind == TokenKind.COMMA and depth == 0:
            segment = tokens[start:i]
            if segment:
                segments.append((segment, start, i))
            start = i + 1
    segment = tokens[start:]
    if segment:
        segments.append((segment, start, len(tokens)))
    return segments


def _scope_visibility(scope: Scope | None) -> str:
    return scope.default_visibility if scope is not None else "public"


def _visibility_from_tokens(tokens: list[Token], default: str) -> str:
    visibility = default
    for tok in tokens:
        if _is_word(tok, "public"):
            visibility = "public"
        elif _is_word(tok, "private"):
            visibility = "private"
    return visibility


def _closer_kind(tokens: list[Token]) -> str | None:
    if not tokens:
        return None
    first = _text(tokens[0])
    compact = {
        "endmodule": "module",
        "endprogram": "program",
        "endsubroutine": "subroutine",
        "endfunction": "function",
        "endtype": "type",
        "endsubmodule": "submodule",
        "endinterface": "interface",
        "endprocedure": "procedure",
    }
    if first in compact:
        return compact[first]
    if first != "end" or len(tokens) < 2:
        return None
    second = _text(tokens[1])
    if second in {
        "module",
        "program",
        "subroutine",
        "function",
        "type",
        "submodule",
        "interface",
        "procedure",
    }:
        return second
    return None


def _is_module_opener(tokens: list[Token]) -> bool:
    return (
        len(tokens) >= 2
        and _is_word(tokens[0], "module")
        and not _is_word(tokens[1], "procedure")
        and tokens[1].kind == TokenKind.NAME
    )


def _submodule_opener(tokens: list[Token]) -> tuple[Token | None, Token | None]:
    if not tokens or not _is_word(tokens[0], "submodule"):
        return (None, None)

    lparen_idx = next(
        (i for i, tok in enumerate(tokens) if tok.kind == TokenKind.LPAREN),
        None,
    )
    if lparen_idx is None:
        return (None, None)

    rparen_idx = next(
        (
            i
            for i in range(lparen_idx + 1, len(tokens))
            if tokens[i].kind == TokenKind.RPAREN
        ),
        None,
    )
    if rparen_idx is None:
        return (None, None)

    host = _first_name(tokens[lparen_idx + 1 : rparen_idx])
    name = _first_name(tokens, rparen_idx + 1)
    return (host, name)


def _is_program_opener(tokens: list[Token]) -> bool:
    return len(tokens) >= 2 and _is_word(tokens[0], "program")


def _is_interface_opener(tokens: list[Token]) -> bool:
    return bool(tokens) and (
        _is_word(tokens[0], "interface")
        or (
            len(tokens) >= 2
            and _is_word(tokens[0], "abstract")
            and _is_word(tokens[1], "interface")
        )
    )


def _procedure_opener(tokens: list[Token]) -> tuple[str, Token] | None:
    if tokens and _is_word(tokens[0], "end"):
        return None
    for i, tok in enumerate(tokens):
        if _is_word(tok, "subroutine") or _is_word(tok, "function"):
            name = _first_name(tokens, i + 1)
            if name is not None:
                return (_text(tok), name)
    return None


def _module_procedure_opener(tokens: list[Token]) -> Token | None:
    if len(tokens) < 3:
        return None
    if not _is_word(tokens[0], "module") or not _is_word(tokens[1], "procedure"):
        return None
    return _first_name(tokens, 2)


def _type_opener(tokens: list[Token]) -> Token | None:
    if not tokens or not _is_word(tokens[0], "type"):
        return None
    if len(tokens) > 1 and tokens[1].kind == TokenKind.LPAREN:
        return None
    colon_idx = next(
        (i for i, tok in enumerate(tokens) if tok.kind == TokenKind.DOUBLE_COLON),
        None,
    )
    if colon_idx is not None:
        return _first_name(tokens, colon_idx + 1)
    return _first_name(tokens, 1)


def _type_opener_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    type_name = _type_opener(tokens)
    if type_name is None:
        return []
    return [
        _name_reference(tok, scope)
        for tok in tokens
        if tok.kind == TokenKind.NAME and tok != type_name
    ]


def _parse_use_imports(tokens: list[Token], scope: int | None) -> list[UseImport]:
    if not tokens or not _is_word(tokens[0], "use"):
        return []
    module_tok: Token | None = None
    for tok in tokens[1:]:
        if tok.kind == TokenKind.NAME:
            module_tok = tok
            break
    if module_tok is None:
        return []

    only_idx = _find_word(tokens, "only")
    if only_idx is None:
        return []
    colon_idx = next(
        (
            i
            for i in range(only_idx + 1, len(tokens))
            if tokens[i].kind == TokenKind.COLON
        ),
        None,
    )
    if colon_idx is None:
        return []

    import_tokens = tokens[colon_idx + 1 :]
    import_spans = _top_level_comma_spans(import_tokens)
    imports: list[UseImport] = []
    for item_index, (segment, start_idx, end_idx) in enumerate(import_spans):
        names = [tok for tok in segment if tok.kind == TokenKind.NAME]
        if not names:
            continue
        arrow_idx = next(
            (i for i, tok in enumerate(segment) if tok.kind == TokenKind.OP_ARROW),
            None,
        )
        if arrow_idx is not None:
            local = _first_name(segment[:arrow_idx])
            imported = _first_name(segment[arrow_idx + 1 :])
            if local is None:
                continue
            end_tok = segment[-1]
            remove_start = import_tokens[start_idx - 1] if start_idx > 0 else segment[0]
            remove_end = (
                import_tokens[end_idx]
                if end_idx < len(import_tokens)
                and import_tokens[end_idx].kind == TokenKind.COMMA
                else end_tok
            )
            imports.append(
                UseImport(
                    module=module_tok.text.lower(),
                    name=local.text.lower(),
                    imported_name=imported.text.lower() if imported else None,
                    line=local.line,
                    col=local.col,
                    scope=scope,
                    end_line=end_tok.line,
                    end_col=end_tok.col + len(end_tok.text),
                    statement_line=tokens[0].line,
                    statement_col=tokens[0].col,
                    item_index=item_index,
                    item_count=len(import_spans),
                    remove_start_line=remove_start.line,
                    remove_start_col=remove_start.col,
                    remove_end_line=remove_end.line,
                    remove_end_col=remove_end.col + len(remove_end.text),
                )
            )
        else:
            name = names[0]
            end_tok = segment[-1]
            remove_start = import_tokens[start_idx - 1] if start_idx > 0 else segment[0]
            remove_end = (
                import_tokens[end_idx]
                if end_idx < len(import_tokens)
                and import_tokens[end_idx].kind == TokenKind.COMMA
                else end_tok
            )
            imports.append(
                UseImport(
                    module=module_tok.text.lower(),
                    name=name.text.lower(),
                    line=name.line,
                    col=name.col,
                    scope=scope,
                    end_line=end_tok.line,
                    end_col=end_tok.col + len(end_tok.text),
                    statement_line=tokens[0].line,
                    statement_col=tokens[0].col,
                    item_index=item_index,
                    item_count=len(import_spans),
                    remove_start_line=remove_start.line,
                    remove_start_col=remove_start.col,
                    remove_end_line=remove_end.line,
                    remove_end_col=remove_end.col + len(remove_end.text),
                )
            )
    return imports


def _parse_declarations(tokens: list[Token], scope: int | None) -> list[Declaration]:
    decl = _parse_declaration(tokens)
    if decl is None:
        return []
    type_spec = " ".join(tok.text.lower() for tok in decl.prefix_tokens)
    declarations: list[Declaration] = []
    for entity in decl.entities:
        name = _first_name(entity)
        if name is None:
            continue
        declarations.append(
            Declaration(
                name=name.text.lower(),
                line=name.line,
                col=name.col,
                scope=scope,
                type_spec=type_spec,
            )
        )
    return declarations


def _name_reference(tok: Token, scope: int | None, kind: str = "name") -> Reference:
    return Reference(
        name=tok.text.lower(),
        line=tok.line,
        col=tok.col,
        scope=scope,
        kind=kind,
    )


def _declaration_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    decl = _parse_declaration(tokens)
    if decl is None:
        return []

    refs = [
        _name_reference(tok, scope)
        for tok in decl.prefix_tokens
        if tok.kind == TokenKind.NAME
    ]
    for entity in decl.entities:
        skipped_entity_name = False
        for tok in entity:
            if tok.kind != TokenKind.NAME:
                continue
            if not skipped_entity_name:
                skipped_entity_name = True
                continue
            refs.append(_name_reference(tok, scope))
    return refs


def _parse_type_bindings(
    tokens: list[Token], scope: int | None, default_visibility: str
) -> list[TypeBinding]:
    if not tokens or not _is_word(tokens[0], "procedure"):
        return []
    colon_idx = next(
        (i for i, tok in enumerate(tokens) if tok.kind == TokenKind.DOUBLE_COLON),
        None,
    )
    if colon_idx is None:
        return []
    visibility = _visibility_from_tokens(tokens[:colon_idx], default_visibility)
    nopass = any(_is_word(tok, "nopass") for tok in tokens[:colon_idx])
    explicit_pass = any(_is_word(tok, "pass") for tok in tokens[:colon_idx])
    bindings: list[TypeBinding] = []
    binding_tokens = tokens[colon_idx + 1 :]
    binding_spans = _top_level_comma_spans(binding_tokens)
    for item_index, (segment, start_idx, end_idx) in enumerate(binding_spans):
        arrow_idx = next(
            (i for i, tok in enumerate(segment) if tok.kind == TokenKind.OP_ARROW),
            None,
        )
        if arrow_idx is None:
            name = _first_name(segment)
            target = None
        else:
            name = _first_name(segment[:arrow_idx])
            target_tok = _first_name(segment[arrow_idx + 1 :])
            target = target_tok.text.lower() if target_tok else None
        if name is None:
            continue
        end_tok = segment[-1]
        remove_start = binding_tokens[start_idx - 1] if start_idx > 0 else segment[0]
        remove_end = (
            binding_tokens[end_idx]
            if end_idx < len(binding_tokens)
            and binding_tokens[end_idx].kind == TokenKind.COMMA
            else end_tok
        )
        bindings.append(
            TypeBinding(
                name=name.text.lower(),
                line=name.line,
                col=name.col,
                scope=scope,
                target=target,
                visibility=visibility,
                nopass=nopass,
                explicit_pass=explicit_pass,
                end_line=end_tok.line,
                end_col=end_tok.col + len(end_tok.text),
                statement_line=tokens[0].line,
                statement_col=tokens[0].col,
                item_index=item_index,
                item_count=len(binding_spans),
                remove_start_line=remove_start.line,
                remove_start_col=remove_start.col,
                remove_end_line=remove_end.line,
                remove_end_col=remove_end.col + len(remove_end.text),
            )
        )
    return bindings


def _type_binding_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    if not tokens or not _is_word(tokens[0], "procedure"):
        return []
    colon_idx = next(
        (i for i, tok in enumerate(tokens) if tok.kind == TokenKind.DOUBLE_COLON),
        None,
    )
    if colon_idx is None:
        return []
    return [
        _name_reference(tok, scope)
        for tok in tokens[:colon_idx]
        if tok.kind == TokenKind.NAME
    ]


def _type_bound_generic_references(
    tokens: list[Token], scope: int | None
) -> list[Reference]:
    if not tokens or not _is_word(tokens[0], "generic"):
        return []
    arrow_idx = next(
        (i for i, tok in enumerate(tokens) if tok.kind == TokenKind.OP_ARROW),
        None,
    )
    if arrow_idx is None:
        return []
    return [
        Reference(
            name=tok.text.lower(),
            line=tok.line,
            col=tok.col,
            scope=scope,
            kind="type_bound_generic_target",
        )
        for segment in _top_level_commas(tokens[arrow_idx + 1 :])
        for tok in segment
        if tok.kind == TokenKind.NAME
    ]


def _call_reference(tokens: list[Token], scope: int | None) -> Reference | None:
    call_idx = _find_word(tokens, "call")
    if call_idx is None:
        return None
    after = tokens[call_idx + 1 :]
    if len(after) >= 3 and after[0].kind == TokenKind.NAME:
        if after[1].kind == TokenKind.OP_PERCENT and after[2].kind == TokenKind.NAME:
            return Reference(
                name=after[2].text.lower(),
                line=after[2].line,
                col=after[2].col,
                scope=scope,
                kind="type_bound_call",
                qualifier=after[0].text.lower(),
            )
    name = _first_name(after)
    if name is None:
        return None
    return Reference(
        name=name.text.lower(),
        line=name.line,
        col=name.col,
        scope=scope,
        kind="call",
    )


def _selector_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    refs: list[Reference] = []
    for i, tok in enumerate(tokens[:-1]):
        if tok.kind != TokenKind.OP_PERCENT or tokens[i + 1].kind != TokenKind.NAME:
            continue
        qualifier = tokens[i - 1].text.lower() if i > 0 else None
        refs.append(
            Reference(
                name=tokens[i + 1].text.lower(),
                line=tokens[i + 1].line,
                col=tokens[i + 1].col,
                scope=scope,
                kind="selector",
                qualifier=qualifier,
            )
        )
    return refs


def _function_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    refs: list[Reference] = []
    skip_previous = {"call", "function", "subroutine", "program", "module", "type"}
    for i, tok in enumerate(tokens[:-1]):
        if tok.kind != TokenKind.NAME or tokens[i + 1].kind != TokenKind.LPAREN:
            continue
        previous = _text(tokens[i - 1]) if i > 0 else ""
        if i > 0 and tokens[i - 1].kind == TokenKind.OP_PERCENT:
            continue
        if previous in skip_previous:
            continue
        refs.append(
            Reference(
                name=tok.text.lower(),
                line=tok.line,
                col=tok.col,
                scope=scope,
                kind="function_call",
            )
        )
    return refs


def _name_references(tokens: list[Token], scope: int | None) -> list[Reference]:
    return [_name_reference(tok, scope) for tok in tokens if tok.kind == TokenKind.NAME]


def _openmp_sentinel_references(
    tokens: list[Token], scope: int | None
) -> list[Reference]:
    refs: list[Reference] = []
    for tok in tokens:
        if tok.kind != TokenKind.COMMENT or not tok.text.startswith("!$"):
            continue
        for match in _NAME_RE.finditer(tok.text[2:]):
            refs.append(
                Reference(
                    name=match.group(0).lower(),
                    line=tok.line,
                    col=tok.col + 2 + match.start(),
                    scope=scope,
                    kind="openmp_sentinel",
                )
            )
    return refs


def analyze_file(
    source: str,
    tokens: list[Token],
    logical_lines: list[list[Token]],
    path: Path | None = None,
) -> FileAnalysis:
    """Collect file-local semantic facts from an already-tokenized source file."""
    del source
    scopes: list[Scope] = []
    declarations: list[Declaration] = []
    use_imports: list[UseImport] = []
    procedures: list[Procedure] = []
    type_bindings: list[TypeBinding] = []
    references: list[Reference] = []
    stack: list[int] = []

    def current_scope_index() -> int | None:
        return stack[-1] if stack else None

    def current_scope() -> Scope | None:
        idx = current_scope_index()
        return scopes[idx] if idx is not None else None

    def push_scope(
        kind: str,
        name: Token | None,
        opener: Token,
        host_name: str | None = None,
        default_visibility: str | None = None,
    ) -> int:
        idx = len(scopes)
        parent = current_scope_index()
        scopes.append(
            Scope(
                kind=kind,
                name=name.text.lower() if name else None,
                line=opener.line,
                col=opener.col,
                parent=parent,
                default_visibility=(
                    default_visibility
                    if default_visibility is not None
                    else _scope_visibility(current_scope())
                ),
                host_name=host_name,
            )
        )
        stack.append(idx)
        return idx

    def pop_scope(kind: str) -> int | None:
        if not any(scopes[idx].kind == kind for idx in stack):
            return None
        while stack:
            idx = stack.pop()
            if scopes[idx].kind == kind:
                return idx
        return None

    def close_procedure(body_scope: int, closer: Token) -> None:
        for i in range(len(procedures) - 1, -1, -1):
            procedure = procedures[i]
            if procedure.body_scope != body_scope or procedure.end_line is not None:
                continue
            procedures[i] = Procedure(
                kind=procedure.kind,
                name=procedure.name,
                line=procedure.line,
                col=procedure.col,
                scope=procedure.scope,
                visibility=procedure.visibility,
                body_scope=procedure.body_scope,
                end_line=closer.line,
                end_col=closer.col + len(closer.text),
            )
            return

    for logical_line in logical_lines:
        references.extend(
            _openmp_sentinel_references(logical_line, current_scope_index())
        )
        core = _core_tokens(logical_line)
        if not core:
            continue

        closer = _closer_kind(core)
        if closer is not None:
            closed_scope = pop_scope(closer)
            if closed_scope is not None and closer in {
                "subroutine",
                "function",
                "procedure",
            }:
                close_procedure(closed_scope, core[-1])
            continue

        scope_idx = current_scope_index()
        scope = current_scope()

        if len(core) == 1 and (
            _is_word(core[0], "private") or _is_word(core[0], "public")
        ):
            if scope_idx is not None:
                scopes[scope_idx] = Scope(
                    kind=scopes[scope_idx].kind,
                    name=scopes[scope_idx].name,
                    line=scopes[scope_idx].line,
                    col=scopes[scope_idx].col,
                    parent=scopes[scope_idx].parent,
                    default_visibility=_text(core[0]),
                    host_name=scopes[scope_idx].host_name,
                )
            continue

        submodule_host, submodule_name = _submodule_opener(core)
        if submodule_host is not None:
            push_scope(
                "submodule",
                submodule_name,
                core[0],
                host_name=submodule_host.text.lower(),
            )
            continue

        if _is_module_opener(core):
            push_scope("module", core[1], core[0])
            continue

        if _is_program_opener(core):
            name = _first_name(core, 1)
            push_scope("program", name, core[0])
            continue

        if _is_interface_opener(core):
            push_scope("interface", _first_name(core, 1), core[0])
            continue

        type_name = _type_opener(core)
        if type_name is not None:
            references.extend(_type_opener_references(core, scope_idx))
            push_scope("type", type_name, core[0], default_visibility="public")
            continue

        module_proc_name = _module_procedure_opener(core)
        if (
            module_proc_name is not None
            and scope is not None
            and scope.kind == "submodule"
        ):
            proc_scope = push_scope("procedure", module_proc_name, core[0])
            procedures.append(
                Procedure(
                    kind="procedure",
                    name=module_proc_name.text.lower(),
                    line=module_proc_name.line,
                    col=module_proc_name.col,
                    scope=scope_idx,
                    visibility=_scope_visibility(scope),
                    body_scope=proc_scope,
                )
            )
            continue

        proc = _procedure_opener(core)
        if proc is not None:
            kind, name = proc
            proc_scope = push_scope(kind, name, core[0])
            procedures.append(
                Procedure(
                    kind=kind,
                    name=name.text.lower(),
                    line=name.line,
                    col=name.col,
                    scope=scope_idx,
                    visibility=_scope_visibility(scope),
                    body_scope=proc_scope,
                )
            )
            continue

        default_visibility = _scope_visibility(scope)
        if scope is not None and scope.kind == "type":
            parsed_bindings = _parse_type_bindings(core, scope_idx, default_visibility)
            if parsed_bindings:
                type_bindings.extend(parsed_bindings)
                references.extend(_type_binding_references(core, scope_idx))
                continue
            generic_references = _type_bound_generic_references(core, scope_idx)
            if generic_references:
                references.extend(generic_references)
                continue

        parsed_imports = _parse_use_imports(core, scope_idx)
        if parsed_imports:
            use_imports.extend(parsed_imports)
            continue

        parsed_declarations = _parse_declarations(core, scope_idx)
        if parsed_declarations:
            declarations.extend(parsed_declarations)
            references.extend(_declaration_references(core, scope_idx))
            continue

        call_ref = _call_reference(core, scope_idx)
        if call_ref is not None:
            references.append(call_ref)
        references.extend(_selector_references(core, scope_idx))
        references.extend(_function_references(core, scope_idx))
        references.extend(_name_references(core, scope_idx))

    return FileAnalysis(
        path=path,
        scopes=tuple(scopes),
        declarations=tuple(declarations),
        use_imports=tuple(use_imports),
        procedures=tuple(procedures),
        type_bindings=tuple(type_bindings),
        references=tuple(references),
    )
