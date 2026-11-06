"""CBO partner sets and summaries over immutable extracted facts."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.cbo import CBO
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def symbol(name: str, kind: SymbolKind, line: int, owner: str | None = None) -> SymbolIR:
    """Create distinct declarations without parsing or language resolution."""
    span = SourceSpan(file=Path("model.py"), start_line=line, start_col=0, end_line=line, end_col=1)
    return SymbolIR(
        name=name, qualified_name=name, kind=kind, owner_id=owner,
        owner_qualified_name=owner, span=span,
        direct_bases=() if kind == SymbolKind.CLASS else None,
        callable_facts=CallableIR(
            declaring_class_id=owner, binding="instance", body_kind="implemented",
            body_span=span, implementation_id=span.entity_id(kind),
        ) if kind == SymbolKind.METHOD else None,
    )


def test_repeated_reverse_and_self_calls_count_distinct_other_partners() -> None:
    """A↔B repeated use is one partner each; A→A and an isolated C add none."""
    a = symbol("A", SymbolKind.CLASS, 1)
    b = symbol("B", SymbolKind.CLASS, 2)
    c = symbol("C", SymbolKind.CLASS, 3)
    am = symbol("A.work", SymbolKind.METHOD, 4, a.id)
    bm = symbol("B.work", SymbolKind.METHOD, 5, b.id)
    uses = tuple(SourceUseIR(
        kind="call", span=am.span, target_span=am.span, target_spelling="work",
        target_form="attribute", owner_id=owner.id, execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    ) for owner, target in ((am, bm), (am, bm), (bm, am), (am, am)))
    module = ModuleIR(
        language=Language.PYTHON, file=Path("model.py"), module_name="model", span=a.span,
        symbols=(a, b, c, am, bm), attributes=(), source_uses=uses,
    )

    assert CBO().partner_sets((module,)) == {a.id: frozenset({b.id}), b.id: frozenset({a.id}), c.id: frozenset()}
    assert CBO().compute((module,)) == {
        "measured_classes": 3, "unavailable_classes": 0,
        "partial_partner_sum": 2, "partial_partner_mean": 2 / 3,
        "partial_partner_max": 1,
    }


@pytest.mark.parametrize("status", ["complete", "approximate"])
def test_runtime_implementations_take_precedence_over_static_selection(status: str) -> None:
    """Even approximate known runtime bodies add partners; static-only owners do not."""
    a = symbol("A", SymbolKind.CLASS, 1)
    b = symbol("B", SymbolKind.CLASS, 2)
    c = symbol("C", SymbolKind.CLASS, 3)
    am = symbol("A.run", SymbolKind.METHOD, 4, a.id)
    bm = symbol("B.work", SymbolKind.METHOD, 5, b.id)
    cm = symbol("C.work", SymbolKind.METHOD, 6, c.id)
    use = SourceUseIR(
        kind="call", span=am.span, target_span=am.span, target_spelling="value.work",
        target_form="attribute", owner_id=am.id, execution_kind="function",
        resolution=TargetResolutionIR(status="project", target_id=bm.id),
        runtime_targets=RuntimeTargetsIR.model_validate({
            "status": status, "target_ids": (cm.id,), "assumption": "closed-project-hierarchy",
        }),
    )
    module = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="model", span=a.span,
        symbols=(a, b, c, am, bm, cm), attributes=(), source_uses=(use,),
    )
    assert CBO().partner_sets((module,)) == {
        a.id: frozenset({c.id}), b.id: frozenset(), c.id: frozenset({a.id}),
    }


@pytest.mark.parametrize("missing", ["source_uses", "attributes", "direct_bases"])
def test_unavailable_extraction_is_distinct_from_partial_zero(missing: str) -> None:
    """Unsupported class diagnostics stay null and do not enter the measured mean."""
    a = symbol("A", SymbolKind.CLASS, 1)
    b = symbol("B", SymbolKind.CLASS, 2)
    available = ModuleIR(
        language=Language.PYTHON, file=a.file, module_name="model", span=a.span,
        symbols=(a,), attributes=(), source_uses=(),
    )
    unavailable = available.model_copy(update={"symbols": (b,)})
    if missing == "direct_bases":
        unavailable = unavailable.model_copy(update={"symbols": (b.model_copy(update={missing: None}),)})
    else:
        unavailable = unavailable.model_copy(update={missing: None})
    partners = CBO().partner_sets((available, unavailable))
    assert partners == {a.id: frozenset(), b.id: None}
    with pytest.raises(TypeError):
        cast("MutableMapping[str, frozenset[str] | None]", partners)[a.id] = None
    assert CBO().compute((available, unavailable)) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_partner_sum": 0, "partial_partner_mean": 0.0, "partial_partner_max": 0,
    }
    assert CBO().compute((unavailable,))["partial_partner_sum"] is None
    assert CBO().compute(())["partial_partner_mean"] is None
