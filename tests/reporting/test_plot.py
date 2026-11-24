import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from scb_check.models import AlignedTrend
from scb_check.models import AnalysisResult
from scb_check.models import Flags
from scb_check.models import SnapshotSeries
from scb_check.reporting.plot import render_trend_html
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import serialize_report
from scb_check.reporting.trend import build_aligned_trend
from scb_check.reporting.trend import build_trend
from scb_check.tree_walking.models import ProjectIR


class ReportPage(HTMLParser):
    """Read semantic HTML output without depending on layout or whitespace."""

    def __init__(self, html: str) -> None:
        """Parse a complete generated report."""
        super().__init__(convert_charrefs=True)
        self.scripts: list[dict[str, str | None]] = []
        self.plot_ids: list[str] = []
        self.cells: list[str] = []
        self.tables = 0
        self.inputs: list[dict[str, str | None]] = []
        self.groups: dict[str, dict[str, str | None]] = {}
        self.group_plots: dict[str, list[str]] = {}
        self.active_group: str | None = None
        self.source_details: dict[str, str | None] | None = None
        self.payload: dict[str, Any] = {}
        self.active_script = False
        self.feed(html)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Collect accessible charts, source-directory disclosure and embedded JSON."""
        attributes = dict(attrs)
        if tag == "script":
            self.scripts.append(attributes)
            self.active_script = attributes.get("id") == "report-data"
        if tag == "div" and attributes.get("role") == "img":
            assert attributes.get("aria-labelledby")
            self.plot_ids.append(str(attributes["id"]))
            if self.active_group is not None:
                self.group_plots[self.active_group].append(
                    str(attributes["id"])
                )
        if tag == "table":
            self.tables += 1
        if tag == "input":
            self.inputs.append(attributes)
        if tag == "details" and attributes.get("id") == "source-directories":
            self.source_details = attributes
        if (
            tag == "details"
            and (group_id := attributes.get("id", ""))
            and group_id.startswith("metric-group-")
        ):
            self.active_group = group_id.removeprefix("metric-group-")
            self.groups[self.active_group] = attributes
            self.group_plots[self.active_group] = []

    def handle_endtag(self, tag: str) -> None:
        """Stop treating script contents as JSON at the script boundary."""
        if tag == "script":
            self.active_script = False
        if tag == "details":
            self.active_group = None

    def handle_data(self, data: str) -> None:
        """Decode raw numerical payload and retain readable page content."""
        if self.active_script:
            self.payload = json.loads(data)
        else:
            self.cells.append(data)


def test_offline_html_prioritizes_plots_with_paths_disclosed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package resources render independently of cwd and preserve units and unknowns."""
    report = serialize_report(
        compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    )
    report["verbosity"]["score"] = 0.125
    report["erosion"]["total_mass"] = 2.5
    report["ric"]["mean"] = 0.5
    paths = (Path("/a/same"), Path("/b/same"))
    trend = build_trend(paths, lambda _path: report)
    monkeypatch.chdir(tmp_path)
    html = render_trend_html(trend, full=True)
    page = ReportPage(html)
    text = " ".join(page.cells)

    assert page.payload["runs"][0]["paths"] == [str(path) for path in paths]
    assert page.payload["labels"] == ["1: same", "2: same"]
    assert page.payload["runs"][0]["snapshots"] == [report, report]
    assert page.payload["runs"][0]["comparisons"][0] is None
    assert len(page.plot_ids) == len(trend.series)
    assert page.tables == 0
    assert page.inputs == []
    assert page.source_details is not None
    assert "open" not in page.source_details
    for path in paths:
        assert page.cells.count(str(path)) == 1
    assert len(set(page.plot_ids)) == len(page.plot_ids)
    assert page.payload["runs"][0]["series"][0] == {
        "metric": "verbosity.score",
        "unit": "fraction",
        "values": [0.125, 0.125],
        "differences": [None, 0.0],
        "tau": None,
    }
    assert "Values (percent)" in text
    assert "Changes from previous" not in text
    assert "Values (mass)" in text
    assert "Values (ratio)" in text
    assert "unavailable" in text
    assert "All measurements unavailable" in text
    assert len(page.scripts) == 3
    assert all("src" not in script for script in page.scripts)
    assert "Plotly.js license" in text
    assert "Copyright" in text
    assert render_trend_html(trend, full=True) == html


@pytest.mark.parametrize("full", [False, True])
def test_metric_groups_are_native_collapsed_disclosures_in_report_order(
    *, full: bool
) -> None:
    """Every plot belongs to one collapsible group; headline-free syntax is full-only."""
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_trend((Path("a"), Path("b")), lambda _path: report)
    page = ReportPage(render_trend_html(trend, full=full))
    plotted = [series["metric"] for series in page.payload["runs"][0]["series"]]

    assert tuple(page.groups) == tuple(
        group for group in report if full or group != "syntax"
    )
    assert all("open" not in attrs for attrs in page.groups.values())
    assert [
        plot for plots in page.group_plots.values() for plot in plots
    ] == page.plot_ids
    assert len(page.plot_ids) == len(plotted)
    if full:
        assert plotted == [series.metric for series in trend.series]
        assert page.group_plots["syntax"] == [
            f"plot-{index}"
            for index, metric in enumerate(plotted)
            if metric.startswith("syntax.")
        ]
    else:
        assert page.group_plots["verbosity"] == ["plot-0"]
        assert {"verbosity.total_loc", "cbo.sum"}.isdisjoint(plotted)
        assert page.payload["runs"][0]["snapshots"] == [
            serialize_report(report)
        ] * 2


def test_multiseries_payload_keeps_steps_and_gaps() -> None:
    """Multiple lines share declared steps while retaining sparse measurements."""
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_aligned_trend(
        ("3", "1", "2"),
        (
            SnapshotSeries("<problem>", (Path("a"), None, Path("a"))),
            SnapshotSeries("other", (Path("b"), Path("b"), Path("b"))),
        ),
        lambda _path: report,
    )
    page = ReportPage(render_trend_html(trend))
    assert page.payload["labels"] == ["3", "1", "2"]
    assert [run["name"] for run in page.payload["runs"]] == [
        "<problem>",
        "other",
    ]
    assert page.payload["runs"][0]["paths"] == ["a", None, "a"]
    assert set(page.payload) == {"labels", "runs", "summaries", "units"}
    assert page.payload["runs"][0]["series"][0]["values"] == [0, None, 0]
    assert page.inputs == []
    problem, other = (
        [series["metric"] for series in run["series"]]
        for run in page.payload["runs"]
    )
    assert problem == other
    assert len(page.plot_ids) == len(problem)


def _loc_trend(observations: dict[str, tuple[int | None, ...]]) -> AlignedTrend:
    """Build one named series per entry, varying only `verbosity.total_loc`."""
    reports = {}
    runs = []
    for name, values in observations.items():
        paths = []
        for index, value in enumerate(values):
            path = Path(f"{name}-{index}")
            report = serialize_report(
                compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
            )
            report["verbosity"]["total_loc"] = value
            reports[path] = report
            paths.append(path)
        runs.append(SnapshotSeries(name, tuple(paths)))
    steps = tuple(str(index) for index in range(len(runs[0].paths)))
    return build_aligned_trend(steps, tuple(runs), reports.__getitem__)


def _loc_coefficients(page: ReportPage) -> list[float | None]:
    return [
        series["tau"]
        for run in page.payload["runs"]
        for series in run["series"]
        if series["metric"] == "verbosity.total_loc"
    ]


def test_kendall_coefficients_and_summaries_weight_series_equally() -> None:
    """Sparse and tied series contribute equally; only flat series adjust the mean."""
    trend = _loc_trend(
        {
            "up": (1, 2, 3, 4),
            "down": (4, None, None, 1),
            "tied": (1, 1, 2, None),
            "constant": (2, 2, 2, 2),
            "short": (None, None, 1, None),
        }
    )
    page = ReportPage(render_trend_html(trend, full=True))
    tied = 0.8164965809
    assert _loc_coefficients(page) == [
        pytest.approx(1),
        pytest.approx(-1),
        pytest.approx(tied),
        None,
        None,
    ]
    assert page.payload["summaries"]["verbosity.total_loc"] == {
        "series": 5,
        "contributors": 3,
        "mean": pytest.approx(tied / 3),
        "median": pytest.approx(tied),
        "flat_adjusted_contributors": 4,
        "flat_adjusted_mean": pytest.approx(tied / 4),
        "flat_adjusted_median": pytest.approx(tied / 2),
    }
    opposing = ReportPage(
        render_trend_html(
            AlignedTrend(trend.steps, trend.trends[:2]), full=True
        )
    )
    summary = opposing.payload["summaries"]["verbosity.total_loc"]
    assert summary["contributors"] == 2
    assert summary["mean"] == pytest.approx(0)
    assert summary["median"] == pytest.approx(0)


def test_single_series_shows_its_coefficient_instead_of_a_mean() -> None:
    """One series is labelled τ, whether its coefficient is defined or not."""
    rising = ReportPage(render_trend_html(_loc_trend({"": (1, 2, 3)}), full=True))
    assert _loc_coefficients(rising) == [pytest.approx(1)]
    assert "Values (lines) · τ: 1.00" in " ".join(rising.cells)
    constant = ReportPage(render_trend_html(_loc_trend({"": (2, 2, 2)}), full=True))
    assert _loc_coefficients(constant) == [None]
    assert "Values (lines) · τ: N/A" in " ".join(constant.cells)


def test_summaries_without_defined_coefficients_report_no_mean() -> None:
    """Undefined series never count as zero unless they are flat."""
    flat_and_short = ReportPage(
        render_trend_html(_loc_trend({"flat": (2, 2), "short": (None, 1)}), full=True)
    )
    assert flat_and_short.payload["summaries"]["verbosity.total_loc"] == {
        "series": 2,
        "contributors": 0,
        "mean": None,
        "median": None,
        "flat_adjusted_contributors": 1,
        "flat_adjusted_mean": 0,
        "flat_adjusted_median": 0,
    }
    assert "τ (0/2 series): mean N/A" in " ".join(flat_and_short.cells)
    short = ReportPage(
        render_trend_html(_loc_trend({"a": (None, 1), "b": (None, 1)}), full=True)
    )
    summary = short.payload["summaries"]["verbosity.total_loc"]
    assert summary["flat_adjusted_contributors"] == 0
    assert summary["flat_adjusted_mean"] is None
    assert summary["flat_adjusted_median"] is None


def test_untrusted_paths_round_trip_without_script_or_markup_injection() -> (
    None
):
    """HTML and JSON escaping preserve hostile path text without executable nodes."""
    path = Path('/untrusted/</script><script>alert("x")</script>& café')
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_trend((path, path), lambda _path: report)
    page = ReportPage(render_trend_html(trend))
    assert len(page.scripts) == 3
    assert page.payload["runs"][0]["paths"] == [str(path), str(path)]
    assert str(path) in " ".join(page.cells)
