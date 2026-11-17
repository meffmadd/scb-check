# Architecture

`scb-check check` reports composite scores plus location-level flags explaining a source codebase's current state. `scb-check diff` compares two independently computed check reports: snapshot metric deltas, not code churn. `scb-check report` plots full reports and adjacent differences across an ordered list of source trees.

This guide describes implementation boundaries and data flow. See the [metric index](metrics.md) for links to implementation docstrings covering formulas, counting policies, and sources. The [JSON reference](report-fields.md) owns numerical fields, units, and aggregation.

## Shared source loading

`pipeline.analyze(path, config)` is the full snapshot-analysis workflow used by `check`, `diff`, and `report`. It calls `analysis.source.read_and_parse_source` directly, with UTF-8 replacement fallback and warn-and-skip read/parse failures. Successful artifacts feed `_index_check_sources`, which builds rendering, language, SLOC, and syntax-count indexes.

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
    │      └─ emit `ModuleIR`, `SLOC`, symbols, complexity, and Python text/use/member/type facts
    ├─ build source indexes
    ├─ build `ProjectIR` semantic indexes
    ├─ detect clone blocks from parser-native trees
    ├─ run bundled and extra Python `ast-grep` rules through `sg`
    ├─ run structural rules over `ProjectIR`
    ├─ apply source ignores, boundary suppression, severity, and thresholds
    └─ return `AnalysisResult` (retained `ProjectIR`, sorted `Flags`, read-only source context)
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

Each side must have successfully parsed eligible source; zero-SLOC files are valid. The command applies the same configuration and analysis options to both sides, preserving ordinary walker semantics including each tree's applicable ignore files. Successful comparisons exit `0` regardless of findings; unusable inputs exit `2` with no partial payload. See [CLI reference](cli.md#comparing-source-trees) for options and output fields.

### Report-comparison interface

`models.py` defines `ReportValue = int | float | None`, `MetricResult = Mapping[str, ReportValue]`, and `Report = Mapping[str, MetricResult]`. These are data contracts, not runtime report classes. Computed reports expose read-only outer and inner mappings over privately owned dictionaries. Metric results are flat: booleans, strings, sequences, nested mappings, and non-finite numbers are not report values. The canonical groups and fields are in the [JSON schema reference](report-fields.md#check-json-report-fields).

`reporting.score.compute_report(analysis: AnalysisResult)` explicitly composes `Verbosity`, `Erosion`, `CognitiveErosion`, `Syntax`, `CBO`, `RFC`, `MPC`, `DistinctCallers`, `DAC`, `CIC`, `RIC`, `AfferentCoupling`, `EfferentCoupling`, and `ModuleCallDependencies` instances from the sibling `metrics/` package. Each metric's `compute()` receives narrowly scoped extracted facts and owns its field names, supporting counts, calculations, and units. The builder owns group names. Private `metrics/_mass.py` shares erosion arithmetic; `metrics/_counts.py` shares sum/mean/max arithmetic for measured CBO, RFC₁, MPC, callers, DAC, CIC, Ca, Ce, and directional module-neighbor counts, returning `None` aggregates for an empty measured population. Concrete metrics retain population, field, and unit ownership. Tree walking owns complexity extraction, not mass calculations.

`metrics.base.Metric` is an abstract base with an abstract `compute()` method and class-declared `units`. Its parameter specification preserves each concrete metric's distinct input signature; it does not require a common analysis context or introduce a registry or dynamic discovery. Metrics do not import reporting.

`comparison.compute_diff_report(earlier_analysis, later_analysis)` returns an ordinary dictionary with exactly `before`, `after`, and `diff`, each a `Report`. It uses the standalone snapshot builder and pure `compare_reports(before, after) -> Report`. The latter has no source access, parsing, analysis execution, or terminal output. It subtracts later minus earlier, retaining zero differences. Required groups and fields must be present; only absent dotted per-language syntax counts are zero-filled over the sorted language union. Explicit `None` on either side produces `None`, even when both sides are null. Snapshots are never mutated.

The two-analysis builder leaves room for a future pairwise measurement without defining all comparisons as subtraction. It currently implements only snapshot differences, with no file pairing, source rereading, or churn calculation.

`score.serialize_report(report)` validates the report contract and creates fresh plain outer and inner dictionaries; changing serialized data cannot change a computed report. `None` becomes JSON `null`. Tree paths remain command-owned context outside numerical reports. `render_comparison(before, after, diff)` uses metric-owned units: fractional scores become percentages, score differences become percentage points, counts and masses keep their units, and unavailable values are explicit. Unit metadata is not embedded in report values.

### Ordered plot reports

`commands/report.py` validates positional directories or a TOML manifest before analysis, then supplies aligned `SnapshotSeries` inputs and a configured loader to `reporting.trend.build_aligned_trend(steps, sources, load_report)`. Relative manifest paths resolve at the command boundary against the manifest directory. Positional inputs become one unnamed series; `build_trend(paths, load_report)` remains the single-series library convenience. The loader runs ordinary analysis, validates usable source, and returns `compute_report` output for each position. One cwd-discovered or explicit configuration and equal analysis flags apply to every input. Only numerical reports are retained across snapshots, not whole-project IRs. Commands own validation and atomic artifact publication; rendering performs no source reads.

Immutable `AlignedTrend` holds shared step identifiers and independent `Trend` objects. Each `Trend` preserves its name, aligned paths, numerical snapshots, comparisons and per-metric measurements; omitted snapshots are `None`. Supplied order and repeated paths survive. All series use the union of observed language fields across every input. Only neighboring declared steps within a series are compared: a missing snapshot interrupts both adjacent comparisons, without bridging to earlier available inputs. Every canonical field and the union of observed language fields produce value and adjacent-change series. Differences delegate to `compare_reports`; there is no alternative subtraction policy. Snapshot language fields absent from an input remain unavailable. Syntax-only zero-filling belongs to comparison; a language absent from both adjacent reports has no delta field. Explicit nulls remain gaps, while zero and isolated values remain visible observations. The first input has no preceding difference.

`reporting/plot.py` prepares library-neutral raw numerical data and plot sections. Full read-only snapshots and comparisons remain available in the embedded data. The packaged Jinja template owns the chart-first layout and embeds data using `tojson`; `static/plot.js` alone translates it into Plotly SVG scatter traces, axes, and tooltips. Native `details`/`summary` disclosures group fields by their top-level metric prefix, preserving report order and starting collapsed. Each metric pairs value and change plots, side by side on wide screens and stacked on narrow screens. Collapse/expand needs no JavaScript; the chart adapter skips closed disclosures during resize and redraws on reopening. Each chart has one trace per series, without a legend. Hover shows the series, input label, plotted measurement with its unit, and the series' Kendall τ-b. Full resolved paths appear once in a collapsed source-directory list, not in tooltips or per-plot tables. All metrics and both plots are included regardless of their values; only native group disclosures control section visibility. Chart options stay outside Python models and numerical reports. Metric-owned units convert only for display: fractions become percentages, differences become percentage points, and dimensionless ratios remain ratios.

Values plots summarize monotonic association with declared step order using SciPy's default Kendall τ-b. Missing observations are omitted, and undefined coefficients (including constant or fewer than two observations) are excluded from the signed, unweighted mean. Both plots show the value-series coefficient on hover; the values-plot mean with contributor count is descriptive, not a significance test. Adjacent changes have no separate trend statistic. The calculation belongs to HTML preparation and does not alter numerical report contracts.

Package loaders/resources find templates and assets independently of cwd. The pinned basic Plotly distribution is embedded once, with attribution, so reports need no server or network. JavaScript enables plots/hover; without scripting, the page explains the requirement and the source-directory disclosure remains accessible. Jinja autoescape protects page text, `StrictUndefined` catches missing context, and only fixed bundled scripts become trusted markup after script-end-tag escaping. Hover text is escaped separately because Plotly supports HTML-like formatting.

Input order is categorical, not chronology or elapsed time. Adjacent differences are not churn or quality judgments: changes in retained populations, scanned context, or extraction coverage can change summaries without changing existing relationships. Read [partial metric interpretation](metrics.md#partial-metric-interpretation) alongside supporting measured/unavailable counts. CLI syntax, options, defaults, and failure behavior are canonical in [CLI reference](cli.md#plot-reports).

### Text evidence boundary

Python's immutable `TextFragmentIR` records preserve source evidence for analysis consumers, including CSE's function/method, class, and file documents. Each occurrence lives once in its module's physical-file inventory with a syntactic owner; parent documents can select child owners without duplicate authoritative copies. Other languages explicitly declare extraction unavailable. See [the fragment contract](tree-walking.md#source-text-fragments) for ownership, spans, and availability.

The IR preserves spelling rather than choosing semantic preprocessing: it does not split identifiers, remove stop words, stem, tokenize for a model, embed, or assemble documents. Consumers choose document membership and representations. Metric implementations remain responsible for populations, formulas, and scores; retaining comments/docstrings does not make them SLOC or change verbosity, erosion, report fields, or independent-snapshot comparison.

### Source-use evidence boundary

Python calls and attribute accesses live once in `ModuleIR.source_uses`, with snapshot occurrence IDs, spans, execution owners, and explicit direct-resolution evidence. Imports remain separate bindings. `build_project()` refines import targets against retained entities; `ProjectIR.source_uses_by_id` is a read-only index, not another inventory. See [the source-use contract](tree-walking.md#canonical-source-uses-and-imports) for supported contexts, alias/scope handling, ambiguity, and unresolved dynamics.

A source site, a distinct caller, and a distinct target are different populations: repeated sites and recursion must survive extraction so consumers can choose counts and direction policies. Static binding evidence is not a possible-runtime-target set. External status requires import/builtin evidence outside the retained snapshot; dotted spelling alone supplies neither external status nor type/runtime-target inference.

Rule-facing references and shallow operation-selected effects intentionally preserve textual nesting, parameter/builtin exclusions, rule-specific self-recursion exclusions, and dotted-call keep-policy. Linked effects carry `source_use_id`, but their rule labels need not match canonical resolution status. This separation retains existing structural-rule behavior while exposing richer facts. Metric populations, counts, formulas, and scores stay in consumers, outside the IR; the inventory itself defines no metric formula. Its consumers preserve verbosity/erosion and CLI exit contracts while adding explicit check/independent-snapshot diff measurements.

### Class and type evidence boundary

Python class/member facts retain declarations rather than precomputed coupling or inherited-member populations. A canonical attribute distinguishes two fields of one class type from two writes to one field; structured types preserve self references, primitives, wrappers, and uncertainty without deciding which count toward DAC or CBO. Direct base relations distinguish inheritance from composition without treating an inherited body as new implementation mass.

Callable facts separate the declaring class, source body identity/location, and recognized abstract/placeholder syntax. The bounded Python member resolver associates inherited members with canonical declarations and implementation bodies without copying them. Declared receivers and retained subclass overrides supply separate possible-body sets with explicit complete-under-assumption, approximate, or unavailable evidence; these do not follow from direct-base/type facts alone. See [the class/member reference](tree-walking.md#class-member-and-declared-type-facts) for producers, ownership, and supported syntax.

Consumers decide whether to include inherited/abstract methods for RFC, which wrappers/primitive/self types contribute to DAC/CBO, and whether to count member-use sites or distinct targets for MPC. Those choices change metric populations and scores, so they remain outside the IR. The facts themselves define no metric formula; consumers above select RFC₁, MPC, and DAC policies while preserving existing rule, verbosity/erosion, CLI exit, and independent-snapshot comparison contracts.

### Metric-ready analysis data flow

The retained contract connects four slices:

```text
already-read source → entities/owners + text fragments + source uses/imports + types/bases
                              ↓                      ↓                         ↓
                         entity indexes ← lexical/import resolution ← retained project
                              ↓                      ↓
                         C3 member lookup → static declarations + possible body sets
                              ↓                      ↓
                       AnalysisResult.project (one independent immutable snapshot)
                              ↓
                 consumer-selected populations, relations, documents, and metrics
```

Entity IDs connect execution owners to source occurrences, declarations to modules/classes, and text fragments to syntactic owners. A static member target identifies its declaring entity rather than manufacturing a member on the receiver class. Implementation identities distinguish an inherited body from an override. Source occurrences remain physical sites, including repetitions and recursion, not expanded runtime edges. Text remains original evidence: preprocessing, embeddings, and document assembly would bake a model and population policy into shared analysis, prevent alternative representations, and duplicate parent/child documents.

The IR-first gate is validated at `analyze_files(...).project` by `tests/test_member_analysis.py`, including `tests/fixtures/ir_contract/`, alongside the entity/use/type/text suites. These tests assert facts, not early metrics. The contract enables restricted, explicitly labeled analyses; it does not remove unsupported Python/library/incoming-caller uncertainty. See [resolution support and assumptions](tree-walking.md#member-resolution-and-runtime-targets).

| Candidate | Required retained facts | Consumer-owned choices |
| --- | --- | --- |
| CBO | Class ownership; method/field uses; canonical declaring owners; possible runtime bodies | Partner union/direction, self exclusion, modeled class universe, partial coverage |
| RFC₁ | Own/inherited member lookup; body identities and bodyless markers; direct calls and possible bodies | Method population and one-level response-set union, not transitive closure |
| MPC | Call occurrence IDs; executing method and implementation owner; static target implementation owner | Per-site count, own/inherited source/target exclusions |
| Distinct callers / callees | Callable IDs; execution owners; direct static/possible targets; module IDs; recursive/repeated sites | Relation inversion/deduplication, recursion and initializer policy |
| DAC | Canonical fields, declaring classes, structured declared types and uncertainty | Attribute population, wrappers/union interpretation, primitives and library policy |
| Ca/Ce class categories | Class/module ownership; resolved method/field uses, types and base relations as separately selectable evidence | Category grouping and dependency predicate; class populations, not module neighbors |
| Module-call dependencies | Logical module/file mapping; static resolved calls; endpoint module IDs | Directed neighbor sets, self exclusion, retained-project scope, partial coverage |
| CIC | Direct bases; static member/field targets; canonical defining/implementation owners; actual sites | Proper-ancestor traversal/filter, inherited-source and dispatch policy, site counting |
| Method RIC | Target method/class identity; distinct executing method/class owners, including owner-class and comparison-class use | Pair population, user deduplication, denominator floor and ratio |
| Multilevel CSE | Original `TextFragmentIR` text/spans and module/declaration owner tree, including nested owners | Method/class/file selection, document preprocessing, explicitly supplied local encoder and similarity |

Implemented consumers and future candidates handle unavailable inventories and uncertain targets explicitly. Shared language resolution belongs here even when expensive; metric-specific graph traversal/counting and embedding computation do not. Fact extraction itself adds no scores, thresholds, or backend registry; implemented metrics explicitly compose their report fields. Ca/Ce select their shared category/dependency policy from these same retained facts; see [the category policy docstrings](../src/scb_check/metrics/categories.py). Existing verbosity/erosion, rule projections, CLI exits, and standalone-check/independent-diff contracts are unchanged.

## Layers

- Boundary: `cli.py`, `commands/`, `config.py`, `walker.py`, and `logging.py` parse arguments, load configuration, walk paths, and wire logging. They do not score code.
- Tree walking: `tree_walking/` parses already-read supported source, computes `SLOC`, parses Python source directives, emits language-agnostic IR, and builds semantic project context. See [Tree walking](tree-walking.md).
- Pipeline: `pipeline.py` owns full snapshot analysis, source indexing, and finding construction for check, diff, and report.
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
: Pydantic model for a parsed source module. It contains generic symbols, text fragments, canonical source uses, import bindings, rule-facing references, operations, source spans, and `SLOC` lines; it does not expose raw tree-sitter nodes.

`TextFragmentIR`
: Immutable identifier, comment, or docstring source occurrence with exact text, source span, and syntactic owner ID.

`SourceUseIR`
: Immutable call or attribute-access occurrence with source/target spans, original target spelling, execution ownership, static `TargetResolutionIR` evidence, and separate `RuntimeTargetsIR` implementation evidence; unsupported contexts remain explicit.

`AttributeIR`
: Canonical supported Python field identified by declaring class and name, with declaration location, syntactic storage evidence, and structured declared types; repeated writes remain source occurrences.

`TypeReferenceIR`
: Structured annotation/base-expression syntax with conservative target resolution and primitive/class/other/unknown evidence, not a metric-specific target set.

`CallableIR`
: Python callable declaration evidence: declaring class, binding/decorators, abstract marker, body location, placeholder kind, and source implementation identity.

`SymbolIR`
: Language-agnostic code symbol such as a class, function, method, or value. Function-like symbols carry signatures, roles, body operations, references, `SLOC`, complexity values, and maximum control-flow nesting depth.

`ProjectIR`
: Immutable project inventory retained in `AnalysisResult.project`, with derived read-only module, symbol, attribute, source-use, and effect indexes. Source spans retain physical-file paths; unavailable inventories are `None`, distinct from successfully extracted empty facts. See the [entity contract](tree-walking.md#retained-entity-contract) for identities, ownership, availability, and supported associations.

`RuleContext`
: Query interface passed to structural rules so rules ask semantic questions, including resolved project call sites, instead of inspecting parser-native syntax.

`RuleFinding`
: Fixed-field structural finding with rule ID, severity, message, span, and subject metadata.

## Design constraints

- Source spans use one-based lines, zero-based UTF-8 byte columns, and exclusive ends after tree-sitter data leaves the parser layer.
- Supported scan targets are Python (`.py`, `.pyw`), Rust (`.rs`), JavaScript (`.js`, `.mjs`, `.cjs`), TypeScript (`.ts`), Zig (`.zig`), Haskell (`.hs`), and C++ (`.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx`).
- `ast-grep`, structural rules, and source directives are Python-only until language-specific rule sets exist.
- Parser-native data may live on parsed file artifacts for clone detection, but not in `ModuleIR`, `ProjectIR`, or structural rules.
- `ast-grep` failure is non-fatal. `scb-check` tries a global `sg` binary first, then falls back to package-managed ast-grep executables next to Python if global `sg` is missing or fails. If no ast-grep binary succeeds, `OSError`, non-zero exits, or invalid JSON return no hits.
- Source ignores and structural rules share one rule ID namespace, so `scbc ignore[...]` is never ambiguous.
- Clone and erosion findings are not suppressible. `ast-grep` and structural findings are suppressible.
- Immutable records cross module boundaries: frozen dataclasses and Pydantic models, tuples/frozensets, and privately owned read-only mappings including nested annotations and lookup indexes.
- Retained entity facts serve analysis consumers and structural rules; metric populations and aggregate calculations stay outside the IR so retaining more declarations does not silently redefine metric membership.

## Scoring-sensitive surfaces

Change these only with tests and documentation updates because they move user-visible scores:

- `SLOC` exclusions in `tree_walking/languages/python/parser.py` and `tree_walking/languages/generic.py`,
- `CLONE_NODE_TYPES`, language clone configs, and clone normalization in `analysis/clones.py` plus `tree_walking/languages/*`,
- cyclomatic and cognitive complexity node sets in `tree_walking/languages/python/parser.py` and `tree_walking/languages/*`,
- structural rule span selection and filtering in `rules/` and `pipeline.py`,
- verbosity union in `metrics/verbosity.py` and complexity mass-share logic in `metrics/erosion.py`, `metrics/cog_erosion.py`, and private `metrics/_mass.py`,
- field coverage and later-minus-earlier arithmetic in `reporting/comparison.py`.

## Extension points

- Extra `ast-grep` rules: set `SCB_CHECK_EXTRA_SLOP_RULES` to a `:`-separated list of YAML files.
- Structural rules: add a rule class in `rules/`, register it in `rules/registry.py`, and keep it on IR plus `RuleContext`.
- New CLI commands: add command wiring under `commands/` and register from `cli.py`.
- Snapshot metrics: subclass `metrics.base.Metric` with a metric-owned flat result and units, explicitly compose it in reporting, and extend comparison contracts and CLI acceptance coverage; see [Add or extend a metric](adding-a-metric.md).
