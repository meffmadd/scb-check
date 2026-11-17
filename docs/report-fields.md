# JSON report reference

## Check JSON report fields

`scb-check check PATH --output-format json` returns a report object with fourteen metric groups. Each group is a flat object of numerical values or `null`, with no `data` wrapper or flat compatibility aliases.

| Metric group | Result fields |
| --- | --- |
| `verbosity` | `score`, `files_scanned`, `total_loc`, `flagged_loc`, `clone_loc`, `ast_grep_flagged_loc`, `structural_rule_loc`, `structural_rule_findings` |
| `erosion` | `score`, `total_functions`, `high_cc_functions`, `total_mass`, `high_cc_mass` |
| `cog_erosion` | `score`, `total_functions`, `high_cog_functions`, `total_cog_mass`, `high_cog_mass` |
| `syntax` | `tree_count`, `node_count`, plus `<language>.tree_count` and `<language>.node_count` |
| `cbo` | `measured_classes`, `unavailable_classes`, `partial_partner_sum`, `partial_partner_mean`, `partial_partner_max` |
| `rfc` | `measured_classes`, `unavailable_classes`, `partial_response_sum`, `partial_response_mean`, `partial_response_max` |
| `mpc` | `measured_classes`, `unavailable_classes`, `partial_call_site_sum`, `partial_call_site_mean`, `partial_call_site_max` |
| `callers` | `measured_callables`, `unavailable_callables`, `partial_caller_sum`, `partial_caller_mean`, `partial_caller_max`, `partial_same_module_sum`, `partial_cross_module_sum` |
| `dac` | `measured_classes`, `unavailable_classes`, `partial_attribute_sum`, `partial_attribute_mean`, `partial_attribute_max` |
| `cic` | `measured_classes`, `unavailable_classes`, `partial_occurrence_sum`, `partial_occurrence_mean`, `partial_occurrence_max` |
| `ric` | `measured_pairs`, `unavailable_pairs`, `partial_ratio_mean`, `partial_ratio_max` |
| `ca` | `measured_categories`, `unavailable_categories`, `partial_client_sum`, `partial_client_mean`, `partial_client_max` |
| `ce` | `measured_categories`, `unavailable_categories`, `partial_source_sum`, `partial_source_mean`, `partial_source_max` |
| `module_call_dependencies` | `measured_modules`, `unavailable_modules`, `partial_incoming_sum`, `partial_incoming_mean`, `partial_incoming_max`, `partial_outgoing_sum`, `partial_outgoing_mean`, `partial_outgoing_max` |

Syntax counts cover parsed Tree-sitter trees and their nodes. Dotted per-language names such as `python.node_count` are single flat keys, not nested objects. Only languages present in that snapshot appear. Group, field, and language ordering is deterministic.

Scores use fractional units. Counts and complexity masses retain their numerical units. Values are finite numbers or `null`; `null` means unavailable or undefined, not zero. Existing zero-denominator scores remain zero, including zero-SLOC verbosity and zero-mass erosion. Human check output remains location-level findings with source context.

### Coupling summaries

Population fields count measured and unavailable entities separately. Summary fields include measured zero values and exclude unavailable entities. With no measured population, every summary is `null`.

Except for RIC, `partial_*_sum` adds per-entity counts, `partial_*_mean` divides that sum by the measured population, and `partial_*_max` selects the largest per-entity count. Directional module fields apply this separately to incoming and outgoing counts.

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
