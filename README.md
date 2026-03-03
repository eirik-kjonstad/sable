<p align="center">
  <img src="https://raw.githubusercontent.com/eirik-kjonstad/sable/v0.1.3/assets/sable-logo.svg" alt="Sable logo" width="420">
</p>

An uncompromising Fortran formatter, inspired by [Black](https://github.com/psf/black).

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable enforces one consistent style for modern free-form Fortran, so you can
focus on code instead of formatting.

## Installation

```bash
pip install sable-fortran
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

## Formatting decisions (and why)

Sable intentionally optimizes for deterministic output over hand-tuned style.
Some choices are opinionated by design:

- **Brutal spacing normalization**: Sable rewrites spacing to one canonical form,
  even when input spacing is deliberate for visual alignment.
  - Rationale: removes style drift, avoids bikeshedding, and keeps output fully
    predictable.
- **No manual column alignment preservation**: alignment such as vertically lined
  up `::`, `=>`, or `=` is not preserved.
  - Rationale: aligned columns create fragile diffs; renaming one symbol can
    force many unrelated whitespace changes.
- **No automatic declaration column alignment**: Sable canonicalizes declarations
  but does not align `::` across grouped lines.
  - Rationale: deterministic and stable across edits; avoids cascading
    re-alignment churn.
- **Canonical declaration structure**: typed declarations are normalized to use
  `::`, and attributes are emitted in a stable order.
  - Rationale: one representation per construct improves readability and diff
    consistency.
- **Modern relational operators by default**: `.EQ.`/`.NE.`/... become
  `==`/`/=`/... (unless `--no-normalize-operators` is used).
  - Rationale: modern syntax is shorter, clearer, and consistent with current
    Fortran style.
- **Keyword normalization**: keyword case and end-keyword form are standardized
  (defaults: lower-case + spaced `end if`/`end do`).
  - Rationale: consistent lexical style improves scanability across files.
- **Deterministic wrapping over aesthetic wrapping**: long lines are wrapped by
  fixed rules (including one-argument-per-line in some cases).
  - Rationale: reproducible output matters more than local wrapping taste.
- **Strict operator spacing rules**: most binary operators get spaces, while `%`
  and `**` stay tight (`a%b`, `x**2`).
  - Rationale: preserves common Fortran idioms for component access and
    exponentiation while keeping other expressions readable.

If you need lower-risk adoption first, use `--safe` for migration-oriented
formatting, then switch to full mode later.

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
