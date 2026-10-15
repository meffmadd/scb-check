# `analysis/` — finding helpers, source IO, and parsed-file comparison

This layer keeps analysis that is intentionally separate from generic tree walking:

- [`astgrep.py`](astgrep.py) shells out to the `sg` binary and returns ast-grep hits.
- [`clones.py`](clones.py) uses parser-native tree-sitter data preserved on parsed file artifacts to hash duplicate syntax blocks across supported languages.
- [`source.py`](source.py) is the shared source IO/dispatch boundary for check and diff, with UTF-8 replacement fallback and warn-and-skip failures.
- [`tree_diff.py`](tree_diff.py) exposes `compare_file(path, before, after) -> FileDiff`: pure comparison of already-parsed versions. `None` means absent, not failed. SLOC filtering, deterministic text matching, status, and original line positions live here; discovery and read/parse failure exclusion live in `pipeline.analyze_diff`.

Source directives, SLOC accounting, parser dispatch, symbol extraction, string-literal helpers, semantic context, and structural rules live under [`../tree_walking/`](../tree_walking/) and [`../rules/`](../rules/), not here.

## Invariants

- **Line numbers are 1-indexed at the module boundary.** Tree-sitter exposes 0-indexed `.start_point[0]`; clone findings emit `+ 1`.
- **Clone and diff line counts use `ParsedFile.module.sloc_lines`.** Filter each diff side to SLOC before matching retained text; non-SLOC lines must never act as match anchors. Return original 1-indexed source positions for changes. Do not reintroduce a second SLOC implementation in this layer.
- **Comparison keeps presence separate from churn.** Return a record for unchanged and zero-SLOC files. Status reflects presence and retained SLOC text, so edits confined to non-SLOC lines are `unchanged`. The pipeline pairs relative paths and excludes read/parse failures before calling `compare_file`; at least one version exists.
- **Keep diff deterministic and dependency-free.** Use newline-normalized SLOC text with no phantom final line and `SequenceMatcher` with autojunk disabled. Preserve indentation, whitespace, and inline comments on retained lines; source positions are not match anchors. Walker remains the only eligibility policy. Churn aggregation belongs in reporting.
- **Most findings are frozen dataclasses** from [`../models.py`](../models.py); emit tuples across module boundaries, never lists.

## Scoring-sensitive surfaces

These drive the verbosity/erosion numbers — change with care:

- `CLONE_NODE_TYPES` in [`clones.py`](clones.py) and language clone configs under [`../tree_walking/languages/`](../tree_walking/languages/) — which block types get hashed.
- `_hash_ast_subtree` / `_normalize_ast` — identifier and literal normalization.

## ast-grep boundary

[`astgrep.run_sg`](astgrep.py) tries a global `sg` binary first, then falls back to package-managed ast-grep executables next to Python if global `sg` is missing or fails. It returns `()` when no binary succeeds, OSError persists, all exits are non-zero, or JSON is unparseable — it **never raises**. That's deliberate: a missing ast-grep binary degrades gracefully rather than failing the run. Tests monkeypatch `scb_check.pipeline.run_sg` (where it's imported) rather than the subprocess itself.
