# `reporting/` — findings → output

Consumes shared `AnalysisResult` for metric reports and `Flags` for location-level human output. [`score.py`](score.py) explicitly composes metric classes and serializes reports; [`comparison.py`](comparison.py) composes and renders before/after/diff reports. See the [ownership and interface guide](../../../docs/architecture.md#report-comparison-interface) when changing contracts and the [README schema](../../../README.md#check-json-report-fields) for canonical fields.

## Ownership

- `Verbosity`, `Erosion`, `CognitiveErosion`, and `Syntax` live in the sibling [`metrics/`](../metrics/AGENTS.md) package. Their `Metric` base declares the calculation contract; concrete classes own their narrow inputs, calculations, result fields, and units.
- `compute_report(AnalysisResult)` owns explicit group composition. `Report` is a mapping alias, with read-only outer and inner mappings, not a runtime class. Keep units outside nullable numerical values.
- Keep calculations and shared erosion arithmetic in `metrics/`. Complexity extraction stays in tree walking.
- `serialize_report` validates contracts and creates fresh plain outer and inner dictionaries. Keep required-field and finite-value validation at the reporting boundary; reject booleans and nonnumeric/nested results.
- Extend explicit composition for real metrics; keep the interface free of registries, dynamic discovery, and unused configuration.

## Scoring invariants

- **Verbosity** is the **union** of clone SLOC lines, ast-grep SLOC lines, and structural rule SLOC lines per file, divided by total SLOC. See [`metrics/verbosity.py`](../metrics/verbosity.py). It is not a sum — lines flagged by multiple sources count once.
- **Erosion** denominator is the cyclomatic mass of **all** function-like symbols; numerator is the mass of symbols with `cyc_complexity > 10`. Symbols with `sloc <= 0` contribute mass 0.
- **Cognitive erosion** uses the same calculation with `cog_complexity > 10` and cognitive mass.
- **Mass** = `complexity * sqrt(sloc)`.
- **`total_loc == 0`** zeroes verbosity and all flagged-LOC counts; **zero total mass** zeroes the corresponding erosion score. Guard both.
- **Report comparison is pure.** `compare_reports(before, after) -> Report` returns read-only signed later-minus-earlier differences. Missing required groups/fields are errors. Only absent dotted per-language syntax fields zero-fill over the sorted language union; explicit `None` on either side propagates, including two null operands. Preserve snapshots.
- **Diff composition accepts analyses.** `compute_diff_report(earlier_analysis, later_analysis)` returns an ordinary dictionary with exactly `before`, `after`, and `diff`, using the standalone `compute_report` for both snapshots. Tree paths are command-owned context; there is no `delta` alias or runtime grouping class.
- **Units stay metric-owned.** Render from class-declared units, including dynamic syntax fields, rather than recognizing score names. JSON score differences are fractional absolute differences. Human scores are percentages and score differences are percentage points; counts and masses retain their units. Include zero differences, display unavailable values explicitly, and keep quality-gate judgments out.

## Rendering

[`render.render_flags`](render.py) emits flags ordered by `(display_path, line, kind_rank)` where `kind_rank` is clone=0, ast-grep=1, structural rule=2, erosion=3, cog_erosion=4. Tests assert on textual markers (e.g. `"duplicate-structure:"`, `"warning[...]"`, `"trivial-wrapper[warning]"`, `"erosion: function ..."`, `"cog_erosion: function ..."`), not the exact layout — preserve those prefixes.

Clones are grouped by `group_hash` so each duplicate group renders once, listing every instance inline under a shared `duplicate-structure:` header (separated by `┆`). Clone line counts and body snippets use duplicated SLOC lines, so docstrings, comments, and blanks inside the clone span are not counted or displayed. Don't reintroduce the "other instances:" cross-reference footer — the inline instances replace it. The group is anchored (for ordering) at the earliest `(display_path, start_line)` instance.
