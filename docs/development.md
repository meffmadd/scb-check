# Development

This guide summarizes the current implementation status and the preferred approach for common changes.

## Current status

`scb-check` is a Python CLI with three public commands:

- `scb-check check PATH` reports human-readable flags or JSON scores.
- `scb-check rule RULE_ID` prints bundled `ast-grep` YAML or structural rule metadata.
- `scb-check diff TREE_A TREE_B` reports SLOC churn and normalized dispersion between directories.

Implemented analysis paths:

- Source discovery for supported Python, Rust, JavaScript, TypeScript, Zig, Haskell, and C++ suffixes.
- Tree-sitter parsing into language-agnostic IR.
- `SLOC` accounting shared by verbosity, clone line counts, rule spans, and churn.
- Sibling `pipeline.analyze()` and `pipeline.analyze_diff()` workflows with shared private source collection and check-only indexing.
- Deterministic tree comparison with relative-path identity and per-side SLOC filtering before matching; changed lines retain original source positions.
- Duplicate-structure detection by normalized AST hashing for all supported languages.
- Bundled Python `ast-grep` slop patterns, plus optional local rules from `SCB_CHECK_EXTRA_SLOP_RULES`.
- Structural rules over `ProjectIR`; the current bundled Python rules are `trivial-wrapper` and opt-in `low-use-short-function`.
- Cyclomatic and cognitive erosion scores for all supported languages.
- Python source ignores for `ast-grep` and structural rule IDs.
- Python boundary suppression for validation/normalization functions.

## Runtime contracts

- `check` exits `0` without findings and `1` with findings; `diff` exits `0` on success regardless of churn.
- Exit `2` is for user-facing failures such as bad config, bad paths, unknown rules, invalid directives, or an empty eligible/parseable source set.
- Individual read/parse failures warn and skip the file instead of aborting the run. In `diff`, a failure on either side skips the entire relative path; one empty tree is valid.
- Non-Python files skip Python ast-grep rules, structural rules, and source directives until language-specific rules exist.
- Config discovery and source-directive behavior are user-facing; keep README examples synchronized when they change.

## Where to make changes

| Change | Primary location |
| --- | --- |
| CLI command or option | `src/scb_check/commands/` |
| Config loading or path walking | `src/scb_check/config.py`, `src/scb_check/walker.py` |
| Source parsing, `SLOC`, directives, IR | `src/scb_check/tree_walking/`; see [Tree walking](tree-walking.md) |
| Language parser configs | `src/scb_check/tree_walking/languages/` |
| Clone detection | `src/scb_check/analysis/clones.py` |
| Shared source IO and parse warnings | `src/scb_check/analysis/source.py` |
| Workflow orchestration, shared collection, diff pairing/failure exclusion | `src/scb_check/pipeline.py` |
| Parsed-file comparison and diff line sets | `src/scb_check/analysis/tree_diff.py` |
| Churn aggregation and summary rendering | `src/scb_check/reporting/churn.py` |
| `ast-grep` integration | `src/scb_check/analysis/astgrep.py` and `src/scb_check/resources/slop_rules/` |
| Structural rule behavior | `src/scb_check/rules/` |
| JSON scores or human rendering | `src/scb_check/reporting/` |
| Shared analysis/reporting records | `src/scb_check/models.py` |

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

## Adding a diff metric

Consume `pipeline.analyze_diff` rather than duplicating discovery or diffing; see the [library seam](architecture.md#tree-diff-library-seam). Keep `_collect_sources` private and build check-only indexes only in the check workflow. Compare parsed files in `analysis/tree_diff.py`; keep aggregation in reporting and add flat, prefixed JSON fields. Do not add a source-only mode, public collection type, registry, checkpoint pairing, or CLI thresholds to the churn path.

Diff behavioral tests live at the Typer CLI boundary in `tests/test_diff_cli.py`. Build two temporary directories and assert counts, output fields, exits, and stderr; no external diff binary is needed. Per-file statuses remain library data, not CLI output.

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
