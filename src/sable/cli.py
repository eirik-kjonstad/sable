"""Command-line interface for sable."""

from __future__ import annotations

import sys
from pathlib import Path

import click

try:  # Python 3.11+
    import tomllib as toml
except ModuleNotFoundError:  # Python 3.10
    import tomli as toml

from . import __version__
from .baseline import diagnostic_key, load_baseline, write_baseline
from .checker import apply_fixes, check_source
from .formatter import DEFAULT_CONFIG, FormatConfig, format_source
from .outputs import (
    render_diagnostics_gitlab_codequality,
    render_diagnostics_json,
    render_diagnostics_sarif,
    render_diagnostics_text,
)
from .rules import get_rule_summaries

# ── Output helpers ────────────────────────────────────────────────────────────


def _sym(char: str, **style) -> str:
    return click.style(char, **style)


SYM_OK = _sym("✓", fg="green")
SYM_CHANGED = _sym("◆", fg="yellow", bold=True)
SYM_SKIP = _sym("~", fg="yellow")
SYM_ERR = _sym("✗", fg="red", bold=True)


def _fmt_label(label: str) -> str:
    return click.style(label, bold=True)


def _summary(n_changed: int, n_unchanged: int, n_errors: int, check: bool) -> str:
    parts: list[str] = []

    if check:
        if n_changed:
            parts.append(
                click.style(
                    (
                        f"{n_changed} file{'s' if n_changed != 1 else ''} "
                        "would be reformatted"
                    ),
                    fg="yellow",
                    bold=True,
                )
            )
        if n_unchanged:
            parts.append(
                click.style(
                    f"{n_unchanged} already formatted",
                    fg="green",
                )
            )
    else:
        if n_changed:
            parts.append(
                click.style(
                    f"{n_changed} file{'s' if n_changed != 1 else ''} reformatted",
                    fg="yellow",
                    bold=True,
                )
            )
        if n_unchanged:
            parts.append(
                click.style(
                    f"{n_unchanged} unchanged",
                    fg="green",
                )
            )

    if n_errors:
        parts.append(
            click.style(
                f"{n_errors} error{'s' if n_errors != 1 else ''}",
                fg="red",
                bold=True,
            )
        )

    return ", ".join(parts) + "."


def _style_diff_line(line: str) -> str:
    if line.startswith("@@"):
        return click.style(line, fg="cyan")
    if line.startswith("--- ") or line.startswith("+++ "):
        return click.style(line, fg="cyan", bold=True)
    if line.startswith("-"):
        return click.style(line, fg="red")
    if line.startswith("+"):
        return click.style(line, fg="green")
    return line


def _colorize_unified_diff(delta: list[str]) -> str:
    return "".join(_style_diff_line(line) for line in delta)


# ── Config ────────────────────────────────────────────────────────────────────


def _make_config(
    line_length: int,
    indent_width: int,
    keyword_case: str,
    end_keyword_form: str,
    no_normalize_operators: bool,
) -> FormatConfig:
    return FormatConfig(
        line_length=line_length,
        indent_width=indent_width,
        keyword_case=keyword_case,
        end_keyword_form=end_keyword_form,
        normalize_operators=not no_normalize_operators,
    )


def _make_safe_config(base: FormatConfig) -> FormatConfig:
    return FormatConfig(
        line_length=base.line_length,
        indent_width=base.indent_width,
        keyword_case=base.keyword_case,
        end_keyword_form=base.end_keyword_form,
        normalize_operators=False,
        trailing_newline=base.trailing_newline,
        double_colon_declarations=base.double_colon_declarations,
        normalize_keyword_case=False,
        normalize_end_keywords=False,
        canonicalize_declarations=False,
    )


_FORTRAN_SUFFIXES = {".f90", ".F90", ".f95", ".F95", ".f03", ".F03", ".f08", ".F08"}


def _collect_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(f for f in path.rglob("*") if f.suffix in _FORTRAN_SUFFIXES)
    return [path]


def _find_pyproject(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        path = candidate / "pyproject.toml"
        if path.is_file():
            return path
    return None


def _load_check_defaults(cwd: Path) -> dict[str, object]:
    pyproject = _find_pyproject(cwd)
    if pyproject is None:
        return {}

    try:
        data = toml.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}
    sable = tool.get("sable")
    if not isinstance(sable, dict):
        return {}
    check = sable.get("check")
    if not isinstance(check, dict):
        return {}
    return check


def _resolve_tuple_option(
    cli_value: tuple[str, ...],
    config_value: object,
) -> tuple[str, ...]:
    if cli_value:
        return cli_value
    if isinstance(config_value, list) and all(isinstance(v, str) for v in config_value):
        return tuple(config_value)
    return ()


def _resolve_str_option(
    cli_value: str | None,
    config_value: object,
    default: str,
) -> str:
    if cli_value is not None:
        return cli_value
    if isinstance(config_value, str) and config_value:
        return config_value
    return default


def _resolve_bool_option(
    cli_value: bool | None,
    config_value: object,
    default: bool,
) -> bool:
    if cli_value is not None:
        return cli_value
    if isinstance(config_value, bool):
        return config_value
    return default


def _read_sources(
    files: tuple[Path, ...], stdin_filename: str | None
) -> tuple[list[tuple[str, Path | None]], list[tuple[Path, Exception]]]:
    sources: list[tuple[str, Path | None]] = []
    read_errors: list[tuple[Path, Exception]] = []

    if not files:
        source = sys.stdin.read()
        path = Path(stdin_filename) if stdin_filename else None
        sources.append((source, path))
        return sources, read_errors

    for entry in files:
        if str(entry) == "-":
            source = sys.stdin.read()
            path = Path(stdin_filename) if stdin_filename else None
            sources.append((source, path))
            continue

        for resolved in _collect_files(entry):
            try:
                source = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                read_errors.append((resolved, exc))
                continue
            sources.append((source, resolved))

    return sources, read_errors


def _run_format(
    files: tuple[Path, ...],
    check: bool,
    diff: bool,
    safe: bool,
    quiet: bool,
    cfg: FormatConfig,
    stdin_filename: str | None,
) -> int:
    safe_cfg = _make_safe_config(cfg) if safe else cfg
    sources, read_errors = _read_sources(files, stdin_filename)

    any_changed = False
    exit_code = 0
    n_changed = n_unchanged = n_errors = 0
    n_safe_non_safe_available = 0
    stdin_mode = False

    for path, exc in read_errors:
        if not quiet:
            click.echo(f"{SYM_ERR} {_fmt_label(str(path))}: {exc}", err=True)
        else:
            click.echo(f"{_fmt_label(str(path))}: {exc}", err=True)
        exit_code = 123
        n_errors += 1

    for source, path in sources:
        label = str(path) if path else "<stdin>"
        try:
            formatted = format_source(source, safe_cfg)
            if safe:
                full_formatted = format_source(source, cfg)
                if full_formatted != formatted:
                    n_safe_non_safe_available += 1
        except Exception as exc:  # noqa: BLE001
            click.echo(f"{SYM_ERR} {_fmt_label(label)}: {exc}", err=True)
            exit_code = 123
            n_errors += 1
            continue

        changed = formatted != source

        if diff and changed:
            import difflib

            original_lines = source.splitlines(keepends=True)
            formatted_lines = formatted.splitlines(keepends=True)
            delta = list(
                difflib.unified_diff(
                    original_lines,
                    formatted_lines,
                    fromfile=f"a/{label}",
                    tofile=f"b/{label}",
                )
            )
            click.echo(_colorize_unified_diff(delta), nl=False)

        if check:
            if changed:
                if not quiet:
                    click.echo(
                        f"{SYM_SKIP} {_fmt_label(label)} "
                        + click.style("would be reformatted", fg="yellow")
                    )
                any_changed = True
                n_changed += 1
            else:
                if not quiet:
                    click.echo(
                        f"{SYM_OK} {click.style(label, dim=True)} "
                        + click.style("already formatted", fg="green")
                    )
                n_unchanged += 1
        else:
            if diff:
                if changed:
                    n_changed += 1
                else:
                    n_unchanged += 1
            elif path and str(path) != "-":
                if changed:
                    path.write_text(formatted, encoding="utf-8")
                    if not quiet:
                        click.echo(f"{SYM_CHANGED} {_fmt_label(label)}")
                    n_changed += 1
                else:
                    if not quiet:
                        click.echo(f"{SYM_OK} {click.style(label, dim=True)}")
                    n_unchanged += 1
            else:
                stdin_mode = True
                click.echo(formatted, nl=False)

    if (
        not quiet
        and not stdin_mode
        and (n_changed + n_unchanged + n_errors) > 0
        and (check or not diff)
    ):
        click.echo()
        click.echo(
            click.style("All done! ", fg="cyan", bold=True)
            + _summary(n_changed, n_unchanged, n_errors, check)
        )

    if safe and n_safe_non_safe_available and not quiet and not stdin_mode:
        click.echo(
            click.style("Note: ", fg="cyan", bold=True)
            + (
                f"{n_safe_non_safe_available} file"
                f"{'s' if n_safe_non_safe_available != 1 else ''} "
                "have additional non-safe rewrites available in full mode."
            )
        )

    if check and any_changed:
        exit_code = 1

    return exit_code


def _run_check(
    files: tuple[Path, ...],
    stdin_filename: str | None,
    select: tuple[str, ...],
    ignore: tuple[str, ...],
    rule_set: str,
    output_format: str,
    cfg: FormatConfig,
    fix: bool,
    unsafe_fixes: bool,
    baseline: str | None,
    generate_baseline: bool,
) -> int:
    sources, read_errors = _read_sources(files, stdin_filename)
    diagnostics = []
    source_lookup: dict[str, str] = {}
    n_errors = 0
    stdin_fixed = False
    baseline_path = Path(baseline) if baseline else Path(".sable-baseline.json")
    baseline_keys = set()

    if baseline and not baseline_path.exists() and not generate_baseline:
        click.echo(
            f"{SYM_ERR} {_fmt_label(str(baseline_path))}: baseline file not found",
            err=True,
        )
        return 123
    if baseline and not generate_baseline:
        try:
            baseline_keys = load_baseline(baseline_path)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"{SYM_ERR} {_fmt_label(str(baseline_path))}: {exc}", err=True)
            return 123

    for path, exc in read_errors:
        click.echo(f"{SYM_ERR} {_fmt_label(str(path))}: {exc}", err=True)
        n_errors += 1

    for source, path in sources:
        label = str(path) if path else "<stdin>"
        try:
            file_diagnostics = check_source(
                source=source,
                cfg=cfg,
                path=path,
                select=set(select) if select else None,
                ignore=set(ignore) if ignore else None,
                rule_set=rule_set,
            )
            if fix:
                fixed, _n_applied = apply_fixes(
                    source, file_diagnostics, include_unsafe=unsafe_fixes
                )
                if fixed != source:
                    if path and str(path) != "-":
                        path.write_text(fixed, encoding="utf-8")
                    else:
                        stdin_fixed = True
                        click.echo(fixed, nl=False)
                    source = fixed
                file_diagnostics = check_source(
                    source=source,
                    cfg=cfg,
                    path=path,
                    select=set(select) if select else None,
                    ignore=set(ignore) if ignore else None,
                    rule_set=rule_set,
                )
            diagnostics.extend(file_diagnostics)
            source_lookup[label] = source
        except Exception as exc:  # noqa: BLE001
            click.echo(f"{SYM_ERR} {_fmt_label(label)}: {exc}", err=True)
            n_errors += 1

    if baseline_keys:
        diagnostics = [
            diag for diag in diagnostics if diagnostic_key(diag) not in baseline_keys
        ]

    if generate_baseline:
        try:
            write_baseline(baseline_path, diagnostics)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"{SYM_ERR} {_fmt_label(str(baseline_path))}: {exc}", err=True)
            return 123

    if output_format == "json":
        click.echo(render_diagnostics_json(diagnostics), nl=False)
    elif output_format == "gitlab-codequality":
        click.echo(render_diagnostics_gitlab_codequality(diagnostics), nl=False)
    elif output_format == "sarif":
        click.echo(
            render_diagnostics_sarif(
                diagnostics,
                source_lookup=source_lookup,
                rule_summaries=get_rule_summaries(),
            ),
            nl=False,
        )
    elif diagnostics and not stdin_fixed:
        click.echo(render_diagnostics_text(diagnostics), nl=False)
    elif diagnostics and stdin_fixed:
        click.echo(render_diagnostics_text(diagnostics), nl=False, err=True)

    if n_errors:
        return 123
    if generate_baseline:
        return 0
    if diagnostics:
        return 1
    return 0


class _DefaultCommandGroup(click.Group):
    def __init__(self, *args, default_command: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.default_command = default_command

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        passthrough = {"-h", "--help", "-V", "--version"}
        if args and args[0] in passthrough:
            return super().parse_args(ctx, args)
        if not args or args[0] not in self.commands:
            args.insert(0, self.default_command)
        return super().parse_args(ctx, args)


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.group(
    cls=_DefaultCommandGroup,
    default_command="format",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, "-V", "--version")
def main() -> None:
    """Sable: an uncompromising Fortran formatter and checker."""


@main.command("format")
@click.argument(
    "files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path, file_okay=True, dir_okay=True),
)
@click.option(
    "--check",
    is_flag=True,
    default=False,
    help="Don't write files, exit non-zero if any file would change.",
)
@click.option(
    "--diff",
    is_flag=True,
    default=False,
    help="Don't write files, print a unified diff of changes.",
)
@click.option(
    "--safe",
    is_flag=True,
    default=False,
    help="Migration mode: only apply low-risk whitespace/layout changes.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress non-error status output (useful with --check).",
)
@click.option(
    "--line-length",
    "-l",
    default=DEFAULT_CONFIG.line_length,
    show_default=True,
    help="Maximum line length.",
    metavar="INT",
)
@click.option(
    "--indent-width",
    "-i",
    default=DEFAULT_CONFIG.indent_width,
    show_default=True,
    help="Spaces per indentation level.",
    metavar="INT",
)
@click.option(
    "--keyword-case",
    default=DEFAULT_CONFIG.keyword_case,
    show_default=True,
    type=click.Choice(["lower", "upper"], case_sensitive=False),
    help="Keyword casing.",
)
@click.option(
    "--end-keyword-form",
    default=DEFAULT_CONFIG.end_keyword_form,
    show_default=True,
    type=click.Choice(["spaced", "compact"], case_sensitive=False),
    help="Form of compound END keywords (e.g. 'end if' vs 'endif').",
)
@click.option(
    "--no-normalize-operators",
    is_flag=True,
    default=False,
    help="Keep old-style relational operators (.EQ., .GT., …) as-is.",
)
@click.option(
    "--stdin-filename",
    default=None,
    help="Filename to use when formatting stdin (for diagnostics only).",
    metavar="PATH",
)
def format_command(
    files: tuple[Path, ...],
    check: bool,
    diff: bool,
    safe: bool,
    quiet: bool,
    line_length: int,
    indent_width: int,
    keyword_case: str,
    end_keyword_form: str,
    no_normalize_operators: bool,
    stdin_filename: str | None,
) -> None:
    """Format FILES in place. Reads from stdin if no FILES are given."""
    cfg = _make_config(
        line_length=line_length,
        indent_width=indent_width,
        keyword_case=keyword_case,
        end_keyword_form=end_keyword_form,
        no_normalize_operators=no_normalize_operators,
    )
    code = _run_format(
        files=files,
        check=check,
        diff=diff,
        safe=safe,
        quiet=quiet,
        cfg=cfg,
        stdin_filename=stdin_filename,
    )
    raise click.exceptions.Exit(code)


@main.command("check")
@click.argument(
    "files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path, file_okay=True, dir_okay=True),
)
@click.option(
    "--select",
    multiple=True,
    metavar="RULE",
    help="Run only the specified rule code(s). Repeat for multiple rules.",
)
@click.option(
    "--ignore",
    multiple=True,
    metavar="RULE",
    help="Ignore the specified rule code(s). Repeat for multiple rules.",
)
@click.option(
    "--rule-set",
    default=None,
    type=click.Choice(["lint", "style", "all"], case_sensitive=False),
    help=(
        "Choose the rule category to run: lint (policy), style "
        "(formatter-adjacent), or all."
    ),
)
@click.option(
    "--output-format",
    default=None,
    type=click.Choice(
        ["text", "json", "sarif", "gitlab-codequality"], case_sensitive=False
    ),
    help="Diagnostic output format (defaults to pyproject setting or text).",
)
@click.option(
    "--fix/--no-fix",
    default=None,
    help="Apply safe autofixes in place, then re-check (supports pyproject default).",
)
@click.option(
    "--unsafe-fixes/--no-unsafe-fixes",
    default=None,
    help="Allow applying unsafe fixes (only used with --fix).",
)
@click.option(
    "--baseline",
    default=None,
    metavar="PATH",
    help="Path to baseline file. Existing baseline filters known diagnostics.",
)
@click.option(
    "--generate-baseline/--no-generate-baseline",
    default=None,
    help="Write current diagnostics to baseline file and exit zero on success.",
)
@click.option(
    "--line-length",
    "-l",
    default=DEFAULT_CONFIG.line_length,
    show_default=True,
    help="Maximum line length.",
    metavar="INT",
)
@click.option(
    "--indent-width",
    "-i",
    default=DEFAULT_CONFIG.indent_width,
    show_default=True,
    help="Spaces per indentation level.",
    metavar="INT",
)
@click.option(
    "--keyword-case",
    default=DEFAULT_CONFIG.keyword_case,
    show_default=True,
    type=click.Choice(["lower", "upper"], case_sensitive=False),
    help="Keyword casing.",
)
@click.option(
    "--end-keyword-form",
    default=DEFAULT_CONFIG.end_keyword_form,
    show_default=True,
    type=click.Choice(["spaced", "compact"], case_sensitive=False),
    help="Form of compound END keywords (e.g. 'end if' vs 'endif').",
)
@click.option(
    "--no-normalize-operators",
    is_flag=True,
    default=False,
    help="Keep old-style relational operators (.EQ., .GT., …) as-is.",
)
@click.option(
    "--stdin-filename",
    default=None,
    help="Filename to use when checking stdin (for diagnostics only).",
    metavar="PATH",
)
def check_command(
    files: tuple[Path, ...],
    select: tuple[str, ...],
    ignore: tuple[str, ...],
    rule_set: str | None,
    output_format: str | None,
    fix: bool | None,
    unsafe_fixes: bool | None,
    baseline: str | None,
    generate_baseline: bool | None,
    line_length: int,
    indent_width: int,
    keyword_case: str,
    end_keyword_form: str,
    no_normalize_operators: bool,
    stdin_filename: str | None,
) -> None:
    """Check FILES for Sable diagnostics without rewriting files."""
    defaults = _load_check_defaults(Path.cwd())
    resolved_select = _resolve_tuple_option(select, defaults.get("select"))
    resolved_ignore = _resolve_tuple_option(ignore, defaults.get("ignore"))
    resolved_rule_set = _resolve_str_option(rule_set, defaults.get("rule_set"), "all")
    resolved_rule_set = resolved_rule_set.lower()
    if resolved_rule_set not in {"lint", "style", "all"}:
        resolved_rule_set = "all"
    resolved_output_format = _resolve_str_option(
        output_format, defaults.get("output_format"), "text"
    ).lower()
    resolved_fix = _resolve_bool_option(fix, defaults.get("fix"), False)
    resolved_unsafe = _resolve_bool_option(
        unsafe_fixes, defaults.get("unsafe_fixes"), False
    )
    resolved_generate_baseline = _resolve_bool_option(
        generate_baseline, defaults.get("generate_baseline"), False
    )
    resolved_baseline = baseline
    if resolved_baseline is None and isinstance(defaults.get("baseline"), str):
        resolved_baseline = defaults["baseline"]

    cfg = _make_config(
        line_length=line_length,
        indent_width=indent_width,
        keyword_case=keyword_case,
        end_keyword_form=end_keyword_form,
        no_normalize_operators=no_normalize_operators,
    )
    code = _run_check(
        files=files,
        stdin_filename=stdin_filename,
        select=resolved_select,
        ignore=resolved_ignore,
        rule_set=resolved_rule_set,
        output_format=resolved_output_format,
        cfg=cfg,
        fix=resolved_fix,
        unsafe_fixes=resolved_unsafe,
        baseline=resolved_baseline,
        generate_baseline=resolved_generate_baseline,
    )
    raise click.exceptions.Exit(code)
