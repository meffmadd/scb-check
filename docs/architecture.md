# Architecture

`scb-check check` reports composite scores plus location-level flags explaining a source codebase's current state. `scb-check diff` measures SLOC churn between two source trees using the same discovery and parser accounting.

## Metrics

### Verbosity

`verbosity` is the share of real source lines of code (`SLOC`) flagged by at least one slop signal.

Per file, flagged lines are the union of:

- clone lines from duplicated syntax blocks in any supported language,
- Python `ast-grep` lines from bundled or extra YAML rules,
- structural rule lines from Python rule classes.

Rust, JavaScript, TypeScript, Zig, Haskell, and C++ currently have no bundled slop-pattern rules, so their verbosity contribution is clone LOC only.

That union is intersected with `SLOC`, then divided by total `SLOC`. A line flagged by more than one source counts once.

### Erosion

`erosion` is the share of cyclomatic function mass concentrated in high-complexity functions.

- `mass = cyclomatic_complexity * sqrt(sloc)`
- high-complexity functions have `cyclomatic_complexity > 10`
- functions with `sloc <= 0` contribute zero mass

`cog_erosion` uses the same mass-share calculation with cognitive complexity and `cog_complexity > 10`.

### Churn

For each eligible relative path, `churn = added SLOC + deleted SLOC`. Each side is filtered to its parser SLOC lines before matching their text, so excluded lines cannot act as match anchors. A line entering or leaving SLOC is an addition or deletion even if its text is unchanged. Relative path is identity, so moving a file contributes deletion plus addition. Edits confined to non-SLOC lines have `unchanged` status and zero churn. Retained SLOC text is not stripped or reformatted: indentation, whitespace, and inline-comment edits on code lines contribute churn.

`churn_total` sums file churn; `churn_touched_files` counts files with positive churn. For union size `N` and positive file churn shares `p_i`, normalized entropy is `-sum(p_i * log2(p_i)) / log2(N)`. Unchanged and zero-churn files remain in `N`, so dispersion is measured against the full comparison scope. Zero total churn or `N <= 1` yields `0.0`. Files failing to read or parse on either side are excluded from both churn and the union denominator.

## Shared source collection

`pipeline.analyze(path, config)` examines a code state; `pipeline.analyze_diff(tree_a, tree_b, config)` examines change between states. Both use private `_collect_sources` to read and parse source through `analysis/source.py`. Collection preserves input order and absent slots; a present path returning `None` signals a read/parse failure. There is no public collection type or source-only mode.

Check filters successful artifacts into `_index_check_sources`, which builds rendering, language, SLOC, and syntax-count indexes. Diff loads one relative-path pair at a time, excludes the whole path if either present side fails, and delegates already-parsed versions to `analysis/tree_diff.compare_file`. It does not retain both trees' parser artifacts or build check-only indexes. The existing parsers still compute IR, symbols, and complexity; this is not a separate SLOC-only parser.

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
    ├─ collect parsed source through `_collect_sources`
    │      └─ emit `ModuleIR`, `SLOC`, symbols, and complexity facts
    ├─ build check-only source indexes
    ├─ build `ProjectIR` semantic indexes
    ├─ detect clone blocks from parser-native trees
    ├─ run bundled and extra Python `ast-grep` rules through `sg`
    ├─ run structural rules over `ProjectIR`
    ├─ apply source ignores, boundary suppression, severity, and thresholds
    └─ build sorted `Flags`
           │
           ├─ `compute_report()` for JSON scores
           └─ `render_flags()` for human-readable output
```

## Diff pipeline

```text
`commands/diff.py`
    ├─ load one config from the current directory
    └─ `pipeline.analyze_diff(tree_a, tree_b, config)`
           ├─ walk each tree using its own gitignore policy
           ├─ union relative paths, including unchanged files
           ├─ collect each file pair through shared `_collect_sources`
           ├─ exclude the whole path if either present side fails
           └─ `analysis/tree_diff.compare_file(path, before, after)`
                  ├─ filter each side to ordered parser SLOC lines
                  ├─ deterministic `SequenceMatcher` over retained SLOC text
                  │      └─ universal newlines, no phantom final line, no autojunk
                  └─ original source line numbers → `FileDiff` → `TreeDiff`
                  │
                  └─ `reporting/churn.compute_diff_report()` → flat payload
                         ├─ flat JSON with prefixed churn fields
                         └─ `render_diff_report()` for a human summary
```

The CLI requires directory roots, accepts a populated-versus-empty comparison, and rejects an empty union after parse skips. No git integration, subprocess, rule execution, source-directive filtering, or checkpoint pairing is involved. See [README](../README.md#comparing-source-trees) for the command contract.

### Tree-diff library seam

`scb_check.pipeline.analyze_diff(tree_a, tree_b, config, include_all=False)` returns a `TreeDiff` with resolved roots and a relative-path-sorted `files` tuple. It is the change-analysis sibling of `analyze(path, config)`. The frozen `TreeDiff` and `FileDiff` dataclasses are defined in `scb_check.models`; each record's `path` is its identity.

Each `FileDiff` carries `path`, `status` (`added`, `deleted`, `modified`, or `unchanged`), and immutable 1-indexed `added_sloc_lines` / `deleted_sloc_lines`. Status reflects presence and changes to retained SLOC text, not changes to excluded lines or original line positions. Parse failures omit the entire path. Library callers may receive an empty `files` tuple; only the CLI treats that as an error.

Future diff metrics consume this seam and aggregate in reporting. New JSON metrics add flat, prefixed fields rather than changing existing fields; there is no metric registry or checkpoint discovery layer.

## Layers

- Boundary: `cli.py`, `commands/`, `config.py`, `walker.py`, and `logging.py` parse arguments, load configuration, walk paths, and wire logging. They do not score code.
- Tree walking: `tree_walking/` parses already-read supported source, computes `SLOC`, parses Python source directives, emits language-agnostic IR, and builds semantic project context. See [Tree walking](tree-walking.md).
- Pipeline: `pipeline.py` owns sibling check/diff workflows, shared private collection, check-only indexing, and diff root validation, pairing, and failure exclusion.
- Analysis: `analysis/` owns `ast-grep` subprocess execution, clone hashing, shared source IO/parse warnings, and pure comparison of already-parsed files over parser SLOC.
- Rules: `rules/` owns structural rule classes, their registry, metadata, and the runner.
- Reporting: `reporting/` turns `Flags` into JSON reports or human-readable flag text, and `TreeDiff` into churn summaries. Check JSON includes score summaries plus syntax tree and node counts by parsed language.
- Shared models: `models.py` contains frozen dataclasses shared by analysis, pipeline, and reporting. Tree-walking IR models live in `tree_walking/models.py`.

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
- verbosity union logic in `reporting/score.py`,
- pre-match SLOC filtering, matching, and original-line mapping in `analysis/tree_diff.py`,
- eligible-union entropy normalization in `reporting/churn.py`.

## Extension points

- Extra `ast-grep` rules: set `SCB_CHECK_EXTRA_SLOP_RULES` to a `:`-separated list of YAML files.
- Structural rules: add a rule class in `rules/`, register it in `rules/registry.py`, and keep it on IR plus `RuleContext`.
- New CLI commands: add command wiring under `commands/` and register from `cli.py`.
- Diff metrics: consume the [tree-diff library seam](#tree-diff-library-seam) and add prefixed report fields in reporting.
