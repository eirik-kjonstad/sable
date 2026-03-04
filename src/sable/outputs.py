"""Diagnostic output renderers for sable check mode."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def render_diagnostics_sarif(diagnostics: list[Diagnostic]) -> str:
    """Render diagnostics in SARIF 2.1.0 format."""
    rule_ids = sorted({diag.rule_id for diag in diagnostics})
    rules = [
        {
            "id": rule_id,
            "shortDescription": {"text": rule_id},
            "name": rule_id,
        }
        for rule_id in rule_ids
    ]

    def _artifact_uri(path: Path | None) -> str:
        return str(path) if path else "<stdin>"

    results = []
    for diag in diagnostics:
        result: dict[str, object] = {
            "ruleId": diag.rule_id,
            "message": {"text": diag.message},
            "level": "warning",
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": _artifact_uri(diag.path)},
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
            result["fixes"] = [
                {
                    "description": {"text": diag.fix.message},
                    "artifactChanges": [
                        {
                            "artifactLocation": {"uri": _artifact_uri(diag.path)},
                            "replacements": [
                                {
                                    "deletedRegion": {
                                        "startLine": diag.line,
                                        "startColumn": diag.col,
                                        "endLine": diag.end_line,
                                        "endColumn": diag.end_col,
                                    },
                                    "insertedContent": {
                                        "text": "".join(
                                            edit.replacement for edit in diag.fix.edits
                                        )
                                    },
                                }
                            ],
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
        payload.append(
            {
                "description": f"{diag.rule_id}: {diag.message}",
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
