"""Compose aligned full-report trends without source IO or analysis orchestration."""

from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

from scb_check.models import AlignedTrend
from scb_check.models import Report
from scb_check.models import SnapshotSeries
from scb_check.models import Trend
from scb_check.models import TrendSeries
from scb_check.reporting.comparison import compare_reports
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import report_unit
from scb_check.reporting.score import validate_report


def build_trend(
    paths: tuple[Path, ...], load_report: Callable[[Path], Report]
) -> Trend:
    """Load positional inputs as one unnamed series, preserving repetitions."""
    if len(paths) < 2:  # noqa: PLR2004 - positional comparisons require two inputs
        raise ValueError("require at least two paths")
    return build_aligned_trend(
        tuple(str(index + 1) for index in range(len(paths))),
        (SnapshotSeries("", paths),),
        load_report,
    ).trends[0]


def build_aligned_trend(
    steps: tuple[str, ...],
    sources: tuple[SnapshotSeries, ...],
    load_report: Callable[[Path], Report],
) -> AlignedTrend:
    """Align complete reports and compare only neighboring declared steps per series."""
    if not steps or len(set(steps)) != len(steps):
        raise ValueError("steps must be nonempty and unique")
    if not sources or any(
        len(source.paths) != len(steps) for source in sources
    ):
        raise ValueError("series must align with declared steps")
    if len({source.name for source in sources}) != len(sources):
        raise ValueError("series names must be unique")
    snapshots = tuple(
        tuple(
            None if path is None else _load_snapshot(path, load_report)
            for path in source.paths
        )
        for source in sources
    )
    fields = tuple(
        (group, field)
        for group, declared in REPORT_UNITS.items()
        for field in (
            *declared,
            *sorted(
                {
                    field
                    for run in snapshots
                    for snapshot in run
                    if snapshot is not None
                    for field in snapshot[group]
                }
                - declared.keys()
            ),
        )
    )
    trends = []
    for source, reports in zip(sources, snapshots, strict=True):
        comparisons = (
            None,
            *(
                None
                if before is None or after is None
                else compare_reports(before, after)
                for before, after in pairwise(reports)
            ),
        )
        series = tuple(
            TrendSeries(
                metric=f"{group}.{field}",
                unit=report_unit(group, field),
                values=tuple(
                    None if report is None else report[group].get(field)
                    for report in reports
                ),
                differences=tuple(
                    None if report is None else report[group].get(field)
                    for report in comparisons
                ),
            )
            for group, field in fields
        )
        trends.append(
            Trend(source.paths, series, reports, comparisons, source.name)
        )
    return AlignedTrend(steps, tuple(trends))


def _load_snapshot(path: Path, load_report: Callable[[Path], Report]) -> Report:
    report = load_report(path)
    validate_report(report)
    # Library loaders may return mutable mappings; retain independent read-only context.
    return MappingProxyType(
        {
            group: MappingProxyType(dict(fields))
            for group, fields in report.items()
        }
    )
