"""Compose and present comparisons without source access or analysis execution."""

from types import MappingProxyType

from scb_check.metrics.units import Unit
from scb_check.models import AnalysisResult
from scb_check.models import MetricResult
from scb_check.models import Report
from scb_check.models import ReportValue
from scb_check.reporting.score import REPORT_UNITS
from scb_check.reporting.score import compute_report
from scb_check.reporting.score import validate_report


def compute_diff_report(
    before: AnalysisResult, after: AnalysisResult
) -> dict[str, Report]:
    """Compose snapshots and their signed later-minus-earlier differences."""
    earlier, later = compute_report(before), compute_report(after)
    return {
        "before": earlier,
        "after": later,
        "diff": compare_reports(earlier, later),
    }


def compare_reports(before: Report, after: Report) -> Report:
    """Subtract corresponding flat results, zero-filling only absent language counts."""
    validate_report(before)
    validate_report(after)
    if before.keys() != after.keys():
        raise ValueError("missing corresponding metric groups")
    difference: dict[str, MetricResult] = {}
    for group, earlier in before.items():
        later = after[group]
        all_fields = earlier.keys() | later.keys()
        language_fields = {
            field
            for field in all_fields
            if group == "syntax"
            and field.partition(".")[0]
            and field.partition(".")[2] in REPORT_UNITS["syntax"]
        }
        if (earlier.keys() ^ later.keys()) - language_fields:
            raise ValueError(f"missing corresponding fields in {group!r}")
        fields = [
            *(field for field in earlier if field not in language_fields),
            *sorted(
                language_fields,
                key=lambda field: (
                    field.partition(".")[0],
                    tuple(REPORT_UNITS["syntax"]).index(field.partition(".")[2]),
                ),
            ),
        ]
        values: dict[str, ReportValue] = {}
        for field in fields:
            # Only language fields can be missing after contract validation.
            first, second = earlier.get(field, 0), later.get(field, 0)
            values[field] = (
                None if first is None or second is None else second - first
            )
        difference[group] = MappingProxyType(values)
    validate_report(difference)
    return MappingProxyType(difference)


def render_comparison(before: Report, after: Report, diff: Report) -> str:
    """Format units supplied by metrics, keeping unknowns and zero differences visible."""
    rows = ["metric | before | after | diff (after - before)"]
    for group, result in diff.items():
        for field, difference in result.items():
            unit = REPORT_UNITS[group][
                field.rsplit(".", 1)[-1] if group == "syntax" else field
            ]
            earlier, later = before[group].get(field), after[group].get(field)
            rows.append(
                f"{group}.{field} | {_format(earlier, unit)} | {_format(later, unit)} | {_format(difference, unit, difference=True)}"
            )
    return "\n".join(rows)


def _format(value: ReportValue, unit: Unit, *, difference: bool = False) -> str:
    if value is None:
        return "unavailable"
    if unit == "fraction":
        return (
            f"{value * 100:+.2f} percentage points"
            if difference
            else f"{value:.2%}"
        )
    return f"{value:+} {unit}" if difference else f"{value} {unit}"
