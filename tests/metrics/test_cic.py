"""CIC's static physical-site and availability contracts over immutable IR."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.cic import CIC
from scb_check.tree_walking.models import AttributeIR
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ReceiverIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import TypeReferenceIR


def span(line: int, start: int = 0, end: int = 10) -> SourceSpan:
    """Locate one physical site with independently selectable receiver/target spans."""
    return SourceSpan(file=Path("cic.py"), start_line=line, end_line=line, start_col=start, end_col=end)


def declaration(name: str, kind: SymbolKind, line: int, owner: str | None = None) -> SymbolIR:
    """Retain explicit ownership and a method body identity distinct from its declaration."""
    return SymbolIR(
        name=name, qualified_name=name, kind=kind, span=span(line), owner_id=owner, owner_qualified_name=owner,
        direct_bases=() if kind == SymbolKind.CLASS else None,
        callable_facts=CallableIR(
            declaring_class_id=owner, binding="instance", body_kind="implemented",
            body_span=span(line), implementation_id=f"body:{name}",
        ) if kind == SymbolKind.METHOD else None,
    )


def subclass(name: str, line: int, *bases: SymbolIR) -> SymbolIR:
    """Supply already-resolved direct base facts without language resolution."""
    return declaration(name, SymbolKind.CLASS, line).model_copy(update={
        "direct_bases": tuple(TypeReferenceIR(
            spelling=base.name, span=span(line), form="name", category="class",
            resolution=TargetResolutionIR(status="project", target_id=base.id),
        ) for base in bases),
    })


def use(owner: SymbolIR, target: str, line: int) -> SourceUseIR:
    """Record one physical statically resolved call occurrence."""
    return SourceUseIR(
        kind="call", span=span(line), target_span=span(line, end=8),
        target_spelling="receiver.member", target_form="attribute",
        owner_id=owner.id, execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target),
    )


def module(symbols: tuple[SymbolIR, ...], uses: tuple[SourceUseIR, ...] = ()) -> ModuleIR:
    """Build supported empty inventories rather than unavailable extraction."""
    return ModuleIR(
        language=Language.PYTHON, file=Path("cic.py"), module_name="cic", span=span(1),
        symbols=symbols, source_uses=uses, attributes=(),
    )


def test_static_ancestor_implementation_and_bare_references_not_runtime_overrides() -> None:
    """Runtime overrides cannot change static eligibility; ambiguous targets add nothing."""
    root = subclass("Root", 1)
    child = subclass("Child", 2, root)
    method = declaration("work", SymbolKind.METHOD, 3, root.id)
    own = declaration("work_override", SymbolKind.METHOD, 4, child.id)
    assert method.callable_facts is not None
    assert own.callable_facts is not None
    runtime_own = RuntimeTargetsIR(
        status="complete", target_ids=("body:work_override",),
        assumption="closed-project-hierarchy",
    )
    runtime_ancestor = RuntimeTargetsIR(
        status="approximate", target_ids=("body:work",),
        assumption="closed-project-hierarchy",
    )
    evidence = module((root, child, method, own), (
        use(own, method.id, 5).model_copy(update={"runtime_targets": runtime_own}),
        use(own, own.id, 6).model_copy(update={"runtime_targets": runtime_ancestor}),
        use(own, method.id, 7).model_copy(update={"kind": "attribute-read"}),
        use(own, method.id, 8).model_copy(update={
            "resolution": TargetResolutionIR(status="ambiguous", candidate_ids=(method.id, own.id)),
        }),
    ))
    assert CIC().class_counts((evidence,)) == {root.id: 0, child.id: 2}


def test_call_target_access_deduplicates_but_receiver_field_and_repeated_sites_survive() -> None:
    """Only the call target duplicate is removed; every distinct eligible site survives."""
    root = subclass("Root", 1)
    child = subclass("Child", 2, root)
    method = declaration("run", SymbolKind.METHOD, 3, child.id)
    target = declaration("work", SymbolKind.METHOD, 4, root.id)
    field = AttributeIR(name="receiver", declaring_class_id=root.id, owner_id=root.id,
                        span=span(5), storage=frozenset({"class"}))
    call = use(method, target.id, 10)
    evidence = module((root, child, method, target), (
        call,
        call.model_copy(update={"kind": "attribute-read", "span": call.target_span}),
        use(method, field.id, 10).model_copy(update={"kind": "attribute-read", "span": span(10, end=4)}),
        use(method, target.id, 11),
        use(method, field.id, 12).model_copy(update={"kind": "attribute-read-write"}),
        use(method, field.id, 13).model_copy(update={"kind": "attribute-delete"}),
        use(method, field.id, 14).model_copy(update={"kind": "attribute-write"}),
    )).model_copy(update={"attributes": (field,)})
    assert CIC().class_counts((evidence,)) == {root.id: 0, child.id: 6}


def test_parenthesized_call_and_its_target_access_are_one_occurrence() -> None:
    """Wrapper spans differ, but the retained target still identifies one physical use."""
    root = subclass("Root", 1)
    child = subclass("Child", 2, root)
    method = declaration("run", SymbolKind.METHOD, 3, child.id)
    target = declaration("work", SymbolKind.METHOD, 4, root.id)
    call = use(method, target.id, 10).model_copy(update={
        "span": span(10, end=13), "target_span": span(10, end=11),
        "target_spelling": "(self.work)", "target_form": "expression",
        "receiver": ReceiverIR(
            resolution=TargetResolutionIR(reason="parameter"), member_path=("work",),
        ),
    })
    access = call.model_copy(update={
        "kind": "attribute-read", "span": span(10, 1, 10), "target_span": span(10, 1, 10),
        "target_spelling": "self.work", "target_form": "attribute",
    })
    evidence = module((root, child, method, target), (call, access))
    assert CIC().class_counts((evidence,)) == {root.id: 0, child.id: 1}
    assert CIC().compute((evidence,)) == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_occurrence_sum": 1, "partial_occurrence_mean": 0.5, "partial_occurrence_max": 1,
    }


@pytest.mark.parametrize("missing", ["source_uses", "attributes", "direct_bases", "callable_facts"])
def test_missing_extraction_is_unavailable_not_partial_zero(missing: str) -> None:
    """Required inventory gaps exclude a class from the measured denominator."""
    root = subclass("Root", 1)
    child = subclass("Child", 2, root)
    method = declaration("run", SymbolKind.METHOD, 3, child.id)
    supported = module((root,))
    if missing == "direct_bases":
        child = child.model_copy(update={"direct_bases": None})
    elif missing == "callable_facts":
        method = method.model_copy(update={"callable_facts": None})
    unsupported = module((child, method))
    if missing in {"source_uses", "attributes"}:
        unsupported = unsupported.model_copy(update={missing: None})
    assert CIC().class_counts((supported, unsupported)) == {root.id: 0, child.id: None}
    assert CIC().compute((supported, unsupported)) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_occurrence_sum": 0, "partial_occurrence_mean": 0.0, "partial_occurrence_max": 0,
    }


@pytest.mark.parametrize("status", ["external", "unresolved", "ambiguous", "unsupported", "project"])
def test_incomplete_transitive_ancestry_is_unavailable(status: str) -> None:
    """No retained complete ancestry means no measured class, even for descendants."""
    root = subclass("Root", 1).model_copy(update={"direct_bases": (TypeReferenceIR.model_validate({
        "spelling": "Unknown", "span": span(1), "form": "name",
        "resolution": {"status": status, "target_id": "missing"},
    }),)})
    child = subclass("Child", 2, root)
    assert CIC().class_counts((module((root, child)),)) == {root.id: None, child.id: None}
    assert CIC().compute((module((root, child)),)) == {
        "measured_classes": 0, "unavailable_classes": 2,
        "partial_occurrence_sum": None, "partial_occurrence_mean": None, "partial_occurrence_max": None,
    }


def test_cycles_are_unavailable_and_diamond_ancestry_does_not_multiply_sites() -> None:
    """Multiple paths are one ancestor relation, while cycles cannot establish ancestry."""
    root = subclass("Root", 1)
    left = subclass("Left", 2, root)
    right = subclass("Right", 3, root)
    leaf = subclass("Leaf", 4, left, right)
    target = declaration("work", SymbolKind.METHOD, 5, root.id)
    evidence = module((root, left, right, leaf, target), (use(leaf, target.id, 6),))
    assert CIC().class_counts((evidence,)) == {root.id: 0, left.id: 0, right.id: 0, leaf.id: 1}
    cyclic_root = subclass("Root", 1, leaf)
    cyclic = evidence.model_copy(update={"symbols": (cyclic_root, left, right, leaf, target)})
    assert set(CIC().class_counts((cyclic,)).values()) == {None}


def test_empty_population_and_read_only_outputs() -> None:
    """Empty populations have null summaries and both outputs reject mutation."""
    result = CIC().compute(())
    assert result == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_occurrence_sum": None, "partial_occurrence_mean": None, "partial_occurrence_max": None,
    }
    with pytest.raises(TypeError):
        cast("MutableMapping[str, object]", result)["measured_classes"] = 1
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | None]", CIC().class_counts(()))["class"] = 1
