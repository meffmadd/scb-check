"""Partial afferent category coupling (Ca), counting distinct external client classes."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.categories import CategoryDependencies
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult


class AfferentCoupling(Metric[[CategoryDependencies]]):
    """Count outside client classes per category, not incoming module neighbors.

    Martin (1994), Dependency Metrics, p. 6:
    https://condor.depaul.edu/dmumaugh/OOT/Design-Principles/oodmetrc.pdf
    Briand, Daly & Wüst (1999), section 4.2.1, printed p. 102:
    https://doi.org/10.1109/32.748920

    The cited dependency predicate is unspecified. The shared policy in
    `categories.py` is an analyzer choice, not a recovered paper definition.
    Unknown incoming uses anywhere can hide clients for any measured category.
    Results, including zero, remain explicitly partial and project-scoped.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_categories": "categories",
        "unavailable_categories": "categories",
        "partial_client_sum": "client classes",
        "partial_client_mean": "client classes",
        "partial_client_max": "client classes",
    }

    def compute(self, dependencies: CategoryDependencies) -> MetricResult:
        """Summarize measured categories only; aggregation is an analyzer convention."""
        clients = self.client_sets(dependencies)
        counts = tuple(len(value) for value in clients.values() if value is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_categories": len(counts),
            "unavailable_categories": len(clients) - len(counts),
            "partial_client_sum": summary.total,
            "partial_client_mean": summary.mean,
            "partial_client_max": summary.maximum,
        })

    def client_sets(self, dependencies: CategoryDependencies) -> Mapping[str, frozenset[str] | None]:
        """Return read-only category-ID client sets, separate from numerical reports.

        Each outside client counts once, even when it uses several internal
        classes or members. Internal clients add nothing. `None` denotes missing
        extraction support; an empty set is an observed partial zero.
        """
        membership = dependencies.class_categories
        clients: dict[str, set[str] | None] = {
            category: None if category in dependencies.unavailable_categories else set()
            for category in dict.fromkeys(membership.values())
        }
        for source, target in dependencies.class_edges:
            category = membership[target]
            population = clients[category]
            if membership[source] != category and population is not None:
                population.add(source)
        return MappingProxyType({
            category: None if value is None else frozenset(value)
            for category, value in clients.items()
        })
