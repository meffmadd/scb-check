# Your first snapshot comparison

We'll measure two supplied Python snapshots, compare them, and generate an offline HTML report. By the end, you'll have seen a measurement change while the erosion score stays the same.

## Start from the checkout

Complete the [README installation](../README.md#install), then run the commands below from the repository root in the same shell.

Our snapshots are in [`examples/snapshots/`](examples/snapshots/):

- [`before/prices.py`](examples/snapshots/before/prices.py) totals a tuple of prices.
- [`after/prices.py`](examples/snapshots/after/prices.py) adds a loop and rejects negative prices.

Create a temporary directory for the results:

```bash
output=$(mktemp -d)
```

We'll use `--disable-sg` throughout so the lesson doesn't need an ast-grep subprocess.

## Measure each snapshot

Save the first snapshot's measurements:

```bash
uv run scb-check check docs/examples/snapshots/before --disable-sg --output-format json > "$output/before.json"
uv run python -m json.tool "$output/before.json"
```

Find `verbosity.total_loc`: it is `2`. Under `erosion`, `total_functions` is `1`, `high_cc_functions` is `0`, and `score` is `0.0`.

Now measure the second snapshot:

```bash
uv run scb-check check docs/examples/snapshots/after --disable-sg --output-format json > "$output/after.json"
uv run python -m json.tool "$output/after.json"
```

`verbosity.total_loc` is now `7`. There is still one function and the erosion score is still `0.0`.

## Compare the snapshots

Generate their signed differences:

```bash
uv run scb-check diff docs/examples/snapshots/before docs/examples/snapshots/after --disable-sg --output-format json > "$output/comparison.json"
uv run python -m json.tool "$output/comparison.json"
```

Look in the `diff` object:

| Field | Expected difference |
| --- | --- |
| `verbosity.total_loc` | `5` |
| `erosion.total_functions` | `0` |
| `erosion.score` | `0.0` |

The `before` and `after` objects contain the measurements you just inspected. `erosion.total_mass` increases even though `erosion.score` does not.

## Plot the same comparison

Create an HTML report:

```bash
uv run scb-check report docs/examples/snapshots/before docs/examples/snapshots/after --disable-sg --output "$output/changes.html"
printf 'Open this file in your browser: %s/changes.html\n' "$output"
```

Open the printed file path in a browser with JavaScript enabled. Expand `verbosity` and find `total_loc`: its values are `2` and `7`, with a change of `5` at the second snapshot. Expand `erosion` and find `score`: both values and the second snapshot's change are zero. The first snapshot has no preceding change.

You've measured two source trees, inspected their differences, and plotted the same results. To use your own checkpoints, continue with [Compare code across checkpoints](comparing-snapshots.md). For what these changes do—and don't—say about quality, see [Interpreting trajectories](metrics.md#interpreting-trajectories).
