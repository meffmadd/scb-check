"""Entity contracts observed through ordinary source analysis."""

from collections.abc import MutableMapping
from dataclasses import replace
from math import sqrt
from operator import setitem
from pathlib import Path
from textwrap import dedent
from textwrap import indent
from typing import cast

import pytest
from pydantic import ValidationError

from scb_check.pipeline import analyze_files
from scb_check.reporting.score import compute_report
from scb_check.tree_walking.models import SymbolKind


def test_analysis_retains_project_inventory(tmp_path: Path) -> None:
    """Source analysis retains classes and methods alongside reporting facts."""
    source = tmp_path / "sample.py"
    source.write_text(
        "class Widget:\n    def render(self):\n        return 1\n",
        encoding="utf-8",
    )

    result = analyze_files((source,), disable_sg=True)

    assert len(result.project.modules) == 1
    module = result.project.modules[0]
    assert module.file == source
    assert [
        (symbol.name, symbol.owner_qualified_name) for symbol in module.symbols
    ] == [
        ("Widget", None),
        ("render", "sample.Widget"),
    ]
    assert result.project.modules_by_file[source].symbols == module.symbols


def test_identity_and_lexical_ownership_survive_repeated_names(
    tmp_path: Path,
) -> None:
    """Repeated declarations retain unique identity and exact lexical parents."""
    source = tmp_path / "sample.py"
    source.write_text(
        "class Widget:\n"
        "    def render(self):\n"
        "        def local():\n"
        "            return 1\n"
        "        return local()\n"
        "class Widget:\n"
        "    def render(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )
    other = tmp_path / "other.py"
    other.write_text("from sample import Widget as Alias\n", encoding="utf-8")

    project = analyze_files((source, other), disable_sg=True).project
    repeated = analyze_files((other, source), disable_sg=True).project
    module = project.modules_by_file[source]
    first, method, local, second, second_method = module.symbols

    assert len(project.symbols_by_id) == 5
    assert project.symbols_by_id == repeated.symbols_by_id
    assert project.modules_by_id == repeated.modules_by_id
    assert module.id != module.file_id
    assert project.files_by_id[module.file_id] == source
    assert module.kind is SymbolKind.MODULE
    assert module.name == module.qualified_name == "sample"
    assert first.id != second.id
    assert first.owner_id == second.owner_id == module.id
    assert method.owner_id == first.id
    assert local.owner_id == method.id
    assert local.kind is SymbolKind.FUNCTION
    assert second_method.owner_id == second.id
    assert {symbol.module_id for symbol in module.symbols} == {module.id}
    assert {symbol.file_id for symbol in module.symbols} == {module.file_id}


def test_analysis_views_are_deeply_read_only(tmp_path: Path) -> None:
    """Neither records nor their nested lookup collections can be mutated."""
    source = tmp_path / "sample.py"
    source.write_text(
        "def render(value: int) -> int:\n    return value\n", encoding="utf-8"
    )
    result = analyze_files((source,), disable_sg=True)
    project = result.project
    module = project.modules[0]
    symbol = module.symbols[0]

    for mapping, key, value in (
        (project.symbols_by_id, symbol.id, symbol),
        (project.symbols_by_qualified_name, symbol.qualified_name, symbol),
        (project.modules_by_id, module.id, module),
        (project.modules_by_file, source, module),
        (project.files_by_id, module.file_id, source),
        (project.effects_by_symbol, symbol.id, ()),
        (symbol.signature.annotations, "value", "str"),
        (result.source_lines_by_file, source, ()),
    ):
        with pytest.raises(TypeError):
            # Deliberately attempt an operation excluded by the read-only type.
            setitem(cast("MutableMapping[object, object]", mapping), key, value)
    for record, attribute in (
        (project, "symbols_by_id"),
        (project, "symbols_by_qualified_name"),
        (project, "modules_by_id"),
        (project, "modules_by_file"),
        (project, "files_by_id"),
        (symbol.span, "file_id"),
    ):
        with pytest.raises(ValidationError):
            setattr(record, attribute, {})
    with pytest.raises(ValidationError):
        symbol.name = "changed"
    with pytest.raises(ValidationError):
        module.symbols = ()

    lines = {source: ("original",)}
    copied = replace(result, source_lines_by_file=lines)
    lines[source] = ("changed",)
    assert copied.source_lines_by_file[source] == ("original",)
    assert symbol.signature.annotations == {"value": "int"}


def test_cross_file_collisions_count_per_file_but_redefinitions_select_last(
    tmp_path: Path,
) -> None:
    """Cross-file collisions contribute mass without counting same-file repeats."""
    first = tmp_path / "api" / "sample.py"
    second = tmp_path / "jobs" / "sample.py"
    first.parent.mkdir()
    second.parent.mkdir()
    complex_function = (
        "def process(value):\n"
        + "".join(
            f"    if value == {number}:\n        return {number}\n"
            for number in range(11)
        )
        + "    return -1\n"
    )
    first.write_text(
        "def process(value):\n    return 0\n\n" + complex_function,
        encoding="utf-8",
    )
    second.write_text("def process(value):\n    return 0\n", encoding="utf-8")

    result = analyze_files((first, second), disable_sg=True)
    reversed_result = analyze_files((second, first), disable_sg=True)
    functions = result.flags.findings.all_functions
    report = compute_report(result)

    assert len(result.project.symbols_by_id) == 3
    assert len(functions) == 2
    assert {(symbol.file, symbol.start_line) for symbol in functions} == {
        (first, 4),
        (second, 1),
    }
    assert len({symbol.qualified_name for symbol in functions}) == 1
    assert report == compute_report(reversed_result)
    assert report["erosion"]["total_functions"] == 2
    assert report["erosion"]["high_cc_functions"] == 1
    assert report["erosion"]["total_mass"] == pytest.approx(
        12 * sqrt(24) + sqrt(2)
    )
    assert report["erosion"]["score"] == pytest.approx(
        12 * sqrt(24) / (12 * sqrt(24) + sqrt(2))
    )
    assert report["cog_erosion"]["total_functions"] == 2
    assert report["cog_erosion"]["high_cog_functions"] == 1
    assert report["cog_erosion"]["total_cog_mass"] == pytest.approx(
        11 * sqrt(24)
    )
    assert report["cog_erosion"]["score"] == 1.0


@pytest.mark.parametrize(
    "wrapper",
    [
        "if enabled:\n{body}",
        "if enabled:\n    pass\nelse:\n{body}",
        "try:\n{body}\nexcept Error:\n    pass\n",
        "try:\n    pass\nexcept Error:\n{body}",
        "try:\n    pass\nfinally:\n{body}",
        "for item in items:\n{body}",
        "while enabled:\n{body}",
        "with context():\n{body}",
        "match value:\n    case 1:\n{body}",
    ],
)
def test_control_flow_declarations_feed_entities_metrics_and_rules(
    tmp_path: Path, wrapper: str
) -> None:
    """Wrappers preserve lexical owners and contribute to ordinary findings."""
    declarations = dedent("""\
        def forward(value):
            return value
        class Holder:
            if enabled:
                def method(self):
                    try:
                        def local():
                            return 1
                    except Error:
                        pass
                    return local()
        """)
    source = tmp_path / "sample.py"
    depth = "        " if wrapper.startswith("match") else "    "
    source.write_text(
        wrapper.format(body=indent(declarations, depth)), encoding="utf-8"
    )

    result = analyze_files((source,), disable_sg=True)
    module = result.project.modules[0]
    symbols = {symbol.name: symbol for symbol in module.symbols}

    assert len(module.symbols) == len(result.project.symbols_by_id) == 4
    assert set(symbols) == {"forward", "Holder", "method", "local"}
    assert (
        symbols["forward"].owner_id == symbols["Holder"].owner_id == module.id
    )
    assert symbols["method"].owner_id == symbols["Holder"].id
    assert symbols["local"].owner_id == symbols["method"].id
    assert symbols["method"].kind is SymbolKind.METHOD
    assert symbols["local"].kind is SymbolKind.FUNCTION
    report = compute_report(result)
    assert report["erosion"]["total_functions"] == 3
    assert report["cog_erosion"]["total_functions"] == 3
    assert any(
        finding.subject_name == "forward"
        for finding in result.flags.findings.structural_findings
    )
    assert report["verbosity"]["structural_rule_loc"] == 2


def test_coverage_distinguishes_empty_facts_from_unsupported_extraction(
    tmp_path: Path,
) -> None:
    """Parser coverage describes support even when no facts were extracted."""
    python = tmp_path / "empty.py"
    generic = tmp_path / "sample.rs"
    unsupported = tmp_path / "ignored.txt"
    invalid = tmp_path / "invalid.py"
    python.write_text("", encoding="utf-8")
    generic.write_text(
        "fn compute(value: i32) -> i32 { value + 1 }\n", encoding="utf-8"
    )
    unsupported.write_text("not supported", encoding="utf-8")
    invalid.write_text("def (", encoding="utf-8")

    result = analyze_files(
        (python, generic, unsupported, invalid), disable_sg=True
    )
    empty = result.project.modules_by_file[python]
    rust = result.project.modules_by_file[generic]

    assert len(result.project.modules) == 2
    assert empty.symbols == empty.imports == empty.references == ()
    assert empty.coverage.entities == "complete"
    assert empty.coverage.complexity == empty.coverage.sloc == "complete"
    assert empty.coverage.references == empty.coverage.imports == "partial"
    assert rust.symbols[0].name == "compute"
    assert rust.coverage.entities == rust.coverage.signatures == "partial"
    assert rust.coverage.complexity == rust.coverage.sloc == "complete"
    assert rust.coverage.imports == rust.coverage.references == "unavailable"
    assert (
        rust.coverage.operations
        == rust.coverage.roles
        == rust.coverage.effects
        == "unavailable"
    )
    with pytest.raises(ValidationError):
        empty.coverage.entities = "unavailable"


@pytest.mark.parametrize(
    ("source_text", "module_end"),
    [
        ('@decorator\ndef café(π: str): return "é"', (2, 31)),
        ('@decorator\ndef café(π: str): return "é"\n', (3, 0)),
    ],
)
def test_spans_use_utf8_columns_and_exclusive_ends(
    tmp_path: Path,
    source_text: str,
    module_end: tuple[int, int],
) -> None:
    """Definition spans exclude decorators; all columns count UTF-8 bytes."""
    source = tmp_path / "unicode.py"
    source.write_text(source_text, encoding="utf-8")

    module = analyze_files((source,), disable_sg=True).project.modules[0]
    function = module.symbols[0]

    assert (function.span.start_line, function.span.start_col) == (2, 0)
    assert (function.span.end_line, function.span.end_col) == (2, 31)
    assert (module.span.start_line, module.span.start_col) == (1, 0)
    assert (module.span.end_line, module.span.end_col) == module_end


def test_effects_do_not_overwrite_repeated_declarations(tmp_path: Path) -> None:
    """Each retained declaration keeps its own existing derived effects."""
    source = tmp_path / "sample.py"
    source.write_text(
        "def process(value):\n    return value\n"
        "def process(value):\n    return value.strip()\n",
        encoding="utf-8",
    )

    result = analyze_files((source,), disable_sg=True)
    project = result.project
    first, second = project.modules[0].symbols

    # Retained effects must not change existing name-selected rule decisions.
    assert result.flags.findings.structural_findings == ()
    assert compute_report(result)["verbosity"]["score"] == 0.0
    assert set(project.effects_by_symbol) == {first.id, second.id}
    assert [effect.kind for effect in project.effects_by_symbol[first.id]] == [
        "read"
    ]
    assert [effect.kind for effect in project.effects_by_symbol[second.id]] == [
        "unresolved-call"
    ]


@pytest.mark.parametrize("wrapped", [False, True])
def test_declaration_discovery_skips_deep_expressions(tmp_path: Path, *, wrapped: bool) -> None:
    """Declaration discovery does not recurse through arbitrary expression trees."""
    source = tmp_path / "sample.py"
    expression = "value = " + " + ".join("1" for _ in range(600)) + "\n"
    source.write_text(
        "if enabled:\n" + indent(expression, "    ") if wrapped else expression,
        encoding="utf-8",
    )

    result = analyze_files((source,), disable_sg=True)

    assert result.project.modules[0].symbols == ()
    assert result.flags.findings.all_functions == ()
    assert compute_report(result)["verbosity"]["total_loc"] == (2 if wrapped else 1)


def test_generic_entities_preserve_overloads_and_unresolved_owners(
    tmp_path: Path,
) -> None:
    """Generic overloads survive and owner names do not invent declarations."""
    cpp = tmp_path / "sample.cpp"
    cpp.write_text(
        "int parse(int value);\n"
        "int parse(int value) { return value + 1; }\n"
        "double parse(double value) { return value + 1.0; }\n",
        encoding="utf-8",
    )
    rust = tmp_path / "sample.rs"
    rust.write_text(
        "impl Missing { fn render(&self) -> i32 { 1 } }\n", encoding="utf-8"
    )

    result = analyze_files((cpp, rust), disable_sg=True)
    project = result.project
    overloads = project.modules_by_file[cpp].symbols
    (method,) = project.modules_by_file[rust].symbols

    assert len(overloads) == len({symbol.id for symbol in overloads}) == 2
    assert len(result.flags.findings.all_functions) == 3
    assert {symbol.owner_id for symbol in overloads} == {
        project.modules_by_file[cpp].id
    }
    assert method.owner_id is None
    assert method.owner_qualified_name == "sample.Missing"
    assert method.module_id == project.modules_by_file[rust].id
    assert len(project.symbols_by_id) == 3


def test_ids_normalize_paths_and_survive_cwd_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalized identity is snapshot-local, not dependent on later process cwd."""
    source = tmp_path / "sample.py"
    source.write_text("def compute():\n    return 1\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    relative = analyze_files(
        (Path("sub/../sample.py"), source), disable_sg=True
    ).project
    assert len(relative.modules) == 1
    absolute = analyze_files((source,), disable_sg=True).project
    module = relative.modules[0]
    symbol = module.symbols[0]
    assert module.id == absolute.modules[0].id
    assert symbol.id == absolute.modules[0].symbols[0].id

    monkeypatch.chdir(tmp_path.parent)
    assert module.id in absolute.modules_by_id
    assert symbol.id in absolute.symbols_by_id


def test_empty_analysis_retains_empty_project() -> None:
    """The explicit-file analysis seam represents an empty project without IO."""
    result = analyze_files((), disable_sg=True)

    assert result.project.modules == ()
    assert not result.project.modules_by_file
    assert not result.source_lines_by_file
