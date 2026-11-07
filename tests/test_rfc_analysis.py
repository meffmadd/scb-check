"""Known direct response sets from Python source and retained project resolution."""

from pathlib import Path

from scb_check.metrics.rfc import RFC
from scb_check.pipeline import analyze_files

FIXTURE = Path(__file__).parent / "fixtures" / "rfc" / "direct.py"


def test_known_direct_response_counts_include_inherited_selected_methods() -> None:
    """Inherited bodies contribute their direct calls, but second hops never do."""
    project = analyze_files((FIXTURE,), disable_sg=True).project
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}
    responses = RFC().response_sets(project)

    assert {
        names[class_id]: {names[method] for method in methods} if methods is not None else None
        for class_id, methods in responses.items()
    } == {
        "direct.Leaf": {"direct.Leaf.finish"},
        "direct.Middle": {"direct.Middle.work", "direct.Leaf.finish"},
        "direct.Base": {"direct.Base.run", "direct.Base.stay", "direct.Middle.work"},
        "direct.Child": {"direct.Base.run", "direct.Child.stay", "direct.Middle.work"},
        "direct.Override": {"direct.Override.run", "direct.Base.stay"},
        "direct.Isolated": {"direct.Isolated.first", "direct.Isolated.second"},
        "direct.Empty": set(),
    }
    assert RFC().compute(project) == {
        "measured_classes": 7, "unavailable_classes": 0,
        "partial_response_sum": 13, "partial_response_mean": 13 / 7, "partial_response_max": 3,
    }


def test_polymorphic_bodies_and_bodyless_declarations_have_distinct_roles(tmp_path: Path) -> None:
    """An abstract seed counts itself; a call adds concrete bodies, not the bodyless target."""
    source = tmp_path / "polymorphic.py"
    source.write_text(
        "from abc import abstractmethod\n"
        "class Contract:\n"
        "    @abstractmethod\n"
        "    def work(self): ...\n"
        "class First(Contract):\n"
        "    def work(self): return 1\n"
        "class Second(Contract):\n"
        "    def work(self): return 2\n"
        "class Client:\n"
        "    def run(self, value: Contract):\n"
        "        value.work()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}
    source.unlink()  # Calculation must use only the retained immutable project.

    assert {
        names[class_id]: {names[method] for method in methods} if methods is not None else None
        for class_id, methods in RFC().response_sets(project).items()
    } == {
        "polymorphic.Contract": {"polymorphic.Contract.work"},
        "polymorphic.First": {"polymorphic.First.work"},
        "polymorphic.Second": {"polymorphic.Second.work"},
        "polymorphic.Client": {"polymorphic.Client.run", "polymorphic.First.work", "polymorphic.Second.work"},
    }
    assert RFC().compute(project)["partial_response_sum"] == 6


def test_nonmethod_unknown_generated_and_nondirect_calls_do_not_expand_response(tmp_path: Path) -> None:
    """Uncertain targets remain partial, while references and nested execution are not calls."""
    source = tmp_path / "partial.py"
    source.write_text(
        "from dataclasses import dataclass\n"
        "from library import External\n"
        "def helper(): return 1\n"
        "class Target:\n"
        "    def work(self): return 1\n"
        "@dataclass\n"
        "class Generated:\n"
        "    field: int\n"
        "class Client:\n"
        "    def run(self, unknown, target: Target):\n"
        "        helper()\n"
        "        unknown.work()\n"
        "        External.work()\n"
        "        Target()\n"
        "        target.work\n"
        "        def nested():\n"
        "            target.work()\n"
        "        nested()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}

    assert {
        names[class_id]: {names[method] for method in methods} if methods is not None else None
        for class_id, methods in RFC().response_sets(project).items()
    } == {
        "partial.Target": {"partial.Target.work"},
        "partial.Generated": set(),
        "partial.Client": {"partial.Client.run"},
    }
    assert RFC().compute(project) == {
        "measured_classes": 3, "unavailable_classes": 0,
        "partial_response_sum": 2, "partial_response_mean": 2 / 3, "partial_response_max": 1,
    }
