# `scb-check/` — package root

Layers:

- [`tree_walking/`](tree_walking/AGENTS.md) — source text → language-agnostic IR, SLOC, source directives, semantic project context
- [`rules/`](rules/AGENTS.md) — structural rules over tree-walking IR
- [`analysis/`](analysis/AGENTS.md) — ast-grep integration, clone detection, shared source IO, and comparison of parsed files
- [`reporting/`](reporting/AGENTS.md) — findings → output
- [`commands/`](commands/AGENTS.md) — CLI subcommand wiring
- This level — boundaries and shared types

## Modules at this level

- [`cli.py`](cli.py) — top-level Typer app wiring only. Defines the root command group and registers subcommands from [`commands/`](commands/AGENTS.md).
- [`pipeline.py`](pipeline.py) — sibling workflows `analyze(path, config) -> AnalysisResult` for a code state and `analyze_diff(tree_a, tree_b, config) -> TreeDiff` for change. Both use private `_collect_sources`; only check builds source indexes, semantic context, rules, clones, and flags. Diff owns root validation, relative-path pairing, and whole-path failure exclusion, then delegates parsed-file matching to analysis. `analyze_files(files)` retains explicit-file analysis.
- [`config.py`](config.py), [`walker.py`](walker.py) — IO boundaries. `load_config` walks upward to find `scb_check.toml` or `[tool.scb-check]`, stopping at a `.git` dir. `walk_source_files` discovers supported source suffixes; `walk_python_files` is retained for Python-only callers. Both apply `DEFAULT_EXCLUDED_DIRS`, `.gitignore` globs, and user `exclude` globs (supports `**`).
- [`logging.py`](logging.py) — structlog setup. `configure_logging(verbosity)` runs once from the CLI; modules elsewhere just call `get_logger(__name__)`.
- [`models.py`](models.py) — shared frozen dataclasses for reporting/analysis, including `TreeDiff` and `FileDiff`. Tree-walking IR models live in [`tree_walking/models.py`](tree_walking/models.py).

## Rules

- **Exit codes**: config errors and path errors exit 2 with a message on stderr; parse failures warn and skip the file.
- **New CLI command?** Add it under [`commands/`](commands/AGENTS.md), not as a new top-level module.
- **New module?** Put it in a layer, not here. This directory is for shared boundaries/types — adding more top-level modules blurs the split.
- **Pipeline helpers stay internal.** `_collect_sources`, `_index_check_sources`, `ParsedSources`, `Findings`, and flag-building helpers stay private to the workflows. Library callers use `analyze` / `AnalysisResult` or `analyze_diff` / `TreeDiff`, not intermediate collections. Keep source loading separate from check-only indexing; an absent side is not a failed read.
