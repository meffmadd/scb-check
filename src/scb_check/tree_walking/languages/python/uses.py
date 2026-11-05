"""Extract Python calls, attribute accesses, imports, and declarations into IR records."""

import builtins
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from scb_check.tree_walking.languages._node_helpers import node_span
from scb_check.tree_walking.languages._node_helpers import text
from scb_check.tree_walking.languages.python.declarations import (
    FLOW_BREAK_TYPES,
)
from scb_check.tree_walking.languages.python.declarations import attribute_facts
from scb_check.tree_walking.languages.python.declarations import callable_facts
from scb_check.tree_walking.languages.python.declarations import (
    declaration_index,
)
from scb_check.tree_walking.languages.python.declarations import direct_bases
from scb_check.tree_walking.languages.python.types import type_reference
from scb_check.tree_walking.models import AttributeIR
from scb_check.tree_walking.models import ExecutionKind
from scb_check.tree_walking.models import ImportIR
from scb_check.tree_walking.models import ReceiverIR
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SourceUseKind
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import UnsupportedContext

_UNSUPPORTED_CONTEXTS: dict[str, UnsupportedContext] = {
    context: context for context in (
        "list_comprehension", "set_comprehension", "dictionary_comprehension",
        "generator_expression", "type_alias_statement", "type_parameter",
    )
}


@dataclass(frozen=True, slots=True)
class _Scope:
    owner_id: str
    kind: ExecutionKind
    parent_id: str | None
    bindings: dict[str, list[TargetResolutionIR]]
    annotations: dict[str, list[Node]]

    def bind_locals(self, node: Node) -> None:
        """Record local names without treating a parameter annotation as a reassignment."""
        annotation_only = node.type == "assignment" and node.child_by_field_name("type") is not None and node.child_by_field_name("right") is None
        annotation = node.child_by_field_name("type") if node.type == "assignment" else None
        left = node.child_by_field_name("left")
        if annotation is not None and left is not None and left.type == "identifier":
            self.annotations.setdefault(text(left), []).append(annotation)
        for name in _bound_names(node):
            if annotation_only and any(binding.reason == "parameter" for binding in self.bindings.get(name, ())):
                continue
            self.bindings.setdefault(name, []).append(TargetResolutionIR(reason="local-binding"))


@dataclass(frozen=True, slots=True)
class PythonFacts:
    """Calls, accesses, imports, symbols, and fields extracted from one Python file."""

    source_uses: tuple[SourceUseIR, ...]
    imports: tuple[ImportIR, ...]
    symbols: tuple[SymbolIR, ...]
    attributes: tuple[AttributeIR, ...]


def import_bindings(file: Path, node: Node, owner_id: str | None = None) -> tuple[ImportIR, ...]:
    """Collect imported names and their local aliases from one import statement."""
    module = node.child_by_field_name("module_name")
    prefix = text(module) if module is not None else ""
    imports: list[ImportIR] = []
    for child in node.named_children:
        if child == module:
            continue
        alias = child.child_by_field_name("alias")
        name = child.child_by_field_name("name") if alias is not None else child
        if name is None or child.type not in {"dotted_name", "aliased_import", "wildcard_import"}:
            continue
        imported = text(name)
        local = text(alias) if alias is not None else imported
        separator = "" if prefix.endswith(".") else "."
        qualified = f"{prefix}{separator}{imported}" if prefix else imported
        if node.type == "import_statement" and alias is None:
            local = qualified = imported.split(".", 1)[0]
        imports.append(ImportIR(
            local_name=local, qualified_name=qualified, span=node_span(file, child), owner_id=owner_id,
        ))
    return tuple(imports)


def python_facts(  # noqa: PLR0913 - Parser-local declaration nodes accompany lexical context.
    file: Path, root: Node, module_id: str, symbols: tuple[SymbolIR, ...], module_name: str,
    *, declaration_nodes: Mapping[str, Node],
) -> PythonFacts:
    """Collect names by scope, then extract calls, accesses, and declaration details."""
    declarations = declaration_index(symbols)
    scopes, imports = _collect_scopes(file, root, module_id, declarations, module_name)
    def resolve(name: str, scope_id: str) -> TargetResolutionIR:
        return _resolve_parts(name.split("."), scope_id or module_id, scopes)

    def resolve_decorator(node: Node, scope_id: str) -> TargetResolutionIR:
        return _resolve_target(node, scope_id or module_id, scopes)

    symbols = tuple(
        symbol.model_copy(update={"callable_facts": callable_facts(
            file, declaration_nodes[symbol.id], symbol,
            resolve_decorator,
        )}) if symbol.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD} else symbol.model_copy(update={
            "direct_bases": direct_bases(file, declaration_nodes[symbol.id], symbol, resolve),
        })
        for symbol in symbols
    )
    attributes, uses = attribute_facts(
        file, root, symbols, _collect_uses(file, root, module_id, declaration_index(symbols), scopes),
        resolve,
    )
    return PythonFacts(source_uses=uses, imports=imports, symbols=symbols, attributes=attributes)


def _collect_scopes(
    file: Path, root: Node, module_id: str,
    declarations: dict[tuple[int, int], SymbolIR], module_name: str,
) -> tuple[dict[str, _Scope], tuple[ImportIR, ...]]:
    scopes = {module_id: _Scope(module_id, "module", None, {}, {})}
    imports: list[ImportIR] = []
    stack = [(root, module_id)]
    while stack:
        node, scope_id = stack.pop()
        scope = scopes[scope_id]
        if node.type in {"function_definition", "class_definition"}:
            symbol = declarations[node.start_point]
            scope.bindings.setdefault(symbol.name, []).append(TargetResolutionIR(
                status="project", target_id=symbol.id,
                qualified_name=symbol.qualified_name, reason="lexical-declaration",
            ))
            scopes[symbol.id] = _declaration_scope(symbol, scope, node)
            body = node.child_by_field_name("body")
            stack.extend((child, symbol.id if child == body else scope_id) for child in reversed(node.named_children))
            continue
        if node.type in {"import_statement", "import_from_statement"}:
            imports.extend(_bind_imports_inplace(file, node, scope, module_name))
            continue
        if node.type == "lambda":
            body = node.child_by_field_name("body")
            stack.extend((child, scope_id) for child in node.named_children if child != body)
            continue
        if node.type in _UNSUPPORTED_CONTEXTS:
            for name in _enclosing_bindings(node):
                scope.bindings.setdefault(name, []).append(TargetResolutionIR(reason="local-binding"))
            continue
        scope.bind_locals(node)
        if node.type in {"global_statement", "nonlocal_statement"}:
            for child in node.named_children:
                scope.bindings.setdefault(text(child), []).append(TargetResolutionIR(
                    status="unsupported", reason="scope-directive",
                ))
        stack.extend((child, scope_id) for child in reversed(node.named_children))

    return scopes, tuple(imports)


def _bind_imports_inplace(file: Path, node: Node, scope: _Scope, module_name: str) -> tuple[ImportIR, ...]:
    bindings = tuple(_absolute_import(binding, file, module_name)
                     for binding in import_bindings(file, node, scope.owner_id))
    for binding in bindings:
        resolution = TargetResolutionIR(
            status="external", qualified_name=binding.qualified_name, reason="import-binding",
        )
        if binding.qualified_name.startswith(".") or binding.local_name == "*":
            resolution = TargetResolutionIR(status="unsupported", reason="relative-or-star-import")
        scope.bindings.setdefault(binding.local_name, []).append(resolution)
    return bindings


def _declaration_scope(symbol: SymbolIR, parent: _Scope, node: Node) -> _Scope:
    parameters = set(symbol.signature.parameters)
    parameter_node = node.child_by_field_name("parameters")
    if parameter_node is not None:
        # Rule signatures are shallow summaries; typed variadics still bind names.
        for parameter in parameter_node.named_children:
            first = parameter.named_children[0] if parameter.named_children else parameter
            if first.type in {"list_splat_pattern", "dictionary_splat_pattern"}:
                parameters.update(text(child) for child in first.named_children if child.type == "identifier")
    inherited = {
        name: [binding for binding in candidates if binding.reason == "type-parameter"]
        for name, candidates in parent.bindings.items() if parent.kind == "class"
    }
    bindings = {name: candidates for name, candidates in inherited.items() if candidates}
    bindings.update({name: [TargetResolutionIR(reason="parameter")] for name in parameters})
    type_parameters = node.child_by_field_name("type_parameters")
    if type_parameters is not None:
        for parameter in type_parameters.named_children:
            current = parameter
            while current.named_children:
                current = current.named_children[0]
            if current.type == "identifier":
                bindings[text(current)] = [TargetResolutionIR(status="unsupported", reason="type-parameter")]
    # Class namespaces are not closure scopes for methods or nested classes.
    return _Scope(
        symbol.id, "class" if symbol.kind is SymbolKind.CLASS else "function",
        parent.parent_id if parent.kind == "class" else parent.owner_id,
        bindings, _parameter_annotations(parameter_node),
    )


def _parameter_annotations(parameters: Node | None) -> dict[str, list[Node]]:
    annotations: dict[str, list[Node]] = {}
    if parameters is not None:
        for parameter in parameters.named_children:
            annotation = parameter.child_by_field_name("type")
            name = parameter.child_by_field_name("name")
            if name is None and parameter.named_children:
                name = parameter.named_children[0]
            if annotation is not None and name is not None and name.type == "identifier":
                annotations[text(name)] = [annotation]
    return annotations


def _absolute_import(binding: ImportIR, file: Path, module_name: str) -> ImportIR:
    qualified = binding.qualified_name
    if not qualified.startswith("."):
        return binding
    level = len(qualified) - len(qualified.lstrip("."))
    package = module_name.split(".") if file.name == "__init__.py" else module_name.split(".")[:-1]
    package = package[:len(package) - level + 1] if level <= len(package) else []
    qualified = ".".join((*package, qualified.lstrip("."))) if package else qualified
    return binding.model_copy(update={"qualified_name": qualified})


def _collect_uses(
    file: Path, root: Node, module_id: str,
    declarations: dict[tuple[int, int], SymbolIR], scopes: dict[str, _Scope],
) -> tuple[SourceUseIR, ...]:
    uses: list[SourceUseIR] = []
    symbols = {symbol.id: symbol for symbol in declarations.values()}
    pending: list[tuple[Node, str, UnsupportedContext | None, int]] = [(root, module_id, None, 0)]
    while pending:
        node, scope_id, unsupported, nesting = pending.pop()
        scope = scopes[scope_id]
        if node.type in {"function_definition", "class_definition"}:
            symbol = declarations[node.start_point]
            body = node.child_by_field_name("body")
            pending.extend((
                child, symbol.id if child == body else scope_id,
                ("type_parameter" if child != body and node.child_by_field_name("type_parameters") is not None else unsupported),
                nesting,
            ) for child in reversed(node.named_children))
            continue
        if node.type in {"import_statement", "import_from_statement"}:
            continue
        if node.type == "lambda":
            body = node.child_by_field_name("body")
            pending.extend((child, scope_id, "lambda" if child == body else unsupported, nesting)
                           for child in reversed(node.named_children))
            continue
        unsupported = _UNSUPPORTED_CONTEXTS.get(node.type, unsupported)
        # Annotation evaluation depends on Python version and future imports.
        if node.type == "type":
            unsupported = "annotation"
        pattern_lookup = node.type == "dotted_name" and len(node.named_children) > 1
        if (node.type in {"call", "attribute"} or pattern_lookup) and not _annotation_target(node):
            target = node.child_by_field_name("function") if node.type == "call" else node
            assert target is not None  # noqa: S101 - Valid Python grammar.
            resolution = _resolve_target(target, scope_id, scopes)
            if unsupported is not None:
                resolution = TargetResolutionIR(status="unsupported", reason=unsupported)
            use = SourceUseIR(
                kind="call" if node.type == "call" else _access_kind(node),
                span=node_span(file, node), target_span=node_span(file, target),
                target_spelling=text(target),
                target_form=("name" if target.type == "identifier" else
                             "attribute" if target.type in {"attribute", "dotted_name"} else "expression"),
                owner_id=scope_id if unsupported is None else None,
                execution_kind=scope.kind if unsupported is None else "unsupported",
                unsupported_context=unsupported, resolution=resolution, nesting=nesting,
                receiver=None if unsupported is not None else _receiver(file, target, scope_id, scopes, symbols),
            )
            uses.extend(_pattern_prefixes(use, node) if pattern_lookup else (use,))
        child_nesting = nesting + (node.type in FLOW_BREAK_TYPES)
        pending.extend((child, scope_id, unsupported, child_nesting) for child in reversed(node.named_children))
    return tuple(uses)


def _enclosing_bindings(node: Node) -> tuple[str, ...]:
    names: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "lambda":
            body = current.child_by_field_name("body")
            stack.extend(child for child in current.named_children if child != body)
            continue
        if current.type in {"named_expression", "type_alias_statement"}:
            target = current.child_by_field_name("name") or current.child_by_field_name("left")
            while target is not None and target.type != "identifier" and target.named_children:
                target = target.named_children[0]
            if target is not None and target.type == "identifier":
                names.append(text(target))
        stack.extend(current.named_children)
    return tuple(names)


def _annotation_target(node: Node) -> bool:
    parent = node.parent
    return (
        parent is not None and parent.type == "assignment"
        and parent.child_by_field_name("left") == node
        and parent.child_by_field_name("type") is not None
        and parent.child_by_field_name("right") is None
    )


def _pattern_prefixes(use: SourceUseIR, node: Node) -> tuple[SourceUseIR, ...]:
    uses = [use]
    members = node.named_children
    for index, member in enumerate(members[1:-1], start=2):
        end = node_span(use.span.file, member)
        span = use.span.model_copy(update={"end_line": end.end_line, "end_col": end.end_col})
        spelling = text(node).encode("utf-8")[:member.end_byte - node.start_byte].decode("utf-8")
        resolution = use.resolution
        if resolution.qualified_name is not None:
            qualified = resolution.qualified_name.rsplit(".", len(members) - index)[0]
            resolution = resolution.model_copy(update={"qualified_name": qualified})
        uses.append(use.model_copy(update={
            "span": span, "target_span": span, "target_spelling": spelling,
            "resolution": resolution,
        }))
    return tuple(uses)


def _binding_target(node: Node) -> Node | None:
    target = None
    if node.type in {"assignment", "augmented_assignment", "named_expression", "for_statement", "for_in_clause"}:
        target = node.child_by_field_name("left") or node.child_by_field_name("name")
    elif node.type == "delete_statement":
        target = node
    elif node.type == "as_pattern":
        target = node.child_by_field_name("alias") or node.named_children[-1]
    elif node.type == "splat_pattern" and text(node).lstrip("*") != "_":
        target = node
    elif node.type == "dotted_name" and len(node.named_children) == 1 and text(node) != "_":
        parent = node.parent
        if parent is not None and parent.type in {"case_pattern", "keyword_pattern"}:
            target = node
    return target


def _bound_names(node: Node) -> tuple[str, ...]:
    target = _binding_target(node)
    if target is None:
        return ()
    names: list[str] = []
    stack = [target]
    while stack:
        current = stack.pop()
        if current.type == "identifier":
            names.append(text(current))
        elif current.type not in {"attribute", "subscript"}:
            stack.extend(current.named_children)
    return tuple(names)


def _receiver(
    file: Path, node: Node, scope_id: str, scopes: dict[str, _Scope],
    symbols: dict[str, SymbolIR],
) -> ReceiverIR | None:
    if _unparenthesized(node).type == "dotted_name":
        return None
    current, members = _target_parts(node)
    if not members or current.type != "identifier":
        return None
    name = text(current)
    resolution = _lookup_name(name, scopes[scope_id], scopes)
    receiver = ReceiverIR(resolution=resolution, member_path=tuple(members))
    scope = scopes[scope_id]
    while name not in scope.bindings and scope.parent_id is not None:
        scope = scopes[scope.parent_id]
    bindings = scope.bindings.get(name, ())
    if len(bindings) != 1 or resolution.reason not in {"parameter", "local-binding"}:
        return receiver
    symbol = symbols.get(scope.owner_id)
    facts = symbol.callable_facts if symbol is not None else None
    if (symbol is not None and facts is not None and facts.binding in {"instance", "class"}
        and symbol.signature.parameters and name == symbol.signature.parameters[0]):
        owner = symbols[facts.declaring_class_id] if facts.declaring_class_id is not None else None
        if owner is not None:
            declared = type_reference(owner.name, node_span(file, current), lambda _: TargetResolutionIR(
                status="project", target_id=owner.id, qualified_name=owner.qualified_name, reason="lexical-declaration",
            ))
            return receiver.model_copy(update={"declared_type": declared, "is_class_receiver": facts.binding == "class"})
    annotations = scope.annotations.get(name, [])
    if len(annotations) == 1:
        annotation = annotations[0]
        annotation_scope = (symbol.owner_id or scope.parent_id) if resolution.reason == "parameter" and symbol is not None else scope.owner_id
        declared = type_reference(text(annotation), node_span(file, annotation),
                                  lambda target: _resolve_parts(target.split("."), annotation_scope or scope.owner_id, scopes))
        return receiver.model_copy(update={"declared_type": declared})
    return receiver


def _target_parts(node: Node) -> tuple[Node, list[str]]:
    parts: list[str] = []
    current = _unparenthesized(node)
    if current.type == "dotted_name":
        parts = [text(child) for child in current.named_children[1:]]
        current = current.named_children[0]
    while current.type == "attribute":
        member = current.child_by_field_name("attribute")
        receiver = current.child_by_field_name("object")
        assert member is not None  # noqa: S101 - Valid grammar.
        assert receiver is not None  # noqa: S101 - Valid grammar.
        parts.insert(0, text(member))
        current = _unparenthesized(receiver)
    return current, parts


def _resolve_target(node: Node, scope_id: str, scopes: dict[str, _Scope]) -> TargetResolutionIR:
    current, parts = _target_parts(node)
    if current.type != "identifier":
        return TargetResolutionIR(reason="dynamic-target")
    return _resolve_parts([text(current), *parts], scope_id, scopes)


def _resolve_parts(parts: list[str], scope_id: str, scopes: dict[str, _Scope]) -> TargetResolutionIR:
    root, *parts = parts
    if not all(part.isidentifier() for part in (root, *parts)):
        return TargetResolutionIR(reason="dynamic-target")
    binding = _lookup_name(root, scopes[scope_id], scopes)
    if parts:
        if binding.status in {"ambiguous", "unresolved", "unsupported"}:
            return binding
        if binding.reason not in {"import-binding", "builtin"}:
            return _direct_class_path(binding, parts, scopes)
        return binding.model_copy(update={"qualified_name": ".".join((binding.qualified_name or root, *parts))})
    return binding


def _direct_class_path(binding: TargetResolutionIR, parts: list[str], scopes: dict[str, _Scope]) -> TargetResolutionIR:
    for member in parts:
        scope = scopes.get(binding.target_id) if binding.target_id is not None else None
        if scope is None or scope.kind != "class" or member not in scope.bindings:
            return TargetResolutionIR(reason="receiver-needs-member-resolution")
        binding = _binding_resolution(scope.bindings[member])
        if binding.status != "project":
            return binding
    return binding


def _unparenthesized(node: Node) -> Node:
    while node.type == "parenthesized_expression":
        node = next(child for child in node.named_children if child.type != "comment")
    return node


def _lookup_name(root: str, scope: _Scope | None, scopes: dict[str, _Scope]) -> TargetResolutionIR:
    bindings: list[TargetResolutionIR] = []
    while scope is not None:
        if root in scope.bindings:
            bindings = scope.bindings[root]
            break
        if "*" in scope.bindings:
            return TargetResolutionIR(status="unsupported", reason="star-import")
        scope = scopes[scope.parent_id] if scope.parent_id is not None else None
    if not bindings:
        if root in vars(builtins):
            return TargetResolutionIR(
                status="external", qualified_name=f"builtins.{root}", reason="builtin",
            )
        return TargetResolutionIR()
    return _binding_resolution(bindings)


def _binding_resolution(bindings: list[TargetResolutionIR]) -> TargetResolutionIR:
    unsupported = next((binding for binding in bindings if binding.status == "unsupported"), None)
    if unsupported is not None:
        return unsupported
    distinct = tuple(dict.fromkeys(bindings))
    if len(distinct) > 1:
        return TargetResolutionIR(
            status="ambiguous", candidate_ids=tuple(binding.target_id for binding in distinct if binding.target_id is not None),
            reason="multiple-lexical-bindings",
        )
    return distinct[0]


def _access_kind(node: Node) -> SourceUseKind:
    current = node
    parent = current.parent
    while parent is not None:
        if parent.type in {"attribute", "subscript"}:
            return "attribute-read"
        if parent.type in {"assignment", "augmented_assignment", "for_statement", "for_in_clause", "named_expression"}:
            target = parent.child_by_field_name("left") or parent.child_by_field_name("name")
            if target == current:
                return "attribute-read-write" if parent.type == "augmented_assignment" else "attribute-write"
            return "attribute-read"
        if parent.type == "delete_statement":
            return "attribute-delete"
        if parent.type == "as_pattern":
            return "attribute-write" if parent.child_by_field_name("alias") == current else "attribute-read"
        if parent.type not in {"pattern_list", "tuple_pattern", "list_pattern", "tuple", "list", "parenthesized_expression", "as_pattern_target", "expression_list"}:
            break
        current, parent = parent, parent.parent
    return "attribute-read"
