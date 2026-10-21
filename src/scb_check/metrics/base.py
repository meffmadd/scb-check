"""Shared metric contract, parameterized by each metric's extracted-fact inputs."""

from abc import ABC
from abc import abstractmethod
from typing import ClassVar

from scb_check.metrics.units import Unit
from scb_check.models import MetricResult


class Metric[**Inputs](ABC):
    """Calculate a flat read-only result while retaining metric-specific inputs."""

    units: ClassVar[dict[str, Unit]]

    @abstractmethod
    def compute(
        self, *args: Inputs.args, **kwargs: Inputs.kwargs
    ) -> MetricResult:
        """Calculate named measurements from the metric's extracted facts."""
        ...
