"""Lightweight semantic analysis for Sable checks."""

from __future__ import annotations

from .file import (
    Declaration,
    FileAnalysis,
    Procedure,
    Reference,
    Scope,
    TypeBinding,
    UseImport,
    analyze_file,
)

__all__ = [
    "Declaration",
    "FileAnalysis",
    "Procedure",
    "Reference",
    "Scope",
    "TypeBinding",
    "UseImport",
    "analyze_file",
]
