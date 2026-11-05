# `tree_walking/` — source → language-agnostic IR

Owns parser dispatch, language walkers, source directives, SLOC lines, pure Pydantic IR models, and semantic project context.

Supported source languages are Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++ (`cpp`). Python parsing and extraction live in `languages/python/`, which exposes `PythonParser`; the other languages use the generic Tree-sitter parser core for minimal symbols, SLOC, and complexity facts.

## Invariants

- Language parsers accept already-read source text. File IO stays in the shared `analysis/source.py` boundary used by check and diff.
- Keep IR records, including `SourceUseIR`, `ImportIR`, and `TargetResolutionIR`, free of parser-native nodes; expose frozen records, tuples, and privately owned read-only indexes.
- Parser-native data may live only on `ParsedFile` for clone detection.
- `AnalysisResult.project` retains the module inventory with derived read-only indexes. Preserve ID-based membership and immutable nested mappings; represent unavailable inventories as `None`, distinct from successfully extracted empty tuples/frozensets. Preserve availability through resolution and projections; see the [entity contract](../../../docs/tree-walking.md#retained-entity-contract).
- Text fragments live once in `ModuleIR.text_fragments`, with ID-based syntactic ownership; unsupported parsers expose `None`. When extending extraction, follow the [fragment policy](../../../docs/tree-walking.md#source-text-fragments); document assembly and model preprocessing belong to consumers.
- When changing calls, attribute accesses, imports, or resolution, read the [source-use contract](../../../docs/tree-walking.md#canonical-source-uses-and-imports). Retain occurrences once in `ModuleIR.source_uses`, derive `source_uses_by_id`, and link eligible effects with `source_use_id`. Keep execution ownership separate from text ownership; mark unsupported contexts explicitly.
- When changing class/member declarations, field identity, annotations, or bases, read the [class/member contract](../../../docs/tree-walking.md#class-member-and-declared-type-facts). Keep canonical fields in `ModuleIR.attributes`, callable/base facts on symbols, and repeated writes in source uses; preserve ownership and nullable coverage without copying inherited bodies. Structured types are evidence, not metric populations.
- Resolve direct lexical/import evidence conservatively: preserve ambiguity and unresolved dynamics; require import/builtin evidence for external status. For member/receiver/dispatch changes, follow the [bounded resolution contract](../../../docs/tree-walking.md#member-resolution-and-runtime-targets): `members.py` derives C3/member views and separate runtime implementation sets. Preserve complete-under-assumption/approximate/unavailable evidence and canonical body IDs. Site/caller/target populations and metric graph policies remain consumer-owned.
- Preserve rule projections' textual nested-call/parameter/builtin policies, self-recursion exclusions, shallow effects, and dotted keep-policy independently of canonical resolution; see [semantic context](../../../docs/tree-walking.md#semantic-context).
- Declaration inventory and metric populations are distinct: retain all declarations here; pipeline selection preserves last same-file qualified-name selection without cross-file overwrites.
- SLOC excludes comments and blank lines. Python also excludes standalone non-f-string/non-bytes string statements; generic parsers also exclude punctuation-only delimiter lines.
- Extract per-function SLOC and cyclomatic/cognitive complexity facts here. Metric classes in `metrics/` own mass arithmetic, aggregate scores, result fields, and units; keep those calculations out of `SymbolIR`.
- Source directives are Python comment-token based; do not raw-search source text.
- Rules ask `RuleContext` for semantic keep reasons and effects instead of inspecting Python syntax.
