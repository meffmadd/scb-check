"""Partial project-only Message Passing Coupling, measured in static call sites."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolKind


class MPC(Metric[[tuple[ModuleIR, ...]]]):
    """Count external method-call sites in methods implemented by each class.

    This is Message Passing Coupling, not Method Pair Coupling. Repeated source
    sites count separately, while loops and possible runtime implementations do
    not multiply a site. Own implementation targets do not count. Inherited
    bodies stay with their declaring class; calls to ancestor bodies can count.

    Briand, Daly & Wüst (1999), Definition 23:
    https://doi.org/10.1109/32.748920. Original provenance: Li & Henry (1993),
    https://doi.org/10.1016/0164-1212(93)90077-B.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_classes": "classes",
        "unavailable_classes": "classes",
        "partial_call_site_sum": "call sites",
        "partial_call_site_mean": "call sites",
        "partial_call_site_max": "call sites",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize measured classes; project aggregation is an analyzer convention.

        Unsupported classes are excluded from the mean. Without measured classes,
        all three summaries are `None`. A measured zero is still explicitly partial.
        """
        counts_by_class = self.class_counts(modules)
        counts = tuple(count for count in counts_by_class.values() if count is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_classes": len(counts),
            "unavailable_classes": len(counts_by_class) - len(counts),
            "partial_call_site_sum": summary.total,
            "partial_call_site_mean": summary.mean,
            "partial_call_site_max": summary.maximum,
        })

    def class_counts(self, modules: tuple[ModuleIR, ...]) -> Mapping[str, int | None]:
        """Return read-only class-ID counts separately from numerical summaries.

        Only retained project implementations are targets. Prefer the IR's known
        runtime bodies, including approximate sets; otherwise use its statically
        selected implemented method. A site counts once if any selected body is
        implemented outside the source class. No resolution is performed here.

        The population is every retained class declaration. Missing source-use or
        direct-base facts, or a declared method without callable facts, give `None`.
        Placeholder bodies are not implementations. Class initialization, nested
        functions, lambdas, and other unsupported execution contexts are excluded.

        Library, unresolved, and non-method targets are omitted, not complete zeros.
        Approximate runtime sets and static fallback are not whole-program bounds.
        Incoming references do not contribute to this outgoing-only metric.
        """
        # Index implemented methods without copying inherited bodies into subclasses.
        methods = {
            symbol.id: symbol.callable_facts
            for module in modules for symbol in module.symbols
            if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is not None
            and symbol.callable_facts.implementation_id is not None
        }
        # Runtime targets name bodies, whereas static fallback names declarations.
        implementation_classes = {
            facts.implementation_id: facts.declaring_class_id for facts in methods.values()
        }
        # Keep unsupported class extraction distinct from observed partial zero.
        counts: dict[str, int | None] = {
            symbol.id: 0 if module.source_uses is not None and symbol.direct_bases is not None else None
            for module in modules for symbol in module.symbols
            if symbol.kind == SymbolKind.CLASS
        }
        # A missing method inventory cannot establish even a partial source population.
        for module in modules:
            for symbol in module.symbols:
                if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is None and symbol.owner_id in counts:
                    counts[symbol.owner_id] = None
        # Count physical call occurrences rather than targets or execution frequency.
        for module in modules:
            for use in module.source_uses or ():
                source = methods.get(use.owner_id or "")
                if (
                    use.kind != "call" or use.execution_kind != "function"
                    or use.unsupported_context is not None or source is None
                ):
                    continue
                owner = source.declaring_class_id
                count = counts.get(owner or "")
                if owner is None or count is None:
                    continue
                if use.runtime_targets.target_ids:
                    target_owners = {
                        implementation_classes.get(target) for target in use.runtime_targets.target_ids
                    }
                else:
                    target = methods.get(use.resolution.target_id or "")
                    target_owners = {target.declaring_class_id if target is not None else None}
                if target_owners - {None, owner}:
                    counts[owner] = count + 1
        # Own the outer mapping so callers cannot change a later computation.
        return MappingProxyType(counts)
