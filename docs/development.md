# Development

This guide summarizes the current implementation status and the preferred approach for common changes.

## Current status

`scb-check` is a Python CLI with three public commands:

- `scb-check check PATH` reports human-readable flags or JSON scores.
- `scb-check rule RULE_ID` prints bundled `ast-grep` YAML or structural rule metadata.
- `scb-check diff TREE_A TREE_B` reports before/after/signed metric deltas between directories.

Implemented analysis paths:

- Source discovery for supported Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++ suffixes.
- Tree-sitter parsing into language-agnostic IR.
- Parser `SLOC` accounting shared by verbosity, clone line counts, and rule spans.
- One full `pipeline.analyze()` workflow using the shared source reader and source indexes for both commands.
- Data-only grouped reports, metric-owned calculations and units, and pure nullable snapshot comparison including dotted per-language syntax counts.
- Duplicate-structure detection by normalized AST hashing for all supported languages.
- Bundled Python `ast-grep` slop patterns, plus optional local rules from `SCB_CHECK_EXTRA_SLOP_RULES`.
- Structural rules over `ProjectIR`; the current bundled Python rules are `trivial-wrapper` and opt-in `low-use-short-function`.
- Cyclomatic and cognitive erosion scores for all supported languages.
- Python source ignores for `ast-grep` and structural rule IDs.
- Python boundary suppression for validation/normalization functions.

## Runtime contracts

- `check` exits `0` without findings and `1` with findings; `diff` exits `0` on success regardless of findings or delta signs.
- Exit `2` is for user-facing failures such as bad config, bad paths, unknown rules, invalid directives, or an empty eligible/parseable source set.
- Individual read/parse failures warn and skip within their own analysis. In `diff`, each side must have at least one successfully parsed eligible file; parsed zero-SLOC files remain valid. A failure produces no partial comparison payload.
- Non-Python files skip Python ast-grep rules, structural rules, and source directives until language-specific rules exist.
- Config discovery and source-directive behavior are user-facing; keep README examples synchronized when they change.

## Where to make changes

| Change | Primary location |
| --- | --- |
| CLI command or option | `src/scb_check/commands/` |
| Config loading or path walking | `src/scb_check/config.py`, `src/scb_check/walker.py` |
| Source parsing, `SLOC`, directives, IR | `src/scb_check/tree_walking/`; see [Tree walking](tree-walking.md) |
| Language parser configs | `src/scb_check/tree_walking/languages/` |
| Clone detection | `src/scb_check/analysis/clones.py` |
| Shared source IO and parse warnings | `src/scb_check/analysis/source.py` |
| Full snapshot analysis and source indexing | `src/scb_check/pipeline.py` |
| Snapshot composition and serialization | `src/scb_check/reporting/score.py` |
| Metric contract | `src/scb_check/metrics/base.py` (`Metric`) |
| Metric calculations, fields, and units | `src/scb_check/metrics/verbosity.py`, `erosion.py`, `cog_erosion.py`, `syntax.py`, `units.py` |
| Shared erosion arithmetic | `src/scb_check/metrics/_mass.py` |
| Report comparison and summary rendering | `src/scb_check/reporting/comparison.py` |
| `ast-grep` integration | `src/scb_check/analysis/astgrep.py` and `src/scb_check/resources/slop_rules/` |
| Structural rule behavior | `src/scb_check/rules/` |
| JSON scores or human rendering | `src/scb_check/reporting/` |
| Shared `AnalysisResult`, finding records, and report mapping aliases | `src/scb_check/models.py` |

## Adding an `ast-grep` rule

1. Add or update YAML under `src/scb_check/resources/slop_rules/`.
2. Use a unique rule ID across both `ast-grep` and structural rules.
3. Set severity and any `min_file_count` metadata deliberately.
4. Add behavioral tests that exercise `pipeline.run_sg` through monkeypatching rather than invoking `sg`.
5. Update README or docs if the rule changes user-facing behavior or scoring expectations.

## Adding a structural rule

1. Add a rule class under `src/scb_check/rules/`.
2. Keep rule metadata immutable: `id`, `severity`, `languages`, `target`, and `description`.
3. Operate on `SymbolIR` or another typed IR subject plus `RuleContext`; do not inspect tree-sitter nodes.
4. Register the rule in `rules/registry.py`.
5. Ensure the rule ID does not collide with bundled `ast-grep` rule IDs.
6. Test observable findings, ignore behavior, report fields, and rendering prefixes.

## Adding a language

1. Add the tree-sitter grammar dependency.
2. Add a `Language` enum value, parser module/config under `tree_walking/languages/`, dispatch suffix mapping, and discovery coverage.
3. Add clone node/literal/identifier config so `analysis/clones.py` can hash duplicate blocks.
4. Add behavioral parser, clone, and pipeline tests.
5. Document whether ast-grep rules, directives, and structural rules apply to the language.

## Changing scoring

Treat scoring changes as public behavior changes. Update tests first, then implementation, then docs.

Pay special attention to:

- `verbosity` as a union, never a sum,
- `SLOC` as the denominator for verbosity and the source of counted flagged lines,
- non-Python verbosity currently includes clone LOC but not Python ast-grep or structural rule LOC,
- high-complexity threshold `> 10`,
- mass formulas for `erosion` and `cog_erosion`,
- line spans used by clone, `ast-grep`, and structural findings.

## Adding or extending a metric

1. Add behavioral acceptance expectations through the Typer CLI for known scores and supporting values. Keep the [README schema reference](../README.md#check-json-report-fields) synchronized.
2. Put a small metric class in its own `metrics/` module, subclassing `metrics.base.Metric` with its `compute()` input types (for example, `Syntax` uses `Metric[[tuple[LanguageSyntaxSummary, ...]]]`). Implement instance `compute()` and declare class-level `units`. Pass only the extracted facts it needs; keep parser traversal and complexity extraction in tree walking. Reuse private `metrics/_mass.py` arithmetic for the erosion variants.
3. Return a read-only flat `MetricResult` of `int | float | None`. Own field names and units in the metric, including dynamic syntax fields. Return defined-but-unavailable fields as `None`; preserve existing zero-denominator results and let calculation errors surface.
4. Explicitly compose the metric in `reporting.score.compute_report(AnalysisResult)` and associate its group with metric-owned units. Keep both mapping levels read-only. Use `serialize_report` for contract validation and fresh plain dictionaries; keep metadata outside numerical results.
5. Update required-field/group validation and comparison coverage for the schema. Use flat numerical fields, not nested result objects. Add no registry, report class, or placeholder configuration; constructors are for real configuration requirements.

Keep `metrics/` independent of reporting and source IO. See the [ownership and interface explanation](architecture.md#report-comparison-interface).

## Extending snapshot comparisons

1. Extend the snapshot metric contract through the steps above.
2. Keep `compare_reports(before, after)` pure and returning a read-only `Report`. Require defined groups and fields; zero-fill only absent dotted per-language syntax fields, without changing snapshots. Propagate explicit `None` rather than treating it as zero.
3. Keep `compute_diff_report(earlier_analysis, later_analysis)` returning an ordinary `before` / `after` / `diff` dictionary. Use the standalone snapshot builder on both analyses. Tree paths belong in command output, not metric results.
4. Add CLI coverage in `tests/test_diff_cli.py`: standalone-check parity plus independently known positive, negative, and zero differences, argument reversal, language additions/removals, exits, and stderr. Cover read-only behavior, fresh serialization, null propagation, and malformed report contracts at the public reporting seam where real-source CLI fixtures cannot produce them.
5. Check observable unit formatting: fractional JSON scores and differences, human percentages and percentage points, count/mass units, explicit unavailable values, and visible zero differences. Retain location-level human check findings.

Commands still run two independent full analyses with one configuration and equal options. Preserve walker exclusions and independent parse-failure handling, without file pairing or source rereading. Monkeypatch `scb_check.pipeline.run_sg` for controlled tooling output. This reporting contract does not implement churn or a quality gate.

## Verification

Run the project workflow after changes:

```bash
uv run ruff check --fix .
uv run ty check .
uv run pytest
uv run scb-check check .
uv run vulture
```

Use focused tests while iterating, then run the full workflow before presenting results. Keep tests behavioral: assert scores, exit codes, report fields, and rendering prefixes instead of internal call order.
