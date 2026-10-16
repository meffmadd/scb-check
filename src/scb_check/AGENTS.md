# `scb-check/` — package root

Layers:

- [`tree_walking/`](tree_walking/AGENTS.md) — source text → language-agnostic IR, SLOC, source directives, semantic project context
- [`rules/`](rules/AGENTS.md) — structural rules over tree-walking IR
- [`analysis/`](analysis/AGENTS.md) — ast-grep integration, clone detection, and shared source IO
- [`reporting/`](reporting/AGENTS.md) — findings → output
- [`commands/`](commands/AGENTS.md) — CLI subcommand wiring
- This level — boundaries and shared types

## Modules at this level

- [`cli.py`](cli.py) — top-level Typer app wiring only. Defines the root command group and registers subcommands from [`commands/`](commands/AGENTS.md).
- [`pipeline.py`](pipeline.py) — `analyze(path, config) -> AnalysisResult` and explicit-file `analyze_files(files)` perform full snapshot analysis through `analysis.source.read_and_parse_source`, source indexes, semantic context, rules, clones, and flags. Check uses one analysis; diff orchestrates two independent analyses in its command boundary and compares scored reports in reporting.
- [`config.py`](config.py), [`walker.py`](walker.py) — IO boundaries. `load_config` walks upward to find `scb_check.toml` or `[tool.scb-check]`, stopping at a `.git` dir. `walk_source_files` discovers supported source suffixes; `walk_python_files` is retained for Python-only callers. Both apply `DEFAULT_EXCLUDED_DIRS`, `.gitignore` globs, and user `exclude` globs (supports `**`).
- [`logging.py`](logging.py) — structlog setup. `configure_logging(verbosity)` runs once from the CLI; modules elsewhere just call `get_logger(__name__)`.
- [`models.py`](models.py) — shared frozen dataclasses for reporting/analysis, including `Flags` and `Report`. Tree-walking IR models live in [`tree_walking/models.py`](tree_walking/models.py).

## Rules

- **Exit codes**: config errors and path errors exit 2 with a message on stderr; parse failures warn and skip the file.
- **New CLI command?** Add it under [`commands/`](commands/AGENTS.md), not as a new top-level module.
- **New module?** Put it in a layer, not here. This directory is for shared boundaries/types — adding more top-level modules blurs the split.
- **Pipeline helpers stay internal.** `_index_check_sources`, `ParsedSources`, `Findings`, and flag-building helpers stay private to analysis. Library callers use `analyze` / `AnalysisResult`; report comparison consumes `Report` values in reporting, not intermediate source collections.
