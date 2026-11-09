"""Method RIC over narrow immutable facts, without parsing or resolution."""

import sys
import tracemalloc
from collections.abc import Callable
from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import FrameType
from typing import cast

import pytest

from scb_check.metrics.ric import RIC
from scb_check.metrics.ric import RICPair
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def declaration(name: str, line: int, owner: SymbolIR | None = None) -> SymbolIR:
    """Retain a class or a method with canonical declaration ownership."""
    span = SourceSpan(file=Path("model.py"), start_line=line, start_col=0, end_line=line, end_col=1)
    return SymbolIR(
        name=name, qualified_name=name, span=span,
        kind=SymbolKind.METHOD if owner else SymbolKind.CLASS,
        owner_id=owner.id if owner else None,
        owner_qualified_name=owner.qualified_name if owner else None,
        direct_bases=None if owner else (),
        callable_facts=CallableIR(
            declaring_class_id=owner.id, binding="instance", body_kind="implemented",
            body_span=span, implementation_id=span.entity_id(SymbolKind.METHOD),
        ) if owner else None,
    )


def call(owner: SymbolIR, target: SymbolIR) -> SourceUseIR:
    """A direct static project call; repeated occurrences remain separate input facts."""
    return SourceUseIR(
        kind="call", span=owner.span, target_span=owner.span,
        target_spelling=target.name, target_form="attribute", owner_id=owner.id,
        execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    )


def module(symbols: tuple[SymbolIR, ...], uses: tuple[SourceUseIR, ...] = ()) -> ModuleIR:
    """A supported inventory with no hidden source dependency."""
    return ModuleIR(
        language=Language.PYTHON, file=Path("model.py"), module_name="model",
        span=symbols[0].span, symbols=symbols, source_uses=uses,
    )


def assert_aggregates_match_diagnostics(modules: tuple[ModuleIR, ...]) -> None:
    """Compare sparse aggregate results with the public explicit all-pair view."""
    diagnostics = RIC().pair_diagnostics(modules)
    ratios = [pair.ratio for pair in diagnostics.values() if pair is not None]
    assert RIC().compute(modules) == {
        "measured_pairs": len(ratios), "unavailable_pairs": len(diagnostics) - len(ratios),
        "partial_ratio_mean": sum(ratios) / len(ratios) if ratios else None,
        "partial_ratio_max": max(ratios) if ratios else None,
    }


def test_zero_call_aggregate_has_linear_resource_budget() -> None:
    """Zero-pair population size must not dictate aggregate storage or executed work."""
    class_count = 200
    symbols = []
    for index in range(class_count):
        owner = declaration(f"C{index}", index * 4 + 1)
        symbols.append(owner)
        symbols.extend(declaration(f"m{j}", index * 4 + j + 2, owner) for j in range(3))
    modules = (module(tuple(symbols)),)
    tracemalloc.start()
    try:
        result = RIC().compute(modules)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == {
        "measured_pairs": 119400, "unavailable_pairs": 0,
        "partial_ratio_mean": 0.0, "partial_ratio_max": 0.0,
    }
    # Generous linear budgets: the previous full-pair path used over 22 MiB.
    assert peak < class_count * 8192
    lines = 0

    def count_lines(frame: FrameType, event: str, _arg: object) -> Callable[..., object]:
        nonlocal lines
        if event == "line" and frame.f_globals.get("__name__") == RIC.__module__:
            lines += 1
        return count_lines

    previous_trace = sys.gettrace()
    try:
        sys.settrace(count_lines)
        assert RIC().compute(modules) == result
    finally:
        sys.settrace(previous_trace)
    assert lines < class_count * 400


def test_all_pairs_deduplicate_users_and_preserve_zero_owner_use() -> None:
    """All pairs include zeros; the floor never overwrites raw owner use."""
    a, b, c = declaration("A", 1), declaration("B", 2), declaration("C", 3)
    target = declaration("target", 4, a)
    first, second = declaration("first", 5, b), declaration("second", 6, b)
    third = declaration("third", 7, c)
    modules = (module((a, b, c, target, first, second, third), (
        call(first, target), call(first, target), call(second, target), call(third, target),
    )),)
    pairs = RIC().pair_diagnostics(modules)
    assert len(pairs) == 8
    assert pairs[target.id, b.id] == RICPair(2, 0, 1, 2.0)
    assert pairs[target.id, c.id] == RICPair(1, 0, 1, 1.0)
    assert pairs[first.id, a.id] == RICPair(0, 0, 1, 0.0)
    assert RIC().compute(modules) == {
        "measured_pairs": 8, "unavailable_pairs": 0,
        "partial_ratio_mean": 0.375, "partial_ratio_max": 2.0,
    }


def test_recursion_and_multiple_owner_methods_supply_actual_denominator() -> None:
    """Distinct owner callers, including recursion, replace the denominator floor."""
    a, b = declaration("A", 1), declaration("B", 2)
    target, sibling = declaration("target", 3, a), declaration("sibling", 4, a)
    first, second, third = (declaration(name, line, b) for name, line in (("one", 5), ("two", 6), ("three", 7)))
    modules = (module((a, b, target, sibling, first, second, third), (
        call(target, target), call(target, target), call(sibling, target),
        call(first, target), call(second, target), call(third, target),
    )),)
    assert RIC().pair_diagnostics(modules)[target.id, b.id] == RICPair(3, 2, 2, 1.5)
    assert_aggregates_match_diagnostics(modules)


@pytest.mark.parametrize("missing", ["callable_facts", "source_uses", "direct_bases"])
def test_unavailable_class_or_method_extraction_is_not_measured_zero(missing: str) -> None:
    """Unsupported endpoints are unavailable without poisoning unrelated pairs."""
    a, b, c = declaration("A", 1), declaration("B", 2), declaration("C", 3)
    target, caller = declaration("target", 4, a), declaration("caller", 5, b)
    if missing == "callable_facts":
        caller = caller.model_copy(update={"callable_facts": None})
    if missing == "direct_bases":
        b = b.model_copy(update={"direct_bases": None})
    unavailable = module((b, caller))
    if missing == "source_uses":
        unavailable = unavailable.model_copy(update={"source_uses": None})
    modules = (module((a, c, target)), unavailable)
    assert RIC().pair_diagnostics(modules) == {
        (target.id, b.id): None, (target.id, c.id): RICPair(0, 0, 1, 0.0),
        (caller.id, a.id): None, (caller.id, c.id): None,
    }
    assert RIC().compute(modules) == {
        "measured_pairs": 1, "unavailable_pairs": 3,
        "partial_ratio_mean": 0.0, "partial_ratio_max": 0.0,
    }
    assert_aggregates_match_diagnostics(modules)
    assert_aggregates_match_diagnostics((module((a, target)), unavailable))
    assert RIC().compute((module((a, target)), unavailable)) == {
        "measured_pairs": 0, "unavailable_pairs": 2,
        "partial_ratio_mean": None, "partial_ratio_max": None,
    }


@pytest.mark.parametrize("ignored", [
    "unresolved", "external", "ambiguous", "unsupported", "attribute_read",
    "module", "class", "unsupported_execution", "unsupported_context", "free_function", "unknown_owner",
])
def test_only_direct_supported_project_calls_executing_in_methods_count(ignored: str) -> None:
    """Unattributable uses cannot create method users, even with a known target."""
    a, b = declaration("A", 1), declaration("B", 2)
    target, caller = declaration("target", 3, a), declaration("caller", 4, b)
    use = call(caller, target)
    symbols = (a, b, target, caller)
    if ignored in {"unresolved", "external", "ambiguous", "unsupported"}:
        use = use.model_copy(update={"resolution": TargetResolutionIR.model_validate({
            "status": ignored, "target_id": target.id, "candidate_ids": (target.id,),
        })})
    elif ignored == "attribute_read":
        use = use.model_copy(update={"kind": "attribute_read"})
    elif ignored in {"module", "class", "unsupported_execution"}:
        use = use.model_copy(update={"execution_kind": "unsupported" if ignored == "unsupported_execution" else ignored})
    elif ignored == "unsupported_context":
        use = use.model_copy(update={"unsupported_context": "unsupported"})
    elif ignored == "free_function":
        free = caller.model_copy(update={"kind": SymbolKind.FUNCTION})
        symbols = (a, b, target, free)
        use = use.model_copy(update={"owner_id": free.id})
    else:
        use = use.model_copy(update={"owner_id": "unknown"})
    assert RIC().pair_diagnostics((module(symbols, (use,)),))[target.id, b.id] == RICPair(0, 0, 1, 0.0)


def test_possible_runtime_bodies_do_not_replace_static_selection() -> None:
    """Runtime alternatives never multiply or redirect static declaration use."""
    a, b, c = declaration("A", 1), declaration("B", 2), declaration("C", 3)
    target, caller, override = declaration("target", 4, a), declaration("caller", 5, b), declaration("override", 6, c)
    use = call(caller, target).model_copy(update={"runtime_targets": RuntimeTargetsIR(
        status="approximate", target_ids=(override.id,), assumption="closed-project-hierarchy",
    )})
    pairs = RIC().pair_diagnostics((module((a, b, c, target, caller, override), (use,)),))
    assert pairs[target.id, b.id] == RICPair(1, 0, 1, 1.0)
    assert pairs[override.id, b.id] == RICPair(0, 0, 1, 0.0)


def test_indirect_calls_do_not_become_target_users() -> None:
    """An external call to an owner wrapper is not external use of its callee."""
    a, b = declaration("A", 1), declaration("B", 2)
    target, wrapper, caller = declaration("target", 3, a), declaration("wrapper", 4, a), declaration("caller", 5, b)
    pairs = RIC().pair_diagnostics((module((a, b, target, wrapper, caller), (
        call(wrapper, target), call(caller, wrapper),
    )),))
    assert pairs[target.id, b.id] == RICPair(0, 1, 1, 0.0)
    assert pairs[wrapper.id, b.id] == RICPair(1, 0, 1, 1.0)


def test_no_pairs_has_null_summaries_and_diagnostics_are_read_only() -> None:
    """Empty populations remain null; both diagnostic layers and reports are frozen."""
    a, b = declaration("A", 1), declaration("B", 2)
    target = declaration("target", 3, a)
    empty = {"measured_pairs": 0, "unavailable_pairs": 0, "partial_ratio_mean": None, "partial_ratio_max": None}
    assert RIC().compute(()) == empty
    assert RIC().compute((module((a, target)),)) == empty
    modules = (module((a, b, target)),)
    pairs = RIC().pair_diagnostics(modules)
    with pytest.raises(TypeError):
        cast("MutableMapping[tuple[str, str], RICPair | None]", pairs)[target.id, b.id] = None
    value = pairs[target.id, b.id]
    assert value is not None
    field_name = "owner_users"
    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, 9)
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | float | None]", RIC().compute(modules))["partial_ratio_mean"] = 9


@pytest.mark.parametrize(("scenario", "measured", "unavailable"), [
    ("zero_use", 18, 0), ("owner_floor", 18, 0), ("recursion", 18, 0),
    ("all_unavailable", 0, 18), ("mixed_unavailable", 5, 13), ("unknown_owner", 18, 4),
    ("no_methods", 0, 0), ("one_class", 0, 0), ("empty", 0, 0),
])
def test_sparse_aggregates_equal_full_diagnostics(scenario: str, measured: int, unavailable: int) -> None:
    """Arithmetic populations and sparse ratios exactly match the explicit all-pair view."""
    a, b, c, empty = (declaration(name, line) for line, name in enumerate(("A", "B", "C", "Empty"), 1))
    target, sibling, extra = (declaration(name, line, a) for line, name in enumerate(("target", "sibling", "extra"), 5))
    first, second, third = declaration("first", 8, b), declaration("second", 9, b), declaration("third", 10, c)
    # Reverse caller-class and target order to exercise canonical floating-point summation.
    uses = (
        call(third, sibling), call(third, target), call(second, target), call(first, target), call(first, target),
    )
    if scenario != "owner_floor":
        uses += (call(target, target), call(target, target), call(sibling, target), call(extra, target))
    if scenario == "zero_use":
        uses = ()
    modules = (module((a, target, sibling, extra), uses), module((b, first, second)), module((c, empty, third)))
    if scenario == "all_unavailable":
        modules = tuple(item.model_copy(update={"source_uses": None}) for item in modules)
    orphan = declaration("orphan", 11, a).model_copy(update={"callable_facts": None, "owner_id": None})
    variants = {
        "unknown_owner": (*modules, module((orphan,))),
        "mixed_unavailable": (*modules[:2], modules[2].model_copy(update={"source_uses": None})),
        "no_methods": (module((a, b, c, empty)),),
        "one_class": (module((a, target, sibling, extra), uses),),
        "empty": (),
    }
    modules = variants.get(scenario, modules)
    assert_aggregates_match_diagnostics(modules)
    diagnostics = RIC().pair_diagnostics(modules)
    assert sum(pair is not None for pair in diagnostics.values()) == measured
    assert sum(pair is None for pair in diagnostics.values()) == unavailable
