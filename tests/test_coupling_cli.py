from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scb_check.cli import main
from scb_check.models import Report


@pytest.fixture
def coupling_trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Use independent snapshots with one config and no external ast-grep process."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    (tmp_path / "scb-check.toml").write_text("", encoding="utf-8")
    earlier, later = tmp_path / "earlier", tmp_path / "later"
    earlier.mkdir()
    later.mkdir()
    return earlier, later


def _check(tree: Path) -> Report:
    result = CliRunner().invoke(main, ["check", str(tree), "--output-format", "json"])
    assert result.exit_code in (0, 1), result.output
    return json.loads(result.stdout)


def _diff(earlier: Path, later: Path) -> dict[str, Report]:
    result = CliRunner().invoke(
        main, ["diff", str(earlier), str(later), "--output-format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["before"] == _check(earlier)
    assert payload["after"] == _check(later)
    return payload


@pytest.mark.parametrize("direction", [-1, 0, 1])
def test_cic_signed_and_zero_deltas_with_standalone_parity(
    coupling_trees: tuple[Path, Path], direction: int,
) -> None:
    """Repeated calls/references retain volume and metric-owned units in both commands."""
    earlier, later = coupling_trees
    prefix = "class Root:\n    def work(self): return 1\nclass Child(Root):\n"
    (earlier / "sample.py").write_text(prefix + "    pass\n", encoding="utf-8")
    (later / "sample.py").write_text(
        prefix + "    def run(self):\n        self.work()\n        return self.work\n",
        encoding="utf-8",
    )
    if direction == -1:
        earlier, later = later, earlier
    elif direction == 0:
        earlier = later
    payload = _diff(earlier, later)
    low = {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_occurrence_sum": 0, "partial_occurrence_mean": 0.0, "partial_occurrence_max": 0,
    }
    high = {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_occurrence_sum": 2, "partial_occurrence_mean": 1.0, "partial_occurrence_max": 2,
    }
    assert payload["before"]["cic"] == (low if direction == 1 else high)
    assert payload["after"]["cic"] == (low if direction == -1 else high)
    assert payload["diff"]["cic"] == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_occurrence_sum": 2 * direction,
        "partial_occurrence_mean": float(direction), "partial_occurrence_max": 2 * direction,
    }
    human = CliRunner().invoke(main, ["diff", str(earlier), str(later)])
    assert human.exit_code == 0, human.output
    assert any("cic.partial_occurrence_sum" in line and "occurrences" in line
               for line in human.stdout.splitlines())


@pytest.mark.parametrize("parenthesized", [
    "(self.work)()", "((self.work))()", "(\n            self.work\n        )()",
])
def test_cic_parenthesized_call_has_zero_metric_delta_and_standalone_parity(
    coupling_trees: tuple[Path, Path], parenthesized: str,
) -> None:
    """Adding call-target parentheses changes syntax, not CIC occurrence volume."""
    earlier, later = coupling_trees
    prefix = (
        "class Root:\n    def work(self): return 1\n"
        "class Child(Root):\n    def run(self):\n        "
    )
    (earlier / "sample.py").write_text(prefix + "self.work()\n", encoding="utf-8")
    (later / "sample.py").write_text(prefix + parenthesized + "\n", encoding="utf-8")
    payload = _diff(earlier, later)
    for snapshot in ("before", "after"):
        assert payload[snapshot]["cic"] == {
            "measured_classes": 2, "unavailable_classes": 0,
            "partial_occurrence_sum": 1, "partial_occurrence_mean": 0.5, "partial_occurrence_max": 1,
        }
    assert payload["diff"]["cic"] == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_occurrence_sum": 0, "partial_occurrence_mean": 0.0, "partial_occurrence_max": 0,
    }


@pytest.mark.parametrize("unavailable_sides", [(True, True), (True, False), (False, True)])
@pytest.mark.parametrize("unavailable_source", ["ancestry", "extraction"])
def test_cic_null_deltas_preserve_unavailability_and_standalone_parity(
    coupling_trees: tuple[Path, Path], unavailable_sides: tuple[bool, bool], unavailable_source: str,
) -> None:
    """Unknown ancestry and unsupported extraction propagate null on either snapshot side."""
    for tree, unavailable in zip(coupling_trees, unavailable_sides, strict=True):
        name, source = "sample.py", "class Empty: pass\n"
        if unavailable:
            name, source = (
                ("sample.py", "from library import External\nclass Child(External): pass\n")
                if unavailable_source == "ancestry" else ("sample.ts", "class Empty {}\n")
            )
        (tree / name).write_text(source, encoding="utf-8")
    payload = _diff(*coupling_trees)
    for snapshot, unavailable in zip(("before", "after"), unavailable_sides, strict=True):
        assert payload[snapshot]["cic"] == {
            "measured_classes": 0 if unavailable else 1,
            "unavailable_classes": 1 if unavailable else 0,
            "partial_occurrence_sum": None if unavailable else 0,
            "partial_occurrence_mean": None if unavailable else 0.0,
            "partial_occurrence_max": None if unavailable else 0,
        }
    for field in ("partial_occurrence_sum", "partial_occurrence_mean", "partial_occurrence_max"):
        assert payload["diff"]["cic"][field] is None
    human = CliRunner().invoke(main, ["diff", *(str(tree) for tree in coupling_trees)])
    assert human.exit_code == 0, human.output
    assert any("cic.partial_occurrence_sum" in line and "unavailable" in line
               for line in human.stdout.splitlines())


def test_rfc_check_and_diff_include_own_method_population(
    coupling_trees: tuple[Path, Path],
) -> None:
    """An isolated class contributes its own methods without a coupling edge."""
    earlier, later = coupling_trees
    (earlier / "sample.py").write_text(
        "class A:\n    def first(self):\n        return 1\n", encoding="utf-8",
    )
    (later / "sample.py").write_text(
        "class A:\n    def first(self):\n        return 1\n"
        "    def second(self):\n        return 2\n", encoding="utf-8",
    )
    payload = _diff(earlier, later)
    assert payload["before"]["rfc"] == {
        "measured_classes": 1, "unavailable_classes": 0,
        "partial_response_sum": 1, "partial_response_mean": 1.0, "partial_response_max": 1,
    }
    assert payload["after"]["rfc"] == {
        "measured_classes": 1, "unavailable_classes": 0,
        "partial_response_sum": 2, "partial_response_mean": 2.0, "partial_response_max": 2,
    }
    assert payload["diff"]["rfc"] == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_response_sum": 1, "partial_response_mean": 1.0, "partial_response_max": 1,
    }


@pytest.mark.parametrize("direction", [-1, 0, 1])
def test_coupling_deltas_preserve_units_and_standalone_check_parity(
    coupling_trees: tuple[Path, Path], direction: int,
) -> None:
    """Two sites add one response method, two messages, one caller, and two fields."""
    earlier, later = coupling_trees
    prefix = "class A:\n    def work(self):\n        return 1\nclass B:\n"
    (earlier / "sample.py").write_text(
        prefix + "    def run(self, other: A):\n        return 2\n", encoding="utf-8",
    )
    (later / "sample.py").write_text(
        prefix + "    first: A\n    second: A\n"
        "    def run(self, other: A):\n        return other.work() + other.work()\n",
        encoding="utf-8",
    )
    if direction == -1:
        earlier, later = later, earlier
    elif direction == 0:
        earlier = later
    payload = _diff(earlier, later)
    expected = {
        "rfc": ({"partial_response_sum": 2, "partial_response_mean": 1.0, "partial_response_max": 1},
                {"partial_response_sum": 3, "partial_response_mean": 1.5, "partial_response_max": 2},
                "methods"),
        "mpc": ({"partial_call_site_sum": 0, "partial_call_site_mean": 0.0, "partial_call_site_max": 0},
                {"partial_call_site_sum": 2, "partial_call_site_mean": 1.0, "partial_call_site_max": 2},
                "call sites"),
        "callers": ({"partial_caller_sum": 0, "partial_caller_mean": 0.0, "partial_caller_max": 0,
                     "partial_same_module_sum": 0, "partial_cross_module_sum": 0},
                    {"partial_caller_sum": 1, "partial_caller_mean": 0.5, "partial_caller_max": 1,
                     "partial_same_module_sum": 1, "partial_cross_module_sum": 0},
                    "callers"),
        "dac": ({"partial_attribute_sum": 0, "partial_attribute_mean": 0.0, "partial_attribute_max": 0},
                {"partial_attribute_sum": 2, "partial_attribute_mean": 1.0, "partial_attribute_max": 2},
                "attributes"),
    }
    human = CliRunner().invoke(main, ["diff", str(earlier), str(later)])
    assert human.exit_code == 0, human.output
    for group, (low, high, unit) in expected.items():
        first, second = (high, low) if direction == -1 else (low, high)
        if direction == 0:
            first = second = high
        population = "callables" if group == "callers" else "classes"
        assert payload["before"][group] == {
            f"measured_{population}": 2, f"unavailable_{population}": 0, **first,
        }
        assert payload["after"][group] == {
            f"measured_{population}": 2, f"unavailable_{population}": 0, **second,
        }
        assert payload["diff"][group] == {
            f"measured_{population}": 0, f"unavailable_{population}": 0,
            **{field: second[field] - first[field] for field in first},
        }
        for field in low:
            assert any(
                f"{group}.{field}" in line and unit in line and "%" not in line
                for line in human.stdout.splitlines()
            )


@pytest.mark.parametrize("unsupported_sides", [(True, True), (True, False), (False, True)])
def test_unsupported_coupling_is_null_not_zero(
    coupling_trees: tuple[Path, Path], unsupported_sides: tuple[bool, bool],
) -> None:
    """Unknown snapshots propagate null, even when the other snapshot measures zero."""
    for tree, unsupported in zip(coupling_trees, unsupported_sides, strict=True):
        name, source = (
            ("sample.ts", "class A { work() { return 1; } }\n")
            if unsupported else
            ("sample.py", "class A:\n    def work(self):\n        return 1\n")
        )
        (tree / name).write_text(source, encoding="utf-8")
    payload = _diff(*coupling_trees)
    human = CliRunner().invoke(main, ["diff", *(str(tree) for tree in coupling_trees)])
    assert human.exit_code == 0, human.output
    summaries = {
        "rfc": {"partial_response_sum": 1, "partial_response_mean": 1.0, "partial_response_max": 1},
        "mpc": {"partial_call_site_sum": 0, "partial_call_site_mean": 0.0, "partial_call_site_max": 0},
        "callers": {"partial_caller_sum": 0, "partial_caller_mean": 0.0, "partial_caller_max": 0,
                    "partial_same_module_sum": 0, "partial_cross_module_sum": 0},
        "dac": {"partial_attribute_sum": 0, "partial_attribute_mean": 0.0, "partial_attribute_max": 0},
    }
    for group, supported in summaries.items():
        population = "callables" if group == "callers" else "classes"
        for snapshot, unsupported in zip(("before", "after"), unsupported_sides, strict=True):
            assert payload[snapshot][group] == {
                f"measured_{population}": 0 if unsupported else 1,
                f"unavailable_{population}": 1 if unsupported else 0,
                **{field: None if unsupported else value for field, value in supported.items()},
            }
        for field in supported:
            assert payload["diff"][group][field] is None
            assert any(
                f"{group}.{field}" in line and "unavailable" in line
                for line in human.stdout.splitlines()
            )


def test_mpc_subclass_override_does_not_change_static_call_volume(
    coupling_trees: tuple[Path, Path],
) -> None:
    """Adding an override does not turn an own-method call into an external site."""
    earlier, later = coupling_trees
    prefix = (
        "class A:\n    def run(self): return self.work()\n"
        "    def work(self): return 1\nclass B(A):\n"
    )
    (earlier / "sample.py").write_text(prefix + "    pass\n", encoding="utf-8")
    (later / "sample.py").write_text(
        prefix + "    def work(self): return 2\n", encoding="utf-8",
    )
    payload = _diff(earlier, later)
    for snapshot in ("before", "after"):
        assert payload[snapshot]["mpc"] == {
            "measured_classes": 2, "unavailable_classes": 0,
            "partial_call_site_sum": 0, "partial_call_site_mean": 0.0,
            "partial_call_site_max": 0,
        }
    assert payload["diff"]["mpc"] == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_call_site_sum": 0, "partial_call_site_mean": 0.0,
        "partial_call_site_max": 0,
    }


def test_callers_keep_recursion_and_module_partitions_in_cli_reports(
    coupling_trees: tuple[Path, Path],
) -> None:
    """Self, local, and imported callers each count once despite repeated sites."""
    earlier, later = coupling_trees
    (earlier / "target.py").write_text(
        "def target():\n    return 1\ndef local():\n    return 2\n", encoding="utf-8",
    )
    (later / "target.py").write_text(
        "def target():\n    return target()\ndef local():\n    return target() + target()\n",
        encoding="utf-8",
    )
    (earlier / "client.py").write_text(
        "from target import target\ndef external():\n    return 3\n", encoding="utf-8",
    )
    (later / "client.py").write_text(
        "from target import target\ndef external():\n    return target() + target()\n",
        encoding="utf-8",
    )
    payload = _diff(earlier, later)
    assert payload["before"]["callers"] == {
        "measured_callables": 3, "unavailable_callables": 0,
        "partial_caller_sum": 0, "partial_caller_mean": 0.0, "partial_caller_max": 0,
        "partial_same_module_sum": 0, "partial_cross_module_sum": 0,
    }
    assert payload["after"]["callers"] == {
        "measured_callables": 3, "unavailable_callables": 0,
        "partial_caller_sum": 3, "partial_caller_mean": 1.0, "partial_caller_max": 3,
        "partial_same_module_sum": 2, "partial_cross_module_sum": 1,
    }
    assert payload["diff"]["callers"] == {
        "measured_callables": 0, "unavailable_callables": 0,
        "partial_caller_sum": 3, "partial_caller_mean": 1.0, "partial_caller_max": 3,
        "partial_same_module_sum": 2, "partial_cross_module_sum": 1,
    }


def test_rfc_cli_uses_retained_inherited_method_selections(
    coupling_trees: tuple[Path, Path],
) -> None:
    """A new base method enters both the base and inheriting class response sets."""
    earlier, later = coupling_trees
    prefix = "class Base:\n    def first(self):\n        return 1\n"
    suffix = "class Child(Base):\n    pass\n"
    (earlier / "sample.py").write_text(prefix + suffix, encoding="utf-8")
    (later / "sample.py").write_text(
        prefix + "    def second(self):\n        return 2\n" + suffix, encoding="utf-8",
    )
    payload = _diff(earlier, later)
    assert payload["before"]["rfc"] == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_response_sum": 2, "partial_response_mean": 1.0, "partial_response_max": 1,
    }
    assert payload["after"]["rfc"] == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_response_sum": 4, "partial_response_mean": 2.0, "partial_response_max": 2,
    }
    assert payload["diff"]["rfc"] == {
        "measured_classes": 0, "unavailable_classes": 0,
        "partial_response_sum": 2, "partial_response_mean": 1.0, "partial_response_max": 1,
    }
