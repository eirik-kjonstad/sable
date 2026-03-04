<p align="center">
  <img src="https://raw.githubusercontent.com/eirik-kjonstad/sable/v0.1.3/assets/sable-logo.svg" alt="Sable logo" width="420">
</p>

An uncompromising Fortran formatter and checker, inspired by [Black](https://github.com/psf/black) and Ruff-style workflows.

> "So it goes."
> — Kurt Vonnegut, *Slaughterhouse-Five*

Sable enforces one consistent style for modern free-form Fortran and can also
report/fix rule-based diagnostics.

## Installation

```bash
pip install sable-fortran
```

## Usage

```bash
# Format a file or directory in place
sable my_module.f90
sable src/
sable format src/

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

# Run rule-based checks (no rewriting)
sable check src/

# Apply safe autofixes, then re-check
sable check --fix src/

# Allow unsafe autofixes too (only with --fix)
sable check --fix --unsafe-fixes src/

# Machine-readable output
sable check --output-format json src/
sable check --output-format sarif src/

# Baseline workflow for gradual adoption
sable check --generate-baseline --baseline .sable-baseline.json src/
sable check --baseline .sable-baseline.json src/
```

Directory scans include `.f90`, `.F90`, `.f95`, `.F95`, `.f03`, `.F03`, `.f08`,
and `.F08` files.

## What Sable does

- Rewrites source to one consistent, project-wide style.
- Applies consistent whitespace, indentation, and line wrapping.
- Normalizes modern free-form Fortran syntax and layout into stable forms.
- Preserves directives and formatting-off regions (`! sable: off` / `on`).
- Guarantees idempotent output with exactly one trailing newline.
- Reports rule-based diagnostics with stable rule IDs (`SBL...`).
- Supports safe and unsafe autofixes with explicit gating.

## Formatting decisions (and why)

Sable favors deterministic output over hand-tuned layout and aims to minimize re-spacing diffs and yield a unified style. This leads to some intentional choices that can look unusual at first:

- **Spacing normalization**: manual visual alignment is not preserved.
- **No grouped alignment**: Sable does not vertically align `::`, `=>`, `=`, etc., across lines.
- **Canonical declarations**: typed declarations use `::` with stable attribute ordering.
- **Modern relational operators by default**: `.EQ.`/`.NE.`/... become `==`/`/=`/... .
- **Standard keyword forms**: defaults are lower-case keywords and spaced end forms (`end if`, `end do`).
- **Deterministic wrapping**: line breaks follow fixed rules rather than per-line aesthetics.
- **Tight `%` and `**`**: component access and exponentiation stay unspaced (`a%b`, `x**2`).

Use `--safe` for lower-risk migration first, then full mode for complete normalization.

```fortran
! Before
IF(A .EQ. B)THEN
CALL compute(alpha_input,beta_input,gamma_input,result_output)
ENDIF

! After
if (A == B) then
   call compute( &
      alpha_input, &
      beta_input, &
      gamma_input, &
      result_output &
   )
end if
```

## Formatting rules (quick reference)

| Input | Output (default) |
|-----|-----|
| `.EQ.` | `==` |
| `.NE.` | `/=` |
| `.LT.` | `<`  |
| `.LE.` | `<=` |
| `.GT.` | `>`  |
| `.GE.` | `>=` |
| `endif` | `end if` |
| `integer x` | `integer :: x` |

- Keywords are lower-case by default (`--keyword-case upper` to change); identifier spelling/case is preserved.
- End keywords default to spaced forms (`end if`, `end do`; configurable).
- One space around most binary operators and after commas; `%` and `**` stay tight.
- No spaces inside `()`/`[]`, except required construct-head spacing (`if (...)`, `select type (...)`).
- Declarations are canonicalized (`::` inserted and attributes emitted in stable order).
- Inline comments are separated from code by two spaces (`x = 1  ! note`).
- Long lines wrap deterministically with `&`; `;`-separated statements are emitted one per line.
- Preprocessor directives stay at column 0, and output is idempotent with one trailing newline.

## Check mode rules (current)

| Rule | Description | Fix safety |
|------|-------------|------------|
| `SBL001` | Old-style relational operators can be modernized (`.EQ.` -> `==`) | Safe |
| `SBL002` | END keyword form differs from configured style | Safe |
| `SBL003` | Declaration is missing `::` | Safe |
| `SBL004` | Semicolon-separated statements should be split | Safe |
| `SBL005` | Trailing whitespace/newline style is non-canonical | Safe |
| `SBL009` | Tab indentation detected | Safe |
| `SBL010` | Stray leading continuation marker `&` | Safe |
| `SBL101` | Program unit is missing `implicit none` | Unsafe |

Notes:
- `--fix` applies safe fixes.
- `--unsafe-fixes` enables unsafe fixes (only when `--fix` is also set).
- Diagnostics are re-evaluated after fixes.

## Suppressions

You can suppress findings inline:

```fortran
if (a .eq. b) then ! sable: ignore SBL001
end if
```

Or file-wide:

```fortran
! sable: ignore-file SBL001,SBL004
```

## Configuration

Formatting options:

| Flag | Default | Description |
|------|---------|-------------|
| `--line-length`, `-l` | `100` | Max line length |
| `--indent-width`, `-i` | `3` | Spaces per indent level |
| `--keyword-case` | `lower` | `lower` or `upper` |
| `--end-keyword-form` | `spaced` | `spaced` or `compact` |
| `--no-normalize-operators` | off | Keep old-style relational operators |
| `--safe` | off | Migration mode; skip non-safe syntax/canonicalization rewrites |
| `--quiet` | off | Suppress non-error status output |

Check options:

| Flag | Default | Description |
|------|---------|-------------|
| `--select RULE` | all | Run only selected rule code(s) |
| `--ignore RULE` | none | Ignore selected rule code(s) |
| `--fix` | off | Apply safe autofixes, then re-check |
| `--unsafe-fixes` | off | Include unsafe fixes (requires `--fix`) |
| `--output-format` | `text` | `text`, `json`, or `sarif` |
| `--baseline PATH` | none | Filter diagnostics present in baseline |
| `--generate-baseline` | off | Write current diagnostics to baseline file |

`sable check` also supports project defaults from `pyproject.toml`:

```toml
[tool.sable.check]
select = ["SBL001", "SBL002", "SBL003", "SBL004", "SBL005", "SBL009", "SBL010"]
ignore = ["SBL101"]
output_format = "text"   # text | json | sarif
baseline = ".sable-baseline.json"
fix = false
unsafe_fixes = false
generate_baseline = false
```

CLI flags take precedence over `pyproject.toml` defaults.

## License

MIT
