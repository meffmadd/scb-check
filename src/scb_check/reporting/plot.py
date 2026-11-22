"""Render library-neutral trend data with packaged visualization assets."""

import math
import re
from dataclasses import dataclass
from importlib import resources
from statistics import median

from jinja2 import Environment
from jinja2 import PackageLoader
from jinja2 import StrictUndefined
from markupsafe import Markup
from scipy.stats import kendalltau

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
    summary: str | None


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
    coefficients = tuple(
        tuple(_kendall_tau(series) for series in run.series)
        for run in trend.trends
    )
    payload = {
        "labels": trend.steps,
        "runs": tuple(
            {
                "name": run.name,
                "paths": tuple(
                    None if path is None else str(path) for path in run.paths
                ),
                "series": tuple(
                    _series_payload(series, tau)
                    for series, tau in zip(
                        run.series, run_coefficients, strict=True
                    )
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
            for run, run_coefficients in zip(
                trend.trends, coefficients, strict=True
            )
        ),
        "units": {
            group: dict(fields) for group, fields in REPORT_UNITS.items()
        },
    }
    sections_by_group: dict[str, list[_Section]] = {}
    for index, series in enumerate(trend.trends[0].series):
        group = series.metric.partition(".")[0]
        displayed = tuple(run.series[index] for run in trend.trends)
        sections_by_group.setdefault(group, []).append(
            _prepare_section(
                index, displayed, tuple(row[index] for row in coefficients)
            )
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


def _kendall_tau(series: TrendSeries) -> float | None:
    observations = [
        (index, value)
        for index, value in enumerate(series.values)
        if value is not None
    ]
    if len(observations) < 2:  # noqa: PLR2004 - correlation requires two observations
        return None
    steps, values = zip(*observations, strict=True)
    if len(set(values)) == 1:
        return None
    statistic = float(kendalltau(steps, values, method="auto").statistic)
    return statistic if math.isfinite(statistic) else None


def _series_payload(
    series: TrendSeries, tau: float | None
) -> dict[str, object]:
    return {
        "metric": series.metric,
        "unit": series.unit,
        "values": series.values,
        "differences": series.differences,
        "tau": tau,
    }


def _prepare_section(
    index: int,
    displayed: tuple[TrendSeries, ...],
    coefficients: tuple[float | None, ...],
) -> _Section:
    series = displayed[0]
    valid = tuple(value for value in coefficients if value is not None)
    value = f"{sum(valid) / len(valid):.2f}" if valid else "N/A"
    median_value = f"{median(valid):.2f}" if valid else "N/A"
    flat_count = sum(
        1
        for item, coefficient in zip(displayed, coefficients, strict=True)
        if coefficient is None
        and len(observations := tuple(v for v in item.values if v is not None)) >= 2  # noqa: PLR2004 - trend requires two observations
        and len(set(observations)) == 1
    )
    adjusted_count = len(valid) + flat_count
    adjusted = f"{sum(valid) / adjusted_count:.2f}" if adjusted_count else "N/A"
    summary = (
        f"Mean τ: {value} · Median τ: {median_value} "
        f"({len(valid)}/{len(coefficients)} contributors) · "
        f"Flat-adjusted mean τ: {adjusted} "
        f"({adjusted_count}/{len(coefficients)} contributors)"
        if len(coefficients) > 1
        else f"τ: {value}"
    )
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
                summary=None if difference else summary,
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
