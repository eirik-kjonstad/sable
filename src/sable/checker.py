"""Check engine for sable."""

from __future__ import annotations

import re
from pathlib import Path

from .diagnostics import Diagnostic, FixSafety, RuleContext, TextEdit
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
) -> list[Diagnostic]:
    """Run enabled checks on *source* and return diagnostics."""
    tokens = tokenize(source)
    logical_lines = list(iter_logical_lines(tokens))
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
    )

    selected = _normalise_rule_ids(select)
    ignored = _normalise_rule_ids(ignore)
    file_ignores, line_ignores = _parse_suppressions(source)
    diagnostics: list[Diagnostic] = []
    for rule in get_rules(select=selected, ignore=ignored):
        diagnostics.extend(rule.check(ctx))

    diagnostics = [
        diag
        for diag in diagnostics
        if not _is_ignored(diag, file_ignores=file_ignores, line_ignores=line_ignores)
    ]
    diagnostics.sort(key=lambda d: (str(d.path or ""), d.line, d.col, d.rule_id))
    return diagnostics


def apply_fixes(
    source: str,
    diagnostics: list[Diagnostic],
    *,
    include_unsafe: bool = False,
) -> tuple[str, int]:
    """Apply non-overlapping fixes from diagnostics and return updated source."""
    edits: list[TextEdit] = []
    for diag in diagnostics:
        if diag.fix is None:
            continue
        if diag.fix.safety == FixSafety.UNSAFE and not include_unsafe:
            continue
        edits.extend(diag.fix.edits)

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
