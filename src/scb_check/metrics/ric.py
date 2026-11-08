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
        """Summarize measured pairs, including zeros; no population yields null ratios."""
        diagnostics = self.pair_diagnostics(modules)
        ratios = tuple(value.ratio for value in diagnostics.values() if value is not None)
        return MappingProxyType({
            "measured_pairs": len(ratios),
            "unavailable_pairs": len(diagnostics) - len(ratios),
            "partial_ratio_mean": sum(ratios) / len(ratios) if ratios else None,
            "partial_ratio_max": max(ratios) if ratios else None,
        })

    def pair_diagnostics(self, modules: tuple[ModuleIR, ...]) -> Mapping[tuple[str, str], RICPair | None]:
        """Return read-only `(method_id, comparison_class_id)` diagnostics.

        Classes require source uses, direct-base facts, and callable extraction
        for all their declared methods. Targets also require callable extraction.
        An unsupported method uses retained lexical ownership only to enumerate
        unavailable pairs; it never supplies a measured caller or target.
        """
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

        # Invert static calls once, retaining distinct users partitioned by declaring class.
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

        pairs: dict[tuple[str, str], RICPair | None] = {}
        for method_id, owner_id in owners.items():
            owner_users = len(users.get((method_id, owner_id), ())) if owner_id is not None else 0
            denominator = max(1, owner_users)
            for class_id, available in classes.items():
                if class_id == owner_id:
                    continue
                key = (method_id, class_id)
                if (not available or owner_id is None or not classes.get(owner_id, False)
                        or method_id not in available_methods):
                    pairs[key] = None
                    continue
                external_users = len(users.get(key, ()))
                pairs[key] = RICPair(external_users, owner_users, denominator, external_users / denominator)
        return MappingProxyType(pairs)
