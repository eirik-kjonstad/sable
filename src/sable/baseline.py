"""Baseline helpers for sable check mode."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .diagnostics import Diagnostic


def _diag_path(diag: Diagnostic) -> str:
    return str(diag.path) if diag.path else "<stdin>"


def diagnostic_key(diag: Diagnostic) -> tuple[str, str, int, int, int, int, str]:
    """Return a stable key for baseline comparisons."""
    message_hash = hashlib.sha1(diag.message.encode("utf-8")).hexdigest()
    return (
        _diag_path(diag),
        diag.rule_id,
        diag.line,
        diag.col,
        diag.end_line,
        diag.end_col,
        message_hash,
    )


def load_baseline(path: Path) -> set[tuple[str, str, int, int, int, int, str]]:
    """Load baseline keys from disk."""
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    out: set[tuple[str, str, int, int, int, int, str]] = set()
    for entry in entries:
        key = (
            str(entry["path"]),
            str(entry["rule_id"]),
            int(entry["line"]),
            int(entry["col"]),
            int(entry["end_line"]),
            int(entry["end_col"]),
            str(entry["message_hash"]),
        )
        out.add(key)
    return out


def write_baseline(path: Path, diagnostics: list[Diagnostic]) -> None:
    """Write current diagnostics as a baseline file."""
    entries = []
    for diag in diagnostics:
        key = diagnostic_key(diag)
        entries.append(
            {
                "path": key[0],
                "rule_id": key[1],
                "line": key[2],
                "col": key[3],
                "end_line": key[4],
                "end_col": key[5],
                "message_hash": key[6],
            }
        )
    entries.sort(
        key=lambda e: (
            e["path"],
            e["rule_id"],
            e["line"],
            e["col"],
            e["end_line"],
            e["end_col"],
            e["message_hash"],
        )
    )
    payload = {"version": 1, "entries": entries}
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
