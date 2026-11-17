"""Second checkpoint of the snapshot tutorial."""
# ruff: noqa: INP001 -- standalone source snapshot, not an importable package


def total(prices: tuple[int, ...]) -> int:
    """Return the sum of nonnegative prices.

    Raises:
        ValueError: If a price is negative.
    """
    amount = 0
    for price in prices:
        if price < 0:
            raise ValueError("Prices must be nonnegative")
        amount += price
    return amount
