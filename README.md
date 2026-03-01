# sable

An opinionated Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable applies a consistent, non-negotiable style to Fortran source files so
that code review can focus on logic rather than style debates.

## Installation

```bash
pip install sable
```

## Development checks

```bash
pip install -e ".[dev]"
pre-commit install
pre-commit run --all-files
```

Pre-commit runs:

- `black` (formatting)
- `ruff` (lint-only; no Ruff formatting)

## Usage

```bash
# Format files in place
sable my_module.f90

# Format all Fortran files in a directory (recursively)
sable src/

# Format multiple files and directories
sable src/ tests/module.f90

# Check without modifying (exit 1 if any file would change)
sable --check src/

# Show a unified diff of changes
sable --diff my_module.f90

# Format stdin, write to stdout
cat code.f90 | sable
cat code.f90 | sable -

# Format stdin and label it in diagnostics
cat code.f90 | sable --stdin-filename my_module.f90
```

Sable recognises `.f90`, `.F90`, `.f95`, `.F95`, `.f03`, `.F03`, `.f08`, and
`.F08` files when scanning directories.

## Formatting decisions

Sable makes the following opinionated choices. They are not configurable
unless the option is marked with *(configurable)*.

### Keywords

- All Fortran keywords are emitted in **lower-case** by default *(configurable:
  `--keyword-case upper`)*.
- Names (variables, procedures, types) are **not** changed — their case is
  preserved exactly as written.

```fortran
! Before
INTEGER, INTENT(IN) :: X

! After
integer, intent(in) :: X
```

### Compound END keywords

Sable normalises `endif` / `enddo` / `endsubroutine` etc. to their **spaced**
forms (`end if` / `end do` / `end subroutine`) by default *(configurable:
`--end-keyword-form compact`)*.

```fortran
! Before
if (x > 0) then
  y = 1
endif

! After
if (x > 0) then
  y = 1
end if
```

### Relational operators

Old-style relational operators are replaced with their modern equivalents:

| Old | New |
|-----|-----|
| `.EQ.` | `==` |
| `.NE.` | `/=` |
| `.LT.` | `<`  |
| `.LE.` | `<=` |
| `.GT.` | `>`  |
| `.GE.` | `>=` |

`.AND.`, `.OR.`, `.NOT.`, `.EQV.`, `.NEQV.` have no modern equivalents and
are kept, but normalised to lower-case.

*(Disable with `--no-normalize-operators`)*

### Spacing

- **One space** around binary operators: `=`, `==`, `/=`, `<`, `<=`, `>`,
  `>=`, `+`, `-`, `//`, `=>`, `::`.
- **No space** around `%` (component access) and `**` (exponentiation):
  `obj%field`, `x**2`.
- **One space** after each comma: `call foo(a, b, c)`.
- **No space** inside parentheses or brackets: `foo(a, b)` not `foo( a, b )`.
- **No space** around `:` in array subscripts/slices: `a(1:n)`.
- **Two spaces** before inline comments: `x = 1  ! comment`.

### Indentation

- **3 spaces** per level by default *(configurable: `--indent-width N`)*.
- Indentation increases after: `then`, `do`, `else`, `contains`, `module`,
  `program`, `function`, `subroutine`, `interface`, `type`, `select case`,
  `associate`, `block`, `critical`, `where`, `forall`.
- `else` / `elseif` / `case` / `contains` dedent before the line, then
  re-indent the body.

```fortran
do i = 1, n
   do j = 1, m
      a(i, j) = i + j
   end do
end do
```

### Line length and continuation

Lines exceeding **100 characters** *(configurable: `--line-length N`)* are
broken with Fortran continuation markers (`&`). Continuation lines are
indented by one additional level.

When choosing line-break points, Sable uses deterministic priority rules:
top-level commas first, then assignment (`=`), then low-precedence operators
(`.or.`, `.and.`, `+`, `-`, `//`), before falling back to greedy splitting.

**Argument-list explosion.** When a call, definition, or similar construct has
multiple arguments and is too long to fit on one line, Sable explodes it
one-argument-per-line (Black style), with `&` markers aligned in a column:

```fortran
! Before (too long)
call compute(alpha_input, beta_input, gamma_input, result_output)

! After
call compute(    &
   alpha_input,  &
   beta_input,   &
   gamma_input,  &
   result_output &
)
```

**Sticky multiline argument lists.** If an argument list is already written
across multiple physical lines in the input, Sable keeps it exploded even when
it would fit on one line under the configured line length.

**String literal splitting.** String literals that are too long to fit on one
physical line are split using Fortran in-string continuation:

```fortran
description = &
   'A long description that would otherwise exceed the line &
   &length limit is split here.'
```

The in-string `&` at the end of a physical line and the resuming `&` at the
start of the next are stripped when the file is re-read, so the string value
is preserved exactly.

**Single-line `if` statements** that fit within the line limit are kept on one
line. If they are too long, the action is split to a continuation line:

```fortran
! Short: kept as-is
if (x > 0) y = y + 1

! Long: split at the action boundary
if (norm2(residual) > threshold) &
   call handle_convergence_failure(solver)
```

### Blank lines between routines

Consecutive `subroutine` and `function` definitions within a `module` or
`contains` block are separated by exactly **two blank lines**. Comment-only
gaps are left as-is.

### Comment indentation

Standalone comment lines and blank lines between statements are held in a
buffer and emitted at the indentation level of the **next** code line, so
comments always align with the code they precede.

### Preprocessor directives

Lines beginning with `#` (e.g. `#ifdef`, `#define`, `#endif`) are passed
through unchanged and always emitted at **column 0**, regardless of the
surrounding indentation level.

### Formatting control comments

Use `! sable: off` and `! sable: on` to disable formatting for a region.
Everything inside that region is emitted verbatim.

### Semicolons

Semicolons used as statement separators are expanded to separate lines:

```fortran
! Before
x = 1; y = 2

! After
x = 1
y = 2
```

### File endings

Files always end with exactly **one newline** character.

## Configuration

Sable intentionally exposes very few options (Black philosophy). The supported
flags are:

| Flag | Default | Description |
|------|---------|-------------|
| `--line-length`, `-l` | `100` | Max line length |
| `--indent-width`, `-i` | `3` | Spaces per indent level |
| `--keyword-case` | `lower` | `lower` or `upper` |
| `--end-keyword-form` | `spaced` | `spaced` or `compact` |
| `--no-normalize-operators` | off | Keep old-style relational operators |

## Roadmap

- [ ] `pyproject.toml` / `sable.toml` configuration file support
- [ ] Alignment of `::` in declaration blocks
- [ ] `USE` statement sorting and deduplication
- [ ] `IMPLICIT NONE` insertion
- [ ] Fixed-form (Fortran 77) source support
- [x] Pre-commit hook integration

## Name

*Sable* is heraldic for black — a nod to Black, the Python formatter that
inspired this project.

## License

MIT
