"""Known attribute-count DAC values from retained Python source facts."""

from pathlib import Path

import pytest

from scb_check.metrics.dac import DAC
from scb_check.pipeline import analyze_files

FIXTURE = Path(__file__).parent / "fixtures" / "dac" / "composition.py"


def test_declared_attribute_volume_not_type_breadth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Self, ancestor, and repeated types count; inherited copies and locals do not."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files((FIXTURE,)).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    diagnostics = DAC().attribute_sets(project.modules)
    attribute_names = {
        names[class_id]: None if attribute_ids is None else {
            project.attributes_by_id[attribute_id].name for attribute_id in attribute_ids
        }
        for class_id, attribute_ids in diagnostics.items()
    }
    assert attribute_names == {
        "Part": set(), "Box": set(), "Base": {"inherited"},
        "Child": {"first", "second", "ancestor", "self_type", "quoted", "boxed", "instance"},
        "Nested": {"value"}, "EmptyChild": set(),
    }
    assert DAC().compute(project.modules) == {
        "measured_classes": 6, "unavailable_classes": 0,
        "partial_attribute_sum": 9, "partial_attribute_mean": 1.5, "partial_attribute_max": 7,
    }


def test_library_classes_count_only_when_their_source_is_retained(tmp_path: Path) -> None:
    """No library import or new resolution is performed by the metric itself."""
    library = tmp_path / "library.py"
    library.write_text("class Item: pass\n")
    client = tmp_path / "client.py"
    client.write_text("from library import Item\nclass Client:\n    value: Item\n")
    outside_project = analyze_files((client,), disable_sg=True).project
    included = analyze_files((client, library), disable_sg=True).project
    client.unlink()
    library.unlink()

    assert DAC().compute(outside_project.modules) == {
        "measured_classes": 1, "unavailable_classes": 0,
        "partial_attribute_sum": 0, "partial_attribute_mean": 0.0, "partial_attribute_max": 0,
    }
    assert DAC().compute(included.modules) == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_attribute_sum": 1, "partial_attribute_mean": 0.5, "partial_attribute_max": 1,
    }


def test_unresolved_types_and_incoming_writes_do_not_claim_complete_zero(tmp_path: Path) -> None:
    """Unsupported external writes are not new fields of a declared class."""
    source = tmp_path / "unknown.py"
    source.write_text(
        "class Client:\n"
        "    unknown: Missing\n"
        "    unannotated = object()\n"
        "def incoming(value: Client):\n"
        "    value.hidden = Client()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    assert DAC().compute(project.modules) == {
        "measured_classes": 1, "unavailable_classes": 0,
        "partial_attribute_sum": 0, "partial_attribute_mean": 0.0, "partial_attribute_max": 0,
    }
    assert {attribute.name for attribute in project.attributes_by_id.values()} == {"unknown", "unannotated"}
