"""Private arithmetic shared by the two function-mass metrics."""

from collections.abc import Callable
from math import sqrt

from scb_check.tree_walking.models import SymbolIR


def mass_share(
    functions: tuple[SymbolIR, ...],
    high_functions: tuple[SymbolIR, ...],
    complexity: Callable[[SymbolIR], int],
) -> tuple[float, float, float]:
    """Return score, total mass, and high-complexity mass; empty mass scores zero."""
    total, high = (
        sum(
            complexity(function) * sqrt(function.sloc)
            for function in population
            if function.sloc > 0
        )
        for population in (functions, high_functions)
    )
    return high / total if total else 0.0, total, high
