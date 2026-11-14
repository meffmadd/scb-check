import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

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
    report["ric"]["partial_ratio_mean"] = 0.5
    paths = (Path("/a/same"), Path("/b/same"))
    trend = build_trend(paths, lambda _path: report)
    monkeypatch.chdir(tmp_path)
    html = render_trend_html(trend)
    page = ReportPage(html)
    text = " ".join(page.cells)

    assert page.payload["runs"][0]["paths"] == [str(path) for path in paths]
    assert page.payload["labels"] == ["1: same", "2: same"]
    assert page.payload["runs"][0]["snapshots"] == [report, report]
    assert page.payload["runs"][0]["comparisons"][0] is None
    assert len(page.plot_ids) == len(trend.series) * 2
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
    }
    assert "Values (percent)" in text
    assert "Changes from previous (percentage points)" in text
    assert "Values (mass)" in text
    assert "Values (ratio)" in text
    assert "no previous snapshot" in text
    assert "unavailable" in text
    assert "All measurements unavailable" in text
    assert len(page.scripts) == 3
    assert all("src" not in script for script in page.scripts)
    assert "Plotly.js license" in text
    assert "Copyright" in text
    assert render_trend_html(trend) == html


def test_metric_groups_are_native_collapsed_disclosures_in_report_order() -> (
    None
):
    """Every plot belongs to exactly one collapsible top-level metric group."""
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_trend((Path("a"), Path("b")), lambda _path: report)
    page = ReportPage(render_trend_html(trend))

    assert tuple(page.groups) == tuple(report)
    assert all("open" not in attrs for attrs in page.groups.values())
    assert page.group_plots["syntax"] == [
        f"plot-{index}-{difference}"
        for index, series in enumerate(trend.series)
        if series.metric.startswith("syntax.")
        for difference in (0, 1)
    ]
    assert [
        plot for plots in page.group_plots.values() for plot in plots
    ] == page.plot_ids


def test_multiseries_payload_keeps_steps_means_and_gaps() -> None:
    """Multiple lines share declared steps while retaining sparse measurements."""
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_aligned_trend(
        ("3", "1", "2"),
        (
            SnapshotSeries("<problem>", (Path("a"), None, Path("a"))),
            SnapshotSeries("other", (Path("b"), Path("b"), Path("b"))),
        ),
        lambda _path: report,
        aggregate="mean",
    )
    page = ReportPage(render_trend_html(trend))
    assert page.payload["labels"] == ["3", "1", "2"]
    assert [run["name"] for run in page.payload["runs"]] == [
        "<problem>",
        "other",
    ]
    assert page.payload["runs"][0]["paths"] == ["a", None, "a"]
    assert page.payload["mean"][0]["contributors"] == [2, 1, 2]
    assert page.inputs == []
    assert len(page.plot_ids) == len(trend.trends[0].series) * 2


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
