# sable

An opinionated Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "Any customer can have a car painted any colour that he wants so long as it is black."
> — Henry Ford

Sable applies a consistent, non-negotiable style to Fortran source files so
that code review can focus on logic rather than style debates.

## Installation

```bash
pip install sable
```

## Usage

```bash
# Format files in place
sable my_module.f90 src/**/*.f90

# Check without modifying (exit 1 if any file would change)
sable --check src/**/*.f90

# Show a unified diff of changes
sable --diff my_module.f90

# Format stdin, write to stdout
cat code.f90 | sable
```

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
- **One space** before inline comments: `x = 1  ! comment`.

### Indentation

- **2 spaces** per level by default *(configurable: `--indent-width N`)*.
- Indentation increases after: `then`, `do`, `else`, `contains`, `module`,
  `program`, `function`, `subroutine`, `interface`, `type`, `select case`,
  `associate`, `block`, `critical`, `where`, `forall`.
- `else` / `elseif` / `case` dedent before the line, then re-indent the body.

```fortran
do i = 1, n
  do j = 1, m
    a(i, j) = i + j
  end do
end do
```

### Line length

Lines exceeding **100 characters** (*(configurable: `--line-length N`)*)
are broken with Fortran continuation markers (`&`). Continuation lines are
indented by one additional level.

### File endings

Files always end with exactly **one newline** character.

### Semicolons

Semicolons used as statement separators are expanded to separate lines:

```fortran
! Before
x = 1; y = 2

! After
x = 1
y = 2
```

## Configuration

Sable intentionally exposes very few options (Black philosophy). The supported
flags are:

| Flag | Default | Description |
|------|---------|-------------|
| `--line-length` | `100` | Max line length |
| `--indent-width` | `2` | Spaces per indent level |
| `--keyword-case` | `lower` | `lower` or `upper` |
| `--end-keyword-form` | `spaced` | `spaced` or `compact` |
| `--no-normalize-operators` | off | Keep old-style relational operators |

## Roadmap

- [ ] `pyproject.toml` / `sable.toml` configuration file support
- [ ] Blank-line normalisation between program units and declarations
- [ ] Alignment of `::` in declaration blocks
- [ ] `USE` statement sorting and deduplication
- [ ] `IMPLICIT NONE` insertion
- [ ] Fixed-form (Fortran 77) source support
- [ ] Pre-commit hook integration

## Name

*Sable* is heraldic for black — a nod to Black, the Python formatter that
inspired this project.

## License

MIT
