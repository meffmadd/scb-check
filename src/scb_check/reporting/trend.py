"""Build ordered full-report series without source IO or analysis orchestration."""

from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

from scb_check.models import Report
from scb_check.models import Trend
from scb_check.models import TrendSeries
from scb_check.reporting.comparison import compare_reports
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import report_unit
from scb_check.reporting.score import validate_report


def build_trend(
    paths: tuple[Path, ...], load_report: Callable[[Path], Report]
) -> Trend:
    """Load each position once and compare adjacent snapshots in supplied order."""
    if len(paths) < 2:  # noqa: PLR2004 - a comparison requires two snapshots
        raise ValueError("require at least two paths")
    snapshots: list[Report] = []
    for path in paths:
        report = load_report(path)
        validate_report(report)
        # Library loaders may return mutable dictionaries; retain independent read-only context.
        snapshots.append(
            MappingProxyType(
                {
                    group: MappingProxyType(dict(fields))
                    for group, fields in report.items()
                }
            )
        )
    comparisons = (
        None,
        *(
            compare_reports(earlier, later)
            for earlier, later in pairwise(snapshots)
        ),
    )
    series = []
    for group, declared in REPORT_UNITS.items():
        observed = {
            field for snapshot in snapshots for field in snapshot[group]
        }
        series.extend(
            TrendSeries(
                metric=f"{group}.{field}",
                unit=report_unit(group, field),
                values=tuple(
                    snapshot[group].get(field) for snapshot in snapshots
                ),
                differences=tuple(
                    None if diff is None else diff[group].get(field)
                    for diff in comparisons
                ),
            )
            for field in (*declared, *sorted(observed - declared.keys()))
        )
    return Trend(paths, tuple(series), tuple(snapshots), comparisons)
