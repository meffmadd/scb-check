"""Canonical source uses observed through the exported analysis contract."""

from collections import Counter
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from scb_check.pipeline import analyze_files
from scb_check.rules.low_use_short_function import LowUseShortFunctionSettings
from scb_check.tree_walking.semantic import build_project


def test_calls_preserve_sites_recursion_and_nested_executable_syntax(tmp_path: Path) -> None:
    """Occurrences are neither deduplicated nor restricted to shallow body summaries."""
    source = tmp_path / "sample.py"
    source.write_text(dedent("""\
        def helper(value):
            return helper(value)
        def run(value):
            if value:
                helper(helper(value))
            for item in value:
                helper(item)
            return helper(value) + helper(value)
        helper(0)
        """))

    project = analyze_files((source,), disable_sg=True).project
    module = project.modules[0]
    helper, run = module.symbols
    assert module.source_uses is not None
    calls = [use for use in module.source_uses if use.kind == "call"]
    assert len(calls) == 7
    assert len({use.id for use in calls}) == 7
    assert {use.target_spelling for use in calls} == {"helper"}
    assert {use.resolution.status for use in calls} == {"project"}
    assert {use.resolution.target_id for use in calls} == {helper.id}
    assert {use.owner_id for use in calls if use.span.start_line == 2} == {helper.id}
    assert {use.owner_id for use in calls if 3 < use.span.start_line < 9} == {run.id}
    assert {use.owner_id for use in calls if use.span.start_line == 9} == {module.id}
    again = analyze_files((source,), disable_sg=True).project.modules[0]
    assert again.source_uses is not None
    assert {use.id for use in again.source_uses} == {use.id for use in calls}


def test_import_bindings_resolve_direct_names_without_guessing_receivers(tmp_path: Path) -> None:
    """Imports provide evidence; parameters and dynamic dotted expressions do not."""
    helper_file = tmp_path / "helpers.py"
    helper_file.write_text("def work(): pass\n")
    source = tmp_path / "sample.py"
    source.write_text(dedent("""\
        import json as codec
        from helpers import work as task
        import os.path
        def run(receiver):
            from math import sqrt as root
            task()
            codec.loads('0')
            root(4)
            os.path.join('a', 'b')
            receiver.send()
            unknown.send()
            factory().send()
        def shadow(task, codec):
            task()
            codec.loads('0')
        """))
    project = analyze_files((source, helper_file), disable_sg=True).project
    module = project.modules_by_file[source.resolve()]
    run, shadow = module.symbols
    assert module.imports is not None
    assert module.source_uses is not None
    imports = {(binding.local_name, binding.qualified_name, binding.owner_id) for binding in module.imports}
    assert imports == {
        ("codec", "json", module.id), ("task", "helpers.work", module.id),
        ("os", "os", module.id), ("root", "math.sqrt", run.id),
    }
    calls = {(use.owner_id, use.target_spelling): use for use in module.source_uses if use.kind == "call"}
    assert calls[run.id, "task"].resolution.target_id == project.modules_by_file[helper_file.resolve()].symbols[0].id
    assert {calls[run.id, name].resolution.qualified_name for name in ("codec.loads", "root", "os.path.join")} == {
        "json.loads", "math.sqrt", "os.path.join",
    }
    assert {calls[run.id, name].resolution.status for name in ("codec.loads", "root", "os.path.join")} == {"external"}
    assert {calls[run.id, name].resolution.status for name in ("receiver.send", "unknown.send", "factory().send", "factory")} == {"unresolved"}
    assert {use.resolution.status for (owner, _), use in calls.items() if owner == shadow.id} == {"unresolved"}
    assert len(module.imports) == len({binding.id for binding in module.imports})


def test_attribute_occurrences_record_access_modes_and_receiver_evaluation(tmp_path: Path) -> None:
    """Write targets do not turn their receiver attribute evaluations into writes."""
    source = tmp_path / "attrs.py"
    source.write_text(dedent("""\
        def update(obj, values):
            obj.field = obj.other
            obj.field += 1
            del obj.old
            for obj.slot in values:
                obj.child.run(obj.field)
            factory().field = obj.child.value
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    assert Counter((use.target_spelling, use.kind) for use in module.source_uses) == Counter({
        ("obj.field", "attribute-write"): 1,
        ("obj.other", "attribute-read"): 1,
        ("obj.field", "attribute-read-write"): 1,
        ("obj.old", "attribute-delete"): 1,
        ("obj.slot", "attribute-write"): 1,
        ("obj.child.run", "call"): 1,
        ("obj.child.run", "attribute-read"): 1,
        ("obj.child", "attribute-read"): 2,
        ("obj.field", "attribute-read"): 1,
        ("factory().field", "attribute-write"): 1,
        ("factory", "call"): 1,
        ("obj.child.value", "attribute-read"): 1,
    })
    assert {use.owner_id for use in module.source_uses} == {module.symbols[0].id}


def test_execution_owners_differ_from_syntactic_declaration_owners(tmp_path: Path) -> None:
    """Defaults, bases and decorators execute outside bodies; unsupported scopes are explicit."""
    source = tmp_path / "contexts.py"
    source.write_text(dedent("""\
        @decorate(option())
        class Widget(base()):
            setting = initialize()
            def method(self, value=default()):
                def inner(arg=nested_default()):
                    return nested_body()
                return method_body()
        def outer(value=module_default()):
            thunk = lambda value=lambda_default(): lambda_body()
            items = [element() for x in iterable() if predicate()]
            def typed(value: annotation()): pass
            return outer_body()
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    symbols = {symbol.name: symbol for symbol in module.symbols}
    assert module.source_uses is not None
    calls = {use.target_spelling: use for use in module.source_uses if use.kind == "call"}
    for name in ("decorate", "option", "base", "module_default"):
        assert calls[name].owner_id == module.id
        assert calls[name].execution_kind == "module"
    for name in ("initialize", "default"):
        assert calls[name].owner_id == symbols["Widget"].id
        assert calls[name].execution_kind == "class"
    assert calls["nested_default"].owner_id == symbols["method"].id
    assert calls["nested_body"].owner_id == symbols["inner"].id
    assert calls["method_body"].owner_id == symbols["method"].id
    for name in ("lambda_default", "outer_body"):
        assert calls[name].owner_id == symbols["outer"].id
    for name, context in {
        "lambda_body": "lambda", "element": "list_comprehension",
        "iterable": "list_comprehension", "predicate": "list_comprehension",
        "annotation": "annotation",
    }.items():
        assert calls[name].owner_id is None
        assert calls[name].execution_kind == "unsupported"
        assert calls[name].unsupported_context == context
        assert calls[name].resolution.status == "unsupported"


def test_static_resolution_handles_closures_shadowing_and_ambiguity(tmp_path: Path) -> None:
    """Static alternatives stay attached to one occurrence, never multiply source sites."""
    source = tmp_path / "scope.py"
    source.write_text(dedent("""\
        def target(): pass
        def outer():
            def local(): return local()
            def nested(): return local()
            return local()
        def shadow():
            target()
            target = factory()
        if condition:
            def choice(): pass
        else:
            def choice(): pass
        choice(); choice()
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    local = next(symbol for symbol in module.symbols if symbol.name == "local")
    assert module.source_uses is not None
    assert {use.resolution.target_id for use in module.source_uses if use.target_spelling == "local"} == {local.id}
    assert {use.resolution.status for use in module.source_uses if use.target_spelling == "target"} == {"unresolved"}
    choices = [use for use in module.source_uses if use.target_spelling == "choice"]
    assert len(choices) == len({use.id for use in choices}) == 2
    assert {use.resolution.status for use in choices} == {"ambiguous"}
    assert all(len(use.resolution.candidate_ids) == 2 for use in choices)


def test_relative_imports_and_duplicate_project_names_do_not_guess_targets(tmp_path: Path) -> None:
    """Relative aliases resolve within packages; colliding imported names remain ambiguous."""
    package = tmp_path / "pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("from .helpers import work\nwork()\n")
    helper = package / "helpers.py"
    helper.write_text("def work(): pass\n")
    source = package / "sample.py"
    source.write_text("from .helpers import work as task\ndef run(): return task()\n")
    files = (init, helper, source)
    project = analyze_files(files, disable_sg=True).project
    expected = project.modules_by_file[helper.resolve()].symbols[0].id
    for file in (init, source):
        module = project.modules_by_file[file.resolve()]
        assert module.imports is not None
        assert module.source_uses is not None
        assert module.imports[0].qualified_name == "pkg.helpers.work"
        assert {use.resolution.target_id for use in module.source_uses} == {expected}

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = other_dir / "helpers.py"
    other.write_text("def work(): pass\n")
    loose = tmp_path / "helpers.py"
    loose.write_text("def work(): pass\n")
    caller = tmp_path / "caller.py"
    caller.write_text("from helpers import work\nwork()\n")
    project = analyze_files((loose, other, caller), disable_sg=True).project
    uses = project.modules_by_file[caller.resolve()].source_uses
    assert uses is not None
    use, = uses
    assert use.resolution.status == "ambiguous"
    assert len(use.resolution.candidate_ids) == 2
    assert use.resolution.target_id is None


def test_calls_survive_try_with_async_yield_and_nested_expression_syntax(tmp_path: Path) -> None:
    """The occurrence inventory is independent of shallow operation normalization."""
    source = tmp_path / "syntax.py"
    source.write_text(dedent("""\
        async def run(value):
            try:
                async with manager() as resource:
                    assert check(await resource.fetch())
                    value = {key(): wrap(item())}
                    yield f"{format_value(value)}"
            except failure_type():
                raise error(build()) from cause()
            finally:
                cleanup()
            match value:
                case [first] if guard():
                    action()
            return (callback())(argument())
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    calls = [use for use in module.source_uses if use.kind == "call"]
    assert Counter(use.target_spelling for use in calls) == Counter({
        "manager": 1, "check": 1, "resource.fetch": 1, "key": 1, "wrap": 1,
        "item": 1, "format_value": 1, "failure_type": 1, "error": 1, "build": 1,
        "cause": 1, "cleanup": 1, "guard": 1, "action": 1, "(callback())": 1,
        "callback": 1, "argument": 1,
    })
    assert {use.owner_id for use in calls} == {module.symbols[0].id}


def test_pattern_attributes_and_with_targets_preserve_access_occurrences(tmp_path: Path) -> None:
    """Pattern grammar lookups and with bindings have the same access semantics as expressions."""
    source = tmp_path / "patterns.py"
    source.write_text(dedent("""\
        import palette
        def run(value, obj):
            with manager() as obj.resource:
                pass
            match value:
                case palette.Colors.RED:
                    pass
                case palette.Widget():
                    pass
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    assert Counter((use.target_spelling, use.kind) for use in module.source_uses) == Counter({
        ("manager", "call"): 1, ("obj.resource", "attribute-write"): 1,
        ("palette.Colors", "attribute-read"): 1, ("palette.Colors.RED", "attribute-read"): 1,
        ("palette.Widget", "attribute-read"): 1,
    })
    assert all(use.resolution.status == "external" for use in module.source_uses if use.target_spelling.startswith("palette."))


def test_direct_import_resolution_does_not_change_rule_name_projection(tmp_path: Path) -> None:
    """Canonical imported targets can be richer than historical rule target selection."""
    package = tmp_path / "pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("")
    helper = package / "helpers.py"
    helper.write_text("def work(value):\n    if value: return value\n    return None\n")
    caller = tmp_path / "caller.py"
    caller.write_text("import pkg.helpers\ndef wrapper(value): return pkg.helpers.work(value)\n")
    analysis = analyze_files((init, helper, caller), disable_sg=True)
    module = analysis.project.modules_by_file[caller.resolve()]
    assert module.source_uses is not None
    call = next(use for use in module.source_uses if use.kind == "call")
    assert call.resolution.status == "project"
    assert call.resolution.qualified_name == "pkg.helpers.work"
    assert not any(finding.subject_name == "wrapper" for finding in analysis.flags.findings.structural_findings)


def test_binding_constructs_do_not_leak_project_targets_into_locals(tmp_path: Path) -> None:
    """Deletion, pattern captures and unsupported scope directives cannot prove direct calls."""
    source = tmp_path / "bindings.py"
    source.write_text(dedent("""\
        def target(): pass
        def deleted():
            del target
            target()
        def captured(value):
            match value:
                case target:
                    target()
        def redirected():
            global target
            target()
        def variadic(*target: tuple):
            target()
        def generic[target]():
            target()
        """))
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    calls = {use.owner_id: use for use in module.source_uses}
    _, deleted, captured, redirected, variadic, generic = module.symbols
    assert calls[deleted.id].resolution.status == "unresolved"
    assert calls[captured.id].resolution.status == "unresolved"
    assert calls[redirected.id].resolution.status == "unsupported"
    assert calls[variadic.id].resolution.status == "unresolved"
    assert calls[generic.id].resolution.status == "unsupported"


@pytest.mark.parametrize("binding", [
    "thunk = lambda x=(target := replacement()): x",
    "values = [(target := item) for item in items]",
    "type target = int",
])
def test_bindings_in_unsupported_syntax_still_shadow_outer_declarations(tmp_path: Path, binding: str) -> None:
    """Unsupported execution semantics do not erase lexical binding evidence."""
    source = tmp_path / "hidden.py"
    source.write_text(f"def target(): pass\ndef run():\n    {binding}\n    target()\n")
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    use = next(use for use in module.source_uses if use.target_spelling == "target")
    assert use.resolution.status in {"unresolved", "unsupported"}


def test_parenthesized_direct_names_resolve_without_inferring_nested_attributes(tmp_path: Path) -> None:
    """Grouping is transparent, but lexical qualified names are not attribute paths."""
    helper = tmp_path / "helpers.py"
    helper.write_text("def outer():\n    def inner(): pass\n    return inner\n")
    source = tmp_path / "caller.py"
    source.write_text("import math\nimport helpers\n(math.sqrt)(4)\n(helpers).outer()\nhelpers.outer.inner()\n")
    module = analyze_files((source, helper), disable_sg=True).project.modules_by_file[source.resolve()]
    assert module.source_uses is not None
    calls = {use.target_spelling: use for use in module.source_uses if use.kind == "call"}
    assert calls["(math.sqrt)"].resolution.status == "external"
    assert calls["(math.sqrt)"].resolution.qualified_name == "math.sqrt"
    assert calls["(helpers).outer"].resolution.status == "project"
    assert calls["helpers.outer.inner"].resolution.status == "unresolved"


def test_annotation_only_attribute_targets_are_not_writes(tmp_path: Path) -> None:
    """An annotation evaluates its receiver, not the final attribute access."""
    source = tmp_path / "annotation.py"
    source.write_text("def run(obj):\n    obj.child.value: int\n    factory().field: int\n")
    module = analyze_files((source,), disable_sg=True).project.modules[0]
    assert module.source_uses is not None
    assert {(use.target_spelling, use.kind) for use in module.source_uses} == {
        ("obj.child", "attribute-read"), ("factory", "call"),
    }


def test_rebuilding_project_resolution_reconsiders_current_snapshot_membership(tmp_path: Path) -> None:
    """Retained modules cannot keep dangling targets or hide new name collisions."""
    helper = tmp_path / "helper.py"
    helper.write_text("def work(): pass\n")
    source = tmp_path / "caller.py"
    source.write_text("from helper import work\nwork()\n")
    project = analyze_files((source, helper), disable_sg=True).project
    caller_module = project.modules_by_file[source.resolve()]
    removed_uses = build_project((caller_module,)).modules[0].source_uses
    assert removed_uses is not None
    removed = removed_uses[0]
    assert removed.resolution.status == "external"
    assert removed.resolution.target_id is None
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = other_dir / "helper.py"
    other.write_text("def work(): pass\n")
    other_module = analyze_files((other,), disable_sg=True).project.modules[0]
    colliding_uses = build_project((*project.modules, other_module)).modules_by_file[source.resolve()].source_uses
    assert colliding_uses is not None
    colliding = colliding_uses[0]
    assert colliding.resolution.status == "ambiguous"
    assert len(colliding.resolution.candidate_ids) == 2


def test_relative_import_projection_keeps_existing_multiple_name_rule_selection(tmp_path: Path) -> None:
    """Canonical relative imports must not silently correct historical rule lookup."""
    package = tmp_path / "pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("")
    helper = package / "helpers.py"
    helper.write_text("first=None\ndef second(x): return x\n")
    caller = package / "caller.py"
    caller.write_text("from .helpers import first, second\ndef caller(x): return second(x)\n")
    decoy = tmp_path / "first.py"
    decoy.write_text("def second(x): return x\n")
    analysis = analyze_files((init, helper, caller, decoy), disable_sg=True,
                             low_use_short_function=LowUseShortFunctionSettings(enabled=True))
    findings = {(finding.rule_id, finding.subject_qualified_name) for finding in analysis.flags.findings.structural_findings}
    assert findings == {
        ("trivial-wrapper", "first.second"), ("trivial-wrapper", "pkg.helpers.second"),
        ("trivial-wrapper", "pkg.caller.caller"), ("low-use-short-function", "first.second"),
    }
    uses = analysis.project.modules_by_file[caller.resolve()].source_uses
    assert uses is not None
    call = next(use for use in uses if use.kind == "call")
    assert call.resolution.qualified_name == "pkg.helpers.second"


def test_empty_unavailable_and_read_only_inventory_contract(tmp_path: Path) -> None:
    """A supported empty family differs from unavailable extraction and views are frozen."""
    python = tmp_path / "empty.py"
    python.write_text("")
    rust = tmp_path / "empty.rs"
    rust.write_text("")
    python_module, rust_module = (
        analyze_files((file,), disable_sg=True).project.modules[0] for file in (python, rust)
    )
    assert python_module.source_uses == ()
    assert rust_module.source_uses is None
    assert analyze_files((), disable_sg=True).project.source_uses_by_id == {}

    python.write_text("print('é'); print('é')\n")
    project = analyze_files((python,), disable_sg=True).project
    uses = project.modules[0].source_uses
    assert uses is not None
    first, second = uses
    assert first.id != second.id
    assert (first.span.start_col, first.span.end_col) == (0, 11)
    assert (second.span.start_col, second.span.end_col) == (13, 24)
    assert {use.resolution.status for use in (first, second)} == {"external"}
    assert project.source_uses_by_id[first.id] is first
    with pytest.raises(TypeError):
        project.source_uses_by_id[first.id] = second  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        first.resolution.status = "unresolved"


def test_richer_inventory_preserves_rule_specific_recursion_and_effect_policies(tmp_path: Path) -> None:
    """Retaining calls does not broaden rule eligibility or count self-recursion as a caller."""
    source = tmp_path / "rules.py"
    source.write_text(dedent("""\
        def recurse(value): return recurse(value)
        def caller(value): return recurse(value)
        def dotted(value): return unknown.member(value)
        def nested(value):
            if value:
                unknown.member(value)
            return value
        """))
    analysis = analyze_files(
        (source,), disable_sg=True,
        low_use_short_function=LowUseShortFunctionSettings(enabled=True),
    )
    project = analysis.project
    module = project.modules[0]
    recurse, caller, dotted, nested = module.symbols
    assert module.source_uses is not None
    assert len([use for use in module.source_uses if use.target_spelling == "recurse"]) == 2
    findings = {(finding.rule_id, finding.subject_name) for finding in analysis.flags.findings.structural_findings}
    assert ("trivial-wrapper", "recurse") not in findings
    assert ("low-use-short-function", "recurse") in findings
    assert ("trivial-wrapper", "dotted") not in findings
    nested_effects = project.effects_by_symbol[nested.id]
    dotted_effects = project.effects_by_symbol[dotted.id]
    caller_effects = project.effects_by_symbol[caller.id]
    assert nested_effects is not None
    assert dotted_effects is not None
    assert caller_effects is not None
    assert {effect.kind for effect in nested_effects} == {"read"}
    effect = next(effect for effect in dotted_effects if effect.kind == "external-call")
    assert effect.kind == "external-call"  # Deliberate rule keep-policy, not resolution evidence.
    assert effect.source_use_id is not None
    assert project.source_uses_by_id[effect.source_use_id].resolution.status == "unresolved"
    caller_effect = next(effect for effect in caller_effects if effect.kind == "project-call")
    assert caller_effect.source_use_id is not None
    assert project.source_uses_by_id[caller_effect.source_use_id].resolution.target_id == recurse.id
