"""Shared category membership and directed dependency policy for Ca and Ce."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from scb_check.tree_walking.models import ProjectIR
from scb_check.tree_walking.models import SymbolKind


@dataclass(frozen=True, slots=True)
class CategoryDependencies:
    """Immutable class membership, unsupported categories, and directed class pairs.

    Categories are class-bearing logical modules, identified by module ID rather
    than qualified name or directory. Known edges remain evidence even when an
    endpoint's category is unavailable; they can inform other measured categories.
    """

    class_categories: Mapping[str, str]
    unavailable_categories: frozenset[str]
    class_edges: frozenset[tuple[str, str]]

    def __post_init__(self) -> None:
        """Own a read-only membership copy, including for direct metric callers."""
        object.__setattr__(self, "class_categories", MappingProxyType(dict(self.class_categories)))


def category_dependencies(project: ProjectIR) -> CategoryDependencies:
    """Project retained facts onto the common Ca/Ce measurement policy, without IO.

    Calls select statically resolved implemented methods; accesses select
    canonical declared fields. Imports, construction alone, bare method
    references, inheritance alone, and annotations alone add no dependencies.
    Possible runtime targets are deliberately not expanded. Uses belong to the
    nearest enclosing class, including initialization and nested functions;
    module/free-function and unsupported execution do not supply client classes.

    Missing use, field, base, or method extraction makes an internal category
    unavailable. Unresolved sites are omitted within explicitly partial evidence,
    never interpreted as proof of absent outgoing or incoming dependencies.
    """
    symbols = project.symbols_by_id
    membership = {
        symbol.id: module.id
        for module in project.modules for symbol in module.symbols
        if symbol.kind == SymbolKind.CLASS
    }
    categories = set(membership.values())
    unavailable = frozenset(
        module.id for module in project.modules
        if module.id in categories and (
            module.source_uses is None or module.attributes is None
            or any((symbol.kind == SymbolKind.CLASS and symbol.direct_bases is None)
                   or (symbol.kind == SymbolKind.METHOD and symbol.callable_facts is None)
                   for symbol in module.symbols)
        )
    )
    edges: set[tuple[str, str]] = set()
    for use in project.source_uses_by_id.values():
        if (
            use.execution_kind == "unsupported" or use.unsupported_context is not None
            or use.resolution.status != "project"
        ):
            continue
        source = use.owner_id
        while source in symbols and source not in membership:
            source = symbols[source].owner_id
        if source not in membership:
            continue
        target_id = use.resolution.target_id
        target_class = None
        if use.kind == "call":
            target = symbols.get(target_id or "")
            if (
                target is not None and target.kind == SymbolKind.METHOD
                and target.callable_facts is not None
                and target.callable_facts.implementation_id is not None
            ):
                target_class = target.callable_facts.declaring_class_id
        else:
            attribute = project.attributes_by_id.get(target_id or "")
            if attribute is not None:
                target_class = attribute.declaring_class_id
        if target_class in membership and target_class != source:
            edges.add((source, target_class))
    return CategoryDependencies(membership, unavailable, frozenset(edges))
