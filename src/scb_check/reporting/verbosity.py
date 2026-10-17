"""Verbosity: the union of flagged SLOC as a share of all SLOC."""

from collections import defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

from scb_check.models import LineGroups
from scb_check.models import MetricResult
from scb_check.reporting.units import Unit
from scb_check.tree_walking.models import RuleFinding


class Verbosity:
    """Calculate the flagged-line union and its contributing measurements."""

    units: ClassVar[dict[str, Unit]] = {
        "score": "fraction",
        "files_scanned": "files",
        "total_loc": "lines",
        "flagged_loc": "lines",
        "clone_loc": "lines",
        "ast_grep_flagged_loc": "lines",
        "structural_rule_loc": "lines",
        "structural_rule_findings": "findings",
    }

    def compute(
        self, lines: LineGroups, structural_findings: tuple[RuleFinding, ...]
    ) -> MetricResult:
        """Compute from SLOC-projected line accounting and structural findings."""
        total_loc = sum(loc for _, loc in lines.total_loc_by_file)
        flagged_by_file: defaultdict[Path, set[int]] = defaultdict(set)
        contributions = (
            lines.clone_sloc_lines_by_file,
            lines.ast_sloc_lines_by_file,
            lines.structural_sloc_lines_by_file,
        )
        for entries in contributions:
            for entry in entries:
                flagged_by_file[entry.file].update(entry.lines)
        flagged_loc = (
            sum(len(flagged) for flagged in flagged_by_file.values())
            if total_loc
            else 0
        )
        clone_loc, ast_loc, structural_loc = (
            sum(len(entry.lines) for entry in entries) if total_loc else 0
            for entries in contributions
        )
        return MappingProxyType(
            {
                "score": flagged_loc / total_loc if total_loc else 0.0,
                "files_scanned": len(lines.total_loc_by_file),
                "total_loc": total_loc,
                "flagged_loc": flagged_loc,
                "clone_loc": clone_loc,
                "ast_grep_flagged_loc": ast_loc,
                "structural_rule_loc": structural_loc,
                "structural_rule_findings": len(structural_findings),
            }
        )
