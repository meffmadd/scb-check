"""Compare independently computed snapshot reports without source access."""

from __future__ import annotations

from scb_check.models import Report
from scb_check.models import ReportValue


def compare_reports(before: Report, after: Report) -> dict[str, ReportValue]:
    """Return signed later-minus-earlier measurements in the check JSON structure."""
    after_values = after.to_dict()
    delta: dict[str, ReportValue] = {}
    for name, earlier in before.to_dict().items():
        later = after_values[name]
        if isinstance(earlier, dict) and isinstance(later, dict):
            delta[name] = {
                language: {
                    count: later.get(language, {}).get(count, 0)
                    - earlier.get(language, {}).get(count, 0)
                    for count in ("tree_count", "node_count")
                }
                for language in sorted(earlier.keys() | later.keys())
            }
        elif not isinstance(earlier, dict) and not isinstance(later, dict):
            delta[name] = later - earlier
    return delta


def render_comparison(
    before: Report, after: Report, delta: dict[str, ReportValue]
) -> str:
    """Render before, after, and signed delta values, including zero deltas."""
    before_values = _display_measurements(before.to_dict())
    after_values = _display_measurements(after.to_dict())
    rows = ["metric | before | after | delta (after - before)"]
    for name, difference in _display_measurements(delta).items():
        earlier, later = before_values.get(name, 0), after_values.get(name, 0)
        rows.append(
            f"{name} | {earlier:.2%} | {later:.2%} | {difference * 100:+.2f} percentage points"
            if name in {"verbosity", "erosion", "cog_erosion"}
            else f"{name} | {earlier} | {later} | {difference:+}"
        )
    return "\n".join(rows)


def _display_measurements(
    report: dict[str, ReportValue],
) -> dict[str, int | float]:
    measurements = {
        name: value
        for name, value in report.items()
        if not isinstance(value, dict)
    }
    syntax = report["syntax_by_language"]
    if isinstance(syntax, dict):
        for language, counts in syntax.items():
            measurements.update(
                (f"syntax_by_language.{language}.{name}", value)
                for name, value in counts.items()
            )
    return measurements
