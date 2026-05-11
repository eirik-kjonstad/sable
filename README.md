<p align="center">
  <img src="https://raw.githubusercontent.com/eirik-kjonstad/sable/v0.1.3/assets/sable-logo.svg" alt="Sable logo" width="420">
</p>

An uncompromising Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable enforces one consistent style for modern free-form Fortran, so you can
focus on code instead of formatting. It also supports code checks beyond formatting
to identify code issues.

## Installation

```bash
pip install sable-fortran
```

## Quick Start

```bash
# Format in place (default command)
sable src/

# Equivalent explicit form
sable format src/

# Check formatting only (no writes)
sable format --check src/

# Preview formatting diff
sable format --diff src/

# Safer migration pass (layout-focused)
sable format --safe src/
```

Recommended CI formatting gate:

```bash
sable format --check src/
```

## Formatting 

`format` rewrites source into Sable's canonical style. This includes:

- Relational operator normalization (`.EQ.` -> `==`, etc.)
- END keyword normalization (`endif` -> `end if`, configurable)
- Declaration normalization (`integer x` -> `integer :: x`)
- Deterministic spacing, indentation, wrapping, and trailing newline handling

Example:

```fortran
! Before
IF(A .EQ. B)THEN
CALL compute(argument_alpha,argument_beta,argument_gamma)
ENDIF

! After
if (A == B) then

   call compute(argument_alpha, &
                argument_beta, &
                argument_gamma)

end if
```

## Checking

`check` reports rule diagnostics and can apply rule fixes.

```bash
# Run all rules (style + lint)
sable check src/

# Focus on policy/lint only
sable check --rule-set lint src/

# Formatter-adjacent style rules only
sable check --rule-set style src/

# Apply safe fixes, then re-check
sable check --fix src/

# Allow unsafe fixes too
sable check --fix --unsafe-fixes src/
```

Rule-set notes:

- `--rule-set all` (default): style + lint
- `--select` takes precedence over `--rule-set`
- `--fix` applies safe fixes
- `--unsafe-fixes` enables unsafe fixes (only with `--fix`)

Current lint rules:

- `SBL101`: Program/module is missing `implicit none`
- `SBL102`: Procedure is missing `implicit none`
- `SBL103`: Dummy argument is missing `intent(in|out|inout)`
- `SBL201`: Name imported with `use ..., only:` is unused
- `SBL202`: Private type-bound procedure binding is never selected
- `SBL203`: Private `nopass` type-bound procedure target is called directly
- `SBL204`: Private passed-object type-bound procedure target is called directly

### Rule reference

Sable's lint rules use lightweight source analysis, not compiler-generated
module files or whole-program linking information. When a command is run on a
directory, Sable does collect project-level facts from all checked files so that
rules can account for common Fortran patterns such as host association from
submodules. For best results, run semantic rules on the whole source tree rather
than on one file at a time.

Fixes marked unsafe may change build behavior if the analyzed source set is
incomplete, generated files are stale, or a project uses patterns outside
Sable's current analysis model. Treat `--fix --unsafe-fixes` like an automated
refactor: review the diff and compile afterward.

#### `SBL101`: Missing `implicit none` in a program or module

Reports a `program` or `module` unit whose specification part does not contain
`implicit none`.

With `--fix --unsafe-fixes`, Sable inserts `implicit none` immediately after the
opening program or module statement, using the configured keyword case and
indentation.

#### `SBL102`: Missing `implicit none` in a procedure

Reports a `subroutine` or `function` whose body does not contain `implicit none`.

With `--fix --unsafe-fixes`, Sable inserts `implicit none` immediately after the
opening procedure statement, using the configured keyword case and indentation.

#### `SBL103`: Missing dummy-argument `intent`

Reports dummy arguments of a `subroutine` or `function` when their declaration
does not include an `intent(...)` attribute.

This rule is diagnostic-only. Sable does not infer whether the correct intent is
`in`, `out`, or `inout`.

#### `SBL201`: Unused `use ..., only:` import

Reports each local name imported by a `use module, only: ...` statement when that
name is not referenced in the importing scope.

Sable treats an import as used when the imported local name appears in:

- the same scope as the `use` statement;
- a descendant scope, such as an internal procedure;
- a submodule of the host module, through host association;
- another file's `use ..., only:` import from the importing module, which models
  public re-export through a forwarding module.

Renamed imports are checked by their local name:

```fortran
use constants, only: wp => real64
```

Here Sable looks for uses of `wp`, not `real64`.

With `--fix --unsafe-fixes`, Sable removes the unused item from the `only:` list.
If every item in the statement is unused, it removes the whole `use` statement.

The fix is unsafe because an import can affect overload resolution, macro-heavy
code, generated source, or files not included in the Sable run.

#### `SBL202`: Unused private type-bound procedure binding

Reports a private type-bound procedure binding when the binding name is never
used as a selector in the module or in any submodule of that module.

For example, this binding is used because `reset` is selected through an object:

```fortran
type :: worker
contains
   procedure, private :: reset => reset_worker
end type worker

call this%reset()
```

Sable checks the binding name, not merely the implementation procedure name.
This distinction matters for renamed bindings:

```fortran
procedure, private :: reset => reset_worker
```

The selected name is `reset`; the implementation body is `reset_worker`.

Sable does not report private bindings that are targets of a type-bound generic:

```fortran
procedure, private :: reset_worker
generic :: reset => reset_worker
```

With `--fix --unsafe-fixes`, Sable removes the unused binding declaration item.
If every binding in the declaration is unused, it removes the whole declaration.
When Sable can prove a unique implementation body in the same module family, it
also removes that procedure body. A module family means the parent module plus
its submodules, so this can remove a dead implementation from a different source
file than the type-bound declaration.

Implementation-body removal is deliberately conservative. Sable will not remove
the body when:

- the target procedure is directly called by name in the module or a submodule;
- the target procedure participates in a type-bound generic;
- no unique non-interface procedure body can be found;
- the body only appears through an interface.

The fix is unsafe because it deletes source code. Compile after applying it,
especially in projects with generated files or preprocessing.

#### `SBL203`: Direct call to a private `nopass` type-bound target

Reports direct calls to the implementation target of a private `nopass`
type-bound binding.

For example:

```fortran
type :: worker
contains
   procedure, private, nopass :: prepare
end type worker

call prepare()
```

Even though `prepare` is `nopass`, Sable prefers calls through the binding:

```fortran
call this%prepare()
```

This keeps the private binding visibly used, which lets `SBL202` distinguish
live bindings from genuinely dead bindings.

With `--fix --unsafe-fixes`, Sable rewrites a direct call to an object-selected
call when it can find exactly one visible dummy or local variable declared as
`class(<declaring type>)` or `type(<declaring type>)` in the calling procedure.
The object name is taken from the source; it is not hard-coded to `this`.

If there is no unique object candidate, Sable reports the diagnostic without a
fix. Calls from submodules are considered for diagnostics, but a fix is only
offered where the local object can be identified in the analyzed source.

#### `SBL204`: Direct call to a private passed-object type-bound target

Reports direct calls to the implementation target of a private type-bound
binding that uses the normal passed-object calling convention.

For example:

```fortran
type :: timings_file
contains
   procedure, private :: print_formatted_task_name
end type timings_file

call print_formatted_task_name(the_file, name_, pl)
```

Sable treats the direct call as evidence that the binding is live, so `SBL202`
will not remove the type-bound declaration. With `--fix --unsafe-fixes`, Sable
rewrites the call through the object and removes the passed-object actual
argument:

```fortran
call the_file%print_formatted_task_name(name_, pl)
```

The object name is taken from the first actual argument and must be declared in
visible scope as `class(<declaring type>)` or `type(<declaring type>)`. Sable
does not currently autofix bindings with an explicit `pass(...)` attribute,
because the passed-object argument may not be the first actual argument in the
direct procedure call.

## Suppressions

Inline:

```fortran
if (a .eq. b) then ! sable: ignore SBL001
end if
```

File-wide:

```fortran
! sable: ignore-file SBL001,SBL004
```

## Configuration

Example `pyproject.toml`:

```toml
[tool.sable.check]
rule_set = "all"  # style | lint | all
select = []
ignore = []
output_format = "text"   # text | json | sarif | gitlab-codequality
baseline = ".sable-baseline.json"
fix = false
unsafe_fixes = false
generate_baseline = false
```

CLI flags override `pyproject.toml` defaults.

## License

MIT
