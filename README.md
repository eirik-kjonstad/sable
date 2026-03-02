# sable

An opinionated Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable applies a consistent, non-negotiable style to Fortran source files so
code review can focus on logic rather than style debates.

## Installation

```bash
pip install sable
```

## Usage

```bash
# Format a file or directory in place
sable my_module.f90
sable src/

# Check formatting without changing files (exit 1 if changes are needed)
sable --check src/

# Preview changes as a unified diff
sable --diff src/

# Format from stdin (stdout result)
sable - < code.f90
sable --stdin-filename my_module.f90 - < code.f90
```

Sable recognises `.f90`, `.F90`, `.f95`, `.F95`, `.f03`, `.F03`, `.f08`, and
`.F08` files when scanning directories.

## Formatting decisions

Sable makes the following opinionated choices. They are not configurable
unless the option is marked with *(configurable)*.

### Most visible changes

These are the style changes users usually notice first:

1. Keyword and operator normalization (`INTEGER` -> `integer`, `.EQ.` -> `==`,
   `endif` -> `end if` by default).
2. Consistent spacing and indentation across modern and legacy constructs.
3. Deterministic wrapping for long lines, including Black-style
   one-argument-per-line formatting for long calls/definitions.

```fortran
! Before
IF(A .EQ. B)THEN
CALL compute(alpha_input,beta_input,gamma_input,result_output)
ENDIF

! After
if (A == B) then
   call compute(    &
      alpha_input,  &
      beta_input,   &
      gamma_input,  &
      result_output &
   )
end if
```

### Keywords and operators

- All Fortran keywords are emitted in **lower-case** by default *(configurable:
  `--keyword-case upper`)*.
- Names (variables, procedures, types) are preserved exactly as written.
- `endif` / `enddo` / `endsubroutine` etc. are normalized to spaced forms by
  default *(configurable: `--end-keyword-form compact`)*.
- Old-style relational operators are normalized by default *(disable with
  `--no-normalize-operators`)*:

| Old | New |
|-----|-----|
| `.EQ.` | `==` |
| `.NE.` | `/=` |
| `.LT.` | `<`  |
| `.LE.` | `<=` |
| `.GT.` | `>`  |
| `.GE.` | `>=` |

`.AND.`, `.OR.`, `.NOT.`, `.EQV.`, `.NEQV.` are preserved (with keyword-case
normalization).

### Spacing and indentation

- **One space** around binary operators (`=`, `==`, `/=`, `<`, `<=`, `>`, `>=`,
  `+`, `-`, `//`, `=>`, `::`), but **no spaces** around `%` and `**`.
- **One space** between control/selector heads and `(`:
  `if (...)`, `associate (...)`, `do concurrent (...)`, `select type (...)`,
  `type is (...)`, `rank (...)`, `change team (...)`.
- **No spaces** inside parens/brackets, and `:` spacing is context-aware:
  `a(1:n)` and `use m, only: foo`.
- **Two spaces** before inline comments: `x = 1  ! comment`.
- **3 spaces** per indent level by default *(configurable: `--indent-width N`)*,
  with correct dedent/re-indent behavior for `else`, `elseif`, `case`,
  `contains`, `select type`, and `select rank` branches.

### Line wrapping and continuation

Lines exceeding **100 characters** *(configurable: `--line-length N`)* are
wrapped with Fortran continuation markers (`&`).

- Split priority is deterministic: top-level commas, then assignment (`=`), then
  low-precedence operators (`.or.`, `.and.`, `+`, `-`, `//`), then greedy split.
- Long multi-argument calls/definitions are exploded one-argument-per-line.
- Existing multiline argument lists stay exploded ("sticky multiline").
- Single-line `if` statements stay on one line when they fit; otherwise Sable
  splits between condition and action.
- Long strings are split using valid Fortran in-string continuation, and existing
  in-string continuations are normalized without changing string values.
- Wrap logic avoids problematic splits in `%` chains (`a%b%c`) and around
  `(/ ... /)` array-constructor delimiters, and avoids leading commas/operators
  on continuation lines where possible.

### Comments, routines, and directives

- Consecutive `subroutine`/`function` definitions in `module`/`contains` blocks
  are separated by exactly **two blank lines** (comment-only gaps are preserved).
- Standalone comments and blank lines are aligned with the following code line.
- Preprocessor directives (`#ifdef`, `#elif`, `#else`, `#endif`, `#define`, ...)
  are emitted unchanged at **column 0**.
- Compiler directive comments like `!$OMP ...` are preserved and kept aligned
  with surrounding code.
- `! sable: off` / `! sable: on` disables formatting for verbatim regions.

### Other guarantees

- Semicolon-separated statements are expanded to separate lines.
- Output is idempotent: formatting an already formatted file produces the same
  result.
- Files always end with exactly **one newline**.

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

## Name

*Sable* is heraldic for black — a nod to Black, the Python formatter that
inspired this project.

## License

MIT
