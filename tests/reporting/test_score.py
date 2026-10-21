from __future__ import annotations

import json
from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.models import AnalysisResult
from scb_check.models import FindingGroups
from scb_check.models import Flags
from scb_check.models import MetricResult
from scb_check.models import Report
from scb_check.models import ReportValue
from scb_check.pipeline import analyze_files
from scb_check.reporting.comparison import compare_reports
from scb_check.reporting.comparison import compute_diff_report
from scb_check.reporting.comparison import render_comparison
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import serialize_report
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind


def test_reports_are_read_only_and_serialization_is_independent(
    tmp_path: Path,
) -> None:
    """Reports consume extracted facts, support mapping operations, and stay immutable."""
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    analysis = analyze_files((source,), disable_sg=True)
    source.unlink()  # Reporting must not read the analyzed sources again.

    reports = compute_diff_report(analysis, analysis)
    assert reports.keys() == {"before", "after", "diff"}
    assert reports["before"] == reports["after"] == compute_report(analysis)
    for report in reports.values():
        assert list(report) == ["verbosity", "erosion", "cog_erosion", "syntax"]
        assert len(report) == 4
        # Intentionally bypass the read-only annotation to attempt runtime mutation.
        with pytest.raises(TypeError):
            cast("MutableMapping[str, MetricResult]", report)["verbosity"] = {}
        for result in report.values():
            with pytest.raises(TypeError):
                cast("MutableMapping[str, ReportValue]", result)["score"] = 99
        serialized = serialize_report(report)
        serialized["verbosity"]["score"] = 99
        serialized["syntax"].clear()
        serialized.clear()
        assert report["verbosity"]["score"] == 0
        assert "python.node_count" in report["syntax"]


@pytest.mark.parametrize(
    ("earlier", "later"), [(None, 1), (1, None), (None, None)]
)
@pytest.mark.parametrize(
    ("group", "field"),
    [
        ("verbosity", "score"),
        ("erosion", "total_mass"),
        ("syntax", "python.node_count"),
    ],
)
def test_unknown_measurements_propagate_without_mutating_snapshots(
    earlier: int | None,
    later: int | None,
    group: str,
    field: str,
) -> None:
    """Explicit unknowns are never zero-filled, including per-language counts."""
    before = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    after = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    before[group][field], after[group][field] = earlier, later

    difference = compare_reports(before, after)

    assert difference[group][field] is None
    assert before[group][field] == earlier
    assert after[group][field] == later
    assert (
        json.loads(json.dumps(serialize_report(difference), allow_nan=False))[
            group
        ][field]
        is None
    )
    rows = render_comparison(before, after, difference).splitlines()
    row = next(row for row in rows if row.startswith(f"{group}.{field} |"))
    assert row.endswith("unavailable")
    assert row.count("unavailable") == (
        3 if earlier is None and later is None else 2
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_only_absent_language_counts_are_zero_filled(*, reverse: bool) -> None:
    """Language zero-filling applies only to subtraction, never to explicit nulls."""
    before = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    after = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    after["syntax"].update({"python.tree_count": 1, "python.node_count": None})
    if reverse:
        before, after = after, before

    difference = compare_reports(before, after)

    assert difference["syntax"]["python.tree_count"] == (-1 if reverse else 1)
    assert difference["syntax"]["python.node_count"] is None
    assert "python.tree_count" not in (after if reverse else before)["syntax"]


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize(
    "group", ["verbosity", "erosion", "cog_erosion", "syntax"]
)
def test_missing_required_groups_and_fields_are_contract_errors(
    side: str, group: str
) -> None:
    """Neither incomplete operand may silently omit a required measurement."""
    baseline = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    for missing_field in (None, *baseline[group]):
        incomplete = serialize_report(baseline)
        if missing_field is None:
            del incomplete[group]
        else:
            del incomplete[group][missing_field]
        before, after = (
            (incomplete, baseline)
            if side == "before"
            else (baseline, incomplete)
        )
        with pytest.raises(ValueError, match="missing"):
            compare_reports(before, after)


@pytest.mark.parametrize(
    "invalid", [True, "1", [], {}, float("nan"), float("inf"), -float("inf")]
)
def test_report_values_must_be_flat_finite_nullable_numbers(
    invalid: object,
) -> None:
    """Malformed library inputs fail instead of leaking invalid measurements."""
    payload: dict[str, dict[str, object]] = {
        group: dict(result)
        for group, result in compute_report(AnalysisResult(Flags(), {})).items()
    }
    payload["verbosity"]["score"] = invalid
    # Simulate an untyped library caller supplying malformed external data.
    report = cast("Report", payload)

    with pytest.raises(ValueError, match=r"verbosity\.score"):
        serialize_report(report)
    with pytest.raises(ValueError, match=r"verbosity\.score"):
        compare_reports(report, report)


@pytest.mark.parametrize("sloc", [0, -2])
def test_nonpositive_function_sloc_has_zero_mass(sloc: int) -> None:
    """Nonpositive SLOC facts contribute no mass, even for high complexity."""
    function = SymbolIR(
        name="empty",
        qualified_name="sample.empty",
        kind=SymbolKind.FUNCTION,
        span=SourceSpan(
            file=Path("sample.py"),
            start_line=1,
            start_col=0,
            end_line=1,
            end_col=0,
        ),
        sloc=sloc,
        cyc_complexity=12,
        cog_complexity=12,
    )
    flags = Flags(
        findings=FindingGroups(
            all_functions=(function,),
            high_cc_functions=(function,),
            high_cog_functions=(function,),
        )
    )

    report = compute_report(AnalysisResult(flags, {}))

    assert report["erosion"] == {
        "score": 0.0,
        "total_functions": 1,
        "high_cc_functions": 1,
        "total_mass": 0.0,
        "high_cc_mass": 0.0,
    }
    assert report["cog_erosion"] == {
        "score": 0.0,
        "total_functions": 1,
        "high_cog_functions": 1,
        "total_cog_mass": 0.0,
        "high_cog_mass": 0.0,
    }


def test_subtraction_cannot_return_nonfinite_measurements() -> None:
    """Even finite operands may overflow; do not return an invalid diff report."""
    before = serialize_report(compute_report(AnalysisResult(Flags(), {})))
    after = serialize_report(before)
    before["erosion"]["total_mass"] = -1e308
    after["erosion"]["total_mass"] = 1e308

    with pytest.raises(ValueError, match=r"erosion\.total_mass"):
        compare_reports(before, after)
