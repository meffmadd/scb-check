"""Directional static-call module neighbors over retained immutable facts."""

from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

from scb_check.metrics.module_dependencies import ModuleCallDependencies
from scb_check.metrics.module_dependencies import ModuleNeighbors
from scb_check.pipeline import analyze_files
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ResolutionStatus
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import TargetResolutionIR


def module(file: str) -> ModuleIR:
    """Use equal descriptive names but distinct physical-file identities."""
    return ModuleIR(
        language=Language.PYTHON, file=Path(file), module_name="same",
        span=SourceSpan(file=Path(file), start_line=1, start_col=0, end_line=20, end_col=0),
        source_uses=(),
    )


def call(source: ModuleIR, target: ModuleIR) -> SourceUseIR:
    """Supply resolved module endpoints without source resolution or IO."""
    return SourceUseIR(
        kind="call", span=source.span, target_span=source.span,
        target_spelling="target", target_form="name", owner_id=source.id,
        execution_kind="module",
        resolution=TargetResolutionIR(status="project", target_id=target.id),
    )


def test_directional_neighbors_deduplicate_preserve_cycles_and_exclude_self() -> None:
    """A↔B and A→C produce three directed pairs; D is a measured zero."""
    a, b, c, d = (module(f"{name}/same.py") for name in "abcd")
    modules = (
        a.model_copy(update={"source_uses": (call(a, b), call(a, b), call(a, c), call(a, a))}),
        b.model_copy(update={"source_uses": (call(b, a),)}), c, d,
    )
    metric = ModuleCallDependencies()
    assert metric.neighbor_sets(modules) == {
        a.id: ModuleNeighbors(frozenset({b.id}), frozenset({b.id, c.id})),
        b.id: ModuleNeighbors(frozenset({a.id}), frozenset({a.id})),
        c.id: ModuleNeighbors(frozenset({a.id}), frozenset()),
        d.id: ModuleNeighbors(frozenset(), frozenset()),
    }
    assert metric.compute(modules) == {
        "measured_modules": 4, "unavailable_modules": 0,
        "partial_incoming_sum": 3, "partial_incoming_mean": 0.75, "partial_incoming_max": 1,
        "partial_outgoing_sum": 3, "partial_outgoing_mean": 0.75, "partial_outgoing_max": 2,
    }


@pytest.mark.parametrize("status", ["external", "unresolved", "ambiguous", "unsupported"])
def test_unknown_static_targets_do_not_become_neighbors(status: ResolutionStatus) -> None:
    """Neither candidate IDs nor runtime alternatives replace static resolution."""
    a, b = module("a.py"), module("b.py")
    use = call(a, b).model_copy(update={
        "resolution": TargetResolutionIR(status=status, target_id=b.id, candidate_ids=(b.id,)),
        "runtime_targets": RuntimeTargetsIR(
            status="complete", target_ids=(b.id,), assumption="closed-project-hierarchy",
        ),
    })
    result = ModuleCallDependencies().compute((a.model_copy(update={"source_uses": (use,)}), b))
    assert result["partial_incoming_sum"] == 0
    assert result["partial_outgoing_sum"] == 0


@pytest.mark.parametrize("change", [
    {"kind": "attribute-read"}, {"execution_kind": "unsupported"},
    {"resolution": TargetResolutionIR(status="project", target_id="absent")},
])
def test_other_relations_and_unretained_targets_add_no_edge(change: dict[str, object]) -> None:
    """Only supported static project calls with retained endpoints count."""
    a, b = module("a.py"), module("b.py")
    use = call(a, b).model_copy(update=change)
    assert ModuleCallDependencies().compute((
        a.model_copy(update={"source_uses": (use,)}), b,
    ))["partial_outgoing_sum"] == 0


def test_static_project_selection_does_not_expand_runtime_alternatives() -> None:
    """Only the selected module counts even when runtime evidence names another."""
    a, b, c = (module(f"{name}.py") for name in "abc")
    use = call(a, b).model_copy(update={
        "runtime_targets": RuntimeTargetsIR(
            status="approximate", target_ids=(c.id,), assumption="closed-project-hierarchy",
        ),
    })
    assert ModuleCallDependencies().neighbor_sets((
        a.model_copy(update={"source_uses": (use,)}), b, c,
    )) == {
        a.id: ModuleNeighbors(frozenset(), frozenset({b.id})),
        b.id: ModuleNeighbors(frozenset({a.id}), frozenset()),
        c.id: ModuleNeighbors(frozenset(), frozenset()),
    }


def test_unavailable_targets_remain_neighbors_without_becoming_measured() -> None:
    """Unsupported destination collection does not discard a known outgoing edge."""
    a, b = module("a.py"), module("b.py").model_copy(update={"source_uses": None})
    a = a.model_copy(update={"source_uses": (call(a, b),)})
    metric = ModuleCallDependencies()
    assert metric.neighbor_sets((a, b)) == {
        a.id: ModuleNeighbors(frozenset(), frozenset({b.id})), b.id: None,
    }
    assert metric.compute((a, b)) == {
        "measured_modules": 1, "unavailable_modules": 1,
        "partial_incoming_sum": 0, "partial_incoming_mean": 0.0, "partial_incoming_max": 0,
        "partial_outgoing_sum": 1, "partial_outgoing_mean": 1.0, "partial_outgoing_max": 1,
    }
    for modules, unavailable in (((), 0), ((b,), 1)):
        assert metric.compute(modules) == {
            "measured_modules": 0, "unavailable_modules": unavailable,
            "partial_incoming_sum": None, "partial_incoming_mean": None, "partial_incoming_max": None,
            "partial_outgoing_sum": None, "partial_outgoing_mean": None, "partial_outgoing_max": None,
        }


def test_known_source_graph_counts_calls_not_imports_or_accesses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated aliases/sites, recursion, cycles, unknowns and imports stay distinct."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    fixture = Path(__file__).parents[1] / "fixtures" / "module_dependencies"
    project = analyze_files(tuple(fixture.glob("*.py"))).project
    modules = {item.module_name: item for item in project.modules}
    a, b, c, idle = (modules[name] for name in ("dep_a", "dep_b", "dep_c", "dep_idle"))
    assert ModuleCallDependencies().neighbor_sets(project.modules) == {
        a.id: ModuleNeighbors(frozenset({b.id}), frozenset({b.id, c.id})),
        b.id: ModuleNeighbors(frozenset({a.id}), frozenset({a.id})),
        c.id: ModuleNeighbors(frozenset({a.id}), frozenset()),
        idle.id: ModuleNeighbors(frozenset(), frozenset()),
    }
    assert ModuleCallDependencies().compute(project.modules) == {
        "measured_modules": 4, "unavailable_modules": 0,
        "partial_incoming_sum": 3, "partial_incoming_mean": 0.75, "partial_incoming_max": 1,
        "partial_outgoing_sum": 3, "partial_outgoing_mean": 0.75, "partial_outgoing_max": 2,
    }


@pytest.mark.parametrize("execution", ["target()", "class Init:\n    target()", "def run():\n    target()"])
def test_supported_initialization_and_function_calls_count(tmp_path: Path, execution: str) -> None:
    """The only cross-module site can execute in module, class, or function scope."""
    destination, source = tmp_path / "destination.py", tmp_path / "source.py"
    destination.write_text("def target():\n    return 1\n")
    source.write_text(f"from destination import target\n{execution}\n")
    project = analyze_files((source, destination), disable_sg=True).project
    assert ModuleCallDependencies().compute(project.modules)["partial_outgoing_sum"] == 1


def test_package_files_stay_distinct_and_inherited_calls_target_declaring_module(tmp_path: Path) -> None:
    """Package membership does not merge files or move an inherited method body."""
    package = tmp_path / "pkg"
    package.mkdir()
    init, base, child, source = (package / name for name in ("__init__.py", "base.py", "child.py", "source.py"))
    init.write_text("")
    base.write_text("class Base:\n    def work(self):\n        return 1\n")
    child.write_text("from pkg.base import Base\nclass Child(Base):\n    pass\n")
    source.write_text("from pkg.child import Child\ndef run(value: Child):\n    value.work()\n")
    project = analyze_files((init, base, child, source), disable_sg=True).project
    modules = {item.module_name: item for item in project.modules}
    assert set(modules) == {"pkg", "pkg.base", "pkg.child", "pkg.source"}
    source_id, base_id = modules["pkg.source"].id, modules["pkg.base"].id
    assert ModuleCallDependencies().neighbor_sets(project.modules) == {
        modules["pkg"].id: ModuleNeighbors(frozenset(), frozenset()),
        base_id: ModuleNeighbors(frozenset({source_id}), frozenset()),
        modules["pkg.child"].id: ModuleNeighbors(frozenset(), frozenset()),
        source_id: ModuleNeighbors(frozenset(), frozenset({base_id})),
    }


def test_results_and_nested_diagnostics_are_read_only() -> None:
    """Consumers cannot mutate numerical reports or either neighbor direction."""
    a = module("a.py")
    metric = ModuleCallDependencies()
    diagnostics = metric.neighbor_sets((a,))
    with pytest.raises(TypeError):
        cast("MutableMapping[str, ModuleNeighbors | None]", diagnostics)[a.id] = None
    value = diagnostics[a.id]
    assert value is not None
    for direction in ("incoming", "outgoing"):
        with pytest.raises(FrozenInstanceError):
            setattr(value, direction, frozenset({"invented"}))
    with pytest.raises(TypeError):
        cast("MutableMapping[str, int | float | None]", metric.compute((a,)))["measured_modules"] = 9
