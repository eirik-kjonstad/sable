<p align="center">
  <img src="assets/sable-logo.svg" alt="Sable logo" width="420">
</p>

An uncompromising Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable enforces one consistent style for modern free-form Fortran, so you can
focus on code instead of formatting.

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

# Check + diff together (non-zero if any file would change)
sable --check --diff src/

# Migration mode: only low-risk whitespace/layout changes
sable --safe src/

# Format piped input (Sable reads stdin when no files are passed)
cat code.f90 | sable

# Optional: label stdin input in diagnostics
cat code.f90 | sable --stdin-filename my_module.f90
```

Directory scans include `.f90`, `.F90`, `.f95`, `.F95`, `.f03`, `.F03`, `.f08`,
and `.F08` files.

## What Sable changes

- Normalizes keyword/operator style (`INTEGER` -> `integer`, `.EQ.` -> `==`,
  `endif` -> `end if` by default).
- Applies consistent spacing and indentation.
- Wraps long lines deterministically (including one-argument-per-line layouts).
- Canonicalizes declarations (`::`, stable attribute order).
- Preserves directives and formatting-off regions (`! sable: off` / `on`).
- Guarantees idempotent output with exactly one trailing newline.

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

## Formatting rules (quick reference)

| Old | New |
|-----|-----|
| `.EQ.` | `==` |
| `.NE.` | `/=` |
| `.LT.` | `<`  |
| `.LE.` | `<=` |
| `.GT.` | `>`  |
| `.GE.` | `>=` |

- Keywords are lower-case by default (`--keyword-case upper` to change).
- Names are preserved exactly as written.
- End keywords use spaced forms by default (`end if`, `end do`; configurable).
- `.AND.`, `.OR.`, `.NOT.`, `.EQV.`, `.NEQV.` are preserved.
- One space around most binary operators; no spaces around `%` or `**`.
- No spaces inside parens/brackets.
- Two spaces before inline comments (`x = 1  ! note`).
- Default indent is 3 spaces (`--indent-width` to change).
- Long lines wrap with `&` using deterministic split rules (`--line-length`).
- Multi-statement lines split into one statement per line.

## Configuration

Sable intentionally exposes few options:

| Flag | Default | Description |
|------|---------|-------------|
| `--line-length`, `-l` | `100` | Max line length |
| `--indent-width`, `-i` | `3` | Spaces per indent level |
| `--keyword-case` | `lower` | `lower` or `upper` |
| `--end-keyword-form` | `spaced` | `spaced` or `compact` |
| `--no-normalize-operators` | off | Keep old-style relational operators |
| `--safe` | off | Migration mode; skip non-safe syntax/canonicalization rewrites |
| `--quiet` | off | Suppress non-error status output |

## Name

*Sable* is heraldic for black — a nod to Black, the Python formatter that
inspired this project.

## License

MIT
