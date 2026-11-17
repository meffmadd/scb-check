# Documentation

`scb-check` measures source snapshots and compares their results. Start with the [README](../README.md) for installation and a few commands.

## Tutorial

- [Your first snapshot comparison](first-comparison.md): measure two supplied examples, inspect their differences, and generate a report.

## Guides

- [Compare code across checkpoints](comparing-snapshots.md): measure snapshots, compare a pair, and plot one or more sequences.

## Reference

- [CLI](cli.md): commands, source discovery, report manifests, defaults, and exit codes.
- [JSON reports](report-fields.md): metric groups, fields, units, aggregation, and signed differences.
- [Configuration and source directives](configuration.md): settings discovery, exclusions, rule budgets, and suppressions.
- [Metric index](metrics.md): links to implementation docstrings for definitions, counting policies, and sources.

## Understanding the measurements

- [Interpreting trajectories](metrics.md#interpreting-trajectories): measurement changes, coverage, and interpretation limits.

## Maintainer guides

- [Architecture](architecture.md): pipeline shape, module boundaries, vocabulary, and scoring-sensitive invariants.
- [Add or extend a metric](adding-a-metric.md): tests, extracted facts, calculations, report composition, and documentation.
- [Tree walking](tree-walking.md): how source becomes IR, directives, semantic context, and rule inputs.
- [Development](development.md): current implementation status, dependency maintenance, and common change approaches.
