"""Direct response sets over immutable retained project facts."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import Literal, cast

import pytest

from scb_check.metrics.rfc import RFC
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def declaration(name: str, line: int, owner: SymbolIR | None = None) -> SymbolIR:
    """Create a declaration without parsing or performing language resolution."""
    kind = SymbolKind.CLASS if owner is None else SymbolKind.METHOD
    span = SourceSpan(file=Path("response.py"), start_line=line, start_col=0, end_line=line, end_col=1)
    return SymbolIR(
        name=name, qualified_name=name, kind=kind, span=span,
        owner_id=owner.id if owner else None,
        owner_qualified_name=owner.name if owner else None,
        direct_bases=() if owner is None else None,
        callable_facts=CallableIR(
            declaring_class_id=owner.id, binding="instance", body_kind="implemented",
            body_span=span, implementation_id=span.entity_id(kind),
        ) if owner else None,
    )


def project_with(
    symbols: tuple[SymbolIR, ...], uses: tuple[SourceUseIR, ...] = (),
) -> ProjectIR:
    """Supply explicit retained member selections for a supported source module."""
    members = {
        symbol.id: {
            member.name: TargetResolutionIR(status="project", target_id=member.id)
            for member in symbols if member.owner_id == symbol.id
        }
        for symbol in symbols if symbol.kind == SymbolKind.CLASS
    }
    return ProjectIR(
        modules=(ModuleIR(
            language=Language.PYTHON, file=symbols[0].file, module_name="response",
            span=symbols[0].span, symbols=symbols, source_uses=uses,
        ),), member_lookup=members, class_member_lookup=members,
    )


def call(
    owner: SymbolIR, target: SymbolIR, line: int, *,
    possible: tuple[SymbolIR, ...] | None = None,
    status: Literal["complete", "approximate"] = "complete",
) -> SourceUseIR:
    """Record supplied possible bodies independently of the static selection."""
    span = owner.span.model_copy(update={"start_line": line, "end_line": line})
    return SourceUseIR(
        kind="call", span=span, target_span=span, target_spelling=target.name,
        target_form="attribute", owner_id=owner.id, execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
        runtime_targets=RuntimeTargetsIR(
            status=status, target_ids=tuple(method.id for method in possible or (target,)),
            assumption="closed-project-hierarchy",
        ),
    )


def test_isolated_class_keeps_its_own_method_population() -> None:
    """Even without calls an isolated class responds with its two declared methods."""
    isolated = declaration("Isolated", 1)
    first = declaration("first", 2, isolated)
    second = declaration("second", 3, isolated)
    project = project_with((isolated, first, second))

    assert RFC().response_sets(project) == {isolated.id: frozenset({first.id, second.id})}
    assert RFC().compute(project) == {
        "measured_classes": 1, "unavailable_classes": 0,
        "partial_response_sum": 2, "partial_response_mean": 2.0, "partial_response_max": 2,
    }


def test_direct_response_deduplicates_recursion_and_excludes_second_hop() -> None:
    """A→B→C adds B, not C, to A; repeated A→B and A→A add no identities."""
    a, b, c = (declaration(name, line) for line, name in enumerate(("A", "B", "C"), 1))
    am = declaration("run", 4, a)
    bm = declaration("work", 5, b)
    cm = declaration("finish", 6, c)
    project = project_with((a, b, c, am, bm, cm), (
        call(am, bm, 7), call(am, bm, 8), call(am, am, 9), call(bm, cm, 10),
    ))

    assert RFC().response_sets(project) == {
        a.id: frozenset({am.id, bm.id}), b.id: frozenset({bm.id, cm.id}),
        c.id: frozenset({cm.id}),
    }
    assert RFC().compute(project) == {
        "measured_classes": 3, "unavailable_classes": 0,
        "partial_response_sum": 5, "partial_response_mean": 5 / 3, "partial_response_max": 2,
    }


@pytest.mark.parametrize("status", ["complete", "approximate"])
def test_possible_method_bodies_replace_static_selection(status: Literal["complete", "approximate"]) -> None:
    """Both complete and approximate supplied bodies count; the static-only method does not."""
    client = declaration("Client", 1)
    base = declaration("Base", 2)
    child = declaration("Child", 3)
    run = declaration("run", 4, client)
    selected = declaration("selected", 5, base)
    possible = declaration("possible", 6, child)
    project = project_with((client, base, child, run, selected, possible), (
        call(run, selected, 7, possible=(possible,), status=status),
    ))

    assert RFC().response_sets(project)[client.id] == frozenset({run.id, possible.id})


@pytest.mark.parametrize("missing", ["source_uses", "direct_bases", "member_lookup", "class_member_lookup", "callable_facts"])
def test_unsupported_population_is_not_a_measured_zero(missing: str) -> None:
    """Missing extraction stays unavailable, while an extracted empty class is zero."""
    unavailable = declaration("Unavailable", 1)
    method = declaration("work", 2, unavailable)
    project = project_with((unavailable, method))
    if missing in {"member_lookup", "class_member_lookup"}:
        project = project.model_copy(update={missing: {}})
    elif missing == "source_uses":
        project = project.model_copy(update={"modules": (project.modules[0].model_copy(update={missing: None}),)})
    else:
        changed = tuple(
            symbol.model_copy(update={missing: None}) if (
                symbol.id == (method.id if missing == "callable_facts" else unavailable.id)
            ) else symbol for symbol in project.modules[0].symbols
        )
        project = ProjectIR(
            modules=(project.modules[0].model_copy(update={"symbols": changed}),),
            member_lookup=project.member_lookup, class_member_lookup=project.class_member_lookup,
        )
    empty = declaration("Empty", 3)
    empty_project = project_with((empty,))
    combined = ProjectIR(
        modules=(*project.modules, *empty_project.modules),
        member_lookup={**project.member_lookup, **empty_project.member_lookup},
        class_member_lookup={**project.class_member_lookup, **empty_project.class_member_lookup},
    )

    assert RFC().response_sets(combined) == {unavailable.id: None, empty.id: frozenset()}
    assert RFC().compute(combined) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_response_sum": 0, "partial_response_mean": 0.0, "partial_response_max": 0,
    }
    assert RFC().compute(project) == {
        "measured_classes": 0, "unavailable_classes": 1,
        "partial_response_sum": None, "partial_response_mean": None, "partial_response_max": None,
    }


@pytest.mark.parametrize("excluded", ["static_only", "reference", "class_execution", "unsupported_context"])
def test_only_supported_direct_call_evidence_expands_response(excluded: str) -> None:
    """A known static declaration or a non-call occurrence is not a possible direct callee."""
    client = declaration("Client", 1)
    target = declaration("Target", 2)
    run = declaration("run", 3, client)
    work = declaration("work", 4, target)
    use = call(run, work, 5)
    if excluded == "static_only":
        use = use.model_copy(update={"runtime_targets": RuntimeTargetsIR()})
    elif excluded == "reference":
        use = use.model_copy(update={"kind": "attribute-read"})
    elif excluded == "class_execution":
        use = use.model_copy(update={"execution_kind": "class"})
    else:
        use = use.model_copy(update={"unsupported_context": "lambda"})
    project = project_with((client, target, run, work), (use,))

    assert RFC().response_sets(project)[client.id] == frozenset({run.id})


def test_retained_selections_define_population_without_new_inheritance_resolution() -> None:
    """A class lookup can preserve a method hidden by an uncertain instance binding."""
    a = declaration("A", 1)
    b = declaration("B", 2)
    am = declaration("local", 3, a)
    bm = declaration("retained", 4, b)
    project = project_with((a, b, am, bm))
    project = ProjectIR(
        modules=project.modules,
        member_lookup={a.id: {"retained": TargetResolutionIR(status="ambiguous", candidate_ids=(bm.id,))}, b.id: {}},
        class_member_lookup={a.id: {"retained": TargetResolutionIR(status="project", target_id=bm.id)}, b.id: {}},
    )

    assert RFC().response_sets(project) == {a.id: frozenset({bm.id}), b.id: frozenset()}


def test_inherited_method_with_unavailable_call_inventory_makes_class_unavailable() -> None:
    """A subclass cannot measure the direct response of an unextracted inherited body."""
    base = declaration("Base", 1)
    method = declaration("inherited", 2, base)
    child = declaration("Child", 3)
    base_project = project_with((base, method))
    child_project = project_with((child,))
    selection = {"inherited": TargetResolutionIR(status="project", target_id=method.id)}
    project = ProjectIR(
        modules=(base_project.modules[0].model_copy(update={"source_uses": None}), *child_project.modules),
        member_lookup={base.id: selection, child.id: selection},
        class_member_lookup={base.id: selection, child.id: selection},
    )

    assert RFC().response_sets(project) == {base.id: None, child.id: None}


def test_empty_project_and_diagnostics_are_read_only() -> None:
    """No population is unavailable, and callers cannot modify retained measurements."""
    assert RFC().compute(ProjectIR()) == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_response_sum": None, "partial_response_mean": None, "partial_response_max": None,
    }
    empty = declaration("Empty", 1)
    project = project_with((empty,))
    responses = RFC().response_sets(project)
    with pytest.raises(TypeError):
        cast("MutableMapping[str, frozenset[str] | None]", responses)[empty.id] = None
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | float | None]", RFC().compute(project))["measured_classes"] = 9
