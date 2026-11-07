"""Known distinct caller counts from retained Python source facts."""

from pathlib import Path

import pytest

from scb_check.metrics.callers import DistinctCallers
from scb_check.pipeline import analyze_files

FIXTURES = Path(__file__).parent / "fixtures" / "callers"


def test_source_callers_reconcile_same_and_cross_module_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static source selection counts declarations, not possible runtime overrides."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files((
        FIXTURES / "callers_targets.py", FIXTURES / "callers_clients.py",
    )).project
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}
    diagnostics = DistinctCallers().caller_sets(project.modules)
    assert {
        names[target]: (
            {names[caller] for caller in value.same_module},
            {names[caller] for caller in value.cross_module},
        ) if value is not None else None
        for target, value in diagnostics.items()
    } == {
        "callers_targets.destination": (
            {"callers_targets.local"},
            {"callers_clients.first", "callers_clients.first.nested", "callers_clients.second"},
        ),
        "callers_targets.recursive": ({"callers_targets.recursive"}, set()),
        "callers_targets.dormant": (set(), set()),
        "callers_targets.Base.work": (set(), {"callers_clients.second"}),
        "callers_targets.Override.work": (set(), set()),
        "callers_targets.local": (set(), set()),
        "callers_clients.first": (set(), set()),
        "callers_clients.first.nested": ({"callers_clients.first"}, set()),
        "callers_clients.second": (set(), set()),
        "callers_clients.uncertain": (set(), set()),
    }
    assert DistinctCallers().compute(project.modules) == {
        "measured_callables": 10, "unavailable_callables": 0,
        "partial_caller_sum": 7, "partial_caller_mean": 0.7, "partial_caller_max": 4,
        "partial_same_module_sum": 3, "partial_cross_module_sum": 4,
    }


def test_placeholder_and_decorated_source_declarations_remain_eligible(
    tmp_path: Path,
) -> None:
    """Static counts include placeholders and decorators, not unsupported lambda owners."""
    source = tmp_path / "declarations.py"
    source.write_text(
        "def target(): ...\n"
        "def decorate(fn): return fn\n"
        "@decorate\n"
        "def decorated(): return target()\n"
        "def caller():\n    target()\n    decorated()\n"
        "class Consumer:\n    def method(self): return target()\n"
        "def hidden(): return lambda: target()\n"
        "target()\n"
        "class Initialization:\n    value = target()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    source.unlink()  # Retained IR must be sufficient after source files disappear.
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}
    diagnostics = DistinctCallers().caller_sets(project.modules)
    assert {
        names[target]: {names[caller] for caller in value.same_module}
        if value is not None else None
        for target, value in diagnostics.items()
    } == {
        "declarations.target": {"declarations.decorated", "declarations.caller", "declarations.Consumer.method"},
        "declarations.decorate": set(),
        "declarations.decorated": {"declarations.caller"},
        "declarations.caller": set(),
        "declarations.Consumer.method": set(),
        "declarations.hidden": set(),
    }
    assert DistinctCallers().compute(project.modules) == {
        "measured_callables": 6, "unavailable_callables": 0,
        "partial_caller_sum": 4, "partial_caller_mean": 2 / 3, "partial_caller_max": 3,
        "partial_same_module_sum": 4, "partial_cross_module_sum": 0,
    }
