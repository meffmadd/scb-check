# Compare code across checkpoints

Use source directories for the checkpoints you want to compare. The commands accept ordinary directories, including directories outside a Git repository; they do not resolve Git tags or revisions.

Run the examples from a checkout of this repository after `uv sync`. With a standalone installation, omit `uv run`. For a guided example using supplied snapshots, start with [Your first snapshot comparison](first-comparison.md).

## Measure a snapshot

Save a numerical report for one checkpoint:

```bash
uv run scb-check check snapshots/step-1 --output-format json > step-1.json
```

`check` exits `1` when it reports findings, even if it successfully writes the JSON report. See [exit codes](cli.md#exit-codes) when scripting this command.

## Compare two checkpoints

Put the earlier directory first:

```bash
uv run scb-check diff snapshots/step-1 snapshots/step-2
```

For machine-readable results:

```bash
uv run scb-check diff snapshots/step-1 snapshots/step-2 --output-format json > comparison.json
```

The result includes both full reports and signed later-minus-earlier differences. See the [JSON reference](report-fields.md#diff-json-fields) for fields and units.

## Plot a sequence

List source directories in the order you want them plotted:

```bash
uv run scb-check report snapshots/step-1 snapshots/step-2 snapshots/step-3 --output changes.html
```

Open `changes.html` in a browser with JavaScript enabled. The report works offline. Expand a metric group to see values and changes between adjacent checkpoints. Its horizontal axis follows your supplied order, not elapsed time.

## Compare multiple sequences

Create a TOML manifest next to your snapshot directories:

```toml
steps = ["1", "2", "3"]

[series.run-a]
"1" = "run-a/step-1"
"2" = "run-a/step-2"
"3" = "run-a/step-3"

[series.run-b]
"1" = "run-b/step-1"
"3" = "run-b/step-3"
```

Then generate the report:

```bash
uv run scb-check report --manifest comparison.toml --output comparison.html
```

Use the same step identifiers for corresponding checkpoints. Omit a step if that snapshot is missing; do not substitute an empty directory. A missing step interrupts adjacent comparisons, so the example does not calculate a step-1-to-step-3 change for `run-b`.

Paths in the manifest resolve relative to the manifest file. See the [manifest reference](cli.md#manifest) for validation rules.

## Apply consistent settings

Choose one configuration for the entire comparison:

```bash
uv run scb-check report snapshots/step-1 snapshots/step-2 --config analysis.toml --output changes.html
```

Use `--disable-sg` to skip ast-grep for every snapshot, or `--include-all` to include normally suppressed findings and gitignored supported files. Configured exclusions still apply. See [configuration](configuration.md) for discovery and suppression details.

When reviewing the plots, consult [metric interpretation](metrics.md): a larger measurement is not automatically worse code, and missing measurements are not zeros.
