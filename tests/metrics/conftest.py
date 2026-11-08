"""Immutable directed class facts shared by the independent category metrics."""

import pytest

from scb_check.metrics.categories import CategoryDependencies


@pytest.fixture
def category_facts() -> CategoryDependencies:
    """Three clients use A; B has two outgoing sources, not three target classes."""
    return CategoryDependencies(
        class_categories={
            "a1": "A", "a2": "A", "internal": "A", "b1": "B", "b2": "B",
            "c1": "C", "c2": "C", "isolated": "D",
        },
        unavailable_categories=frozenset(),
        class_edges=frozenset({
            ("internal", "a1"), ("b1", "a1"), ("b1", "a2"),
            ("b1", "c1"), ("b2", "a1"), ("c2", "a1"),
        }),
    )
