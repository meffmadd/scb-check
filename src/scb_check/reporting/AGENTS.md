# `reporting/` — findings → output

Takes `Flags` (sorted findings) for JSON [`Report`](../models.py) or human-readable flag text. [`comparison.py`](comparison.py) compares already-computed reports and renders before/after/delta summaries. Consumed by the check and diff command boundaries.

## Scoring invariants

- **Verbosity** is the **union** of clone SLOC lines, ast-grep SLOC lines, and structural rule SLOC lines per file, divided by total SLOC. See `_count_union_lines` in [`score.py`](score.py). It is not a sum — lines flagged by multiple sources count once.
- **Erosion** denominator is the cyclomatic mass of **all** function-like symbols; numerator is the mass of symbols with `cyc_complexity > 10`. Symbols with `sloc <= 0` contribute mass 0.
- **Cognitive erosion** uses the same calculation with `cog_complexity > 10` and cognitive mass.
- **Mass** = `complexity * sqrt(sloc)`.
- **`total_loc == 0`** zeroes verbosity and all flagged-LOC counts; **zero total mass** zeroes the corresponding erosion score. Guard both.
- **Report comparison is pure.** `compare_reports(before, after)` accepts `Report` values and returns a check-shaped dictionary of signed later-minus-earlier deltas. Scalar numeric fields from `Report.to_dict()` compare automatically; nested or nonnumeric additions need explicit handling. See the [report-comparison interface](../../../docs/architecture.md#report-comparison-interface).
- **Diff JSON preserves check structure.** `before`, `after`, and `delta` use the check metric fields; tree paths are command-owned context. Language deltas use the sorted union, zero-filling missing counts only for subtraction.
- **Units stay consistent.** JSON score deltas are fractional absolute differences. Human percentage differences are percentage points; counts and masses retain their units. Include zero deltas without quality-gate judgments.

## Rendering

[`render.render_flags`](render.py) emits flags ordered by `(display_path, line, kind_rank)` where `kind_rank` is clone=0, ast-grep=1, structural rule=2, erosion=3, cog_erosion=4. Tests assert on textual markers (e.g. `"duplicate-structure:"`, `"warning[...]"`, `"trivial-wrapper[warning]"`, `"erosion: function ..."`, `"cog_erosion: function ..."`), not the exact layout — preserve those prefixes.

Clones are grouped by `group_hash` so each duplicate group renders once, listing every instance inline under a shared `duplicate-structure:` header (separated by `┆`). Clone line counts and body snippets use duplicated SLOC lines, so docstrings, comments, and blanks inside the clone span are not counted or displayed. Don't reintroduce the "other instances:" cross-reference footer — the inline instances replace it. The group is anchored (for ordering) at the earliest `(display_path, start_line)` instance.
