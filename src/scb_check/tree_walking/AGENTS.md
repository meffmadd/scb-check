# `tree_walking/` — source → language-agnostic IR

Owns parser dispatch, language walkers, source directives, SLOC lines, pure Pydantic IR models, and semantic project context.

Supported source languages are Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++ (`cpp`). Python has the rich semantic walker; the other languages use the generic Tree-sitter parser core for minimal symbols, SLOC, and complexity facts.

## Invariants

- Language parsers accept already-read source text. File IO stays in the shared `analysis/source.py` boundary used by check and diff.
- `ModuleIR`, `SymbolIR`, `OperationIR`, `ValueIR`, `EffectIR`, and `RuleFinding` must not store raw tree-sitter nodes.
- Parser-native data may live only on `ParsedFile` for clone detection.
- `AnalysisResult.project` retains the module inventory with derived read-only indexes. Preserve ID-based membership, immutable nested mappings, and conservative parser-declared `FactCoverage`; see the [entity contract](../../../docs/tree-walking.md#retained-entity-contract).
- Declaration inventory and metric populations are distinct: retain all declarations here; pipeline selection preserves last same-file qualified-name selection without cross-file overwrites.
- SLOC excludes comments and blank lines. Python also excludes standalone non-f-string/non-bytes string statements; generic parsers also exclude punctuation-only delimiter lines.
- Extract per-function SLOC and cyclomatic/cognitive complexity facts here. Metric classes in `metrics/` own mass arithmetic, aggregate scores, result fields, and units; keep those calculations out of `SymbolIR`.
- Source directives are Python comment-token based; do not raw-search source text.
- Rules ask `RuleContext` for semantic keep reasons and effects instead of inspecting Python syntax.
