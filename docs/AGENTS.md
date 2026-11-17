# `docs/`

This folder contains user guides, reference material, and maintainer guides.

## Responsibilities

- `index.md` is the docs landing page.
- `first-comparison.md` is a tutorial using the supplied source trees in `examples/snapshots/`; verify its commands and expected measurements when examples or analysis behavior change.
- `comparing-snapshots.md` is the task guide for measuring, comparing, and plotting checkpoints.
- `cli.md`, `report-fields.md`, and `configuration.md` are canonical for CLI behavior, numerical report fields, and settings/directives respectively.
- `metrics.md` indexes implementation modules and explains interpretation. Metric docstrings are canonical for definitions, counting policies, limitations, and sources; link to them rather than duplicating their contracts here.
- `architecture.md` is canonical for pipeline shape, module boundaries, vocabulary, and scoring-sensitive invariants.
- `adding-a-metric.md` owns the contributor workflow for measurements and report composition.
- `tree-walking.md` is the canonical source for how source text becomes IR, directives, semantic context, and structural-rule inputs.
- `development.md` is the canonical source for current implementation status and common change approaches.

## Rules

- Keep guides concise and current; document what the code does now.
- Keep `README.md` focused on project purpose, checkout installation, a few commands, documentation links, and upstream acknowledgements. Put detailed usage and contracts in the relevant guide or reference here.
- Separate task instructions, factual reference, and interpretation. Link to canonical details instead of duplicating them; add pages only for concrete content.
- Wrap code identifiers, CLI options, rule IDs, and paths in backticks.
- Update these guides whenever behavior, scoring, public commands, or extension points change.
