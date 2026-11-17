"""Analyze ordered directories and atomically publish an offline HTML report."""

import tomllib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import typer

from scb_check.commands.validation import ensure_files_parsed
from scb_check.config import load_config
from scb_check.logging import configure_logging
from scb_check.models import Report
from scb_check.models import SnapshotSeries
from scb_check.pipeline import analyze
from scb_check.reporting.plot import render_trend_html
from scb_check.reporting.score import compute_report
from scb_check.reporting.trend import build_aligned_trend


def report(  # noqa: PLR0913
    paths: Annotated[
        list[Path] | None,
        typer.Argument(
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="At least two source directories, in supplied order.",
        ),
    ] = None,
    *,
    manifest: Annotated[
        Path | None,
        typer.Option(
            "--manifest",
            help="TOML manifest with named series and ordered steps.",
        ),
    ] = None,
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
        steps, sources = _load_inputs(tuple(paths or ()), manifest)
        _validate_output(output)
        config = load_config(config_path, Path.cwd())

        def load_snapshot(path: Path) -> Report:
            result = analyze(
                path, config, include_all=include_all, disable_sg=disable_sg
            )
            ensure_files_parsed(result, path)
            return compute_report(result)

        trend = build_aligned_trend(steps, sources, load_snapshot)
        html = render_trend_html(trend)
        _write_html(output, html)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Wrote {output.resolve()}")


def _load_inputs(
    paths: tuple[Path, ...],
    manifest: Path | None,
) -> tuple[tuple[str, ...], tuple[SnapshotSeries, ...]]:
    if manifest is not None:
        if paths:
            raise ValueError("cannot combine positional paths with --manifest")
        return _load_manifest(manifest)
    if len(paths) < 2:  # noqa: PLR2004 - positional comparisons require two inputs
        raise ValueError("require at least two paths or --manifest")
    return (
        tuple(f"{index + 1}: {path.name}" for index, path in enumerate(paths)),
        (SnapshotSeries("", paths),),
    )


def _load_manifest(
    manifest: Path,
) -> tuple[tuple[str, ...], tuple[SnapshotSeries, ...]]:
    with manifest.open("rb") as stream:
        data = tomllib.load(stream)
    if set(data) != {"steps", "series"}:
        raise ValueError("manifest requires exactly 'steps' and 'series'")
    steps = _manifest_steps(data["steps"])
    series = data["series"]
    if not isinstance(series, dict) or not series:
        raise ValueError("manifest series must be a nonempty table")
    sources = []
    for name, entries in series.items():
        if not name or not isinstance(entries, dict):
            raise ValueError("each series must be a named table of step paths")
        sources.append(_manifest_series(name, entries, steps, manifest.parent))
    return steps, tuple(sources)


def _manifest_steps(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("manifest steps must be nonempty, unique strings")
    steps: list[str] = []
    for step in value:
        if not isinstance(step, str) or not step:
            raise ValueError("manifest steps must be nonempty, unique strings")
        steps.append(step)
    if len(set(steps)) != len(steps):
        raise ValueError("manifest steps must be nonempty, unique strings")
    return tuple(steps)


def _manifest_series(
    name: str,
    entries: dict[str, object],
    steps: tuple[str, ...],
    base: Path,
) -> SnapshotSeries:
    if unknown := entries.keys() - set(steps):
        raise ValueError(
            f"series {name!r} references undeclared steps: {sorted(unknown)!r}"
        )
    paths: dict[str, Path] = {}
    for step in steps:
        if step not in entries:
            continue
        value = entries[step]
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"series {name!r} step {step!r} requires a nonempty directory path"
            )
        path = (base / value).resolve()
        if not path.is_dir():
            raise ValueError(
                f"invalid source directory for series {name!r} step {step!r}: {path}"
            )
        paths[step] = path
    return SnapshotSeries(name, tuple(paths.get(step) for step in steps))


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
