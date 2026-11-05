"""Resolve Python members and possible method implementations within the analyzed project."""

from dataclasses import dataclass

from scb_check.tree_walking.models import AttributeIR
from scb_check.tree_walking.models import MemberLookup
from scb_check.tree_walking.models import ModuleIR
from scb_check.tree_walking.models import ReceiverIR
from scb_check.tree_walking.models import RuntimeTargetsIR
from scb_check.tree_walking.models import SourceUseIR
from scb_check.tree_walking.models import SymbolIR
from scb_check.tree_walking.models import TargetResolutionIR


@dataclass(frozen=True, slots=True)
class _MemberSelection:
    resolution: TargetResolutionIR
    dispatch_class: str | None = None
    class_object: bool = False
    approximate_path: bool = False


def resolve_member_uses(modules: tuple[ModuleIR, ...]) -> tuple[tuple[ModuleIR, ...], MemberLookup, MemberLookup]:
    """Resolve calls and accesses, and build instance and class member lookups without IO."""
    resolver = _MemberResolver(modules)
    return tuple(module.model_copy(update={
        "source_uses": None if module.source_uses is None else tuple(
            resolver.resolve_use(use) for use in module.source_uses
        ),
    }) for module in modules), resolver.lookup, resolver.class_lookup


def _c3_merge_inplace(sequences: list[list[str]]) -> tuple[str, ...] | None:
    """Consume base-class method orders using Python's C3 merge; return `None` on conflict."""
    result: list[str] = []
    while any(sequences):
        sequences = [sequence for sequence in sequences if sequence]
        head = next((sequence[0] for sequence in sequences
                     if all(sequence[0] not in other[1:] for other in sequences)), None)
        if head is None:
            return None
        result.append(head)
        for sequence in sequences:
            if sequence[0] == head:
                sequence.pop(0)
    return tuple(result)


class _MemberResolver:
    def __init__(self, modules: tuple[ModuleIR, ...]) -> None:
        self.symbols = {symbol.id: symbol for module in modules for symbol in module.symbols}
        self.entities = {
            **{module.id: module for module in modules}, **self.symbols,
            **{field.id: field for module in modules for field in module.attributes or ()},
        }
        self.classes = {key: symbol for key, symbol in self.symbols.items() if symbol.direct_bases is not None}
        self.children: dict[str, dict[str, list[str]]] = {}
        modules_by_name: dict[str, list[ModuleIR]] = {}
        for module in modules:
            modules_by_name.setdefault(module.module_name, []).append(module)
        for child in modules:
            prefix, _, name = child.module_name.rpartition(".")
            for parent in modules_by_name.get(prefix, ()):
                self.children.setdefault(parent.id, {}).setdefault(name, []).append(child.id)
        for entity in self.entities.values():
            if isinstance(entity, ModuleIR):
                continue
            owner = entity.declaring_class_id if isinstance(entity, AttributeIR) else entity.owner_id
            if owner is not None:
                self.children.setdefault(owner, {}).setdefault(entity.name, []).append(entity.id)
        self.mros: dict[str, tuple[str, ...] | None] = {}
        for class_id in self.classes:
            self._mro(class_id, frozenset())
        self.lookup = self._lookup_view(class_object=False)
        self.class_lookup = self._lookup_view(class_object=True)

    def _lookup_view(self, *, class_object: bool) -> MemberLookup:
        return {
            class_id: {name: self._member(class_id, name, class_object=class_object)
                       for name in self._names(class_id)
                       if not class_object or self._class_candidates(class_id, name)}
            for class_id in self.classes
        }

    def _class_candidates(self, class_id: str, name: str) -> list[str]:
        for owner in self.mros[class_id] or (class_id,):
            candidates = []
            for entity_id in self.children.get(owner, {}).get(name, ()):
                entity = self.entities[entity_id]
                if not isinstance(entity, AttributeIR) or "class" in entity.writes:
                    candidates.append(entity_id)
            if candidates:
                return candidates
        return []

    def _mro(self, class_id: str, pending: frozenset[str]) -> tuple[str, ...] | None:
        if class_id in self.mros:
            return self.mros[class_id]
        if class_id in pending:
            return None
        bases = self.classes[class_id].direct_bases
        assert bases is not None  # noqa: S101 - Only supported classes enter this index.
        ids: list[str] = []
        for base in bases:
            if base.resolution.qualified_name == "builtins.object" and base.resolution.status == "external":
                continue
            target = base.resolution.target_id
            if base.form != "name" or target not in self.classes:
                self.mros[class_id] = None
                return None
            ids.append(target)
        parent_mros = [self._mro(base, pending | {class_id}) for base in ids]
        if len(set(ids)) != len(ids) or any(mro is None for mro in parent_mros):
            self.mros[class_id] = None
            return None
        sequences = [list(mro) for mro in parent_mros if mro is not None] + [ids.copy()]
        merged = _c3_merge_inplace(sequences)
        self.mros[class_id] = None if merged is None else (class_id, *merged)
        return self.mros[class_id]

    def _names(self, class_id: str) -> set[str]:
        return {name for owner in self.mros[class_id] or (class_id,) for name in self.children.get(owner, {})}

    def _member(self, class_id: str, name: str, *, class_object: bool = False) -> TargetResolutionIR:
        if name.startswith("__") and not name.endswith("__"):
            return TargetResolutionIR(status="unsupported", reason="private-member")
        ids = self._class_candidates(class_id, name)
        if not class_object:
            instance_fields = [entity_id for owner in self.mros[class_id] or (class_id,)
                               for entity_id in self.children.get(owner, {}).get(name, ())
                               if isinstance(entity := self.entities[entity_id], AttributeIR)
                               and "instance" in entity.writes]
            if instance_fields:
                # Instance writes can shadow non-data descriptors anywhere in the MRO.
                # Without construction/flow analysis retain all competing declarations.
                ids = list(dict.fromkeys((*instance_fields, *ids)))
            if not ids:
                ids = self._annotation_fields(class_id, name)
        if ids:
            return self._selection(ids)
        return TargetResolutionIR(reason="unknown-member-order" if self.mros[class_id] is None else "missing-member")

    def _annotation_fields(self, class_id: str, name: str) -> list[str]:
        # An annotation can type an instance field without creating a class binding.
        for owner in self.mros[class_id] or (class_id,):
            fields = [entity_id for entity_id in self.children.get(owner, {}).get(name, ())
                      if isinstance(self.entities[entity_id], AttributeIR)]
            if fields:
                return fields
        return []

    def _selection(self, ids: list[str]) -> TargetResolutionIR:
        if not ids:
            return TargetResolutionIR(reason="missing-member")
        if len(ids) != 1:
            return TargetResolutionIR(status="ambiguous", candidate_ids=tuple(ids), reason="multiple-member-declarations")
        entity = self.entities[ids[0]]
        return TargetResolutionIR(status="project", target_id=entity.id,
                                  qualified_name=entity.qualified_name if isinstance(entity, (SymbolIR, ModuleIR)) else None,
                                  reason="member-declaration")

    def resolve_use(self, use: SourceUseIR) -> SourceUseIR:
        selection = _MemberSelection(use.resolution)
        if use.receiver is not None:
            selection = self._resolve_receiver(use.receiver, use.resolution)
        if use.declared_attribute_id is not None:
            selection = _MemberSelection(TargetResolutionIR(status="project", target_id=use.declared_attribute_id, reason="member-declaration"))
        runtime = self._runtime(selection) if use.kind in {"call", "attribute-read"} else RuntimeTargetsIR(reason="not-a-callable-use")
        return use.model_copy(update={"resolution": selection.resolution, "runtime_targets": runtime})

    def _resolve_receiver(self, receiver: ReceiverIR, resolution: TargetResolutionIR) -> _MemberSelection:
        dispatch_class: str | None = None
        root = receiver.resolution
        declared = receiver.declared_type
        class_object = declared is None or receiver.is_class_receiver
        approximate_path = declared is not None and len(receiver.member_path) > 1
        if declared is not None:
            root = declared.resolution if declared.form == "name" and declared.category == "class" else TargetResolutionIR()
        target = root.target_id
        for index, member in enumerate(receiver.member_path):
            if target in self.classes:
                resolution = self._member(target, member, class_object=class_object)
                if index == len(receiver.member_path) - 1 and declared is not None:
                    dispatch_class = target
            elif target in self.entities and isinstance(self.entities[target], ModuleIR):
                resolution = self._selection(self.children.get(target, {}).get(member, []))
            else:
                if index > 0:
                    resolution = TargetResolutionIR(reason="receiver-needs-member-resolution")
                break
            target = resolution.target_id
            # Supported nested receiver paths follow a single explicit field type.
            entity = self.entities.get(target) if target is not None else None
            if target in self.classes:
                class_object = True
            if isinstance(entity, AttributeIR) and index < len(receiver.member_path) - 1:
                approximate_path = True
                class_object = False
                types = entity.declared_types
                if len(types) == 1 and types[0].form == "name" and types[0].category == "class":
                    target = types[0].resolution.target_id
                    declared = types[0]
                else:
                    resolution = TargetResolutionIR(reason="receiver-needs-member-resolution")
                    break
        return _MemberSelection(resolution, dispatch_class, class_object, approximate_path)

    def _runtime(self, selection: _MemberSelection) -> RuntimeTargetsIR:
        resolution = selection.resolution
        dispatch_class = selection.dispatch_class
        selected = self.symbols.get(resolution.target_id) if resolution.target_id is not None else None
        if selected is None or selected.callable_facts is None:
            return RuntimeTargetsIR()
        targets: set[str] = set()
        complete = not selection.approximate_path
        candidates = [resolution]
        if dispatch_class is not None:
            candidates = [self._member(class_id, selected.name, class_object=selection.class_object) for class_id, mro in self.mros.items()
                          if mro is not None and dispatch_class in mro]
            # An unresolved hierarchy could hide a subclass or an override.
            complete = complete and all(mro is not None for mro in self.mros.values())
        for candidate in candidates:
            symbol = self.symbols.get(candidate.target_id) if candidate.target_id is not None else None
            facts = symbol.callable_facts if symbol is not None else None
            if facts is None or not facts.dispatch_supported or facts.implementation_id is None:
                complete = False
            else:
                targets.add(facts.implementation_id)
        if not targets:
            return RuntimeTargetsIR(reason="no-supported-implementation")
        return RuntimeTargetsIR(status="complete" if complete else "approximate", target_ids=tuple(sorted(targets)),
                                assumption="closed-project-hierarchy", reason="supported-declarations" if complete else "partial-hierarchy-path-or-implementation")
