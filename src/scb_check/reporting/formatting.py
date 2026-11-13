"""Shared unit-aware text formatting for numerical report presentations."""

from scb_check.metrics.units import Unit
from scb_check.models import ReportValue


def format_measurement(
    value: ReportValue,
    unit: Unit,
    *,
    difference: bool = False,
    precision: int | None = None,
) -> str:
    """Format unavailable values and units, optionally rounding fraction displays.

    The terminal comparison supplies its fixed fractional `precision`.
    Raw reports are never changed by display conversion.
    """
    if value is None:
        return "unavailable"
    scaled = value * 100 if unit == "fraction" else value
    if unit == "fraction" and precision is not None:
        number = f"{scaled:.{precision}f}"
    else:
        number = str(scaled)
        if precision is None:
            number = number.removesuffix(".0")
    if difference and not number.startswith("-"):
        number = "+" + number
    if unit == "fraction":
        return f"{number} percentage points" if difference else f"{number}%"
    return f"{number} {unit}"
