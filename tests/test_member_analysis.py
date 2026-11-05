"""Member and dispatch contracts observed at the source-to-analysis seam."""

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from scb_check.pipeline import analyze_files
from scb_check.tree_walking.models import EffectKind


def test_member_lookup_uses_c3_and_keeps_static_and_runtime_targets_separate(tmp_path: Path) -> None:
    """Inherited calls select original bodies, while typed receivers admit overrides."""
    source = tmp_path / "hierarchy.py"
    source.write_text(dedent("""\
        class Root:
            def work(self): return 1
        class Left(Root): pass
        class Right(Root):
            def work(self): return 2
        class Diamond(Left, Right):
            def run(self):
                self.work()
                Root.work(self)
        class Override(Diamond):
            def work(self): return 3
        def caller(value: Diamond):
            value.work()
            value.work()
        Diamond.work(None)
        """))
    project = analyze_files((source,), disable_sg=True).project
    symbols = project.symbols_by_qualified_name
    right = symbols["hierarchy.Right.work"]
    root = symbols["hierarchy.Root.work"]
    override = symbols["hierarchy.Override.work"]
    diamond = symbols["hierarchy.Diamond"]
    calls = {use.span.start_line: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    assert calls[8].resolution.target_id == right.id
    assert calls[9].resolution.target_id == root.id
    assert calls[13].resolution.target_id == right.id
    assert calls[14].resolution.target_id == right.id
    assert calls[15].resolution.target_id == right.id
    assert calls[13].runtime_targets.status == "complete"
    assert calls[13].runtime_targets.assumption == "closed-project-hierarchy"
    assert set(calls[13].runtime_targets.target_ids) == {right.id, override.id}
    assert calls[9].runtime_targets.target_ids == (root.id,)
    assert calls[15].runtime_targets.target_ids == (right.id,)
    assert project.member_lookup[diamond.id]["work"].target_id == right.id
    assert right.callable_facts is not None
    assert right.callable_facts.declaring_class_id == symbols["hierarchy.Right"].id
    assert len([symbol for symbol in project.symbols_by_id.values() if symbol.name == "work"]) == 3
    assert len([use for use in calls.values() if use.target_spelling == "value.work"]) == 2


def test_imported_receivers_fields_and_declared_locals_resolve_to_canonical_members(tmp_path: Path) -> None:
    """Imports, annotations, and direct receiver fields connect uses across modules."""
    dependency = tmp_path / "dependency.py"
    dependency.write_text(dedent("""\
        class Payload:
            def send(self): return 1
        class Base:
            item: Payload
            @classmethod
            def create(cls): return cls
            @staticmethod
            def utility(): return 1
            def run(this): return this.item.send()
        """))
    source = tmp_path / "consumer.py"
    source.write_text(dedent("""\
        from dependency import Base as Parent, Payload
        import dependency as dep
        class Child(Parent):
            def execute(self, value: Payload):
                local: Payload
                local.send()
                value.send()
                self.item.send()
                self.saved = value
                self.create()
                self.utility()
        dep.Base.utility()
        Parent.create()
        """))
    project = analyze_files((source, dependency), disable_sg=True).project
    symbols = project.symbols_by_qualified_name
    send = symbols["dependency.Payload.send"]
    calls = {use.target_spelling: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    for name in ("local.send", "value.send", "self.item.send", "this.item.send"):
        assert calls[name].resolution.target_id == send.id
        assert calls[name].runtime_targets.target_ids == (send.id,)
    assert calls["self.create"].resolution.target_id == symbols["dependency.Base.create"].id
    assert calls["Parent.create"].runtime_targets.target_ids == (symbols["dependency.Base.create"].id,)
    assert calls["dep.Base.utility"].resolution.target_id == symbols["dependency.Base.utility"].id
    field = next(field for field in project.attributes_by_id.values() if field.name == "item" and field.declaring_class_id == symbols["dependency.Base"].id)
    read = next(use for use in project.source_uses_by_id.values() if use.target_spelling == "self.item" and use.kind == "attribute-read")
    assert read.resolution.target_id == field.id
    assert project.member_lookup[symbols["consumer.Child"].id]["item"].target_id == field.id
    assert len([field for field in project.attributes_by_id.values() if field.name == "item"]) == 1


def test_annotation_scope_shadowing_and_unsupported_receivers_do_not_guess_targets(tmp_path: Path) -> None:
    """Header type names resolve outside the parameter scope; rebinding disables inference."""
    source = tmp_path / "scope.py"
    source.write_text(dedent("""\
        class Payload:
            def send(self): return 1
        def header(Payload: Payload): Payload.send()
        def rebound(value: Payload):
            value = unknown()
            value.send()
        def union(value: Payload | None): value.send()
        def wrapped(value: list[Payload]): value.send()
        def dynamic(value): value.send()
        def unsupported(value: Payload):
            return lambda: value.send()
        def forward(value: "Payload"): value.send()
        """))
    project = analyze_files((source,), disable_sg=True).project
    send = project.symbols_by_qualified_name["scope.Payload.send"]
    calls = {use.span.start_line: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    assert calls[3].resolution.target_id == send.id
    assert calls[12].resolution.target_id == send.id
    for line in (6, 7, 8, 9, 11):
        assert calls[line].resolution.status in {"unresolved", "unsupported", "ambiguous"}
        assert calls[line].runtime_targets.status == "unavailable"
        assert calls[line].runtime_targets.target_ids == ()
    assert calls[6].resolution.reason == "multiple-lexical-bindings"
    assert calls[11].owner_id is None


def test_unknown_hierarchies_and_descriptors_publish_target_uncertainty(tmp_path: Path) -> None:
    """Unknown bases, duplicate members, placeholders, and decorators are not empty sets."""
    source = tmp_path / "uncertain.py"
    source.write_text(dedent("""\
        class Base:
            def work(self): return 1
            def missing(self): ...
            @custom
            def decorated(self): return 2
            @property
            def computed(self): return 3
            def duplicate(self): return 4
            def duplicate(self): return 5
        class Unknown(Base, External): pass
        def calls(value: Base, uncertain: Unknown):
            value.work()
            value.missing()
            value.decorated()
            value.computed()
            value.duplicate()
            uncertain.work()
            missing()
        """))
    project = analyze_files((source,), disable_sg=True).project
    calls = {use.target_spelling: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    work = project.symbols_by_qualified_name["uncertain.Base.work"]
    assert calls["value.work"].resolution.target_id == work.id
    assert calls["value.work"].runtime_targets.status == "approximate"
    assert calls["value.work"].runtime_targets.target_ids == (work.id,)
    for spelling in ("value.missing", "value.decorated", "value.computed", "value.duplicate", "uncertain.work", "missing"):
        assert calls[spelling].runtime_targets.status == "unavailable"
        assert calls[spelling].runtime_targets.target_ids == ()
    assert calls["value.duplicate"].resolution.status == "ambiguous"
    assert len(calls["value.duplicate"].resolution.candidate_ids) == 2
    assert calls["uncertain.work"].resolution.reason == "unknown-member-order"


def test_inconsistent_mro_and_cycles_do_not_select_an_arbitrary_inherited_member(tmp_path: Path) -> None:
    """Invalid/unknown Python hierarchies remain retained evidence, not guessed lookup."""
    source = tmp_path / "invalid.py"
    source.write_text(dedent("""\
        class X:
            def work(self): return 1
        class Y: pass
        class A(X, Y): pass
        class B(Y, X): pass
        class Invalid(A, B): pass
        class Cycle(Other): pass
        class Other(Cycle): pass
        class Repeated(X, X): pass
        Invalid.work(None)
        Cycle.work(None)
        Repeated.work(None)
        """))
    project = analyze_files((source,), disable_sg=True).project
    calls = [use for use in project.source_uses_by_id.values() if use.kind == "call"]
    assert len(calls) == 3
    assert all(use.resolution.reason == "unknown-member-order" for use in calls)
    assert all(use.runtime_targets.status == "unavailable" for use in calls)


def test_candidate_inputs_connect_entities_uses_types_and_multilevel_text() -> None:
    """The candidate gate validates evidence and ownership, not metric scores."""
    root = Path(__file__).parent / "fixtures" / "ir_contract"
    project = analyze_files(tuple(root.rglob("*.py")), disable_sg=True).project
    symbols = project.symbols_by_qualified_name
    model, payload = symbols["domain.model.Model"], symbols["domain.model.Payload"]
    run, send = symbols["domain.model.Model.run"], symbols["domain.model.Payload.send"]
    base_work = symbols["domain.model.Base.work"]
    uses = tuple(project.source_uses_by_id.values())
    calls = [use for use in uses if use.kind == "call"]
    # CBO/RFC/MPC: sites, execution class, static implementation, and dispatch bodies.
    outgoing = [use for use in calls if use.owner_id == run.id]
    assert [use.resolution.target_id for use in outgoing] == [send.id, send.id, base_work.id, symbols["domain.model.Model.own"].id]
    assert all(use.runtime_targets.status == "complete" for use in outgoing)
    assert project.member_lookup[model.id]["work"].target_id == base_work.id
    assert base_work.callable_facts is not None
    assert base_work.callable_facts.declaring_class_id == symbols["domain.model.Base"].id
    # Callers/RIC: repeated sites retain distinct IDs and their distinct source owners.
    incoming = [use for use in calls if use.resolution.target_id == run.id]
    assert len(incoming) == 4
    assert len({use.id for use in incoming}) == 4
    assert {use.owner_id for use in incoming} == {symbols["client.Client.invoke"].id, symbols["client.caller"].id, project.modules_by_file[(root / "client.py").resolve()].id}
    recursive = next(use for use in calls if use.owner_id == symbols["domain.model.Model.own"].id)
    assert recursive.resolution.target_id == recursive.owner_id
    # Attribute-only use, field volume, and declared types remain independent facts.
    fields = {field.name: field for field in project.attributes_by_id.values() if field.declaring_class_id == model.id}
    assert fields["first"].id != fields["second"].id
    assert fields["first"].declared_types[0].resolution.target_id == payload.id
    assert fields["second"].declared_types[0].resolution.target_id == payload.id
    assert fields["recursive"].declared_types[0].resolution.target_id == model.id
    assert fields["ancestor"].declared_types[0].resolution.target_id == symbols["domain.model.Base"].id
    assert fields["primitive"].declared_types[0].category == "primitive"
    assert fields["unknown"].declared_types[0].category == "unknown"
    assert fields["wrapped"].declared_types[0].form == "generic"
    assert "inherited" not in fields
    size = next(field for field in project.attributes_by_id.values() if field.name == "size")
    assert {use.owner_id for use in uses if use.resolution.target_id == size.id} == {run.id, symbols["client.Client.inspect"].id}
    # Class-category/module edges can recover both endpoints without parsing paths.
    invoke = symbols["client.Client.invoke"]
    assert invoke.module_id != run.module_id
    assert invoke.owner_id == symbols["client.Client"].id
    assert run.module_id is not None
    assert project.modules_by_id[run.module_id].name == "domain.model"
    # CIC has direct ancestry and canonical implementation/field owners, not copies.
    assert model.direct_bases is not None
    assert model.direct_bases[0].resolution.target_id == symbols["domain.model.Base"].id
    assert base_work.id not in project.entities_by_owner[model.id]
    # CSE selects originals at method, class (with descendants), or whole-file level.
    assert model.module_id is not None
    module = project.modules_by_id[model.module_id]
    assert module.text_fragments is not None
    inner = symbols["domain.model.Model.nested.inner"]
    assert inner.owner_id == symbols["domain.model.Model.nested"].id
    assert any(fragment.text == '"""Inner document."""' and fragment.owner_id == inner.id for fragment in module.text_fragments)
    assert any(fragment.text == "# Run comment document." and fragment.owner_id == run.id for fragment in module.text_fragments)
    assert len({fragment.span for fragment in module.text_fragments}) == len(module.text_fragments)


def test_snapshot_facts_are_independent_readonly_and_preserve_rule_projections(tmp_path: Path) -> None:
    """Replacing source cannot mutate an earlier analysis or its lookup views."""
    source = tmp_path / "snapshot.py"
    source.write_text("class Owner:\n    def work(self): return 1\n    def run(self, value: Owner): return value.work()\n")
    before = analyze_files((source,), disable_sg=True)
    source.write_text("class Owner:\n    def work(self): return 1\n    def run(self, value: Owner): return value.lost()\n")
    after = analyze_files((source,), disable_sg=True)
    first = next(use for use in before.project.source_uses_by_id.values() if use.kind == "call")
    second = next(use for use in after.project.source_uses_by_id.values() if use.kind == "call")
    assert first.resolution.status == "project"
    assert first.runtime_targets.status == "complete"
    assert second.resolution.status == "unresolved"
    assert second.runtime_targets.status == "unavailable"
    run = before.project.symbols_by_qualified_name["snapshot.Owner.run"]
    effects = before.project.effects_by_symbol[run.id]
    assert effects is not None
    assert any(effect.kind == EffectKind.UNRESOLVED_CALL and effect.source_use_id == first.id for effect in effects)
    assert run.owner_id is not None
    with pytest.raises(TypeError):
        before.project.member_lookup[run.owner_id]["work"] = second.resolution  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError):
        before.project.entities_by_owner[run.owner_id] = ()  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        first.runtime_targets.status = "unavailable"
    assert first.receiver is not None
    with pytest.raises(ValidationError):
        first.receiver.member_path = ()


def test_empty_nested_and_generic_analysis_preserve_family_coverage(tmp_path: Path) -> None:
    """Missing semantic families differ from successful empty Python extraction."""
    empty = tmp_path / "empty.py"
    empty.write_text("")
    generic = tmp_path / "generic.rs"
    generic.write_text("fn work() {}\n")
    source = tmp_path / "nested.py"
    source.write_text(dedent("""\
        class Outer:
            class Inner:
                def café(self): return 1
                def __hidden(self): return 2
                def __len__(self): return 3
        Outer.Inner.café(None)
        Outer.Inner.__hidden(None)
        Outer.Inner.__len__(None)
        """))
    project = analyze_files((empty, generic, source), disable_sg=True).project
    python = project.modules_by_file[empty.resolve()]
    rust = project.modules_by_file[generic.resolve()]
    assert python.source_uses == python.attributes == python.text_fragments == ()
    assert rust.source_uses is rust.attributes is rust.text_fragments is None
    assert rust.symbols[0].callable_facts is None
    calls = {use.target_spelling: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    assert calls["Outer.Inner.café"].resolution.target_id == project.symbols_by_qualified_name["nested.Outer.Inner.café"].id
    assert calls["Outer.Inner.__hidden"].resolution.status == "unsupported"
    assert calls["Outer.Inner.__hidden"].runtime_targets.status == "unavailable"
    assert calls["Outer.Inner.__len__"].runtime_targets.status == "complete"
    assert analyze_files((empty, generic), disable_sg=True).project.member_lookup == {}
    assert analyze_files((), disable_sg=True).project.entities_by_owner == {}


@pytest.mark.parametrize("duplicate_child", [False, True])
def test_package_member_paths_preserve_child_module_ambiguity(tmp_path: Path, *, duplicate_child: bool) -> None:
    """Package paths resolve unique child modules without choosing between duplicate names."""
    package = tmp_path / "left" / "pkg"
    package.mkdir(parents=True)
    parent = package / "__init__.py"
    parent.write_text("")
    child = package / "child.py"
    child.write_text("class Worker:\n    @staticmethod\n    def work(): return 1\n")
    caller = tmp_path / "caller.py"
    caller.write_text("import pkg\npkg.child.Worker.work()\n")
    sources = [caller, child, parent]
    if duplicate_child:
        other_package = tmp_path / "right" / "pkg"
        other_package.mkdir(parents=True)
        (other_package / "__init__.py").write_text("")
        other_child = other_package / "child.py"
        other_child.write_text(child.read_text())
        sources.append(other_child)

    project = analyze_files(tuple(sources), disable_sg=True).project
    call = next(use for use in project.source_uses_by_id.values() if use.kind == "call")
    if duplicate_child:
        assert call.resolution.status == "unresolved"
        assert call.runtime_targets.status == "unavailable"
        child_use = next(use for use in project.source_uses_by_id.values() if use.target_spelling == "pkg.child")
        assert child_use.resolution.status == "ambiguous"
        assert set(child_use.resolution.candidate_ids) == {
            module.id for module in project.modules if module.module_name == "pkg.child"
        }
    else:
        method = project.symbols_by_qualified_name["pkg.child.Worker.work"]
        assert call.resolution.target_id == method.id
        assert call.runtime_targets.target_ids == (method.id,)
        assert call.runtime_targets.status == "complete"


def test_self_receiver_identity_survives_local_classes_and_qualified_name_collisions(tmp_path: Path) -> None:
    """A syntactic receiver class is selected by declaration ID, not a global name."""
    sources = []
    for directory in ("left", "right"):
        parent = tmp_path / directory
        parent.mkdir()
        source = parent / "same.py"
        source.write_text(dedent("""\
            class Owner:
                def work(self): return 1
                def run(self): return self.work()
            def factory():
                class Local:
                    def work(self): return 2
                    def run(self): return self.work()
                return Local
            """))
        sources.append(source)
    project = analyze_files(tuple(sources), disable_sg=True).project
    calls = [use for use in project.source_uses_by_id.values() if use.kind == "call"]
    assert len(calls) == 4
    for use in calls:
        assert use.owner_id is not None
        assert use.resolution.target_id is not None
        owner = project.symbols_by_id[use.owner_id]
        target = project.symbols_by_id[use.resolution.target_id]
        assert owner.owner_id == target.owner_id
        assert owner.file_id == target.file_id
        assert use.runtime_targets.status == "complete"


def test_class_object_lookup_excludes_instance_only_fields(tmp_path: Path) -> None:
    """Instance writes cannot replace class namespace entries in explicit class lookup."""
    source = tmp_path / "namespaces.py"
    source.write_text(dedent("""\
        class Payload:
            def send(self): return 1
        class Base:
            def __init__(self):
                self.work = unknown()
                self.item: Payload
            def work(self): return 2
            @classmethod
            def invoke(cls): return cls.work(None)
        class Child(Base):
            def work(self): return 3
        Base.work(None)
        Base.item.send()
        def caller(value: Base): value.work()
        def subclass(value: Child): value.work()
        """))
    project = analyze_files((source,), disable_sg=True).project
    calls = {use.target_spelling: use for use in project.source_uses_by_id.values() if use.kind == "call"}
    method = project.symbols_by_qualified_name["namespaces.Base.work"]
    base = project.symbols_by_qualified_name["namespaces.Base"]
    assert calls["Base.work"].resolution.target_id == method.id
    assert calls["Base.work"].runtime_targets.target_ids == (method.id,)
    assert calls["Base.item.send"].resolution.status == "unresolved"
    assert calls["Base.item.send"].runtime_targets.status == "unavailable"
    assert calls["value.work"].resolution.status == "ambiguous"
    assert project.member_lookup[base.id]["work"].status == "ambiguous"
    assert calls["cls.work"].resolution.target_id == method.id
    assert calls["cls.work"].runtime_targets.status == "complete"
    assert set(calls["cls.work"].runtime_targets.target_ids) == {method.id, project.symbols_by_qualified_name["namespaces.Child.work"].id}
    assert project.class_member_lookup[base.id]["work"].target_id == method.id
    assert "item" not in project.class_member_lookup[base.id]


def test_multistep_polymorphic_receiver_paths_do_not_claim_complete_targets(tmp_path: Path) -> None:
    """An override of an intermediate class-valued member can change final targets."""
    source = tmp_path / "paths.py"
    source.write_text(dedent("""\
        class Holder:
            class Nested:
                def work(self): return 1
        class Child(Holder):
            class Nested:
                def work(self): return 2
        def caller(value: Holder): value.Nested.work(None)
        """))
    project = analyze_files((source,), disable_sg=True).project
    call = next(use for use in project.source_uses_by_id.values() if use.kind == "call")
    assert call.resolution.target_id == project.symbols_by_qualified_name["paths.Holder.Nested.work"].id
    assert call.runtime_targets.status == "approximate"


def test_nested_class_annotations_and_bases_match_imported_declaration_paths(tmp_path: Path) -> None:
    """Direct nested type declarations connect receiver and inheritance evidence."""
    source = tmp_path / "nested_types.py"
    source.write_text(dedent("""\
        class Outer:
            class Base:
                def work(self): return 1
        class Child(Outer.Base):
            def run(self): return self.work()
        def local(value: Outer.Base): return value.work()
        """))
    imported = tmp_path / "consumer.py"
    imported.write_text("from nested_types import Outer\ndef imported(value: Outer.Base): return value.work()\n")
    project = analyze_files((source, imported), disable_sg=True).project
    base = project.symbols_by_qualified_name["nested_types.Outer.Base"]
    method = project.symbols_by_qualified_name["nested_types.Outer.Base.work"]
    child = project.symbols_by_qualified_name["nested_types.Child"]
    assert child.direct_bases is not None
    assert child.direct_bases[0].resolution.target_id == base.id
    calls = [use for use in project.source_uses_by_id.values() if use.kind == "call"]
    assert len(calls) == 3
    assert all(use.resolution.target_id == method.id for use in calls)
    assert all(use.runtime_targets.status == "complete" for use in calls)


def test_annotation_only_class_fields_do_not_shadow_inherited_namespace_bindings(tmp_path: Path) -> None:
    """Annotations retain field evidence but create no runtime class namespace entry."""
    source = tmp_path / "annotations.py"
    source.write_text(dedent("""\
        class Base:
            def work(self): return 1
        class Child(Base):
            work: int
            field: int
            def annotate(self): self.work: int
        Child.work(None)
        def caller(value: Child): return value.work()
        """))
    project = analyze_files((source,), disable_sg=True).project
    method = project.symbols_by_qualified_name["annotations.Base.work"]
    child = project.symbols_by_qualified_name["annotations.Child"]
    calls = [use for use in project.source_uses_by_id.values() if use.kind == "call"]
    assert len(calls) == 2
    assert all(use.resolution.target_id == method.id for use in calls)
    assert all(use.runtime_targets.target_ids == (method.id,) for use in calls)
    fields = {field.name: field for field in project.attributes_by_id.values()}
    assert fields["work"].declaring_class_id == child.id
    assert fields["work"].writes == frozenset()
    assert project.member_lookup[child.id]["field"].target_id == fields["field"].id
    assert "field" not in project.class_member_lookup[child.id]
