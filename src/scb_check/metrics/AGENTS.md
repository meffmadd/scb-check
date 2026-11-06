# `metrics/` — extracted facts → measurements

Metric classes own calculations, flat result-field names, and units. Reporting composes their results into reports and handles serialization, comparison, and presentation.

- Subclass `Metric` from `base.py` and implement instance `compute()`. Its parameter specification preserves each metric's narrow extracted-fact inputs; declare result units on the class.
- Return a read-only flat `MetricResult` (`int | float | None`). Keep metadata separate from result values.
- Keep each conceptual metric in its own module. Share erosion arithmetic privately in `_mass.py`; preserve the union, mass, threshold, and zero-denominator semantics in the [architecture guide](../../../docs/architecture.md#metrics).
- Use extracted facts only: source IO, parser traversal, and analysis orchestration stay outside this package. Keep this package independent of `reporting/`.
- CBO uses retained module facts and owns partner-set construction; all summaries are explicitly partial. When changing its population or resolution fallback, preserve the [CBO contract](../../../docs/architecture.md#coupling-between-objects-cbo) and keep unsupported class diagnostics separate from measured partial zero.
- Reporting explicitly composes concrete metrics. The base class is a contract, not a registry or automatic dispatcher.
