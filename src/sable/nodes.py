"""CST (Concrete Syntax Tree) node definitions for sable.

Sable uses a *concrete* rather than abstract syntax tree so that formatting
can reconstruct the exact source, including comments. Each node holds the
tokens it owns plus child nodes.

Design goals
------------
* Round-trip safe: the original token stream can always be recovered.
* Formatter-friendly: nodes carry enough structure for the formatter to apply
  spacing, indentation, and line-length rules without re-parsing.

Node hierarchy (simplified)
----------------------------
    SourceFile
      ProgramUnit*
        | ProgramBlock
        | ModuleBlock
        | SubroutineSubprogram
        | FunctionSubprogram
        | …
      Statement*
        | UseStatement
        | ImplicitStatement
        | TypeDeclaration
        | AssignmentStatement
        | CallStatement
        | IfConstruct
        | DoConstruct
        | SelectConstruct
        | …
      Expression*
        | BinaryOp
        | UnaryOp
        | FunctionCall / ArrayElement
        | Literal
        | NameRef
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tokens import Token


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """Base class for all CST nodes."""

    #: Tokens that belong directly to this node (not to children).
    tokens: list[Token] = field(default_factory=list, repr=False)

    def token_text(self) -> str:
        return " ".join(t.text for t in self.tokens if t.text.strip())


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


@dataclass
class Literal(Node):
    value: str = ""


@dataclass
class NameRef(Node):
    name: str = ""


@dataclass
class UnaryOp(Node):
    operator: str = ""
    operand: "Expr | None" = None


@dataclass
class BinaryOp(Node):
    left: "Expr | None" = None
    operator: str = ""
    right: "Expr | None" = None


@dataclass
class FunctionCall(Node):
    name: str = ""
    args: list["Expr"] = field(default_factory=list)


@dataclass
class ArraySection(Node):
    name: str = ""
    subscripts: list["Expr | None"] = field(default_factory=list)


@dataclass
class PartRef(Node):
    """Component access: a%b%c."""

    parts: list[str] = field(default_factory=list)


Expr = (
    Literal | NameRef | UnaryOp | BinaryOp | FunctionCall | ArraySection | PartRef | Any
)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class Statement(Node):
    """Generic statement (catch-all for unrecognised constructs)."""

    label: str | None = None
    raw_tokens: list[Token] = field(default_factory=list)


@dataclass
class UseStatement(Node):
    label: str | None = None
    module_name: str = ""
    only: list[str] = field(default_factory=list)
    rename: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ImplicitStatement(Node):
    label: str | None = None
    is_none: bool = True


@dataclass
class TypeDeclaration(Node):
    """e.g. integer, intent(in) :: x, y"""

    label: str | None = None
    type_spec: str = ""
    attributes: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@dataclass
class AssignmentStatement(Node):
    label: str | None = None
    lhs: Expr | None = None
    rhs: Expr | None = None


@dataclass
class CallStatement(Node):
    label: str | None = None
    procedure: str = ""
    args: list[Expr] = field(default_factory=list)


@dataclass
class PrintStatement(Node):
    label: str | None = None
    format_spec: str = ""
    items: list[Expr] = field(default_factory=list)


@dataclass
class ReturnStatement(Node):
    label: str | None = None


@dataclass
class CycleStatement(Node):
    label: str | None = None
    construct_name: str | None = None


@dataclass
class ExitStatement(Node):
    label: str | None = None
    construct_name: str | None = None


# ---------------------------------------------------------------------------
# Constructs (multi-statement)
# ---------------------------------------------------------------------------


@dataclass
class IfConstruct(Node):
    label: str | None = None
    condition: Expr | None = None
    then_block: list[Any] = field(default_factory=list)
    else_if_clauses: list[tuple[Expr, list[Any]]] = field(default_factory=list)
    else_block: list[Any] | None = None


@dataclass
class DoConstruct(Node):
    label: str | None = None
    construct_name: str | None = None
    variable: str | None = None
    start: Expr | None = None
    stop: Expr | None = None
    step: Expr | None = None
    body: list[Any] = field(default_factory=list)


@dataclass
class SelectCaseConstruct(Node):
    label: str | None = None
    expr: Expr | None = None
    cases: list[tuple[list[Expr | None], list[Any]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Program units
# ---------------------------------------------------------------------------


@dataclass
class ContainsStatement(Node):
    pass


@dataclass
class SubroutineSubprogram(Node):
    name: str = ""
    dummy_args: list[str] = field(default_factory=list)
    prefix: list[str] = field(default_factory=list)
    specification: list[Any] = field(default_factory=list)
    execution: list[Any] = field(default_factory=list)
    internal: list[Any] = field(default_factory=list)


@dataclass
class FunctionSubprogram(Node):
    name: str = ""
    dummy_args: list[str] = field(default_factory=list)
    prefix: list[str] = field(default_factory=list)
    result: str | None = None
    specification: list[Any] = field(default_factory=list)
    execution: list[Any] = field(default_factory=list)
    internal: list[Any] = field(default_factory=list)


@dataclass
class ModuleBlock(Node):
    name: str = ""
    specification: list[Any] = field(default_factory=list)
    internal: list[Any] = field(default_factory=list)


@dataclass
class ProgramBlock(Node):
    name: str | None = None
    specification: list[Any] = field(default_factory=list)
    execution: list[Any] = field(default_factory=list)
    internal: list[Any] = field(default_factory=list)


@dataclass
class SourceFile(Node):
    units: list[Any] = field(default_factory=list)
    comments: list[Token] = field(default_factory=list)


@dataclass
class Comment(Node):
    text: str = ""
