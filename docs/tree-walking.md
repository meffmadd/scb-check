# Tree walking

Tree walking turns already-read supported source into language-agnostic facts that scoring, structural rules, and reporting can share. It lives in `src/scb_check/tree_walking/`.

## Boundaries

`tree_walking/` does not discover files or read from disk. `pipeline.analyze()` calls `analysis.source.read_and_parse_source()` directly, which reads newline-normalized text and calls `parse_source_file(path, source)`. Both commands use this full analysis workflow: once for check, independently for each diff snapshot. Successful files feed source indexes for rendering, syntax counts, and Python directives; read/parse failures warn and skip within their own analysis.

`ParsedFile` intentionally has two sides:

- `module`: pure `ModuleIR` for downstream scoring and rules.
- `native_tree`: parser-native data kept only for clone detection.

Do not put raw tree-sitter nodes into `ModuleIR`, `SymbolIR`, `OperationIR`, `ValueIR`, `EffectIR`, or `RuleFinding`.

## Parse flow

```text
`pipeline.analyze()`
    │
    ▼
`analysis.source.read_and_parse_source()`
    │
    ▼
`dispatch.parse_source_file(path, source)`
    │
    ├─ choose candidate languages from the file suffix
    ├─ apply optional language filters
    └─ try parsers in order
            │
            ▼
`PythonParser.parse()` or `GenericTreeSitterParser.parse()`
    │
    ├─ parse with the language tree-sitter grammar
    ├─ compute `SLOC` lines
    ├─ walk symbols and complexity facts
    └─ return `ParsedFile(source, ModuleIR, native_tree)`
```

A parser raises `LanguageParseError` when it cannot parse source for its own language. Dispatch wraps parser failures in `ProjectParseError`, which the shared reader logs as a warning before skipping that file.

The default dispatch table knows Python (`.py`, `.pyw`), Rust (`.rs`), JavaScript (`.js`, `.mjs`, `.cjs`), TypeScript (`.ts`), Zig (`.zig`), Haskell (`.hs`), and C++ (`.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx`). CLI discovery supplies those supported suffixes.

## `SLOC`

`SLOC` is computed once by the parser and reused for scoring, clone line counts, and rule spans. Snapshot comparisons use the resulting ordinary report measurements.

The Python parser:

1. tokenizes source with `tokenize.generate_tokens`,
2. keeps lines with real tokens,
3. drops comments, blanks, indentation-only tokens, and newline-only tokens,
4. removes standalone non-byte, non-f-string string expression statements when the literal owns the full line span.

This is why docstrings do not count as `SLOC`, but meaningful string expressions can still count when they are not plain standalone docstrings.

The generic Tree-sitter parser used for Rust, JavaScript, TypeScript, Zig, Haskell, and C++ starts from non-blank lines, removes comment-only lines from grammar comment nodes including language doc comments such as Haskell `haddock` nodes, and drops punctuation-only delimiter lines such as standalone braces.

## Python walking

`PythonWalker` walks tree-sitter nodes into `ModuleIR`:

- module names come from the path and package `__init__.py` chain,
- spans use one-based lines, zero-based UTF-8 byte columns, and exclusive ends,
- root-level imports become `ImportIR` records,
- classes and functions become `SymbolIR` records,
- declarations beneath control-flow wrappers are visited once with their lexical owner,
- nested classes/functions keep their descriptive `owner_qualified_name` and exact `owner_id`,
- module references are aggregated from symbol call references.

Function-like symbols carry:

- `SignatureIR` with parameter names, annotations, and return annotation text,
- body `OperationIR` records for top-level executable body statements,
- call `ReferenceIR` records resolved through imports when possible, including the control-flow nesting depth of each call,
- `SymbolRole` facts for keep reasons,
- `SLOC`, cyclomatic complexity, cognitive complexity, and maximum control-flow nesting depth.

The walker only normalizes the facts current rules need. Unknown or unsupported syntax should become `OperationKind.UNKNOWN` or `ValueKind.UNKNOWN`, not parser-native leakage.

## Generic multi-language walking

Rust, JavaScript, TypeScript, Zig, Haskell, and C++ use `GenericTreeSitterParser` with one config per language under `tree_walking/languages/`. The generic parser intentionally emits the minimum IR needed for clone detection and erosion scoring:

- module language, file, span, and `SLOC` lines,
- class-like symbols where the grammar exposes them,
- function and method symbols, including JavaScript and TypeScript generator functions, with names, owners, signatures, spans, `SLOC`, cyclomatic complexity, and cognitive complexity,
- parser-native trees retained on `ParsedFile` for clone hashing and syntax node counts.

It does not yet emit imports, references, body operations, value summaries, or source directives for non-Python languages. Structural rules therefore remain Python-only until they have language-specific semantic facts.

## Operations and values

Body operations are a shallow summary of executable body statements:

- `return`, branch, loop, and `raise` statements map to their matching `OperationKind`,
- expression statements wrapping assignments or calls map to `ASSIGN` or `CALL`,
- anything else maps to `UNKNOWN`.

Return and call operations also carry a `ValueIR`. Values are normalized as invocations, symbol references, member accesses, literals, collections, operators, or `UNKNOWN`. Invocation arguments are recursively normalized so semantic analysis can reason about forwarded parameters and call effects.

## Roles and keep reasons

The parser assigns conservative `SymbolRole` facts:

- dunder methods are `CONTRACT_MEMBER`,
- decorated functions are `CONTRACT_MEMBER`, except `@property`-style decorators become `COMPUTED_ATTRIBUTE`,
- methods on classes with base names are `INHERITED_OVERRIDE`,
- single-return functions that return a parameter with a literal, collection, or uppercase constant default are `FACTORY` value providers.

Structural rules do not inspect decorators, base-class syntax, or Python nodes directly. They ask `RuleContext` questions such as `is_required_api_surface()`.

## Source directives

Source directives are part of tree walking, but they are parsed separately from `PythonWalker` because they need the full source map and the shared rule namespace.

`directives.py` scans Python comment tokens with `tokenize`; it does not raw-search text. Non-Python files are skipped by directive filtering. It parses:

- `# scbc ignore[rule-id]`, which applies to the same line when it follows code, or to the next non-blank, non-comment code line when standalone,
- `# scbc boundary`, which records the directive line.

The full analysis workflow in `pipeline.py` validates ignore rule IDs against the combined `ast-grep` and structural rule ID namespace. It maps boundary directives to containing function spans before filtering `ast-grep` findings. Both diff snapshots receive ordinary check directive handling, including `--include-all` suppression bypasses.

## Retained entity contract

`AnalysisResult.project` retains the `ProjectIR` built by `build_project()` for ordinary checks and each independent diff analysis. This is an internal interface without a public compatibility promise. The authoritative inventory is `ProjectIR.modules`, with each module's `symbols` tuple; indexes are derived read-only views over those records.

| Lookup | Contents |
| --- | --- |
| `modules_by_id` | Logical module ID → `ModuleIR` |
| `modules_by_file` | Physical path → its one successfully parsed logical module |
| `files_by_id` | Physical-file ID → physical path |
| `symbols_by_id` | Declaration ID → every `SymbolIR`, including repeated names |
| `symbols_by_qualified_name` | Qualified name → last declaration selected for existing semantic queries; not a complete inventory |
| `effects_by_symbol` | Declaration ID → derived `EffectIR` tuple |

Access all declarations in a physical file through `project.modules_by_file[path].symbols`. Constructing an `AnalysisResult` requires an explicit `project`; synthetic empty analyses can supply `ProjectIR()`.

Records are frozen. Indexes, signature annotation mappings, and `AnalysisResult.source_lines_by_file` are read-only, privately owned mappings; nested sequences are tuples or frozensets. Parser-native trees and source IO remain outside the IR. `analyze_files()` resolves and deduplicates physical paths before parsing; files that fail extraction have no module record. An explicit empty file set yields an empty project; CLI discovery/usable-input validation still rejects unusable trees.

### Identity, membership, and spans

Physical-file IDs use normalized absolute paths. Logical-module and declaration IDs add entity kind and declaration span to physical-file identity. They are deterministic for identical inputs at the same location, independent of input order, and do not use qualified names or hashes. IDs do not track moves, renames, or relocation between snapshots.

A `ModuleIR` exposes `id`, `file_id`, `kind`, `language`, `name`, `qualified_name`, and its whole-source `span`. A `SymbolIR` exposes those facts plus `module_id` and `owner_id`. Its existing `name` is the display name. Physical files remain paths, addressed by `file_id`, rather than a second semantic entity hierarchy. There is exactly one logical module per parsed physical file; no package aggregation or multi-file module merging occurs.

Python module names use the contiguous parent directory chain containing `__init__.py`, followed by the file stem. An `__init__.py` names that package itself (falling back to its parent directory name when no package chain exists). For example, `pkg/__init__.py` maps to `pkg`, `pkg/sub/__init__.py` to `pkg.sub`, and `pkg/sub/util.py` to `pkg.sub.util`. Files outside that chain use only their stem; unrelated directories can therefore produce identical module/qualified names. Namespace packages are not aggregated.

Top-level declarations have the logical module's `owner_id`. Nested declarations have their enclosing declaration's ID, even beneath `if`, `try`, loops, `with`, or `match`. This is syntax traversal, not condition evaluation. Class methods are distinct from functions nested inside methods. Generic parser owner contexts without a corresponding lexical declaration retain `owner_qualified_name` and `owner_id=None`; no owner entity is invented. In particular, generic Rust `impl` contexts do not resolve their named type to a separate class declaration.

All `SourceSpan` lines are one-based, columns are zero-based UTF-8 bytes, and ends are exclusive. Whole-module spans include trailing newlines (ending at column zero on the next line). Definition spans begin at the declaration, not its decorators/comments.

### Fact-family coverage

`ModuleIR.coverage` is a frozen, parser-declared `FactCoverage`. Each field is `complete`, `partial`, or `unavailable`, defaulting conservatively to `unavailable`. Status describes extraction support, not the number of extracted facts: successful empty extraction is distinct from unavailable extraction. `complete` means the documented supported subset, not full language semantics.

| Fact family | Python | Generic languages | Producer / supported subset |
| --- | --- | --- | --- |
| `entities` | complete | partial | Parser: named class/function declarations (Python includes async/decorated/nested/conditional definitions; not lambdas); generic grammar-configured symbols |
| `signatures` | partial | partial | Parser: parameter names and Python annotation text, not full type semantics |
| `complexity` | complete | complete | Parser: configured cyclomatic/cognitive syntax counts; Python also supplies maximum nesting |
| `sloc` | complete | complete | Parser: documented language-specific SLOC exclusions |
| `imports` | partial | unavailable | Python parser: root-level import bindings |
| `references` | partial | unavailable | Python parser: existing symbol call references and import-based name expansion |
| `operations` | partial | unavailable | Python parser: shallow executable body summaries and supported values |
| `roles` | partial | unavailable | Python parser: conservative semantic keep reasons |
| `effects` | partial | unavailable | `build_project()`: effects derived from supported operations/values |

No per-entity completeness, automatic completeness analysis, or project coverage summary is implied. Call/reference extraction and execution ownership retain their existing limitations; declaration discovery does not add module-level references or a new resolver.

### Counting and associations

Every declaration survives in `symbols_by_id`, including Python overloads, repeated definitions, and property accessors. Import aliases remain bindings, not duplicate target entities. Python metric populations select the last record per `(physical file, existing qualified name)`, preserving same-file collision behavior while preventing cross-file name overwrites. Generic-language collisions still receive the existing source/span name suffix so their metric populations retain overloads and duplicate basenames.

The generic C++ frontend extracts function definitions, not standalone prototypes, so a prototype plus its definition does not create two counted functions. There is no general declaration/body resolver, property/overload-family grouping, `.pyi` discovery, or stub/implementation matching. Unsupported associations remain unassociated, not fabricated entities.

## Semantic context

`build_project()` derives effects from the retained modules and supplies `RuleContext` for structural rules. Each declaration retains its own ID-keyed effects, while `RuleContext` preserves last-qualified-name effect selection for existing rule decisions, including same-file redefinitions. Retaining more facts alone does not change those decisions. Entity lookup consumers use IDs for identity; existing name-based semantic queries remain limited and are not a canonical cross-file reference resolver.

Effects are derived from normalized operations and values. Invocation values become `PROJECT_CALL`, `EXTERNAL_CALL`, or `UNRESOLVED_CALL`; symbol and member values become `READ`; raise operations become `RAISE`.

`RuleContext` is the structural-rule API over `ProjectIR`. It exposes derived effects and resolved project call sites for rules such as `low-use-short-function`, which estimates whether inlining a short helper would stay within caller SLOC, complexity, cognitive complexity, and nesting budgets. Add a query there when a rule needs a new semantic question, rather than teaching the rule Python syntax.

## Extension rules

- Keep file IO at boundaries; parsers accept `Path` plus already-read source text.
- Keep IR pure and immutable; pass tuples across module boundaries.
- Add parser-native data only to `ParsedFile`, and only when an analysis helper needs it.
- Add enum members or IR fields only when at least one real rule or scoring path needs them.
- When adding syntax support, update parser tests, semantic tests, and any affected scoring docs.
- When adding a new language, add a parser config/module, dispatch mapping, `Language` value, discovery support, clone config, tests, and docs deliberately; do not make Python-specific assumptions in structural rules.
