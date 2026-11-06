"""Known partner counts from real Python source and retained resolution evidence."""

from pathlib import Path

import pytest

from scb_check.metrics.cbo import CBO
from scb_check.pipeline import analyze_files
from scb_check.reporting.score import compute_report

FIXTURE = Path(__file__).parent / "fixtures" / "cbo" / "partners.py"


def test_member_use_ancestor_and_polymorphic_partners(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only use introduces edges; inheritance and annotations do not."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    project = analyze_files((FIXTURE,)).project
    names = {symbol.id: symbol.name for symbol in project.symbols_by_id.values()}
    partners = CBO().partner_sets(project.modules)
    assert {names[key]: {names[partner] for partner in value} if value is not None else None
            for key, value in partners.items()} == {
        "Base": {"Client", "Child", "AttrsOnly"},
        "Override": {"Client"},
        "Client": {"Base", "Override"},
        "Child": {"Base"},
        "TypeOnly": set(), "EmptyChild": set(), "SelfOnly": set(),
        "AttrsOnly": {"Base"},
    }
    assert CBO().compute(project.modules) == {
        "measured_classes": 8, "unavailable_classes": 0,
        "partial_partner_sum": 8, "partial_partner_mean": 1.0, "partial_partner_max": 3,
    }


def test_placeholder_declarations_do_not_count_as_implemented_member_use(
    tmp_path: Path,
) -> None:
    """A bodyless contract is not an implementation partner without a known body."""
    source = tmp_path / "contract.py"
    source.write_text(
        "class Contract:\n    def work(self): ...\n"
        "class Client:\n    def run(self, value: Contract):\n        value.work()\n"
    )
    project = analyze_files((source,), disable_sg=True).project
    assert CBO().compute(project.modules)["partial_partner_sum"] == 0


def test_unknown_library_and_incoming_uses_remain_explicitly_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown references never turn a partial zero into a verified complete zero."""
    monkeypatch.setattr("scb_check.pipeline.run_sg", lambda _files, _rules_path: ())
    source = tmp_path / "unknown.py"
    source.write_text(
        "from library import External\n"
        "class Known:\n    def work(self): return 1\n"
        "class Client:\n    def run(self, unknown):\n"
        "        unknown.work()\n        External.work()\n"
        "def incoming(unknown):\n    unknown.work()\n"
    )
    analysis = analyze_files((source,))
    source.unlink()  # Metrics/reporting must consume only retained facts.
    result = compute_report(analysis)["cbo"]
    assert result == {
        "measured_classes": 2, "unavailable_classes": 0,
        "partial_partner_sum": 0, "partial_partner_mean": 0.0, "partial_partner_max": 0,
    }
    assert "score" not in result
