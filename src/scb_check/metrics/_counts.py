"""Private arithmetic for measured count populations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CountSummary:
    total: int | None
    mean: float | None
    maximum: int | None


def summarize_counts(counts: tuple[int, ...]) -> CountSummary:
    """Return the total, arithmetic mean, and largest value in measured `counts`.

    Each entry is one entity's measured count, including measured zeros.
    Callers must leave unavailable entities out of `counts`. An empty tuple
    returns `None` for all three fields: no measurements is different from
    measuring only zeros, which returns zero for each field.
    """
    if not counts:
        return CountSummary(None, None, None)
    total = sum(counts)
    return CountSummary(total, total / len(counts), max(counts))
