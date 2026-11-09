"""Historical Ca counts external client classes, not importing modules or sites."""

from scb_check.metrics.ca import AfferentCoupling
from scb_check.metrics.categories import CategoryDependencies


def test_ca_deduplicates_clients_per_category(category_facts: CategoryDependencies) -> None:
    """One client using multiple internal classes contributes only once to Ca."""
    assert AfferentCoupling().client_sets(category_facts) == {
        "A": frozenset({"b1", "b2", "c2"}), "B": frozenset(),
        "C": frozenset({"b1"}), "D": frozenset(),
    }
    assert AfferentCoupling().compute(category_facts) == {
        "measured_categories": 4, "unavailable_categories": 0,
        "partial_client_sum": 4, "partial_client_mean": 1.0, "partial_client_max": 3,
    }
