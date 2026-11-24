"""Shared metric contract, parameterized by each metric's extracted-fact inputs."""

from abc import ABC
from abc import abstractmethod
from typing import ClassVar

from scb_check.metrics.units import Unit
from scb_check.models import MetricResult


class Metric[**Inputs](ABC):
    """Calculate a flat read-only result while retaining metric-specific inputs.

    Concrete metrics declare `units` for every result field and an ordered
    `headline_fields` selection of those fields. Headlines are the measurements
    presented by default; the others are supporting measurements. Membership
    makes no claim about quality, desirability, or growth invariance.
    """

    units: ClassVar[dict[str, Unit]]
    headline_fields: ClassVar[tuple[str, ...]]

    @abstractmethod
    def compute(
        self, *args: Inputs.args, **kwargs: Inputs.kwargs
    ) -> MetricResult:
        """Calculate named measurements from the metric's extracted facts."""
        ...
