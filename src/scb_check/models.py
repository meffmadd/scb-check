"""Shared immutable models for analysis and reporting."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import RuleFinding
from scb_check.tree_walking.models import SymbolIR

type AstGrepSeverity = Literal["info", "warning", "critical"]
type ReportValue = int | float | None
type MetricResult = Mapping[str, ReportValue]
type Report = Mapping[str, MetricResult]
type SourceLines = Mapping[Path, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class CloneBlock:
    """A duplicated syntax block found in one file."""

    file: Path
    start_line: int
    end_line: int
    group_hash: str
    instance_count: int
    other_instances: tuple[tuple[Path, int], ...]
    first_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AstGrepHit:
    """An ast-grep rule match with source location and message."""

    file: Path
    line: int
    end_line: int
    col: int
    end_col: int
    rule_id: str
    matched_text: str
    message: str = ""
    severity: AstGrepSeverity = "warning"


@dataclass(frozen=True, slots=True)
class FileLineSet:
    """A file path paired with immutable 1-indexed line numbers."""

    file: Path
    lines: frozenset[int]

    @classmethod
    def from_parts(cls, file: Path, lines: Iterable[int]) -> FileLineSet:
        """Build a `FileLineSet` from line numbers."""
        return cls(file=file, lines=frozenset(lines))


@dataclass(frozen=True, slots=True)
class FindingGroups:
    """Analysis findings grouped by source."""

    clones: tuple[CloneBlock, ...] = ()
    ast_grep_hits: tuple[AstGrepHit, ...] = ()
    structural_findings: tuple[RuleFinding, ...] = ()
    high_cc_functions: tuple[SymbolIR, ...] = ()
    high_cog_functions: tuple[SymbolIR, ...] = ()
    all_functions: tuple[SymbolIR, ...] = ()


@dataclass(frozen=True, slots=True)
class LineGroups:
    """SLOC line sets used for scoring."""

    total_loc_by_file: tuple[tuple[Path, int], ...] = ()
    clone_sloc_lines_by_file: tuple[FileLineSet, ...] = ()
    ast_sloc_lines_by_file: tuple[FileLineSet, ...] = ()
    structural_sloc_lines_by_file: tuple[FileLineSet, ...] = ()


@dataclass(frozen=True, slots=True)
class LanguageSyntaxSummary:
    """Syntax tree and node counts for one source language."""

    language: Language
    tree_count: int
    node_count: int


@dataclass(frozen=True, slots=True)
class Flags:
    """Sorted analysis findings and line sets used for reporting."""

    findings: FindingGroups = field(default_factory=FindingGroups)
    lines: LineGroups = field(default_factory=LineGroups)
    syntax_by_language: tuple[LanguageSyntaxSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Extracted analysis facts and source lines for reporting."""

    flags: Flags
    source_lines_by_file: SourceLines
    project: ProjectIR = field(default_factory=ProjectIR)

    def __post_init__(self) -> None:
        """Expose privately owned, read-only source context."""
        object.__setattr__(
            self,
            "source_lines_by_file",
            MappingProxyType(dict(self.source_lines_by_file)),
        )
