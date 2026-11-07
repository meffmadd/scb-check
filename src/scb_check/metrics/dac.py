"""Partial retained-project attribute-count Data Abstraction Coupling (DAC)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from scb_check.metrics._counts import summarize_counts
from scb_check.metrics.base import Metric
from scb_check.metrics.units import Unit
from scb_check.models import MetricResult
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolKind


class DAC(Metric[[tuple[ModuleIR, ...]]]):
    """Count declared fields with known retained-project class types, not distinct types.

    Each canonical attribute contributes at most one, even if several annotations
    name classes. Two fields of the same class type contribute two. Both class
    and instance fields count; self and ancestor types are eligible. Inherited
    fields stay with their declaring class, not with subclasses. Parameters,
    locals, primitive types, and nonclass types do not count.

    Use only the outer type's retained category and resolution. A project generic
    class can count, but its arguments are never flattened: collections, unions,
    and typing wrappers do not become fields of their argument types. Python
    object references count through their declared class type; the current IR
    supplies no C++ pointer/reference/array underlying-type normalization.

    Every retained class declaration is in the population, including nested and
    repeated declarations. Library classes count only when their source is
    included as project input. No quality thresholds or scores are implied.

    Results are explicitly partial: library classes outside retained source,
    unannotated fields, unresolved types, and unsupported assignment forms can
    hide composition. Missing inference is not evidence of a nonclass type.
    Repeated or conflicting annotations supply positive evidence only, not a
    claim about the field's unique runtime type. Incoming uses do not add fields;
    writes outside supported declaring-class extraction may be missing.

    Briand, Daly & Wüst (1999), Definition 24 and section 3.6:
    https://doi.org/10.1109/32.748920
    Li & Henry (1993), original provenance:
    https://doi.org/10.1016/0164-1212(93)90077-B
    """

    units: ClassVar[dict[str, Unit]] = {
        "measured_classes": "classes",
        "unavailable_classes": "classes",
        "partial_attribute_sum": "attributes",
        "partial_attribute_mean": "attributes",
        "partial_attribute_max": "attributes",
    }

    def compute(self, modules: tuple[ModuleIR, ...]) -> MetricResult:
        """Summarize supported classes using analyzer conventions, not a paper formula.

        Unknown field types are skipped within partial counts. Classes without
        attribute extraction are unavailable and excluded from the mean. With
        no measured classes the sum, mean, and maximum are all `None`.
        """
        # Summarize only measured classes, retaining supported partial zeros.
        attributes = self.attribute_sets(modules)
        counts = tuple(len(value) for value in attributes.values() if value is not None)
        summary = summarize_counts(counts)
        return MappingProxyType({
            "measured_classes": len(counts),
            "unavailable_classes": len(attributes) - len(counts),
            "partial_attribute_sum": summary.total,
            "partial_attribute_mean": summary.mean,
            "partial_attribute_max": summary.maximum,
        })

    def attribute_sets(
        self, modules: tuple[ModuleIR, ...],
    ) -> Mapping[str, frozenset[str] | None]:
        """Return immutable eligible attribute IDs keyed by class declaration ID.

        `None` means attribute extraction is unavailable; an empty set is only
        an observed partial zero. Class declarations are never merged by name.
        No source reads, inference, or new name resolution are performed.
        """
        # Index the retained class population and extraction availability.
        attributes: dict[str, set[str] | None] = {
            symbol.id: set() if module.attributes is not None else None
            for module in modules for symbol in module.symbols
            if symbol.kind == SymbolKind.CLASS
        }
        # Count canonical fields only for their declaring class, using positive type evidence.
        for module in modules:
            for attribute in module.attributes or ():
                eligible = attributes.get(attribute.declaring_class_id)
                if eligible is not None and any(
                    reference.form in {"name", "generic"}
                    and reference.category == "class"
                    and reference.resolution.status == "project"
                    and reference.resolution.target_id in attributes
                    for reference in attribute.declared_types
                ):
                    eligible.add(attribute.id)
        # Freeze both the per-class sets and the diagnostic mapping.
        return MappingProxyType({
            class_id: None if value is None else frozenset(value)
            for class_id, value in attributes.items()
        })
