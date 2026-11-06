"""Parse type annotations without evaluating them, importing modules, or reading files."""

import ast
from collections.abc import Callable
from dataclasses import dataclass

from scb_check.tree_walking.models import SourceSpan
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import TypeReferenceIR

type AnnotationResolver = Callable[[str], TargetResolutionIR]


def type_reference(
    spelling: str, span: SourceSpan, resolve: AnnotationResolver,
    *, allow_forward: bool = True,
) -> TypeReferenceIR:
    """Parse a type expression, keeping unsupported syntax as unknown rather than guessing."""
    try:
        expression = ast.parse(spelling, mode="eval").body
    except SyntaxError:
        return TypeReferenceIR(spelling=spelling, span=span, form="unknown")
    reference = _TypeParser(span, resolve, allow_forward).reference(expression, spelling)
    return reference.model_copy(update={"spelling": spelling})


@dataclass(frozen=True, slots=True)
class _TypeParser:
    span: SourceSpan
    resolve: AnnotationResolver
    allow_forward: bool

    def reference(self, node: ast.expr, source: str) -> TypeReferenceIR:  # noqa: PLR0911 - Annotation syntax forms.
        spelling = ast.get_source_segment(source, node) or source
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and self.allow_forward:
                inner = type_reference(node.value, self.span, self.resolve)
                return inner.model_copy(update={"spelling": spelling, "is_forward": True})
            if node.value is None:
                return TypeReferenceIR(spelling=spelling, span=self.span, form="name", name="None",
                                       resolution=TargetResolutionIR(status="external", qualified_name="builtins.None", reason="builtin"))
            return TypeReferenceIR(spelling=spelling, span=self.span, form="literal", category="other")
        name = _dotted_name(node)
        if name is not None:
            return TypeReferenceIR(spelling=spelling, span=self.span, form="name", name=name, resolution=self.resolve(name))
        if isinstance(node, ast.Subscript):
            name = _dotted_name(node.value)
            resolution = self.resolve(name) if name is not None else TargetResolutionIR(reason="dynamic-target")
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            qualified = resolution.qualified_name
            arguments = tuple(
                TypeReferenceIR(spelling=ast.get_source_segment(source, item) or source, span=self.span, form="literal", category="other")
                if qualified in {"typing.Literal", "typing_extensions.Literal"}
                or (index > 0 and qualified in {"typing.Annotated", "typing_extensions.Annotated"})
                else self.reference(item, source)
                for index, item in enumerate(items)
            )
            return TypeReferenceIR(spelling=spelling, span=self.span, form="generic", name=name,
                                   arguments=arguments, resolution=resolution)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            arguments = tuple(self.reference(item, source) for item in (node.left, node.right))
            return TypeReferenceIR(spelling=spelling, span=self.span, form="union", arguments=arguments, category="other")
        if isinstance(node, ast.List):
            # Callable[[A, B], R] retains its parameter type list without flattening.
            return TypeReferenceIR(spelling=spelling, span=self.span, form="type-list", category="other",
                                   arguments=tuple(self.reference(item, source) for item in node.elts))
        return TypeReferenceIR(spelling=spelling, span=self.span, form="unknown", resolution=TargetResolutionIR(reason="dynamic-target"))


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None
