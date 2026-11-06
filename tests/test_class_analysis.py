"""Class source facts observed through the retained analysis interface."""

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from scb_check.pipeline import analyze_files
from scb_check.tree_walking.models import ProjectIR


def test_callable_members_retain_declarations_and_only_their_own_bodies(tmp_path: Path) -> None:
    """Inheritance does not copy declarations, bodies, or executable occurrences."""
    source = tmp_path / "members.py"
    source.write_text(dedent('''\
        from abc import abstractmethod
        class Base:
            @abstractmethod
            def missing(self): ...
            @abstractmethod
            def template(self):
                return work()
            @classmethod
            def make(cls): pass
            @staticmethod
            def utility():
                """Documentation is not implementation."""
                ...
            @property
            def value(self): return 1
        class Child(Base):
            def own(self):
                def local(): return nested()
                return local()
        '''))
    project = analyze_files((source,), disable_sg=True).project
    module = project.modules[0]
    symbols = {symbol.name: symbol for symbol in module.symbols}
    base, child = symbols["Base"], symbols["Child"]
    callables = {symbol.name: symbol.callable_facts for symbol in module.symbols if symbol.callable_facts is not None}
    assert set(callables) == {"missing", "template", "make", "utility", "value", "own", "local"}
    for name in ("missing", "template", "make", "utility", "value"):
        assert callables[name].declaring_class_id == base.id
    missing = callables["missing"]
    template = callables["template"]
    assert missing.body_span.start_line == 4
    assert template.body_span.start_line == 7
    assert missing.is_abstract is True
    assert missing.body_kind == "ellipsis"
    assert missing.implementation_id is None
    assert template.is_abstract is True
    assert template.body_kind == "implemented"
    assert template.implementation_id == symbols["template"].id
    assert callables["make"].binding == "class"
    assert callables["make"].body_kind == "pass"
    assert callables["utility"].binding == "static"
    assert callables["utility"].body_kind == "ellipsis"
    assert callables["value"].dispatch_supported is False
    assert callables["own"].declaring_class_id == child.id
    assert callables["local"].declaring_class_id is None
    assert callables["local"].binding == "function"
    assert module.source_uses is not None
    assert {(use.target_spelling, use.owner_id) for use in module.source_uses if use.kind == "call"} == {
        ("work", symbols["template"].id), ("nested", symbols["local"].id), ("local", symbols["own"].id),
    }
    assert len([symbol for symbol in module.symbols if symbol.owner_id == child.id]) == 1


def test_conditional_redefinitions_keep_their_own_declaration_facts(tmp_path: Path) -> None:
    """Repeated names and nested declarations retain distinct base and callable facts."""
    source = tmp_path / "conditional.py"
    source.write_text(dedent("""\
        class Base: pass
        if enabled:
            class Widget(Base):
                @staticmethod
                def build(): ...
                def build(self):
                    class Nested(Base):
                        def run(self): pass
                    return Nested()
        else:
            class Widget:
                @classmethod
                def build(cls): return cls()
        """))
    project = analyze_files((source,), disable_sg=True).project
    symbols = project.modules[0].symbols
    base = next(symbol for symbol in symbols if symbol.name == "Base")
    first, second = (symbol for symbol in symbols if symbol.name == "Widget")
    nested = next(symbol for symbol in symbols if symbol.name == "Nested")
    placeholder, implemented, factory = (symbol for symbol in symbols if symbol.name == "build")
    run = next(symbol for symbol in symbols if symbol.name == "run")

    assert first.id != second.id
    assert first.direct_bases is not None
    assert [reference.resolution.target_id for reference in first.direct_bases] == [base.id]
    assert second.direct_bases == ()
    assert nested.direct_bases is not None
    assert [reference.resolution.target_id for reference in nested.direct_bases] == [base.id]
    assert nested.owner_id == implemented.id
    for symbol, owner, binding, body_kind in (
        (placeholder, first, "static", "ellipsis"),
        (implemented, first, "instance", "implemented"),
        (factory, second, "class", "implemented"),
        (run, nested, "instance", "pass"),
    ):
        facts = symbol.callable_facts
        assert facts is not None
        assert symbol.owner_id == facts.declaring_class_id == owner.id
        assert facts.binding == binding
        assert facts.body_kind == body_kind
        assert facts.body_span.start_line >= symbol.start_line
        assert facts.body_span.end_line <= symbol.end_line
        assert facts.implementation_id == (symbol.id if body_kind == "implemented" else None)


def test_attribute_identity_is_per_declaring_class_not_per_write_or_local(tmp_path: Path) -> None:
    """Class and direct receiver assignments retain one field and distinct write sites."""
    source = tmp_path / "fields.py"
    source.write_text(dedent("""\
        class Widget:
            count = 0
            count = 1
            pending: int
            left, right = 1, 2
            def __init__(this, value):
                local = value
                this.item = value
                this.item = local
                this.item += 1
                this.first = this.second = value
                this.child.value = 1
                setattr(this, "dynamic", 1)
                def nested(): this.hidden = 1
            @classmethod
            def reset(cls): cls.count = 0
            @staticmethod
            def unrelated(self): self.not_a_field = 1
        class Other:
            def update(self, obj):
                self.item = 0
                obj.foreign = 1
        """))
    project = analyze_files((source,), disable_sg=True).project
    module = project.modules[0]
    symbols = {symbol.name: symbol for symbol in module.symbols}
    assert module.attributes is not None
    fields = {(field.declaring_class_id, field.name): field for field in module.attributes}
    widget, other = symbols["Widget"], symbols["Other"]
    assert set(fields) == {
        (widget.id, name) for name in ("count", "pending", "left", "right", "item", "first", "second")
    } | {(other.id, "item")}
    count, item = fields[widget.id, "count"], fields[widget.id, "item"]
    assert count.storage == frozenset({"class"})
    assert item.storage == frozenset({"instance"})
    assert count.writes == frozenset({"class"})
    assert item.writes == frozenset({"instance"})
    assert fields[widget.id, "pending"].writes == frozenset()
    assert item.owner_id == symbols["__init__"].id
    assert (item.span.start_line, item.span.start_col, item.span.end_col) == (8, 8, 17)
    assert fields[other.id, "item"].id != item.id
    assert module.source_uses is not None
    writes = [use for use in module.source_uses if use.declared_attribute_id == item.id]
    assert {(use.kind, use.span.start_line) for use in writes} == {
        ("attribute-write", 8), ("attribute-write", 9), ("attribute-read-write", 10),
    }
    assert len([use for use in module.source_uses if use.declared_attribute_id == count.id]) == 3
    assert project.attributes_by_id[item.id] is item


@pytest.fixture
def annotated_project(tmp_path: Path) -> ProjectIR:
    """Analyze class attributes with a range of declared types and direct bases."""
    dependency = tmp_path / "dependency.py"
    dependency.write_text("class Parent: pass\nclass Payload: pass\n")
    source = tmp_path / "types.py"
    source.write_text(dedent("""\
        from dependency import Parent as Root, Payload
        from typing import Optional, ClassVar, Literal, Annotated, Self
        class Node(Root, unknown_base, factory(), metaclass=Meta, **options):
            first: Payload
            second: Payload
            parent: "Node | None"
            children: list["Node"]
            maybe: Optional[Payload]
            cache: ClassVar[dict[str, Payload]]
            mode: Literal["fast", 1]
            marked: Annotated[Payload, "metadata"]
            recursive: Self
            unresolved: "Missing"
            not_a_class: int
            opaque: make_type()
            def __init__(self, value: Payload):
                local: Payload
                self.forward: "Later"
        class Later: pass
        """))
    return analyze_files((source, dependency), disable_sg=True).project


def test_declared_types_preserve_structure_and_uncertainty(annotated_project: ProjectIR) -> None:
    """Field populations and structured type targets remain separate facts."""
    module = next(module for module in annotated_project.modules if module.name == "types")
    assert module.attributes is not None
    fields = {field.name: field for field in module.attributes}
    symbols = {symbol.name: symbol for symbol in annotated_project.symbols_by_id.values()}
    node, payload = symbols["Node"], symbols["Payload"]
    first, = fields["first"].declared_types
    second, = fields["second"].declared_types
    assert first.category == second.category == "class"
    assert first.resolution.target_id == second.resolution.target_id == payload.id
    assert fields["first"].id != fields["second"].id
    assert {"local", "value"}.isdisjoint(fields)
    recursive, = fields["parent"].declared_types
    assert recursive.form == "union"
    assert recursive.is_forward
    assert [arg.category for arg in recursive.arguments] == ["class", "primitive"]
    assert recursive.arguments[0].resolution.target_id == node.id
    children, = fields["children"].declared_types
    assert (children.form, children.name) == ("generic", "list")
    assert children.category == "other"
    assert children.arguments[0].is_forward
    assert children.arguments[0].resolution.target_id == node.id
    maybe, = fields["maybe"].declared_types
    assert maybe.resolution.qualified_name == "typing.Optional"
    assert maybe.arguments[0].resolution.target_id == payload.id
    cache, = fields["cache"].declared_types
    assert cache.resolution.qualified_name == "typing.ClassVar"
    assert [arg.category for arg in cache.arguments[0].arguments] == ["primitive", "class"]
    mode, = fields["mode"].declared_types
    marked, = fields["marked"].declared_types
    assert [arg.form for arg in mode.arguments] == ["literal", "literal"]
    assert marked.arguments[1].form == "literal"
    assert marked.arguments[0].resolution.target_id == payload.id
    self_type, = fields["recursive"].declared_types
    assert self_type.category == "class"
    assert self_type.resolution.target_id == node.id
    unresolved, = fields["unresolved"].declared_types
    assert unresolved.category == "unknown"
    assert unresolved.resolution.status == "unresolved"
    primitive, = fields["not_a_class"].declared_types
    assert primitive.category == "primitive"
    opaque, = fields["opaque"].declared_types
    assert (opaque.form, opaque.category) == ("unknown", "unknown")
    forward, = fields["forward"].declared_types
    assert forward.resolution.target_id == symbols["Later"].id


def test_direct_bases_exclude_keywords_without_inventing_dynamic_targets(annotated_project: ProjectIR) -> None:
    """Only positional base expressions are relations; metaclass is not a base."""
    symbols = {symbol.name: symbol for symbol in annotated_project.symbols_by_id.values()}
    node, parent = symbols["Node"], symbols["Parent"]
    assert node.direct_bases is not None
    assert [base.spelling for base in node.direct_bases] == ["Root", "unknown_base", "factory()"]
    assert node.direct_bases[0].resolution.target_id == parent.id
    assert [base.resolution.status for base in node.direct_bases[1:]] == ["unresolved", "unresolved"]
    assert symbols["Later"].direct_bases == ()


def test_nested_empty_and_unsupported_facts_have_explicit_coverage(tmp_path: Path) -> None:
    """Availability and lexical identity survive empty and partially modeled syntax."""
    empty = tmp_path / "empty.py"
    empty.write_text("")
    cpp = tmp_path / "generic.cpp"
    cpp.write_text("class Generic {};\n")
    source = tmp_path / "nested.py"
    source.write_text(dedent("""\
        from abc import abstractmethod as contract
        class Outer:
            class Inner:
                field: int
                def update(self): self.field = 1
            @contract
            def pending(self):
                ("doc" "string")
                ...
            def expression(self):
                rf"not a docstring"
                ...
            def rebound(self):
                self = factory()
                self.unknown = 1
            @staticmethod
            def static(self): self.unknown = 1
            def normal(self):
                self.__dict__["dynamic"] = 1
                setattr(self, "other", 2)
        class Generic[T]:
            field: T
        """))
    project = analyze_files((empty, cpp, source), disable_sg=True).project
    assert project.modules_by_file[empty.resolve()].attributes == ()
    generic = project.modules_by_file[cpp.resolve()]
    assert generic.attributes is None
    assert generic.symbols[0].direct_bases is None
    assert generic.symbols[0].callable_facts is None
    module = project.modules_by_file[source.resolve()]
    assert module.attributes is not None
    symbols = {symbol.name: symbol for symbol in module.symbols}
    fields = {(field.declaring_class_id, field.name): field for field in module.attributes}
    assert set(fields) == {(symbols["Inner"].id, "field"), (symbols["Generic"].id, "field")}
    field = fields[symbols["Inner"].id, "field"]
    assert field.storage == frozenset({"class", "instance"})
    assert symbols["Inner"].owner_id == symbols["Outer"].id
    pending, expression = symbols["pending"].callable_facts, symbols["expression"].callable_facts
    assert pending is not None
    assert expression is not None
    assert pending.is_abstract
    assert pending.body_kind == "ellipsis"
    assert expression.body_kind == "implemented"
    parameter, = fields[symbols["Generic"].id, "field"].declared_types
    assert parameter.category == "unknown"
    assert parameter.resolution.status == "unsupported"
    assert parameter.resolution.reason == "type-parameter"
    again = analyze_files((source,), disable_sg=True).project
    assert set(again.attributes_by_id) == set(project.attributes_by_id)
    assert analyze_files((), disable_sg=True).project.attributes_by_id == {}
    with pytest.raises(TypeError):
        project.attributes_by_id[field.id] = field  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        field.name = "changed"
    with pytest.raises(ValidationError):
        parameter.category = "class"
    with pytest.raises(ValidationError):
        pending.is_abstract = False


def test_type_resolution_requires_class_evidence_and_preserves_repeated_annotations(tmp_path: Path) -> None:
    """Imports, ambiguity, aliases, and shadowing never fabricate a class target."""
    dependency = tmp_path / "dependency.py"
    dependency.write_text("class Payload: pass\n")
    source = tmp_path / "evidence.py"
    source.write_text(dedent("""\
        from dependency import Payload, Missing
        from external import Foreign
        from typing import Callable
        if condition:
            class Choice: pass
        else:
            class Choice: pass
        def not_a_type(): pass
        Alias = Payload
        str = factory()
        class Owner:
            field: Payload
            field: int = 1
            field = 2
            ambiguous: Choice
            absent: Missing
            external: Foreign
            alias: Alias
            shadowed: str
            function: not_a_type
            callback: Callable[[Payload, int], Payload]
        class Nested(Owner.Inner): pass
        """))
    project = analyze_files((source, dependency), disable_sg=True).project
    module = project.modules_by_file[source.resolve()]
    assert module.attributes is not None
    fields = {field.name: field for field in module.attributes}
    field = fields["field"]
    assert field.span.start_line == 12
    assert len(field.declared_types) == 2
    assert [reference.category for reference in field.declared_types] == ["class", "primitive"]
    assert module.source_uses is not None
    assert {use.span.start_line for use in module.source_uses if use.declared_attribute_id == field.id} == {13, 14}
    ambiguous, = fields["ambiguous"].declared_types
    assert ambiguous.category == "unknown"
    assert ambiguous.resolution.status == "ambiguous"
    assert len(ambiguous.resolution.candidate_ids) == 2
    for name, status in (("absent", "unresolved"), ("external", "external"), ("alias", "unresolved"), ("shadowed", "unresolved")):
        reference, = fields[name].declared_types
        assert reference.category == "unknown"
        assert reference.resolution.status == status
    function, = fields["function"].declared_types
    assert function.category == "other"
    callback, = fields["callback"].declared_types
    assert [argument.category for argument in callback.arguments[0].arguments] == ["class", "primitive"]
    assert callback.arguments[1].category == "class"
    nested = next(symbol for symbol in module.symbols if symbol.name == "Nested")
    assert nested.direct_bases is not None
    assert nested.direct_bases[0].resolution.reason == "receiver-needs-member-resolution"
    without_dependency = analyze_files((source,), disable_sg=True).project.modules[0]
    assert without_dependency.attributes is not None
    imported = next(attribute for attribute in without_dependency.attributes if attribute.name == "field").declared_types[0]
    assert imported.resolution.status == "external"
    assert imported.category == "unknown"


def test_annotation_evidence_keeps_parentheses_and_utf8_locations(tmp_path: Path) -> None:
    """Structured references preserve their complete source spelling and byte ranges."""
    source = tmp_path / "unicode.py"
    source.write_text('class Café:\n    résumé: ("Café")\n')
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.attributes is not None
    field, = module.attributes
    reference, = field.declared_types
    assert field.name == "résumé"
    assert (field.span.start_line, field.span.start_col, field.span.end_col) == (2, 4, 12)
    assert reference.spelling == '("Café")'
    assert (reference.span.start_col, reference.span.end_col) == (14, 23)
    assert reference.resolution.target_id == module.symbols[0].id


def test_callable_binding_and_placeholder_facts_use_lexical_evidence(tmp_path: Path) -> None:
    """Decorator aliases count as evidence; names and top-level functions are not classes."""
    source = tmp_path / "markers.py"
    source.write_text(dedent('''\
        from builtins import classmethod as factory
        from types import NoneType
        def abstractmethod(function): return function
        @classmethod
        def standalone(cls): cls.not_a_field = 1
        class Owner:
            global redirected
            redirected = 1
            @factory
            def reset(cls): cls.field: NoneType = None
            def documented(self):
                """Only documentation."""
            @abstractmethod
            def ordinary(self): pass
        '''))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    callables = {symbol.name: symbol.callable_facts for symbol in module.symbols if symbol.callable_facts is not None}
    assert callables["standalone"].binding == "function"
    assert callables["standalone"].declaring_class_id is None
    assert callables["reset"].binding == "class"
    assert callables["documented"].body_kind == "empty"
    assert callables["documented"].implementation_id is None
    assert callables["ordinary"].is_abstract is False
    assert module.attributes is not None
    field, = module.attributes
    assert field.name == "field"
    assert field.storage == frozenset({"class"})
    assert field.declared_types[0].category == "primitive"


def test_parenthesized_decorators_keep_descriptor_and_abstract_evidence(tmp_path: Path) -> None:
    """Grouping preserves semantic decorator evidence for binding and dispatch."""
    source = tmp_path / "grouped.py"
    source.write_text(dedent("""\
        from abc import abstractmethod
        class Owner:
            @(staticmethod)
            def static(obj): obj.not_a_field = 1
            @((abstractmethod))
            def pending(self): ...
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    callables = {symbol.name: symbol.callable_facts for symbol in module.symbols if symbol.callable_facts is not None}
    assert callables["static"].binding == "static"
    assert callables["static"].dispatch_supported is True
    assert callables["pending"].is_abstract
    assert callables["pending"].dispatch_supported is True
    assert callables["pending"].implementation_id is None
    assert module.attributes == ()


def test_annotation_only_receiver_declarations_do_not_count_as_rebinding(tmp_path: Path) -> None:
    """A local annotation can describe the receiver without replacing its binding."""
    source = tmp_path / "receiver.py"
    source.write_text(dedent("""\
        class Owner:
            def update(self):
                self: Owner
                self.field = 1
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.attributes is not None
    field, = module.attributes
    assert field.name == "field"
    assert module.source_uses is not None
    write, = module.source_uses
    assert write.declared_attribute_id == field.id


def test_shadowed_standard_modules_cannot_prove_primitive_or_typing_categories(tmp_path: Path) -> None:
    """A missing member in a retained module remains unknown despite its spelling."""
    types = tmp_path / "types.py"
    types.write_text("")
    typing = tmp_path / "typing.py"
    typing.write_text("")
    source = tmp_path / "shadow.py"
    source.write_text("from types import NoneType\nfrom typing import Optional\nclass Owner:\n    field: NoneType\n    wrapper: Optional[int]\n")
    project = analyze_files((source, types, typing), disable_sg=True).project
    module = project.modules_by_file[source.resolve()]
    assert module.attributes is not None
    for field in module.attributes:
        reference, = field.declared_types
        assert reference.resolution.status == "unresolved"
        assert reference.category == "unknown"


def test_class_write_occurrences_preserve_control_flow_depth(tmp_path: Path) -> None:
    """A class-name write and its initializer share syntactic execution context."""
    source = tmp_path / "depth.py"
    source.write_text("class Owner:\n    if condition:\n        for item in items:\n            field = factory()\n")
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    assert {(use.target_spelling, use.nesting, use.execution_kind) for use in module.source_uses} == {
        ("field", 2, "class"), ("factory", 2, "class"),
    }
