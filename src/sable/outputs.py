"""Diagnostic output renderers for sable check mode."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic


def render_diagnostics_text(diagnostics: list[Diagnostic]) -> str:
    """Render diagnostics in a compact text format."""
    if not diagnostics:
        return ""

    lines: list[str] = []
    for diag in diagnostics:
        label = str(diag.path) if diag.path else "<stdin>"
        lines.append(f"{label}:{diag.line}:{diag.col}: {diag.rule_id} {diag.message}")
    return "\n".join(lines) + "\n"


def render_diagnostics_json(diagnostics: list[Diagnostic]) -> str:
    """Render diagnostics as stable JSON."""
    payload = {"diagnostics": [diag.to_dict() for diag in diagnostics]}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _offset_to_line_col(starts: list[int], offset: int) -> tuple[int, int]:
    line = 1
    for i, start in enumerate(starts):
        if i + 1 >= len(starts) or starts[i + 1] > offset:
            line = i + 1
            col = (offset - start) + 1
            return line, col
    last = len(starts) - 1
    return last + 1, (offset - starts[last]) + 1


def render_diagnostics_sarif(
    diagnostics: list[Diagnostic],
    source_lookup: dict[str, str] | None = None,
    rule_summaries: dict[str, str] | None = None,
) -> str:
    """Render diagnostics in SARIF 2.1.0 format."""
    rule_ids = sorted({diag.rule_id for diag in diagnostics})
    rules = [
        {
            "id": rule_id,
            "name": (rule_summaries or {}).get(rule_id, rule_id),
            "shortDescription": {"text": (rule_summaries or {}).get(rule_id, rule_id)},
        }
        for rule_id in rule_ids
    ]

    def _artifact_uri(path: Path | None) -> str:
        return str(path) if path else "<stdin>"

    artifacts: list[dict[str, object]] = []
    artifact_index_by_uri: dict[str, int] = {}

    def _artifact_location(uri: str) -> dict[str, object]:
        if uri not in artifact_index_by_uri:
            artifact_index_by_uri[uri] = len(artifacts)
            artifacts.append({"location": {"uri": uri}})
        return {"uri": uri, "index": artifact_index_by_uri[uri]}

    results = []
    for diag in diagnostics:
        uri = _artifact_uri(diag.path)
        result: dict[str, object] = {
            "ruleId": diag.rule_id,
            "message": {"text": diag.message},
            "level": "warning",
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": _artifact_location(uri),
                        "region": {
                            "startLine": diag.line,
                            "startColumn": diag.col,
                            "endLine": diag.end_line,
                            "endColumn": diag.end_col,
                        },
                    }
                }
            ],
        }
        if diag.fix is not None:
            replacements: list[dict[str, Any]] = []
            label = uri
            source = source_lookup.get(label, "") if source_lookup else ""
            starts = _line_starts(source) if source else []

            for edit in diag.fix.edits:
                if source and 0 <= edit.start <= edit.end <= len(source):
                    s_line, s_col = _offset_to_line_col(starts, edit.start)
                    e_line, e_col = _offset_to_line_col(starts, edit.end)
                else:
                    s_line, s_col = diag.line, diag.col
                    e_line, e_col = diag.end_line, diag.end_col
                replacements.append(
                    {
                        "deletedRegion": {
                            "startLine": s_line,
                            "startColumn": s_col,
                            "endLine": e_line,
                            "endColumn": e_col,
                        },
                        "insertedContent": {"text": edit.replacement},
                    }
                )
            result["fixes"] = [
                {
                    "description": {"text": diag.fix.message},
                    "artifactChanges": [
                        {
                            "artifactLocation": _artifact_location(label),
                            "replacements": replacements,
                        }
                    ],
                }
            ]
        results.append(result)

    payload = {
        "version": "2.1.0",
        "$schema": ("https://json.schemastore.org/sarif-2.1.0-rtm.5.json"),
        "runs": [
            {
                "tool": {"driver": {"name": "sable", "rules": rules}},
                "artifacts": artifacts,
                "results": results,
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_diagnostics_gitlab_codequality(diagnostics: list[Diagnostic]) -> str:
    """Render diagnostics in GitLab Code Quality (CodeClimate-like) format."""

    def _path(path: Path | None) -> str:
        return str(path) if path else "<stdin>"

    payload = []
    for diag in diagnostics:
        seed = (
            f"{_path(diag.path)}|{diag.rule_id}|{diag.line}|{diag.col}|"
            f"{diag.end_line}|{diag.end_col}|{diag.message}"
        )
        fingerprint = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        description = f"{diag.rule_id}: {diag.message}"
        if diag.fix is not None:
            description += f" (fix: {diag.fix.message})"

        payload.append(
            {
                "description": description,
                "check_name": diag.rule_id,
                "fingerprint": fingerprint,
                "severity": "major",
                "location": {
                    "path": _path(diag.path),
                    "lines": {"begin": diag.line, "end": diag.end_line},
                },
            }
        )

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
