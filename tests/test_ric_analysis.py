"""Known-value RIC from retained Python source facts."""

from pathlib import Path

from scb_check.metrics.ric import RIC
from scb_check.metrics.ric import RICPair
from scb_check.pipeline import analyze_files

FIXTURE = Path(__file__).parent / "fixtures" / "ric" / "direct.py"


def test_known_ratios_keep_canonical_ownership_and_static_dispatch() -> None:
    """Repeated, inherited, placeholder, recursive and unknown uses retain distinct roles."""
    project = analyze_files((FIXTURE,), disable_sg=True).project
    names = {symbol.id: symbol.qualified_name for symbol in project.symbols_by_id.values()}
    pairs = {
        (names[method], names[comparison]): value
        for (method, comparison), value in RIC().pair_diagnostics(project.modules).items()
    }
    assert len(pairs) == 48
    assert pairs["direct.Owner.target", "direct.Client"] == RICPair(3, 2, 2, 1.5)
    assert pairs["direct.Owner.target", "direct.Other"] == RICPair(1, 2, 2, 0.5)
    assert pairs["direct.Owner.target", "direct.Child"] == RICPair(1, 2, 2, 0.5)
    assert pairs["direct.Owner.zero_owner", "direct.Client"] == RICPair(1, 0, 1, 1.0)
    assert pairs["direct.Owner.zero_owner", "direct.Other"] == RICPair(0, 0, 1, 0.0)
    assert pairs["direct.Owner.recur", "direct.Client"] == RICPair(1, 1, 1, 1.0)
    assert pairs["direct.Owner.unused", "direct.Client"] == RICPair(0, 0, 1, 0.0)
    assert pairs["direct.Override.target", "direct.Client"] == RICPair(0, 0, 1, 0.0)
    assert {method for method, _ in pairs if method.startswith("direct.Child.")} == {"direct.Child.run"}
    assert RIC().compute(project.modules) == {
        "measured_pairs": 48, "unavailable_pairs": 0,
        "partial_ratio_mean": 0.09375, "partial_ratio_max": 1.5,
    }


def test_retained_facts_are_sufficient_after_source_is_removed(tmp_path: Path) -> None:
    """The metric consumes immutable analysis, not source or a second resolver."""
    source = tmp_path / "sample.py"
    source.write_text(
        "class A:\n    def target(self): ...\n"
        "class B:\n    def use(self, value: A): return value.target()\n",
        encoding="utf-8",
    )
    project = analyze_files((source,), disable_sg=True).project
    source.unlink()
    assert RIC().compute(project.modules) == {
        "measured_pairs": 2, "unavailable_pairs": 0,
        "partial_ratio_mean": 0.5, "partial_ratio_max": 1.0,
    }
