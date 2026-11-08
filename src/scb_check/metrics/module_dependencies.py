"""Engineering-defined partial static resolved-call logical-module neighbors."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR


@dataclass(frozen=True, slots=True)
class ModuleNeighbors:
    """Distinct directional module IDs, not call occurrences or runtime targets."""

    incoming: frozenset[str]
    outgoing: frozenset[str]


class ModuleCallDependencies(Metric[[tuple[ModuleIR, ...]]]):
    """Count static resolved-call neighbors within retained project source.

    One `ModuleIR.id` represents one parsed physical file, without package/name
    merging. Supported module/class initialization and function execution count;
    unsupported execution does not. Only `project` static call targets contribute,
    mapped to their declaring modules. Imports, accesses, and possible runtime
    bodies add no edges. Repeated pairs deduplicate; self edges are excluded.

    Missing `source_uses` makes a module unavailable, not a measured zero. Known
    retained targets remain eligible neighbors regardless of their own extraction
    support. All measured counts are partial: missing/unresolved/external uses can
    hide incoming neighbors anywhere. Libraries enter only as scanned source.
    Sum/mean/max cover measured modules only, with null summaries if none exist;
    directional sums may differ when target extraction is unavailable. These are
    analyzer conventions, not Martin Ca/Ce, Henry-Kafura metrics, or quality scores.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_modules": "modules",
        "unavailable_modules": "modules",
        "partial_incoming_sum": "module-neighbor incidences",
        "partial_incoming_mean": "neighbors per module",
        "partial_incoming_max": "neighbors per module",
        "partial_outgoing_sum": "module-neighbor incidences",
        "partial_outgoing_mean": "neighbors per module",
        "partial_outgoing_max": "neighbors per module",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize each direction over measured modules, including partial zeros."""
        diagnostics = self.neighbor_sets(modules)
        measured = tuple(value for value in diagnostics.values() if value is not None)
        incoming = summarize_counts(tuple(len(value.incoming) for value in measured))
        outgoing = summarize_counts(tuple(len(value.outgoing) for value in measured))
        return MappingProxyType({
            "measured_modules": len(measured),
            "unavailable_modules": len(diagnostics) - len(measured),
            "partial_incoming_sum": incoming.total,
            "partial_incoming_mean": incoming.mean,
            "partial_incoming_max": incoming.maximum,
            "partial_outgoing_sum": outgoing.total,
            "partial_outgoing_mean": outgoing.mean,
            "partial_outgoing_max": outgoing.maximum,
        })

    def neighbor_sets(self, modules: tuple[ModuleIR, ...]) -> Mapping[str, ModuleNeighbors | None]:
        """Expose read-only diagnostics separately from flat numerical reports."""
        entity_modules = {
            entity.id: module.id
            for module in modules for entity in (module, *module.symbols)
        }
        incoming: dict[str, set[str]] = {module.id: set() for module in modules}
        outgoing: dict[str, set[str]] = {module.id: set() for module in modules}
        for module in modules:
            for use in module.source_uses or ():
                if (
                    use.kind != "call" or use.execution_kind == "unsupported"
                    or use.resolution.status != "project"
                ):
                    continue
                target_id = use.resolution.target_id
                target_module = entity_modules.get(target_id) if target_id is not None else None
                if target_module is not None and target_module != module.id:
                    outgoing[module.id].add(target_module)
                    incoming[target_module].add(module.id)
        return MappingProxyType({
            module.id: None if module.source_uses is None else ModuleNeighbors(
                frozenset(incoming[module.id]), frozenset(outgoing[module.id]),
            ) for module in modules
        })
