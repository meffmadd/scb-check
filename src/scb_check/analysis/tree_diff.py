"""Compare already-parsed file versions by matching only their SLOC lines."""

from __future__ import annotations

from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path

from scb_check.models import FileDiff
from scb_check.models import FileDiffStatus
from scb_check.tree_walking.dispatch import ParsedFile

type _SlocLines = tuple[tuple[int, str], ...]


def compare_file(
    path: Path, before: ParsedFile | None, after: ParsedFile | None,
) -> FileDiff:
    """Compare a relative `path`'s parsed versions; `None` means absent.

    At least one version exists; callers exclude read/parse failures beforehand.
    Only parser SLOC text participates in matching. Changes retain original
    1-indexed positions; unchanged and zero-SLOC files still produce records.
    """
    added, deleted = _changed_sloc_lines(_sloc_lines(before), _sloc_lines(after))

    status: FileDiffStatus = "unchanged"
    if before is None:
        status = "added"
    elif after is None:
        status = "deleted"
    elif added or deleted:
        status = "modified"

    return FileDiff(
        path=path,
        status=status,
        added_sloc_lines=added,
        deleted_sloc_lines=deleted,
    )


def _sloc_lines(parsed: ParsedFile | None) -> _SlocLines:
    if parsed is None:
        return ()
    return tuple(
        (line_number, text.removesuffix("\n"))
        for line_number, text in enumerate(StringIO(parsed.source), start=1)
        if line_number in parsed.module.sloc_lines
    )


def _changed_sloc_lines(
    lines_a: _SlocLines, lines_b: _SlocLines,
) -> tuple[frozenset[int], frozenset[int]]:
    added: set[int] = set()
    deleted: set[int] = set()
    # Original positions are for reporting only, never match anchors.
    matcher = SequenceMatcher(
        a=tuple(text for _, text in lines_a),
        b=tuple(text for _, text in lines_b),
        autojunk=False,
    )
    for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            deleted.update(line_number for line_number, _ in lines_a[start_a:end_a])
        if tag in {"replace", "insert"}:
            added.update(line_number for line_number, _ in lines_b[start_b:end_b])
    return frozenset(added), frozenset(deleted)
