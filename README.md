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
CALL compute(alpha,beta,gamma)
ENDIF

! After
if (A == B) then
   call compute( &
      alpha, &
      beta, &
      gamma &
   )
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
