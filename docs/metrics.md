# Metrics

The metric implementations and their docstrings are the source of truth for formulas, counting policies, populations, limitations, and metric-specific citations. The table links directly to those modules; the [JSON reference](report-fields.md) defines report fields, units, and project-level aggregation.

| Measurement | Implementation and docstrings |
| --- | --- |
| Verbosity: flagged SLOC share | [`Verbosity`](../src/scb_check/metrics/verbosity.py) |
| Cyclomatic erosion: high-complexity function mass share | [`Erosion`](../src/scb_check/metrics/erosion.py) |
| Cognitive erosion: high-cognitive-complexity function mass share | [`CognitiveErosion`](../src/scb_check/metrics/cog_erosion.py) |
| Syntax: tree and node counts | [`Syntax`](../src/scb_check/metrics/syntax.py) |
| Coupling Between Objects | [`CBO`](../src/scb_check/metrics/cbo.py) |
| Direct Response For a Class | [`RFC`](../src/scb_check/metrics/rfc.py) |
| Message Passing Coupling | [`MPC`](../src/scb_check/metrics/mpc.py) |
| Distinct callers | [`DistinctCallers`](../src/scb_check/metrics/callers.py) |
| Data Abstraction Coupling | [`DAC`](../src/scb_check/metrics/dac.py) |
| Class Inheritance-related Coupling | [`CIC`](../src/scb_check/metrics/cic.py) |
| Method-level Relative Inward Coupling | [`RIC`](../src/scb_check/metrics/ric.py) |
| Afferent category coupling | [`AfferentCoupling`](../src/scb_check/metrics/ca.py) |
| Efferent category coupling | [`EfferentCoupling`](../src/scb_check/metrics/ce.py) |
| Module-call dependencies | [`ModuleCallDependencies`](../src/scb_check/metrics/module_dependencies.py) |

Ca and Ce use the [shared category/dependency policy](../src/scb_check/metrics/categories.py). The erosion variants share [mass arithmetic](../src/scb_check/metrics/_mass.py); function classification and thresholds are applied in the [analysis pipeline](../src/scb_check/pipeline.py).

## Interpreting trajectories

An increase means a larger measurement, not necessarily worse code. Raw counts may grow because the implementation grows. Means, maxima, and scores can change when the measured population changes. These measurements support investigating trajectories without assuming that every metric should move in one direction.

Snapshot differences are not code churn. Literal edits or renames that preserve reports produce zero differences; zero aggregate differences can also hide offsetting local changes. Differences use later minus earlier in the measurement's existing units, with score changes displayed as percentage points rather than relative percentages. See [diff fields](report-fields.md#diff-json-fields).

SlopCodeBench runs provide an experimental setting with ordered source checkpoints. Those checkpoints approximate an evolving development process; benchmark observations do not by themselves establish what happens in other projects.

## Interpreting headlines

HTML reports plot each metric's [headline fields](report-fields.md#check-json-report-fields) by default: the verbosity and erosion scores, and the existing per-entity means and maxima of the structural measurements. They are selected measurements, not new arithmetic, a universal slop score, or a guarantee of growth neutrality.

- Scores are already shares of flagged SLOC or complexity mass.
- Means weight every measured entity equally. Maxima expose an extreme entity, but can rise simply because a measured population grows.
- Ca and Ce summarize module categories, so adding classes inside existing categories can change their means.
- RIC includes zero-use method/class pairs, so adding unrelated classes can dilute its mean without improving existing relationships.
- Incoming and outgoing module dependencies stay separate headlines, so neither direction hides the other.

Syntax counts are size measurements and have no headlines. Use `scb-check report --full` to plot supporting populations, totals, sums, and syntax counts alongside the headlines.

## Partial metric interpretation

The coupling measurements describe retained project source, not verified whole-program behavior. Their Python-first resolution can miss unresolved uses, unknown types, and unscanned libraries. A measured partial zero is not proof of absence. Concise keys such as `cbo.mean` carry no `partial` prefix, but every coupling summary remains partial.

Unavailable entities lack required extraction support and are excluded from summary denominators rather than treated as zero. Measured and unavailable populations remain separate; summaries are `null` when no population is measured. Each snapshot models its own population, so differences may reflect coverage changes as well as changed relationships.

Project-level aggregates are analyzer conventions, not claims that the metric papers define system-wide quality scores. Coupling measurements add no quality thresholds, findings, or exit-code changes. RIC is not a method-move recommendation, and module-call dependencies are not Ca/Ce. Consult each implementation's docstrings for its specific evidence and availability policy.
