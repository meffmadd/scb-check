"""Python declaration extraction over already-parsed syntax and lexical evidence."""

from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from scb_check.tree_walking.languages._node_helpers import node_span
from scb_check.tree_walking.languages._node_helpers import text
from scb_check.tree_walking.languages.python_strings import docstring_literals
from scb_check.tree_walking.languages.python_types import type_reference
from scb_check.tree_walking.models import AttributeIR
from scb_check.tree_walking.models import CallableIR
from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import TypeReferenceIR

type NameResolver = Callable[[str, str], TargetResolutionIR]
type DecoratorResolver = Callable[[Node, str], TargetResolutionIR]

FLOW_BREAK_TYPES = frozenset({
    "if_statement", "elif_clause", "else_clause", "for_statement", "while_statement",
    "except_clause", "conditional_expression",
})


def declaration_index(symbols: tuple[SymbolIR, ...]) -> dict[tuple[int, int], SymbolIR]:
    """Index IR declarations by parser-native start points within this extraction."""
    return {(symbol.span.start_line - 1, symbol.span.start_col): symbol for symbol in symbols}


def callable_facts(
    file: Path, node: Node, symbol: SymbolIR, resolve: DecoratorResolver,
) -> CallableIR:
    """Retain syntax-level body/descriptor facts, without merging declarations."""
    decorators = ()
    parent = node.parent
    if parent is not None and parent.type == "decorated_definition":
        decorators = tuple(child for child in parent.named_children if child.type == "decorator")
    spellings = tuple(text(decorator).removeprefix("@").strip() for decorator in decorators)
    names = {resolve(decorator.named_children[0], symbol.owner_id or "").qualified_name for decorator in decorators}
    binding = "function"
    if symbol.kind is SymbolKind.METHOD:
        binding = "instance"
        if "builtins.staticmethod" in names:
            binding = "static"
        elif "builtins.classmethod" in names:
            binding = "class"
    body = node.child_by_field_name("body")
    assert body is not None  # noqa: S101 - Valid grammar.
    statements = [child for child in body.named_children if child.type != "comment"]
    if docstring_literals(node):
        statements.pop(0)
    kind = "implemented"
    if not statements:
        kind = "empty"
    elif all(statement.type == "pass_statement" for statement in statements):
        kind = "pass"
    elif all(text(statement) == "..." for statement in statements):
        kind = "ellipsis"
    return CallableIR(
        declaring_class_id=symbol.owner_id if binding != "function" else None,
        binding=binding, decorators=spellings,
        is_abstract="abc.abstractmethod" in names,
        body_kind=kind, body_span=node_span(file, body),
        implementation_id=symbol.id if kind == "implemented" else None,
    )


def direct_bases(file: Path, node: Node, symbol: SymbolIR, resolve: NameResolver) -> tuple[TypeReferenceIR, ...]:
    """Retain positional base expressions, excluding metaclass and other keywords."""
    arguments = node.child_by_field_name("superclasses")
    if arguments is None:
        return ()
    return tuple(type_reference(
        text(base), node_span(file, base),
        lambda name: resolve(name, symbol.owner_id or ""), allow_forward=False,
    ) for base in arguments.named_children if base.type not in {"keyword_argument", "dictionary_splat", "comment"})


def attribute_facts(
    file: Path, root: Node, symbols: tuple[SymbolIR, ...],
    uses: tuple[SourceUseIR, ...], resolve: NameResolver,
) -> tuple[tuple[AttributeIR, ...], tuple[SourceUseIR, ...]]:
    """Canonicalize supported assignment targets, retaining write occurrences once."""
    return _AttributeExtractor(file, resolve, declaration_index(symbols)).extract(root, uses)


@dataclass(frozen=True, slots=True)
class _AttributeExtractor:
    file: Path
    resolve: NameResolver
    declarations: dict[tuple[int, int], SymbolIR]

    def extract(self, root: Node, uses: tuple[SourceUseIR, ...]) -> tuple[tuple[AttributeIR, ...], tuple[SourceUseIR, ...]]:
        """Return canonical fields and linked occurrences using this parser context."""
        fields: dict[tuple[str, str], AttributeIR] = {}
        targets: list[tuple[SourceSpan, tuple[str, str]]] = []
        class_writes: list[SourceUseIR] = []
        for node, owner, nesting in self._assignments(root):
            left = node.child_by_field_name("left")
            assert left is not None  # noqa: S101 - Valid grammar.
            for target in self._assignment_targets(left):
                field = self._attribute_target(target, owner)
                if field is None:
                    continue
                field = self._with_annotation(field, node, owner)
                key = (field.declaring_class_id, field.name)
                previous = fields.get(key)
                if node.type != "augmented_assignment":
                    fields[key] = field if previous is None else previous.model_copy(update={
                        "storage": previous.storage | field.storage,
                        "declared_types": (*previous.declared_types, *field.declared_types),
                    })
                targets.append((field.span, key))
                if target.type == "identifier" and node.child_by_field_name("right") is not None:
                    class_writes.append(SourceUseIR(
                        kind="attribute-read-write" if node.type == "augmented_assignment" else "attribute-write",
                        span=field.span, target_span=field.span,
                        target_spelling=field.name, target_form="name",
                        owner_id=owner.id, execution_kind="class", nesting=nesting,
                    ))
        ids = {span: fields[key].id for span, key in targets if key in fields}
        linked = tuple(
            use.model_copy(update={"declared_attribute_id": ids[use.target_span]})
            if use.kind != "call" and use.target_span in ids else use
            for use in (*uses, *class_writes)
        )
        return tuple(fields.values()), tuple(sorted(linked, key=lambda use: (
            use.span.start_line, use.span.start_col, use.kind != "call",
        )))

    def _assignments(self, root: Node) -> Iterator[tuple[Node, SymbolIR, int]]:
        pending: list[tuple[Node, SymbolIR | None, int]] = [(root, None, 0)]
        while pending:
            node, owner, nesting = pending.pop()
            if node.type in {"class_definition", "function_definition"}:
                owner = self.declarations[node.start_point]
                body = node.child_by_field_name("body")
                if body is not None:
                    pending.append((body, owner, nesting))
                continue
            if node.type in {"lambda", "list_comprehension", "set_comprehension", "dictionary_comprehension", "generator_expression", "type_alias_statement"}:
                continue
            if owner is not None and node.type in {"assignment", "augmented_assignment"}:
                yield node, owner, nesting
            child_nesting = nesting + (node.type in FLOW_BREAK_TYPES)
            pending.extend((child, owner, child_nesting) for child in reversed(node.named_children))

    def _with_annotation(self, field: AttributeIR, node: Node, owner: SymbolIR) -> AttributeIR:
        annotation = node.child_by_field_name("type")
        if annotation is None:
            return field
        return field.model_copy(update={"declared_types": (
            type_reference(text(annotation), node_span(self.file, annotation), lambda name: self.resolve(name, owner.id)),
        )})

    def _assignment_targets(self, node: Node) -> tuple[Node, ...]:
        if node.type in {"identifier", "attribute"}:
            return (node,)
        if node.type in {"pattern_list", "tuple_pattern", "list_pattern", "tuple", "list", "parenthesized_expression", "list_splat_pattern"}:
            return tuple(target for child in node.named_children for target in self._assignment_targets(child))
        return ()

    def _attribute_target(self, node: Node, owner: SymbolIR) -> AttributeIR | None:
        if self.resolve(text(node), owner.id).reason in {"scope-directive", "type-parameter"}:
            return None
        if owner.kind is SymbolKind.CLASS and node.type == "identifier":
            return AttributeIR(name=text(node), declaring_class_id=owner.id, owner_id=owner.id,
                               span=node_span(self.file, node), storage=frozenset({"class"}))
        facts = owner.callable_facts
        if facts is None or facts.binding not in {"instance", "class"} or node.type != "attribute":
            return None
        receiver = node.child_by_field_name("object")
        member = node.child_by_field_name("attribute")
        if receiver is None or member is None or not owner.signature.parameters:
            return None
        if receiver.type != "identifier" or text(receiver) != owner.signature.parameters[0] or self.resolve(text(receiver), owner.id).reason != "parameter":
            return None
        assert facts.declaring_class_id is not None  # noqa: S101 - Methods have a declaring class.
        return AttributeIR(name=text(member), declaring_class_id=facts.declaring_class_id, owner_id=owner.id,
                           span=node_span(self.file, node), storage=frozenset({"class" if facts.binding == "class" else "instance"}))
