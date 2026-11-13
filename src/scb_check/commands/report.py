"""Analyze ordered directories and atomically publish an offline HTML report."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import typer

from scb_check.commands.validation import ensure_files_parsed
from scb_check.config import load_config
from scb_check.logging import configure_logging
from scb_check.models import Report
from scb_check.pipeline import analyze
from scb_check.reporting.plot import render_trend_html
from scb_check.reporting.score import compute_report
from scb_check.reporting.trend import build_trend


def report(  # noqa: PLR0913
    paths: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="At least two source directories, in supplied order.",
        ),
    ],
    *,
    output: Annotated[
        Path, typer.Option("--output", help="HTML output path.")
    ] = Path("report.html"),
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit shared config path."),
    ] = None,
    include_all: Annotated[
        bool,
        typer.Option(
            "--include-all",
            help="Include gitignored files and normally suppressed findings in every input.",
        ),
    ] = False,
    disable_sg: Annotated[
        bool,
        typer.Option(
            "--disable-sg", help="Disable ast-grep analysis in every input."
        ),
    ] = False,
    verbosity: Annotated[
        int,
        typer.Option(
            "-v",
            "--verbosity",
            count=True,
            help="Increase logging detail: -v for info, -vv for debug.",
        ),
    ] = 0,
) -> None:
    """Plot every snapshot value and adjacent signed change in offline HTML."""
    configure_logging(verbosity)
    try:
        _validate_output(output)
        config = load_config(config_path, Path.cwd())

        def load_snapshot(path: Path) -> Report:
            result = analyze(
                path, config, include_all=include_all, disable_sg=disable_sg
            )
            ensure_files_parsed(result, path)
            return compute_report(result)

        html = render_trend_html(build_trend(tuple(paths), load_snapshot))
        _write_html(output, html)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Wrote {output.resolve()}")


def _validate_output(output: Path) -> None:
    if not output.parent.is_dir():
        raise ValueError(f"output parent does not exist: {output.parent}")
    if output.is_dir():
        raise ValueError(f"output is a directory: {output}")


def _write_html(output: Path, html: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
