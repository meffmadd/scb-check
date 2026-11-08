"""Partial static Class Inheritance-related Coupling over retained source sites."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ReceiverIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind


class CIC(Metric[[tuple[ModuleIR, ...]]]):
    """Count accesses/uses of members canonically defined in proper ancestors.

    Rajaraman & Lyu (1992), Some Coupling Measures for C++ Programs, §IV,
    PDF p. 6 / printed p. 5 (no DOI verified):
    https://www.cse.cuhk.edu.hk/lyu/_media/conference/crajaraman_tools1992_some.pdf
    Static dispatch, source ownership, and project aggregation are analyzer
    conventions for this Python-first interpretation, not paper-defined policies.
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_classes": "classes",
        "unavailable_classes": "classes",
        "partial_occurrence_sum": "occurrences",
        "partial_occurrence_mean": "occurrences",
        "partial_occurrence_max": "occurrences",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize measured classes only; no measured population gives `None`."""
        diagnostics = self.class_counts(modules)
        counts = tuple(count for count in diagnostics.values() if count is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_classes": len(counts),
            "unavailable_classes": len(diagnostics) - len(counts),
            "partial_occurrence_sum": summary.total,
            "partial_occurrence_mean": summary.mean,
            "partial_occurrence_max": summary.maximum,
        })

    def class_counts(self, modules: tuple[ModuleIR, ...]) -> Mapping[str, int | None]:
        """Return immutable class-ID counts, separate from flat numerical reports.

        Every retained class enters the population. Missing required inventories,
        missing callable facts, or incomplete/cyclic ancestry makes it unavailable.
        Resolved outgoing sites remain partial: unknown members and unscanned
        libraries are omitted. Incoming uses cannot affect this outgoing count.

        Supported sites belong to their nearest enclosing class, including class
        initialization and nested functions. Inherited bodies stay only with their
        declaring class. Static implemented-method references and canonical field
        accesses count; possible runtime overrides never multiply or select sites.
        A call and its target-access record are one occurrence, while a distinct
        receiver-field access remains a separate occurrence. Read-write is one site.
        """
        def supported_occurrences(module: ModuleIR) -> tuple[SourceUseIR, ...]:
            uses = module.source_uses or ()
            target_accesses = self._call_target_accesses(uses)
            return tuple(
                use for use in uses
                if use.unsupported_context is None and use.execution_kind != "unsupported"
                and use.id not in target_accesses
            )

        symbols = {symbol.id: symbol for module in modules for symbol in module.symbols}
        classes = {key: symbol for key, symbol in symbols.items() if symbol.kind == SymbolKind.CLASS}
        ancestry = _ancestor_sets(classes)

        counts: dict[str, int | None] = {
            symbol.id: (
                0 if module.source_uses is not None and module.attributes is not None
                and ancestry[symbol.id] is not None else None
            )
            for module in modules for symbol in module.symbols
            if symbol.kind == SymbolKind.CLASS
        }
        for symbol in symbols.values():
            if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is None and symbol.owner_id in counts:
                counts[symbol.owner_id] = None
        member_owners = {
            symbol.id: symbol.callable_facts.declaring_class_id
            for symbol in symbols.values()
            if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is not None
            and symbol.callable_facts.implementation_id is not None
        }
        member_owners.update({
            attribute.id: attribute.declaring_class_id
            for module in modules for attribute in module.attributes or ()
        })
        for module in modules:
            for use in supported_occurrences(module):
                owner = use.owner_id
                while owner in symbols and owner not in classes:
                    owner = symbols[owner].owner_id
                count = counts.get(owner or "")
                if owner is None or count is None or use.resolution.status != "project":
                    continue
                target_owner = member_owners.get(use.resolution.target_id or "")
                if target_owner in (ancestry.get(owner) or ()):
                    counts[owner] = count + 1
        return MappingProxyType(counts)

    @staticmethod
    def _call_target_accesses(uses: tuple[SourceUseIR, ...]) -> frozenset[str]:
        exact_targets: set[SourceSpan] = set()
        calls_by_target: dict[tuple[str | None, str | None, ReceiverIR | None], list[SourceSpan]] = {}
        for use in uses:
            if use.kind != "call":
                continue
            exact_targets.add(use.target_span)
            if use.resolution.status == "project" and use.receiver is not None:
                key = (use.owner_id, use.resolution.target_id, use.receiver)
                calls_by_target.setdefault(key, []).append(use.target_span)
        # Parentheses enlarge the call target span, but preserve its selected target
        # and receiver. Matching the full member path preserves independent prefixes,
        # even when a receiver field and the called field share a canonical target ID.
        return frozenset(
            use.id for use in uses if use.kind == "attribute-read" and (
                use.span in exact_targets or any(
                    target.file_id == use.span.file_id
                    and (target.start_line, target.start_col) <= (use.span.start_line, use.span.start_col)
                    and (use.span.end_line, use.span.end_col) <= (target.end_line, target.end_col)
                    for target in calls_by_target.get((use.owner_id, use.resolution.target_id, use.receiver), ())
                )
            )
        )


def _ancestor_sets(classes: Mapping[str, SymbolIR]) -> Mapping[str, frozenset[str] | None]:
    ancestry: dict[str, frozenset[str] | None] = {}

    def proper_ancestors(class_id: str) -> frozenset[str] | None:
        if class_id in ancestry:
            return ancestry[class_id]
        # An active traversal is incomplete too: revisiting it detects a cycle.
        ancestry[class_id] = None
        bases = classes[class_id].direct_bases
        if bases is None:
            return None
        ancestors: set[str] = set()
        for base in bases:
            target = base.resolution.target_id
            if base.resolution.status != "project" or target not in classes:
                return None
            inherited = proper_ancestors(target)
            if inherited is None:
                return None
            ancestors.add(target)
            ancestors.update(inherited)
        ancestry[class_id] = frozenset(ancestors)
        return ancestry[class_id]

    for class_id in classes:
        proper_ancestors(class_id)
    return MappingProxyType(ancestry)
