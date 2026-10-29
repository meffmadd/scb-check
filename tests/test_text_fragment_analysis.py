"""Source text evidence observed through the retained analysis project."""

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from scb_check.pipeline import analyze_files


def test_analysis_retains_original_text_with_syntactic_owners(
    tmp_path: Path,
) -> None:
    """Identifiers, comments and docstrings survive independently of SLOC."""
    source = tmp_path / "sample.py"
    source.write_text(
        '# file note\n"""Module docs."""\n'
        "class Widget:\n"
        '    """Class docs."""\n'
        "    def render(self, input_value):\n"
        '        """Method docs."""\n'
        "        # keep this\n"
        "        return input_value  # trailing\n",
        encoding="utf-8",
    )

    module = analyze_files((source,), disable_sg=True).project.modules[0]
    widget, render = module.symbols

    assert module.coverage.text_fragments == "complete"
    assert {
        (fragment.text, fragment.kind, fragment.owner_id)
        for fragment in module.text_fragments
    } == {
        ("# file note", "comment", module.id),
        ('"""Module docs."""', "docstring", module.id),
        ("Widget", "identifier", widget.id),
        ('"""Class docs."""', "docstring", widget.id),
        ("render", "identifier", render.id),
        ("self", "identifier", render.id),
        ("input_value", "identifier", render.id),
        ('"""Method docs."""', "docstring", render.id),
        ("# keep this", "comment", render.id),
        ("# trailing", "comment", render.id),
    }
    assert (
        sum(
            fragment.text == "input_value" for fragment in module.text_fragments
        )
        == 2
    )
    assert module.sloc_lines == frozenset({3, 5, 8})


def test_nested_and_decorated_entities_own_each_occurrence_once(
    tmp_path: Path,
) -> None:
    """Leading comments stay with the enclosing entity; decorators go to declarations."""
    source = tmp_path / "nested.py"
    source.write_text(
        dedent('''\
        # before outer
        @outer_decorator  # outer decoration
        class Outer(Base):
            # before method
            @method_decorator(option)
            async def method(self, value: Kind = default):  # method header
                # before inner
                @inner_decorator
                class Inner:
                    """Inner documentation."""
                    def local(self): return value  # local tail
                def repeat(): return 1
                def repeat(): return 2
                return Inner
            # after method
        # after outer
        '''),
        encoding="utf-8",
    )

    project = analyze_files((source,), disable_sg=True).project
    module = project.modules[0]
    outer, method, inner, local, first, second = module.symbols
    fragments = module.text_fragments
    assert len(fragments) == len({fragment.span for fragment in fragments})
    expected_owners = {
        "# before outer": module.id,
        "outer_decorator": outer.id,
        "# outer decoration": outer.id,
        "Base": outer.id,
        "# before method": outer.id,
        "method_decorator": method.id,
        "option": method.id,
        "Kind": method.id,
        "default": method.id,
        "# method header": method.id,
        "# before inner": method.id,
        "inner_decorator": inner.id,
        '"""Inner documentation."""': inner.id,
        "# local tail": local.id,
        "# after method": outer.id,
        "# after outer": module.id,
    }
    for text, owner_id in expected_owners.items():
        assert [
            (fragment.text, fragment.owner_id)
            for fragment in fragments
            if fragment.text == text
        ] == [(text, owner_id)]
    assert {
        fragment.owner_id for fragment in fragments if fragment.text == "repeat"
    } == {
        first.id,
        second.id,
    }
    # A consumer can select a subtree by IDs without copying text into ancestors.
    method_subtree = {method.id, inner.id, local.id, first.id, second.id}
    selected = [
        fragment
        for fragment in fragments
        if fragment.owner_id in method_subtree
    ]
    assert sum(fragment.text == "value" for fragment in selected) == 2
    assert all(
        fragment.owner_id in {module.id, *project.symbols_by_id}
        for fragment in fragments
    )


def test_unicode_multiline_and_same_line_fragments_have_exact_spans(
    tmp_path: Path,
) -> None:
    """Spans slice normalized source by UTF-8 bytes, with exclusive ends."""
    source = tmp_path / "unicode.py"
    source_text = (
        '"""Módulo\n保持"""\ndef café(π): "début"; π = π; return π  # fin é\n'
    )
    source.write_text(source_text, encoding="utf-8")

    module = analyze_files((source,), disable_sg=True).project.modules[0]
    function = module.symbols[0]
    (doc,) = (
        fragment
        for fragment in module.text_fragments
        if fragment.owner_id == module.id
    )
    assert doc.text == '"""Módulo\n保持"""'
    assert (
        doc.span.start_line,
        doc.span.start_col,
        doc.span.end_line,
        doc.span.end_col,
    ) == (
        1,
        0,
        2,
        9,
    )
    (name,) = (
        fragment
        for fragment in module.text_fragments
        if fragment.text == "café"
    )
    assert (name.span.start_line, name.span.start_col, name.span.end_col) == (
        3,
        4,
        9,
    )
    assert name.owner_id == function.id
    assert sum(fragment.text == "π" for fragment in module.text_fragments) == 4
    assert {
        fragment.text
        for fragment in module.text_fragments
        if fragment.kind == "docstring"
    } == {
        '"""Módulo\n保持"""',
        '"début"',
    }
    assert module.sloc_lines == frozenset({3})
    lines = source_text.encode("utf-8").splitlines(keepends=True)
    for fragment in module.text_fragments:
        span = fragment.span
        selected = b"".join(lines[span.start_line - 1 : span.end_line])
        end_offset = sum(
            len(line) for line in lines[span.start_line - 1 : span.end_line - 1]
        )
        assert (
            selected[span.start_col : end_offset + span.end_col].decode("utf-8")
            == fragment.text
        )
        assert span.file_id == module.file_id
    with pytest.raises(ValidationError):
        doc.text = "changed"
    with pytest.raises(ValidationError):
        module.text_fragments = ()


@pytest.mark.parametrize("source_text", ["", "pass\n", "42\n"])
def test_no_eligible_fragments_is_successful_extraction(
    tmp_path: Path, source_text: str
) -> None:
    """Coverage does not depend on the number of emitted fragments."""
    source = tmp_path / "empty.py"
    source.write_text(source_text, encoding="utf-8")
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.text_fragments == ()
    assert module.coverage.text_fragments == "complete"


@pytest.mark.parametrize(
    ("suffix", "source_text"),
    [
        ("rs", "// note\nfn compute() {}\n"),
        ("js", "// note\nfunction compute() {}\n"),
        ("ts", "// note\nfunction compute(): void {}\n"),
        ("zig", "// note\nfn compute() void {}\n"),
        ("hs", "-- note\ncompute x = x + 1\n"),
        ("cpp", "// note\nint compute() { return 1; }\n"),
    ],
)
def test_other_language_fragments_are_explicitly_unavailable(
    tmp_path: Path,
    suffix: str,
    source_text: str,
) -> None:
    """Other supported scans remain usable, without claiming text extraction."""
    source = tmp_path / f"sample.{suffix}"
    source.write_text(source_text, encoding="utf-8")
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.symbols
    assert module.text_fragments == ()
    assert module.coverage.text_fragments == "unavailable"


@pytest.mark.parametrize(
    "body",
    [
        '"not documentation",',
        '"not documentation", value',
        '("not documentation",)',
    ],
)
@pytest.mark.parametrize(
    "wrapper",
    [
        "{body}\n",
        "class Example:\n    {body}\n",
        "def example():\n    {body}\n",
    ],
)
def test_initial_tuple_expressions_are_not_docstrings(
    tmp_path: Path,
    body: str,
    wrapper: str,
) -> None:
    """A tuple containing a string is not documentation, even with one element."""
    source = tmp_path / "tuples.py"
    source.write_text(wrapper.format(body=body), encoding="utf-8")

    module = analyze_files((source,), disable_sg=True).project.modules[0]

    assert not any(
        fragment.kind == "docstring" for fragment in module.text_fragments
    )
    assert sum(
        fragment.text == "value" for fragment in module.text_fragments
    ) == (1 if body == '"not documentation", value' else 0)


def test_docstrings_and_comments_come_from_syntax_not_literal_substrings(
    tmp_path: Path,
) -> None:
    """Only initial plain string expressions are docstrings; literals are not comments."""
    source = tmp_path / "literals.py"
    source.write_text(
        dedent("""\
        (r"module "  # between literals
         u"docs")
        "not a docstring"
        def plain():
            (("first " "second"))
            return "# not a comment"
        def formatted(value):
            f"not docs {value} # not a comment"
        def binary():
            b"not docs"
        """),
        encoding="utf-8",
    )
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    plain, formatted, _binary = module.symbols
    assert {
        (fragment.text, fragment.kind, fragment.owner_id)
        for fragment in module.text_fragments
        if fragment.kind != "identifier"
    } == {
        ('r"module "', "docstring", module.id),
        ('u"docs"', "docstring", module.id),
        ("# between literals", "comment", module.id),
        ('"first "', "docstring", plain.id),
        ('"second"', "docstring", plain.id),
    }
    assert (
        sum(
            fragment.text == "value" and fragment.owner_id == formatted.id
            for fragment in module.text_fragments
        )
        == 2
    )
