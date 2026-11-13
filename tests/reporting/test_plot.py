import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from scb_check.models import AnalysisResult
from scb_check.models import Flags
from scb_check.reporting.plot import render_trend_html
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import serialize_report
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
        self.payload: dict[str, Any] = {}
        self.active_script = False
        self.feed(html)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Collect accessible chart containers, table cells and embedded JSON."""
        attributes = dict(attrs)
        if tag == "script":
            self.scripts.append(attributes)
            self.active_script = attributes.get("id") == "report-data"
        if tag == "div" and attributes.get("role") == "img":
            assert attributes.get("aria-labelledby")
            self.plot_ids.append(str(attributes["id"]))
        if tag == "table":
            self.tables += 1

    def handle_endtag(self, tag: str) -> None:
        """Stop treating script contents as JSON at the script boundary."""
        if tag == "script":
            self.active_script = False

    def handle_data(self, data: str) -> None:
        """Decode raw numerical payload and retain readable page content."""
        if self.active_script:
            self.payload = json.loads(data)
        else:
            self.cells.append(data)


def test_offline_html_has_every_metric_both_plots_raw_context_and_readable_tables(
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

    assert page.payload["paths"] == [str(path) for path in paths]
    assert page.payload["labels"] == ["1: same", "2: same"]
    assert page.payload["snapshots"] == [report, report]
    assert page.payload["comparisons"][0] is None
    assert len(page.plot_ids) == len(trend.series) * 2 == page.tables
    assert len(set(page.plot_ids)) == len(page.plot_ids)
    assert page.payload["series"][0] == {
        "metric": "verbosity.score",
        "unit": "fraction",
        "values": [0.125, 0.125],
        "differences": [None, 0.0],
    }
    assert "12.5%" in text
    assert "+0 percentage points" in text
    assert "2.5 mass" in text
    assert "0.5 ratio" in text
    assert "no previous snapshot" in text
    assert "unavailable" in text
    assert "All measurements unavailable" in text
    assert len(page.scripts) == 3
    assert all("src" not in script for script in page.scripts)
    assert "Plotly.js license" in text
    assert "Copyright" in text
    assert render_trend_html(trend) == html


def test_untrusted_paths_round_trip_without_script_or_markup_injection() -> (
    None
):
    """HTML and JSON escaping preserve hostile path text without executable nodes."""
    path = Path('/untrusted/</script><script>alert("x")</script>& café')
    report = compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    trend = build_trend((path, path), lambda _path: report)
    page = ReportPage(render_trend_html(trend))
    assert len(page.scripts) == 3
    assert page.payload["paths"] == [str(path), str(path)]
    assert str(path) in " ".join(page.cells)
