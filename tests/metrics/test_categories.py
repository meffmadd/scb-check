"""Shared category policy over immutable IR, independent of either metric."""

from pathlib import Path

import pytest

from scb_check.metrics.categories import category_dependencies
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind


def _module(name: str) -> ModuleIR:
    file = Path(f"{name}.py")
    span = SourceSpan(file=file, start_line=1, start_col=0, end_line=5, end_col=0)
    first = SymbolIR(
        name="First", qualified_name=f"{name}.First", kind=SymbolKind.CLASS,
        span=span.model_copy(update={"end_line": 3}), direct_bases=(),
    )
    second = SymbolIR(
        name="Second", qualified_name=f"{name}.Second", kind=SymbolKind.CLASS,
        span=span.model_copy(update={"start_line": 4}), direct_bases=(),
    )
    method_span = span.model_copy(update={"start_line": 2, "end_line": 3})
    method = SymbolIR(
        name="work", qualified_name=f"{name}.First.work", kind=SymbolKind.METHOD,
        span=method_span, owner_id=first.id, owner_qualified_name=first.qualified_name,
        callable_facts=CallableIR(
            declaring_class_id=first.id, binding="instance", body_kind="implemented",
            body_span=method_span, implementation_id=method_span.entity_id(SymbolKind.METHOD),
        ),
    )
    return ModuleIR(
        language=Language.PYTHON, file=file, module_name=name, span=span,
        symbols=(first, second, method), source_uses=(), attributes=(),
    )


@pytest.mark.parametrize("missing", ["source_uses", "attributes", "direct_bases", "callable_facts"])
def test_any_missing_internal_extraction_makes_whole_category_unavailable(missing: str) -> None:
    """One unsupported class/method must not masquerade as a smaller complete category."""
    supported, unsupported = _module("supported"), _module("unsupported")
    if missing in {"source_uses", "attributes"}:
        unsupported = unsupported.model_copy(update={missing: None})
    else:
        symbols = tuple(
            symbol.model_copy(update={missing: None})
            if symbol.name == ("Second" if missing == "direct_bases" else "work") else symbol
            for symbol in unsupported.symbols
        )
        unsupported = unsupported.model_copy(update={"symbols": symbols})
    facts = category_dependencies(ProjectIR(modules=(supported, unsupported)))
    assert facts.unavailable_categories == frozenset({unsupported.id})
    assert len(facts.class_categories) == 4
    assert facts.class_edges == frozenset()


def test_classless_modules_do_not_create_categories_even_with_unavailable_facts() -> None:
    """An empty eligible category population does not gain invented zero measurements."""
    empty = _module("empty").model_copy(update={"symbols": (), "source_uses": None, "attributes": None})
    facts = category_dependencies(ProjectIR(modules=(empty,)))
    assert facts.class_categories == {}
    assert facts.unavailable_categories == frozenset()
    assert facts.class_edges == frozenset()
