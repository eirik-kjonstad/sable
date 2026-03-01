"""Token definitions for the Fortran lexer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    # Literals
    INTEGER = auto()
    REAL = auto()
    STRING = auto()
    LOGICAL = auto()  # .TRUE. / .FALSE.

    # Identifiers & keywords
    NAME = auto()
    KEYWORD = auto()

    # Operators
    OP_PLUS = auto()  # +
    OP_MINUS = auto()  # -
    OP_STAR = auto()  # *
    OP_SLASH = auto()  # /
    OP_POWER = auto()  # **
    OP_CONCAT = auto()  # //
    OP_EQ = auto()  # ==  or .EQ.
    OP_NEQ = auto()  # /=  or .NE.
    OP_LT = auto()  # <   or .LT.
    OP_LE = auto()  # <=  or .LE.
    OP_GT = auto()  # >   or .GT.
    OP_GE = auto()  # >=  or .GE.
    OP_AND = auto()  # .AND.
    OP_OR = auto()  # .OR.
    OP_NOT = auto()  # .NOT.
    OP_EQV = auto()  # .EQV.
    OP_NEQV = auto()  # .NEQV.
    OP_ASSIGN = auto()  # =
    OP_ARROW = auto()  # =>
    OP_PERCENT = auto()  # % (component access)

    # Delimiters
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COMMA = auto()  # ,
    SEMICOLON = auto()  # ;
    COLON = auto()  # :
    DOUBLE_COLON = auto()  # ::
    COLON_COLON = auto()  # :: (alias)

    # Special
    DIRECTIVE = auto()  # # preprocessor directive (entire line)
    COMMENT = auto()  # ! ...
    NEWLINE = auto()
    CONTINUATION = auto()  # &
    LABEL = auto()  # numeric statement label
    EOF = auto()

    # Unknown / error
    UNKNOWN = auto()


# Keywords are case-insensitive in Fortran; stored in lower-case for matching.
KEYWORDS: frozenset[str] = frozenset(
    {
        "program",
        "end",
        "module",
        "submodule",
        "use",
        "implicit",
        "none",
        "integer",
        "real",
        "complex",
        "logical",
        "character",
        "type",
        "class",
        "double",
        "precision",
        "if",
        "then",
        "else",
        "elseif",
        "end if",
        "endif",
        "do",
        "while",
        "end do",
        "enddo",
        "cycle",
        "exit",
        "select",
        "case",
        "end select",
        "endselect",
        "function",
        "subroutine",
        "end function",
        "end subroutine",
        "endfunction",
        "endsubroutine",
        "contains",
        "return",
        "result",
        "call",
        "intent",
        "in",
        "out",
        "inout",
        "allocatable",
        "pointer",
        "target",
        "save",
        "parameter",
        "public",
        "private",
        "protected",
        "interface",
        "end interface",
        "associate",
        "end associate",
        "block",
        "critical",
        "flush",
        "sync",
        "print",
        "write",
        "read",
        "open",
        "close",
        "format",
        "allocate",
        "deallocate",
        "nullify",
        "pure",
        "elemental",
        "recursive",
        "impure",
        "abstract",
        "extends",
        "deferred",
        "non_overridable",
        "bind",
        "sequence",
        "enumerator",
        "enum",
        "forall",
        "where",
        "elsewhere",
        "end where",
    }
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.kind.name}, {self.text!r}, {self.line}:{self.col})"
