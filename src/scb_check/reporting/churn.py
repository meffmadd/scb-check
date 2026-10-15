"""Aggregate SLOC churn and render a tree comparison summary."""

from __future__ import annotations

import math

from scb_check.models import TreeDiff

type _DiffPayload = dict[str, str | int | float]


def compute_diff_report(tree_diff: TreeDiff) -> _DiffPayload:
    """Compute churn-share entropy normalized over the full eligible union."""
    added = sum(len(file.added_sloc_lines) for file in tree_diff.files)
    deleted = sum(len(file.deleted_sloc_lines) for file in tree_diff.files)
    total = added + deleted
    union_count = len(tree_diff.files)
    positive_churn = tuple(
        churn
        for file in tree_diff.files
        if (churn := len(file.added_sloc_lines) + len(file.deleted_sloc_lines)) > 0
    )
    normalized_entropy = 0.0
    if total > 0 and union_count > 1:
        entropy = sum(
            -(churn / total) * math.log2(churn / total) for churn in positive_churn
        )
        normalized_entropy = entropy / math.log2(union_count)
    return {
        "tree_a": str(tree_diff.tree_a),
        "tree_b": str(tree_diff.tree_b),
        "eligible_file_union_count": union_count,
        "churn_added_sloc": added,
        "churn_deleted_sloc": deleted,
        "churn_total": total,
        "churn_touched_files": len(positive_churn),
        "churn_normalized_entropy": normalized_entropy,
    }


def render_diff_report(report: _DiffPayload) -> str:
    """Render a minimal human summary with stable field labels."""
    return "\n".join(f"{name}: {value}" for name, value in report.items())
