from collections.abc import Callable
from typing import cast

import pytest

from scb_check.metrics.base import Metric


def test_metric_requires_a_compute_implementation() -> None:
    """The abstract metric cannot be instantiated without implementing `compute`."""
    # Deliberately bypass static abstract-class checking to test runtime enforcement.
    constructor = cast("Callable[[], Metric[[]]]", Metric)

    with pytest.raises(TypeError, match="abstract"):
        constructor()
