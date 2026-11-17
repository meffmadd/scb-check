# Configuration and source directives

## Configuration discovery

`scb-check` looks for `scb-check.toml` or a `pyproject.toml` containing `[tool.scb-check]`, `[tool.ruff]`, or `[tool.ty.src]`, walking upward from the current directory until it hits a `.git` root. `--config FILE` selects an explicit file instead.

`diff` and `report` apply this one configuration to every snapshot; they do not load each source tree's config separately.

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

When using `pyproject.toml`, `scb-check` also includes excludes from:

- `[tool.ruff].exclude`
- `[tool.ruff].extend-exclude`
- `[tool.ty.src].exclude`

## Source directives

Python files support suppression of specific ast-grep or structural rule findings at the source line level:

```python
# scbc ignore[rule-id]
# scbc ignore[trivial-wrapper]
```

### Same-line form

```python
value = cfg.get("a", {}).get("b", {})  # scbc ignore[chained-dict-get] Boundary normalization for legacy webhook payloads.
```

### Standalone block form

```python
# scbc ignore[chained-dict-get]
# Boundary normalization for legacy webhook payloads.
value = cfg.get("a", {}).get("b", {})
```

### Multiple rule IDs

```python
# scbc ignore[chained-dict-get,dict-get-empty-dict-default]
# Legacy webhook payloads are partially populated and normalized downstream.
value = cfg.get("a", {}).get("b", {})
```

### Function boundary suppression

Function-level boundary suppression is available for code that intentionally validates or normalizes external input:

```python
def _load_toml(path: Path) -> dict[str, Any]:
    # scbc boundary: reads and validates user config
    ...
```

Boundary directives must be inside the function body, after the `def` line. By default, ast-grep findings inside that function are hidden, and informational ast-grep rules are omitted. `--include-all` shows ignored, informational, and boundary-suppressed ast-grep findings.

### Directive rules

- Rule IDs inside `ignore[...]` are required.
- Reason text is optional.
- Same-line ignore directives apply to that same physical line.
- Standalone ignore directives apply to the next non-blank, non-comment code line.
- Boundary directives apply to the containing function body.
- Ast-grep and structural rule findings are suppressible; clone and erosion findings are not.
- Invalid directives fail the run with exit code `2` unless `--include-all` is used.

These directives and both rule families are Python-only. See [source discovery](cli.md#source-discovery) for language coverage and [tree walking](tree-walking.md#source-directives) for parser details.
