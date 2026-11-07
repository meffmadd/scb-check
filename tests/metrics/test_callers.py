"""Distinct incoming caller counts over immutable retained facts."""

from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.callers import CallerSets
from scb_check.metrics.callers import DistinctCallers
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def callable_symbol(name: str, line: int, file: str = "model.py") -> SymbolIR:
    """Make a function declaration with supported callable extraction."""
    span = SourceSpan(file=Path(file), start_line=line, start_col=0, end_line=line, end_col=1)
    return SymbolIR(
        name=name, qualified_name=name, kind=SymbolKind.FUNCTION, span=span,
        callable_facts=CallableIR(
            binding="function", body_kind="implemented", body_span=span,
            implementation_id=span.entity_id(SymbolKind.FUNCTION),
        ),
    )


def call(owner: SymbolIR, target: SymbolIR) -> SourceUseIR:
    """Record a static project call without running a resolver."""
    return SourceUseIR(
        kind="call", span=owner.span, target_span=owner.span,
        target_spelling=target.name, target_form="name", owner_id=owner.id,
        execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    )


def module(symbols: tuple[SymbolIR, ...], uses: tuple[SourceUseIR, ...] = ()) -> ModuleIR:
    """Retain declarations and occurrences in one logical module."""
    return ModuleIR(
        language=Language.PYTHON, file=symbols[0].file, module_name="model",
        span=symbols[0].span, symbols=symbols, source_uses=uses,
    )


def test_distinct_callers_include_recursion_and_measured_zero() -> None:
    """Two sites from one caller count once; recursion adds one distinct caller."""
    target = callable_symbol("target", 1)
    first = callable_symbol("first", 2)
    second = callable_symbol("second", 3)
    retained = module((target, first, second), (
        call(first, target), call(first, target), call(second, target), call(target, target),
    ))

    assert DistinctCallers().caller_sets((retained,)) == {
        target.id: CallerSets(frozenset({first.id, second.id, target.id}), frozenset()),
        first.id: CallerSets(frozenset(), frozenset()),
        second.id: CallerSets(frozenset(), frozenset()),
    }
    assert DistinctCallers().compute((retained,)) == {
        "measured_callables": 3, "unavailable_callables": 0,
        "partial_caller_sum": 3, "partial_caller_mean": 1.0, "partial_caller_max": 3,
        "partial_same_module_sum": 3, "partial_cross_module_sum": 0,
    }


def test_static_selection_partitions_modules_without_runtime_expansion() -> None:
    """Equal module names are not equal identities; runtime alternatives add no callers."""
    target = callable_symbol("target", 1)
    override = callable_symbol("override", 2)
    source = callable_symbol("source", 1, "other/model.py")
    use = call(source, target).model_copy(update={
        "runtime_targets": RuntimeTargetsIR(
            status="approximate", target_ids=(override.id,),
            assumption="closed-project-hierarchy",
        ),
    })
    modules = (module((target, override)), module((source,), (use, use)))
    assert DistinctCallers().caller_sets(modules) == {
        target.id: CallerSets(frozenset(), frozenset({source.id})),
        override.id: CallerSets(frozenset(), frozenset()),
        source.id: CallerSets(frozenset(), frozenset()),
    }
    assert DistinctCallers().compute(modules) == {
        "measured_callables": 3, "unavailable_callables": 0,
        "partial_caller_sum": 1, "partial_caller_mean": 1 / 3, "partial_caller_max": 1,
        "partial_same_module_sum": 0, "partial_cross_module_sum": 1,
    }


@pytest.mark.parametrize("status", ["unresolved", "external", "ambiguous", "unsupported"])
def test_nonproject_calls_do_not_create_known_incoming_edges(status: str) -> None:
    """Candidate IDs and runtime candidates cannot substitute for static project selection."""
    target = callable_symbol("target", 1)
    source = callable_symbol("source", 2)
    use = call(source, target).model_copy(update={
        "resolution": TargetResolutionIR.model_validate({
            "status": status, "target_id": target.id, "candidate_ids": (target.id,),
        }),
        "runtime_targets": RuntimeTargetsIR(
            status="complete", target_ids=(target.id,), assumption="closed-project-hierarchy",
        ),
    })
    result = DistinctCallers().compute((module((target, source), (use,)),))
    assert result["measured_callables"] == 2
    assert result["partial_caller_sum"] == 0


@pytest.mark.parametrize("execution_kind", ["module", "class", "unsupported"])
def test_nonfunction_execution_never_invents_a_caller(execution_kind: str) -> None:
    """Even a lexical function owner cannot make class initialization a function call."""
    target = callable_symbol("target", 1)
    outer = callable_symbol("outer", 2)
    use = SourceUseIR.model_validate({
        **call(outer, target).model_dump(), "execution_kind": execution_kind,
    })
    assert DistinctCallers().compute((module((target, outer), (use,)),))["partial_caller_sum"] == 0


@pytest.mark.parametrize("owner_id", [None, "unknown-owner"])
def test_missing_callable_owners_are_not_inferred(owner_id: str | None) -> None:
    """A resolved destination alone does not establish a callable caller."""
    target = callable_symbol("target", 1)
    use = call(target, target).model_copy(update={"owner_id": owner_id})
    assert DistinctCallers().compute((module((target,), (use,)),))["partial_caller_sum"] == 0


@pytest.mark.parametrize("missing", ["callable_facts", "source_uses"])
def test_unavailable_population_is_not_a_measured_zero(missing: str) -> None:
    """Missing extraction stays null; supported zeros still enter the measured population."""
    supported = callable_symbol("supported", 1)
    unsupported = callable_symbol("unsupported", 1, "other.py")
    unavailable = module((unsupported,))
    if missing == "callable_facts":
        unavailable = module((unsupported.model_copy(update={"callable_facts": None}),))
    else:
        unavailable = unavailable.model_copy(update={"source_uses": None})
    modules = (module((supported,)), unavailable)
    assert DistinctCallers().caller_sets(modules) == {
        supported.id: CallerSets(frozenset(), frozenset()), unsupported.id: None,
    }
    assert DistinctCallers().compute(modules) == {
        "measured_callables": 1, "unavailable_callables": 1,
        "partial_caller_sum": 0, "partial_caller_mean": 0.0, "partial_caller_max": 0,
        "partial_same_module_sum": 0, "partial_cross_module_sum": 0,
    }
    assert DistinctCallers().compute((unavailable,)) == {
        "measured_callables": 0, "unavailable_callables": 1,
        "partial_caller_sum": None, "partial_caller_mean": None, "partial_caller_max": None,
        "partial_same_module_sum": None, "partial_cross_module_sum": None,
    }


def test_empty_population_has_unavailable_summaries() -> None:
    """No callable population has no measured aggregate, rather than zero use."""
    assert DistinctCallers().compute(()) == {
        "measured_callables": 0, "unavailable_callables": 0,
        "partial_caller_sum": None, "partial_caller_mean": None, "partial_caller_max": None,
        "partial_same_module_sum": None, "partial_cross_module_sum": None,
    }


@pytest.mark.parametrize("field_name", ["same_module", "cross_module"])
def test_diagnostics_and_report_are_read_only(field_name: str) -> None:
    """Neither flat reports nor nested caller diagnostics allow mutation."""
    target = callable_symbol("target", 1)
    modules = (module((target,), (call(target, target),)),)
    diagnostics = DistinctCallers().caller_sets(modules)
    with pytest.raises(TypeError):
        cast("MutableMapping[str, CallerSets | None]", diagnostics)[target.id] = None
    value = diagnostics[target.id]
    assert value is not None
    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, frozenset())
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | float | None]", DistinctCallers().compute(modules))["partial_caller_sum"] = 9
