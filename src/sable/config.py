"""Configuration for sable formatting."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_CONFIG", "FormatConfig"]


@dataclass
class FormatConfig:
    """All knobs exposed to the user (Black-style: mostly zero knobs)."""

    line_length: int = 100
    """Maximum line length before continuation is inserted."""

    indent_width: int = 3
    """Spaces per indentation level."""

    keyword_case: str = "lower"
    """How to case Fortran keywords: 'lower' | 'upper'."""

    end_keyword_form: str = "spaced"
    """How to emit compound END keywords.

    'spaced'  ->  end if / end do / end subroutine / ...
    'compact' ->  endif / enddo / endsubroutine / ...
    """

    normalize_operators: bool = True
    """Replace old-style relational operators (.EQ., .GT., ...) with modern ones."""

    trailing_newline: bool = True
    """Ensure the file ends with exactly one newline."""

    double_colon_declarations: bool = True
    """Always emit '::' in type declarations."""

    normalize_keyword_case: bool = True
    """Normalize keyword casing according to ``keyword_case`` when enabled."""

    normalize_end_keywords: bool = True
    """Normalize compact/spaced END keywords according to ``end_keyword_form``."""

    canonicalize_declarations: bool = True
    """Canonicalize declaration structure and attribute ordering."""


DEFAULT_CONFIG = FormatConfig()
