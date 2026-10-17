# `metrics/` — extracted facts → measurements

Metric classes own calculations, flat result-field names, and units. Reporting composes their results into reports and handles serialization, comparison, and presentation.

- Subclass `Metric` from `base.py` and implement instance `compute()`. Its parameter specification preserves each metric's narrow extracted-fact inputs; declare result units on the class.
- Return a read-only flat `MetricResult` (`int | float | None`). Keep metadata separate from result values.
- Keep each conceptual metric in its own module. Share erosion arithmetic privately in `_mass.py`; preserve the union, mass, threshold, and zero-denominator semantics in the [architecture guide](../../../docs/architecture.md#metrics).
- Use extracted facts only: source IO, parser traversal, and analysis orchestration stay outside this package. Keep this package independent of `reporting/`.
- Reporting explicitly composes concrete metrics. The base class is a contract, not a registry or automatic dispatcher.
