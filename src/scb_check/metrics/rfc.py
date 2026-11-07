"""Partial retained-project direct Response For a Class (RFC₁)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import SymbolKind


class RFC(Metric[[ProjectIR]]):
    """Count selected class methods and their direct possible method callees.

    This is a partial project-only interpretation of direct RFC₁, not a
    transitive response set or a quality score. Method selection comes from
    the retained instance and class member lookups, including inherited
    declarations and honoring their selected overrides. Identities, not call
    sites or paths, are counted once per class.

    Briand, Daly & Wüst (1999), Definitions 21-22:
    https://doi.org/10.1109/32.748920
    Chidamber & Kemerer (1994): https://doi.org/10.1109/32.295895
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_classes": "classes",
        "unavailable_classes": "classes",
        "partial_response_sum": "methods",
        "partial_response_mean": "methods",
        "partial_response_max": "methods",
    }

    def compute(self, project: ProjectIR) -> MetricResult:
        """Summarize measured classes; these aggregates are an analyzer convention.

        Classes with unsupported extraction do not enter the sum, mean, or
        maximum. With no measured classes all three aggregates are `None`.
        """
        responses = self.response_sets(project)
        counts = tuple(len(value) for value in responses.values() if value is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_classes": len(counts),
            "unavailable_classes": len(responses) - len(counts),
            "partial_response_sum": summary.total,
            "partial_response_mean": summary.mean,
            "partial_response_max": summary.maximum,
        })

    def response_sets(self, project: ProjectIR) -> Mapping[str, frozenset[str] | None]:
        """Return read-only response identities keyed by class declaration ID.

        Selected abstract, pass-only, ellipsis-only, and empty declarations
        remain seed methods. Generated methods are not invented. Inherited
        methods retain their canonical declaring identities and recorded calls;
        those calls are not re-resolved for each inheriting class.

        Add only the retained runtime method bodies directly called by each
        seed, using both complete and approximate possible-target sets. Never
        fall back to static selection when possible bodies are unavailable.
        Free/nested functions, attribute references, initialization execution,
        and explicitly unsupported contexts do not expand the response set.
        Calls in nested functions are not promoted to their enclosing method.

        Only retained project declarations and bodies count. Libraries count
        only when analyzed as project source. Unknown ancestry, unresolved
        calls, external overrides, decorators, and dynamic behavior may hide
        responses, so even an observed zero is partial. Incoming call volume
        is irrelevant; unmodeled incoming callers do not enlarge these sets.

        `None` marks missing source-use, base, member-lookup, or selected-method
        extraction, including a selected inherited body's call inventory.
        Available but ambiguous/unsupported member selections are skipped;
        neither lookup promises a complete runtime method population.
        """
        # Index possible method bodies, excluding standalone and nested functions.
        method_bodies = {
            symbol.callable_facts.implementation_id
            for symbol in project.symbols_by_id.values()
            if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is not None
            and symbol.callable_facts.implementation_id is not None
        }
        # Group only direct calls by execution owner, without following callee bodies.
        callees: dict[str, set[str]] = {}
        for use in project.source_uses_by_id.values():
            if (use.kind == "call" and use.execution_kind == "function"
                    and use.unsupported_context is None and use.owner_id is not None):
                callees.setdefault(use.owner_id, set()).update(
                    target for target in use.runtime_targets.target_ids if target in method_bodies
                )
        # Require callable and call-inventory extraction for every selected seed body.
        available_methods = {
            method.id for module in project.modules if module.source_uses is not None
            for method in module.symbols
            if method.kind == SymbolKind.METHOD and method.callable_facts is not None
        }
        # Seed each supported class from retained selections rather than resolving bases.
        responses: dict[str, frozenset[str] | None] = {}
        for module in project.modules:
            for symbol in module.symbols:
                if symbol.kind != SymbolKind.CLASS:
                    continue
                if (module.source_uses is None or symbol.direct_bases is None
                        or symbol.id not in project.member_lookup
                        or symbol.id not in project.class_member_lookup):
                    responses[symbol.id] = None
                    continue
                methods = frozenset(
                    target.id
                    for lookup in (project.member_lookup, project.class_member_lookup)
                    for selection in lookup[symbol.id].values()
                    if selection.target_id is not None
                    and (target := project.symbols_by_id.get(selection.target_id)) is not None
                    and target.kind == SymbolKind.METHOD
                )
                # Missing seed extraction is unavailable, not a measured empty population.
                if not methods <= available_methods:
                    responses[symbol.id] = None
                    continue
                # Expand only the seed methods, never the methods added by this union.
                responses[symbol.id] = methods.union(*(callees.get(method, set()) for method in methods))
        # Keep structured diagnostics separate from the flat numerical summary.
        return MappingProxyType(responses)
