from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.models import AnalysisResult
from scb_check.models import Flags
from scb_check.models import Report
from scb_check.models import ReportValue
from scb_check.models import SnapshotSeries
from scb_check.reporting.comparison import compare_reports
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import serialize_report
from scb_check.reporting.trend import build_aligned_trend
from scb_check.reporting.trend import build_trend
from scb_check.tree_walking.models import ProjectIR


def test_ordered_values_and_adjacent_changes_cover_complete_reports() -> None:
    """Input positions, including repeats, retain all fields and comparator semantics."""
    reports = []
    for score in (0.2, 0.15, 0.15):
        report = serialize_report(
            compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
        )
        report["verbosity"]["score"] = score
        reports.append(report)
    reports[2]["syntax"].update({"rust.node_count": 7, "rust.tree_count": 1})
    paths = (Path("last"), Path("first"), Path("first"))
    inputs = iter(reports)
    trend = build_trend(paths, lambda _path: next(inputs))
    series = {series.metric: series for series in trend.series}

    assert trend.paths == paths
    assert series["verbosity.score"].values == (0.2, 0.15, 0.15)
    assert series["verbosity.score"].differences[0] is None
    assert series["verbosity.score"].differences[1:] == pytest.approx(
        (-0.05, 0)
    )
    assert series["syntax.rust.node_count"].values == (None, None, 7)
    assert series["syntax.rust.node_count"].differences == (None, None, 7)
    assert series["syntax.rust.node_count"].unit == "nodes"
    assert series["ric.partial_ratio_mean"].unit == "ratio"
    assert series["cbo.partial_partner_sum"].differences == (None, None, None)
    assert len(series) == len(trend.series)
    assert set(series) == {
        *(
            f"{group}.{field}"
            for group, fields in REPORT_UNITS.items()
            for field in fields
        ),
        "syntax.rust.node_count",
        "syntax.rust.tree_count",
    }
    assert trend.snapshots == tuple(reports)
    assert trend.comparisons == (
        None,
        compare_reports(reports[0], reports[1]),
        compare_reports(reports[1], reports[2]),
    )
    assert "rust.node_count" not in reports[0]["syntax"]
    for index, snapshot in enumerate(reports[1:], 1):
        comparison = compare_reports(reports[index - 1], snapshot)
        for item in trend.series:
            group, _, field = item.metric.partition(".")
            assert item.differences[index] == comparison[group].get(field)
    assert (
        build_trend(paths, lambda _path: reports[0]).series[0].metric
        == "verbosity.score"
    )


def test_aligned_series_preserve_gaps_and_average_adjacent_deltas() -> None:
    """Unequal coverage cannot change alignment or invent a delta population."""
    reports = {}
    for name, score, loc in (
        ("a", 0.2, 10),
        ("b", 0.4, 1000),
        ("c", 0.8, 20),
        ("d", 0.9, 30),
    ):
        report = serialize_report(
            compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
        )
        report["verbosity"].update(score=score, total_loc=loc)
        reports[Path(name)] = report
    trend = build_aligned_trend(
        ("third", "first", "last", "empty"),
        (
            SnapshotSeries("problem-a", (Path("a"), None, Path("c"), None)),
            SnapshotSeries("problem-b", (Path("b"), Path("d"), None, None)),
        ),
        reports.__getitem__,
        aggregate="mean",
    )
    a, b = trend.trends
    score_a = next(s for s in a.series if s.metric == "verbosity.score")
    score_b = next(s for s in b.series if s.metric == "verbosity.score")
    assert score_a.values == (0.2, None, 0.8, None)
    assert score_a.differences == (None, None, None, None)
    assert score_b.values == (0.4, 0.9, None, None)
    assert score_b.differences == (None, 0.5, None, None)
    assert a.snapshots[1] is None
    mean = next(s for s in trend.mean if s.metric == "verbosity.score")
    assert mean.values[:3] == pytest.approx((0.3, 0.9, 0.8))
    assert mean.values[3] is None
    assert mean.differences == (None, 0.5, None, None)
    assert mean.contributors == (2, 1, 1, 0)
    assert mean.change_contributors == (0, 1, 0, 0)
    unavailable = next(
        s for s in trend.mean if s.metric == "rfc.partial_response_sum"
    )
    assert unavailable.values == (None,) * 4
    assert unavailable.contributors == (0,) * 4


def test_mean_changes_average_series_deltas_not_step_means() -> None:
    """Different contributor populations yield mean deltas of 60 and -3 lines."""
    reports = {}
    for name, loc in (
        ("a", 10),
        ("b", 30),
        ("c", 20),
        ("d", 1000),
        ("e", 1100),
        ("f", 1),
        ("g", 5),
    ):
        report = serialize_report(
            compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
        )
        report["verbosity"]["total_loc"] = loc
        reports[Path(name)] = report
    reports[Path("g")]["syntax"].update(
        {"rust.node_count": 7, "rust.tree_count": 1}
    )
    sources = (
        SnapshotSeries("a", (Path("a"), Path("b"), Path("c"))),
        SnapshotSeries("b", (Path("d"), Path("e"), None)),
        SnapshotSeries("c", (None, Path("f"), Path("g"))),
    )
    trend = build_aligned_trend(
        ("1", "2", "3"), sources, reports.__getitem__, aggregate="mean"
    )
    mean = next(s for s in trend.mean if s.metric == "verbosity.total_loc")
    assert mean.values == (505, 377, 12.5)
    assert mean.differences == (None, 60, -3)
    assert mean.contributors == (2, 3, 2)
    assert mean.change_contributors == (0, 2, 2)
    for run in trend.trends:
        rust = next(
            s for s in run.series if s.metric == "syntax.rust.node_count"
        )
        if run.name != "c":
            assert rust.values == (None, None, None)
            assert rust.differences == (None, None, None)
    assert (
        build_aligned_trend(("1", "2", "3"), sources, reports.__getitem__).mean
        == ()
    )


@pytest.mark.parametrize("paths", [(), (Path("only"),)])
def test_too_few_paths_rejected_before_loading(paths: tuple[Path, ...]) -> None:
    """An invalid series cannot invoke source loading."""

    def load(_path: Path) -> Report:
        pytest.fail("must not load a short path list")

    with pytest.raises(ValueError, match="at least two"):
        build_trend(paths, load)


def test_missing_required_fields_are_not_unavailable_measurements() -> None:
    """A malformed report fails instead of inventing a null data point."""
    report = serialize_report(
        compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    )
    del report["verbosity"]["score"]
    with pytest.raises(ValueError, match="missing required fields"):
        build_trend((Path("a"), Path("b")), lambda _path: report)


def test_retained_context_is_read_only_and_independent_of_loader() -> None:
    """Mutable loader outputs cannot change an already built trend."""
    report = serialize_report(
        compute_report(AnalysisResult(Flags(), {}, ProjectIR()))
    )
    trend = build_trend((Path("a"), Path("b")), lambda _path: report)
    report["verbosity"]["score"] = 9
    assert trend.snapshots[0] is not None
    assert trend.snapshots[0]["verbosity"]["score"] == 0
    with pytest.raises(TypeError):
        cast(
            "MutableMapping[str, ReportValue]", trend.snapshots[0]["verbosity"]
        )["score"] = 7
