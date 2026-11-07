"""Known Message Passing Coupling values through the retained source-analysis seam."""

from pathlib import Path

import pytest

from scb_check.metrics.mpc import MPC
from scb_check.pipeline import analyze_files

FIXTURE = Path(__file__).parent / "fixtures" / "mpc" / "calls.py"


def test_repetition_loops_and_inherited_implementation_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three caller sites stay three; inherited bodies belong only to their declarer."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files((FIXTURE,)).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in MPC().class_counts(project.modules).items()} == {
        "Target": 0, "Override": 0, "Caller": 3, "Ancestor": 1, "Child": 1,
        "EmptyChild": 0, "SelfOnly": 0, "Contract": 0, "ContractClient": 0,
        "IgnoredBodies": 0, "StaticSource": 2,
    }
    assert MPC().compute(project.modules) == {
        "measured_classes": 11, "unavailable_classes": 0,
        "partial_call_site_sum": 7, "partial_call_site_mean": 7 / 11,
        "partial_call_site_max": 3,
    }


def test_unknown_library_and_free_function_calls_are_partial_not_method_calls(
    tmp_path: Path,
) -> None:
    """Only known project method bodies count; no later source IO is needed."""
    source = tmp_path / "unknown.py"
    source.write_text(
        "from library import External\n"
        "def helper(): return 1\n"
        "class Known:\n    def work(self): return 1\n"
        "class Client:\n    def run(self, unknown):\n"
        "        unknown.work()\n        External.work()\n"
        "        helper()\n        Known()\n        return Known.work\n"
        "def incoming(unknown):\n    unknown.work()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    source.unlink()
    assert MPC().compute(project.modules) == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_call_site_sum": 0, "partial_call_site_mean": 0.0, "partial_call_site_max": 0,
    }


def test_unsupported_source_classes_do_not_become_observed_zero(tmp_path: Path) -> None:
    """An unsupported class is outside the measured denominator, unlike empty Python."""
    unsupported = tmp_path / "unsupported.ts"
    unsupported.write_text("class Unsupported { work() { return 1; } }\n")
    supported = tmp_path / "supported.py"
    supported.write_text("class Empty: pass\n")
    project = analyze_files((unsupported, supported), disable_sg=True).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    assert {names[key]: count for key, count in MPC().class_counts(project.modules).items()} == {
        "Unsupported": None, "Empty": 0,
    }
    assert MPC().compute(project.modules) == {
        "measured_classes": 1, "unavailable_classes": 1,
        "partial_call_site_sum": 0, "partial_call_site_mean": 0.0, "partial_call_site_max": 0,
    }
