"""Message Passing Coupling over immutable call-site evidence."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.mpc import MPC
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def declaration(name: str, kind: SymbolKind, line: int, owner: str | None = None) -> SymbolIR:
    """Build a declaration with explicit implementation ownership."""
    span = SourceSpan(file=Path("mpc.py"), start_line=line, start_col=0, end_line=line, end_col=1)
    return SymbolIR(
        name=name, qualified_name=name, kind=kind, span=span,
        owner_id=owner, owner_qualified_name=owner,
        direct_bases=() if kind == SymbolKind.CLASS else None,
        callable_facts=CallableIR(
            declaring_class_id=owner, binding="instance", body_kind="implemented",
            body_span=span, implementation_id=span.entity_id(kind),
        ) if kind == SymbolKind.METHOD else None,
    )


def call(owner: SymbolIR, target: SymbolIR, line: int) -> SourceUseIR:
    """Record one distinct physical call site, without doing resolution."""
    span = owner.span.model_copy(update={"start_line": line, "end_line": line})
    return SourceUseIR(
        kind="call", span=span, target_span=span, target_spelling=target.name,
        target_form="attribute", owner_id=owner.id, execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    )


def test_repeated_sites_count_but_self_calls_do_not() -> None:
    """Two sites to B count twice for A, not once per target or in reverse."""
    a = declaration("A", SymbolKind.CLASS, 1)
    b = declaration("B", SymbolKind.CLASS, 2)
    am = declaration("run", SymbolKind.METHOD, 3, a.id)
    bm = declaration("work", SymbolKind.METHOD, 4, b.id)
    module = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="mpc", span=a.span,
        symbols=(a, b, am, bm), source_uses=(call(am, bm, 5), call(am, bm, 6), call(am, am, 7)),
    )

    assert MPC().class_counts((module,)) == {a.id: 2, b.id: 0}
    assert MPC().compute((module,)) == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_call_site_sum": 2, "partial_call_site_mean": 1.0, "partial_call_site_max": 2,
    }


@pytest.mark.parametrize("status", ["complete", "approximate"])
def test_static_target_ownership_ignores_runtime_implementations(status: str) -> None:
    """Overrides cannot make an own static target external, or vice versa."""
    a = declaration("A", SymbolKind.CLASS, 1)
    b = declaration("B", SymbolKind.CLASS, 2)
    c = declaration("C", SymbolKind.CLASS, 3)
    am = declaration("run", SymbolKind.METHOD, 4, a.id)
    bm = declaration("work", SymbolKind.METHOD, 5, b.id)
    cm = declaration("work", SymbolKind.METHOD, 6, c.id)
    assert bm.callable_facts is not None
    bm = bm.model_copy(update={"callable_facts": bm.callable_facts.model_copy(
        update={"implementation_id": "body:B.work"},
    )})
    use = call(am, am, 7).model_copy(update={"runtime_targets": RuntimeTargetsIR.model_validate({
        "status": status, "target_ids": (am.id, "body:B.work", cm.id),
        "assumption": "closed-project-hierarchy",
    })})
    module = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="mpc", span=a.span,
        symbols=(a, b, c, am, bm, cm), source_uses=(use, call(am, am, 8).model_copy(update={
            "runtime_targets": RuntimeTargetsIR(
                status="complete", target_ids=("body:B.work",), assumption="closed-project-hierarchy",
            ),
        })),
    )
    assert MPC().class_counts((module,)) == {a.id: 0, b.id: 0, c.id: 0}
    # An external static target counts even when runtime evidence is own-only.
    own_only = call(am, bm, 8).model_copy(update={"runtime_targets": RuntimeTargetsIR(
        status="complete", target_ids=(am.id,), assumption="closed-project-hierarchy",
    )})
    assert MPC().class_counts((module.model_copy(update={"source_uses": (own_only,)}),))[a.id] == 1


@pytest.mark.parametrize("context", ["class", "module", "unsupported", "lambda", "attribute", "nested"])
def test_only_supported_calls_executing_in_implemented_methods_count(context: str) -> None:
    """Class initialization, unsupported contexts, and nested functions are not method bodies."""
    a = declaration("A", SymbolKind.CLASS, 1)
    b = declaration("B", SymbolKind.CLASS, 2)
    am = declaration("run", SymbolKind.METHOD, 3, a.id)
    bm = declaration("work", SymbolKind.METHOD, 4, b.id)
    nested = declaration("helper", SymbolKind.FUNCTION, 5, am.id)
    use = call(am, bm, 6)
    if context in {"class", "module", "unsupported"}:
        use = use.model_copy(update={"execution_kind": context})
    elif context == "lambda":
        use = use.model_copy(update={"unsupported_context": "lambda"})
    elif context == "attribute":
        use = use.model_copy(update={"kind": "attribute-read"})
    else:
        use = use.model_copy(update={"owner_id": nested.id})
    module = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="mpc", span=a.span,
        symbols=(a, b, am, bm, nested), source_uses=(use,),
    )
    assert MPC().class_counts((module,)) == {a.id: 0, b.id: 0}


@pytest.mark.parametrize("missing", ["source_uses", "direct_bases", "callable_facts"])
def test_unsupported_classes_are_unavailable_not_measured_zero(missing: str) -> None:
    """Only supported classes enter summary denominators, even in mixed snapshots."""
    a = declaration("A", SymbolKind.CLASS, 1)
    b = declaration("B", SymbolKind.CLASS, 2)
    bm = declaration("work", SymbolKind.METHOD, 3, b.id)
    available = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="mpc", span=a.span,
        symbols=(a,), source_uses=(),
    )
    if missing == "direct_bases":
        b = b.model_copy(update={"direct_bases": None})
    elif missing == "callable_facts":
        bm = bm.model_copy(update={"callable_facts": None})
    unavailable = available.model_copy(update={
        "symbols": (b, bm), "source_uses": None if missing == "source_uses" else (),
    })
    assert MPC().class_counts((available, unavailable)) == {a.id: 0, b.id: None}
    assert MPC().compute((available, unavailable)) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_call_site_sum": 0, "partial_call_site_mean": 0.0, "partial_call_site_max": 0,
    }
    assert MPC().compute((unavailable,)) == {
        "measured_classes": 0, "unavailable_classes": 1,
        "partial_call_site_sum": None, "partial_call_site_mean": None, "partial_call_site_max": None,
    }


def test_empty_population_and_read_only_results() -> None:
    """Empty input has unavailable summaries and diagnostics cannot be mutated."""
    metric = MPC()
    result = metric.compute(())
    assert result == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_call_site_sum": None, "partial_call_site_mean": None, "partial_call_site_max": None,
    }
    with pytest.raises(TypeError):
        cast("MutableMapping[str, object]", result)["measured_classes"] = 1
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | None]", metric.class_counts(()))["class"] = 0
