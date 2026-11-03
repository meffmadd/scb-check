# Tree walking

Tree walking turns already-read supported source into language-agnostic facts that scoring, structural rules, and reporting can share. It lives in `src/scb_check/tree_walking/`.

## Boundaries

`tree_walking/` does not discover files or read from disk. `pipeline.analyze()` calls `analysis.source.read_and_parse_source()` directly, which reads newline-normalized text and calls `parse_source_file(path, source)`. Both commands use this full analysis workflow: once for check, independently for each diff snapshot. Successful files feed source indexes for rendering, syntax counts, and Python directives; read/parse failures warn and skip within their own analysis.

`ParsedFile` intentionally has two sides:

- `module`: pure `ModuleIR` for downstream scoring and rules.
- `native_tree`: parser-native data kept only for clone detection.

Parser-native nodes (including Python AST nodes) stay outside all IR records, including class/member and declared-type facts.

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
- imports in retained lexical scopes become separate `ImportIR` bindings,
- calls and attribute accesses become module-owned `SourceUseIR` occurrences,
- classes and functions become `SymbolIR` records, with direct-base and callable declaration facts,
- supported class/receiver assignments become canonical `AttributeIR` records and linked write occurrences,
- declarations beneath control-flow wrappers are visited once with their lexical owner,
- nested classes/functions keep their descriptive `owner_qualified_name` and exact `owner_id`,
- rule-facing symbol references are projected from source uses (not a second authoritative inventory),
- identifiers, comments, and docstring literals become entity-owned `TextFragmentIR` occurrences.

Function-like symbols carry:

- `SignatureIR` with parameter names, annotations, and return annotation text,
- body `OperationIR` records for top-level executable body statements,
- compatibility `ReferenceIR` call projections with textual containment, root-import name expansion, and control-flow nesting for existing rules,
- `SymbolRole` facts for keep reasons,
- `SLOC`, cyclomatic complexity, cognitive complexity, and maximum control-flow nesting depth.

The walker only normalizes the facts current rules need. Unknown or unsupported syntax should become `OperationKind.UNKNOWN` or `ValueKind.UNKNOWN`, not parser-native leakage.

## Generic multi-language walking

Rust, JavaScript, TypeScript, Zig, Haskell, and C++ use `GenericTreeSitterParser` with one config per language under `tree_walking/languages/`. The generic parser intentionally emits the minimum IR needed for clone detection and erosion scoring:

- module language, file, span, and `SLOC` lines,
- class-like symbols where the grammar exposes them,
- function and method symbols, including JavaScript and TypeScript generator functions, with names, owners, signatures, spans, `SLOC`, cyclomatic complexity, and cognitive complexity,
- parser-native trees retained on `ParsedFile` for clone hashing and syntax node counts.

It does not yet emit text fragments, source uses, imports, class/member/type semantics, references, body operations, value summaries, or source directives for non-Python languages. Structural rules therefore remain Python-only until they have language-specific semantic facts.

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
| `symbols_by_id` | Declaration ID → every `SymbolIR`, including repeated names |
| `symbols_by_qualified_name` | Qualified name → last declaration selected for existing semantic queries; not a complete inventory |
| `effects_by_symbol` | Callable declaration ID → derived `EffectIR` tuple, or `None` when body extraction is unavailable |
| `source_uses_by_id` | Occurrence ID → canonical `SourceUseIR`, including unsupported contexts |
| `attributes_by_id` | Field ID → canonical `AttributeIR` from available module inventories |

Access all declarations in a physical file through `project.modules_by_file[path].symbols`; source paths are available on module/entity spans without a separate physical-file index. Constructing an `AnalysisResult` requires an explicit `project`; synthetic empty analyses can supply `ProjectIR()`. The source-use index includes occurrences only from available inventories; an empty index alone does not establish extraction support.

Records are frozen. Indexes, signature annotation mappings, and `AnalysisResult.source_lines_by_file` are read-only, privately owned mappings; nested sequences are tuples or frozensets. Parser-native trees and source IO remain outside the IR. `analyze_files()` resolves and deduplicates physical paths before parsing; files that fail extraction have no module record. An explicit empty file set yields an empty project; CLI discovery/usable-input validation still rejects unusable trees.

### Identity, membership, and spans

Physical-file IDs use normalized absolute paths. Logical-module and declaration IDs add entity kind and declaration span to physical-file identity. They are deterministic for identical inputs at the same location, independent of input order, and do not use qualified names or hashes. IDs do not track moves, renames, or relocation between snapshots.

A `ModuleIR` exposes `id`, `file_id`, `kind`, `language`, `name`, `qualified_name`, and its whole-source `span`. A `SymbolIR` exposes those facts plus `module_id` and `owner_id`. Its existing `name` is the display name. Physical files remain paths, addressed by `file_id`, rather than a second semantic entity hierarchy. There is exactly one logical module per parsed physical file; no package aggregation or multi-file module merging occurs.

Python module names use the contiguous parent directory chain containing `__init__.py`, followed by the file stem. An `__init__.py` names that package itself (falling back to its parent directory name when no package chain exists). For example, `pkg/__init__.py` maps to `pkg`, `pkg/sub/__init__.py` to `pkg.sub`, and `pkg/sub/util.py` to `pkg.sub.util`. Files outside that chain use only their stem; unrelated directories can therefore produce identical module/qualified names. Namespace packages are not aggregated.

Top-level declarations have the logical module's `owner_id`. Nested declarations have their enclosing declaration's ID, even beneath `if`, `try`, loops, `with`, or `match`. This is syntax traversal, not condition evaluation. Class methods are distinct from functions nested inside methods. Generic parser owner contexts without a corresponding lexical declaration retain `owner_qualified_name` and `owner_id=None`; no owner entity is invented. In particular, generic Rust `impl` contexts do not resolve their named type to a separate class declaration.

All `SourceSpan` lines are one-based, columns are zero-based UTF-8 bytes, and ends are exclusive. Whole-module spans include trailing newlines (ending at column zero on the next line). Definition spans begin at the declaration, not its decorators/comments.

### Source text fragments

`project.modules_by_file[path].text_fragments` is the sole physical-file inventory of `TextFragmentIR` occurrences. Each frozen record contains:

| Field | Meaning |
| --- | --- |
| `text` | Exact source spelling, including comment markers, literal prefixes, quotes, escapes, and internal newlines |
| `kind` | `identifier`, `comment`, or `docstring` |
| `span` | Physical source occurrence; `span.file_id` associates it with the module's physical file |
| `owner_id` | Syntactic owning module or declaration ID, not a resolved referent or execution scope |

The Python producer reuses the already-parsed tree and its source bytes. It retains every grammar identifier occurrence (declarations, parameters, imports, attributes, annotations, expression identifiers), every grammar comment, and initial plain string expressions in module/class/function bodies. Comments before the first statement do not prevent docstring recognition. Parenthesized docstrings are supported; implicitly concatenated docstrings emit one fragment per constituent literal, with any intervening comments retained separately. Byte strings, f-strings, ordinary string literals, and later standalone string statements are not docstrings. Identifiers inside f-string expressions remain eligible. This extraction is independent of `SLOC` exclusions.

Ownership follows parser syntax containment, with these attribution rules:

- A class/function owns its declaration name, signature/defaults/bases, body text, and decorators, including comments inside its decorated-definition wrapper. Definition spans themselves still exclude decorators.
- Nested declarations own their own fragments; those fragments are not copied to any ancestor. Repeated names still have distinct owning IDs.
- Leading standalone comments before a declaration/decorator stay with the enclosing entity, rather than attaching speculatively to the following declaration. Header/inline/body comments follow their containing syntax node; comments after a dedent belong to the enclosing entity. Blank lines do not change ownership.
- Control-flow wrappers, lambdas, and comprehensions do not introduce retained entities; their text belongs to the nearest enclosing retained declaration or module. This is syntactic ownership, not runtime name binding.

Spans use the shared one-based lines, zero-based UTF-8 byte columns, and exclusive ends. Multiline text includes its internal newlines; the final column counts bytes only on its last line. Text is exact relative to the reader's newline-normalized source, not raw on-disk line endings. A source occurrence appears once in the inventory; its span distinguishes repeated spellings, including same-line statements.

Consumers can select direct fragments by `owner_id`, or include child owners transitively through `SymbolIR.owner_id`, filtering the physical-file inventory once. File documents can select the whole tuple. Document assembly and child inclusion policy belong to consumers, not to the IR; see [the architectural boundary](architecture.md#text-evidence-boundary).

### Canonical source uses and imports

`ModuleIR.source_uses` is the sole inventory of executable call and attribute-access occurrences. `languages/python_uses.py` produces it from the already-parsed tree; `source_uses.resolve_project_references()` refines import evidence against retained modules/declarations during `build_project()`. `AnalysisResult.project` exposes the resolved modules and the derived read-only `source_uses_by_id` index. These are frozen records with tuple-valued candidates, not parser nodes or mutable resolver state.

| `SourceUseIR` field | Meaning |
| --- | --- |
| `kind` | `call`, `attribute-read`, `attribute-write`, `attribute-read-write` (augmented assignment), or `attribute-delete` |
| `span` / `target_span` | Whole occurrence / target expression; a call includes arguments in `span`, but not in `target_span` |
| `target_spelling` / `target_form` | Original target text and `name`, `attribute`, or `expression` form |
| `owner_id` / `execution_kind` | Executing module, class initialization, or function; unsupported contexts have no owner and kind `unsupported` |
| `unsupported_context` | Explicit unsupported syntax context, otherwise `None` |
| `declared_attribute_id` | Canonical field for a supported direct assignment/augmented-write target, otherwise `None`; not receiver inference |
| `resolution` | Immutable `TargetResolutionIR` static binding evidence |
| `nesting` | Syntactic control-flow depth, not an execution count |

Occurrence IDs combine normalized physical-file identity, use kind, and whole-occurrence span. They are repeatable for identical source at the same location, independent of target resolution, not persistent identities across edits or snapshots. Import IDs use physical-file identity, `import`, and the individual alias span. All spans follow the shared one-based-line, zero-based UTF-8-byte-column, exclusive-end contract. Repeated calls and recursion remain separate occurrences. A method invocation has both a call occurrence and an attribute-read occurrence; chained attributes likewise retain their individual accesses. These are different fact kinds, not duplicate calls.

#### Execution ownership and supported syntax

Calls and accesses are retained through branches, loops, `try`, `with`, `match`, and nested expressions, including module and class initialization. A nested function body belongs only to that function. Decorators, function defaults, class bases, and other definition-header expressions belong to the enclosing execution context, not the declaration they introduce. This differs deliberately from [text-fragment ownership](#source-text-fragments), where the declaration owns its header text.

Lambda bodies, comprehensions/generator expressions, type aliases, type-parameter headers, and annotation contexts do not receive a guessed execution owner. Their retained calls/accesses have `owner_id=None`, `execution_kind="unsupported"`, and unsupported resolution with a context reason. Lambda defaults remain in the enclosing execution context. No retained lambda/comprehension entity is invented. Annotation evaluation is unsupported because Python version and future imports affect its execution semantics. Annotation-only attribute targets are not reads/writes of the final attribute; receiver evaluations are retained. Pattern attribute lookups and `with` attribute-binding targets retain their access modes.

#### Import bindings and direct resolution

`ModuleIR.imports` is a separate relation, not a set of call sites or target entities. Each `ImportIR` contains `local_name`, `qualified_name`, its alias `span`, and lexical `owner_id`. Module, class, and function scopes retain imports, including bindings under control-flow wrappers. `import pkg.member` binds the root `pkg`; aliases and `from` imports bind their local names. Relative imports expand against the parser's package/module name when possible; unexpandable relative imports and star imports carry unsupported resolution evidence when used.

`TargetResolutionIR` exposes `status`, optional `target_id` and `qualified_name`, tuple `candidate_ids`, and an explicit `reason`:

- `project`: a direct lexical declaration or a unique imported module/declaration in the retained snapshot.
- `external`: import or builtin evidence outside the retained snapshot, not a dotted spelling heuristic or proof that a dependency is installed. An imported member missing from a retained module is instead unresolved.
- `ambiguous`: competing lexical bindings or multiple retained import targets; alternatives stay on one occurrence, with known candidate IDs rather than duplicated sites.
- `unresolved`: no direct binding, parameter/local binding, dynamic target, or a receiver requiring member resolution.
- `unsupported`: unsupported execution syntax, type-parameter bindings, star/unexpandable relative imports, or `global`/`nonlocal` scope directives.

Bindings are collected lexically without evaluating control flow or statement order. Repeated declarations/rebindings can therefore be ambiguous rather than selecting a runtime winner. Function parameters (including typed variadics) and local bindings shadow outer names, including bindings in lambda defaults, comprehensions, and type aliases. Method/nested-class lookup skips the runtime class namespace as a closure scope; type-parameter bindings remain explicitly unsupported. Parenthesized direct targets resolve without dropping their original spelling. Import-qualified names match module-accessible declarations, not declarations nested inside function bodies; collisions remain ambiguous. Rebuilding a project reconsiders import resolution against its current modules. Instance/class member lookup, assignment-alias propagation, type inference, runtime dispatch, and possible-runtime-target sets are not provided. In particular, `self.method()` and arbitrary `receiver.member()` are not inferred project or external calls merely from their spelling.

### Class, member, and declared-type facts

`languages/python_uses.python_facts()` collects lexical evidence shared by source uses and declarations. `languages/python_declarations.py` produces callable facts, direct bases, and canonical fields; `languages/python_types.py` parses annotation expressions without evaluation. `source_uses.resolve_project_references()` refines imported type/base targets and classifies known types during `build_project()`. These facts are available through `AnalysisResult.project`, independently of rule projections and metric populations; see [the policy boundary](architecture.md#class-and-type-evidence-boundary).

#### Callable declarations

`SymbolIR.callable_facts` is a frozen `CallableIR` for Python function/method declarations, otherwise `None`:

| Field | Meaning |
| --- | --- |
| `declaring_class_id` | Immediate owning class for methods; `None` for functions, including functions nested inside methods |
| `binding` | Syntactic `function`, `instance`, `class`, or `static`; recognized builtin `classmethod`/`staticmethod` bindings include import aliases |
| `decorators` | Tuple of original decorator expression spellings, in source order, without `@` |
| `is_abstract` | Recognized `abc.abstractmethod` binding evidence, including aliases; not a claim about runtime metaclass state |
| `body_kind` | `empty` (docstring-only), `pass`, `ellipsis`, or `implemented`, after excluding an initial plain docstring and comments |
| `body_span` | Source body location, including a docstring if present |
| `implementation_id` | This callable's declaration ID for `implemented` bodies; `None` for the documented placeholder forms |

Abstract declarations can have implemented bodies. A raising body is implemented syntax; placeholder classification is not an assessment of useful behavior. Custom decorators/descriptors, runtime abstractness, overload/property-family grouping, and stub/implementation matching are not inferred. Decorator spellings and ownership remain available for subsequent resolvers. Existing `SymbolIR.body`, complexity, and rule roles are unchanged, including for placeholders.

#### Canonical attributes

`ModuleIR.attributes` is the sole tuple inventory of `AttributeIR`; `ProjectIR.attributes_by_id` is a derived read-only view. Each field has `name`, `declaring_class_id`, the first declaration target's `span` and lexical `owner_id`, `storage`, and `declared_types`. Its ID is the declaring class's snapshot ID plus `:attribute:` and the attribute name, not the assignment span. Repeated writes do not create fields; two different names with one declared type remain two fields. Repeated class declarations have distinct field identities.

Supported declarations are:

- Class-scope identifier assignments and annotations, including declarations beneath control-flow wrappers, chained assignments, and tuple/list unpacking targets.
- Direct assignments/annotations to the first parameter's attributes in instance methods or recognized classmethods (the parameter need not be called `self`/`cls`). Any lexical rebinding of that parameter disables this attribution for the method. Static methods and functions nested inside methods do not declare receiver fields.

`storage` records syntactic declaration evidence: `class` for class-scope names/classmethod receiver assignments, `instance` for instance-method receiver assignments, or both. It does not infer runtime storage: an uninitialized class annotation, dataclass transformation, or `ClassVar` wrapper is retained as syntax, not evaluated. `declared_types` retains each explicit annotation in source order; unannotated writes add no inferred type. Parameters, function locals, and `global`/`nonlocal` targets are not fields.

Ordinary supported class-name assignments also produce `SourceUseIR` writes with `target_form="name"` and class execution ownership. Receiver writes reuse existing occurrences. Repeated and augmented writes link through `declared_attribute_id`; augmented assignments alone do not introduce declarations. Annotation-only targets declare fields but are not writes. Reads/deletions retain their existing unresolved source-use evidence; field linking is not a member resolver.

Unsupported creation includes `setattr`, `exec`, `__dict__`/subscript mutations, generated slots/dataclass/metaclass fields, receiver aliases, arbitrary object assignments, class-name-qualified writes outside the supported receiver form, and nested receiver paths such as `self.child.field`. An ordinary `__slots__` assignment retains the `__slots__` field itself, not generated slot declarations. Subclass writes remain declarations on the syntactic subclass; associating them with inherited fields is subsequent resolver work.

#### Structured types and direct bases

Each `TypeReferenceIR` retains `spelling`, annotation/base-expression `span`, `form`, optional dotted `name`, recursive tuple `arguments`, `is_forward`, `category`, and `TargetResolutionIR`. Nested arguments share the full annotation/base span as their evidence location; their spellings describe the nested expression, not separately addressable source occurrences. Root spelling preserves quotes and grouping. Forward strings are parsed without executing them.

Forms are `name`, `generic`, `union` (`|`), `type-list` (for example `Callable[[A, B], R]`), `literal`, and `unknown`. Generic wrappers and arguments remain structured rather than flattened into class sets. Imported `typing`/`typing_extensions` `Literal` arguments and `Annotated` metadata remain literal evidence, not forward class references. Signature parameter/return annotations remain the existing textual `SignatureIR` contract; structured extraction covers fields and bases.

Categories describe evidence, not metric inclusion:

- `class`: a uniquely resolved retained class. Imported `typing.Self`/`typing_extensions.Self` refers to the declaring class in field annotations.
- `primitive`: builtin `bool`, `int`, `float`, `complex`, `str`, `bytes`, `None`, or imported `types.NoneType` evidence.
- `other`: known non-class project targets, other builtins, recognized typing wrappers, unions, type lists, or literal metadata.
- `unknown`: unresolved/ambiguous/unsupported references, unknown external annotations, and unsupported dynamic expressions. An import alone does not prove a class type. Assignment aliases and type-parameter semantics are not inferred.

`SymbolIR.direct_bases` is a tuple on Python classes, including `()` for no explicit bases; other symbols/parsers expose `None`. Each positional base expression retains its own structured reference and resolution limits. Class keywords (including `metaclass` and `**options`) are excluded; starred/dynamic positional bases remain unknown. No implicit `object` edge or transitive bases are invented. Dotted lexical class members can remain unresolved with `receiver-needs-member-resolution`; imported qualified names resolve conservatively against module-accessible declarations. Forward-string interpretation applies to annotations, not base expressions.

The existing `base_names` strings on classes/methods remain a compatibility projection for structural-rule keep reasons, including header keywords; they are not the canonical base relation.

Inheritance never copies a base's callable/field declarations, body operations, or source uses into subclasses. Direct relations and declaration ownership are the inputs to a subsequent inheritance/member resolver, not precomputed inherited method populations or dispatch sets.

### Fact availability and parser support

Availability is represented by the data itself: `None` means extraction is unavailable; an empty tuple (or frozenset for roles) means extraction succeeded with no facts in the documented supported subset. Optional inventories default to `None`. All parsers supply declaration, signature, complexity, and SLOC facts, so those fields remain non-nullable. There is no parallel coverage record or inferred per-file completeness status.

| Facts | Python supported subset | Generic-language supported subset |
| --- | --- | --- |
| `ModuleIR.symbols` | Named async/decorated/nested/conditional class/function declarations, not lambdas | Grammar-configured class/function declarations |
| `SymbolIR.signature` | Parameter names and annotation text, not full type semantics | Parameter names |
| Complexity and SLOC | Documented syntax counts, maximum nesting, and SLOC exclusions | Configured cyclomatic/cognitive syntax counts and SLOC exclusions |
| `ModuleIR.text_fragments` | Identifiers, comments, and docstring literals under the source-text policy above | `None` |
| `ModuleIR.source_uses` | Documented call/access subset, including explicit unsupported-context records; import refinement in `build_project()` | `None` |
| `ModuleIR.imports` | Scoped alias bindings and resolvable relative names, not full import semantics | `None` |
| `ModuleIR.attributes` | Documented canonical class/receiver assignment subset; annotation references are structured | `None` |
| `SymbolIR.callable_facts` | Callable declaration, binding/decorator, abstract and body-placeholder evidence | `None` |
| `SymbolIR.direct_bases` | Explicit positional base references on classes, with conservative type resolution | `None` |
| `SymbolIR.references` | Function/method rule projections from canonical calls | `None` |
| `SymbolIR.body` | Shallow function/method body operations and supported values | `None` |
| `SymbolIR.roles` | Conservative semantic keep reasons | `None` |
| `ProjectIR.effects_by_symbol` values | Callable effects derived from supported operations/values | `None` per callable |
| `ModuleIR.operations` | `None` (module operations are not extracted) | `None` |

Python class body/reference summaries are also unavailable (`None`); class initialization uses remain in the canonical module inventory. `SymbolIR.return_operations` preserves body availability. Resolution preserves availability; indexes include only available occurrences. Consumers must handle unavailable facts explicitly rather than silently treating them as empty. Available facts do not promise full language semantics or complete resolution. A retained unsupported source-use context remains an occurrence with explicit uncertainty, not an unavailable file inventory.

TODO: [#6](https://github.com/meffmadd/scb-check/issues/6) adds possible-runtime-target sets with their own complete-under-assumption, approximate, or unavailable evidence. Nullable inventories alone cannot express target-set completeness; unknown targets must never become complete empty sets.

### Counting and associations

Every declaration survives in `symbols_by_id`, including Python overloads, repeated definitions, and property accessors. Import aliases remain bindings, not duplicate target entities. Python metric populations select the last record per `(physical file, existing qualified name)`, preserving same-file collision behavior while preventing cross-file name overwrites. Generic-language collisions still receive the existing source/span name suffix so their metric populations retain overloads and duplicate basenames.

The generic C++ frontend extracts function definitions, not standalone prototypes, so a prototype plus its definition does not create two counted functions. There is no general declaration/body resolver, property/overload-family grouping, `.pyi` discovery, or stub/implementation matching. Unsupported associations remain unassociated, not fabricated entities.

## Semantic context

`build_project()` resolves canonical source uses and declared type/base references, derives compatibility effects from the retained modules, and supplies `RuleContext` for structural rules. Each declaration retains its own ID-keyed effects, while `RuleContext` preserves last-qualified-name effect selection for existing rule decisions, including same-file redefinitions. Retaining more facts alone does not change those decisions. Entity lookup consumers use IDs for identity; rule-specific name queries are not the canonical source-use resolver.

Rule projections intentionally preserve historical decisions rather than adopting canonical execution/resolution policy wholesale:

- Symbol `references` link to canonical occurrences through `source_use_id` and use textual containment, including nested bodies and headers, with parameter-root, builtin-root, own-name, and nested-declaration-name calls excluded. There is no module-wide reference aggregate; consumers needing source occurrences use `ModuleIR.source_uses`.
- `RuleContext.call_sites_for_symbol()` preserves name-based selection and excludes self-recursion. Canonical source uses retain parameter/builtin calls and recursion, with execution ownership independent of textual containment.
- Effects remain shallow, selected by supported body operations/values, not every canonical nested use. Invocation values become `PROJECT_CALL`, `EXTERNAL_CALL`, or `UNRESOLVED_CALL`; symbol/member values become `READ`; raise operations become `RAISE`. Call and member-read effects link back through `EffectIR.source_use_id`; plain-name reads and raises have no such occurrence link.
- Rule import expansion remains root-only, including compatibility handling of unaliased dotted and relative imports; it is separate from canonical scoped import resolution. The effect classifier's dotted-name/import-expansion keep-policy preserves wrapper-rule behavior. Its `EXTERNAL_CALL` label is a rule decision, not an assertion that the linked canonical resolution is `external`. A dotted receiver can remain canonically unresolved.

References, operations, and effects are consumer projections, not competing authoritative call inventories. Metrics select sites, distinct execution owners/callers, or distinct resolved targets from canonical facts according to their own population and direction policies; those counts and formulas remain outside the IR.

`RuleContext` is the structural-rule API over `ProjectIR`. It exposes derived effects and resolved project call sites for rules such as `low-use-short-function`, which estimates whether inlining a short helper would stay within caller SLOC, complexity, cognitive complexity, and nesting budgets. Add a query there when a rule needs a new semantic question, rather than teaching the rule Python syntax.

## Extension rules

- Keep file IO at boundaries; parsers accept `Path` plus already-read source text.
- Keep IR pure and immutable; pass tuples across module boundaries.
- Add parser-native data only to `ParsedFile`, and only when an analysis helper needs it.
- Add enum members or IR fields for a specified analysis consumer or rule/scoring need; keep consumer-specific document assembly and calculations outside the IR.
- When adding syntax support, update parser tests, semantic tests, and any affected scoring docs.
- When adding a new language, add a parser config/module, dispatch mapping, `Language` value, discovery support, clone config, tests, and docs deliberately; do not make Python-specific assumptions in structural rules.
