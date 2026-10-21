"""Shared validation at the CLI command boundary."""

from __future__ import annotations

from pathlib import Path

import typer

from scb_check.models import AnalysisResult


def ensure_files_parsed(result: AnalysisResult, path: Path) -> None:
    """Reject unavailable analyses while accepting parsed zero-SLOC files."""
    if not result.flags.lines.total_loc_by_file:
        typer.echo(
            f"no supported source files could be parsed at {path}",
            err=True,
        )
        raise typer.Exit(code=2)
