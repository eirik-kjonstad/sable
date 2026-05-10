"""Tests for Sable's lightweight semantic analysis."""

from __future__ import annotations

from sable.analysis import analyze_file
from sable.lexer import iter_logical_lines, tokenize


def _analyze(source: str):
    tokens = tokenize(source)
    logical_lines = list(iter_logical_lines(tokens))
    return analyze_file(source, tokens, logical_lines)


def test_analysis_collects_scopes_procedures_and_declarations():
    analysis = _analyze(
        """
module solver_mod
   implicit none
   private
contains
   subroutine step(x)
      real, intent(inout) :: x
      call helper(x)
   end subroutine step

   subroutine helper(x)
      real, intent(inout) :: x
   end subroutine helper
end module solver_mod
"""
    )

    assert [(scope.kind, scope.name) for scope in analysis.scopes] == [
        ("module", "solver_mod"),
        ("subroutine", "step"),
        ("subroutine", "helper"),
    ]
    assert [
        (proc.kind, proc.name, proc.visibility) for proc in analysis.procedures
    ] == [
        ("subroutine", "step", "private"),
        ("subroutine", "helper", "private"),
    ]
    assert [decl.name for decl in analysis.declarations] == ["x", "x"]
    assert ("call", "helper") in [(ref.kind, ref.name) for ref in analysis.references]


def test_analysis_collects_use_only_imports_and_renames():
    analysis = _analyze(
        """
module client
   use constants, only: dp, local_name => exported_name
   implicit none
end module client
"""
    )

    assert [
        (item.module, item.name, item.imported_name) for item in analysis.use_imports
    ] == [
        ("constants", "dp", None),
        ("constants", "local_name", "exported_name"),
    ]


def test_analysis_collects_type_bound_procedure_bindings_and_references():
    analysis = _analyze(
        """
module solver_types
   implicit none
   type :: solver_t
   contains
      procedure, private :: old_step => solver_old_step
      procedure :: step
   end type solver_t
contains
   subroutine run(solver)
      type(solver_t), intent(inout) :: solver
      call solver%step()
   end subroutine run

   subroutine solver_old_step(self)
      type(solver_t), intent(inout) :: self
   end subroutine solver_old_step
end module solver_types
"""
    )

    assert [
        (binding.name, binding.target, binding.visibility)
        for binding in analysis.type_bindings
    ] == [
        ("old_step", "solver_old_step", "private"),
        ("step", None, "public"),
    ]
    assert [
        (ref.kind, ref.qualifier, ref.name)
        for ref in analysis.references
        if ref.kind == "type_bound_call"
    ] == [
        ("type_bound_call", "solver", "step"),
    ]


def test_analysis_collects_declaration_references_without_declared_entities():
    analysis = _analyze(
        """
module arrays
   use kinds, only: dp
   use sizes, only: n
   implicit none
   real(dp) :: values(n)
end module arrays
"""
    )

    referenced_names = {ref.name for ref in analysis.references}
    assert {"dp", "n"}.issubset(referenced_names)
    assert "values" not in referenced_names
