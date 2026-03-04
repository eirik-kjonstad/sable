<p align="center">
  <img src="https://raw.githubusercontent.com/eirik-kjonstad/sable/v0.1.3/assets/sable-logo.svg" alt="Sable logo" width="420">
</p>

An uncompromising Fortran formatter and checker, inspired by Black and Ruff-style workflows.

## Installation

```bash
pip install sable-fortran
```

## Format vs Check

Sable has two responsibilities:

- `sable format` (or just `sable`) rewrites files to Sable's canonical style.
  This includes syntax/style normalization like `.EQ.` -> `==`, `endif` -> `end if`, declaration normalization, wrapping, and whitespace.
- `sable check` reports rule diagnostics and can apply rule fixes with `--fix`.
  Use `--rule-set` to choose `style`, `lint`, or `all` (default).

## Quick Usage

```bash
# Format in place
sable src/

# Check formatting only (no writes)
sable format --check src/

# Show formatting diff
sable format --diff src/

# Safer migration pass (layout-focused)
sable format --safe src/

# Run all check rules (style + lint)
sable check src/

# Run only lint rules
sable check --rule-set lint src/

# Run only style rules
sable check --rule-set style src/

# Apply safe fixes, then re-check
sable check --fix src/

# Include unsafe fixes too
sable check --fix --unsafe-fixes src/
```

Recommended CI split:

```bash
sable format --check src/
sable check --rule-set lint src/
```

## Rule Sets

`--rule-set all` (default):
- Style: `SBL001`, `SBL002`, `SBL003`, `SBL004`, `SBL005`, `SBL009`, `SBL010`
- Lint: `SBL101`, `SBL102`, `SBL103`

Rule notes:
- `--select` takes precedence over `--rule-set`.
- `--fix` applies safe fixes.
- `--unsafe-fixes` enables unsafe fixes (only with `--fix`).

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
