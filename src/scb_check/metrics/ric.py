"""Partial method-level Relative Inward Coupling over retained direct calls."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolKind


@dataclass(frozen=True, slots=True)
class RICPair:
    """Partial counts for one method/comparison-class pair, preserving the floor."""

    external_users: int
    owner_users: int
    effective_denominator: int
    ratio: float


@dataclass(frozen=True, slots=True)
class _RICFacts:
    """Shared availability, canonical ownership, and sparse distinct-user counts."""

    classes: Mapping[str, bool]
    owners: Mapping[str, str | None]
    measured_owners: Mapping[str, str]
    users: Mapping[tuple[str, str], int]

    def pair(self, method_id: str, class_id: str) -> RICPair | None:
        """Apply the same availability gate and formula for both public consumers."""
        if method_id not in self.measured_owners or not self.classes[class_id]:
            return None
        owner_id = self.measured_owners[method_id]
        owner_users = self.users.get((method_id, owner_id), 0)
        denominator = max(1, owner_users)
        external_users = self.users.get((method_id, class_id), 0)
        return RICPair(external_users, owner_users, denominator, external_users / denominator)


def _project_facts(modules: tuple[ModuleIR, ...]) -> _RICFacts:
    """Project immutable retained evidence once without expanding comparison pairs."""
    classes = {
        symbol.id: module.source_uses is not None and symbol.direct_bases is not None
        for module in modules for symbol in module.symbols if symbol.kind == SymbolKind.CLASS
    }
    methods = {
        symbol.id: symbol
        for module in modules for symbol in module.symbols if symbol.kind == SymbolKind.METHOD
    }
    owners = {
        method.id: method.callable_facts.declaring_class_id if method.callable_facts else method.owner_id
        for method in methods.values()
    }
    available_methods = {
        symbol.id for module in modules if module.source_uses is not None
        for symbol in module.symbols
        if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is not None
        and symbol.callable_facts.declaring_class_id in classes
    }
    unavailable_owners = {owners[method_id] for method_id in methods.keys() - available_methods}
    classes = {
        class_id: available and class_id not in unavailable_owners
        for class_id, available in classes.items()
    }
    measured_owners = {
        method_id: owner_id for method_id in available_methods
        if (owner_id := owners[method_id]) is not None and classes[owner_id]
    }

    # Keep distinct using methods, not repeated source sites or expanded dispatch.
    users: dict[tuple[str, str], set[str]] = {}
    for module in modules:
        for use in module.source_uses or ():
            if (use.kind != "call" or use.execution_kind != "function"
                    or use.unsupported_context is not None or use.owner_id not in available_methods
                    or use.resolution.status != "project"):
                continue
            target_id = use.resolution.target_id
            caller_class = owners[use.owner_id]
            if target_id in available_methods and caller_class is not None:
                users.setdefault((target_id, caller_class), set()).add(use.owner_id)

    # Preserve full diagnostics' summation order, omitting only zero contributions.
    method_order = {method_id: index for index, method_id in enumerate(owners)}
    class_order = {class_id: index for index, class_id in enumerate(classes)}
    counts = {
        key: len(users[key])
        for key in sorted(users, key=lambda key: (method_order[key[0]], class_order[key[1]]))
    }
    return _RICFacts(
        MappingProxyType(classes), MappingProxyType(owners), MappingProxyType(measured_owners), MappingProxyType(counts),
    )


class RIC(Metric[[tuple[ModuleIR, ...]]]):
    """Measure distinct external using methods / max(1, owner using methods).

    Joshi & Joshi (2006), §7, method variant immediately after the attribute
    formula, https://doi.org/10.1109/CSMR.2006.32. This preserves that formula,
    not §8's conflicting edge-count interpretation.

    The population is every retained method crossed with every other retained
    class, including zero-use pairs. Canonical declaring ownership applies to
    both callers and targets; inherited bodies are not copied to subclasses.
    Abstract/placeholder declarations remain eligible. Only direct static
    project-resolved calls executing in methods count, once per caller identity.
    Recursion counts as owner use. No runtime-target expansion, indirect traversal,
    nested/free-function promotion, or inferred initialization calls occur.

    Missing extraction makes pairs unavailable; measured values are always
    partial, including zeros. Unresolved or unretained incoming callers can hide
    either count, so ratios are not runtime bounds. Libraries participate only
    as retained project source. Public APIs, callbacks, and external consumers
    limit interpretation: this is not a move/remove recommendation or quality
    score. Project mean/max are analyzer conventions, not paper-defined RIC.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_pairs": "pairs",
        "unavailable_pairs": "pairs",
        "partial_ratio_mean": "ratio",
        "partial_ratio_max": "ratio",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Count all pairs arithmetically and aggregate only sparse nonzero ratios."""
        facts = _project_facts(modules)
        total_pairs = sum(len(facts.classes) - (owner_id in facts.classes) for owner_id in facts.owners.values())
        measured_pairs = len(facts.measured_owners) * max(0, sum(facts.classes.values()) - 1)
        ratios = [
            pair.ratio for method_id, class_id in facts.users
            if class_id != facts.owners[method_id] and (pair := facts.pair(method_id, class_id)) is not None
        ]
        return MappingProxyType({
            "measured_pairs": measured_pairs,
            "unavailable_pairs": total_pairs - measured_pairs,
            "partial_ratio_mean": sum(ratios) / measured_pairs if measured_pairs else None,
            "partial_ratio_max": max(ratios, default=0.0) if measured_pairs else None,
        })

    def pair_diagnostics(self, modules: tuple[ModuleIR, ...]) -> Mapping[tuple[str, str], RICPair | None]:
        """Explicitly materialize read-only `(method_id, comparison_class_id)` pairs.

        Classes require source uses, direct-base facts, and callable extraction
        for all their declared methods. Targets also require callable extraction.
        An unsupported method uses retained lexical ownership only to enumerate
        unavailable pairs; it never supplies a measured caller or target.
        """
        facts = _project_facts(modules)
        return MappingProxyType({
            (method_id, class_id): facts.pair(method_id, class_id)
            for method_id, owner_id in facts.owners.items()
            for class_id in facts.classes if class_id != owner_id
        })
