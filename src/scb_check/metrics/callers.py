"""Partial project-only distinct callers, an engineering count of incoming use."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolKind


@dataclass(frozen=True, slots=True)
class CallerSets:
    """Distinct caller declaration IDs, separated by logical-module membership."""

    same_module: frozenset[str]
    cross_module: frozenset[str]


class DistinctCallers(Metric[[tuple[ModuleIR, ...]]]):
    """Count retained source functions and methods that directly call each callable.

    Invert only calls whose static `resolution.status` is `project`, selecting
    `resolution.target_id`, not `runtime_targets`. Each source declaration counts
    once per destination, including direct recursion. A nested function is its own
    caller; module/class initialization and unsupported execution have no callable
    caller and are excluded, without walking up to an enclosing callable.

    The population is retained function/method declarations with `callable_facts`
    and available module `source_uses`. Placeholder and decorated declarations
    remain eligible: this measures source declaration use, not implementation
    bodies or runtime dispatch. Other retained callables are unavailable (`None`
    diagnostics). Empty or wholly unavailable populations have null summaries.

    All measured values are explicitly partial project-only counts, even zeros:
    unresolved, ambiguous, external, unsupported, and unretained incoming uses
    cannot be attributed. Static member selection does not expand overrides,
    infer callbacks, or model execution frequency. Missing extraction elsewhere
    can hide incoming callers without making supported destinations unavailable.
    Same/cross module compares `ModuleIR.id`, one logical module per physical file,
    not potentially colliding module names or package membership.

    Sums count caller/destination pairs, not globally distinct callers. Mean and
    maximum range over measured destinations, including measured zeros. These
    project summaries are analyzer conventions, not quality scores, Henry-Kafura
    fan-in, or the paper-defined RIC ratio. No defining paper is claimed.
    Briand, Daly & Wüst (1999), https://doi.org/10.1109/32.748920, is coupling
    framework background only.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_callables": "functions",
        "unavailable_callables": "functions",
        "partial_caller_sum": "callers",
        "partial_caller_mean": "callers",
        "partial_caller_max": "callers",
        "partial_same_module_sum": "callers",
        "partial_cross_module_sum": "callers",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize measured destinations without treating unavailable counts as zero."""
        diagnostics = self.caller_sets(modules)
        measured = [value for value in diagnostics.values() if value is not None]
        counts = tuple(len(value.same_module) + len(value.cross_module) for value in measured)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_callables": len(measured),
            "unavailable_callables": len(diagnostics) - len(measured),
            "partial_caller_sum": summary.total,
            "partial_caller_mean": summary.mean,
            "partial_caller_max": summary.maximum,
            "partial_same_module_sum": sum(len(value.same_module) for value in measured) if measured else None,
            "partial_cross_module_sum": sum(len(value.cross_module) for value in measured) if measured else None,
        })

    def caller_sets(self, modules: tuple[ModuleIR, ...]) -> Mapping[str, CallerSets | None]:
        """Return immutable per-destination caller sets, separate from numerical reports."""
        # Index supported callable declarations by their logical module identity.
        callable_modules = {
            symbol.id: module.id
            for module in modules for symbol in module.symbols
            if symbol.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD}
            and symbol.callable_facts is not None and module.source_uses is not None
        }
        # Keep unavailable destinations distinct from supported empty caller sets.
        callers: dict[str, tuple[set[str], set[str]] | None] = {
            symbol.id: (set(), set()) if symbol.id in callable_modules else None
            for module in modules for symbol in module.symbols
            if symbol.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD}
        }
        # Invert static direct calls without expanding dispatch or guessing owners.
        for module in modules:
            for use in module.source_uses or ():
                if (
                    use.kind != "call" or use.execution_kind != "function"
                    or use.owner_id not in callable_modules
                    or use.resolution.status != "project"
                ):
                    continue
                target_id = use.resolution.target_id
                if target_id is None:
                    continue
                destination = callers.get(target_id)
                if destination is None:
                    continue
                # Partition each caller/destination pair using retained module IDs.
                same_module = callable_modules[use.owner_id] == callable_modules[target_id]
                destination[0 if same_module else 1].add(use.owner_id)
        # Freeze both the diagnostic mapping and its nested caller sets.
        return MappingProxyType({
            target_id: None if value is None else CallerSets(frozenset(value[0]), frozenset(value[1]))
            for target_id, value in callers.items()
        })
