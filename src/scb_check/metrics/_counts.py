"""Private arithmetic for measured count populations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CountSummary:
    total: int | None
    mean: float | None
    maximum: int | None


def summarize_counts(counts: tuple[int, ...]) -> CountSummary:
    """Return null aggregates only when no counts were measured."""
    if not counts:
        return CountSummary(None, None, None)
    total = sum(counts)
    return CountSummary(total, total / len(counts), max(counts))
