# Development

This guide summarizes the current implementation status and the preferred approach for common changes.

## Current status

`scb-check` is a Python CLI with four public commands:

- `scb-check check PATH` reports human-readable flags or JSON scores.
- `scb-check rule RULE_ID` prints bundled `ast-grep` YAML or structural rule metadata.
- `scb-check diff TREE_A TREE_B` reports before/after/signed metric deltas between directories.
- `scb-check report PATH...` creates offline HTML plots of every metric's values and adjacent changes; see [CLI options and defaults](../README.md#plot-reports).

Implemented analysis paths:

- Source discovery for supported Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++ suffixes.
- Tree-sitter parsing into language-agnostic IR, retained as immutable `AnalysisResult.project` with declaration identity, ownership, module/file membership, and nullable unavailable inventories.
- Python entity-owned identifiers, comments, and docstring literals retained once per physical file as immutable `TextFragmentIR` records; other languages declare text extraction unavailable.
- Canonical Python call/attribute-access occurrences, scoped import bindings, direct lexical/import project resolution, and explicit ambiguous/unresolved/unsupported evidence; generic languages declare source uses unavailable. See [the source-use contract](tree-walking.md#canonical-source-uses-and-imports).
- Python canonical attributes, callable declaration/body ownership, structured declared field types, and direct bases with conservative class/primitive/other/unknown resolution; generic languages expose unavailable semantic families. See [class/member facts](tree-walking.md#class-member-and-declared-type-facts).
- Bounded Python C3 member lookup connects lexical/import and declared-receiver evidence to canonical declarations and separate possible implementation sets, with explicit completeness assumptions. The [candidate input matrix](architecture.md#metric-ready-analysis-data-flow) and source-to-analysis fixtures validate the IR-first metric gate.
- Rule-facing reference/effect projections preserve existing structural decisions; metrics consume retained facts through explicit report composition.
- Parser `SLOC` accounting shared by verbosity, clone line counts, and rule spans.
- One full `pipeline.analyze()` workflow using the shared source reader and source indexes for check, diff, and report.
- Data-only grouped reports, metric-owned calculations and units, and pure nullable snapshot comparison including dotted per-language syntax counts.
- Duplicate-structure detection by normalized AST hashing for all supported languages.
- Bundled Python `ast-grep` slop patterns, plus optional local rules from `SCB_CHECK_EXTRA_SLOP_RULES`.
- Structural rules over `ProjectIR`; the current bundled Python rules are `trivial-wrapper` and opt-in `low-use-short-function`.
- Cyclomatic and cognitive erosion scores for all supported languages.
- [Partial retained-project CBO](architecture.md#coupling-between-objects-cbo), with Python-first member use, possible polymorphic targets, separate immutable partner diagnostics, measured/unavailable populations, and independent check/diff reports.
- [Direct RFC₁](architecture.md#direct-response-for-a-class-rfc₁): selected own/inherited methods plus one level of known possible method bodies, without static fallback or transitive expansion.
- [Message Passing Coupling](architecture.md#message-passing-coupling-mpc): statically selected external implemented-method call occurrences, counted once per site regardless of possible runtime overrides.
- [Distinct callers](architecture.md#distinct-callers): engineering-defined incoming callable counts from static project calls, including recursion and same-/cross-module partitions.
- [Method-level RIC](architecture.md#method-level-relative-inward-coupling-ric): all method/other-class pairs, direct static distinct using methods, raw counts and floored denominator diagnostics, partial pair mean/max ratios. Ordinary aggregates use arithmetic populations and sparse observed contributions; full Cartesian diagnostics are explicit opt-in.
- [Attribute-count DAC](architecture.md#data-abstraction-coupling-dac): canonical own fields with known outer retained-class types, not distinct types or flattened generic arguments.
- [Class Inheritance-related Coupling](architecture.md#class-inheritance-related-coupling-cic): static proper-ancestor member occurrences, including bare implemented-method references, nearest-enclosing-class source ownership, and strict transitive ancestry availability.
- [Category Ca/Ce](architecture.md#category-coupling-ca-and-ce): distinct outside client classes and distinct inside source classes with outside dependencies. Both independently consume one immutable module-category/static member-dependency projection; Ce is not outside target breadth.
- [Module-call dependencies](architecture.md#module-call-dependencies): engineering-defined distinct directional logical-module neighbors from static resolved project calls, including supported initialization and excluding self-module edges.
- These coupling metrics expose partial measured/unavailable populations, separate read-only diagnostics, and independent check/diff reports. Their project summaries are analyzer conventions without quality thresholds; [Architecture](architecture.md#partial-metric-interpretation) owns precise population, dispatch, type, and uncertainty policies.
- Python source ignores for `ast-grep` and structural rule IDs.
- Python boundary suppression for validation/normalization functions.

## Runtime contracts

- `check` exits `0` without findings and `1` with findings; `diff` and `report` exit `0` on success regardless of findings or delta signs.
- Exit `2` is for user-facing failures such as bad config, bad paths, unknown rules, invalid directives, or an empty eligible/parseable source set.
- Individual read/parse failures warn and skip within their own analysis. In `diff` and `report`, every snapshot must have at least one successfully parsed eligible file; parsed zero-SLOC files remain valid. A failure produces no partial comparison payload or HTML artifact. Report publication is atomic and preserves existing output on failure.
- Non-Python files skip Python ast-grep rules, structural rules, and source directives until language-specific rules exist.
- Config discovery and source-directive behavior are user-facing; keep README examples synchronized when they change.

## Where to make changes

| Change | Primary location |
| --- | --- |
| CLI command or option | `src/scb_check/commands/` |
| Config loading or path walking | `src/scb_check/config.py`, `src/scb_check/walker.py` |
| Source parsing, `SLOC`, directives, IR | `src/scb_check/tree_walking/`; see [Tree walking](tree-walking.md) |
| Python source uses and scoped import extraction | `src/scb_check/tree_walking/languages/python/uses.py` |
| Class/member/base extraction and annotation syntax | `src/scb_check/tree_walking/languages/python/declarations.py`, `python/types.py`; shared names and scopes in `python/uses.py` |
| Direct import/type/base-to-project resolution | `src/scb_check/tree_walking/source_uses.py`; orchestration/effect links in `semantic.py` |
| C3 member lookup and possible implementation sets | `src/scb_check/tree_walking/members.py`; receiver details in `languages/python/uses.py` |
| Language parser configs | `src/scb_check/tree_walking/languages/` |
| Clone detection | `src/scb_check/analysis/clones.py` |
| Shared source IO and parse warnings | `src/scb_check/analysis/source.py` |
| Full snapshot analysis and source indexing | `src/scb_check/pipeline.py` |
| Snapshot composition and serialization | `src/scb_check/reporting/score.py` |
| Metric contract | `src/scb_check/metrics/base.py` (`Metric`) |
| Metric calculations, fields, and units | `src/scb_check/metrics/verbosity.py`, `erosion.py`, `cog_erosion.py`, `syntax.py`, `cbo.py`, `rfc.py`, `mpc.py`, `callers.py`, `dac.py`, `cic.py`, `ric.py`, `ca.py`, `ce.py`, `module_dependencies.py`, `units.py` |
| Shared Ca/Ce policy and immutable projection | `src/scb_check/metrics/categories.py` (class-bearing module membership, static directed method/field dependencies, category availability) |
| Shared metric arithmetic | `src/scb_check/metrics/_mass.py` (erosion), `_counts.py` (measured-count sum/mean/max) |
| Report comparison and summary rendering | `src/scb_check/reporting/comparison.py` |
| Shared unit-aware text formatting | `src/scb_check/reporting/formatting.py` |
| Ordered report composition | `src/scb_check/reporting/trend.py` (`build_trend`, caller-supplied snapshot loader) |
| HTML data/table preparation and Jinja rendering | `src/scb_check/reporting/plot.py` |
| HTML layout, tables, and JSON embedding | `src/scb_check/reporting/templates/report.html.jinja` |
| Plotly charts and hover | `src/scb_check/reporting/static/plot.js` |
| Pinned Plotly distribution, license, and update procedure | `src/scb_check/reporting/static/vendor/` |
| `ast-grep` integration | `src/scb_check/analysis/astgrep.py` and `src/scb_check/resources/slop_rules/` |
| Structural rule behavior | `src/scb_check/rules/` |
| JSON scores or human rendering | `src/scb_check/reporting/` |
| Shared `AnalysisResult`, finding records, and report mapping aliases | `src/scb_check/models.py` |

## Extending retained entity facts

1. Keep facts in `ModuleIR` / `SymbolIR` and expose them through `AnalysisResult.project`; use the [entity contract](tree-walking.md#retained-entity-contract) for identity, membership, availability, and association semantics.
2. Update the producing parser and document its supported subset in the [availability contract](tree-walking.md#fact-availability-and-parser-support). Use `None` for unavailable inventories and empty tuples for successful extraction with no facts; preserve this distinction through resolution and projections. Keep parser-native nodes and source IO outside the IR, and metric populations/calculations in their existing layers. Text facts follow the [source-fragment ownership policy](tree-walking.md#source-text-fragments); reuse already-read/parser source, retain original spelling once, and leave document assembly and model preprocessing to consumers.
3. Test real-source behavior through `analyze` / `analyze_files`, including immutable nested views, empty/unavailable facts, exact lexical parents, and repeatable IDs. Preserve same-file metric selection while retaining every declaration.
4. Check numerical parity on unaffected fixtures. For cross-file function collisions and conditional Python declarations, test the corrected counts/masses/findings explicitly, including independent check/diff parity.

### Extending source-use facts

1. Follow the [canonical inventory contract](tree-walking.md#canonical-source-uses-and-imports): retain each occurrence once in `ModuleIR.source_uses`, derive indexes/projections, and keep imports separate. Preserve immutable records, stable snapshot IDs, byte spans, repeated sites, and recursion.
2. Assign execution ownership independently of text ownership. Add explicit unsupported-context records where ownership/evaluation is not modeled; an available inventory describes only the documented subset, not full Python semantics.
3. Keep direct lexical/import evidence in extraction/resolution. Leave ambiguous bindings and dynamic receivers explicit; external status needs import/builtin evidence, not dotted spelling. Bounded member/declared-receiver resolution belongs in `members.py`, separately from lexical/import extraction and from rule-specific effects; preserve [runtime-target uncertainty](tree-walking.md#member-resolution-and-runtime-targets).
4. Preserve rule compatibility: textual nested-call projections, parameter/builtin exclusions, rule-specific self-recursion exclusion, shallow effects with `source_use_id`, and dotted keep-policy are distinct from canonical resolution. Verify unchanged structural findings and verbosity/erosion scores.
5. Test exported `analyze` / `analyze_files` facts for module/class/default execution, nested bodies/expressions/control flow, repeated and recursive calls, attribute access modes, aliases/scopes/relative imports, project collisions, dynamic targets, unsupported contexts, empty/unavailable inventories, and read-only indexes. Stub `scb_check.pipeline.run_sg`; assert facts rather than traversal order. Retain standalone-check/independent-diff parity and existing report/exit contracts.
6. Keep site/caller/target populations and metric formulas in consumers. Update the canonical contract and parser-support table when support changes, rather than adding metric-specific IR fields or a second call inventory.

### Extending class/member facts

1. Follow the [class/member contract](tree-walking.md#class-member-and-declared-type-facts). Keep fields in `ModuleIR.attributes`, callable/base facts on the owning symbol, and indexes derived from these inventories. Extend Python extraction using shared lexical evidence rather than building another name resolver.
2. Preserve field identities across repeated writes. Link supported write targets to their canonical field; retain annotation occurrences and structured wrappers/arguments without inferring types from initializers. Keep syntax evidence distinct from runtime storage and metric inclusion.
3. Retain uncertainty for dynamic fields, unknown annotations, decorators, and base expressions. Resolve known retained classes conservatively; inheritance/member resolution must associate existing declarations/bodies rather than copying them into subclasses.
4. Test source-to-`analyze_files(...).project` behavior for repeated fields, self/forward/unresolved types, locals versus attributes, direct bases, abstract/placeholder bodies, nested declarations, unsupported syntax, empty/unavailable families, and frozen views. Keep scoring/check/diff compatibility coverage unchanged.
5. Extend the member resolver through the same seam: verify C3/overrides, static declarations versus possible body sets, receiver annotation scope/rebinding, and uncertainty. Reuse canonical IDs and derived read-only owner/member/target views; update the candidate input fixture/matrix rather than introducing metric-specific inventories or scores.

## Adding an `ast-grep` rule

1. Add or update YAML under `src/scb_check/resources/slop_rules/`.
2. Use a unique rule ID across both `ast-grep` and structural rules.
3. Set severity and any `min_file_count` metadata deliberately.
4. Add behavioral tests that exercise `pipeline.run_sg` through monkeypatching rather than invoking `sg`.
5. Update README or docs if the rule changes user-facing behavior or scoring expectations.

## Adding a structural rule

1. Add a rule class under `src/scb_check/rules/`.
2. Keep rule metadata immutable: `id`, `severity`, `languages`, `target`, and `description`.
3. Operate on `SymbolIR` or another typed IR subject plus `RuleContext`; do not inspect tree-sitter nodes.
4. Register the rule in `rules/registry.py`.
5. Ensure the rule ID does not collide with bundled `ast-grep` rule IDs.
6. Test observable findings, ignore behavior, report fields, and rendering prefixes.

## Adding a language

1. Add the tree-sitter grammar dependency.
2. Add a `Language` enum value, parser module/config under `tree_walking/languages/`, dispatch suffix mapping, and discovery coverage.
3. Add clone node/literal/identifier config so `analysis/clones.py` can hash duplicate blocks.
4. Add behavioral parser, clone, and pipeline tests.
5. Document whether ast-grep rules, directives, and structural rules apply to the language.

## Changing scoring

Treat scoring changes as public behavior changes. Update tests first, then implementation, then docs.

Pay special attention to:

- `verbosity` as a union, never a sum,
- `SLOC` as the denominator for verbosity and the source of counted flagged lines,
- non-Python verbosity currently includes clone LOC but not Python ast-grep or structural rule LOC,
- high-complexity threshold `> 10`,
- mass formulas for `erosion` and `cog_erosion`,
- line spans used by clone, `ast-grep`, and structural findings.

## Adding or extending a metric

1. Add behavioral acceptance expectations through the Typer CLI for known scores and supporting values. Keep the [README schema reference](../README.md#check-json-report-fields) synchronized.
2. Put a small metric class in its own `metrics/` module, subclassing `metrics.base.Metric` with its `compute()` input types (for example, `Syntax` uses `Metric[[tuple[LanguageSyntaxSummary, ...]]]`). Implement instance `compute()` and declare class-level `units`. Pass only the extracted facts it needs; keep parser traversal and complexity extraction in tree walking. Reuse private `metrics/_mass.py` arithmetic for the erosion variants and `metrics/_counts.py`'s `summarize_counts` for measured-count aggregates. Concrete metrics still select populations and own fields and units.
3. Return a read-only flat `MetricResult` of `int | float | None`. Own field names and units in the metric, including dynamic syntax fields. Return defined-but-unavailable fields as `None`; preserve existing zero-denominator results and let calculation errors surface.
4. Explicitly compose the metric in `reporting.score.compute_report(AnalysisResult)` and associate its group with metric-owned units. Keep both mapping levels read-only. Use `serialize_report` for contract validation and fresh plain dictionaries; keep metadata outside numerical results.
5. For class/callable/module metrics, preserve the [partial/unavailable distinction](architecture.md#partial-metric-interpretation), explicit extraction gates, and narrow immutable inputs. Reuse retained member selections, source occurrences, and declared types rather than adding a resolver. Test known-value source cases: RFC₁ one-hop/inherited/bodyless methods; MPC repeated/loop sites and implementation ownership; callers recursion, initialization exclusion, and module partition reconciliation; DAC repeated field types, wrappers, and unknown annotations; Ca per-category client deduplication; Ce saturation per internal source class; shared category membership, static dependency policy, partial zeros, and unavailable internal extraction; module-call neighbors repeated/cyclic/self edges, physical-file mapping, supported initialization, and unavailable targets; CIC proper ancestors, repeated sites, call/target-access deduplication, static overrides, inherited-body ownership, and unresolved ancestry availability; RIC all-pair zeros, raw zero-owner use versus the denominator floor, repeated callers, canonical ownership, and unavailable endpoints. For RIC aggregate changes, compare against full diagnostics and preserve the zero-call allocation/work regression without timing thresholds. Keep structured diagnostics outside numerical results. Document counting variants and citations without quality thresholds.
6. Update required-field/group validation and comparison coverage for the schema. Use flat numerical fields, not nested result objects. Add no registry, report class, or placeholder configuration; constructors are for real configuration requirements.

Keep `metrics/` independent of reporting and source IO. See the [ownership and interface explanation](architecture.md#report-comparison-interface).

## Extending snapshot comparisons

1. Extend the snapshot metric contract through the steps above.
2. Keep `compare_reports(before, after)` pure and returning a read-only `Report`. Require defined groups and fields; zero-fill only absent dotted per-language syntax fields, without changing snapshots. Propagate explicit `None` rather than treating it as zero.
3. Keep `compute_diff_report(earlier_analysis, later_analysis)` returning an ordinary `before` / `after` / `diff` dictionary. Use the standalone snapshot builder on both analyses. Tree paths belong in command output, not metric results.
4. Add CLI coverage in `tests/test_diff_cli.py`: standalone-check parity plus independently known positive, negative, and zero differences, argument reversal, language additions/removals, exits, and stderr. Cover read-only behavior, fresh serialization, null propagation, and malformed report contracts at the public reporting seam where real-source CLI fixtures cannot produce them.
5. Check observable unit formatting: fractional JSON scores and differences, human percentages and percentage points, count/mass units, explicit unavailable values, and visible zero differences. Retain location-level human check findings.

`diff` runs two independent full analyses with one configuration and equal options. Preserve walker exclusions and independent parse-failure handling, without file pairing or source rereading. Monkeypatch `scb_check.pipeline.run_sg` for controlled tooling output. This reporting contract does not implement churn or a quality gate.

## Extending ordered HTML reporting

Keep path/config validation, analysis, and atomic output IO in `commands/report.py`. `build_trend` consumes ordered paths and a loader returning ordinary reports; it preserves repetitions and delegates adjacent differences to `compare_reports`. Shared presentation contracts are immutable `Trend` and `TrendSeries` in `models.py`. Retain numerical snapshots for hover context rather than analysis IRs. Add fields through existing `compute_report` / `REPORT_UNITS` composition, not a plotting registry or renderer-side measurement calculation.

Use `tests/test_report_cli.py` for known-source standalone-check/diff parity, shared configuration/flags, unusable inputs, exit codes, and atomic publication failures. Use `tests/reporting/test_trend.py` and `test_plot.py` for complete field coverage, nullable deltas, units, safe embedded JSON, and accessible table contracts. Both value and adjacent-change plots are always included. Assert meaning rather than full-document layouts or call order.

For browser acceptance, run `tests/reporting/report_browser_smoke.py` with Chromium installed in a pinned, isolated Playwright tool environment. Verify real hover details, escaped labels, null gaps, isolated/zero/negative points, unclipped labels at narrow/wide widths, resizing, offline/no-network operation, and readable tables with JavaScript disabled. Keep browser tooling out of runtime dependencies.

After runtime dependency changes, regenerate `uv.lock` and both [exported requirements locks](../README.md#install). Build wheel and sdist with `uv build`; inspect them for the Jinja template, chart adapter, and vendor asset/license/provenance files. Install the wheel in a clean environment, leave the checkout, and generate a report with `--disable-sg` to verify packaged asset loading is independent of cwd. When updating Plotly, follow the vendor provenance/update instructions and repeat packaging and offline browser checks.

## Verification

Run the project workflow after changes:

```bash
uv run ruff check --fix .
uv run ty check .
uv run pytest
uv run scb-check check .
uv run vulture
```

Use focused tests while iterating, then run the full workflow before presenting results. Keep tests behavioral: assert scores, exit codes, report fields, and rendering prefixes instead of internal call order.
