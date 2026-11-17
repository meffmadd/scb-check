# scb-check

Implements various code-quality metrics to explore how code changes over time.

Measure source snapshots, compare their results, and plot changes across checkpoints. The metrics cover duplication, complexity, syntax size, and coupling. They support investigating code evolution, including during agentic development; an increasing measurement does not automatically mean declining quality.

Supports Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++. Coverage varies by metric; semantic coupling measurements are currently Python-first and partial.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

Install from this fork's checkout:

```bash
git clone https://github.com/meffmadd/scb-check.git
cd scb-check
uv sync
```

## Usage

Run these commands from the checkout.

Measure a snapshot:

```bash
uv run scb-check check PATH --output-format json
```

Compare an earlier and a later snapshot:

```bash
uv run scb-check diff BEFORE AFTER
```

Plot a sequence of source directories as an offline HTML report:

```bash
uv run scb-check report STEP_1 STEP_2 STEP_3 --output changes.html
```

Differences are later minus earlier. `check` exits `1` when it reports findings; `diff` and `report` exit `0` on success regardless of findings.

## Documentation

- [Compare code across checkpoints](docs/comparing-snapshots.md)
- [CLI reference](docs/cli.md), [JSON report fields](docs/report-fields.md), and [configuration](docs/configuration.md)
- [Measurements and limitations](docs/metrics.md)
- [Development](docs/development.md) and [documentation index](docs/index.md)

## Acknowledgements

This fork builds on [scb-check](https://github.com/gabeorlanski/scb-check) and the work of [SlopCodeBench](https://github.com/SprocketLab/slop-code-bench).
