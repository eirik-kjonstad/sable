"""Diagnostic model for sable check mode."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .tokens import Token

if TYPE_CHECKING:
    from .formatter import FormatConfig


class Severity(str, Enum):
    """Severity level for diagnostics."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FixSafety(str, Enum):
    """Safety level for a suggested fix."""

    SAFE = "safe"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class TextEdit:
    """A source edit represented as byte offsets in the original text."""

    start: int
    end: int
    replacement: str

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start, "end": self.end, "replacement": self.replacement}


@dataclass(frozen=True, slots=True)
class Fix:
    """A fix proposal for a diagnostic."""

    message: str
    edits: tuple[TextEdit, ...]
    safety: FixSafety = FixSafety.SAFE

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            "safety": self.safety.value,
            "edits": [edit.to_dict() for edit in self.edits],
        }


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single diagnostic finding reported by a rule."""

    rule_id: str
    message: str
    line: int
    col: int
    end_line: int
    end_col: int
    severity: Severity = Severity.WARNING
    path: Path | None = None
    fix: Fix | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "severity": self.severity.value,
            "path": str(self.path) if self.path else None,
            "fix": self.fix.to_dict() if self.fix else None,
        }


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Context passed to rule evaluators."""

    source: str
    tokens: list[Token]
    logical_lines: list[list[Token]]
    line_starts: tuple[int, ...]
    cfg: FormatConfig
    path: Path | None = None


class Rule(Protocol):
    """Contract for check rules."""

    rule_id: str
    summary: str

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        """Evaluate *ctx* and return diagnostics for this rule."""
