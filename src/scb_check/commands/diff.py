"""Implement the `scb-check diff` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer

from scb_check.config import load_config
from scb_check.logging import configure_logging
from scb_check.pipeline import analyze_diff
from scb_check.reporting.churn import compute_diff_report
from scb_check.reporting.churn import render_diff_report


def diff(
    tree_a: Annotated[Path, typer.Argument(help="Earlier source tree directory.")],
    tree_b: Annotated[Path, typer.Argument(help="Later source tree directory.")],
    *,
    output_format: Annotated[
        Literal["human", "json"],
        typer.Option("--output-format", help="Choose human or JSON output."),
    ] = "human",
    include_all: Annotated[
        bool,
        typer.Option("--include-all", help="Include gitignored files in both trees."),
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
    """Compare two source trees and report SLOC churn."""
    configure_logging(verbosity)
    try:
        config = load_config(None, Path.cwd())
        tree_diff = analyze_diff(tree_a, tree_b, config, include_all=include_all)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if not tree_diff.files:
        typer.echo(
            f"no supported source files could be parsed in either tree: {tree_a}, {tree_b}",
            err=True,
        )
        raise typer.Exit(code=2)

    report = compute_diff_report(tree_diff)
    if output_format == "json":
        typer.echo(json.dumps(report, allow_nan=False))
    else:
        typer.echo(render_diff_report(report))
