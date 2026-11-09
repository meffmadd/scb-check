"""Category membership and directed class dependencies from retained source facts."""

from collections.abc import Callable
from pathlib import Path
from shutil import copytree

import pytest

from scb_check.metrics.ca import AfferentCoupling
from scb_check.metrics.categories import category_dependencies
from scb_check.metrics.ce import EfferentCoupling
from scb_check.pipeline import analyze_files
from scb_check.reporting.score import compute_report
from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import SymbolKind

FIXTURES = Path(__file__).parent / "fixtures" / "category_coupling"


@pytest.fixture
def project_from_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Callable[[dict[str, str]], ProjectIR]:
    """Analyze real source through the ordinary retained-IR seam, without ast-grep."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())

    def build(sources: dict[str, str]) -> ProjectIR:
        files = tuple(tmp_path / name for name in sources)
        for file, source in zip(files, sources.values(), strict=True):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(source, encoding="utf-8")
        return analyze_files(files).project

    return build


def _named_edges(project: ProjectIR) -> set[tuple[str, str]]:
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    return {(names[source], names[target]) for source, target in category_dependencies(project).class_edges}


def test_category_policy_retains_direction_and_class_not_file_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated sites deduplicate; internal edges survive and free clients do not."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files(tuple(FIXTURES.glob("*.py"))).project
    facts = category_dependencies(project)
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    modules = {module.id: module.name for module in project.modules}

    assert {names[key]: modules[value] for key, value in facts.class_categories.items()} == {
        "Primary": "targets", "Secondary": "targets", "InternalClient": "targets",
        "FirstClient": "clients", "SecondClient": "clients",
        "Utility": "other", "ThirdClient": "other", "Isolated": "isolated",
    }
    assert {(names[source], names[target]) for source, target in facts.class_edges} == {
        ("InternalClient", "Primary"), ("FirstClient", "Primary"),
        ("FirstClient", "Secondary"), ("FirstClient", "Utility"),
        ("SecondClient", "Primary"), ("ThirdClient", "Primary"),
    }
    assert facts.unavailable_categories == frozenset()


def test_category_reports_and_diagnostics_need_only_retained_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known Ca/Ce differ: category-client incidences are not source-class volume."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    copied = copytree(FIXTURES, tmp_path / "source")
    files = tuple(copied.glob("*.py"))
    analysis = analyze_files(files)
    for source in files:
        source.unlink()
    facts = category_dependencies(analysis.project)
    names = {symbol.id: symbol.name for symbol in analysis.project.symbols_by_id.values()}
    modules = {module.id: module.name for module in analysis.project.modules}
    clients = AfferentCoupling().client_sets(facts)
    sources = EfferentCoupling().source_sets(facts)
    assert {modules[key]: {names[value] for value in values} if values is not None else None
            for key, values in clients.items()} == {
        "targets": {"FirstClient", "SecondClient", "ThirdClient"},
        "clients": set(), "other": {"FirstClient"}, "isolated": set(),
    }
    assert {modules[key]: {names[value] for value in values} if values is not None else None
            for key, values in sources.items()} == {
        "targets": set(), "clients": {"FirstClient", "SecondClient"},
        "other": {"ThirdClient"}, "isolated": set(),
    }
    report = compute_report(analysis)
    assert report["ca"] == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_client_sum": 4, "partial_client_mean": 1.0, "partial_client_max": 3,
    }
    assert report["ce"] == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_source_sum": 3, "partial_source_mean": 0.75, "partial_source_max": 2,
    }


def test_static_dispatch_and_ancestor_fields_select_canonical_declaring_class(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """Runtime overrides add no edges; inherited calls and field modes select Base."""
    project = project_from_sources({
        "base.py": "class Base:\n    value = 1\n    def work(self): return self.value\n",
        "child.py": "from base import Base\nclass Child(Base):\n    def work(self): return 2\n"
                    "class Inherited(Base): pass\n",
        "client.py": "from base import Base\nfrom child import Inherited\n"
                     "class Client:\n    def run(self, value: Base, inherited: Inherited):\n"
                     "        value.work()\n        inherited.work()\n"
                     "        inherited.value += 1\n        del inherited.value\n"
                     "        return inherited.value\n",
    })
    override = next(symbol for symbol in project.symbols_by_id.values()
                    if symbol.qualified_name == "child.Child.work")
    assert any(override.id in use.runtime_targets.target_ids for use in project.source_uses_by_id.values())
    assert _named_edges(project) == {("Client", "Base")}


@pytest.mark.parametrize("statement", [
    "return value.field", "value.field = 2", "value.field += 1", "del value.field",
])
def test_each_declared_field_access_mode_can_supply_a_dependency(
    project_from_sources: Callable[[dict[str, str]], ProjectIR], statement: str,
) -> None:
    """Reads, writes, augmented writes, and deletes count without any method-call edge."""
    project = project_from_sources({
        "target.py": "class Target:\n    field = 1\n",
        "client.py": "from target import Target\nclass Client:\n"
                     f"    def run(self, value: Target):\n        {statement}\n",
    })
    assert _named_edges(project) == {("Client", "Target")}
    facts = category_dependencies(project)
    assert AfferentCoupling().compute(facts)["partial_client_sum"] == 1
    assert EfferentCoupling().compute(facts)["partial_source_sum"] == 1


def test_inheritance_types_construction_and_bare_methods_do_not_add_edges(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """Neither imports nor type/creation evidence is the selected member-use predicate."""
    project = project_from_sources({
        "target.py": "class Target:\n    def __init__(self): self.value = 1\n"
                     "    def work(self): return 1\n"
                     "class Contract:\n    def work(self): ...\n",
        "client.py": "from target import Target, Contract\n"
                     "class Client(Target):\n    field: Target\n"
                     "    def run(self, value: Target, contract: Contract):\n"
                     "        Target()\n        value.work\n        contract.work()\n"
                     "def free(value: Target): return value.work()\nTarget.work(None)\n",
    })
    assert _named_edges(project) == set()
    facts = category_dependencies(project)
    assert AfferentCoupling().compute(facts)["partial_client_sum"] == 0
    assert EfferentCoupling().compute(facts)["partial_source_sum"] == 0


def test_initialization_and_nested_functions_use_nearest_enclosing_class(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """Nested classes are their own clients; unsupported comprehensions are not promoted."""
    project = project_from_sources({
        "target.py": "class Target:\n    def work(self): return 1\n",
        "client.py": "from target import Target\nclass Outer:\n"
                     "    initial = Target.work(None)\n"
                     "    def run(self):\n        def nested(value: Target):\n"
                     "            return value.work()\n        return nested\n"
                     "    class Inner:\n        def run(self, value: Target): return value.work()\n"
                     "class Unsupported:\n    def run(self, value: Target):\n"
                     "        return [value.work() for _ in range(2)]\n",
    })
    assert _named_edges(project) == {("Outer", "Target"), ("Inner", "Target")}
    facts = category_dependencies(project)
    assert AfferentCoupling().compute(facts)["partial_client_sum"] == 2
    assert EfferentCoupling().compute(facts)["partial_source_sum"] == 2


def test_module_categories_do_not_merge_packages_names_or_repeated_classes(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """Same-package modules remain separate; duplicate names retain distinct identities."""
    project = project_from_sources({
        "pkg/__init__.py": "",
        "pkg/target.py": "class Target:\n    def work(self): return 1\n",
        "pkg/client.py": "from pkg.target import Target\nclass Client:\n"
                         "    def run(self, value: Target): return value.work()\n",
        "left/common.py": "class Repeated: pass\nclass Repeated:\n    class Nested: pass\n",
        "right/common.py": "class Repeated: pass\n",
    })
    facts = category_dependencies(project)
    assert len(facts.class_categories) == 6
    assert len(set(facts.class_categories.values())) == 4
    assert len({module.name for module in project.modules}) == 4
    assert _named_edges(project) == {("Client", "Target")}
    assert AfferentCoupling().compute(facts) == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_client_sum": 1, "partial_client_mean": 0.25, "partial_client_max": 1,
    }
    assert EfferentCoupling().compute(facts) == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_source_sum": 1, "partial_source_mean": 0.25, "partial_source_max": 1,
    }


def test_libraries_count_only_when_retained_and_unknown_references_stay_partial(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """An import alone supplies no external class identity or invented dependency."""
    sources = {
        "client.py": "from library import External\nclass Client:\n"
                     "    def run(self, value: External, unknown):\n"
                     "        unknown.work()\n        return value.work()\n",
    }
    outside = project_from_sources(sources)
    assert _named_edges(outside) == set()
    assert category_dependencies(outside).unavailable_categories == frozenset()
    assert AfferentCoupling().compute(category_dependencies(outside))["partial_client_sum"] == 0
    assert EfferentCoupling().compute(category_dependencies(outside))["partial_source_sum"] == 0
    sources["library.py"] = "class External:\n    def work(self): return 1\n"
    retained = project_from_sources(sources)
    assert _named_edges(retained) == {("Client", "External")}
    assert AfferentCoupling().compute(category_dependencies(retained))["partial_client_sum"] == 1
    assert EfferentCoupling().compute(category_dependencies(retained))["partial_source_sum"] == 1
    assert len([symbol for symbol in retained.symbols_by_id.values() if symbol.kind == SymbolKind.CLASS]) == 2


def test_unresolved_ambiguous_and_external_uses_cannot_establish_complete_incoming_zero(
    project_from_sources: Callable[[dict[str, str]], ProjectIR],
) -> None:
    """A supported target stays measured/partial despite unknown incoming callers."""
    project = project_from_sources({
        "target.py": "class Target:\n    def work(self): return 1\n",
        "client.py": "from library import External\nfrom target import Target\n"
                     "class Client:\n    def run(self, unknown, value: Target):\n"
                     "        unknown.work()\n        External.work()\n        value.work()\n"
                     "class Duplicate:\n    def work(self): return 1\n"
                     "    def work(self): return 2\n"
                     "class Ambiguous:\n    def run(self, value: Duplicate): return value.work()\n",
    })
    assert _named_edges(project) == {("Client", "Target")}
    assert {use.resolution.status for use in project.source_uses_by_id.values()} >= {
        "unresolved", "external", "ambiguous", "project",
    }
    facts = category_dependencies(project)
    assert facts.unavailable_categories == frozenset()
    assert AfferentCoupling().compute(facts) == {
        "measured_categories": 2, "unavailable_categories": 0,
        "partial_client_sum": 1, "partial_client_mean": 0.5, "partial_client_max": 1,
    }
    assert EfferentCoupling().compute(facts) == {
        "measured_categories": 2, "unavailable_categories": 0,
        "partial_source_sum": 1, "partial_source_mean": 0.5, "partial_source_max": 1,
    }
