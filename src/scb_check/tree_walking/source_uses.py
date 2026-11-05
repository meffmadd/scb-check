"""Match calls, accesses, and declared types or bases to project declarations without IO."""

from collections.abc import Callable

from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR
from scb_check.tree_walking.models import TypeReferenceIR

_PRIMITIVES = frozenset(f"builtins.{name}" for name in (
    "bool", "int", "float", "complex", "str", "bytes", "None",
)) | {"types.NoneType"}
_TYPING_FORMS = frozenset(f"{module}.{name}" for module in ("typing", "typing_extensions") for name in (
    "Annotated", "Any", "Callable", "ClassVar", "Final", "Generic", "Literal", "Optional",
    "Protocol", "Union", "List", "Dict", "Set", "FrozenSet", "Tuple", "Type", "Self",
    "Never", "NoReturn", "TypeGuard", "TypeIs", "Required", "NotRequired", "Unpack",
))


def resolve_project_references(modules: tuple[ModuleIR, ...]) -> tuple[ModuleIR, ...]:
    """Match imported names to analyzed modules and declarations without inferring types."""
    entities: dict[str, list[ModuleIR | SymbolIR]] = {}
    for module in modules:
        entities.setdefault(module.qualified_name, []).append(module)
        symbols = {symbol.id: symbol for symbol in module.symbols}
        for symbol in module.symbols:
            if _module_accessible(symbol, module.id, symbols):
                entities.setdefault(symbol.qualified_name, []).append(symbol)

    def resolve(resolution: TargetResolutionIR) -> TargetResolutionIR:
        if resolution.reason not in {
            "import-binding", "project-import-binding", "multiple-project-bindings", "unresolved-project-member", "self-type",
        }:
            return resolution
        name = resolution.qualified_name
        assert name is not None  # noqa: S101 - Import bindings always have a name.
        candidates = entities.get(name, [])
        if len(candidates) == 1:
            return TargetResolutionIR(
                status="project", target_id=candidates[0].id,
                qualified_name=name, reason="project-import-binding",
            )
        if candidates:
            return TargetResolutionIR(
                status="ambiguous", qualified_name=name,
                candidate_ids=tuple(candidate.id for candidate in candidates),
                reason="multiple-project-bindings",
            )
        if any(name.startswith(f"{module.module_name}.") for module in modules):
            return TargetResolutionIR(
                qualified_name=name, reason="unresolved-project-member",
            )
        return TargetResolutionIR(status="external", qualified_name=name, reason="import-binding")

    symbols = {symbol.id: symbol for module in modules for symbol in module.symbols}
    return tuple(module.model_copy(update={
        "source_uses": None if module.source_uses is None else tuple(
            use.model_copy(update={
                "resolution": resolve(use.resolution),
                "receiver": None if use.receiver is None else use.receiver.model_copy(update={
                    "resolution": resolve(use.receiver.resolution),
                    "declared_type": None if use.receiver.declared_type is None else _resolve_type(use.receiver.declared_type, resolve, symbols),
                }),
            }) for use in module.source_uses
        ),
        "symbols": tuple(symbol.model_copy(update={
            "direct_bases": None if symbol.direct_bases is None else tuple(
                _resolve_type(base, resolve, symbols) for base in symbol.direct_bases
            ),
        }) for symbol in module.symbols),
        "attributes": None if module.attributes is None else tuple(attribute.model_copy(update={
            "declared_types": tuple(_resolve_type(reference, resolve, symbols, attribute.declaring_class_id) for reference in attribute.declared_types),
        }) for attribute in module.attributes),
    }) for module in modules)


def _resolve_type(
    reference: TypeReferenceIR, resolve: Callable[[TargetResolutionIR], TargetResolutionIR],
    symbols: dict[str, SymbolIR], declaring_class_id: str | None = None,
) -> TypeReferenceIR:
    resolution = resolve(reference.resolution)
    if resolution.status == "external" and resolution.qualified_name in {"typing.Self", "typing_extensions.Self"} and declaring_class_id is not None:
        resolution = resolution.model_copy(update={
            "status": "project", "target_id": declaring_class_id, "reason": "self-type",
        })
    target = symbols.get(resolution.target_id) if resolution.target_id is not None else None
    category = "unknown"
    if reference.form in {"union", "literal", "type-list"}:
        category = "other"
    elif resolution.status == "project" and target is not None:
        category = "class" if target.kind is SymbolKind.CLASS else "other"
    elif resolution.status == "external":
        if resolution.qualified_name in _PRIMITIVES:
            category = "primitive"
        elif resolution.reason == "builtin" or resolution.qualified_name in _TYPING_FORMS:
            category = "other"
    return reference.model_copy(update={
        "resolution": resolution, "category": category,
        "arguments": tuple(_resolve_type(argument, resolve, symbols, declaring_class_id) for argument in reference.arguments),
    })


def _module_accessible(symbol: SymbolIR, module_id: str, symbols: dict[str, SymbolIR]) -> bool:
    owner_id = symbol.owner_id
    while owner_id != module_id:
        owner = symbols.get(owner_id) if owner_id is not None else None
        if owner is None or owner.kind is not SymbolKind.CLASS:
            return False
        owner_id = owner.owner_id
    return True
