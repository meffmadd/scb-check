"""Python tree-sitter parser that emits language-agnostic IR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from token import COMMENT
from token import DEDENT
from token import ENDMARKER
from token import INDENT
from token import NEWLINE
from token import NL
from tokenize import TokenError
from tokenize import generate_tokens
from typing import TYPE_CHECKING

import tree_sitter_python
from tree_sitter import Language as TreeSitterLanguage
from tree_sitter import Parser

from scb_check.tree_walking.artifacts import LanguageParseError
from scb_check.tree_walking.artifacts import ParsedFile
from scb_check.tree_walking.languages._node_helpers import (
    count_sloc_in_span as _count_sloc_in_span,
)
from scb_check.tree_walking.languages._node_helpers import (
    iter_nodes as _iter_nodes,
)
from scb_check.tree_walking.languages._node_helpers import (
    module_span as _module_span,
)
from scb_check.tree_walking.languages._node_helpers import (
    node_span as _node_span,
)
from scb_check.tree_walking.languages._node_helpers import (
    qualified_name as _qualified_name,
)
from scb_check.tree_walking.languages._node_helpers import text as _text
from scb_check.tree_walking.languages.python_declarations import (
    FLOW_BREAK_TYPES as _COG_FLOW_BREAK_TYPES,
)
from scb_check.tree_walking.languages.python_strings import (
    docstring_literals as _docstring_literals,
)
from scb_check.tree_walking.languages.python_strings import python_string_prefix
from scb_check.tree_walking.languages.python_uses import import_bindings
from scb_check.tree_walking.languages.python_uses import python_facts
from scb_check.tree_walking.models import Language
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import OperationIR
from scb_check.tree_walking.models import OperationKind
from scb_check.tree_walking.models import ReferenceIR
from scb_check.tree_walking.models import SignatureIR
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import SymbolRole
from scb_check.tree_walking.models import TextFragmentIR
from scb_check.tree_walking.models import TextFragmentKind
from scb_check.tree_walking.models import ValueIR
from scb_check.tree_walking.models import ValueKind

if TYPE_CHECKING:
    from tree_sitter import Node
    from tree_sitter import Tree

_CYC_COMPLEXITY_NODE_TYPES = frozenset(
    {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "assert_statement",
        "list_comprehension",
        "set_comprehension",
        "dictionary_comprehension",
        "generator_expression",
        "boolean_operator",
        "conditional_expression",
        "if_clause",
    },
)
_COG_JUMP_TYPES = frozenset({"break_statement", "continue_statement"})
_SCOPE_NODE_TYPES = frozenset({"function_definition", "class_definition"})
_DECLARATION_CONTAINER_TYPES = frozenset({
    "block", "if_statement", "elif_clause", "else_clause", "try_statement",
    "except_clause", "finally_clause", "for_statement", "while_statement",
    "with_statement", "match_statement", "case_clause",
})
_STATEMENT_SUFFIX = "_statement"
_LITERAL_TYPES = frozenset(
    {
        "string",
        "integer",
        "float",
        "imaginary",
        "true",
        "false",
        "none",
    },
)
_COLLECTION_TYPES = frozenset(
    {
        "list",
        "tuple",
        "dictionary",
        "set",
        "list_comprehension",
        "set_comprehension",
        "dictionary_comprehension",
        "generator_expression",
    },
)
_OPERATOR_TYPES = frozenset(
    {
        "binary_operator",
        "boolean_operator",
        "comparison_operator",
        "not_operator",
        "unary_operator",
        "conditional_expression",
    },
)
_STATEMENT_OPERATION_KINDS = {
    "return_statement": OperationKind.RETURN,
    "if_statement": OperationKind.BRANCH,
    "match_statement": OperationKind.BRANCH,
    "try_statement": OperationKind.BRANCH,
    "for_statement": OperationKind.LOOP,
    "while_statement": OperationKind.LOOP,
    "raise_statement": OperationKind.RAISE,
}
_EXPRESSION_OPERATION_KINDS = {
    "assignment": OperationKind.ASSIGN,
    "call": OperationKind.CALL,
}
_BUILTIN_CALL_ROOTS = frozenset(
    {
        "bool",
        "dict",
        "float",
        "int",
        "len",
        "list",
        "print",
        "range",
        "set",
        "str",
        "super",
        "tuple",
    },
)
_IGNORED_SLOC_TOKEN_TYPES = {
    COMMENT,
    DEDENT,
    ENDMARKER,
    INDENT,
    NEWLINE,
    NL,
}
_RECEIVER_PARAMETER_NAMES = frozenset({"self", "cls"})

_PARSER: Parser | None = None


@dataclass(frozen=True, slots=True)
class ClassContext:
    """Enclosing class facts used while walking Python symbols."""

    qualified_name: str
    base_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VisitContext:
    """Current ownership and decorator context during tree walking."""

    owner_qualified_name: str | None = None
    owner_id: str | None = None
    class_context: ClassContext | None = None
    decorators: tuple[str, ...] = ()


class PythonParser:
    """Parse Python source into `ModuleIR`."""

    language = Language.PYTHON

    def parse(self, file_path: Path, source: str) -> ParsedFile:
        """Parse already-read Python `source`."""
        tree = _parse_tree(source)
        try:
            sloc_lines = _sloc_line_numbers(source, tree)
        except (IndentationError, TokenError) as exc:
            raise LanguageParseError(
                f"failed to tokenize Python source: {exc}",
                language=self.language,
                file_path=file_path,
            ) from exc
        walker = PythonWalker(file_path, source, tree, sloc_lines)
        return ParsedFile(
            file=file_path,
            source=source,
            module=walker.module(),
            native_tree=tree,
        )


class PythonWalker:
    """Walk a Python tree-sitter tree into generic module IR."""

    def __init__(
        self,
        file_path: Path,
        source: str,
        tree: Tree,
        sloc_lines: frozenset[int],
    ) -> None:
        """Initialize the walker with source and precomputed SLOC lines."""
        self._file_path = file_path
        self._source = source
        self._tree = tree
        self._sloc_lines = sloc_lines
        self._module_name = _module_name_for_path(file_path)
        self._imports_by_name = _rule_import_names(file_path, tree.root_node)
        self._symbols: list[SymbolIR] = []
        self._symbol_nodes: dict[str, Node] = {}

    def module(self) -> ModuleIR:
        """Return the parsed module IR."""
        self._visit_children(self._tree.root_node, VisitContext())
        span = _module_span(self._file_path, self._source)
        facts = python_facts(
            self._file_path, self._tree.root_node,
            span.entity_id(SymbolKind.MODULE), tuple(self._symbols), self._module_name,
        )
        symbols = tuple(
            symbol.model_copy(update={"references": _symbol_references(
                self._symbol_nodes[symbol.id], facts.source_uses, self._imports_by_name,
            )}) if symbol.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD} else symbol
            for symbol in facts.symbols
        )
        return ModuleIR(
            language=Language.PYTHON,
            file=self._file_path,
            module_name=self._module_name,
            span=span,
            imports=facts.imports,
            source_uses=facts.source_uses,
            attributes=facts.attributes,
            symbols=symbols,
            text_fragments=_text_fragments(
                self._file_path,
                self._tree.root_node,
                span.entity_id(SymbolKind.MODULE),
                tuple(self._symbols),
            ),
            sloc_lines=self._sloc_lines,
        )

    def _visit_children(self, node: Node, context: VisitContext) -> None:
        for child in node.children:
            self._visit_child(child, context)

    def _visit_child(self, child: Node, context: VisitContext) -> None:
        match child.type:
            case "import_statement" | "import_from_statement":
                return
            case "decorated_definition":
                self._visit_decorated_definition(child, context)
            case "class_definition":
                self._handle_class(child, context)
            case "function_definition":
                self._handle_function(child, context)
            case wrapper if wrapper in _DECLARATION_CONTAINER_TYPES:
                # Control-flow wrappers do not introduce lexical declaration owners.
                self._visit_children(child, context)

    def _visit_decorated_definition(
        self,
        node: Node,
        context: VisitContext,
    ) -> None:
        decorators = tuple(
            _decorator_name(child) for child in node.children if child.type == "decorator"
        )
        definition = next(
            (
                child
                for child in node.children
                if child.type in {"function_definition", "class_definition"}
            ),
            None,
        )
        if definition is None:
            return
        decorated_context = VisitContext(
            owner_qualified_name=context.owner_qualified_name,
            owner_id=context.owner_id,
            class_context=context.class_context,
            decorators=decorators,
        )
        if definition.type == "class_definition":
            self._handle_class(definition, decorated_context)
            return
        self._handle_function(definition, decorated_context)

    def _handle_class(self, node: Node, context: VisitContext) -> None:
        name = _name_from_node(node)
        if name is None:
            return
        qualified_name = _qualified_name(
            self._module_name,
            context.owner_qualified_name,
            name,
        )
        base_names = _class_base_names(node)
        class_symbol = SymbolIR(
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.CLASS,
            span=_node_span(self._file_path, node),
            language=Language.PYTHON,
            roles=frozenset(),
            owner_qualified_name=context.owner_qualified_name,
            owner_id=context.owner_id,
            base_names=base_names,
            sloc=_count_sloc_in_span(node, self._sloc_lines),
        )
        self._symbols.append(class_symbol)
        class_context = ClassContext(
            qualified_name=qualified_name,
            base_names=base_names,
        )
        self._visit_children(
            node,
            VisitContext(
                owner_qualified_name=qualified_name,
                owner_id=class_symbol.id,
                class_context=class_context,
            ),
        )

    def _handle_function(self, node: Node, context: VisitContext) -> None:
        name = _name_from_node(node)
        if name is None:
            return
        qualified_name = _qualified_name(
            self._module_name,
            context.owner_qualified_name,
            name,
        )
        signature = _signature_from_node(node)
        symbol = SymbolIR(
            name=name,
            qualified_name=qualified_name,
            kind=(
                SymbolKind.METHOD
                if context.class_context is not None
                else SymbolKind.FUNCTION
            ),
            span=_node_span(self._file_path, node),
            language=Language.PYTHON,
            roles=_function_roles(name, context, node),
            signature=signature,
            body=_body_operations(self._file_path, node, self._imports_by_name),
            owner_qualified_name=context.owner_qualified_name,
            owner_id=context.owner_id,
            base_names=(
                context.class_context.base_names
                if context.class_context is not None
                else ()
            ),
            sloc=_count_sloc_in_span(node, self._sloc_lines),
            cyc_complexity=1
            + sum(
                1
                for current in _iter_nodes(node)
                if current.type in _CYC_COMPLEXITY_NODE_TYPES
            ),
            cog_complexity=sum(
                _cognitive_for_node(child, nesting=0) for child in node.children
            ),
            max_nesting=_max_nesting_for_node(node),
        )
        self._symbols.append(symbol)
        self._symbol_nodes[symbol.id] = node
        self._visit_children(
            node,
            VisitContext(owner_qualified_name=qualified_name, owner_id=symbol.id),
        )


def _text_fragments(
    file_path: Path,
    root: Node,
    module_id: str,
    symbols: tuple[SymbolIR, ...],
) -> tuple[TextFragmentIR, ...]:
    """Extract occurrences once, using declaration ownership rather than execution scope."""
    owners = {
        (symbol.span.start_line - 1, symbol.span.start_col): symbol.id
        for symbol in symbols
    }
    docstrings: set[int] = set()
    fragments: list[TextFragmentIR] = []
    stack = [(root, module_id)]
    while stack:
        node, owner_id = stack.pop()
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            assert definition is not None  # noqa: S101 - Guaranteed by the valid grammar.
            owner_id = owners[definition.start_point]
        elif node.type in _SCOPE_NODE_TYPES:
            owner_id = owners[node.start_point]
        if node.type == "module" or node.type in _SCOPE_NODE_TYPES:
            docstrings.update(
                literal.start_byte for literal in _docstring_literals(node)
            )
        kind: TextFragmentKind | None = None
        if node.type == "identifier":
            kind = "identifier"
        elif node.type == "comment":
            kind = "comment"
        elif node.start_byte in docstrings and node.type == "string":
            kind = "docstring"
        if kind is not None:
            fragments.append(
                TextFragmentIR(
                    text=_text(node),
                    kind=kind,
                    span=_node_span(file_path, node),
                    owner_id=owner_id,
                )
            )
            continue
        stack.extend((child, owner_id) for child in reversed(node.named_children))
    return tuple(fragments)


def _parse_tree(source: str) -> Tree:
    parser = _get_parser()
    tree = parser.parse(source.encode("utf-8"))
    if tree.root_node.has_error:
        raise LanguageParseError(
            "failed to parse Python source",
            language=Language.PYTHON,
        )
    return tree


def _get_parser() -> Parser:
    global _PARSER  # noqa: PLW0603
    if _PARSER is None:
        language = TreeSitterLanguage(tree_sitter_python.language())
        _PARSER = Parser(language)
    return _PARSER


def _module_name_for_path(path: Path) -> str:
    package_parts = _package_parts(path.parent)
    if path.name == "__init__.py":
        return ".".join(package_parts) if package_parts else path.parent.name
    return ".".join((*package_parts, path.stem)) if package_parts else path.stem


def _package_parts(directory: Path) -> tuple[str, ...]:
    parts: list[str] = []
    current = directory
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent
    return tuple(reversed(parts))


def _name_from_node(node: Node) -> str | None:
    name_node = next(
        (
            child
            for child in node.children
            if child.type in {"identifier", "name"}
        ),
        None,
    )
    return _text(name_node) if name_node is not None else None


def _top_level_statements(node: Node) -> tuple[Node, ...]:
    block = next((child for child in node.children if child.type == "block"), None)
    if block is None:
        return ()
    return tuple(
        child
        for child in block.children
        if child.type.endswith(_STATEMENT_SUFFIX)
        or child.type
        in {
            "function_definition",
            "class_definition",
            "decorated_definition",
        }
    )


def _executable_body_statements(node: Node) -> tuple[Node, ...]:
    return tuple(
        statement
        for statement in _top_level_statements(node)
        if not _is_plain_string_expression_statement(statement)
    )


def _is_plain_string_expression_statement(statement: Node) -> bool:
    if statement.type != "expression_statement":
        return False
    if len(statement.named_children) != 1:
        return False

    expression = statement.named_children[0]
    if expression.type != "string":
        return False

    node_text = expression.text
    if node_text is None:
        return False

    prefix = python_string_prefix(node_text.decode("utf-8"))
    return "b" not in prefix and "f" not in prefix


def _sloc_line_numbers(source: str, tree: Tree) -> frozenset[int]:
    source_lines = source.splitlines(keepends=True)
    text_lines = source.splitlines()
    lines: set[int] = set()
    for token in generate_tokens(iter(source_lines).__next__):
        if token.type not in _IGNORED_SLOC_TOKEN_TYPES:
            lines.add(token.start[0])

    for start, end in _string_ranges(tree.root_node, text_lines):
        for line_no in range(start, end + 1):
            lines.discard(line_no)

    return frozenset(lines)


def _string_ranges(root: Node, source_lines: list[str]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if (
            _is_plain_string_expression_statement(node)
            and (literal := node.named_children[0]) is not None
            and _owns_line(literal, source_lines)
        ):
            ranges.append((literal.start_point[0] + 1, literal.end_point[0] + 1))
        stack.extend(reversed(node.named_children))
    return tuple(ranges)


def _owns_line(literal: Node, source_lines: list[str]) -> bool:
    start_row, start_col = literal.start_point
    end_row, end_col = literal.end_point
    start_line = source_lines[start_row] if start_row < len(source_lines) else ""
    end_line = source_lines[end_row] if end_row < len(source_lines) else ""
    return not start_line[:start_col].strip() and not end_line[end_col:].strip()


def _signature_from_node(node: Node) -> SignatureIR:
    annotations = _arguments_from_node(node)
    return SignatureIR(
        parameters=tuple(annotations),
        annotations=annotations,
        returns=_return_annotation_from_node(node),
    )


def _arguments_from_node(node: Node) -> dict[str, str | None]:
    params = next(
        (child for child in node.children if child.type == "parameters"), None,
    )
    if params is None:
        return {}
    return {
        name: annotation
        for child in params.children
        for parsed in [_parse_parameter(child)]
        if parsed is not None
        for name, annotation in [parsed]
    }


def _parse_parameter(node: Node) -> tuple[str, str | None] | None:
    if node.type == "identifier":
        return (_text(node), None)
    if node.type not in {
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }:
        return None
    name_node = next(
        (child for child in node.children if child.type == "identifier"),
        None,
    )
    if name_node is None:
        return None
    type_node = next(
        (child for child in node.children if child.type == "type"), None,
    )
    return (_text(name_node), _text(type_node) if type_node is not None else None)


def _return_annotation_from_node(node: Node) -> str | None:
    children = node.children
    return next(
        (
            _text(children[index + 1])
            for index, child in enumerate(children[:-1])
            if child.type == "->"
        ),
        None,
    )


def _decorator_name(node: Node) -> str:
    raw = _text(node).strip()
    return raw.removeprefix("@").strip()


def _class_base_names(node: Node) -> tuple[str, ...]:
    argument_list = next(
        (child for child in node.children if child.type == "argument_list"),
        None,
    )
    if argument_list is None:
        return ()
    return tuple(_text(child) for child in argument_list.named_children)


def _function_roles(
    name: str,
    context: VisitContext,
    node: Node,
) -> frozenset[SymbolRole]:
    return frozenset(
        role
        for role in (
            SymbolRole.CONTRACT_MEMBER if _is_dunder_name(name) else None,
            _decorator_role(context.decorators),
            _inherited_override_role(name, context),
            SymbolRole.FACTORY if _returns_constant_default_parameter(node) else None,
        )
        if role is not None
    )


def _decorator_role(decorators: tuple[str, ...]) -> SymbolRole | None:
    if not decorators:
        return None
    if any(decorator.startswith("property") for decorator in decorators):
        return SymbolRole.COMPUTED_ATTRIBUTE
    return SymbolRole.CONTRACT_MEMBER


def _inherited_override_role(
    name: str,
    context: VisitContext,
) -> SymbolRole | None:
    if (
        context.class_context is not None
        and context.class_context.base_names
        and name not in _RECEIVER_PARAMETER_NAMES
    ):
        return SymbolRole.INHERITED_OVERRIDE
    return None


def _returns_constant_default_parameter(node: Node) -> bool:
    returned_name = _single_returned_identifier(node)
    return (
        returned_name is not None
        and returned_name in _constant_default_parameter_names(node)
    )


def _single_returned_identifier(node: Node) -> str | None:
    statements = _executable_body_statements(node)
    if len(statements) != 1:
        return None
    statement = statements[0]
    if statement.type != "return_statement":
        return None
    value = next(
        (child for child in statement.named_children if child.type == "identifier"),
        None,
    )
    return _text(value) if value is not None else None


def _constant_default_parameter_names(node: Node) -> frozenset[str]:
    params = next(
        (child for child in node.children if child.type == "parameters"),
        None,
    )
    if params is None:
        return frozenset()
    return frozenset(
        name
        for child in params.named_children
        if child.type in {"default_parameter", "typed_default_parameter"}
        for name in [_name_from_node(child)]
        if name is not None and _has_constantish_default(child)
    )


def _has_constantish_default(node: Node) -> bool:
    default = _default_value_node(node)
    return default is not None and _is_constantish_value_node(default)


def _default_value_node(node: Node) -> Node | None:
    saw_equals = False
    for child in node.children:
        if child.type == "=":
            saw_equals = True
            continue
        if saw_equals and child.is_named:
            return child
    return None


def _is_constantish_value_node(node: Node) -> bool:
    if node.type == "identifier":
        return _text(node).isupper()
    return node.type in _LITERAL_TYPES | _COLLECTION_TYPES and not any(
        child.type == "call" for child in _iter_nodes(node)
    )


def _is_dunder_name(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _body_operations(
    file_path: Path,
    node: Node,
    imports: dict[str, str],
) -> tuple[OperationIR, ...]:
    return tuple(
        _operation_from_statement(file_path, statement, imports)
        for statement in _executable_body_statements(node)
    )


def _operation_from_statement(
    file_path: Path,
    statement: Node,
    imports: dict[str, str],
) -> OperationIR:
    kind = _operation_kind(statement)
    return OperationIR(
        kind=kind,
        span=_node_span(file_path, statement),
        value=_operation_value(file_path, statement, imports, kind),
    )


def _operation_kind(statement: Node) -> OperationKind:
    if statement.type in _STATEMENT_OPERATION_KINDS:
        return _STATEMENT_OPERATION_KINDS[statement.type]
    if statement.type == "expression_statement" and statement.named_children:
        expression = statement.named_children[0]
        return _EXPRESSION_OPERATION_KINDS.get(
            expression.type,
            OperationKind.UNKNOWN,
        )
    return OperationKind.UNKNOWN


def _operation_value(
    file_path: Path,
    statement: Node,
    imports: dict[str, str],
    kind: OperationKind,
) -> ValueIR | None:
    if kind is OperationKind.RETURN and statement.named_children:
        return _value_from_node(file_path, statement.named_children[0], imports)
    if kind is OperationKind.CALL:
        return _value_from_node(file_path, statement.named_children[0], imports)
    return None


def _value_from_node(
    file_path: Path,
    node: Node,
    imports: dict[str, str],
) -> ValueIR:
    if node.type == "call":
        return _invocation_value(file_path, node, imports)
    if node.type in {"identifier", "attribute"}:
        return _reference_value(file_path, node, imports)
    if node.type in _LITERAL_TYPES:
        return ValueIR(
            kind=ValueKind.LITERAL,
            span=_node_span(file_path, node),
            text=_text(node),
        )
    if node.type in _COLLECTION_TYPES:
        return _compound_value(file_path, node, imports, ValueKind.COLLECTION)
    if node.type in _OPERATOR_TYPES:
        return _compound_value(file_path, node, imports, ValueKind.OPERATOR)
    return ValueIR(kind=ValueKind.UNKNOWN, span=_node_span(file_path, node), text=_text(node))


def _compound_value(
    file_path: Path,
    node: Node,
    imports: dict[str, str],
    kind: ValueKind,
) -> ValueIR:
    return ValueIR(
        kind=kind,
        span=_node_span(file_path, node),
        text=_text(node),
        arguments=tuple(
            _value_from_node(file_path, child, imports)
            for child in node.named_children
        ),
    )


def _reference_value(
    file_path: Path,
    node: Node,
    imports: dict[str, str],
) -> ValueIR:
    name = _text(node)
    kind = (
        ValueKind.SYMBOL_REFERENCE
        if node.type == "identifier"
        else ValueKind.MEMBER_ACCESS
    )
    return ValueIR(
        kind=kind,
        span=_node_span(file_path, node),
        text=name,
        name=name,
        resolved_name=_resolve_name(name, imports),
    )


def _invocation_value(
    file_path: Path,
    node: Node,
    imports: dict[str, str],
) -> ValueIR:
    raw_name = _call_name(node)
    argument_list = next(
        (child for child in node.children if child.type == "argument_list"),
        None,
    )
    return ValueIR(
        kind=ValueKind.INVOCATION,
        span=_node_span(file_path, node),
        text=_text(node),
        name=raw_name,
        resolved_name=_resolve_name(raw_name, imports) if raw_name is not None else None,
        arguments=(
            tuple(
                _value_from_node(file_path, child, imports)
                for child in argument_list.named_children
            )
            if argument_list is not None
            else ()
        ),
    )


def _symbol_references(
    node: Node,
    uses: tuple[SourceUseIR, ...],
    imports: dict[str, str],
) -> tuple[ReferenceIR, ...]:
    # This compatibility projection intentionally includes textually nested bodies
    # and headers. Execution ownership in the canonical inventory is independent.
    local = _local_names(node) | _BUILTIN_CALL_ROOTS
    base_nesting = 0
    ancestor = node.parent
    while ancestor is not None:
        base_nesting += ancestor.type in _COG_FLOW_BREAK_TYPES
        ancestor = ancestor.parent
    return tuple(
        ReferenceIR(
            name=use.target_spelling,
            resolved_name=_resolve_name(use.target_spelling, imports),
            kind="call", span=use.target_span, nesting=use.nesting - base_nesting,
            source_use_id=use.id,
        )
        for use in uses
        if use.kind == "call" and use.target_form != "expression"
        and (use.span.start_line - 1, use.span.start_col) >= node.start_point
        and (use.span.end_line - 1, use.span.end_col) <= node.end_point
        and use.target_spelling.split(".", 1)[0] not in local
    )


def _local_names(node: Node) -> set[str]:
    names = {_name_from_node(node) or ""}
    names.update(_arguments_from_node(node))
    for current in _iter_nodes(node):
        if current is node:
            continue
        if current.type in _SCOPE_NODE_TYPES:
            name = _name_from_node(current)
            if name is not None:
                names.add(name)
    names.discard("")
    return names


def _call_name(node: Node) -> str | None:
    target = _call_target(node)
    name = None
    if target is not None and target.type in {"identifier", "attribute"}:
        name = _text(target)
    return name


def _call_target(node: Node) -> Node | None:
    return next(
        (
            child
            for child in node.children
            if child.type not in {"argument_list", "(", ")", ","}
        ),
        None,
    )


def _rule_import_names(file_path: Path, root: Node) -> dict[str, str]:
    # Keep root-only rule expansion independent of canonical scoped resolution,
    # including its historical handling of unaliased dotted and relative imports.
    names: dict[str, str] = {}
    for statement in root.named_children:
        if statement.type not in {"import_statement", "import_from_statement"}:
            continue
        module = statement.child_by_field_name("module_name")
        if module is not None and module.type == "relative_import":
            names.update(_relative_rule_import_names(file_path, statement, module))
            continue
        children: dict[tuple[int, int], Node] = {
            child.start_point: child for child in statement.named_children
        }
        for binding in import_bindings(file_path, statement):
            qualified = binding.qualified_name
            point = (binding.span.start_line - 1, binding.span.start_col)
            if statement.type == "import_statement" and children[point].type == "dotted_name":
                qualified = _text(children[point])
            names[binding.local_name] = qualified
    return names


def _relative_rule_import_names(file: Path, statement: Node, module: Node) -> dict[str, str]:
    # The rule policy selects the first plain imported name as its prefix for
    # relative imports. Do not apply this historical expansion to canonical facts.
    selected = next((child for child in statement.named_children if child.type == "dotted_name"), None)
    prefix = f"{_text(selected)}." if selected is not None else ""
    return {
        binding.local_name: prefix + binding.qualified_name[len(_text(module)):].removeprefix(".")
        for binding in import_bindings(file, statement)
        if selected is None or (binding.span.start_line - 1, binding.span.start_col) != selected.start_point
    }


def _resolve_name(name: str, imports: dict[str, str]) -> str:
    root = name.split(".", 1)[0]
    if root not in imports:
        return name
    return imports[root] if root == name else f"{imports[root]}{name[len(root) :]}"


def _cognitive_for_node(node: Node, *, nesting: int) -> int:
    child_score = sum(
        _cognitive_for_node(child, nesting=nesting) for child in node.children
    )
    if node.type == "boolean_operator":
        return 1 + child_score
    if node.type in _COG_JUMP_TYPES:
        return 1
    if node.type in _COG_FLOW_BREAK_TYPES:
        nested_score = sum(
            _cognitive_for_node(child, nesting=nesting + 1)
            for child in node.children
        )
        return 1 + nesting + nested_score
    return child_score


def _max_nesting_for_node(node: Node) -> int:
    max_nesting = 0
    stack = [(node, 0)]
    while stack:
        current, nesting = stack.pop()
        max_nesting = max(max_nesting, nesting)
        child_nesting = nesting + 1 if current.type in _COG_FLOW_BREAK_TYPES else nesting
        stack.extend((child, child_nesting) for child in current.children)
    return max_nesting
