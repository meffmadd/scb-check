"""Recognize Python string prefixes and docstring literals."""

from tree_sitter import Node

from scb_check.tree_walking.languages._node_helpers import text


def python_string_prefix(literal: str) -> str:
    """Return the lowercase prefix before a Python string literal quote."""
    prefix_chars: list[str] = []
    for character in literal:
        if character in {'"', "'"}:
            break
        prefix_chars.append(character.lower())
    return "".join(prefix_chars)


def docstring_literals(node: Node) -> tuple[Node, ...]:
    """Return initial plain docstring literals, keeping concatenated parts separate."""
    body = node if node.type == "module" else node.child_by_field_name("body")
    if body is None:
        return ()
    first = next(
        (child for child in body.named_children if child.type != "comment"), None,
    )
    if first is None or first.type != "expression_statement":
        return ()
    # Unparenthesized tuples expose their comma beside the first expression.
    if any(child.type == "," for child in first.children):
        return ()
    expression = first.named_children[0]
    while expression.type == "parenthesized_expression":
        expression = next(
            child for child in expression.named_children if child.type != "comment"
        )
    if expression.type == "string":
        literals = (expression,)
    elif expression.type == "concatenated_string":
        literals = tuple(
            child for child in expression.named_children if child.type == "string"
        )
    else:
        return ()
    if any(set(python_string_prefix(text(literal))) & {"b", "f"} for literal in literals):
        return ()
    return literals
