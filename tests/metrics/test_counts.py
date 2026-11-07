"""Measured count summaries distinguish unavailable populations from zeros."""

import pytest

from scb_check.metrics._counts import summarize_counts


@pytest.mark.parametrize(
    ("counts", "total", "mean", "maximum"),
    [
        ((), None, None, None),
        ((0,), 0, 0.0, 0),
        ((0, 0), 0, 0.0, 0),
        ((0, 2, 3), 5, 5 / 3, 3),
    ],
)
def test_summarize_measured_counts(
    counts: tuple[int, ...], total: int | None, mean: float | None, maximum: int | None,
) -> None:
    """Empty populations are null; measured zeros participate in all aggregates."""
    summary = summarize_counts(counts)

    assert summary.total == total
    assert summary.mean == mean
    assert summary.maximum == maximum
