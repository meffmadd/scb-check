# CLI reference

## Commands

```bash
scb-check check PATH                       # location-level findings
scb-check check PATH --output-format json  # numerical metric report
scb-check check PATH --report              # shortcut for JSON output
scb-check check PATH -v                    # info logging; -vv for debug
scb-check check PATH --config FILE         # explicit configuration
scb-check check PATH --include-all         # include normally suppressed findings and gitignored files
scb-check check PATH --disable-sg          # skip ast-grep subprocess findings
scb-check check PATH --min-duplicate-lines N  # minimum duplicated SLOC for displayed groups
scb-check rule RULE_ID                     # bundled YAML or structural rule metadata
scb-check diff TREE_A TREE_B               # before / after / signed differences
scb-check diff TREE_A TREE_B --output-format json
scb-check report TREE_A TREE_B TREE_C      # offline report.html
scb-check report TREE_A TREE_B TREE_C --output changes.html
```

Every command accepts `--help`. See [comparing snapshots](comparing-snapshots.md) for a task-oriented guide, [configuration](configuration.md) for settings and source directives, and the [JSON reference](report-fields.md) for numerical output.

## Source discovery

For `check`, `PATH` may be a file or directory; `diff` and `report` accept directories only. Directories are walked for supported source files:

| Language | Suffixes |
| --- | --- |
| Python | `.py`, `.pyw` |
| Rust | `.rs` |
| JavaScript | `.js`, `.mjs`, `.cjs` |
| TypeScript | `.ts` |
| Zig | `.zig` |
| Haskell | `.hs` |
| C++ | `.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx` |

Directory discovery respects `.gitignore` globs by default. `--include-all` includes gitignored supported files plus ignored, lower-severity, and boundary-suppressed findings. Configured excludes and default excluded directories still apply.

Ast-grep rules, structural rules, and source directives are Python-only. Other supported languages participate in SLOC totals, clone detection, cyclomatic erosion, and cognitive erosion. Semantic coupling measurements have [Python-first, partial coverage](metrics.md#partial-metric-interpretation).

Individual read/parse failures warn and skip within their own analysis. Each snapshot needs at least one successfully parsed eligible file; parsed zero-SLOC files are valid. Invalid directives fail the run unless `--include-all` is used. Optional ast-grep failures degrade without aborting analysis.

## Check findings

Human output shows location-level findings with source context. JSON output contains measurements rather than a findings list.

Clone detection only emits duplicated syntax blocks with at least two executable body statements. Function signatures, comments, blanks, and Python docstrings do not satisfy that threshold; displayed clone line counts and `--min-duplicate-lines` still use duplicated SLOC in the clone span.

`scb-check` tries a global `sg` executable first. If it is missing or fails, it falls back to the `ast-grep-cli` executable installed with the package. `--disable-sg` skips these subprocess findings, not clone detection or structural rules.

`SCB_CHECK_EXTRA_SLOP_RULES` accepts a `:`-separated list of YAML paths to layer local ast-grep rules on top of the bundled set.

## Comparing source trees

`scb-check diff TREE_A TREE_B` runs a full check analysis of each directory, including plain directories outside any Git repository. `TREE_A` is the earlier snapshot; `TREE_B` is the later snapshot. Every delta is **after minus before**, including negative and zero values. The default human summary shows both resolved roots and before/after/diff columns for all scores, underlying counts, complexity masses, and syntax counts.

One configuration applies to both analyses: discovered from the current working directory, or selected with `--config FILE`. Tree-local configs are not loaded separately. Discovery uses each tree's applicable `.gitignore` files and ordinary check exclusion semantics. `--include-all` has its full check meaning on both sides; `--disable-sg` disables ast-grep on both sides. Logging uses `-v` / `--verbosity` and `-vv` as with `check`.

There is no `--report` alias, duplicate-display option, or threshold gate. Failures skip independently within each analysis, without dropping the readable counterpart in the other tree. An unusable side fails the comparison without a partial payload on stdout.

See [diff JSON fields](report-fields.md#diff-json-fields) for the output contract and [metric interpretation](metrics.md) for why differences are not churn or quality judgments.

## Plot reports

`scb-check report PATH... [OPTIONS]` creates a self-contained HTML report from at least two source directories in supplied order. Inputs are source trees, not saved JSON or Git revisions. Repeated paths remain separate positions; inputs are neither sorted nor deduplicated.

| Option | Behavior |
| --- | --- |
| `--manifest FILE` | TOML manifest of named series aligned by explicit steps; cannot be combined with positional paths. |
| `--output PATH` | HTML destination; defaults to `report.html` in the current directory. |
| `--config FILE` | Shared settings file; otherwise discover settings from the current directory. |
| `--include-all` | Include gitignored files and normally suppressed findings for every input. |
| `--disable-sg` | Skip ast-grep checks for every input. |
| `-v` / `--verbosity` | Info logging; repeat as `-vv` for debug logging. |
| `--help` | Show usage. |

### Manifest

`scb-check report --manifest comparison.toml --output comparison.html` accepts one or more named series. A single-series manifest produces the same values and changes as equivalent positional inputs:

```toml
steps = ["1", "2", "3"]

[series.eve_industry]
"1" = "eve_industry/checkpoint_1/snapshot"
"2" = "eve_industry/checkpoint_2/snapshot"
"3" = "eve_industry/checkpoint_3/snapshot"
```

Multiple series share those exact step identifiers and their declared order:

```toml
steps = ["1", "2", "3"]

[series.problem-1]
"1" = "run/problem-1/checkpoint_1/snapshot"
"2" = "run/problem-1/checkpoint_2/snapshot"
"3" = "run/problem-1/checkpoint_3/snapshot"

[series.problem-2]
"1" = "run/problem-2/checkpoint_1/snapshot"
"3" = "run/problem-2/checkpoint_3/snapshot"
```

Relative source paths resolve against the manifest's directory, not the working directory. Steps must be a nonempty list of unique, nonempty strings; `series` must contain named tables mapping declared steps to nonempty directory paths. Omitted entries are missing snapshots, never zeros. Explicit invalid paths, undeclared steps, malformed TOML, and unknown top-level keys are errors before analysis. An explicitly configured snapshot must still contain usable source.

Missing snapshots interrupt both values and adjacent changes: a change compares only the current and previous **declared step** within the same series, never an earlier available checkpoint.

### Analysis and output

One configuration and equal analysis flags apply to every snapshot, with ordinary `check`/`diff` semantics. Tree-local configs are not loaded separately. By default, exclusions and suppressions apply and ast-grep runs normally. `--include-all` includes ignored, informational, and boundary-suppressed findings, but configured excludes and default excluded directories still apply.

Every field in the full [check report](report-fields.md#check-json-report-fields), including counts and per-language fields, gets separate value and adjacent-change line plots. Changes are **current minus previous**, positioned at the later input; the first input has no previous difference. The x-axis is evenly spaced, not elapsed time. Positional labels include index and directory basename; manifest labels are the declared steps. Hover shows the series (when named), input label and plotted value or signed change with its unit. Full resolved paths appear once in a collapsed **Source directories** list; there are no per-plot tables. Value and change plots sit side by side on wide screens and stack on narrow screens.

Metrics are organized into collapsible groups such as `syntax`, containing fields such as `syntax.python.node_count`. Groups start collapsed; click the group heading (or use the keyboard) to expand or collapse the whole group. These native disclosures work without JavaScript; charts still require it. Each metric plots one line per series with a legend.

Unavailable values are gaps, not zeros or interpolated lines; isolated observations remain dots. Language fields cover the union of inputs, but absent snapshot language counts remain unavailable. Only subtraction zero-fills absent dotted syntax counts; a language absent from both adjacent snapshots has no change measurement. Explicit `null` propagates. Fractions display as percentages and their changes as percentage points; counts, masses, and dimensionless ratios retain metric-owned units.

Plotly.js is embedded once, with no CDN or network requirement. Plots and hover require JavaScript; without it, the page explains this requirement and source directories remain accessible. Output is always HTML, with all metrics and both plots: there is no metric selection, mode switch, `--output-format`, `--report` alias, `--min-duplicate-lines`, threshold gate, Git traversal, or browser launch.

Every input needs successfully parsed eligible source; parsed zero-SLOC files are valid. Individual read/parse failures warn and skip normally, but an unusable snapshot is never silently dropped. Only complete HTML is published, atomically; failure preserves any existing artifact. The output parent must already exist. See [ordered plot reports](architecture.md#ordered-plot-reports) for reporting internals and partial-coverage limits.

## Exit codes

| Command | `0` | `1` | `2` |
| --- | --- | --- | --- |
| `check` | No findings | Any finding: clones, ast-grep hits, structural findings, or high-complexity functions | Usage, configuration, input, or directive errors |
| `rule` | Rule displayed | Not used | Usage or unknown rule errors |
| `diff` | Successful comparison, regardless of findings or delta signs | Not used | Invalid paths/config/options/directives or a side without successfully parsed eligible files |
| `report` | Successful generation, regardless of findings | Not used | Usage, input, configuration, or output errors |

Failures print to stderr. `diff` produces no partial comparison on failure; `report` preserves any existing output artifact.
