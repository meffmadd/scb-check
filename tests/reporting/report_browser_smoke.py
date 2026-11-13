"""Standalone Chromium acceptance; deliberately not collected by pytest.

From the checkout (Playwright is a tool, never a project dependency)::

    uv run --with playwright==1.51.0 python -m playwright install chromium
    uv run --with playwright==1.51.0 python tests/reporting/report_browser_smoke.py

The runner enforces that pin, generates reports through the public reporting
interfaces, opens temporary file URLs, blocks networking, and fails on attempted
HTTP(S), browser errors, or failed assertions. Browser installation needs network;
report generation and browser acceptance do not. No screenshot baselines.
"""

from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from sys import stdout
from tempfile import TemporaryDirectory
from typing import Any

from scb_check.models import AnalysisResult
from scb_check.models import Flags
from scb_check.models import Trend
from scb_check.reporting.plot import render_trend_html
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import serialize_report
from scb_check.reporting.trend import build_trend
from scb_check.tree_walking.models import ProjectIR

PLAYWRIGHT_VERSION = "1.51.0"


def representative_trend() -> Trend:
    """Cover hostile text, partial coverage, units, sparse data and identical inputs."""
    hostile = '</script><script>window.__injected=1</script><img src=x onerror="window.__injected=2">& café'
    paths = tuple(
        Path(f"/snapshots/{hostile}/{'long-directory-name-' * 3}{index}")
        for index in range(5)
    )
    paths = (paths[0].with_name(paths[0].name + '<img src=x onerror="window.__injected=3"> & café'), *paths[1:])
    reports = []
    for index in range(5):
        report = serialize_report(compute_report(AnalysisResult(Flags(), {}, ProjectIR())))
        report["verbosity"].update(
            score=(0.125, None, 0, None, 0.25)[index],
            total_loc=(3, 5, 2, 2, 2)[index],
        )
        report["erosion"]["total_mass"] = (2.5, 1.25, 1.25, 1.25, 1.25)[index]
        report["erosion"]["score"] = (0.25, 0.125, 0.125, 0.125, 0.125)[index]
        report["ric"].update(partial_ratio_mean=0.5, measured_pairs=2, unavailable_pairs=1)
        report["rfc"]["unavailable_classes"] = 3
        # A late language introduces snapshot gaps but signed zero-filled differences.
        if index == 4:
            report["syntax"]["python.node_count"] = 7
            report["syntax"]["python.tree_count"] = 1
        reports.append(report)
    return build_trend(paths, dict(zip(paths, reports, strict=True)).__getitem__)


def plot_id(trend: Trend, metric: str, *, difference: bool = False) -> str:
    """Locate a chart by metric rather than relying on canonical field positions."""
    index = next(index for index, series in enumerate(trend.series) if series.metric == metric)
    return f"plot-{index}-{int(difference)}"


def hover(page: Any, chart_id: str, marker: int) -> str:  # noqa: ANN401
    """Use actual mouse movement over a visible SVG point, not Plotly's hover API."""
    point = page.locator(f"#{chart_id} .scatterlayer .point").nth(marker)
    point.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    point.hover(force=True)
    label = page.locator(f"#{chart_id} .hoverlayer .hovertext")
    label.wait_for(state="visible")
    return label.text_content() or ""


def check_render(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Every metric renders both SVG charts with finite axes and no external assets."""
    expected = len(trend.series) * 2
    page.wait_for_function(
        "n => document.querySelectorAll('.metric-plot .main-svg').length >= n",
        arg=expected,
        timeout=120_000,
    )
    assert page.locator(".metric-plot.js-plotly-plot").count() == expected
    assert page.locator("table").count() == 0
    assert not page.locator("#source-directories").evaluate("element => element.open")
    assert page.locator("script[src], link[href], canvas, img, iframe").count() == 0
    assert page.locator("script").count() == 3
    assert page.evaluate("window.__injected === undefined")
    assert page.evaluate("Plotly.version") == "3.0.1"
    assert page.locator(".metric-plot .scatterlayer").count() == expected
    assert page.locator(".xtick text, .ytick text").evaluate_all(
        "ticks => ticks.every(t => !/^(NaN|[+-]?Infinity)$/.test(t.textContent))"
    )
    assert "Plot unavailable:" not in page.locator("body").inner_text()
    for series in trend.series:
        for difference in (False, True):
            chart = page.locator(f"#{plot_id(trend, series.metric, difference=difference)}")
            raw = series.differences if difference else series.values
            scale = 100 if series.unit == "fraction" else 1
            assert chart.evaluate("p => p.data[0].y") == [None if value is None else value * scale for value in raw]
            unit = ("percentage points" if difference else "percent") if series.unit == "fraction" else series.unit
            assert chart.locator(".ytitle").text_content() == unit


def check_hover(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Hover shows only the input label and the plotted measurement with its unit."""
    score = plot_id(trend, "verbosity.score")
    text = hover(page, score, 0)
    assert text == f"1: {trend.paths[0].name}Value: 12.5%", text
    assert str(trend.paths[0]) not in text
    assert page.locator(".hoverlayer script, .hoverlayer img, .hoverlayer a, .hoverlayer svg").count() == 0
    assert page.evaluate("window.__injected === undefined")

    count = plot_id(trend, "verbosity.total_loc", difference=True)
    text = hover(page, count, 1)
    assert text == f"3: {trend.paths[2].name}Change: -3 lines", text

    for metric, expected in (("erosion.total_mass", "2.5 mass"),
                             ("ric.partial_ratio_mean", "0.5 ratio")):
        text = hover(page, plot_id(trend, metric), 0)
        assert expected in text, text
        assert "50%" not in text, text
    text = hover(page, plot_id(trend, "rfc.unavailable_classes"), 0)
    assert text == f"1: {trend.paths[0].name}Value: 3 classes", text


def check_hostile_labels(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Hostile basenames remain literal hover text; full paths stay in the disclosure."""
    text = hover(page, plot_id(trend, "verbosity.score"), 0)
    assert page.locator(".hoverlayer script, .hoverlayer img, .hoverlayer a").count() == 0
    assert page.evaluate("window.__injected === undefined")
    assert trend.paths[0].name in text, text
    sources = page.locator("#source-directories")
    sources.locator("summary").click()
    assert sources.locator("li").all_text_contents() == [str(path) for path in trend.paths]
    assert sources.locator("script, img, a").count() == 0
    sources.locator("summary").click()


def check_gaps_and_units(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Nulls break visible lines; isolated, zero, negative and unchanged points survive."""
    score = page.locator(f"#{plot_id(trend, 'verbosity.score')}")
    assert score.locator(".scatterlayer .point").count() == 3
    assert score.evaluate("p => p.data[0].y") == [12.5, None, 0, None, 25]
    # No SVG segment may bridge either null between these three isolated points.
    assert score.locator(".scatterlayer .js-line").evaluate_all(
        "paths => paths.every(p => p.getTotalLength() < 1)"
    )
    assert score.locator(".ytitle").text_content() == "percent"
    assert "Value: 0%" in hover(page, score.get_attribute("id"), 1)
    change = page.locator(f"#{plot_id(trend, 'verbosity.total_loc', difference=True)}")
    assert change.evaluate("p => p.data[0].y") == [None, 2, -3, 0, 0]
    assert change.locator(".scatterlayer .point").count() == 4
    assert "Change: +0 lines" in hover(page, change.get_attribute("id"), 2)
    fraction_change = page.locator(f"#{plot_id(trend, 'erosion.score', difference=True)}")
    assert fraction_change.locator(".ytitle").text_content() == "percentage points"
    assert "Change: -12.5 percentage points" in hover(page, fraction_change.get_attribute("id"), 0)
    null = page.locator(f"#{plot_id(trend, 'rfc.partial_response_sum')}")
    assert null.locator(".scatterlayer .point").count() == 0
    assert null.evaluate("p => p.data[0].y") == [None] * 5
    late = page.locator(f"#{plot_id(trend, 'syntax.python.node_count')}")
    assert late.locator(".scatterlayer .point").count() == 1
    assert late.evaluate("p => p.data[0].y") == [None, None, None, None, 7]


def wait_for_chart_width(page: Any, chart_id: str) -> None:  # noqa: ANN401
    """Wait until the rendered SVG fits its responsive chart container."""
    page.wait_for_function("""id => {
      const p = document.getElementById(id);
      return Math.abs(p.querySelector('.main-svg').getBoundingClientRect().width - p.clientWidth) < 3;
    }""", arg=chart_id)


def check_resize(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Wrapped long tick labels stay inside SVG bounds with useful plotting area."""
    chart_id = plot_id(trend, "verbosity.total_loc")
    widths = []
    for width in (1280, 480, 1280):
        page.set_viewport_size({"width": width, "height": 1000})
        wait_for_chart_width(page, chart_id)
        chart = page.locator(f"#{chart_id}")
        chart.scroll_into_view_if_needed()
        geometry = chart.evaluate("""p => {
          const svg = p.querySelector('.main-svg').getBoundingClientRect();
          const labels = [...p.querySelectorAll('.xtick text')].map(t => {
            const r = t.getBoundingClientRect();
            return {text: t.textContent, inside: r.left >= svg.left - 2 &&
              r.right <= svg.right + 2 && r.top >= svg.top - 2 && r.bottom <= svg.bottom + 2};
          });
          const area = p.querySelector('.nsewdrag').getBoundingClientRect();
          return {width: svg.width, area: {w: area.width, h: area.height}, labels};
        }""")
        assert len(geometry["labels"]) == len(trend.paths), geometry
        assert all(label["inside"] for label in geometry["labels"]), geometry
        for index, label in enumerate(geometry["labels"]):
            assert label["text"] == f"{index + 1}: {trend.paths[index].name}"
        assert geometry["area"]["w"] >= 200, geometry
        assert geometry["area"]["h"] >= 120, geometry
        value_box = chart.bounding_box()
        change_box = page.locator(f"#{plot_id(trend, 'verbosity.total_loc', difference=True)}").bounding_box()
        assert value_box is not None
        assert change_box is not None
        if width >= 1024:
            assert change_box["x"] > value_box["x"]
            assert abs(change_box["y"] - value_box["y"]) < 2
        else:
            assert change_box["y"] > value_box["y"] + value_box["height"]
        widths.append(geometry["width"])
    assert widths[1] < widths[0], widths
    assert abs(widths[0] - widths[2]) < 3, widths


def check_unchanged_toggle(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """CSS alone hides unchanged pairs, preserves unknowns, and restores resized charts."""
    toggle = page.get_by_label("Hide unchanged metrics", exact=True)
    assert not toggle.is_checked()
    stable = ("ric.partial_ratio_mean", "verbosity.flagged_loc")
    kept = ("verbosity.total_loc", "verbosity.score", "rfc.partial_response_sum")
    toggle.check()
    for metric in stable:
        for difference in (False, True):
            assert not page.locator(f"#{plot_id(trend, metric, difference=difference)}").is_visible()
    for metric in kept:
        for difference in (False, True):
            assert page.locator(f"#{plot_id(trend, metric, difference=difference)}").is_visible()
    page.set_viewport_size({"width": 480, "height": 1000})
    toggle.uncheck()
    for metric in stable:
        chart_id = plot_id(trend, metric)
        chart = page.locator(f"#{chart_id}")
        assert chart.is_visible()
        if chart.locator(".main-svg").count():
            wait_for_chart_width(page, chart_id)
    page.set_viewport_size({"width": 1280, "height": 1000})


def check_metric_groups(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Native disclosures collapse whole groups and cooperate with filtering and resize."""
    groups = page.locator("details.metric-group")
    assert groups.count() == 14
    group = page.locator("#metric-group-syntax")
    summary = group.locator("summary")
    chart_id = plot_id(trend, "syntax.python.node_count")
    chart = page.locator(f"#{chart_id}")
    assert group.evaluate("element => element.open")
    summary.press("Enter")
    assert not group.evaluate("element => element.open")
    assert not chart.is_visible()
    assert page.locator(f"#{plot_id(trend, 'verbosity.total_loc')}").is_visible()
    page.set_viewport_size({"width": 480, "height": 1000})
    summary.press("Enter")
    assert chart.is_visible()
    if chart.locator(".main-svg").count():
        wait_for_chart_width(page, chart_id)
    toggle = page.get_by_label("Hide unchanged metrics", exact=True)
    toggle.check()
    assert not page.locator("#metric-group-cog_erosion").is_visible()
    assert summary.is_visible()
    assert chart.is_visible()
    assert not page.locator(f"#{plot_id(trend, 'syntax.node_count')}").is_visible()
    toggle.uncheck()
    assert page.locator("#metric-group-cog_erosion").is_visible()
    summary.press("Enter")
    toggle.check()
    toggle.uncheck()
    assert not group.evaluate("element => element.open")
    summary.press("Enter")
    page.set_viewport_size({"width": 1280, "height": 1000})


def check_without_javascript(page: Any, trend: Trend) -> None:  # noqa: ANN401
    """Without JavaScript, explain the requirement and keep source paths accessible."""
    assert page.locator(".main-svg").count() == 0
    assert page.locator("noscript").is_visible()
    assert "Enable JavaScript" in page.locator("noscript").inner_text()
    assert page.locator("table").count() == 0
    sources = page.locator("#source-directories")
    sources.locator("summary").click()
    assert sources.locator("li").all_text_contents() == [str(path) for path in trend.paths]
    assert page.locator("img, iframe").count() == 0


def main() -> None:
    """Install no dependencies; exercise the pinned tool environment and fail loudly."""
    assert version("playwright") == PLAYWRIGHT_VERSION, "Use the documented Playwright pin"
    # Dynamic import keeps this optional browser tool outside ordinary project imports.
    api = import_module("playwright.sync_api")
    sync_playwright = api.sync_playwright
    trend = representative_trend()
    attempts: list[str] = []
    errors: list[str] = []
    failures: list[str] = []
    with TemporaryDirectory(prefix="scb-browser-") as temporary, sync_playwright() as playwright:
        artifact = Path(temporary) / "report.html"
        artifact.write_text(render_trend_html(trend), encoding="utf-8")
        browser = playwright.chromium.launch()
        for javascript in (True, False):
            context = browser.new_context(
                java_script_enabled=javascript, offline=True,
                viewport={"width": 1280, "height": 1000}, service_workers="block",
            )
            context.on("request", lambda request: attempts.append(request.url)
                       if request.url.startswith(("http://", "https://")) else None)
            context.route("http://**/*", lambda route: route.abort())
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text)
                    if message.type == "error" else None)
            page.goto(artifact.as_uri(), wait_until="load", timeout=120_000)
            checks = (check_render, check_hover, check_hostile_labels, check_gaps_and_units, check_unchanged_toggle, check_metric_groups, check_resize) if javascript else (check_without_javascript, check_unchanged_toggle, check_metric_groups)
            for check in checks:
                try:
                    check(page, trend)
                except (AssertionError, api.Error) as error:
                    failures.append(f"{check.__name__}: {error}")
                    stdout.write(f"FAIL {failures[-1]}\n")
                else:
                    stdout.write(f"PASS {check.__name__}\n")
            context.close()
        browser.close()
    assert not attempts, f"Attempted HTTP(S): {attempts}"
    assert not errors, f"Browser errors: {errors}"
    assert not failures, "\n".join(failures)
    stdout.write(f"PASS offline Chromium acceptance: {len(trend.series) * 2} SVG charts; no browser errors or HTTP(S)\n")


if __name__ == "__main__":
    main()
