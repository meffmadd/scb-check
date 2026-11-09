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

Complexity metric populations select declarations by `(physical file, qualified name)`, keeping the last same-file declaration; generic parsers retain their existing name disambiguation. Cross-file Python name collisions no longer discard functions. Python declarations under control-flow wrappers also enter ordinary metrics and structural rules. These two extraction/indexing corrections intentionally affect counts, masses, erosion scores, and potentially structural verbosity, without changing formulas, rule policies, report fields, or CLI contracts.

### Coupling Between Objects (CBO)

`cbo` reports **partial retained-project CBO**, not verified full-program CBO and not a sloppiness score. The selected definition is Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §4.2.1 Definition 20 (printed p. 101), using §3.7 Definition 17's `uses` predicate (printed p. 94). It formalizes the CK metric ([Chidamber & Kemerer, 1994](https://doi.org/10.1109/32.295895)). No refined/slice-based variants or quality thresholds are applied.

For each class, count distinct other classes where either class invokes a method implemented by the other or accesses an attribute declared by the other. Count actual ancestor-member use; inheritance and type declarations alone add no edges. Repeated sites, reads/writes/deletes, and reverse-direction uses deduplicate to one partner. Self-use adds none. An inherited body belongs to its declaring class; it is not copied to subclasses. Uses belong to their nearest enclosing class (including class initialization and nested functions); module/free-function uses without an enclosing class cannot contribute a class partner.

The modeled population is every retained class declaration, including nested and repeated declarations, in successfully parsed files. Python classes with available use/attribute inventories and direct-base facts receive partial measurements; unsupported classes receive `None` diagnostics. External/library classes, builtins, excluded files, and failed parses are outside the population. Libraries contribute only if their source is explicitly included and parsed as project source. Imports, class construction alone, bare method references, and placeholder-only method bodies do not add method-use edges; declared fields supply attribute edges. Construction does not imply an inferred `__init__` call.

For method calls, use the IR's possible implementation bodies when available, including polymorphic overrides. Both complete-under-`closed-project-hierarchy` and approximate sets contribute their known bodies. If unavailable, use a statically selected implemented method as partial evidence. Attribute uses select canonical declared fields. The metric performs no language resolution or source IO. Its immutable module-fact input is a projection of retained analysis, not rule references or a second graph resolver.

All measurements are explicitly **partial**: dynamic receivers, unsupported contexts/decorators/descriptors, unresolved/ambiguous uses, unavailable inventories, unmodeled libraries, and external subclasses/callers can hide partners. Unknown outgoing references are omitted, never assigned invented partners. An unresolved incoming use in another class can hide a partner for any measured class, even one with completely resolved outgoing sites. A partial zero means no observed resolved partners, not a verified absence of coupling. Approximate/static fallback sets are not a sound full-runtime upper or lower bound.

Project aggregation is an **analyzer convention**, not a paper-defined project formula:

- `measured_classes` counts classes with partial measurements; `unavailable_classes` counts retained classes with unsupported extraction (units: classes).
- `partial_partner_sum`, `partial_partner_mean`, and `partial_partner_max` summarize only the measured population (units: partners per class for mean/max, class-partner incidences for sum). Each undirected pair contributes twice to the sum.
- With no measured classes, all three summaries are `None`, not zero. Unavailable classes are excluded from denominators. All measured values remain partial, including in mixed-language snapshots.

`CBO.partner_sets()` exposes read-only per-class partner-ID sets (`None` for unsupported extraction) separately from flat numerical reports. `tests/fixtures/cbo/partners.py` has eight measured classes with partner counts `3, 1, 2, 1, 0, 0, 0, 1`: sum `8`, mean `1`, maximum `3`. Snapshot differences compare independently modeled populations; larger breadth is not inherently worse.

### Partial metric interpretation

CBO, RFC₁, MPC, distinct callers, DAC, CIC, method RIC, Ca, and Ce describe retained source, not whole-program behavior or code quality. Their project summaries are **analyzer conventions**, not paper-defined project formulas. Larger values do not imply sloppiness; these metrics introduce no quality thresholds, findings, or exit-code changes.

A **partial** measurement counts supported evidence, including an observed zero. An **unavailable** measurement means the entity lacks required extraction support; it is excluded from summary denominators rather than treated as zero. Measured and unavailable populations remain separate. Each snapshot models its own retained population; differences can reflect coverage changes as well as changed relationships.

### Direct Response For a Class (RFC₁)

`rfc` implements a restricted retained-project **direct RFC₁**, following Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §4.2.1 Definitions 21–22 (printed p. 101), formalizing [Chidamber & Kemerer (1994)](https://doi.org/10.1109/32.295895). It is not transitive RFC∞.

For each class, seed a response set with method declaration identities selected by the retained instance and class member lookups. This includes inherited selections, respects selected overrides, and deduplicates methods visible through both lookups. Selected abstract/placeholder declarations count even without bodies. No generated methods are invented. An isolated class therefore still contributes its selected method count.

Union the known possible **method implementation** identities directly called by those seed methods. Both approximate and complete-under-`closed-project-hierarchy` runtime-target sets supply known bodies; there is **no static-target fallback** when that set is empty. Own-method calls remain eligible, while recursion and repeated sites add no duplicate identities. Follow only one level: a newly added callee's calls are not expanded. Free/nested functions are not method targets; calls executing in nested functions, module/class initialization, or explicitly unsupported contexts do not expand a seed method. Inherited bodies are examined as their canonical declarations rather than copied implementations.

Every retained class, including nested/repeated declarations, enters the population. A class is measured when its module has source-use extraction, its direct-base facts exist, both retained member lookups contain it, and every selected method has callable facts and an available source-use inventory in its declaring module; otherwise it is unavailable. This also applies to inherited selections. Currently this is Python-first. Only retained project methods contribute; libraries contribute only when scanned as project source. Dynamic/unresolved calls, external bases/overrides, and unsupported execution contexts can hide responses within a measured class. Incoming call volume does not directly enter RFC₁; unmodeled incoming callers do not enlarge its set. Possible-target evidence is not a verified full-runtime bound.

`partial_response_sum`, `partial_response_mean`, and `partial_response_max` summarize per-class response-set sizes over measured classes, including zeros (unit: methods; the sum counts class–response incidences). `measured_classes` and `unavailable_classes` use classes. With no measured classes, all summaries are `None`. `RFC.response_sets()` exposes separate read-only diagnostics.

### Message Passing Coupling (MPC)

`mpc` measures **Message Passing Coupling**, not Method Pair Coupling. The selected counting variant follows Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §4.2.1 Definition 23 (printed pp. 101–102). Original provenance is [Li & Henry (1993)](https://doi.org/10.1016/0164-1212(93)90077-B); its primary full text was not independently checked for this implementation.

Count each static call occurrence executing directly in an implemented method of the focal class when the statically selected target method is implemented outside that class. Use the retained static declaration's implementation owner; possible runtime overrides do not change site eligibility or multiply the count. Repeated sites count separately; one site in a loop counts once. Calls only to own implementations contribute zero. Inherited source bodies stay with their declaring class; an ancestor-implemented target remains external to a subclass. Bodyless methods supply neither source implementations nor eligible targets. No generated methods or implicit constructor calls are invented. Free/nested-function bodies, initialization code, bare method references, and unsupported execution contexts do not contribute.

The population is every retained class, including nested/repeated declarations. Source-use and direct-base extraction make a class measurable; missing support makes it unavailable. Targets must be retained project method implementations; unscanned libraries, unresolved outgoing calls, dynamic dispatch, and unsupported bodies can hide sites. Incoming callers do not affect this outgoing count. All observed counts remain partial, including zero; static selection does not establish a sound whole-program runtime bound.

`partial_call_site_sum`, `partial_call_site_mean`, and `partial_call_site_max` summarize measured per-class counts (unit: call sites). `measured_classes` and `unavailable_classes` use classes. Summaries are `None` with no measured classes. `MPC.class_counts()` provides separate read-only diagnostics.

### Distinct callers

`callers` is an **engineering-defined incoming-use count**, not Henry–Kafura information-flow fan-in or the RIC ratio. No defining paper or DOI is claimed. Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §§3.3, 3.7 and 4.2.2 (printed pp. 103–104 for §4.2.2), supplies coupling-framework background only.

Invert direct call occurrences with function execution ownership and static resolution status `project`, selecting the canonical `resolution.target_id`. Do not expand possible runtime bodies or overrides. Each source callable declaration contributes once per destination, regardless of repeated sites; direct recursion contributes one caller. A nested function is its own caller. Module/class initialization has no callable caller and contributes none; execution ownership is not promoted to an enclosing function. Inherited methods stay canonical declarations rather than being copied to subclasses. Placeholder/abstract and decorated declarations remain eligible because this counts declaration use, not implemented bodies. No generated callables or implicit calls are invented.

The population is every retained function/method declaration, including nested/repeated declarations. Available module source uses plus callable facts make a declaration measurable; missing support makes it unavailable. Generic-language callables currently lack this support. Only retained source callers/destinations count; a library participates only as scanned project source. Unresolved/ambiguous/external calls, callbacks, unsupported execution, and missing extraction elsewhere can hide incoming callers for **any** measured destination, even one with fully resolved outgoing calls. Such destinations remain partial, not unavailable or verified zero. Outgoing uncertainty in one callable becomes incoming uncertainty for potential destinations.

Same-module versus cross-module compares `ModuleIR.id`: one logical module per physical file, not module-name spelling or package membership. `partial_caller_sum` counts caller–destination pairs, not globally distinct callers; `partial_same_module_sum` and `partial_cross_module_sum` partition it. `partial_caller_mean` and `partial_caller_max` summarize counts per measured destination, including zeros (unit: callers). Population fields `measured_callables` and `unavailable_callables` count functions/methods (declared unit: `functions`). All five summaries are `None` with no measured destinations. `DistinctCallers.caller_sets()` exposes separate read-only, partitioned diagnostics.

### Data Abstraction Coupling (DAC)

`dac` implements **attribute-count DAC**, following Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §4.2.1 Definition 24 (printed p. 102), with §3.6 type conventions (printed p. 94). Original provenance is [Li & Henry (1993)](https://doi.org/10.1016/0164-1212(93)90077-B); its primary full text was not independently checked for this implementation.

Count a canonical attribute once if any retained declared type has form `name` or `generic`, category `class`, and project resolution to a retained class. Two fields of the same class type contribute two: this measures attribute volume, not independent type breadth. Repeated or conflicting annotations supply positive evidence but never multiple contributions for one field or proof of a unique runtime type. Class and instance fields count; self/ancestor class types are eligible. Inherited fields stay with their declaring class. Parameters, locals, primitives, and nonclass types do not count. Bodyless methods add no inferred fields; no generated methods/fields are invented.

Use only the outer declared type. A retained project generic class can count, but containers, unions, and typing wrappers are not flattened into their argument classes. Python object references count through the declared class type. There is no C++ pointer/reference/array underlying-type normalization in the current supported subset; generic-language attribute extraction is unavailable.

Every retained class, including nested/repeated declarations, enters the population. Available module attribute extraction makes a class measurable; absent extraction makes it unavailable. Unannotated fields, unknown/unresolved types, unsupported assignments, and library types outside retained source are omitted within **partial** measurements, not classified as known nonclass types. Libraries contribute only when their classes are scanned as project source. Initializers do not infer types. Incoming uses do not add attributes, though writes outside supported declaring-class extraction can be missing.

`partial_attribute_sum`, `partial_attribute_mean`, and `partial_attribute_max` summarize measured per-class field counts (unit: attributes); `measured_classes` and `unavailable_classes` use classes. Summaries are `None` with no measured classes. `DAC.attribute_sets()` exposes separate read-only diagnostics.

### Class Inheritance-related Coupling (CIC)

`cic` reports **partial static retained-project CIC**. Rajaraman & Lyu (1992), *Some Coupling Measures for C++ Programs*, §IV, [author-hosted primary paper](https://www.cse.cuhk.edu.hk/lyu/_media/conference/crajaraman_tools1992_some.pdf), PDF p. 6 / printed p. 5, defines CIC as the count of accesses to variables and uses of member functions defined in proper ancestor classes. The primary text was checked for this implementation; **no DOI was verified**. The paper's directed multigraph preserves repeated references. The following source-body, dispatch, occurrence, and aggregation policies are analyzer choices for a Python-first interpretation, not claims that the paper settles them.

- Traverse retained project `direct_bases` transitively to establish the focal class's proper ancestors, excluding itself. Select outgoing occurrences by the canonical field-defining or method-implementation owner, not the receiver's type or member spelling. Uses of own overrides and unrelated members, inheritance declarations alone, type declarations, and construction alone contribute zero.
- Use retained **static** project targets only; possible runtime implementations neither change eligibility nor multiply a site. Calls and bare references to implemented ancestor methods count. Abstract/placeholder declarations without implementations do not supply method targets. Canonical ancestor fields count reads, writes, read-writes, and deletes.
- Preserve repeated physical source sites; loops do not multiply them. A call and its accompanying target-access record count once, including nested/multiline parentheses around the target. When spans differ, deduplication requires matching retained execution owner, static target, and full receiver facts within the call's target span; containment alone does not suppress accesses. Bare references, argument references, and distinct receiver-field accesses remain independently eligible, including receiver prefixes resolving to the same canonical field as the call target. An augmented field update is one read-write occurrence.
- Attribute supported execution to the nearest enclosing class, including class initialization and nested functions. A nested class is its own focal class. Module/free-function sites without an enclosing class and explicitly unsupported execution contexts (including lambdas/comprehensions) contribute nothing. Inherited bodies stay only with their source-declaring class; they are never copied or re-extracted for subclasses.

The population is every retained class declaration, including nested/repeated declarations, in successfully parsed files. A class is measurable only when its module has source-use and attribute inventories, its declared methods have callable facts, and every transitive base relation resolves to a retained class with available direct-base facts. Unknown, ambiguous, external, missing, unsupported, or cyclic ancestry makes the class **unavailable**, including descendants of such classes. Implicit Python `object` is not an invented retained base; an explicit unscanned `object` base is unavailable under this strict policy. Generic-language extraction currently makes CIC unavailable.

For classes with established ancestry, unknown/ambiguous/external member targets, unsupported member resolution, and unmodeled execution can still hide occurrences; measured counts are therefore **partial**, including zero. Libraries participate only when included and parsed as retained project source. Excluded/failed files supply no invented facts. Static selection is not a verified whole-program runtime bound. Incoming references do not contribute to this outgoing-only metric, so incoming-reference uncertainty cannot enlarge its counted population. The metric consumes immutable module facts without source IO, reparsing, or additional language resolution; proper-ancestor traversal is a metric filter over retained base edges.

Project aggregation is an **analyzer convention**, not a paper-defined project formula. `measured_classes` and `unavailable_classes` count retained classes (unit: classes). `partial_occurrence_sum`, `partial_occurrence_mean`, and `partial_occurrence_max` summarize only measured per-class counts (declared unit: occurrences; mean is occurrences per measured class). All three are `None` with no measured classes; unavailable classes are excluded from the denominator. `CIC.class_counts()` exposes separate read-only class-ID diagnostics with `None` for unavailable classes. `tests/fixtures/cic/occurrences.py` has counts `0, 4, 4, 0, 0, 0`: sum `8`, mean `8/6`, maximum `4`. No quality thresholds or sloppiness judgments are introduced. Check and independent-snapshot diff compose these fields explicitly, preserving signed/zero deltas and null propagation.

### Method-level Relative Inward Coupling (RIC)

`ric` implements the explicit **method variant** of Joshi & Joshi (2006), *Microscopic coupling metrics for refactoring*, [DOI 10.1109/CSMR.2006.32](https://doi.org/10.1109/CSMR.2006.32), §7 (manuscript PDF p. 5), immediately after the attribute formula. It preserves that formula rather than §8's conflicting edge-count interpretation:

`RIC(method owned by i, comparison class j) = distinct methods of j directly using method / max(1, distinct methods of i directly using method)`

The population is **all retained method declarations × all other retained class declarations**, including zero-use pairs, nested/repeated declarations, and classes with no methods. Inherited methods and callers retain their canonical declaring classes; they are not copied into subclasses. Overrides are separate declarations. Abstract/placeholder and decorated declarations remain eligible when callable extraction is available. No generated methods or implicit constructor calls are invented.

Count only direct call occurrences executing in retained methods, with static resolution status `project` and a retained method target. Deduplicate caller declaration IDs per target/class, regardless of repeated sites. Direct recursion contributes one owner using method. Runtime possible-target sets do not expand or replace static selection. Free/nested functions, module/class initialization, and explicitly unsupported execution contexts do not count; calls are not promoted to an enclosing method. There is **no indirect traversal**.

A class requires available module source uses, direct-base facts, and callable facts for every method declared in it. A pair is unavailable when its target method, declaring class, or comparison class lacks required extraction. Retained lexical method ownership enumerates unavailable pairs when callable facts are missing; it does not supply measured use. Current support is Python-first; generic-language class/method extraction does not suffice for measurement. A supported class with no methods can still contribute comparison pairs with zero external users. No methods or fewer than two classes yields no pairs.

Every measured pair remains **partial**, including zero: unresolved/ambiguous/external calls, dynamic dispatch, unsupported contexts, missing extraction elsewhere, excluded/failed files, and unretained incoming callers can hide either raw count. Missing incoming evidence elsewhere does not make every supported destination unavailable. Libraries participate only as explicitly scanned project source. Neither counts nor ratios establish verified runtime bounds; partial ratios are not necessarily lower bounds. Public APIs, framework callbacks, and missing external caller visibility limit interpretation. RIC adds no thresholds, sloppiness judgment, or automatic move/remove-method recommendations.

`RIC.pair_diagnostics(modules)` returns a read-only mapping keyed by `(method_id, comparison_class_id)`. Values are frozen `RICPair` records, or `None` for unavailable pairs. `external_users` is the raw numerator, `owner_users` is raw owner use, `effective_denominator` is `max(1, owner_users)` (all counts: distinct using methods), and `ratio` is their dimensionless quotient. Thus one external user and zero owner users gives `(1, 0, 1, 1.0)`, distinct from equal actual use `(1, 1, 1, 1.0)`. Diagnostics remain separate from flat numerical reports.

Project summaries are **analyzer conventions**, not paper-defined class/system RIC: `measured_pairs` and `unavailable_pairs` count pairs; `partial_ratio_mean` and `partial_ratio_max` summarize measured pair ratios, including zeros (unit: `ratio`, not `fraction`/percentage). No ratio sum or pooled ratio is reported. With no measured pairs both summaries are `None`. Adding unused classes changes the all-pairs mean; independently modeled snapshot populations and coverage can change summaries without changing any existing call. Only explicit `pair_diagnostics()` enumeration has method × class space/time cost.

Ordinary `compute()`, `check`, and `diff` share a narrow internal facts projection with diagnostics: class/method availability, canonical ownership, and sparse distinct-user counts. Total pairs are counted per method as `retained classes - (owner is retained)`; measured pairs are `eligible methods × (available classes - 1)`, with unavailable pairs the difference. Measured zero-use pairs therefore remain in population counts and the mean denominator without being materialized. Only observed, measured external-use groups contribute ratios; an entirely zero measured population still has mean/max `0.0`. Nonzero contributions retain diagnostic method/class order and the same float summation semantics. Projection storage scales with declarations and distinct observed user relations, not zero-pair population size; grouping and counting scan retained declarations/uses, and canonical ordering sorts only observed target/class groups. `tests/metrics/test_ric.py` checks exact equivalence to full diagnostics and bounds aggregate allocation and executed RIC line events on a zero-call project, without timing thresholds.

`tests/fixtures/ric/direct.py` has 48 measured pairs, ratio mean `0.09375`, and maximum `1.5`; owner target users are two methods, with three external users in `Client` and one each in `Other` and `Child`. It also distinguishes recursion, placeholders, inherited selection, runtime overrides, repeated sites, unknown references, and free/nested execution.

### Category coupling (Ca and Ce)

`ca` and `ce` preserve the class populations in [Robert C. Martin's 1994 manuscript, *OO Design Quality Metrics: An Analysis of Dependencies*](https://condor.depaul.edu/dmumaugh/OOT/Design-Principles/oodmetrc.pdf): categories are discussed on PDF p. 5, with dependency metrics on p. 6. No DOI is claimed for this manuscript. Briand, Daly & Wüst (1999), [DOI 10.1109/32.748920](https://doi.org/10.1109/32.748920), §4.2.1 (PDF p. 12 / printed p. 102), reproduces these populations and explicitly leaves the dependency predicate unspecified. The following shared policy is an **analyzer choice**, not a recovered primary-paper formalization.

#### Shared measurement policy

- **Category membership:** one class-bearing retained logical module per physical file, keyed by `ModuleIR.id`. Include every retained class declaration, including nested/repeated declarations; never merge categories or classes by qualified name. Modules in one package remain separate, including a class-bearing `__init__.py`. Classless modules add neither measured nor unavailable categories. Directories and namespace packages are not inferred categories.
- **Directed dependency:** a class calls a statically resolved implemented method or accesses a canonical declared field of another retained class. Reads, writes, augmented writes, and deletes qualify. Use `SourceUseIR.resolution` with status `project` and canonical declaring owners; **do not expand possible runtime targets**. Inherited targets stay with their declaring class. Bodyless target methods supply no implementation dependency. Static declaration evidence is not a verified runtime relationship, including for decorated methods.
- **Source ownership:** the nearest enclosing class of a supported execution owner supplies the client, including class initialization and functions nested inside methods. Nested classes supply their own clients. Inherited source bodies stay with their declaring class, not subclasses. Module/free-function uses and unsupported execution contexts supply no class client.
- **Excluded evidence:** imports alone, inheritance alone, declared types alone, class construction alone (no inferred constructor call), bare method references, self-use, and unresolved/ambiguous/unsupported targets add no class dependency. Internal-only class dependencies remain in shared diagnostics but contribute to neither metric for that category.
- **Scope:** only retained project classes participate. “Outside” means outside the category, not outside the project. Builtins and unscanned library classes have no invented class identities; libraries participate only when their source is included and parsed as project source. Failed parses, exclusions, and dynamic generation can hide classes and relations.

`metrics.categories.category_dependencies(project)` projects the already-resolved immutable IR onto `CategoryDependencies`: read-only class-to-category membership, unavailable category IDs, and immutable directed class pairs. It performs no parsing, source IO, or language resolution. Reporting builds this projection once per snapshot and independently supplies it to `AfferentCoupling` and `EfferentCoupling`. Neither metric depends on the other or on CBO; the policy does not change existing metrics.

#### Counting and project summaries

For a category `K`:

- **Ca:** count distinct client classes outside `K` with any qualifying dependency on a class inside `K`. Several external clients count separately, even within one module. One client using several internal classes/members or repeated sites counts once. Internal clients do not contribute.
- **Ce:** count distinct source classes inside `K` with any qualifying dependency on a class outside `K`. One source depending on twenty outside classes contributes **one**, not twenty. External clients, outside target classes, and neighboring modules are not Ce's population. This historical source-class variant differs from tools that label outside target breadth “Ce”.

Both groups expose `measured_categories` and `unavailable_categories` (unit: categories). Ca's `partial_client_sum`, `partial_client_mean`, and `partial_client_max` summarize measured category client-set sizes (unit: client classes). Ce's `partial_source_sum`, `partial_source_mean`, and `partial_source_max` summarize measured category source-set sizes (unit: source classes). Sums count category–client/source incidences, means divide by measured categories, and maxima select the largest per-category count. One Ca client can contribute to several destination categories; a Ce source belongs to exactly one category. These project aggregates are **analyzer conventions**, not paper-defined formulas.

`AfferentCoupling.client_sets()` and `EfferentCoupling.source_sets()` expose separate read-only category-ID → class-ID-set diagnostics, with `None` for unavailable categories. Structured membership and class-pair diagnostics never enter numerical reports. The [source fixture](../tests/fixtures/category_coupling/) has four measured categories: Ca counts `3, 0, 1, 0` (sum `4`, mean `1`, maximum `3`); Ce counts `0, 2, 1, 0` (sum `3`, mean `0.75`, maximum `2`).

#### Availability and interpretation

A class-bearing category is unavailable if any internal class lacks direct-base extraction, its module lacks source-use or attribute extraction, or a declared method lacks callable facts. Generic-language class categories currently lack this support. An available tuple containing unresolved bases is still partial evidence, not missing extraction. A category is never silently measured using only its supported internal subset. Known edges involving an unavailable category can still inform other measured categories.

Unknown relations are omitted within explicitly **partial** measurements. Unresolved outgoing uses can hide Ce sources; unmodeled libraries can hide outside dependencies. Unknown incoming uses or unavailable extraction **anywhere** can hide clients for any measured Ca category, even if every outgoing use in that category resolves. Choosing a predicate does not erase these source limitations. Static selection and unsupported dispatch/inference are not sound whole-program runtime bounds.

An isolated supported category measures partial zero, not proven absence. Unavailable categories are excluded from denominators. If no categories are measured—including classless snapshots—all summary fields are `None`, not zero. Check and independent-snapshot diff use the same composition; deltas are signed later minus earlier, and any null operand yields a null delta, including two nulls. Coverage changes can change populations independently of observed relationships.

Category size, grouping, and scanned context affect interpretation: Ce is bounded by the category's internal class count, while Ca is not; aggregating more classes or scanning more client/library source changes exposure. Neither larger values nor positive deltas imply sloppiness. No quality thresholds, findings, or score/exit-code changes are introduced. See the [glossary](../GLOSSARY.md) for counting terminology.

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

Each side must have successfully parsed eligible source; zero-SLOC files are valid. The command applies the same configuration and analysis options to both sides, preserving ordinary walker semantics including each tree's applicable ignore files. Successful comparisons exit `0` regardless of findings; unusable inputs exit `2` with no partial payload. See [README](../README.md#comparing-source-trees) for options and output fields.

### Report-comparison interface

`models.py` defines `ReportValue = int | float | None`, `MetricResult = Mapping[str, ReportValue]`, and `Report = Mapping[str, MetricResult]`. These are data contracts, not runtime report classes. Computed reports expose read-only outer and inner mappings over privately owned dictionaries. Metric results are flat: booleans, strings, sequences, nested mappings, and non-finite numbers are not report values. The canonical groups and fields are in the [README schema reference](../README.md#check-json-report-fields).

`reporting.score.compute_report(analysis: AnalysisResult)` explicitly composes `Verbosity`, `Erosion`, `CognitiveErosion`, `Syntax`, `CBO`, `RFC`, `MPC`, `DistinctCallers`, `DAC`, `CIC`, `RIC`, `AfferentCoupling`, and `EfferentCoupling` instances from the sibling `metrics/` package. Each metric's `compute()` receives narrowly scoped extracted facts and owns its field names, supporting counts, calculations, and units. The builder owns group names. Private `metrics/_mass.py` shares erosion arithmetic; `metrics/_counts.py` shares sum/mean/max arithmetic for measured CBO, RFC₁, MPC, callers, DAC, CIC, Ca, and Ce counts, returning `None` aggregates for an empty measured population. Concrete metrics retain population, field, and unit ownership. Tree walking owns complexity extraction, not mass calculations.

`metrics.base.Metric` is an abstract base with an abstract `compute()` method and class-declared `units`. Its parameter specification preserves each concrete metric's distinct input signature; it does not require a common analysis context or introduce a registry or dynamic discovery. Metrics do not import reporting.

`comparison.compute_diff_report(earlier_analysis, later_analysis)` returns an ordinary dictionary with exactly `before`, `after`, and `diff`, each a `Report`. It uses the standalone snapshot builder and pure `compare_reports(before, after) -> Report`. The latter has no source access, parsing, analysis execution, or terminal output. It subtracts later minus earlier, retaining zero differences. Required groups and fields must be present; only absent dotted per-language syntax counts are zero-filled over the sorted language union. Explicit `None` on either side produces `None`, even when both sides are null. Snapshots are never mutated.

The two-analysis builder leaves room for a future pairwise measurement without defining all comparisons as subtraction. It currently implements only snapshot differences, with no file pairing, source rereading, or churn calculation.

`score.serialize_report(report)` validates the report contract and creates fresh plain outer and inner dictionaries; changing serialized data cannot change a computed report. `None` becomes JSON `null`. Tree paths remain command-owned context outside numerical reports. `render_comparison(before, after, diff)` uses metric-owned units: fractional scores become percentages, score differences become percentage points, counts and masses keep their units, and unavailable values are explicit. Unit metadata is not embedded in report values.

### Text evidence boundary

Python's immutable `TextFragmentIR` records preserve source evidence for analysis consumers, including CSE's function/method, class, and file documents. Each occurrence lives once in its module's physical-file inventory with a syntactic owner; parent documents can select child owners without duplicate authoritative copies. Other languages explicitly declare extraction unavailable. See [the fragment contract](tree-walking.md#source-text-fragments) for ownership, spans, and availability.

The IR preserves spelling rather than choosing semantic preprocessing: it does not split identifiers, remove stop words, stem, tokenize for a model, embed, or assemble documents. Consumers choose document membership and representations. Metric implementations remain responsible for populations, formulas, and scores; retaining comments/docstrings does not make them SLOC or change verbosity, erosion, report fields, or independent-snapshot comparison.

### Source-use evidence boundary

Python calls and attribute accesses live once in `ModuleIR.source_uses`, with snapshot occurrence IDs, spans, execution owners, and explicit direct-resolution evidence. Imports remain separate bindings. `build_project()` refines import targets against retained entities; `ProjectIR.source_uses_by_id` is a read-only index, not another inventory. See [the source-use contract](tree-walking.md#canonical-source-uses-and-imports) for supported contexts, alias/scope handling, ambiguity, and unresolved dynamics.

A source site, a distinct caller, and a distinct target are different populations: repeated sites and recursion must survive extraction so consumers can choose counts and direction policies. Static binding evidence is not a possible-runtime-target set. External status requires import/builtin evidence outside the retained snapshot; dotted spelling alone supplies neither external status nor type/runtime-target inference.

Rule-facing references and shallow operation-selected effects intentionally preserve textual nesting, parameter/builtin exclusions, self-recursion exclusions, and dotted-call keep-policy. Linked effects carry `source_use_id`, but their rule labels need not match canonical resolution status. This separation retains existing structural-rule behavior while exposing richer facts. Metric populations, counts, formulas, and scores stay in consumers, outside the IR; the inventory itself defines no metric formula. Its consumers preserve verbosity/erosion and CLI exit contracts while adding explicit check/independent-snapshot diff measurements.

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
| Module edges | Logical module/file mapping; import bindings or resolved calls; endpoint module IDs | Explicit relation selection, directions, external scope, neighbor deduplication |
| CIC | Direct bases; static member/field targets; canonical defining/implementation owners; actual sites | Proper-ancestor traversal/filter, inherited-source and dispatch policy, site counting |
| Method RIC | Target method/class identity; distinct executing method/class owners, including owner-class and comparison-class use | Pair population, user deduplication, denominator floor and ratio |
| Multilevel CSE | Original `TextFragmentIR` text/spans and module/declaration owner tree, including nested owners | Method/class/file selection, document preprocessing, explicitly supplied local encoder and similarity |

Implemented consumers and future candidates handle unavailable inventories and uncertain targets explicitly. Shared language resolution belongs here even when expensive; metric-specific graph traversal/counting and embedding computation do not. Fact extraction itself adds no scores, thresholds, or backend registry; implemented metrics explicitly compose their report fields. Ca/Ce select their shared category/dependency policy from these same retained facts; see [category coupling](#category-coupling-ca-and-ce). Existing verbosity/erosion, rule projections, CLI exits, and standalone-check/independent-diff contracts are unchanged.

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
- Snapshot metrics: subclass `metrics.base.Metric` with a metric-owned flat result and units, explicitly compose it in reporting, and extend comparison contracts and CLI acceptance coverage; see [Development](development.md#adding-or-extending-a-metric).
