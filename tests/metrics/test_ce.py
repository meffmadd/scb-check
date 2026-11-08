"""Historical Ce counts internal source classes, never external target breadth."""

from scb_check.metrics.categories import CategoryDependencies
from scb_check.metrics.ce import EfferentCoupling


def test_ce_saturates_per_internal_source_class(category_facts: CategoryDependencies) -> None:
    """B has two sources even though one depends on three outside classes."""
    assert EfferentCoupling().source_sets(category_facts) == {
        "A": frozenset(), "B": frozenset({"b1", "b2"}),
        "C": frozenset({"c2"}), "D": frozenset(),
    }
    assert EfferentCoupling().compute(category_facts) == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_source_sum": 3, "partial_source_mean": 0.75, "partial_source_max": 2,
    }


def test_twenty_external_targets_still_contribute_one_source() -> None:
    """Ce's historical population is internal source classes, not target breadth."""
    facts = CategoryDependencies(
        {"client": "inside", **{f"target{index}": "outside" for index in range(20)}},
        frozenset(),
        frozenset(("client", f"target{index}") for index in range(20)),
    )
    assert EfferentCoupling().source_sets(facts) == {
        "inside": frozenset({"client"}), "outside": frozenset(),
    }
    assert EfferentCoupling().compute(facts) == {
        "measured_categories": 2, "unavailable_categories": 0,
        "partial_source_sum": 1, "partial_source_mean": 0.5, "partial_source_max": 1,
    }
