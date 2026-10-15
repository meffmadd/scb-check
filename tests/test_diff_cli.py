from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scb_check.cli import main


def _json_diff(trees: tuple[Path, Path], *options: str) -> dict[str, str | int | float]:
    result = CliRunner().invoke(
        main,
        ["diff", *(str(tree) for tree in trees), "--output-format", "json", *options],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.fixture
def trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create two plain trees with configuration discovered from their parent."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scb-check.toml").write_text("", encoding="utf-8")
    tree_a = tmp_path / "earlier"
    tree_b = tmp_path / "later"
    tree_a.mkdir()
    tree_b.mkdir()
    return tree_a, tree_b


def test_diff_reports_sloc_churn_and_retains_unchanged_files(
    trees: tuple[Path, Path],
) -> None:
    """A replacement counts both sides and unchanged files stay in the union."""
    tree_a, tree_b = trees
    (tree_a / "changed.py").write_text("value = 1\n", encoding="utf-8")
    (tree_b / "changed.py").write_text("value = 2\nnext_value = 3\n", encoding="utf-8")
    for tree in trees:
        (tree / "unchanged.py").write_text("stable = True\n", encoding="utf-8")

    assert _json_diff(trees) == {
        "tree_a": str(tree_a),
        "tree_b": str(tree_b),
        "eligible_file_union_count": 2,
        "churn_added_sloc": 2,
        "churn_deleted_sloc": 1,
        "churn_total": 3,
        "churn_touched_files": 1,
        "churn_normalized_entropy": 0.0,
    }


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("def bad(:\n", "value = 1\n"),
        ("value = 1\n", "def bad(:\n"),
        (None, "def bad(:\n"),
        ("def bad(:\n", None),
        ("value = 1\n", "def value():\n    value = 1\n  return 2\n"),
    ],
)
def test_diff_warns_and_skips_whole_file_on_parse_failure(
    trees: tuple[Path, Path], before: str | None, after: str | None,
) -> None:
    """A failure on either side must not turn the other side into churn."""
    tree_a, tree_b = trees
    for tree, source in zip(trees, (before, after), strict=True):
        (tree / "ok.py").write_text("value = 0\n", encoding="utf-8")
        if source is not None:
            (tree / "broken.py").write_text(source, encoding="utf-8")

    result = CliRunner().invoke(
        main, ["diff", str(tree_a), str(tree_b), "--output-format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["eligible_file_union_count"] == 1
    assert payload["churn_total"] == 0
    assert "failed to parse file" in result.stderr
    assert "broken.py" in result.stderr


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("# old\nvalue = 1\n", "# new\n\nvalue = 1\n# end\n"),
        ('"""old docs"""\nvalue = 1\n', '"""new docs"""\nvalue = 1\n'),
        ("value = 1\r\nother = 2\r\n", "value = 1\nother = 2\n"),
        ("value = 1\rother = 2\r", "value = 1\nother = 2\n"),
        ("value = 1\n", "value = 1"),
        ("value = 1", "value = 1\n"),
    ],
)
def test_diff_ignores_non_sloc_and_newline_only_changes(
    trees: tuple[Path, Path], before: str, after: str,
) -> None:
    """Comments, docstrings, blanks, and normalized endings do not add churn."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_bytes(before.encode())
    (tree_b / "sample.py").write_bytes(after.encode())

    payload = _json_diff(trees)
    assert payload["eligible_file_union_count"] == 1
    assert payload["churn_added_sloc"] == 0
    assert payload["churn_deleted_sloc"] == 0
    assert payload["churn_total"] == 0
    assert payload["churn_touched_files"] == 0
    assert payload["churn_normalized_entropy"] == 0.0


@pytest.mark.parametrize("failed_side", [0, 1])
def test_diff_warns_and_skips_whole_file_on_read_failure(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, failed_side: int,
) -> None:
    """An unreadable file is not a deletion or addition on its readable side."""
    tree_a, tree_b = trees
    for tree, value in zip(trees, (1, 2), strict=True):
        (tree / "ok.py").write_text("stable = True\n", encoding="utf-8")
        (tree / "unreadable.py").write_text(f"value = {value}\n", encoding="utf-8")
    unreadable = (trees[failed_side] / "unreadable.py").resolve()
    original_read_text = Path.read_text

    def read_text(
        file_path: Path, encoding: str | None = None, errors: str | None = None,
    ) -> str:
        if file_path == unreadable:
            raise PermissionError("cannot read source")
        return original_read_text(file_path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text)
    result = CliRunner().invoke(
        main, ["diff", str(tree_a), str(tree_b), "--output-format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["eligible_file_union_count"] == 1
    assert payload["churn_total"] == 0
    assert "failed to parse file" in result.stderr
    assert "unreadable.py" in result.stderr


@pytest.mark.parametrize("directive", ["# scbc ignore[unknown-rule]", "# scbc boundary"])
def test_diff_does_not_validate_check_directives(
    trees: tuple[Path, Path], directive: str,
) -> None:
    """Check-only directive errors cannot reject a valid SLOC comparison."""
    for tree, value in zip(trees, (1, 2), strict=True):
        (tree / "sample.py").write_text(
            f"{directive}\nvalue = {value}\n", encoding="utf-8",
        )

    payload = _json_diff(trees)

    assert payload["eligible_file_union_count"] == 1
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 1


@pytest.mark.parametrize(
    ("before", "after", "added", "deleted"),
    [
        ('"""notes"""\n', "value = 1\n", 1, 0),
        ("value = 1\n", '"""notes"""\n', 0, 1),
    ],
)
def test_diff_uses_each_sides_sloc_classification(
    trees: tuple[Path, Path], before: str, after: str, added: int, deleted: int,
) -> None:
    """Replacement lines use the SLOC classification of their own tree."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text(before, encoding="utf-8")
    (tree_b / "sample.py").write_text(after, encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["churn_added_sloc"] == added
    assert payload["churn_deleted_sloc"] == deleted
    assert payload["churn_touched_files"] == 1
    assert payload["churn_normalized_entropy"] == 0.0


@pytest.mark.parametrize(
    "non_sloc",
    [
        "# anchor one\n# anchor two\n# anchor three\n",
        "\n\n\n",
        '"""notes\nmore notes\nend notes"""\n',
    ],
)
def test_diff_matches_only_sloc_not_non_code_anchors(
    trees: tuple[Path, Path], non_sloc: str,
) -> None:
    """Non-code anchors must not turn one moved SLOC line into two replacements."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text(
        f"first = 1\n{non_sloc}second = 2\n", encoding="utf-8",
    )
    (tree_b / "sample.py").write_text(
        f"second = 2\n{non_sloc}first = 1\n", encoding="utf-8",
    )

    payload = _json_diff(trees)
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 1
    assert payload["churn_total"] == 2
    assert payload["churn_touched_files"] == 1


def test_diff_keeps_inline_comments_on_sloc_lines(trees: tuple[Path, Path]) -> None:
    """SLOC filtering removes whole non-code lines, not text on retained lines."""
    tree_a, tree_b = trees
    (tree_a / "sample.py").write_text("value = 1  # old\n", encoding="utf-8")
    (tree_b / "sample.py").write_text("value = 1  # new\n", encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 1
    assert payload["churn_total"] == 2


@pytest.mark.parametrize("code_side", [0, 1])
def test_diff_counts_unchanged_text_entering_or_leaving_sloc(
    trees: tuple[Path, Path], code_side: int,
) -> None:
    """Identical text is added/deleted when its parser classification changes."""
    (trees[code_side] / "sample.py").write_text(
        "# notes\nvalue = 1\n# end\n", encoding="utf-8",
    )
    (trees[1 - code_side] / "sample.py").write_text(
        '"""notes\nvalue = 1\nend"""\n', encoding="utf-8",
    )

    payload = _json_diff(trees)
    assert payload["churn_added_sloc"] == (1 if code_side == 1 else 0)
    assert payload["churn_deleted_sloc"] == (1 if code_side == 0 else 0)
    assert payload["churn_total"] == 1
    assert payload["churn_touched_files"] == 1


@pytest.mark.parametrize(
    ("suffix", "source"),
    [
        (".py", '# comment\ndef value():\n    """docs"""\n    return 1\n'),
        (".rs", "// comment\nfn value() -> i32 {\n    1\n}\n"),
        (".js", "// comment\nfunction value() {\n    return 1;\n}\n"),
        (".ts", "// comment\nfunction value(): number {\n    return 1;\n}\n"),
        (".zig", "// comment\npub fn value() u32 {\n    return 1;\n}\n"),
        (".hs", "-- comment\nvalue :: Int\nvalue = 1\n"),
        (".cpp", "// comment\nint value() {\n    return 1;\n}\n"),
    ],
)
@pytest.mark.parametrize("populated_side", [0, 1])
def test_diff_all_added_or_deleted_uses_supported_language_sloc(
    trees: tuple[Path, Path], suffix: str, source: str, populated_side: int,
) -> None:
    """One empty tree is valid; parser-native SLOC excludes non-code lines."""
    (trees[populated_side] / f"sample{suffix}").write_text(source, encoding="utf-8")
    payload = _json_diff(trees)
    assert payload["eligible_file_union_count"] == 1
    assert payload["churn_added_sloc"] == (2 if populated_side == 1 else 0)
    assert payload["churn_deleted_sloc"] == (2 if populated_side == 0 else 0)
    assert payload["churn_total"] == 2
    assert payload["churn_touched_files"] == 1
    assert payload["churn_normalized_entropy"] == 0.0


def test_diff_counts_rename_as_deletion_and_addition(trees: tuple[Path, Path]) -> None:
    """Relative paths are identity even when content is identical."""
    tree_a, tree_b = trees
    (tree_a / "old.py").write_text("value = 1\n", encoding="utf-8")
    (tree_b / "new.py").write_text("value = 1\n", encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["eligible_file_union_count"] == 2
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 1
    assert payload["churn_total"] == 2
    assert payload["churn_touched_files"] == 2
    assert payload["churn_normalized_entropy"] == 1.0


@pytest.mark.parametrize(("unchanged_count", "entropy"), [(0, 1.0), (2, 0.5)])
def test_diff_entropy_normalizes_over_full_union(
    trees: tuple[Path, Path], unchanged_count: int, entropy: float,
) -> None:
    """Two equally touched files have lower dispersion in a larger union."""
    tree_a, tree_b = trees
    for name in ("first.py", "second.py"):
        (tree_a / name).write_text("value = 1\n", encoding="utf-8")
        (tree_b / name).write_text("value = 2\n", encoding="utf-8")
    for index in range(unchanged_count):
        for tree in trees:
            (tree / f"stable{index}.py").write_text("stable = 1\n", encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["churn_total"] == 4
    assert payload["churn_touched_files"] == 2
    assert payload["churn_normalized_entropy"] == entropy


def test_diff_entropy_weights_unequal_churn(trees: tuple[Path, Path]) -> None:
    """A three-to-one churn split has known non-uniform entropy."""
    _, tree_b = trees
    (tree_b / "large.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (tree_b / "small.py").write_text("a = 1\n", encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["churn_total"] == 4
    assert payload["churn_normalized_entropy"] == pytest.approx(0.8112781244591328)


@pytest.mark.parametrize("include_all", [False, True])
def test_diff_applies_each_trees_eligibility_and_shared_cwd_config(
    trees: tuple[Path, Path], *, include_all: bool,
) -> None:
    """Gitignore is tree-local; include-all bypasses it but not other excludes."""
    tree_a, tree_b = trees
    (tree_a.parent / "scb-check.toml").write_text(
        'exclude = ["**/excluded.py"]\n', encoding="utf-8",
    )
    for tree in trees:
        # Tree-local configs must not replace the config discovered from cwd.
        (tree / "scb-check.toml").write_text("unknown = true\n", encoding="utf-8")
        for name in ("only-a.py", "only-b.py", "keep.py"):
            (tree / name).write_text("value = 1\n", encoding="utf-8")
        nested = tree / "nested"
        nested.mkdir()
        (nested / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        for excluded_dir in ("build", "node_modules"):
            directory = tree / excluded_dir
            directory.mkdir()
            (directory / "noise.py").write_text("value = 1\n", encoding="utf-8")
    (tree_a / ".gitignore").write_text("only-a.py\n", encoding="utf-8")
    (tree_b / ".gitignore").write_text("only-b.py\n", encoding="utf-8")
    for tree, value in zip(trees, (1, 2), strict=True):
        for name in ("excluded.py", "README.md", "requirements.txt", "nested/ignored.py"):
            (tree / name).write_text(f"value = {value}\n", encoding="utf-8")

    options = ["--include-all"] if include_all else []
    payload = _json_diff(trees, *options)
    assert payload["eligible_file_union_count"] == (4 if include_all else 3)
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 1
    assert payload["churn_touched_files"] == (1 if include_all else 2)
    assert payload["churn_normalized_entropy"] == pytest.approx(
        0.0 if include_all else 0.6309297535714574,
    )


@pytest.mark.parametrize("invalid_side", [0, 1])
@pytest.mark.parametrize("path_kind", ["missing", "file"])
def test_diff_rejects_invalid_tree_paths(
    trees: tuple[Path, Path], invalid_side: int, path_kind: str,
) -> None:
    """Both arguments must name existing directories, not individual files."""
    invalid_path = trees[invalid_side] / "sample.py"
    if path_kind == "file":
        invalid_path.write_text("value = 1\n", encoding="utf-8")
    paths = list(trees)
    paths[invalid_side] = invalid_path

    result = CliRunner().invoke(main, ["diff", *(str(path) for path in paths)])

    assert result.exit_code == 2
    assert str(invalid_path) in result.stderr
    assert ("path does not exist" if path_kind == "missing" else "not a directory") in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("contents", ["empty", "unsupported", "ignored", "broken"])
def test_diff_rejects_empty_eligible_union(
    trees: tuple[Path, Path], contents: str,
) -> None:
    """No eligible parseable source on either side is an error, not zero churn."""
    tree_a, tree_b = trees
    for tree in trees:
        if contents == "unsupported":
            (tree / "README.md").write_text("notes\n", encoding="utf-8")
        elif contents == "ignored":
            (tree / ".gitignore").write_text("*.py\n", encoding="utf-8")
            (tree / "sample.py").write_text("value = 1\n", encoding="utf-8")
        elif contents == "broken":
            (tree / "sample.py").write_text("def bad(:\n", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["diff", str(tree_a), str(tree_b), "--output-format", "json"],
    )

    assert result.exit_code == 2
    assert "no supported source files" in result.stderr
    assert result.stdout == ""
    if contents == "broken":
        assert "failed to parse file" in result.stderr


@pytest.mark.parametrize("config", ["exclude = 42\n", "not valid TOML"])
def test_diff_reports_config_errors(trees: tuple[Path, Path], config: str) -> None:
    """Invalid current-directory configuration fails with exit 2 and stderr."""
    tree_a, tree_b = trees
    (tree_a.parent / "scb-check.toml").write_text(config, encoding="utf-8")
    for tree in trees:
        (tree / "sample.py").write_text("value = 1\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["diff", str(tree_a), str(tree_b)])

    assert result.exit_code == 2
    assert "scb-check.toml" in result.stderr
    assert result.stdout == ""


def test_diff_human_summary_is_default(trees: tuple[Path, Path]) -> None:
    """Human output includes paths and churn numbers, even with zero churn."""
    tree_a, tree_b = trees
    for tree in trees:
        (tree / "sample.py").write_text("value = 1\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["diff", str(tree_a), str(tree_b), "-vv"])

    assert result.exit_code == 0, result.output
    assert str(tree_a) in result.stdout
    assert str(tree_b) in result.stdout
    assert "eligible_file_union_count: 1" in result.stdout
    assert "churn_total: 0" in result.stdout
    assert "churn_normalized_entropy: 0.0" in result.stdout


@pytest.mark.parametrize("options", [["--report"], ["--threshold", "1"], ["--output-format", "yaml"]])
def test_diff_rejects_unsupported_options(
    trees: tuple[Path, Path], options: list[str],
) -> None:
    """Diff has a single output option, no report alias or threshold gates."""
    result = CliRunner().invoke(main, ["diff", *(str(tree) for tree in trees), *options])

    assert result.exit_code == 2
    assert result.stderr


def test_diff_repeated_lines_are_deterministic(trees: tuple[Path, Path]) -> None:
    """A small insertion in repetitive code stays small on repeated runs."""
    tree_a, tree_b = trees
    before = "value = 0\n" * 250
    (tree_a / "sample.py").write_text(before, encoding="utf-8")
    (tree_b / "sample.py").write_text("new_value = 1\n" + before, encoding="utf-8")
    args = ["diff", str(tree_a), str(tree_b), "--output-format", "json"]

    first = CliRunner().invoke(main, args)
    second = CliRunner().invoke(main, args)

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["churn_added_sloc"] == 1
    assert payload["churn_deleted_sloc"] == 0


def test_diff_retains_empty_source_files_in_union(trees: tuple[Path, Path]) -> None:
    """Eligible files with zero SLOC still belong to a valid zero-churn union."""
    tree_a, tree_b = trees
    (tree_a / "empty.py").write_text("", encoding="utf-8")
    (tree_b / "comments.py").write_text("# comment only\n", encoding="utf-8")

    payload = _json_diff(trees)
    assert payload["eligible_file_union_count"] == 2
    assert payload["churn_total"] == 0
    assert payload["churn_touched_files"] == 0
    assert payload["churn_normalized_entropy"] == 0.0
