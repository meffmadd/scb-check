"""Category population availability and read-only numerical/diagnostic interfaces."""

from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError
from dataclasses import replace
from typing import cast

import pytest

from scb_check.metrics.ca import AfferentCoupling
from scb_check.metrics.categories import CategoryDependencies
from scb_check.metrics.ce import EfferentCoupling
from scb_check.models import ReportValue


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        (AfferentCoupling(), {
            "partial_client_sum": 4, "partial_client_mean": 4 / 3, "partial_client_max": 3,
        }),
        (EfferentCoupling(), {
            "partial_source_sum": 1, "partial_source_mean": 1 / 3, "partial_source_max": 1,
        }),
    ],
)
def test_unavailable_category_is_excluded_not_zeroed(
    category_facts: CategoryDependencies,
    metric: AfferentCoupling | EfferentCoupling,
    expected: dict[str, ReportValue],
) -> None:
    """Known edges from/to unavailable B still inform other measured categories."""
    partial = replace(category_facts, unavailable_categories=frozenset({"B"}))
    assert metric.compute(partial) == {
        "measured_categories": 3, "unavailable_categories": 1, **expected,
    }
    assert AfferentCoupling().client_sets(partial)["B"] is None
    assert EfferentCoupling().source_sets(partial)["B"] is None


@pytest.mark.parametrize("unsupported", [False, True])
@pytest.mark.parametrize("metric", [AfferentCoupling(), EfferentCoupling()])
def test_empty_or_wholly_unavailable_population_has_null_summaries(
    metric: AfferentCoupling | EfferentCoupling, *, unsupported: bool,
) -> None:
    """No measured categories differs from a measured isolated category's zero."""
    facts = CategoryDependencies(
        {"unknown": "U"} if unsupported else {},
        frozenset({"U"}) if unsupported else frozenset(), frozenset(),
    )
    result = metric.compute(facts)
    prefix = "partial_client" if isinstance(metric, AfferentCoupling) else "partial_source"
    assert result == {
        "measured_categories": 0, "unavailable_categories": int(unsupported),
        f"{prefix}_sum": None, f"{prefix}_mean": None, f"{prefix}_max": None,
    }
    assert metric.units.keys() == result.keys()


def test_category_facts_and_metric_views_are_immutable_owned_data(
    category_facts: CategoryDependencies,
) -> None:
    """Caller mutations cannot change membership, diagnostics, or later results."""
    membership = {"client": "C", "target": "T"}
    facts = CategoryDependencies(membership, frozenset(), frozenset({("client", "target")}))
    membership.clear()
    assert facts.class_categories == {"client": "C", "target": "T"}
    with pytest.raises(FrozenInstanceError):
        setattr(facts, "class_edges", frozenset())  # noqa: B010
    with pytest.raises(TypeError):
        cast("MutableMapping[str, str]", facts.class_categories)["client"] = "T"
    for result in (AfferentCoupling().compute(facts), EfferentCoupling().compute(facts)):
        with pytest.raises(TypeError):
            cast("MutableMapping[str, ReportValue]", result)["measured_categories"] = 99
    for diagnostic in (AfferentCoupling().client_sets(category_facts),
                       EfferentCoupling().source_sets(category_facts)):
        with pytest.raises(TypeError):
            cast("MutableMapping[str, frozenset[str] | None]", diagnostic)["A"] = None
        assert all(value is None or isinstance(value, frozenset) for value in diagnostic.values())
