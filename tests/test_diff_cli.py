from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from scb_check.cli import main
from scb_check.logging import get_logger
from scb_check.models import AstGrepHit

if TYPE_CHECKING:
    from click.testing import Result


def _invoke_diff(trees: tuple[Path, Path], *options: str) -> Result:
    return CliRunner().invoke(
        main,
        ["diff", *(str(tree) for tree in trees), *options],
    )


def _json_diff(trees: tuple[Path, Path], *options: str) -> dict[str, Any]:
    result = _invoke_diff(trees, "--output-format", "json", *options)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _json_check(tree: Path, *options: str) -> dict[str, Any]:
    result = CliRunner().invoke(
        main,
        ["check", str(tree), "--output-format", "json", *options],
    )
    assert result.exit_code in (0, 1), result.output
    return json.loads(result.stdout)


@pytest.fixture
def trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create two plain trees with shared config and controlled optional tooling."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "scb_check.pipeline.run_sg", lambda _files, _rules_path: ()
    )
    (tmp_path / "scb-check.toml").write_text("", encoding="utf-8")
    tree_a = tmp_path / "earlier"
    tree_b = tmp_path / "later"
    tree_a.mkdir()
    tree_b.mkdir()
    return tree_a, tree_b


def test_diff_compares_full_check_reports(trees: tuple[Path, Path]) -> None:
    """Snapshot values match check; deltas are signed later-minus-earlier values."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tree_b / "sample.py").write_text(
        "value = 2\nother = 3\n", encoding="utf-8"
    )

    payload = _json_diff(trees)

    assert payload.keys() == {"tree_a", "tree_b", "before", "after", "diff"}
    assert payload["tree_a"] == str(tree_a.resolve())
    assert payload["tree_b"] == str(tree_b.resolve())
    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    assert payload["diff"] == {
        "verbosity": {
            "score": 0.0,
            "files_scanned": 0,
            "total_loc": 1,
            "flagged_loc": 0,
            "clone_loc": 0,
            "ast_grep_flagged_loc": 0,
            "structural_rule_loc": 0,
            "structural_rule_findings": 0,
        },
        "erosion": {
            "score": 0.0,
            "total_functions": 0,
            "high_cc_functions": 0,
            "total_mass": 0.0,
            "high_cc_mass": 0.0,
        },
        "cog_erosion": {
            "score": 0.0,
            "total_functions": 0,
            "high_cog_functions": 0,
            "total_cog_mass": 0.0,
            "high_cog_mass": 0.0,
        },
        "syntax": {
            "tree_count": 0,
            "node_count": 5,
            "python.tree_count": 0,
            "python.node_count": 5,
        },
    }
    reverse = _json_diff((tree_b, tree_a))
    assert reverse["before"] == payload["after"]
    assert reverse["after"] == payload["before"]
    assert reverse["diff"]["verbosity"]["total_loc"] == -1
    assert reverse["diff"]["syntax"]["node_count"] == -5


def test_diff_shows_ratio_decrease_despite_growing_flagged_count(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absolute score differences do not hide a growing flagged numerator."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text(
        "flagged = 1\nclean = 1\n", encoding="utf-8"
    )
    (tree_b / "sample.py").write_text(
        "flagged = 1\nflagged_again = 2\n" + "clean = 1\n" * 6,
        encoding="utf-8",
    )

    def hits(
        files: tuple[Path, ...], _rules_path: Path
    ) -> tuple[AstGrepHit, ...]:
        return tuple(
            AstGrepHit(file, line, line, 0, 1, "json-loads-read", text)
            for file in files
            for line, text in enumerate(
                file.read_text(encoding="utf-8").splitlines(), 1
            )
            if text.startswith("flagged")
        )

    monkeypatch.setattr("scb_check.pipeline.run_sg", hits)
    payload = _json_diff(trees)

    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    assert payload["before"]["verbosity"]["score"] == 0.5
    assert payload["after"]["verbosity"]["score"] == 0.25
    assert payload["diff"]["verbosity"]["score"] == pytest.approx(-0.25)
    assert payload["diff"]["verbosity"]["flagged_loc"] == 1
    assert payload["diff"]["verbosity"]["ast_grep_flagged_loc"] == 1
    reverse = _json_diff((tree_b, tree_a))
    assert reverse["diff"]["verbosity"]["score"] == pytest.approx(0.25)
    result = _invoke_diff(trees, "-vv")
    assert result.exit_code == 0, result.output
    assert str(tree_a) in result.stdout
    assert str(tree_b) in result.stdout
    assert all(
        label in result.stdout
        for label in (
            "before",
            "after",
            "diff",
            "verbosity.score",
            "total_loc",
            "total_mass",
        )
    )
    assert "50.00%" in result.stdout
    assert "25.00%" in result.stdout
    assert "-25.00 percentage points" in result.stdout


def test_diff_compares_complexity_counts_and_masses(
    trees: tuple[Path, Path],
) -> None:
    """Complexity scores retain their thresholds, mass formula, and units."""
    tree_a, tree_b = trees
    (tree_a / "route.py").write_text(
        "def route(value):\n    return 0\n", encoding="utf-8"
    )
    branches = "".join(
        f"    if value == {index}:\n        return {index}\n"
        for index in range(11)
    )
    (tree_b / "route.py").write_text(
        f"def route(value):\n{branches}    return -1\n\ndef stable():\n    return 1\n",
        encoding="utf-8",
    )

    payload = _json_diff(trees)

    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    difference = payload["diff"]
    assert difference["verbosity"]["total_loc"] == 24
    assert difference["erosion"]["total_functions"] == difference["cog_erosion"]["total_functions"] == 1
    assert difference["erosion"]["high_cc_functions"] == difference["cog_erosion"]["high_cog_functions"] == 1
    assert difference["erosion"]["high_cc_mass"] == pytest.approx(58.78775382679627)
    assert difference["erosion"]["total_mass"] == pytest.approx(58.78775382679627)
    assert difference["cog_erosion"]["high_cog_mass"] == pytest.approx(53.88877434122992)
    assert difference["cog_erosion"]["total_cog_mass"] == pytest.approx(53.88877434122992)
    assert difference["erosion"]["score"] == pytest.approx(0.976508474)
    assert difference["cog_erosion"]["score"] == 1.0
    reverse = _json_diff((tree_b, tree_a))
    for group, result in difference.items():
        for name, value in result.items():
            assert reverse["diff"][group][name] == pytest.approx(-value)
    human = _invoke_diff(trees)
    mass_rows = [row for row in human.stdout.splitlines() if "mass" in row]
    assert mass_rows
    assert all("%" not in row and "percentage" not in row for row in mass_rows)


def test_diff_keeps_full_tree_clone_context_and_source_directives(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged file joins an after-only clone; directive filtering stays normal."""
    tree_a, tree_b = trees
    source = "def compute(value):\n    total = value + 1\n    doubled = total * 2\n    tripled = doubled * 3\n    return tripled\n"
    for tree in trees:
        (tree / "original.py").write_text(source, encoding="utf-8")
        directive = "# scbc ignore[trivial-wrapper]\n" if tree == tree_b else ""
        (tree / "wrapper.py").write_text(
            f"{directive}def passthrough(value):\n    return value\n",
            encoding="utf-8",
        )
    (tree_b / "copy.py").write_text(source, encoding="utf-8")

    def hits(
        files: tuple[Path, ...], _rules_path: Path
    ) -> tuple[AstGrepHit, ...]:
        return tuple(
            AstGrepHit(file, 2, 2, 0, 1, "json-loads-read", "total = value + 1")
            for file in files
            if file.name == "original.py"
        )

    monkeypatch.setattr("scb_check.pipeline.run_sg", hits)
    payload = _json_diff(trees)

    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    assert payload["before"]["verbosity"]["clone_loc"] == 0  # Independent projects.
    assert payload["after"]["verbosity"]["clone_loc"] == 10
    assert payload["diff"]["verbosity"]["files_scanned"] == 1
    assert payload["diff"]["verbosity"]["clone_loc"] == 10
    assert payload["diff"]["verbosity"]["structural_rule_loc"] == -2
    assert payload["diff"]["verbosity"]["structural_rule_findings"] == -1
    assert payload["after"]["verbosity"]["flagged_loc"] == 10  # Clone/ast union.
    assert payload["diff"]["verbosity"]["flagged_loc"] == 7
    assert payload["diff"]["verbosity"]["ast_grep_flagged_loc"] == 0


def test_diff_preserves_three_way_verbosity_union(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clone, ast-grep, and structural overlap counts once, excluding non-SLOC."""
    config = trees[0].parent / "scb-check.toml"
    config.write_text("[low-use-short-function]\nenabled = true\n", encoding="utf-8")
    source = (
        'def first(value):\n    """Docs."""\n    # notes\n    cleaned = value.strip()\n\n    return cleaned\n\n'
        'def second(value):\n    """Docs."""\n    cleaned = value.strip()\n\n    return cleaned\n\n'
        "def route(value):\n    return first(value) + second(value)\n"
    )
    for tree in trees:
        (tree / "sample.py").write_text(source, encoding="utf-8")

    def hits(files: tuple[Path, ...], _rules_path: Path) -> tuple[AstGrepHit, ...]:
        return tuple(
            AstGrepHit(file, start, end, 0, 1, "json-loads-read", "cleaned")
            for file in files
            for start, end in ((2, 4), (9, 10))
        )

    monkeypatch.setattr("scb_check.pipeline.run_sg", hits)
    payload = _json_diff(trees)

    assert payload["before"] == payload["after"] == _json_check(trees[0]) == _json_check(trees[1])
    assert payload["before"]["verbosity"] == {
        "score": 0.75,
        "files_scanned": 1,
        "total_loc": 8,
        "flagged_loc": 6,
        "clone_loc": 6,
        "ast_grep_flagged_loc": 2,
        "structural_rule_loc": 6,
        "structural_rule_findings": 2,
    }
    assert all(value == 0 for value in payload["diff"]["verbosity"].values())


@pytest.mark.parametrize(("branches", "high_cc", "high_cog"), [(9, 0, 0), (10, 1, 0), (11, 1, 1)])
def test_diff_uses_strict_complexity_thresholds(
    trees: tuple[Path, Path], branches: int, high_cc: int, high_cog: int,
) -> None:
    """Cyclomatic and cognitive thresholds are independently strictly above ten."""
    (trees[0] / "sample.py").write_text("", encoding="utf-8")
    body = "".join(f"    if value == {index}:\n        return {index}\n" for index in range(branches))
    (trees[1] / "sample.py").write_text(f"def route(value):\n{body}    return -1\n", encoding="utf-8")

    payload = _json_diff(trees)

    assert payload["before"] == _json_check(trees[0])
    assert payload["after"] == _json_check(trees[1])
    for group, count_field, expected in (("erosion", "high_cc_functions", high_cc), ("cog_erosion", "high_cog_functions", high_cog)):
        assert payload["after"][group][count_field] == payload["diff"][group][count_field] == expected
        assert payload["after"][group]["score"] == payload["diff"][group]["score"] == expected
        assert payload["after"][group]["total_functions"] == 1


@pytest.mark.parametrize("change", ["identical", "literal", "rename"])
def test_diff_zero_deltas_measure_metrics_not_edit_volume(
    trees: tuple[Path, Path],
    change: str,
) -> None:
    """Identical reports stay zero even when text or file names differ."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tree_b / ("renamed.py" if change == "rename" else "sample.py")).write_text(
        "value = 2\n" if change == "literal" else "value = 1\n",
        encoding="utf-8",
    )

    payload = _json_diff(trees)

    assert (
        payload["before"]
        == payload["after"]
        == _json_check(tree_a)
        == _json_check(tree_b)
    )
    assert payload["diff"].keys() == payload["before"].keys()
    for group, result in payload["diff"].items():
        assert result.keys() == payload["before"][group].keys()
        assert all(value == 0 for value in result.values())
    result = _invoke_diff(trees)
    assert result.exit_code == 0
    assert "+0.00 percentage points" in result.stdout
    assert "syntax.python.node_count" in result.stdout


def test_diff_compares_language_union_without_changing_snapshot_maps(
    trees: tuple[Path, Path],
) -> None:
    """All supported languages contribute counts; only delta zero-fills missing ones."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text("value = 1\n", encoding="utf-8")
    samples = {
        "sample.rs": "fn value() -> i32 {\n    1\n}\n",
        "sample.js": "function value() {\n    return 1;\n}\n",
        "sample.ts": "function value(): number {\n    return 1;\n}\n",
        "sample.zig": "pub fn value() u32 {\n    return 1;\n}\n",
        "Sample.hs": "value :: Int\nvalue = 1\n",
        "sample.cpp": "int value() {\n    return 1;\n}\n",
    }
    for name, source in samples.items():
        (tree_b / name).write_text(source, encoding="utf-8")

    payload = _json_diff(trees)

    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    assert set(payload["before"]["syntax"]) == {
        "tree_count", "node_count", "python.tree_count", "python.node_count",
    }
    syntax = payload["diff"]["syntax"]
    assert list(syntax) == [
        "tree_count", "node_count",
        "cpp.tree_count", "cpp.node_count",
        "haskell.tree_count", "haskell.node_count",
        "javascript.tree_count", "javascript.node_count",
        "python.tree_count", "python.node_count",
        "rust.tree_count", "rust.node_count",
        "typescript.tree_count", "typescript.node_count",
        "zig.tree_count", "zig.node_count",
    ]
    assert syntax["python.tree_count"] == -1
    assert syntax["python.node_count"] == -6
    for language in ("cpp", "haskell", "javascript", "rust", "typescript", "zig"):
        assert payload["after"]["syntax"][f"{language}.tree_count"] == syntax[f"{language}.tree_count"] == 1
        assert payload["after"]["syntax"][f"{language}.node_count"] == syntax[f"{language}.node_count"] > 0
    assert "python.tree_count" not in payload["after"]["syntax"]
    assert payload["diff"]["verbosity"]["total_loc"] == 11
    assert payload["diff"]["verbosity"]["files_scanned"] == syntax["tree_count"] == 5
    reverse = _json_diff((tree_b, tree_a))
    assert reverse["diff"]["syntax"] == {name: -value for name, value in syntax.items()}


def test_diff_compares_shared_added_and_removed_languages(
    trees: tuple[Path, Path],
) -> None:
    """Language additions and removals do not hide changes in a shared language."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tree_b / "sample.py").write_text(
        "value = 1\nother = 2\n", encoding="utf-8"
    )
    (tree_a / "removed.js").write_text("", encoding="utf-8")
    (tree_b / "added.rs").write_text("", encoding="utf-8")

    payload = _json_diff(trees)

    assert payload["before"] == _json_check(tree_a)
    assert payload["after"] == _json_check(tree_b)
    assert payload["diff"]["syntax"] == {
        "tree_count": 0,
        "node_count": 5,
        "javascript.tree_count": -1,
        "javascript.node_count": -1,
        "python.tree_count": 0,
        "python.node_count": 5,
        "rust.tree_count": 1,
        "rust.node_count": 1,
    }


def test_diff_is_deterministic_finite_and_resolves_tree_context(
    trees: tuple[Path, Path],
) -> None:
    """Controlled repeated comparisons emit identical JSON with resolved roots."""
    for tree in trees:
        (tree / "sample.py").write_text("value = 1\n" * 30, encoding="utf-8")
    relative_trees = (Path("earlier/../earlier"), Path("later"))
    first = _invoke_diff(relative_trees, "--output-format", "json")
    second = _invoke_diff(relative_trees, "--output-format", "json")

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["tree_a"] == str(trees[0])
    assert payload["tree_b"] == str(trees[1])
    for name in ("before", "after", "diff"):
        assert all(
            math.isfinite(value)
            for result in payload[name].values()
            for value in result.values()
        )


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("include_all", [False, True])
def test_diff_shared_config_preserves_check_exclusions_and_rule_settings(
    trees: tuple[Path, Path],
    *,
    explicit: bool,
    include_all: bool,
) -> None:
    """One cwd/override config governs both trees without rebasing excludes."""
    tree_a, tree_b = trees
    config_path = tree_a.parent / (
        "override.toml" if explicit else "scb-check.toml"
    )
    config_path.write_text(
        'exclude = ["**/excluded.py", "earlier/local.py"]\n[low-use-short-function]\nenabled = true\n',
        encoding="utf-8",
    )
    if explicit:
        (tree_a.parent / "scb-check.toml").write_text(
            "unknown = true\n", encoding="utf-8"
        )
    (tree_a.parent / ".gitignore").write_text("ancestor.py\n", encoding="utf-8")
    for tree in trees:
        (tree / "scb-check.toml").write_text(
            "unknown = true\n", encoding="utf-8"
        )
        (tree / "keep.py").write_text(
            'def clean(value):\n    return value.strip()\n\ndef route(value):\n    cleaned = clean(value)\n    return f"<{cleaned}>"\n',
            encoding="utf-8",
        )
        for name in ("only-a.py", "only-b.py", "local.py", "ancestor.py"):
            (tree / name).write_text("value = 1\n", encoding="utf-8")
        (tree / "nested").mkdir()
        (tree / "nested/.gitignore").write_text(
            "ignored.py\n", encoding="utf-8"
        )
        (tree / "nested/ignored.py").write_text("value = 1\n", encoding="utf-8")
        for name in ("excluded.py", "README.md", "requirements.txt"):
            (tree / name).write_text("def bad(:\n", encoding="utf-8")
        for name in ("build", "node_modules"):
            (tree / name).mkdir()
            (tree / name / "noise.py").write_text(
                "def bad(:\n", encoding="utf-8"
            )
    (tree_a / ".gitignore").write_text("only-a.py\n", encoding="utf-8")
    (tree_b / ".gitignore").write_text("only-b.py\n", encoding="utf-8")
    options = (["--config", str(config_path)] if explicit else []) + (
        ["--include-all"] if include_all else []
    )

    payload = _json_diff(trees, *options)

    assert payload["before"] == _json_check(tree_a, *options)
    assert payload["after"] == _json_check(tree_b, *options)
    assert payload["before"]["verbosity"]["files_scanned"] == (5 if include_all else 2)
    assert payload["after"]["verbosity"]["files_scanned"] == (6 if include_all else 3)
    assert (
        payload["before"]["verbosity"]["structural_rule_findings"]
        == payload["after"]["verbosity"]["structural_rule_findings"]
        == 1
    )
    assert payload["diff"]["verbosity"]["files_scanned"] == payload["diff"]["verbosity"]["total_loc"] == 1


@pytest.mark.parametrize("include_all", [False, True])
def test_diff_include_all_has_full_check_suppression_semantics(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_all: bool,
) -> None:
    """Include-all controls discovery, ignores, severity, and boundary suppression."""
    for tree in trees:
        (tree / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (tree / "ignored.py").write_text("value = 1\n", encoding="utf-8")
        (tree / "sample.py").write_text(
            "# scbc ignore[trivial-wrapper]\ndef wrapper(value):\n    return value\n\n"
            'def boundary(raw):\n    # scbc boundary\n    result = raw.get("a")\n    return result\n'
            "# scbc ignore[json-loads-read]\nignored = 1\ninfo = None\n",
            encoding="utf-8",
        )

    def hits(
        files: tuple[Path, ...], _rules_path: Path
    ) -> tuple[AstGrepHit, ...]:
        return tuple(
            AstGrepHit(file, line, line, 0, 1, rule_id, "value")
            for file in files
            if file.name == "sample.py"
            for line, rule_id in (
                (7, "json-loads-read"),
                (10, "json-loads-read"),
                (11, "redundant-return-none"),
            )
        )

    monkeypatch.setattr("scb_check.pipeline.run_sg", hits)
    options = ["--include-all"] if include_all else []
    payload = _json_diff(trees, *options)

    for group, tree in zip(("before", "after"), trees, strict=True):
        assert payload[group] == _json_check(tree, *options)
        assert payload[group]["verbosity"]["files_scanned"] == (2 if include_all else 1)
        assert payload[group]["verbosity"]["ast_grep_flagged_loc"] == (3 if include_all else 0)
        assert payload[group]["verbosity"]["structural_rule_findings"] == (1 if include_all else 0)
        assert payload[group]["verbosity"]["flagged_loc"] == (5 if include_all else 0)


@pytest.mark.parametrize("tooling", ["disabled", "unavailable"])
def test_diff_without_ast_grep_retains_other_measurements(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tooling: str,
) -> None:
    """Disabling or losing optional tooling still reports structural findings."""
    for tree in trees:
        (tree / "sample.py").write_text(
            "def wrapper(value):\n    return value\n", encoding="utf-8"
        )

    def no_tool(
        _files: tuple[Path, ...], _rules_path: Path
    ) -> tuple[AstGrepHit, ...]:
        if tooling == "disabled":
            pytest.fail("disabled ast-grep must not execute")
        get_logger(__name__).warning("ast-grep binary not found")
        return ()

    monkeypatch.setattr("scb_check.pipeline.run_sg", no_tool)
    options = ["--disable-sg"] if tooling == "disabled" else []
    result = _invoke_diff(trees, "--output-format", "json", *options)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    for group, tree in zip(("before", "after"), trees, strict=True):
        assert payload[group] == _json_check(tree, *options)
        assert payload[group]["verbosity"]["ast_grep_flagged_loc"] == 0
        assert payload[group]["verbosity"]["structural_rule_findings"] == 1
        assert payload[group]["erosion"]["total_functions"] == 1
        assert payload[group]["cog_erosion"]["total_functions"] == 1
    if tooling == "unavailable":
        assert "ast-grep binary not found" in result.stderr


@pytest.mark.parametrize("failed_side", [0, 1])
@pytest.mark.parametrize("failure", ["read", "parse"])
def test_diff_warns_and_skips_failures_independently(
    trees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    failed_side: int,
    failure: str,
) -> None:
    """A bad file does not remove its readable counterpart from the other report."""
    for tree in trees:
        (tree / "ok.py").write_text("stable = 1\n", encoding="utf-8")
        (tree / "problem.py").write_text("value = 1\n", encoding="utf-8")
    problem = trees[failed_side] / "problem.py"
    if failure == "parse":
        problem.write_text("def bad(:\n", encoding="utf-8")
    else:
        original_read_text = Path.read_text

        def read_text(
            file_path: Path,
            encoding: str | None = None,
            errors: str | None = None,
        ) -> str:
            if file_path == problem:
                raise PermissionError("cannot read source")
            return original_read_text(
                file_path, encoding=encoding, errors=errors
            )

        monkeypatch.setattr(Path, "read_text", read_text)
    result = _invoke_diff(trees, "--output-format", "json")

    assert result.exit_code == 0, result.output
    assert "failed to parse file" in result.stderr
    assert str(problem) in result.stderr
    payload = json.loads(result.stdout)
    for side, group in enumerate(("before", "after")):
        assert payload[group] == _json_check(trees[side])
        assert payload[group]["verbosity"]["files_scanned"] == (1 if side == failed_side else 2)
    assert payload["diff"]["verbosity"]["files_scanned"] == (1 if failed_side == 0 else -1)
    assert payload["diff"]["verbosity"]["total_loc"] == (1 if failed_side == 0 else -1)


@pytest.mark.parametrize("invalid_side", [0, 1])
def test_diff_preserves_utf8_replacement_behavior(
    trees: tuple[Path, Path], invalid_side: int
) -> None:
    """The shared reader warns for invalid UTF-8 but still analyzes valid code."""
    for side, tree in enumerate(trees):
        notes = b"# notes: \xff\n" if side == invalid_side else b"# notes\n"
        (tree / "sample.py").write_bytes(notes + b"value = 1\n")
    result = _invoke_diff(trees, "--output-format", "json")

    assert result.exit_code == 0, result.output
    assert "not valid UTF-8" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == _json_check(trees[0])
    assert payload["after"] == _json_check(trees[1])
    assert payload["before"]["verbosity"]["files_scanned"] == payload["after"]["verbosity"]["files_scanned"] == 1
    assert payload["diff"]["verbosity"]["total_loc"] == 0


@pytest.mark.parametrize("invalid_side", [0, 1])
@pytest.mark.parametrize("path_kind", ["missing", "file"])
def test_diff_validates_both_directory_arguments_before_analysis(
    trees: tuple[Path, Path],
    invalid_side: int,
    path_kind: str,
) -> None:
    """Bad paths take precedence over analysis and never produce partial output."""
    for tree in trees:
        (tree / "sample.py").write_text(
            "# scbc ignore[unknown-rule]\nvalue = 1\n", encoding="utf-8"
        )
    invalid_path = trees[invalid_side] / (
        "missing" if path_kind == "missing" else "sample.py"
    )
    paths = (
        (invalid_path, trees[1])
        if invalid_side == 0
        else (trees[0], invalid_path)
    )

    result = _invoke_diff(paths, "--output-format", "json")

    assert result.exit_code == 2
    assert (
        "tree_a" if invalid_side == 0 else "tree_b"
    ) in result.stderr.lower()
    assert invalid_path.name in result.stderr
    assert ("exist" if path_kind == "missing" else "file") in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("empty_side", [0, 1])
@pytest.mark.parametrize(
    "contents", ["empty", "unsupported", "ignored", "broken"]
)
def test_diff_requires_successful_analysis_on_each_side(
    trees: tuple[Path, Path],
    empty_side: int,
    contents: str,
) -> None:
    """A missing measurement is not a zero report, even with a usable other tree."""
    (trees[1 - empty_side] / "ok.py").write_text(
        "value = 1\n", encoding="utf-8"
    )
    empty_tree = trees[empty_side]
    if contents == "unsupported":
        (empty_tree / "README.md").write_text("notes\n", encoding="utf-8")
    elif contents == "ignored":
        (empty_tree / ".gitignore").write_text("*.py\n", encoding="utf-8")
        (empty_tree / "sample.py").write_text("value = 1\n", encoding="utf-8")
    elif contents == "broken":
        (empty_tree / "sample.py").write_text("def bad(:\n", encoding="utf-8")

    result = _invoke_diff(trees, "--output-format", "json")

    assert result.exit_code == 2
    assert "no supported source files" in result.stderr
    assert str(empty_tree) in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "contents", ["", "# comment only\n", '"""module docs"""\n']
)
def test_diff_accepts_parsed_zero_sloc_files(
    trees: tuple[Path, Path], contents: str
) -> None:
    """Zero SLOC is valid when files have been successfully parsed."""
    for tree in trees:
        (tree / "sample.py").write_text(contents, encoding="utf-8")
    payload = _json_diff(trees)

    assert payload["before"] == payload["after"] == _json_check(trees[0])
    assert payload["before"]["verbosity"]["files_scanned"] == 1
    assert payload["before"]["verbosity"]["total_loc"] == 0
    assert all(payload["before"][group]["score"] == 0 for group in ("verbosity", "erosion", "cog_erosion"))
    assert payload["diff"]["verbosity"]["files_scanned"] == payload["diff"]["verbosity"]["total_loc"] == 0


@pytest.mark.parametrize("invalid_side", [0, 1])
@pytest.mark.parametrize(
    "directive", ["# scbc ignore[unknown-rule]", "# scbc boundary"]
)
def test_diff_invalid_directives_fail_without_partial_payload(
    trees: tuple[Path, Path],
    invalid_side: int,
    directive: str,
) -> None:
    """Directive errors retain check's usage-error contract on either side."""
    for side, tree in enumerate(trees):
        (tree / "sample.py").write_text(
            (directive + "\n" if side == invalid_side else "") + "value = 1\n",
            encoding="utf-8",
        )

    result = _invoke_diff(trees, "--output-format", "json")

    assert result.exit_code == 2
    assert (
        "unknown rule id" if "ignore[" in directive else "scbc boundary"
    ) in result.stderr
    assert str(trees[invalid_side] / "sample.py") in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("config", ["exclude = 42\n", "not valid TOML"])
@pytest.mark.parametrize("explicit", [False, True])
def test_diff_reports_config_errors(
    trees: tuple[Path, Path], config: str, *, explicit: bool
) -> None:
    """Discovered and explicit invalid configs fail with stderr and no payload."""
    config_path = trees[0].parent / "scb-check.toml"
    config_path.write_text(config, encoding="utf-8")
    for tree in trees:
        (tree / "sample.py").write_text("value = 1\n", encoding="utf-8")
    options = ["--config", str(config_path)] if explicit else []

    result = _invoke_diff(trees, "--output-format", "json", *options)

    assert result.exit_code == 2
    assert str(config_path) in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "options",
    [
        ["--report"],
        ["--threshold", "1"],
        ["--min-duplicate-lines", "5"],
        ["--output-format", "yaml"],
        ["--config", "missing.toml"],
    ],
)
def test_diff_rejects_invalid_options(
    trees: tuple[Path, Path], options: list[str]
) -> None:
    """Reject unsupported options, output formats, and missing config overrides."""
    result = _invoke_diff(trees, *options)

    assert result.exit_code == 2
    assert result.stderr
    assert result.stdout == ""
