"""Semantic lint rules backed by lightweight file analysis."""

from __future__ import annotations

from ..analysis import TypeBinding, UseImport
from ..diagnostics import Diagnostic, Fix, FixSafety, RuleContext, Severity, TextEdit
from ..tokens import Token, TokenKind


def _line_col_to_offset(ctx: RuleContext, line: int, col: int) -> int:
    return ctx.line_starts[line - 1] + col - 1


def _line_end_offset(ctx: RuleContext, line: int) -> int:
    if line < len(ctx.line_starts):
        return ctx.line_starts[line] - 1
    return len(ctx.source)


def _line_end_with_newline_offset(ctx: RuleContext, line: int) -> int:
    if line < len(ctx.line_starts):
        return ctx.line_starts[line]
    return len(ctx.source)


def _expand_over_following_inline_space(ctx: RuleContext, offset: int) -> int:
    while offset < len(ctx.source) and ctx.source[offset] in " \t":
        offset += 1
    return offset


class SBL201UnusedUseOnlyImportRule:
    """Detect names imported via ``use ..., only:`` that are never referenced."""

    rule_id = "SBL201"
    summary = "Name imported with 'use ..., only:' is unused."

    def _statement_key(self, imported: UseImport) -> tuple[int, int]:
        return (
            imported.statement_line or imported.line,
            imported.statement_col or imported.col,
        )

    def _fix_for_group(
        self, ctx: RuleContext, imports: list[UseImport], unused: list[UseImport]
    ) -> Fix | None:
        if not unused:
            return None

        if len(unused) == len(imports):
            start_line = min(item.statement_line or item.line for item in imports)
            end_line = max(item.end_line or item.line for item in imports)
            return Fix(
                message="Remove unused use-only import statement",
                edits=(
                    TextEdit(
                        start=_line_col_to_offset(ctx, start_line, 1),
                        end=_line_end_with_newline_offset(ctx, end_line),
                        replacement="",
                    ),
                ),
                safety=FixSafety.UNSAFE,
            )

        unused_indices = {item.item_index for item in unused}
        edits: list[TextEdit] = []
        sorted_imports = sorted(imports, key=lambda item: item.item_index)
        i = 0
        while i < len(sorted_imports):
            item = sorted_imports[i]
            if item.item_index not in unused_indices:
                i += 1
                continue

            run_start = i
            run_end = i
            while (
                run_end + 1 < len(sorted_imports)
                and sorted_imports[run_end + 1].item_index in unused_indices
            ):
                run_end += 1

            first = sorted_imports[run_start]
            last = sorted_imports[run_end]
            if first.remove_start_line is None or first.remove_start_col is None:
                return None
            if (
                first.item_index == 0
                and last.remove_end_line is not None
                and last.remove_end_col is not None
                and last.item_index < len(sorted_imports) - 1
            ):
                end = _line_col_to_offset(
                    ctx, last.remove_end_line, last.remove_end_col
                )
                end = _expand_over_following_inline_space(ctx, end)
            else:
                end = _line_col_to_offset(
                    ctx, last.end_line or last.line, last.end_col or last.col
                )

            start = _line_col_to_offset(
                ctx, first.remove_start_line, first.remove_start_col
            )
            edits.append(TextEdit(start=start, end=end, replacement=""))
            i = run_end + 1

        return Fix(
            message="Remove unused use-only import",
            edits=tuple(edits),
            safety=FixSafety.UNSAFE,
        )

    def _fixes_by_statement(self, ctx: RuleContext) -> dict[tuple[int, int], Fix]:
        if ctx.analysis is None:
            return {}

        referenced_names = self._referenced_names_by_scope(ctx)
        imports_by_statement: dict[tuple[int, int], list[UseImport]] = {}
        for imported in ctx.analysis.use_imports:
            imports_by_statement.setdefault(self._statement_key(imported), []).append(
                imported
            )

        fixes: dict[tuple[int, int], Fix] = {}
        for key, imports in imports_by_statement.items():
            unused = [
                imported
                for imported in imports
                if imported.name not in referenced_names.get(imported.scope, set())
            ]
            fix = self._fix_for_group(ctx, imports, unused)
            if fix is not None:
                fixes[key] = fix
        return fixes

    def _referenced_names_by_scope(
        self, ctx: RuleContext
    ) -> dict[int | None, set[str]]:
        referenced: dict[int | None, set[str]] = {}
        if ctx.analysis is None:
            return referenced

        for ref in ctx.analysis.references:
            idx = ref.scope
            referenced.setdefault(idx, set()).add(ref.name)
            while idx is not None:
                referenced.setdefault(idx, set()).add(ref.name)
                idx = ctx.analysis.scopes[idx].parent

        external = ctx.external_references or {}
        for idx, scope in enumerate(ctx.analysis.scopes):
            if scope.name is None:
                continue
            referenced.setdefault(idx, set()).update(external.get(scope.name, set()))

        return referenced

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        if ctx.analysis is None:
            return []

        referenced_names = self._referenced_names_by_scope(ctx)
        fixes_by_statement = self._fixes_by_statement(ctx)
        diagnostics: list[Diagnostic] = []
        for imported in ctx.analysis.use_imports:
            if imported.name in referenced_names.get(imported.scope, set()):
                continue
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=(
                        f"Imported name '{imported.name}' from module "
                        f"'{imported.module}' is unused."
                    ),
                    line=imported.line,
                    col=imported.col,
                    end_line=imported.line,
                    end_col=imported.col + len(imported.name),
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=fixes_by_statement.get(self._statement_key(imported)),
                )
            )
        return diagnostics


class SBL202UnusedPrivateTypeBoundProcedureRule:
    """Detect private type-bound procedure bindings that are never selected."""

    rule_id = "SBL202"
    summary = "Private type-bound procedure binding is never selected."

    def _statement_key(self, binding: TypeBinding) -> tuple[int, int]:
        return (
            binding.statement_line or binding.line,
            binding.statement_col or binding.col,
        )

    def _fix_for_group(
        self, ctx: RuleContext, bindings: list[TypeBinding], unused: list[TypeBinding]
    ) -> Fix | None:
        if not unused:
            return None

        if len(unused) == len(bindings):
            start_line = min(item.statement_line or item.line for item in bindings)
            end_line = max(item.end_line or item.line for item in bindings)
            edits = [
                TextEdit(
                    start=_line_col_to_offset(ctx, start_line, 1),
                    end=_line_end_with_newline_offset(ctx, end_line),
                    replacement="",
                )
            ]
            edits.extend(self._implementation_body_edits(ctx, unused))
            return Fix(
                message="Remove unused private type-bound procedure binding statement",
                edits=tuple(edits),
                safety=FixSafety.UNSAFE,
            )

        unused_indices = {item.item_index for item in unused}
        edits: list[TextEdit] = []
        sorted_bindings = sorted(bindings, key=lambda item: item.item_index)
        i = 0
        while i < len(sorted_bindings):
            item = sorted_bindings[i]
            if item.item_index not in unused_indices:
                i += 1
                continue

            run_start = i
            run_end = i
            while (
                run_end + 1 < len(sorted_bindings)
                and sorted_bindings[run_end + 1].item_index in unused_indices
            ):
                run_end += 1

            first = sorted_bindings[run_start]
            last = sorted_bindings[run_end]
            if first.remove_start_line is None or first.remove_start_col is None:
                return None
            if (
                first.item_index == 0
                and last.remove_end_line is not None
                and last.remove_end_col is not None
                and last.item_index < len(sorted_bindings) - 1
            ):
                end = _line_col_to_offset(
                    ctx, last.remove_end_line, last.remove_end_col
                )
                end = _expand_over_following_inline_space(ctx, end)
            else:
                end = _line_col_to_offset(
                    ctx, last.end_line or last.line, last.end_col or last.col
                )

            start = _line_col_to_offset(
                ctx, first.remove_start_line, first.remove_start_col
            )
            edits.append(TextEdit(start=start, end=end, replacement=""))
            i = run_end + 1

        edits.extend(self._implementation_body_edits(ctx, unused))
        return Fix(
            message="Remove unused private type-bound procedure binding",
            edits=tuple(edits),
            safety=FixSafety.UNSAFE,
        )

    def _ancestor_scope(
        self, ctx: RuleContext, scope_idx: int | None, kind: str
    ) -> tuple[int, str] | None:
        if ctx.analysis is None:
            return None
        idx = scope_idx
        while idx is not None:
            scope = ctx.analysis.scopes[idx]
            if scope.kind == kind and scope.name is not None:
                return (idx, scope.name)
            idx = scope.parent
        return None

    def _is_descendant_scope(
        self, ctx: RuleContext, scope_idx: int | None, ancestor_idx: int
    ) -> bool:
        if ctx.analysis is None:
            return False
        idx = scope_idx
        while idx is not None:
            if idx == ancestor_idx:
                return True
            idx = ctx.analysis.scopes[idx].parent
        return False

    def _is_inside_scope(
        self, ctx: RuleContext, scope_idx: int | None, ancestor_kind: str
    ) -> bool:
        if ctx.analysis is None:
            return False
        idx = scope_idx
        while idx is not None:
            scope = ctx.analysis.scopes[idx]
            if scope.kind == ancestor_kind:
                return True
            idx = scope.parent
        return False

    def _selector_names_for_module(
        self, ctx: RuleContext, module_idx: int, module_name: str
    ) -> set[str]:
        names: set[str] = set()
        if ctx.analysis is None:
            return names
        for ref in ctx.analysis.references:
            if ref.kind != "selector":
                continue
            if self._is_descendant_scope(ctx, ref.scope, module_idx):
                names.add(ref.name)
        names.update((ctx.external_selectors or {}).get(module_name, set()))
        return names

    def _generic_targets_by_type_scope(
        self, ctx: RuleContext
    ) -> dict[int | None, set[str]]:
        targets: dict[int | None, set[str]] = {}
        if ctx.analysis is None:
            return targets
        for ref in ctx.analysis.references:
            if ref.kind == "type_bound_generic_target":
                targets.setdefault(ref.scope, set()).add(ref.name)
        return targets

    def _is_used(
        self,
        ctx: RuleContext,
        binding: TypeBinding,
        *,
        selectors: set[str],
        generic_targets: dict[int | None, set[str]],
        direct_calls: set[str],
    ) -> bool:
        if binding.name in selectors:
            return True
        if binding.name in generic_targets.get(binding.scope, set()):
            return True
        return (binding.target or binding.name) in direct_calls

    def _directly_called_targets_by_module(
        self, ctx: RuleContext, module_idx: int, module_name: str
    ) -> set[str]:
        names: set[str] = set()
        if ctx.analysis is None:
            return names
        for ref in ctx.analysis.references:
            if ref.kind not in {"call", "function_call"}:
                continue
            if self._is_descendant_scope(ctx, ref.scope, module_idx):
                names.add(ref.name)
        names.update((ctx.external_direct_calls or {}).get(module_name, set()))
        return names

    def _all_generic_targets(self, ctx: RuleContext) -> set[str]:
        if ctx.analysis is None:
            return set()
        return {
            ref.name
            for ref in ctx.analysis.references
            if ref.kind == "type_bound_generic_target"
        }

    def _target_body_edit(
        self, ctx: RuleContext, binding: TypeBinding
    ) -> TextEdit | None:
        if ctx.analysis is None:
            return None
        module_scope = self._ancestor_scope(ctx, binding.scope, "module")
        if module_scope is None:
            return None
        module_idx, module_name = module_scope
        target = binding.target or binding.name
        if target in self._directly_called_targets_by_module(
            ctx, module_idx, module_name
        ):
            return None
        if target in self._all_generic_targets(ctx):
            return None

        project_bodies = ctx.external_procedure_bodies or {}
        body_candidates = project_bodies.get(module_name, {}).get(target, ())
        if body_candidates:
            if len(body_candidates) != 1:
                return None
            body = body_candidates[0]
            edit_path = body.path if body.path != ctx.path else None
            return TextEdit(
                start=body.start,
                end=body.end,
                replacement="",
                path=edit_path,
            )

        candidates = []
        for procedure in ctx.analysis.procedures:
            if procedure.name != target:
                continue
            if procedure.end_line is None:
                continue
            if self._is_inside_scope(ctx, procedure.scope, "interface"):
                continue
            if not (
                self._is_descendant_scope(ctx, procedure.scope, module_idx)
                or procedure.scope == module_idx
            ):
                continue
            candidates.append(procedure)
        if len(candidates) != 1:
            return None

        procedure = candidates[0]
        return TextEdit(
            start=_line_col_to_offset(ctx, procedure.line, 1),
            end=_line_end_with_newline_offset(
                ctx, procedure.end_line or procedure.line
            ),
            replacement="",
        )

    def _implementation_body_edits(
        self, ctx: RuleContext, unused: list[TypeBinding]
    ) -> list[TextEdit]:
        edits: list[TextEdit] = []
        seen: set[tuple[int, int, str]] = set()
        for binding in unused:
            edit = self._target_body_edit(ctx, binding)
            if edit is None:
                continue
            key = (edit.start, edit.end, edit.replacement)
            if key in seen:
                continue
            seen.add(key)
            edits.append(edit)
        return edits

    def _unused_bindings(
        self, ctx: RuleContext
    ) -> tuple[list[TypeBinding], dict[tuple[int, int], Fix]]:
        if ctx.analysis is None:
            return ([], {})

        generic_targets = self._generic_targets_by_type_scope(ctx)
        selectors_by_module: dict[int, set[str]] = {}
        direct_calls_by_module: dict[int, set[str]] = {}
        unused: list[TypeBinding] = []
        bindings_by_statement: dict[tuple[int, int], list[TypeBinding]] = {}
        for binding in ctx.analysis.type_bindings:
            bindings_by_statement.setdefault(self._statement_key(binding), []).append(
                binding
            )
            if binding.visibility != "private":
                continue
            module_scope = self._ancestor_scope(ctx, binding.scope, "module")
            if module_scope is None:
                continue
            module_idx, module_name = module_scope
            selectors = selectors_by_module.setdefault(
                module_idx,
                self._selector_names_for_module(ctx, module_idx, module_name),
            )
            direct_calls = direct_calls_by_module.setdefault(
                module_idx,
                self._directly_called_targets_by_module(ctx, module_idx, module_name),
            )
            if self._is_used(
                ctx,
                binding,
                selectors=selectors,
                generic_targets=generic_targets,
                direct_calls=direct_calls,
            ):
                continue
            unused.append(binding)

        unused_by_statement: dict[tuple[int, int], list[TypeBinding]] = {}
        for binding in unused:
            unused_by_statement.setdefault(self._statement_key(binding), []).append(
                binding
            )

        fixes: dict[tuple[int, int], Fix] = {}
        for key, unused_group in unused_by_statement.items():
            fix = self._fix_for_group(ctx, bindings_by_statement[key], unused_group)
            if fix is not None:
                fixes[key] = fix
        return (unused, fixes)

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        if ctx.analysis is None:
            return []

        unused_bindings, fixes_by_statement = self._unused_bindings(ctx)
        diagnostics: list[Diagnostic] = []
        for binding in unused_bindings:
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=(
                        f"Private type-bound procedure binding '{binding.name}' "
                        "is never selected."
                    ),
                    line=binding.line,
                    col=binding.col,
                    end_line=binding.line,
                    end_col=binding.col + len(binding.name),
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=fixes_by_statement.get(self._statement_key(binding)),
                )
            )
        return diagnostics


class SBL203DirectPrivateNopassBindingCallRule(
    SBL202UnusedPrivateTypeBoundProcedureRule
):
    """Detect direct calls to private nopass type-bound procedure targets."""

    rule_id = "SBL203"
    summary = "Private nopass type-bound procedure target is called directly."

    def _direct_call_refs_for_module(
        self, ctx: RuleContext, module_idx: int
    ) -> list[tuple[str, int, int, int | None]]:
        refs: list[tuple[str, int, int, int | None]] = []
        if ctx.analysis is None:
            return refs
        for ref in ctx.analysis.references:
            if ref.kind not in {"call", "function_call"}:
                continue
            if self._is_descendant_scope(ctx, ref.scope, module_idx):
                refs.append((ref.name, ref.line, ref.col, ref.scope))
        return refs

    def _binding_object_name(
        self, ctx: RuleContext, scope_idx: int | None, binding: TypeBinding
    ) -> str | None:
        if ctx.analysis is None or scope_idx is None or binding.scope is None:
            return None
        type_scope = ctx.analysis.scopes[binding.scope]
        if type_scope.kind != "type" or type_scope.name is None:
            return None

        expected_class = f"class({type_scope.name})"
        expected_type = f"type({type_scope.name})"
        candidates = []
        for declaration in ctx.analysis.declarations:
            if declaration.scope != scope_idx:
                continue
            type_spec = "".join(declaration.type_spec.split())
            if type_spec.startswith(expected_class) or type_spec.startswith(
                expected_type
            ):
                candidates.append(declaration.name)
        unique = sorted(set(candidates))
        if len(unique) != 1:
            return None
        return unique[0]

    def _fix_for_direct_call(
        self,
        ctx: RuleContext,
        *,
        line: int,
        col: int,
        target: str,
        binding_name: str,
        object_name: str,
    ) -> Fix:
        return Fix(
            message=f"Call private nopass binding through {object_name}",
            edits=(
                TextEdit(
                    start=_line_col_to_offset(ctx, line, col),
                    end=_line_col_to_offset(ctx, line, col + len(target)),
                    replacement=f"{object_name}%{binding_name}",
                ),
            ),
            safety=FixSafety.UNSAFE,
        )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        if ctx.analysis is None:
            return []

        local_calls_by_module: dict[int, list[tuple[str, int, int, int | None]]] = {}
        diagnostics: list[Diagnostic] = []
        for binding in ctx.analysis.type_bindings:
            if binding.visibility != "private" or not binding.nopass:
                continue
            module_scope = self._ancestor_scope(ctx, binding.scope, "module")
            if module_scope is None:
                continue
            module_idx, module_name = module_scope
            local_calls = local_calls_by_module.setdefault(
                module_idx,
                self._direct_call_refs_for_module(ctx, module_idx),
            )
            target = binding.target or binding.name
            found_local_call = False
            for call_name, line, col, scope_idx in local_calls:
                if call_name != target:
                    continue
                found_local_call = True
                fix = None
                object_name = self._binding_object_name(ctx, scope_idx, binding)
                if object_name is not None:
                    fix = self._fix_for_direct_call(
                        ctx,
                        line=line,
                        col=col,
                        target=target,
                        binding_name=binding.name,
                        object_name=object_name,
                    )
                diagnostics.append(
                    Diagnostic(
                        rule_id=self.rule_id,
                        message=(
                            f"Private nopass type-bound procedure target '{target}' "
                            f"for binding '{binding.name}' is called directly."
                        ),
                        line=line,
                        col=col,
                        end_line=line,
                        end_col=col + len(target),
                        severity=Severity.WARNING,
                        path=ctx.path,
                        fix=fix,
                    )
                )
            if found_local_call:
                continue
            if target not in (ctx.external_direct_calls or {}).get(module_name, set()):
                continue
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=(
                        f"Private nopass type-bound procedure target '{target}' "
                        f"for binding '{binding.name}' is called directly."
                    ),
                    line=binding.line,
                    col=binding.col,
                    end_line=binding.line,
                    end_col=binding.col + len(binding.name),
                    severity=Severity.WARNING,
                    path=ctx.path,
                )
            )
        return diagnostics


class SBL204DirectPrivatePassBindingCallRule(SBL203DirectPrivateNopassBindingCallRule):
    """Detect direct calls to private passed-object type-bound procedure targets."""

    rule_id = "SBL204"
    summary = "Private passed-object type-bound procedure target is called directly."

    def _type_name_for_binding(
        self, ctx: RuleContext, binding: TypeBinding
    ) -> str | None:
        if ctx.analysis is None or binding.scope is None:
            return None
        type_scope = ctx.analysis.scopes[binding.scope]
        if type_scope.kind != "type":
            return None
        return type_scope.name

    def _object_has_binding_type(
        self,
        ctx: RuleContext,
        *,
        scope_idx: int | None,
        object_name: str,
        type_name: str,
    ) -> bool:
        if ctx.analysis is None or scope_idx is None:
            return False
        expected_class = f"class({type_name})"
        expected_type = f"type({type_name})"
        idx = scope_idx
        while idx is not None:
            for declaration in ctx.analysis.declarations:
                if declaration.scope != idx or declaration.name != object_name:
                    continue
                type_spec = "".join(declaration.type_spec.split())
                if type_spec.startswith(expected_class) or type_spec.startswith(
                    expected_type
                ):
                    return True
            idx = ctx.analysis.scopes[idx].parent
        return False

    def _logical_line_for_call(
        self, ctx: RuleContext, *, line: int, col: int, target: str
    ) -> tuple[list[Token], int] | None:
        for logical_line in ctx.logical_lines:
            for idx, tok in enumerate(logical_line):
                if tok.line != line or tok.col != col:
                    continue
                if tok.kind != TokenKind.NAME or tok.text.lower() != target:
                    continue
                return (logical_line, idx)
        return None

    def _matching_rparen(self, tokens: list[Token], lparen_idx: int) -> int | None:
        depth = 0
        for idx in range(lparen_idx, len(tokens)):
            tok = tokens[idx]
            if tok.kind == TokenKind.LPAREN:
                depth += 1
            elif tok.kind == TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return idx
        return None

    def _first_actual_argument(
        self, tokens: list[Token], lparen_idx: int, rparen_idx: int
    ) -> tuple[Token, int, int, int | None] | None:
        depth = 0
        comma_idx = None
        first_idx = None
        last_idx = None
        for idx in range(lparen_idx + 1, rparen_idx):
            tok = tokens[idx]
            if tok.kind in {
                TokenKind.COMMENT,
                TokenKind.CONTINUATION,
                TokenKind.NEWLINE,
            }:
                continue
            if first_idx is None:
                first_idx = idx
            last_idx = idx
            if tok.kind == TokenKind.LPAREN:
                depth += 1
            elif tok.kind == TokenKind.RPAREN:
                depth = max(0, depth - 1)
            elif tok.kind == TokenKind.COMMA and depth == 0:
                comma_idx = idx
                last_idx = idx - 1
                break
        if first_idx is None or last_idx is None:
            return None
        first_tok = tokens[first_idx]
        if first_tok.kind != TokenKind.NAME:
            return None
        return (first_tok, first_idx, last_idx, comma_idx)

    def _fix_for_pass_direct_call(
        self,
        ctx: RuleContext,
        *,
        line: int,
        col: int,
        target: str,
        binding_name: str,
        type_name: str,
        scope_idx: int | None,
    ) -> Fix | None:
        found = self._logical_line_for_call(ctx, line=line, col=col, target=target)
        if found is None:
            return None
        tokens, target_idx = found
        if (
            target_idx + 1 >= len(tokens)
            or tokens[target_idx + 1].kind != TokenKind.LPAREN
        ):
            return None
        lparen_idx = target_idx + 1
        rparen_idx = self._matching_rparen(tokens, lparen_idx)
        if rparen_idx is None:
            return None
        first_actual = self._first_actual_argument(tokens, lparen_idx, rparen_idx)
        if first_actual is None:
            return None
        object_tok, first_idx, last_idx, comma_idx = first_actual
        object_name = object_tok.text.lower()
        if not self._object_has_binding_type(
            ctx,
            scope_idx=scope_idx,
            object_name=object_name,
            type_name=type_name,
        ):
            return None

        target_edit = TextEdit(
            start=_line_col_to_offset(ctx, line, col),
            end=_line_col_to_offset(ctx, line, col + len(target)),
            replacement=f"{object_tok.text}%{binding_name}",
        )
        remove_start = _line_col_to_offset(
            ctx, tokens[first_idx].line, tokens[first_idx].col
        )
        if comma_idx is not None:
            remove_end = _line_col_to_offset(
                ctx,
                tokens[comma_idx].line,
                tokens[comma_idx].col + len(tokens[comma_idx].text),
            )
            remove_end = _expand_over_following_inline_space(ctx, remove_end)
        else:
            remove_end = _line_col_to_offset(
                ctx,
                tokens[last_idx].line,
                tokens[last_idx].col + len(tokens[last_idx].text),
            )
        return Fix(
            message=f"Call private binding through {object_tok.text}",
            edits=(target_edit, TextEdit(remove_start, remove_end, "")),
            safety=FixSafety.UNSAFE,
        )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        if ctx.analysis is None:
            return []

        local_calls_by_module: dict[int, list[tuple[str, int, int, int | None]]] = {}
        diagnostics: list[Diagnostic] = []
        for binding in ctx.analysis.type_bindings:
            if binding.visibility != "private" or binding.nopass:
                continue
            module_scope = self._ancestor_scope(ctx, binding.scope, "module")
            if module_scope is None:
                continue
            type_name = self._type_name_for_binding(ctx, binding)
            if type_name is None:
                continue
            module_idx, module_name = module_scope
            local_calls = local_calls_by_module.setdefault(
                module_idx,
                self._direct_call_refs_for_module(ctx, module_idx),
            )
            target = binding.target or binding.name
            found_local_call = False
            for call_name, line, col, scope_idx in local_calls:
                if call_name != target:
                    continue
                found_local_call = True
                fix = None
                if not binding.explicit_pass:
                    fix = self._fix_for_pass_direct_call(
                        ctx,
                        line=line,
                        col=col,
                        target=target,
                        binding_name=binding.name,
                        type_name=type_name,
                        scope_idx=scope_idx,
                    )
                diagnostics.append(
                    Diagnostic(
                        rule_id=self.rule_id,
                        message=(
                            f"Private type-bound procedure target '{target}' "
                            f"for binding '{binding.name}' is called directly."
                        ),
                        line=line,
                        col=col,
                        end_line=line,
                        end_col=col + len(target),
                        severity=Severity.WARNING,
                        path=ctx.path,
                        fix=fix,
                    )
                )
            if found_local_call:
                continue
            if target not in (ctx.external_direct_calls or {}).get(module_name, set()):
                continue
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=(
                        f"Private type-bound procedure target '{target}' "
                        f"for binding '{binding.name}' is called directly."
                    ),
                    line=binding.line,
                    col=binding.col,
                    end_line=binding.line,
                    end_col=binding.col + len(binding.name),
                    severity=Severity.WARNING,
                    path=ctx.path,
                )
            )
        return diagnostics
