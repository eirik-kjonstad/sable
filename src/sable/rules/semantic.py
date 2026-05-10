"""Semantic lint rules backed by lightweight file analysis."""

from __future__ import annotations

from ..analysis import UseImport
from ..diagnostics import Diagnostic, Fix, FixSafety, RuleContext, Severity, TextEdit


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
