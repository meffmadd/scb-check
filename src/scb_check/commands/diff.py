"""Implement the `scb-check diff` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer

from scb_check.commands.validation import ensure_files_parsed
from scb_check.config import load_config
from scb_check.logging import configure_logging
from scb_check.pipeline import analyze
from scb_check.reporting.comparison import compute_diff_report
from scb_check.reporting.comparison import render_comparison
from scb_check.reporting.score import serialize_report


def diff(  # noqa: PLR0913
    tree_a: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="Earlier source tree directory.",
        ),
    ],
    tree_b: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="Later source tree directory.",
        ),
    ],
    *,
    output_format: Annotated[
        Literal["human", "json"],
        typer.Option("--output-format", help="Choose human or JSON output."),
    ] = "human",
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit shared config path."),
    ] = None,
    include_all: Annotated[
        bool,
        typer.Option(
            "--include-all",
            help="Include gitignored files, ignored rule findings, lower-severity ast-grep findings, and boundary-suppressed ast-grep findings in both trees.",
        ),
    ] = False,
    disable_sg: Annotated[
        bool,
        typer.Option(
            "--disable-sg", help="Disable ast-grep analysis in both trees."
        ),
    ] = False,
    verbosity: Annotated[
        int,
        typer.Option(
            "-v",
            "--verbosity",
            count=True,
            help="Increase logging detail. -v enables info logs, -vv enables debug logs.",
        ),
    ] = 0,
) -> None:
    """Compare full snapshot metrics; deltas are later minus earlier, not churn."""
    configure_logging(verbosity)
    try:
        config = load_config(config_path, Path.cwd())
        analyses = []
        for tree in (tree_a, tree_b):
            result = analyze(
                tree, config, include_all=include_all, disable_sg=disable_sg
            )
            ensure_files_parsed(result, tree)
            analyses.append(result)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    reports = compute_diff_report(*analyses)
    context = {"tree_a": str(tree_a), "tree_b": str(tree_b)}
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    **context,
                    **{name: serialize_report(report) for name, report in reports.items()},
                },
                allow_nan=False,
            )
        )
    else:
        typer.echo(
            "\n".join(f"{name}: {value}" for name, value in context.items())
        )
        typer.echo(render_comparison(reports["before"], reports["after"], reports["diff"]))
