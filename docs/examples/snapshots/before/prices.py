"""First checkpoint of the snapshot tutorial."""
# ruff: noqa: INP001 -- standalone source snapshot, not an importable package


def total(prices: tuple[int, ...]) -> int:
    """Return the sum of prices."""
    return sum(prices)
