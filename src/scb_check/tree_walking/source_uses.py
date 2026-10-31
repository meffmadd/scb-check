"""Pure project resolution for the canonical module-owned source-use inventory."""

from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import SymbolKind
from scb_check.tree_walking.models import TargetResolutionIR


def resolve_source_uses(modules: tuple[ModuleIR, ...]) -> tuple[ModuleIR, ...]:
    """Resolve imported names only against retained project facts, without type inference."""
    entities: dict[str, list[ModuleIR | SymbolIR]] = {}
    for module in modules:
        entities.setdefault(module.qualified_name, []).append(module)
        symbols = {symbol.id: symbol for symbol in module.symbols}
        for symbol in module.symbols:
            if _module_accessible(symbol, module.id, symbols):
                entities.setdefault(symbol.qualified_name, []).append(symbol)

    def resolve(resolution: TargetResolutionIR) -> TargetResolutionIR:
        if resolution.reason not in {
            "import-binding", "project-import-binding", "multiple-project-bindings", "unresolved-project-member",
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

    return tuple(module.model_copy(update={
        "source_uses": tuple(use.model_copy(update={"resolution": resolve(use.resolution)})
                             for use in module.source_uses),
    }) for module in modules)


def _module_accessible(symbol: SymbolIR, module_id: str, symbols: dict[str, SymbolIR]) -> bool:
    owner_id = symbol.owner_id
    while owner_id != module_id:
        owner = symbols.get(owner_id) if owner_id is not None else None
        if owner is None or owner.kind is not SymbolKind.CLASS:
            return False
        owner_id = owner.owner_id
    return True
