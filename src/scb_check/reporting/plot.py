"""Render library-neutral trend data with packaged visualization assets."""

import math
import re
from dataclasses import asdict
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
class _SeriesTrend:
    tau: float | None
    flat: bool


@dataclass(frozen=True, slots=True)
class _TauSummary:
    series: int
    contributors: int
    mean: float | None
    median: float | None
    flat_adjusted_contributors: int
    flat_adjusted_mean: float | None
    flat_adjusted_median: float | None


@dataclass(frozen=True, slots=True)
class _Section:
    metric: str
    plot_id: str
    unit: str
    all_unavailable: bool
    summary: str


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
    series_trends = tuple(
        tuple(_series_trend(series) for series in run.series)
        for run in trend.trends
    )
    summaries = tuple(
        _summarize(tuple(row[index] for row in series_trends))
        for index in range(len(trend.trends[0].series))
    )
    payload = _payload(trend, series_trends, summaries)
    groups = _groups(trend, summaries)
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


def _payload(
    trend: AlignedTrend,
    series_trends: tuple[tuple[_SeriesTrend, ...], ...],
    summaries: tuple[_TauSummary, ...],
) -> dict[str, object]:
    return {
        "labels": trend.steps,
        "runs": tuple(
            _run_payload(run, run_trends)
            for run, run_trends in zip(trend.trends, series_trends, strict=True)
        ),
        "summaries": {
            series.metric: asdict(summary)
            for series, summary in zip(
                trend.trends[0].series, summaries, strict=True
            )
        },
        "units": {
            group: dict(fields) for group, fields in REPORT_UNITS.items()
        },
    }


def _run_payload(
    run: Trend, run_trends: tuple[_SeriesTrend, ...]
) -> dict[str, object]:
    return {
        "name": run.name,
        "paths": tuple(
            None if path is None else str(path) for path in run.paths
        ),
        "series": tuple(
            {
                "metric": series.metric,
                "unit": series.unit,
                "values": series.values,
                "differences": series.differences,
                "tau": series_trend.tau,
            }
            for series, series_trend in zip(run.series, run_trends, strict=True)
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


def _groups(
    trend: AlignedTrend, summaries: tuple[_TauSummary, ...]
) -> tuple[_Group, ...]:
    sections_by_group: dict[str, list[_Section]] = {}
    for index, series in enumerate(trend.trends[0].series):
        sections_by_group.setdefault(
            series.metric.partition(".")[0], []
        ).append(
            _Section(
                metric=series.metric,
                plot_id=f"plot-{index}",
                unit="percent" if series.unit == "fraction" else series.unit,
                all_unavailable=all(
                    value is None
                    for run in trend.trends
                    for value in run.series[index].values
                ),
                summary=_summary_text(summaries[index]),
            )
        )
    return tuple(
        _Group(name, tuple(sections))
        for name, sections in sections_by_group.items()
    )


def _series_trend(series: TrendSeries) -> _SeriesTrend:
    observed = tuple(value for value in series.values if value is not None)
    if len(observed) < 2:  # noqa: PLR2004 - correlation requires two observations
        return _SeriesTrend(tau=None, flat=False)
    if len(set(observed)) == 1:
        return _SeriesTrend(tau=None, flat=True)
    # Kendall τ depends only on order, so positions among the observed values
    # stand in for the declared steps that remain after omitting gaps.
    statistic = float(
        kendalltau(range(len(observed)), observed, method="auto").statistic
    )
    return _SeriesTrend(
        tau=statistic if math.isfinite(statistic) else None, flat=False
    )


def _summarize(series_trends: tuple[_SeriesTrend, ...]) -> _TauSummary:
    coefficients = tuple(
        item.tau for item in series_trends if item.tau is not None
    )
    # Flat series count as zero trend here; series too short to rank never do.
    flat_adjusted = coefficients + tuple(
        0.0 for item in series_trends if item.flat
    )
    return _TauSummary(
        series=len(series_trends),
        contributors=len(coefficients),
        mean=sum(coefficients) / len(coefficients) if coefficients else None,
        median=median(coefficients) if coefficients else None,
        flat_adjusted_contributors=len(flat_adjusted),
        flat_adjusted_mean=(
            sum(flat_adjusted) / len(flat_adjusted) if flat_adjusted else None
        ),
        flat_adjusted_median=median(flat_adjusted) if flat_adjusted else None,
    )


def _summary_text(summary: _TauSummary) -> str:
    def shown(coefficient: float | None) -> str:
        return "N/A" if coefficient is None else f"{coefficient:.2f}"

    if summary.series == 1:
        return f"τ: {shown(summary.mean)}"
    return (
        f"τ ({summary.contributors}/{summary.series} series): "
        f"mean {shown(summary.mean)}, median {shown(summary.median)} · "
        f"flat-adjusted ({summary.flat_adjusted_contributors}/{summary.series} series): "
        f"mean {shown(summary.flat_adjusted_mean)}, "
        f"median {shown(summary.flat_adjusted_median)}"
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
