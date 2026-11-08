"""Known CIC values from retained immutable source facts."""

from pathlib import Path

import pytest

from scb_check.metrics.cic import CIC
from scb_check.pipeline import analyze_files

FIXTURE = Path(__file__).parent / "fixtures" / "cic" / "occurrences.py"


def test_proper_ancestors_repeated_sites_overrides_and_source_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each call counts once; inherited bodies never become new subclass sites."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files((FIXTURE,)).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in CIC().class_counts(project.modules).items()} == {
        "Root": 0, "Middle": 4, "Leaf": 4, "EmptyLeaf": 0,
        "Unrelated": 0, "DeclarationOnly": 0,
    }
    assert CIC().compute(project.modules) == {
        "measured_classes": 6, "unavailable_classes": 0,
        "partial_occurrence_sum": 8, "partial_occurrence_mean": 8 / 6,
        "partial_occurrence_max": 4,
    }


def test_unresolved_ancestry_is_unavailable_but_unknown_members_are_partial(tmp_path: Path) -> None:
    """External/unknown bases propagate unavailability, not invented ancestor zeros."""
    source = tmp_path / "unknown.py"
    source.write_text(
        "from library import External\n"
        "class Root:\n    def work(self): return 1\n"
        "class Client(Root):\n"
        "    def run(self, unknown):\n"
        "        unknown.work()\n        External.work()\n"
        "        return [self.work() for _ in ()]\n"
        "class LibraryChild(External): pass\n"
        "class UnknownChild(Missing): pass\n"
        "class Descendant(LibraryChild): pass\n"
        "def incoming(unknown): return unknown.work()\n",
        encoding="utf-8",
    )
    unsupported = tmp_path / "unsupported.ts"
    unsupported.write_text("class Unsupported {}\n", encoding="utf-8")
    project = analyze_files((source, unsupported), disable_sg=True).project
    source.unlink()
    unsupported.unlink()
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in CIC().class_counts(project.modules).items()} == {
        "Root": 0, "Client": 0, "LibraryChild": None, "UnknownChild": None,
        "Descendant": None, "Unsupported": None,
    }
    assert CIC().compute(project.modules) == {
        "measured_classes": 2, "unavailable_classes": 4,
        "partial_occurrence_sum": 0, "partial_occurrence_mean": 0.0, "partial_occurrence_max": 0,
    }


def test_imported_ancestor_members_use_canonical_owners_without_source_rereading(tmp_path: Path) -> None:
    """Already-resolved cross-module ancestry and members survive removal of source files."""
    base = tmp_path / "base.py"
    base.write_text("class Root:\n    field = 1\n    def work(self): return 1\n", encoding="utf-8")
    child = tmp_path / "child.py"
    child.write_text(
        "from base import Root as Parent\nclass Child(Parent):\n"
        "    def run(self):\n        self.work()\n        return self.field\n",
        encoding="utf-8",
    )
    project = analyze_files((base, child), disable_sg=True).project
    base.unlink()
    child.unlink()
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in CIC().class_counts(project.modules).items()} == {
        "Root": 0, "Child": 2,
    }


def test_bodyless_targets_and_nested_classes_do_not_manufacture_member_uses(tmp_path: Path) -> None:
    """Placeholder methods and unsupported bodies add no sites or enclosing-class uses."""
    source = tmp_path / "ownership.py"
    source.write_text(
        "class Root:\n"
        "    def placeholder(self): ...\n"
        "    def work(self): return 1\n"
        "class Child(Root):\n"
        "    def run(self):\n"
        "        self.placeholder()\n"
        "        reference = self.placeholder\n"
        "        thunk = lambda: self.work()\n"
        "        class Nested:\n"
        "            selected = Root.work\n"
        "        return reference\n",
        encoding="utf-8",
    )
    project = analyze_files((source,), disable_sg=True).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in CIC().class_counts(project.modules).items()} == {
        "Root": 0, "Child": 0, "Nested": 0,
    }
