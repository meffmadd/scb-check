"""Partial retained-project CBO: distinct partners from member use in either direction."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolKind


class CBO(Metric[[tuple[ModuleIR, ...]]]):
    """Count other project classes connected by method calls or attribute access.

    A partner is another class connected through a method call or attribute
    access in either direction. If class `A` calls a method on class `B`, each
    counts the other as one partner. Repeated calls still count once. Include
    uses of inherited members, but exclude a class's use of its own members.
    Results are partial: classes outside the analyzed project are excluded,
    unknown references are skipped, and some call targets are estimates.

    Briand, Daly & Wüst (1999), "A unified framework for coupling measurement in
    object-oriented systems", Definitions 17 and 20:
    https://doi.org/10.1109/32.748920
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_classes": "classes",
        "unavailable_classes": "classes",
        "partial_partner_sum": "partners",
        "partial_partner_mean": "partners",
        "partial_partner_max": "partners",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize available partial class counts; an empty population is unavailable."""
        partners = self.partner_sets(modules)
        counts = [len(value) for value in partners.values() if value is not None]
        return MappingProxyType({
            "measured_classes": len(counts),
            "unavailable_classes": len(partners) - len(counts),
            "partial_partner_sum": sum(counts) if counts else None,
            "partial_partner_mean": sum(counts) / len(counts) if counts else None,
            "partial_partner_max": max(counts) if counts else None,
        })

    def partner_sets(
        self, modules: tuple[ModuleIR, ...]
    ) -> Mapping[str, frozenset[str] | None]:
        """Return separate immutable diagnostics keyed by class declaration ID.

        `None` denotes unsupported extraction, not an observed empty partner set.
        Execution belongs to the nearest enclosing class, including nested functions;
        inherited bodies stay with their declaring class rather than being copied.
        """
        symbols = {symbol.id: symbol for module in modules for symbol in module.symbols}
        partners: dict[str, set[str] | None] = {
            symbol.id: (
                set() if module.source_uses is not None and module.attributes is not None
                and symbol.direct_bases is not None else None
            )
            for module in modules for symbol in module.symbols
            if symbol.kind == SymbolKind.CLASS
        }
        method_classes = {
            symbol.id: symbol.callable_facts.declaring_class_id
            for symbol in symbols.values()
            if symbol.kind == SymbolKind.METHOD and symbol.callable_facts is not None
            and symbol.callable_facts.implementation_id is not None
        }
        attribute_classes = {
            attribute.id: attribute.declaring_class_id
            for module in modules for attribute in module.attributes or ()
        }
        for module in modules:
            for use in module.source_uses or ():
                owner_id = use.owner_id
                while owner_id in symbols and owner_id not in partners:
                    owner_id = symbols[owner_id].owner_id
                if owner_id is None:
                    continue
                source = partners.get(owner_id)
                if source is None:
                    continue
                if use.kind == "call":
                    # Possible implementation bodies take precedence over the static
                    # declaration. Unavailable sets fall back to explicitly partial evidence.
                    targets = use.runtime_targets.target_ids or (use.resolution.target_id,)
                    target_classes = {method_classes.get(target) for target in targets if target is not None}
                else:
                    # A method's attribute-read accompanies a call but is not itself
                    # a method invocation; only actual fields count as attribute use.
                    target_classes = {attribute_classes.get(use.resolution.target_id or "")}
                for target_id in target_classes:
                    if target_id is None or target_id == owner_id:
                        continue
                    destination = partners.get(target_id)
                    if destination is not None:
                        source.add(target_id)
                        destination.add(owner_id)
        return MappingProxyType({
            class_id: None if value is None else frozenset(value)
            for class_id, value in partners.items()
        })
