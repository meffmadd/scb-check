"""Render library-neutral trend data and numerical tables with packaged assets."""

import re
from dataclasses import dataclass
from importlib import resources

from jinja2 import Environment
from jinja2 import PackageLoader
from jinja2 import StrictUndefined
from markupsafe import Markup

from scb_check.models import Trend
from scb_check.models import TrendSeries
from scb_check.reporting.formatting import format_measurement
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import serialize_report

_SCRIPT_END = re.compile(r"</script", flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Row:
    index: int
    path: str
    previous_path: str
    value_text: str


@dataclass(frozen=True, slots=True)
class _Plot:
    id: str
    title: str
    unit: str
    rows: tuple[_Row, ...]
    all_unavailable: bool


@dataclass(frozen=True, slots=True)
class _Section:
    metric: str
    plots: tuple[_Plot, ...]


def render_trend_html(trend: Trend) -> str:
    """Produce self-contained HTML; user data is escaped in markup and JSON."""
    environment = Environment(
        loader=PackageLoader("scb_check.reporting", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    payload = {
        "paths": tuple(str(path) for path in trend.paths),
        "labels": tuple(
            f"{index + 1}: {path.name}"
            for index, path in enumerate(trend.paths)
        ),
        "series": tuple(
            {
                "metric": series.metric,
                "unit": series.unit,
                "values": series.values,
                "differences": series.differences,
            }
            for series in trend.series
        ),
        "snapshots": tuple(
            serialize_report(report) for report in trend.snapshots
        ),
        "comparisons": tuple(
            None if report is None else serialize_report(report)
            for report in trend.comparisons
        ),
        "units": {
            group: dict(fields) for group, fields in REPORT_UNITS.items()
        },
    }
    return environment.get_template("report.html.jinja").render(
        title="Snapshot metrics",
        sections=tuple(
            _prepare_section(index, series, trend)
            for index, series in enumerate(trend.series)
        ),
        payload=payload,
        plotly_js=_bundled_script("vendor/plotly-basic.min.js"),
        report_js=_bundled_script("plot.js"),
        plotly_license=resources.files("scb_check.reporting")
        .joinpath("static/vendor/LICENSE.plotly.txt")
        .read_text("utf-8"),
    )


def _prepare_section(index: int, series: TrendSeries, trend: Trend) -> _Section:
    plots = []
    for difference, measurements in enumerate(
        (series.values, series.differences)
    ):
        unit = (
            ("percentage points" if difference else "percent")
            if series.unit == "fraction"
            else series.unit
        )
        rows = tuple(
            _Row(
                index=input_index + 1,
                path=str(path),
                previous_path=str(trend.paths[input_index - 1])
                if input_index
                else "no previous snapshot",
                value_text="no previous snapshot"
                if difference and input_index == 0
                else format_measurement(value, series.unit, difference=bool(difference)),
            )
            for input_index, (path, value) in enumerate(
                zip(trend.paths, measurements, strict=True)
            )
        )
        plots.append(
            _Plot(
                id=f"plot-{index}-{difference}",
                title="Changes from previous" if difference else "Values",
                unit=unit,
                rows=rows,
                all_unavailable=all(value is None for value in measurements),
            )
        )
    return _Section(series.metric, tuple(plots))


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
