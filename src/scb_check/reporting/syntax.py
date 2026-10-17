"""Syntax totals and flat per-language tree and node counts."""

from types import MappingProxyType
from typing import ClassVar

from scb_check.models import LanguageSyntaxSummary
from scb_check.models import MetricResult
from scb_check.models import ReportValue
from scb_check.reporting.units import Unit


class Syntax:
    """Summarize extracted syntax counts without accessing parser-native trees."""

    # Dotted language fields have the same unit as their count suffix.
    units: ClassVar[dict[str, Unit]] = {"tree_count": "trees", "node_count": "nodes"}

    def compute(
        self, summaries: tuple[LanguageSyntaxSummary, ...]
    ) -> MetricResult:
        """Include only languages present in the analysis, in sorted order."""
        result: dict[str, ReportValue] = {
            "tree_count": sum(summary.tree_count for summary in summaries),
            "node_count": sum(summary.node_count for summary in summaries),
        }
        for summary in sorted(
            summaries, key=lambda summary: summary.language.value
        ):
            result[f"{summary.language.value}.tree_count"] = summary.tree_count
            result[f"{summary.language.value}.node_count"] = summary.node_count
        return MappingProxyType(result)
