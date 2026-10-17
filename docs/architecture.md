# Architecture

`scb-check check` reports composite scores plus location-level flags explaining a source codebase's current state. `scb-check diff` compares two independently computed check reports: snapshot metric deltas, not code churn.

## Metrics

### Verbosity

`verbosity` is the share of real source lines of code (`SLOC`) flagged by at least one slop signal.

Per file, flagged lines are the union of:

- clone lines from duplicated syntax blocks in any supported language,
- Python `ast-grep` lines from bundled or extra YAML rules,
- structural rule lines from Python rule classes.

Rust, JavaScript, TypeScript, Zig, Haskell, and C++ currently have no bundled slop-pattern rules, so their verbosity contribution is clone LOC only.

That union is intersected with `SLOC`, then divided by total `SLOC`. A line flagged by more than one source counts once. Zero total `SLOC` yields zero verbosity and flagged-LOC counts.

### Erosion

`erosion` is the share of cyclomatic function mass concentrated in high-complexity functions.

- `mass = cyclomatic_complexity * sqrt(sloc)`
- high-complexity functions have `cyclomatic_complexity > 10`
- functions with `sloc <= 0` contribute zero mass

`cog_erosion` uses the same mass-share calculation with cognitive complexity and `cog_complexity > 10`. Zero total mass yields a zero score.

### Snapshot comparison

Each delta is the later measurement minus the earlier measurement, in its existing units. `diff` compares every numeric check report measurement: scores, scanned-file and SLOC counts, flagged-line and finding counts, function counts and masses, and syntax-tree/node counts including per-language counts. Only absent dotted per-language syntax fields contribute zero counts to subtraction; original snapshots keep their own language coverage. Explicit `None` propagates through subtraction, while missing required groups or fields are contract errors.

Absolute ratio differences avoid division by a zero baseline. JSON retains fractional units; human percentage differences are percentage points. Counts and masses expose numerator and denominator changes: verbosity can fall even while flagged SLOC grows. A larger measurement is not automatically a regression, and unchanged aggregates can hide offsetting changes or literal edits. This is not a measure of edit volume.

## Shared source loading

`pipeline.analyze(path, config)` is the full snapshot-analysis workflow used by both commands. It calls `analysis.source.read_and_parse_source` directly, with UTF-8 replacement fallback and warn-and-skip read/parse failures. Successful artifacts feed `_index_check_sources`, which builds rendering, language, SLOC, and syntax-count indexes.

Each comparison side has its own full project context: semantic indexes, clone detection, rules, directives, finding filtering, and scoring. A failed file affects only its own analysis. Files are neither paired across trees nor filtered by textual changes.

## Check pipeline

```text
CLI (`cli.py` / `commands/`)
    │
    ├─ load config
    │
    ▼
`analyze()` in `pipeline.py`
    │
    ├─ discover supported source files with the walker
    ├─ read and parse source through `read_and_parse_source`
    │      └─ emit `ModuleIR`, `SLOC`, symbols, and complexity facts
    ├─ build source indexes
    ├─ build `ProjectIR` semantic indexes
    ├─ detect clone blocks from parser-native trees
    ├─ run bundled and extra Python `ast-grep` rules through `sg`
    ├─ run structural rules over `ProjectIR`
    ├─ apply source ignores, boundary suppression, severity, and thresholds
    └─ return `AnalysisResult` (including sorted `Flags` and source context)
           │
           ├─ `compute_report(analysis)` → `serialize_report(report)` for JSON
           └─ `render_flags()` for location-level human output
```

## Diff pipeline

```text
`commands/diff.py`
    ├─ validate both directories and shared options
    ├─ load one config from cwd discovery or an explicit override
    ├─ `analyze(tree_a, config, ...)` → earlier analysis
    ├─ `analyze(tree_b, config, ...)` → later analysis
    ├─ `compute_diff_report(earlier, later)` → before / after / diff reports
    │      ├─ `compute_report()` for each snapshot
    │      └─ `compare_reports(before, after)` → signed diff report
    ├─ JSON: `serialize_report()` for each report, plus command-owned tree context
    └─ `render_comparison(before, after, diff)` for a human summary
```

Each side must have successfully parsed eligible source; zero-SLOC files are valid. The command applies the same configuration and analysis options to both sides, preserving ordinary walker semantics including each tree's applicable ignore files. Successful comparisons exit `0` regardless of findings; unusable inputs exit `2` with no partial payload. See [README](../README.md#comparing-source-trees) for options and output fields.

### Report-comparison interface

`models.py` defines `ReportValue = int | float | None`, `MetricResult = Mapping[str, ReportValue]`, and `Report = Mapping[str, MetricResult]`. These are data contracts, not runtime report classes. Computed reports expose read-only outer and inner mappings over privately owned dictionaries. Metric results are flat: booleans, strings, sequences, nested mappings, and non-finite numbers are not report values. The canonical groups and fields are in the [README schema reference](../README.md#check-json-report-fields).

`reporting.score.compute_report(analysis: AnalysisResult)` explicitly composes `Verbosity`, `Erosion`, `CognitiveErosion`, and `Syntax` instances from the sibling `metrics/` package. Each metric's `compute()` receives narrowly scoped extracted facts and owns its field names, supporting counts, calculations, and units. The builder owns group names. Private `metrics/_mass.py` shares erosion arithmetic; tree walking owns complexity extraction, not mass calculations.

`metrics.base.Metric` is an abstract base with an abstract `compute()` method and class-declared `units`. Its parameter specification preserves each concrete metric's distinct input signature; it does not require a common analysis context or introduce a registry or dynamic discovery. Metrics do not import reporting.

`comparison.compute_diff_report(earlier_analysis, later_analysis)` returns an ordinary dictionary with exactly `before`, `after`, and `diff`, each a `Report`. It uses the standalone snapshot builder and pure `compare_reports(before, after) -> Report`. The latter has no source access, parsing, analysis execution, or terminal output. It subtracts later minus earlier, retaining zero differences. Required groups and fields must be present; only absent dotted per-language syntax counts are zero-filled over the sorted language union. Explicit `None` on either side produces `None`, even when both sides are null. Snapshots are never mutated.

The two-analysis builder leaves room for a future pairwise measurement without defining all comparisons as subtraction. It currently implements only snapshot differences, with no file pairing, source rereading, or churn calculation.

`score.serialize_report(report)` validates the report contract and creates fresh plain outer and inner dictionaries; changing serialized data cannot change a computed report. `None` becomes JSON `null`. Tree paths remain command-owned context outside numerical reports. `render_comparison(before, after, diff)` uses metric-owned units: fractional scores become percentages, score differences become percentage points, counts and masses keep their units, and unavailable values are explicit. Unit metadata is not embedded in report values.

## Layers

- Boundary: `cli.py`, `commands/`, `config.py`, `walker.py`, and `logging.py` parse arguments, load configuration, walk paths, and wire logging. They do not score code.
- Tree walking: `tree_walking/` parses already-read supported source, computes `SLOC`, parses Python source directives, emits language-agnostic IR, and builds semantic project context. See [Tree walking](tree-walking.md).
- Pipeline: `pipeline.py` owns full snapshot analysis, source indexing, and finding construction for both check and diff.
- Analysis: `analysis/` owns `ast-grep` subprocess execution, clone hashing, and shared source IO/parse warnings.
- Rules: `rules/` owns structural rule classes, their registry, metadata, and the runner.
- Metrics: `metrics/` owns metric classes, the `Metric` abstract base, calculation helpers, and units. It consumes extracted facts without source IO or reporting dependencies.
- Reporting: `reporting/` selects facts from `AnalysisResult`, explicitly composes metric results, compares data-only reports, serializes JSON-compatible mappings, and renders metrics or location-level `Flags`.
- Shared models: `models.py` contains frozen analysis/finding dataclasses, including `AnalysisResult` and `Flags`, plus the report mapping aliases. Reporting does not import pipeline orchestration for its data model. Tree-walking IR models live in `tree_walking/models.py`.

## Vocabulary

`SLOC`
: Real source lines of code. Comments, blank lines, punctuation-only delimiter lines in generic parsers, and standalone non-byte, non-f-string Python string statements do not count.

`source directive`
: Python comment directive parsed with `tokenize`, such as `# scbc ignore[...]` or `# scbc boundary`.

`boundary suppression`
: `# scbc boundary` inside a function body hides default `ast-grep` findings in that function. Use `--include-all` to show boundary-suppressed findings.

`ast-grep rule`
: Python YAML-backed rule run by the `sg` subprocess. Extra local rules come from `SCB_CHECK_EXTRA_SLOP_RULES`.

`clone finding`
: Duplicate syntax block found by hashing normalized tree-sitter subtrees. Candidates must contain at least two executable body statements in one duplicated body; signatures, comments, blanks, and Python docstrings do not satisfy that threshold.

`structural rule`
: Python class in `rules/` that checks typed IR subjects and returns `RuleFinding | None`.

`ModuleIR`
: Pydantic model for a parsed source module. It contains generic symbols, imports, references, operations, source spans, and `SLOC` lines; it does not expose raw tree-sitter nodes.

`SymbolIR`
: Language-agnostic code symbol such as a class, function, method, or value. Function-like symbols carry signatures, roles, body operations, references, `SLOC`, complexity values, and maximum control-flow nesting depth.

`ProjectIR`
: Project-level semantic model built from parsed modules. It indexes modules, symbols, files, and derived effects.

`RuleContext`
: Query interface passed to structural rules so rules ask semantic questions, including resolved project call sites, instead of inspecting parser-native syntax.

`RuleFinding`
: Fixed-field structural finding with rule ID, severity, message, span, and subject metadata.

## Design constraints

- Line numbers are 1-indexed after tree-sitter data leaves the parser layer.
- Supported scan targets are Python (`.py`, `.pyw`), Rust (`.rs`), JavaScript (`.js`, `.mjs`, `.cjs`), TypeScript (`.ts`), Zig (`.zig`), Haskell (`.hs`), and C++ (`.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx`).
- `ast-grep`, structural rules, and source directives are Python-only until language-specific rule sets exist.
- Parser-native data may live on parsed file artifacts for clone detection, but not in `ModuleIR`, `ProjectIR`, or structural rules.
- `ast-grep` failure is non-fatal. `scb-check` tries a global `sg` binary first, then falls back to package-managed ast-grep executables next to Python if global `sg` is missing or fails. If no ast-grep binary succeeds, `OSError`, non-zero exits, or invalid JSON return no hits.
- Source ignores and structural rules share one rule ID namespace, so `scbc ignore[...]` is never ambiguous.
- Clone and erosion findings are not suppressible. `ast-grep` and structural findings are suppressible.
- Immutable records cross module boundaries: frozen dataclasses and Pydantic models, with tuples instead of lists.

## Scoring-sensitive surfaces

Change these only with tests and documentation updates because they move user-visible scores:

- `SLOC` exclusions in `tree_walking/languages/python.py` and `tree_walking/languages/generic.py`,
- `CLONE_NODE_TYPES`, language clone configs, and clone normalization in `analysis/clones.py` plus `tree_walking/languages/*`,
- cyclomatic and cognitive complexity node sets in `tree_walking/languages/python.py` and `tree_walking/languages/*`,
- structural rule span selection and filtering in `rules/` and `pipeline.py`,
- verbosity union in `metrics/verbosity.py` and complexity mass-share logic in `metrics/erosion.py`, `metrics/cog_erosion.py`, and private `metrics/_mass.py`,
- field coverage and later-minus-earlier arithmetic in `reporting/comparison.py`.

## Extension points

- Extra `ast-grep` rules: set `SCB_CHECK_EXTRA_SLOP_RULES` to a `:`-separated list of YAML files.
- Structural rules: add a rule class in `rules/`, register it in `rules/registry.py`, and keep it on IR plus `RuleContext`.
- New CLI commands: add command wiring under `commands/` and register from `cli.py`.
- Snapshot metrics: subclass `metrics.base.Metric` with a metric-owned flat result and units, explicitly compose it in reporting, and extend comparison contracts and CLI acceptance coverage; see [Development](development.md#adding-or-extending-a-metric).
