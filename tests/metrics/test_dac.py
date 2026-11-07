"""Attribute-count DAC over retained immutable declarations."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.dac import DAC
from scb_check.tree_walking.models import AttributeIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import TypeReferenceIR


def declaration(name: str, line: int) -> SymbolIR:
    """Make class declarations with distinct physical identities."""
    return SymbolIR(
        name=name, qualified_name=name, kind=SymbolKind.CLASS,
        span=SourceSpan(file=Path("dac.py"), start_line=line, start_col=0, end_line=line, end_col=1),
    )


def field(owner: SymbolIR, name: str, *types: TypeReferenceIR) -> AttributeIR:
    """Make a canonical declared field, not a local or a parameter."""
    return AttributeIR(
        name=name, declaring_class_id=owner.id, owner_id=owner.id,
        span=owner.span, storage=frozenset({"instance"}), declared_types=types,
    )


def class_type(target: SymbolIR) -> TypeReferenceIR:
    """Supply type resolution as input rather than asking the metric to resolve."""
    return TypeReferenceIR(
        spelling=target.name, name=target.name, span=target.span, form="name", category="class",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    )


def test_attributes_not_distinct_types_are_counted_once_each() -> None:
    """Two fields of one type contribute two; repeated annotations do not add volume."""
    owner = declaration("Owner", 1)
    target = declaration("Target", 2)
    reference = class_type(target)
    first = field(owner, "first", reference, reference)
    second = field(owner, "second", reference)
    module = ModuleIR(
        language=Language.PYTHON, file=owner.file, module_name="dac", span=owner.span,
        symbols=(owner, target), attributes=(first, second),
    )
    assert DAC().attribute_sets((module,)) == {
        owner.id: frozenset({first.id, second.id}), target.id: frozenset(),
    }
    assert DAC().compute((module,)) == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_attribute_sum": 2, "partial_attribute_mean": 1.0, "partial_attribute_max": 2,
    }


@pytest.mark.parametrize("case", [
    "primitive", "other", "unknown", "external", "ambiguous", "unresolved",
    "unsupported", "missing-target", "union", "wrapper", "unannotated",
])
def test_no_class_evidence_remains_partial_zero(case: str) -> None:
    """Unknown is not proven nonclass; argument types are never flattened."""
    owner = declaration("Owner", 1)
    target = declaration("Target", 2)
    reference = class_type(target)
    if case in {"primitive", "other", "unknown"}:
        reference = reference.model_copy(update={"category": case})
    elif case in {"external", "ambiguous", "unresolved", "unsupported"}:
        reference = reference.model_copy(update={
            "resolution": TargetResolutionIR.model_validate({"status": case, "target_id": target.id}),
        })
    elif case == "missing-target":
        reference = reference.model_copy(update={
            "resolution": TargetResolutionIR(status="project", target_id="not-retained"),
        })
    elif case in {"union", "wrapper"}:
        reference = TypeReferenceIR(
            spelling="wrapper", span=owner.span, form="union" if case == "union" else "generic",
            category="other", arguments=(reference,),
        )
    attribute = field(owner, "value", *((reference,) if case != "unannotated" else ()))
    module = ModuleIR(
        language=Language.PYTHON, file=owner.file, module_name="dac", span=owner.span,
        symbols=(owner, target), attributes=(attribute,),
    )
    assert DAC().attribute_sets((module,))[owner.id] == frozenset()
    assert DAC().compute((module,))["partial_attribute_sum"] == 0


def test_class_identity_and_canonical_field_identity_are_not_names_or_occurrences() -> None:
    """Retained same-name classes stay separate; duplicate field records count once."""
    first = declaration("Repeated", 1)
    second = declaration("Repeated", 2)
    first_field = field(first, "same_name", class_type(first))
    second_field = field(second, "same_name", class_type(second))
    module = ModuleIR(
        language=Language.PYTHON, file=first.file, module_name="dac", span=first.span,
        symbols=(first, second), attributes=(first_field, first_field, second_field),
    )
    assert DAC().attribute_sets((module,)) == {
        first.id: frozenset({first_field.id}), second.id: frozenset({second_field.id}),
    }
    assert DAC().compute((module,))["partial_attribute_sum"] == 2


def test_known_class_type_does_not_require_target_attribute_extraction() -> None:
    """A retained class is a type even when its own field inventory is unavailable."""
    owner = declaration("Owner", 1)
    target = declaration("Target", 2)
    attribute = field(owner, "value", class_type(target))
    available = ModuleIR(
        language=Language.PYTHON, file=owner.file, module_name="dac", span=owner.span,
        symbols=(owner,), attributes=(attribute,),
    )
    unsupported = ModuleIR(
        language=Language.RUST, file=target.file, module_name="unsupported", span=target.span,
        symbols=(target,),
    )
    assert DAC().attribute_sets((available, unsupported)) == {
        owner.id: frozenset({attribute.id}), target.id: None,
    }
    assert DAC().compute((available, unsupported)) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_attribute_sum": 1, "partial_attribute_mean": 1.0, "partial_attribute_max": 1,
    }


def test_unavailable_extraction_and_empty_population_are_not_measured_zero() -> None:
    """Only availability of the field inventory controls whether a class is measured."""
    owner = declaration("Owner", 1)
    unknown = declaration("Unknown", 2)
    available = ModuleIR(
        language=Language.PYTHON, file=owner.file, module_name="dac", span=owner.span,
        symbols=(owner,), attributes=(),
    )
    unsupported = ModuleIR(
        language=Language.RUST, file=unknown.file, module_name="unsupported", span=unknown.span,
        symbols=(unknown,),
    )
    assert DAC().attribute_sets((available, unsupported)) == {owner.id: frozenset(), unknown.id: None}
    assert DAC().compute((available, unsupported)) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_attribute_sum": 0, "partial_attribute_mean": 0.0, "partial_attribute_max": 0,
    }
    assert DAC().compute((unsupported,)) == {
        "measured_classes": 0, "unavailable_classes": 1,
        "partial_attribute_sum": None, "partial_attribute_mean": None, "partial_attribute_max": None,
    }
    assert DAC().compute(()) == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_attribute_sum": None, "partial_attribute_mean": None, "partial_attribute_max": None,
    }
    diagnostics = DAC().attribute_sets((available,))
    with pytest.raises(TypeError):
        cast("MutableMapping[str, frozenset[str] | None]", diagnostics)[owner.id] = None
    result = DAC().compute((available,))
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | float | None]", result)["measured_classes"] = 99
