# Add or extend a metric

Use this guide when introducing a measurement or changing an existing metric's fields or counting policy. Start from a working [development checkout](development.md#setup).

## 1. Define the measurement and write behavioral tests

Choose the measured population, evidence, units, aggregation, and unavailable-result policy. For an existing metric, read its implementation docstrings via the [metric index](metrics.md). Keep the distinction between [partial and unavailable](metrics.md#partial-metric-interpretation) explicit.

Add known-value source cases through the Typer CLI before implementing the change. Assert observable measurements, supporting population counts, and exits rather than rendering strings or internal call order. Stub `scb_check.pipeline.run_sg` where controlled ast-grep output is needed.

Cover at least:

- nonzero measurements, measured zero, unavailable extraction, and empty measured populations;
- independent snapshot analyses, including positive, negative, zero, and null differences;
- unit formatting and standalone-check parity in `tests/test_diff_cli.py`;
- any changed population, dispatch, type eligibility, or ownership rule.

For existing coupling metrics, retain their specific cases:

| Metric | Cases to preserve |
| --- | --- |
| RFC₁ | One-hop union, inherited selections, and bodyless methods |
| MPC | Repeated/loop sites and implementation ownership |
| Callers | Recursion, initialization exclusion, and same-/cross-module partition reconciliation |
| DAC | Repeated field types, wrappers, and unknown annotations |
| Ca/Ce | Per-category client deduplication, Ce saturation per source class, shared membership/dependencies, partial zeros, and unavailable internal extraction |
| Module-call dependencies | Repeated/cyclic/self edges, physical-file mapping, supported initialization, and unavailable targets |
| CIC | Proper ancestors, repeated sites, call/target-access deduplication, static overrides, inherited-body ownership, and unresolved ancestry |
| RIC | All-pair zeros, raw zero-owner use versus the denominator floor, repeated callers, canonical ownership, and unavailable endpoints |

For RIC aggregate changes, compare against full diagnostics and preserve the zero-call allocation/work regression without timing thresholds.

## 2. Reuse extracted facts

Choose the narrow immutable inputs the calculation needs. Use retained member selections, source occurrences, and declared types rather than adding a metric-specific resolver.

Keep source IO, parser traversal, and complexity extraction outside `metrics/`. If the required facts do not exist, extend the producer first using the [retained-fact workflow](development.md#extending-retained-entity-facts) and document extraction support in the [tree-walking contract](tree-walking.md#fact-availability-and-parser-support).

## 3. Implement the metric and its docstrings

Put a small class in its own `src/scb_check/metrics/` module, subclassing [`Metric`](../src/scb_check/metrics/base.py) with its `compute()` input types. For example, [`Syntax`](../src/scb_check/metrics/syntax.py) uses `Metric[[tuple[LanguageSyntaxSummary, ...]]]`.

Implement instance `compute()` and declare class-level `units`. Return a read-only flat `MetricResult` of `int | float | None`; keep structured diagnostics and metadata separate. Own field names, population selection, and units in the metric, including dynamic fields. Return defined-but-unavailable values as `None`, preserve defined zero-denominator behavior, and let calculation errors surface.

Reuse private `metrics/_mass.py` arithmetic for erosion variants and `metrics/_counts.py`'s `summarize_counts` for measured-count aggregates. Keep constructors for real configuration needs; use explicit composition rather than a registry or automatic dispatcher.

Document the definition, provenance, counting variant, population, dispatch/type limits, and availability in the implementation docstrings. Those docstrings are canonical; the [metric index](metrics.md) links to them instead of duplicating their policies.

## 4. Compose and validate the report

Explicitly compose the metric in [`reporting.score.compute_report`](../src/scb_check/reporting/score.py) and associate its group with metric-owned units. Keep both mapping levels read-only. Use `serialize_report` for contract validation and fresh plain dictionaries; metadata stays outside numerical results.

Update required-field/group validation and comparison coverage for the schema. Keep fields flat and numerical; preserve explicit nulls through independent-snapshot subtraction. Metric code stays independent of reporting and source IO. See the [report-comparison interface](architecture.md#report-comparison-interface) for ownership.

## 5. Update documentation

Update the [JSON reference](report-fields.md) for fields, units, and aggregation. Add or adjust the implementation link in the [metric index](metrics.md). Update CLI/configuration reference only if those interfaces change.

Keep formulas, counting policies, and citations in implementation docstrings. Describe measurements without introducing unsupported quality judgments or thresholds.

## 6. Verify the result

Run the [development verification workflow](development.md#verification). The change is complete when known-value tests pass, check/diff/report retain their contracts, and documentation points to the updated implementation and report fields.
