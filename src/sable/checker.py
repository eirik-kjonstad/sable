"""Check engine for sable."""

from __future__ import annotations

import re
from pathlib import Path

from .analysis import analyze_file
from .diagnostics import Diagnostic, FixSafety, ProcedureBody, RuleContext, TextEdit
from .formatter import FormatConfig
from .lexer import iter_logical_lines, tokenize
from .rules import get_rules


def _normalise_rule_ids(rule_ids: set[str] | None) -> set[str] | None:
    if rule_ids is None:
        return None
    return {rule_id.strip().upper() for rule_id in rule_ids if rule_id.strip()}


_IGNORE_FILE_RE = re.compile(r"!\s*sable:\s*ignore-file\s+(.+)$", flags=re.IGNORECASE)
_IGNORE_LINE_RE = re.compile(r"!\s*sable:\s*ignore\s+(.+)$", flags=re.IGNORECASE)


def _parse_rule_codes(raw: str) -> set[str]:
    parts = re.split(r"[,\s]+", raw.strip())
    return {part.upper() for part in parts if part}


def _parse_suppressions(source: str) -> tuple[set[str], dict[int, set[str]]]:
    file_ignores: set[str] = set()
    line_ignores: dict[int, set[str]] = {}
    for idx, line in enumerate(source.splitlines(), start=1):
        file_match = _IGNORE_FILE_RE.search(line)
        if file_match:
            file_ignores.update(_parse_rule_codes(file_match.group(1)))
        line_match = _IGNORE_LINE_RE.search(line)
        if line_match:
            line_ignores[idx] = _parse_rule_codes(line_match.group(1))
    return file_ignores, line_ignores


def _is_ignored(
    diag: Diagnostic, file_ignores: set[str], line_ignores: dict[int, set[str]]
) -> bool:
    code = diag.rule_id.upper()
    if "ALL" in file_ignores or code in file_ignores:
        return True
    if diag.line in line_ignores:
        rules = line_ignores[diag.line]
        if "ALL" in rules or code in rules:
            return True
    return False


def check_source(
    source: str,
    cfg: FormatConfig,
    path: Path | None = None,
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    rule_set: str = "all",
    external_references: dict[str, set[str]] | None = None,
    external_selectors: dict[str, set[str]] | None = None,
    external_direct_calls: dict[str, set[str]] | None = None,
    external_procedure_bodies: (
        dict[str, dict[str, tuple[ProcedureBody, ...]]] | None
    ) = None,
) -> list[Diagnostic]:
    """Run enabled checks on *source* and return diagnostics."""
    tokens = tokenize(source)
    logical_lines = list(iter_logical_lines(tokens))
    analysis = analyze_file(source, tokens, logical_lines, path)
    line_starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            line_starts.append(i + 1)
    ctx = RuleContext(
        source=source,
        tokens=tokens,
        logical_lines=logical_lines,
        line_starts=tuple(line_starts),
        cfg=cfg,
        path=path,
        analysis=analysis,
        external_references=external_references,
        external_selectors=external_selectors,
        external_direct_calls=external_direct_calls,
        external_procedure_bodies=external_procedure_bodies,
    )

    selected = _normalise_rule_ids(select)
    ignored = _normalise_rule_ids(ignore)
    file_ignores, line_ignores = _parse_suppressions(source)
    diagnostics: list[Diagnostic] = []
    for rule in get_rules(select=selected, ignore=ignored, rule_set=rule_set):
        diagnostics.extend(rule.check(ctx))

    diagnostics = [
        diag
        for diag in diagnostics
        if not _is_ignored(diag, file_ignores=file_ignores, line_ignores=line_ignores)
    ]
    diagnostics.sort(key=lambda d: (str(d.path or ""), d.line, d.col, d.rule_id))
    return diagnostics


def collect_external_references(
    sources: list[tuple[str, Path | None]],
) -> dict[str, set[str]]:
    """Collect project-level references that module-scope checks must consider.

    Submodules can use names imported by their parent module through host
    association. File-local unused-import checks therefore need a project-level
    hint before judging parent-module imports.

    A module can also re-export public names that it imported from another
    module. If another source imports that name through the forwarding module,
    the forwarding module's import is semantically used even when the name is
    never referenced in its own executable statements.
    """
    references_by_host: dict[str, set[str]] = {}

    for source, path in sources:
        tokens = tokenize(source)
        logical_lines = list(iter_logical_lines(tokens))
        analysis = analyze_file(source, tokens, logical_lines, path)

        for imported in analysis.use_imports:
            references_by_host.setdefault(imported.module, set()).add(imported.name)

        for scope in analysis.scopes:
            if scope.kind != "submodule" or scope.host_name is None:
                continue
            names = references_by_host.setdefault(scope.host_name, set())
            for ref in analysis.references:
                idx = ref.scope
                while idx is not None:
                    ref_scope = analysis.scopes[idx]
                    if ref_scope == scope:
                        names.add(ref.name)
                        break
                    idx = ref_scope.parent

    return references_by_host


def collect_external_selectors(
    sources: list[tuple[str, Path | None]],
) -> dict[str, set[str]]:
    """Collect type-bound selector names used by submodules of each host."""
    selectors_by_host: dict[str, set[str]] = {}

    for source, path in sources:
        tokens = tokenize(source)
        logical_lines = list(iter_logical_lines(tokens))
        analysis = analyze_file(source, tokens, logical_lines, path)

        for scope in analysis.scopes:
            if scope.kind != "submodule" or scope.host_name is None:
                continue
            names = selectors_by_host.setdefault(scope.host_name, set())
            for ref in analysis.references:
                if ref.kind != "selector":
                    continue
                idx = ref.scope
                while idx is not None:
                    ref_scope = analysis.scopes[idx]
                    if ref_scope == scope:
                        names.add(ref.name)
                        break
                    idx = ref_scope.parent

    return selectors_by_host


def collect_external_direct_calls(
    sources: list[tuple[str, Path | None]],
) -> dict[str, set[str]]:
    """Collect plain procedure calls made by submodules of each host."""
    calls_by_host: dict[str, set[str]] = {}

    for source, path in sources:
        tokens = tokenize(source)
        logical_lines = list(iter_logical_lines(tokens))
        analysis = analyze_file(source, tokens, logical_lines, path)

        for scope in analysis.scopes:
            if scope.kind != "submodule" or scope.host_name is None:
                continue
            names = calls_by_host.setdefault(scope.host_name, set())
            for ref in analysis.references:
                if ref.kind not in {"call", "function_call"}:
                    continue
                idx = ref.scope
                while idx is not None:
                    ref_scope = analysis.scopes[idx]
                    if ref_scope == scope:
                        names.add(ref.name)
                        break
                    idx = ref_scope.parent

    return calls_by_host


def _is_descendant_scope(analysis, scope_idx: int | None, ancestor_idx: int) -> bool:
    idx = scope_idx
    while idx is not None:
        if idx == ancestor_idx:
            return True
        idx = analysis.scopes[idx].parent
    return False


def _ancestor_scope(analysis, scope_idx: int | None, kind: str):
    idx = scope_idx
    while idx is not None:
        scope = analysis.scopes[idx]
        if scope.kind == kind and scope.name is not None:
            return (idx, scope)
        idx = scope.parent
    return None


def _is_inside_scope(analysis, scope_idx: int | None, kind: str) -> bool:
    return _ancestor_scope(analysis, scope_idx, kind) is not None


def _procedure_host_module(analysis, scope_idx: int | None) -> str | None:
    submodule_scope = _ancestor_scope(analysis, scope_idx, "submodule")
    if submodule_scope is not None:
        _idx, scope = submodule_scope
        return scope.host_name

    module_scope = _ancestor_scope(analysis, scope_idx, "module")
    if module_scope is not None:
        _idx, scope = module_scope
        return scope.name
    return None


def collect_external_procedure_bodies(
    sources: list[tuple[str, Path | None]],
) -> dict[str, dict[str, tuple[ProcedureBody, ...]]]:
    """Collect unique-addressable procedure bodies by module family."""
    bodies: dict[str, dict[str, list[ProcedureBody]]] = {}

    for source, path in sources:
        tokens = tokenize(source)
        logical_lines = list(iter_logical_lines(tokens))
        analysis = analyze_file(source, tokens, logical_lines, path)
        line_starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                line_starts.append(i + 1)

        for procedure in analysis.procedures:
            if procedure.end_line is None:
                continue
            if _is_inside_scope(analysis, procedure.scope, "interface"):
                continue
            module_name = _procedure_host_module(analysis, procedure.scope)
            if module_name is None:
                continue
            body = ProcedureBody(
                name=procedure.name,
                path=path,
                line=procedure.line,
                col=procedure.col,
                end_line=procedure.end_line,
                end_col=procedure.end_col or 1,
                start=line_starts[procedure.line - 1],
                end=(
                    line_starts[procedure.end_line]
                    if procedure.end_line < len(line_starts)
                    else len(source)
                ),
            )
            bodies.setdefault(module_name, {}).setdefault(procedure.name, []).append(
                body
            )

    return {
        module_name: {
            procedure_name: tuple(procedure_bodies)
            for procedure_name, procedure_bodies in procedures.items()
        }
        for module_name, procedures in bodies.items()
    }


def _apply_text_edits(source: str, edits: list[TextEdit]) -> tuple[str, int]:
    """Apply non-overlapping edits to one source string."""

    if not edits:
        return source, 0

    unique: dict[tuple[int, int, str], TextEdit] = {}
    for edit in edits:
        unique[(edit.start, edit.end, edit.replacement)] = edit
    ordered = sorted(unique.values(), key=lambda e: (e.start, e.end))

    filtered: list[TextEdit] = []
    last_end = -1
    for edit in ordered:
        if edit.start < 0 or edit.end < edit.start or edit.end > len(source):
            continue
        if filtered and edit.start < last_end:
            continue
        filtered.append(edit)
        last_end = edit.end

    if not filtered:
        return source, 0

    out = source
    for edit in reversed(filtered):
        out = out[: edit.start] + edit.replacement + out[edit.end :]
    return out, len(filtered)


def apply_fixes(
    source: str,
    diagnostics: list[Diagnostic],
    *,
    include_unsafe: bool = False,
) -> tuple[str, int]:
    """Apply same-file fixes from diagnostics and return updated source."""
    edits: list[TextEdit] = []
    for diag in diagnostics:
        if diag.fix is None:
            continue
        if diag.fix.safety == FixSafety.UNSAFE and not include_unsafe:
            continue
        edits.extend(edit for edit in diag.fix.edits if edit.path is None)

    return _apply_text_edits(source, edits)


def apply_fixes_to_sources(
    sources: list[tuple[str, Path | None]],
    diagnostics: list[Diagnostic],
    *,
    include_unsafe: bool = False,
) -> tuple[list[tuple[str, Path | None]], set[Path | None], int]:
    """Apply local and cross-file fixes to a source set."""
    source_by_path = {path: source for source, path in sources}
    edits_by_path: dict[Path | None, list[TextEdit]] = {}
    for diag in diagnostics:
        if diag.fix is None:
            continue
        if diag.fix.safety == FixSafety.UNSAFE and not include_unsafe:
            continue
        for edit in diag.fix.edits:
            target = edit.path if edit.path is not None else diag.path
            if target not in source_by_path:
                continue
            edits_by_path.setdefault(target, []).append(edit)

    changed: set[Path | None] = set()
    n_applied = 0
    updated_sources: list[tuple[str, Path | None]] = []
    for source, path in sources:
        fixed, applied = _apply_text_edits(source, edits_by_path.get(path, []))
        if applied and fixed != source:
            changed.add(path)
            n_applied += applied
        updated_sources.append((fixed, path))
    return updated_sources, changed, n_applied
