"""Cyclomatic erosion and its function-mass context."""

from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._mass import mass_share
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import SymbolIR


class Erosion(Metric[[tuple[SymbolIR, ...], tuple[SymbolIR, ...]]]):
    """Measure the cyclomatic mass share of analysis-classified high-CC functions."""

    units: ClassVar[dict[str, Unit]] = {
        "score": "fraction",
        "total_functions": "functions",
        "high_cc_functions": "functions",
        "total_mass": "mass",
        "high_cc_mass": "mass",
    }

    def compute(
        self,
        functions: tuple[SymbolIR, ...],
        high_functions: tuple[SymbolIR, ...],
    ) -> MetricResult:
        """Compute from eligible functions and their high-complexity subset."""
        score, total, high = mass_share(
            functions, high_functions, lambda function: function.cyc_complexity
        )
        return MappingProxyType(
            {
                "score": score,
                "total_functions": len(functions),
                "high_cc_functions": len(high_functions),
                "total_mass": total,
                "high_cc_mass": high,
            }
        )
