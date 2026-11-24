# JSON report reference

## Check JSON report fields

`scb-check check PATH --output-format json` returns a report object with fourteen metric groups. Each group is a flat object of numerical values or `null`, with no `data` wrapper or flat compatibility aliases.

| Metric group | Result fields | Headline fields |
| --- | --- | --- |
| `verbosity` | `score`, `files_scanned`, `total_loc`, `flagged_loc`, `clone_loc`, `ast_grep_flagged_loc`, `structural_rule_loc`, `structural_rule_findings` | `score` |
| `erosion` | `score`, `total_functions`, `high_cc_functions`, `total_mass`, `high_cc_mass` | `score` |
| `cog_erosion` | `score`, `total_functions`, `high_cog_functions`, `total_cog_mass`, `high_cog_mass` | `score` |
| `syntax` | `tree_count`, `node_count`, plus `<language>.tree_count` and `<language>.node_count` | (none) |
| `cbo` | `measured_classes`, `unavailable_classes`, `sum`, `mean`, `max` | `mean`, `max` |
| `rfc` | `measured_classes`, `unavailable_classes`, `sum`, `mean`, `max` | `mean`, `max` |
| `mpc` | `measured_classes`, `unavailable_classes`, `sum`, `mean`, `max` | `mean`, `max` |
| `callers` | `measured_callables`, `unavailable_callables`, `sum`, `mean`, `max`, `same_module_sum`, `cross_module_sum` | `mean`, `max` |
| `dac` | `measured_classes`, `unavailable_classes`, `sum`, `mean`, `max` | `mean`, `max` |
| `cic` | `measured_classes`, `unavailable_classes`, `sum`, `mean`, `max` | `mean`, `max` |
| `ric` | `measured_pairs`, `unavailable_pairs`, `mean`, `max` | `mean`, `max` |
| `ca` | `measured_categories`, `unavailable_categories`, `sum`, `mean`, `max` | `mean`, `max` |
| `ce` | `measured_categories`, `unavailable_categories`, `sum`, `mean`, `max` | `mean`, `max` |
| `module_call_dependencies` | `measured_modules`, `unavailable_modules`, `incoming_sum`, `incoming_mean`, `incoming_max`, `outgoing_sum`, `outgoing_mean`, `outgoing_max` | `incoming_mean`, `incoming_max`, `outgoing_mean`, `outgoing_max` |

Syntax counts cover parsed Tree-sitter trees and their nodes. Dotted per-language names such as `python.node_count` are single flat keys, not nested objects. Only languages present in that snapshot appear. Group, field, and language ordering is deterministic.

Each metric class declares its headline fields in the order shown; every other field is a supporting measurement. Headlines only select what [HTML reports](cli.md#plot-reports) plot by default. Check and diff JSON always contain every field. See [interpreting headlines](metrics.md#interpreting-headlines) for what headlines do and do not mean.

Scores use fractional units. Counts and complexity masses retain their numerical units. Values are finite numbers or `null`; `null` means unavailable or undefined, not zero. Existing zero-denominator scores remain zero, including zero-SLOC verbosity and zero-mass erosion. Human check output remains location-level findings with source context.

### Coupling summaries

Population fields count measured and unavailable entities separately. Summary fields include measured zero values and exclude unavailable entities. With no measured population, every summary is `null`.

Except for RIC, `sum` adds per-entity counts, `mean` divides that sum by the measured population, and `max` selects the largest per-entity count. Directional module fields apply this separately to incoming and outgoing counts, as `incoming_*` and `outgoing_*`.

These summaries are partial even though their keys carry no `partial` prefix: they count supported static evidence and may omit unknown relationships, so an observed zero does not establish absence.

| Group | Population unit | Per-entity summary unit | Aggregation details |
| --- | --- | --- | --- |
| `cbo` | Classes | Partners per class | Sum counts class–partner incidences; each undirected pair contributes twice. |
| `rfc` | Classes | Methods | Sum counts class–response incidences. |
| `mpc` | Classes | Call sites | Sum adds per-class call-site counts. |
| `callers` | Functions/methods (`functions`) | Callers | Sum counts caller–destination pairs, not globally distinct callers. Same-/cross-module sums partition the total. |
| `dac` | Classes | Attributes | Sum adds per-class attribute counts. |
| `cic` | Classes | Occurrences | Sum adds per-class physical ancestor-member occurrence counts. |
| `ric` | Method/comparison-class pairs (`pairs`) | Dimensionless `ratio` | Mean/max summarize measured pair ratios, including zero-use pairs. No ratio sum or pooled ratio; ratios are not percentages. |
| `ca` | Class-bearing module categories | Client classes | Sum counts category–client incidences. |
| `ce` | Class-bearing module categories | Source classes | Sum counts category–source incidences. |
| `module_call_dependencies` | Modules | Neighbors per module | Sums count directional module–neighbor incidences. Measured directional sums can differ when known target modules are unavailable. |

Project aggregates are analyzer conventions. Structured per-entity diagnostics are separate from numerical JSON reports. RIC check/diff aggregates count zero-use pairs arithmetically without building the full diagnostic Cartesian product.

For per-entity counting, availability, and provenance, follow the implementation links in the [metric index](metrics.md). See [partial metric interpretation](metrics.md#partial-metric-interpretation) for the meaning of partial zero and unavailable results.

## Diff JSON fields

`scb-check diff TREE_A TREE_B --output-format json` returns:

- `tree_a`, `tree_b`: resolved directory paths, separate from measurements.
- `before`, `after`: each preserves the complete [check JSON report structure](#check-json-report-fields).
- `diff`: the same metric groups and fields with signed differences, including zeros, without per-field delta suffixes. Dotted syntax fields cover the sorted language union; only absent per-language counts contribute zero for subtraction. The snapshots remain unchanged and equal standalone check JSON with identical settings.

If either operand is `null`, its difference is `null`, including two null operands. Missing required groups or fields are report-contract errors, not zeros. The comparison key is `diff`; there is no `delta` alias.

Scores and score deltas use fractional units in JSON. A score changing from `0.20` to `0.15` has delta `-0.05`. Human output displays scores as percentages and their differences as percentage points (`-5.00 percentage points`), not relative percentage changes. Counts and masses retain their existing units. Human output labels unavailable values explicitly rather than displaying them as zero.

See the [CLI reference](cli.md) for input handling and exit codes, and [metric interpretation](metrics.md) for what changes do and do not mean.
