"""Command-line interface for sable."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .formatter import DEFAULT_CONFIG, FormatConfig, format_source


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


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version")
@click.argument("files", nargs=-1, type=click.Path(exists=True, path_type=Path))
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
def main(
    files: tuple[Path, ...],
    check: bool,
    diff: bool,
    line_length: int,
    indent_width: int,
    keyword_case: str,
    end_keyword_form: str,
    no_normalize_operators: bool,
    stdin_filename: str | None,
) -> None:
    """Sable: an opinionated Fortran formatter.

    Format FILES in place. Reads from stdin if no FILES are given.

    Examples:

        sable my_module.f90
        sable --check src/**/*.f90
        cat code.f90 | sable -
    """
    cfg = _make_config(
        line_length=line_length,
        indent_width=indent_width,
        keyword_case=keyword_case,
        end_keyword_form=end_keyword_form,
        no_normalize_operators=no_normalize_operators,
    )

    sources: list[tuple[str, Path | None]] = []

    if not files:
        # Read from stdin
        source = sys.stdin.read()
        path = Path(stdin_filename) if stdin_filename else None
        sources.append((source, path))
    else:
        for p in files:
            if str(p) == "-":
                source = sys.stdin.read()
                path = Path(stdin_filename) if stdin_filename else None
            else:
                source = p.read_text(encoding="utf-8")
                path = p
            sources.append((source, path))

    any_changed = False
    exit_code = 0

    for source, path in sources:
        label = str(path) if path else "<stdin>"
        try:
            formatted = format_source(source, cfg)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"error: {label}: {exc}", err=True)
            exit_code = 123
            continue

        changed = formatted != source

        if diff:
            if changed:
                import difflib
                original_lines = source.splitlines(keepends=True)
                formatted_lines = formatted.splitlines(keepends=True)
                delta = difflib.unified_diff(
                    original_lines,
                    formatted_lines,
                    fromfile=f"a/{label}",
                    tofile=f"b/{label}",
                )
                click.echo("".join(delta), nl=False)
        elif check:
            if changed:
                click.echo(f"would reformat {label}")
                any_changed = True
        else:
            if path and str(path) != "-":
                if changed:
                    path.write_text(formatted, encoding="utf-8")
                    click.echo(f"reformatted {label}")
                else:
                    click.echo(f"{label} already formatted")
            else:
                # Stdin mode: write to stdout
                click.echo(formatted, nl=False)

    if check and any_changed:
        exit_code = 1

    sys.exit(exit_code)
