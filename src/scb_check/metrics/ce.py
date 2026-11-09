"""Partial efferent category coupling (Ce), counting internal source classes."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.categories import CategoryDependencies
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult


class EfferentCoupling(Metric[[CategoryDependencies]]):
    """Count inside classes with outside dependencies, not distinct outside targets.

    One source class depending on twenty outside classes contributes one.
    This preserves Martin's historical population rather than the target-breadth
    variant used by other tools. Internal-only dependencies add nothing.

    Martin (1994), Dependency Metrics, p. 6:
    https://condor.depaul.edu/dmumaugh/OOT/Design-Principles/oodmetrc.pdf
    Briand, Daly & Wüst (1999), section 4.2.1, printed p. 102:
    https://doi.org/10.1109/32.748920

    The dependency predicate is unspecified in the cited definition. Both Ca and
    Ce independently consume the analyzer-selected policy in `categories.py`.
    Unresolved outgoing uses can hide dependencies; observed zeros remain partial.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_categories": "categories",
        "unavailable_categories": "categories",
        "partial_source_sum": "source classes",
        "partial_source_mean": "source classes",
        "partial_source_max": "source classes",
    }

    def compute(self, dependencies: CategoryDependencies) -> MetricResult:
        """Summarize measured categories only; aggregation is an analyzer convention."""
        sources = self.source_sets(dependencies)
        counts = tuple(len(value) for value in sources.values() if value is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_categories": len(counts),
            "unavailable_categories": len(sources) - len(counts),
            "partial_source_sum": summary.total,
            "partial_source_mean": summary.mean,
            "partial_source_max": summary.maximum,
        })

    def source_sets(self, dependencies: CategoryDependencies) -> Mapping[str, frozenset[str] | None]:
        """Return read-only category-ID source sets, separate from numerical reports.

        Each internal source counts once regardless of outside target or site
        volume. `None` denotes missing extraction support; an empty set is only
        an observed partial zero. No language resolution or IO is performed.
        """
        membership = dependencies.class_categories
        sources: dict[str, set[str] | None] = {
            category: None if category in dependencies.unavailable_categories else set()
            for category in dict.fromkeys(membership.values())
        }
        for source, target in dependencies.class_edges:
            category = membership[source]
            population = sources[category]
            if membership[target] != category and population is not None:
                population.add(source)
        return MappingProxyType({
            category: None if value is None else frozenset(value)
            for category, value in sources.items()
        })
