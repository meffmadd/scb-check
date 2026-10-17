"""Cognitive erosion and its function-mass context."""

from types import MappingProxyType
from typing import ClassVar

from scb_check.models import MetricResult
from scb_check.reporting._mass import mass_share
from scb_check.reporting.units import Unit
from scb_check.tree_walking.models import SymbolIR


class CognitiveErosion:
    """Measure the cognitive mass share of analysis-classified high-cognitive functions."""

    units: ClassVar[dict[str, Unit]] = {
        "score": "fraction",
        "total_functions": "functions",
        "high_cog_functions": "functions",
        "total_cog_mass": "mass",
        "high_cog_mass": "mass",
    }

    def compute(
        self,
        functions: tuple[SymbolIR, ...],
        high_functions: tuple[SymbolIR, ...],
    ) -> MetricResult:
        """Compute from eligible functions and their high-complexity subset."""
        score, total, high = mass_share(
            functions, high_functions, lambda function: function.cog_complexity
        )
        return MappingProxyType(
            {
                "score": score,
                "total_functions": len(functions),
                "high_cog_functions": len(high_functions),
                "total_cog_mass": total,
                "high_cog_mass": high,
            }
        )
