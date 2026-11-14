"""Render library-neutral trend data with packaged visualization assets."""

import re
from dataclasses import dataclass
from importlib import resources

from jinja2 import Environment
from jinja2 import PackageLoader
from jinja2 import StrictUndefined
from markupsafe import Markup

from scb_check.models import AlignedTrend
from scb_check.models import Trend
from scb_check.models import TrendSeries
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import serialize_report

_SCRIPT_END = re.compile(r"</script", flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Plot:
    id: str
    title: str
    unit: str
    all_unavailable: bool


@dataclass(frozen=True, slots=True)
class _Section:
    metric: str
    plots: tuple[_Plot, ...]


@dataclass(frozen=True, slots=True)
class _Group:
    name: str
    sections: tuple[_Section, ...]


def render_trend_html(trend: Trend | AlignedTrend) -> str:
    """Produce self-contained HTML; user data is escaped in markup and JSON."""
    environment = Environment(
        loader=PackageLoader("scb_check.reporting", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    if isinstance(trend, Trend):
        labels = tuple(
            f"{index + 1}: {path.name if path is not None else 'missing'}"
            for index, path in enumerate(trend.paths)
        )
        trend = AlignedTrend(labels, (trend,))
    payload = {
        "labels": trend.steps,
        "runs": tuple(
            {
                "name": run.name,
                "paths": tuple(
                    None if path is None else str(path) for path in run.paths
                ),
                "series": tuple(
                    _series_payload(series) for series in run.series
                ),
                "snapshots": tuple(
                    None if report is None else serialize_report(report)
                    for report in run.snapshots
                ),
                "comparisons": tuple(
                    None if report is None else serialize_report(report)
                    for report in run.comparisons
                ),
            }
            for run in trend.trends
        ),
        "mean": tuple(
            {
                **_series_payload(series),
                "contributors": series.contributors,
                "change_contributors": series.change_contributors,
            }
            for series in trend.mean
        ),
        "units": {
            group: dict(fields) for group, fields in REPORT_UNITS.items()
        },
    }
    sections_by_group: dict[str, list[_Section]] = {}
    for index, series in enumerate(trend.trends[0].series):
        group = series.metric.partition(".")[0]
        displayed = tuple(run.series[index] for run in trend.trends)
        if trend.mean:
            displayed = (*displayed, trend.mean[index])
        sections_by_group.setdefault(group, []).append(
            _prepare_section(index, displayed)
        )
    groups = tuple(
        _Group(name, tuple(sections))
        for name, sections in sections_by_group.items()
    )
    return environment.get_template("report.html.jinja").render(
        title="Snapshot metrics",
        groups=groups,
        metric_count=len(trend.trends[0].series),
        payload=payload,
        plotly_js=_bundled_script("vendor/plotly-basic.min.js"),
        report_js=_bundled_script("plot.js"),
        plotly_license=resources.files("scb_check.reporting")
        .joinpath("static/vendor/LICENSE.plotly.txt")
        .read_text("utf-8"),
    )


def _series_payload(series: TrendSeries) -> dict[str, object]:
    return {
        "metric": series.metric,
        "unit": series.unit,
        "values": series.values,
        "differences": series.differences,
    }


def _prepare_section(
    index: int,
    displayed: tuple[TrendSeries, ...],
) -> _Section:
    series = displayed[0]
    plots = []
    for difference in (False, True):
        measurements = tuple(
            value
            for item in displayed
            for value in (item.differences if difference else item.values)
        )
        unit = (
            ("percentage points" if difference else "percent")
            if series.unit == "fraction"
            else series.unit
        )
        plots.append(
            _Plot(
                id=f"plot-{index}-{int(difference)}",
                title="Changes from previous" if difference else "Values",
                unit=unit,
                all_unavailable=all(value is None for value in measurements),
            )
        )
    return _Section(
        series.metric,
        tuple(plots),
    )


def _bundled_script(relative_path: str) -> Markup:
    source = (
        resources.files("scb_check.reporting")
        .joinpath("static", relative_path)
        .read_text("utf-8")
    )
    # Only fixed packaged scripts are trusted. HTML's script parser ignores JS string boundaries.
    return Markup(  # noqa: S704 - fixed packaged assets only
        _SCRIPT_END.sub(lambda match: r"<\/" + match.group()[2:], source)
    )
