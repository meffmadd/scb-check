# scb-check

Python CLI that reports SCBench verbosity and erosion composites for supported source codebases, and compares snapshot metrics between source trees.

- [Paper](https://arxiv.org/abs/2603.24755)
- [Source](https://github.com/gabeorlanski/scb-check)
- [SlopCodeBench (main repo)](https://github.com/SprocketLab/slop-code-bench)

- **Verbosity**: fraction of SLOC flagged by clone detection, ast-grep slop rules, or structural rules. Non-Python languages currently contribute clone lines only.
- **Erosion**: share of function "mass" (`complexity * sqrt(sloc)`) concentrated in high-complexity functions (cyclomatic complexity > 10).
- **Cognitive erosion**: same mass-share calculation using cognitive complexity > 10.
- **Metric deltas**: signed later-minus-earlier differences in scores, counts, and complexity masses from two full analyses.

## Install

Requires Python 3.12+.

Run without installing (recommended):

```bash
uvx scb-check check PATH
uvx --from git+https://github.com/gabeorlanski/scb-check scb-check check PATH
```

Or install into the current project:

```bash
uv sync              # for development in this repo
uv add scb-check     # as a dependency elsewhere
```

For hash-checked dependency installs from this repository, use the exported lock files:

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --require-hashes -r requirements-dev.lock
```

Regenerate them after dependency changes with:

```bash
uv export --format requirements.txt --no-dev --no-emit-project --frozen --output-file requirements.lock
uv export --format requirements.txt --all-groups --no-emit-project --frozen --output-file requirements-dev.lock
```

`scb-check` runs bundled ast-grep rules by trying a global `sg` executable first. If global `sg` is missing or fails, it falls back to the `ast-grep-cli` executable installed with `scb-check`.

## Usage

```bash
scb-check check PATH                    # human-readable flags
scb-check check PATH --output-format json  # JSON report with verbosity/erosion scores
scb-check check PATH --report           # shortcut for --output-format json
scb-check check PATH -v / --verbosity   # add info logging
scb-check check PATH -vv                # add debug logging
scb-check check PATH --config FILE      # explicit config path
scb-check check PATH --include-all      # include gitignored files plus ignored, lower-severity, and boundary-suppressed findings
scb-check check PATH --disable-sg  # skip ast-grep subprocess findings
scb-check check PATH --min-duplicate-lines N  # show duplicate groups with at least N SLOC lines
scb-check rule RULE_ID                  # print YAML or metadata for a specific rule
scb-check diff TREE_A TREE_B            # before / after / signed metric deltas
scb-check diff TREE_A TREE_B --output-format json  # structured metric comparison
scb-check diff TREE_A TREE_B --config FILE --disable-sg  # shared options for both analyses
```

`PATH` may be a file or directory. Directories are walked for supported source files: Python (`.py`, `.pyw`), Rust (`.rs`), JavaScript (`.js`, `.mjs`, `.cjs`), TypeScript (`.ts`), Zig (`.zig`), Haskell (`.hs`), and C++ (`.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hh`, `.hxx`). Directory discovery respects `.gitignore` globs by default; use `--include-all` to scan gitignored supported files too.

### Check JSON report fields

`verbosity`, `erosion`, `cog_erosion`, `files_scanned`, `total_loc`, `verbosity_flagged_loc`, `clone_loc`, `ast_grep_flagged_loc`, `structural_rule_loc`, `structural_rule_findings`, `total_functions`, `high_cc_functions`, `high_cog_functions`, `total_mass`, `high_cc_mass`, `total_cog_mass`, `high_cog_mass`, `syntax_tree_count`, `syntax_node_count`, and `syntax_by_language`.

`syntax_by_language` is keyed by language value and reports `tree_count` plus total Tree-sitter `node_count` for parsed files in that language.

### Comparing source trees

`scb-check diff TREE_A TREE_B` runs a full check analysis of each directory, including plain directories outside any git repository. `TREE_A` is the earlier snapshot; `TREE_B` is the later snapshot. Every delta is **after minus before**, including negative and zero values. The default human summary shows both resolved roots and before/after/delta columns for all scores, underlying counts, complexity masses, and syntax counts.

One configuration applies to both analyses: discovered from the current working directory, or selected with `--config FILE`. Tree-local configs are not loaded separately. Discovery uses each tree's applicable `.gitignore` files and the ordinary check exclusion semantics. `--include-all` has its full check meaning on both sides: include gitignored files plus ignored, informational, and boundary-suppressed findings; configured excludes and default excluded directories still apply. `--disable-sg` disables ast-grep on both sides. Otherwise each analysis can run the ordinary ast-grep subprocesses. Logging uses `-v` / `--verbosity` and `-vv` as with `check`. There is no `--report` alias, duplicate-display option, or threshold gate.

#### Diff JSON fields

- `tree_a`, `tree_b`: resolved directory paths, separate from measurements.
- `before`, `after`: each preserves the complete [check JSON report structure](#check-json-report-fields).
- `delta`: the same metric fields with signed differences. `syntax_by_language` contains the sorted union of languages; a missing language contributes zero counts for subtraction only. The snapshot mappings remain unchanged.

Scores and score deltas use fractional units in JSON. A score changing from `0.20` to `0.15` has delta `-0.05`. Human output displays scores as percentages and their differences as percentage points (`-5.00 percentage points`), not relative percentage changes. Counts and masses retain their existing units.

Individual read/parse failures warn and skip within their own analysis, without dropping the readable counterpart in the other tree. Each side must have at least one successfully parsed eligible file; zero-SLOC files are valid. Invalid directives retain check's error behavior. Optional ast-grep failures degrade as in check.

This measures snapshot changes, **not code churn**: literal edits or renames that preserve ordinary reports yield zero deltas. Zero aggregate deltas do not prove unchanged code or rule out offsetting local changes. A positive delta means a larger measurement, not necessarily a regression. See [Architecture](docs/architecture.md#snapshot-comparison) for interpretation and the pure Python report-comparison interface.

### Exit codes

`scb-check check` exits `0` when no findings are reported, `1` when any finding is present (clones, ast-grep hits, structural findings, or high-complexity functions), and `2` for usage errors (bad path, missing config, invalid directives).

`scb-check diff` exits `0` on success regardless of findings or delta signs, and `2` for invalid paths/config/options/directives or a side with no successfully parsed eligible files. Failures print to stderr without a partial comparison on stdout. It never exits `1`.

Clone detection only emits duplicated syntax blocks with at least two executable body statements. Function signatures, comments, blanks, and Python docstrings do not satisfy that threshold; displayed clone line counts and `--min-duplicate-lines` still use duplicated `SLOC` in the clone span.

## Configuration

scb-check looks for `scb-check.toml` or a `pyproject.toml` containing `[tool.scb-check]`, `[tool.ruff]`, or `[tool.ty.src]`, walking upward from the current directory until it hits a `.git` root.

```toml
# scb-check.toml
exclude = ["tests/fixtures/*", "vendor/**"]
context = 1

[low-use-short-function]
enabled = true
max-call-sites = 2
max-function-sloc = 5
max-inline-caller-sloc = 50
max-inline-caller-complexity = 10
max-inline-caller-cognitive-complexity = 10
max-inline-call-nesting = 3
```

```toml
# pyproject.toml
[tool.scb-check]
exclude = ["tests/fixtures/*"]
context = 2

[tool.scb-check.low-use-short-function]
enabled = true
```

- `exclude`: list of glob patterns to skip while discovering supported source files.
- `context`: number of surrounding source lines to show around human-readable ast-grep, structural rule, and erosion findings.
- `low-use-short-function`: opt-in budgets for the short low-use helper rule. Set `enabled = true` to enable it, then tune `max-call-sites`, `max-function-sloc`, `max-inline-caller-sloc`, `max-inline-caller-complexity`, `max-inline-caller-cognitive-complexity`, and `max-inline-call-nesting`.

Configured `exclude` patterns still apply when `--include-all` is used; only `.gitignore` file discovery is extended.

Ast-grep slop rules, structural rules, and source directives are currently Python-only. Rust, JavaScript, TypeScript, Zig, Haskell, and C++ still participate in SLOC totals, clone detection, cyclomatic erosion, and cognitive erosion.

When using `pyproject.toml`, scb-check also includes excludes from:

- `[tool.ruff].exclude`
- `[tool.ruff].extend-exclude`
- `[tool.ty.src].exclude`

## Source directives

In Python files, you can suppress specific ast-grep or structural rule findings at the source line level with:

```python
# scbc ignore[rule-id]
# scbc ignore[trivial-wrapper]
```

Same-line form:

```python
value = cfg.get("a", {}).get("b", {})  # scbc ignore[chained-dict-get] Boundary normalization for legacy webhook payloads.
```

Standalone block form:

```python
# scbc ignore[chained-dict-get]
# Boundary normalization for legacy webhook payloads.
value = cfg.get("a", {}).get("b", {})
```

Multiple rule IDs:

```python
# scbc ignore[chained-dict-get,dict-get-empty-dict-default]
# Legacy webhook payloads are partially populated and normalized downstream.
value = cfg.get("a", {}).get("b", {})
```

Function-level boundary suppression is available for code that intentionally validates or normalizes external input:

```python
def _load_toml(path: Path) -> dict[str, Any]:
    # scbc boundary: reads and validates user config
    ...
```

Boundary directives must be inside the function body, after the `def` line. By default, ast-grep findings inside that function are hidden, and informational ast-grep rules are omitted. Use `--include-all` to show ignored, informational, and boundary-suppressed ast-grep findings.

Rules:

- Rule IDs inside `ignore[...]` are required.
- Reason text is optional.
- Same-line ignore directives apply to that same physical line.
- Standalone ignore directives apply to the next non-blank, non-comment code line.
- Boundary directives apply to the containing function body.
- Ast-grep and structural rule findings are suppressible; clone and erosion findings are not.
- Invalid directives fail the run with exit code `2` unless `--include-all` is used.

## How it works

- **Tree walking**: language dispatch backed by tree-sitter grammars emits language-agnostic `ModuleIR` and semantic project context.
- **Clone detection**: hashed AST blocks across the scanned set; two or more matching instances become a `CloneBlock`.
- **Slop patterns**: Python ast-grep rules in `src/scb_check/resources/slop_rules/` split by category (e.g. `range(len(x))`, `dict.get(k, None)`, `isinstance` ladders, manual min/max, defensive guards).
- **Structural rules**: typed Python classes in `src/scb_check/rules/` run over tree-walking IR. `trivial-wrapper` flags removable single-return pass-through functions (identity returns and calls that only forward parameters to another scanned function), while semantic keep reasons skip constant returns, default-backed value providers, external calls, decorated functions, dunder methods, and inherited API implementations. `low-use-short-function` flags short helpers with few resolved call sites only when inlining them would stay within configured caller SLOC, complexity, cognitive complexity, and nesting budgets.
- **Extra local slop patterns**: set `SCB_CHECK_EXTRA_SLOP_RULES` to a `:`-separated list of YAML paths to layer additional rules on top of the bundled set.
- **Complexity**: per-function cyclomatic and cognitive complexity plus SLOC, combined into mass scores for erosion metrics.

## Documentation

- [Docs index](docs/index.md)
- [Architecture and concepts](docs/architecture.md)
- [Current status and development approach](docs/development.md)

## Development

```bash
uv run pytest
uv run ruff check
uv run ty check src/
```
