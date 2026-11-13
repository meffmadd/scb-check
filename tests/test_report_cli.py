from __future__ import annotations

import json
import re
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from scb_check.cli import main
from scb_check.logging import get_logger
from scb_check.models import AstGrepHit

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import Result


def _invoke(paths: tuple[Path, ...], *options: str) -> Result:
    return CliRunner().invoke(
        main, ["report", *(str(path) for path in paths), *options]
    )


def _payload(output: Path) -> dict[str, Any]:
    match = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>',
        output.read_text("utf-8"),
        re.DOTALL,
    )
    assert match
    return json.loads(match[1])


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ...]:
    """Use independently known SLOC counts and deterministic external tooling."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "scb_check.pipeline.run_sg", lambda _files, _rules_path: ()
    )
    paths = tuple(tmp_path / name for name in ("first", "second", "third"))
    for path, lines in zip(paths, (1, 3, 2), strict=True):
        path.mkdir()
        (path / "sample.py").write_text("value = 1\n" * lines, encoding="utf-8")
    return paths


def test_complete_snapshot_and_adjacent_diff_parity(
    roots: tuple[Path, ...],
) -> None:
    """Every report field matches standalone check/diff with known signed SLOC deltas."""
    output = Path("report.html")
    result = _invoke(roots)
    assert result.exit_code == 0, result.output
    assert str(output.resolve()) in result.stdout
    payload = _payload(output)
    assert payload["paths"] == [str(path.resolve()) for path in roots]
    for index, path in enumerate(roots):
        check = CliRunner().invoke(
            main, ["check", str(path), "--output-format", "json"]
        )
        assert check.exit_code in (0, 1)
        assert payload["snapshots"][index] == json.loads(check.stdout)
        if index:
            diff = CliRunner().invoke(
                main,
                [
                    "diff",
                    str(roots[index - 1]),
                    str(path),
                    "--output-format",
                    "json",
                ],
            )
            assert diff.exit_code == 0, diff.output
            assert (
                payload["comparisons"][index] == json.loads(diff.stdout)["diff"]
            )
    series = {series["metric"]: series for series in payload["series"]}
    assert series["verbosity.total_loc"]["values"] == [1, 3, 2]
    assert series["verbosity.total_loc"]["differences"] == [None, 2, -1]
    assert set(series) == {
        f"{group}.{field}"
        for report in payload["snapshots"]
        for group, fields in report.items()
        for field in fields
    }


def test_custom_output_reversal_and_repetition(roots: tuple[Path, ...]) -> None:
    """Repeated roots are separate points, and changes follow input order."""
    output = Path("changes.html")
    result = _invoke((roots[2], roots[0], roots[0]), "--output", str(output))
    assert result.exit_code == 0, result.output
    series = next(
        series
        for series in _payload(output)["series"]
        if series["metric"] == "verbosity.total_loc"
    )
    assert series["values"] == [2, 1, 1]
    assert series["differences"] == [None, -1, 0]


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("include_all", [False, True])
def test_shared_config_and_suppressions_match_check(
    roots: tuple[Path, ...],
    monkeypatch: pytest.MonkeyPatch,
    *,
    explicit: bool,
    include_all: bool,
) -> None:
    """One settings source applies exclusions and ordinary inclusion semantics everywhere."""
    config = Path("override.toml" if explicit else "scb-check.toml")
    config.write_text('exclude = ["**/excluded.py"]\n', encoding="utf-8")
    if explicit:
        Path("scb-check.toml").write_text("unknown = true\n", encoding="utf-8")
    for root in roots:
        (root / "scb-check.toml").write_text(
            "unknown = true\n", encoding="utf-8"
        )
        (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (root / "ignored.py").write_text("value = 1\n", encoding="utf-8")
        (root / "excluded.py").write_text("def bad(:\n", encoding="utf-8")
        (root / "sample.py").write_text(
            "# scbc ignore[trivial-wrapper]\ndef wrapper(value):\n    return value\n\n"
            'def boundary(raw):\n    # scbc boundary\n    result = raw.get("a")\n    return result\n'
            "# scbc ignore[json-loads-read]\nignored = 1\ninfo = None\n",
            encoding="utf-8",
        )

    def hits(files: tuple[Path, ...], _rules: Path) -> tuple[AstGrepHit, ...]:
        return tuple(
            AstGrepHit(file, line, line, 0, 1, rule, "value")
            for file in files
            if file.name == "sample.py"
            for line, rule in (
                (7, "json-loads-read"),
                (10, "json-loads-read"),
                (11, "redundant-return-none"),
            )
        )

    monkeypatch.setattr("scb_check.pipeline.run_sg", hits)
    options = (["--config", str(config)] if explicit else []) + (
        ["--include-all"] if include_all else []
    )
    result = _invoke(roots, *options)
    assert result.exit_code == 0, result.output
    for index, root in enumerate(roots):
        check = CliRunner().invoke(
            main, ["check", str(root), "--output-format", "json", *options]
        )
        assert check.exit_code == (1 if include_all else 0), check.output
        snapshot = _payload(Path("report.html"))["snapshots"][index]
        assert snapshot == json.loads(check.stdout)
        assert snapshot["verbosity"]["files_scanned"] == (
            2 if include_all else 1
        )
        assert snapshot["verbosity"]["ast_grep_flagged_loc"] == (
            3 if include_all else 0
        )
        assert snapshot["verbosity"]["structural_rule_findings"] == (
            1 if include_all else 0
        )


@pytest.mark.parametrize("disabled", [False, True])
def test_missing_or_disabled_ast_grep_retains_other_metrics(
    roots: tuple[Path, ...],
    monkeypatch: pytest.MonkeyPatch,
    *,
    disabled: bool,
) -> None:
    """Optional tooling loss is not a report failure, and findings never exit 1."""

    def no_tool(
        _files: tuple[Path, ...], _rules: Path
    ) -> tuple[AstGrepHit, ...]:
        if disabled:
            pytest.fail("disabled ast-grep must not execute")
        get_logger(__name__).warning("ast-grep binary not found")
        return ()

    monkeypatch.setattr("scb_check.pipeline.run_sg", no_tool)
    (roots[0] / "sample.py").write_text(
        "def wrapper(value):\n    return value\n", encoding="utf-8"
    )
    result = _invoke(roots, *(["--disable-sg"] if disabled else []))
    assert result.exit_code == 0, result.output
    snapshot = _payload(Path("report.html"))["snapshots"][0]
    assert snapshot["verbosity"]["ast_grep_flagged_loc"] == 0
    assert snapshot["verbosity"]["structural_rule_findings"] == 1
    if not disabled:
        assert "ast-grep binary not found" in result.stderr


@pytest.mark.parametrize("verbosity", ["-v", "--verbosity", "-vv"])
def test_logs_stay_out_of_artifact(
    roots: tuple[Path, ...],
    monkeypatch: pytest.MonkeyPatch,
    verbosity: str,
) -> None:
    """Verbose analysis logs go to stderr, not the HTML or success message."""

    def log_tool(
        _files: tuple[Path, ...], _rules: Path
    ) -> tuple[AstGrepHit, ...]:
        get_logger(__name__).info("report tool info")
        get_logger(__name__).debug("report tool debug")
        return ()

    monkeypatch.setattr("scb_check.pipeline.run_sg", log_tool)
    result = _invoke(roots, verbosity)
    assert result.exit_code == 0, result.output
    assert "report tool info" in result.stderr
    assert ("report tool debug" in result.stderr) == (verbosity == "-vv")
    assert result.stdout.startswith("Wrote ")
    assert (
        _payload(Path("report.html"))["snapshots"][0]["verbosity"]["total_loc"]
        == 1
    )


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("failure", ["empty", "broken", "directive"])
def test_unusable_snapshot_never_publishes_partial_report(
    roots: tuple[Path, ...],
    position: int,
    failure: str,
) -> None:
    """Every input is required; analysis failure preserves an existing artifact."""
    source = roots[position] / "sample.py"
    if failure == "empty":
        source.unlink()
    else:
        source.write_text(
            "def bad(:\n"
            if failure == "broken"
            else "# scbc ignore[unknown-rule]\nvalue = 1\n",
            encoding="utf-8",
        )
    output = Path("report.html")
    output.write_text("previous report", encoding="utf-8")
    result = _invoke(roots)
    assert result.exit_code == 2
    assert result.stderr
    assert result.stdout == ""
    assert output.read_text("utf-8") == "previous report"
    assert not list(Path.cwd().glob(".report.html.*.tmp"))


def test_invalid_late_root_precedes_earlier_directive_failure(
    roots: tuple[Path, ...],
) -> None:
    """Typer validates all roots before any source analysis."""
    (roots[0] / "sample.py").write_text(
        "# scbc ignore[unknown-rule]\nvalue = 1\n", encoding="utf-8"
    )
    result = _invoke((*roots, Path("missing-root")))
    assert result.exit_code == 2
    assert "missing-root" in result.stderr
    assert "unknown rule" not in result.stderr
    assert not Path("report.html").exists()


@pytest.mark.parametrize(
    "options",
    [
        ["--metric", "verbosity.score"],
        ["--mode", "values"],
        ["--output-format", "html"],
        ["--report"],
        ["--min-duplicate-lines", "5"],
        ["--config", "missing.toml"],
        ["--output", "missing/report.html"],
        ["--output", "."],
    ],
)
def test_invalid_options_or_output_do_not_create_artifact(
    roots: tuple[Path, ...], options: list[str]
) -> None:
    """The command has one HTML mode and fails cleanly before publication."""
    result = _invoke(roots, *options)
    assert result.exit_code == 2
    assert result.stderr
    assert not Path("report.html").exists()


@pytest.mark.parametrize("size", [0, 1])
def test_too_few_inputs(roots: tuple[Path, ...], size: int) -> None:
    """At least two directories are required even when one directory is usable."""
    result = _invoke(roots[:size])
    assert result.exit_code == 2
    assert result.stderr
    assert not Path("report.html").exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_invalid_config_does_not_create_artifact(
    roots: tuple[Path, ...], *, explicit: bool
) -> None:
    """Invalid discovered or shared explicit settings retain the usage-error contract."""
    config = Path("scb-check.toml")
    config.write_text("exclude = 42\n", encoding="utf-8")
    result = _invoke(roots, *(["--config", str(config)] if explicit else []))
    assert result.exit_code == 2
    assert result.stderr
    assert not Path("report.html").exists()


def test_failed_files_are_skipped_but_zero_sloc_is_valid(
    roots: tuple[Path, ...],
) -> None:
    """Individual parse failures warn without dropping usable or zero-SLOC snapshots."""
    (roots[1] / "sample.py").write_text("# comment only\n", encoding="utf-8")
    (roots[1] / "broken.py").write_text("def bad(:\n", encoding="utf-8")
    result = _invoke(roots)
    assert result.exit_code == 0, result.output
    assert "failed to parse file" in result.stderr
    snapshot = _payload(Path("report.html"))["snapshots"][1]
    assert snapshot["verbosity"]["files_scanned"] == 1
    assert snapshot["verbosity"]["total_loc"] == 0


def test_atomic_replace_failure_preserves_artifact_and_cleans_temporary_file(
    roots: tuple[Path, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publication failures never leave a truncated output or temporary sibling."""

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("simulated replace failure")

    output = Path("report.html")
    output.write_text("previous report", encoding="utf-8")
    monkeypatch.setattr(Path, "replace", fail_replace)
    result = _invoke(roots)
    assert result.exit_code == 2
    assert "simulated replace failure" in result.stderr
    assert output.read_text("utf-8") == "previous report"
    assert not list(Path.cwd().glob(".report.html.*.tmp"))


def test_write_failure_cleans_partial_temporary_file(
    roots: tuple[Path, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disk error after writing starts leaves neither output nor a temporary sibling."""

    @contextmanager
    def fail_write(**options: Any) -> Iterator[Any]:  # noqa: ANN401 - IO factory test adapter
        with NamedTemporaryFile(**options) as stream:
            original_write = stream.write

            def partial_write(html: str) -> None:
                original_write(html[:10])
                raise OSError("simulated disk full")

            stream.write = partial_write
            yield stream

    monkeypatch.setattr(
        import_module("scb_check.commands.report"),
        "NamedTemporaryFile",
        fail_write,
    )
    result = _invoke(roots)
    assert result.exit_code == 2
    assert "simulated disk full" in result.stderr
    assert not Path("report.html").exists()
    assert not list(Path.cwd().glob(".report.html.*.tmp"))
