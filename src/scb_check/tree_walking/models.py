"""Language-agnostic IR models for tree walking and structural rules."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from os.path import abspath
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Self

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import PrivateAttr
from pydantic import field_validator
from pydantic import model_validator

HIGH_COMPLEXITY_THRESHOLD = 10


class IRModel(BaseModel):
    """Base for immutable Pydantic IR records."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class Language(StrEnum):
    """Supported source languages."""

    CPP = "cpp"
    HASKELL = "haskell"
    JAVASCRIPT = "javascript"
    PYTHON = "python"
    PYTHON_STUB = "python-stub"
    RUST = "rust"
    TYPESCRIPT = "typescript"
    ZIG = "zig"


class Severity(StrEnum):
    """Structural finding severity."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SymbolKind(StrEnum):
    """Language-agnostic symbol categories."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VALUE = "value"


class SymbolRole(StrEnum):
    """Semantic roles used by structural rules."""

    CONTRACT_MEMBER = "contract-member"
    INHERITED_OVERRIDE = "inherited-override"
    COMPUTED_ATTRIBUTE = "computed-attribute"
    ENTRYPOINT = "entrypoint"
    PUBLIC_API = "public-api"
    FACTORY = "factory"
    UNKNOWN_EXTERNAL_BINDING = "unknown-external-binding"


class RuleTarget(StrEnum):
    """Subject category a structural rule checks."""

    SYMBOL = "symbol"
    MODULE = "module"
    OPERATION = "operation"
    PROJECT = "project"


class OperationKind(StrEnum):
    """Normalized body operation kinds."""

    RETURN = "return"
    BIND = "bind"
    ASSIGN = "assign"
    CALL = "call"
    BRANCH = "branch"
    LOOP = "loop"
    RAISE = "raise"
    YIELD = "yield"
    AWAIT = "await"
    ENTER_SCOPE = "enter-scope"
    UNKNOWN = "unknown"


class ValueKind(StrEnum):
    """Normalized expression value kinds."""

    SYMBOL_REFERENCE = "symbol-reference"
    MEMBER_ACCESS = "member-access"
    INVOCATION = "invocation"
    LITERAL = "literal"
    COLLECTION = "collection"
    OPERATOR = "operator"
    UNKNOWN = "unknown"


class EffectKind(StrEnum):
    """Derived behavior facts used by semantic queries."""

    READ = "read"
    WRITE = "write"
    MUTATION = "mutation"
    PROJECT_CALL = "project-call"
    EXTERNAL_CALL = "external-call"
    ALLOCATION = "allocation"
    RAISE = "raise"
    UNRESOLVED_CALL = "unresolved-call"


class SourceSpan(IRModel):
    """A range with one-based lines, zero-based UTF-8 byte columns, exclusive ends."""

    file: Path
    start_line: int = Field(ge=1)
    start_col: int = Field(ge=0)
    end_line: int = Field(ge=1)
    end_col: int = Field(ge=0)

    _file_id: str = PrivateAttr()

    def model_post_init(self, _context: object) -> None:
        """Capture physical-file identity before the process cwd can change."""
        # `Path.resolve()` would introduce filesystem IO into the pure IR.
        normalized = abspath(self.file)  # noqa: PTH100
        self._file_id = f"file:{Path(normalized).as_posix()}"

    @property
    def file_id(self) -> str:
        """Return normalized absolute physical-file identity without source IO."""
        return self._file_id

    def entity_id(self, kind: SymbolKind) -> str:
        """Identify a declaration by physical file, kind, and declaration span."""
        return (
            f"{self.file_id}:{kind.value}:"
            f"{self.start_line}:{self.start_col}-{self.end_line}:{self.end_col}"
        )


type SignatureAnnotations = Mapping[str, str | None]


class SignatureIR(IRModel):
    """Normalized callable signature facts."""

    parameters: tuple[str, ...] = ()
    annotations: SignatureAnnotations = Field(
        default_factory=lambda: MappingProxyType({})
    )
    returns: str | None = None

    @field_validator("annotations")
    @classmethod
    def _freeze_annotations(cls, annotations: SignatureAnnotations) -> SignatureAnnotations:
        """Own a read-only copy of signature annotations."""
        return MappingProxyType(dict(annotations))


class ImportIR(IRModel):
    """A module import binding."""

    local_name: str
    qualified_name: str
    span: SourceSpan


class ReferenceIR(IRModel):
    """A resolved symbol usage location in scanned source."""

    name: str
    resolved_name: str | None
    kind: Literal["call", "reference"]
    span: SourceSpan
    nesting: int = 0


class ValueIR(IRModel):
    """A normalized expression value."""

    kind: ValueKind
    span: SourceSpan
    text: str = ""
    name: str | None = None
    resolved_name: str | None = None
    arguments: tuple[ValueIR, ...] = ()


class OperationIR(IRModel):
    """A normalized statement or body operation."""

    kind: OperationKind
    span: SourceSpan
    value: ValueIR | None = None
    target: ValueIR | None = None


class EffectIR(IRModel):
    """A behavior fact derived from operations and semantic context."""

    kind: EffectKind
    span: SourceSpan
    symbol_qualified_name: str
    target_name: str | None = None
    target_qualified_name: str | None = None


class SymbolIR(IRModel):
    """A language-agnostic code symbol."""

    name: str
    qualified_name: str
    kind: SymbolKind
    span: SourceSpan
    language: Language = Language.PYTHON
    roles: frozenset[SymbolRole] = frozenset()
    signature: SignatureIR = Field(default_factory=SignatureIR)
    body: tuple[OperationIR, ...] = ()
    references: tuple[ReferenceIR, ...] = ()
    owner_qualified_name: str | None = None
    owner_id: str | None = None
    module_id: str | None = None
    base_names: tuple[str, ...] = ()
    sloc: int = 0
    cyc_complexity: int = 1
    cog_complexity: int = 0
    max_nesting: int = 0

    @property
    def id(self) -> str:
        """Return snapshot-local declaration identity, independent of its name."""
        return self.span.entity_id(self.kind)

    @property
    def file_id(self) -> str:
        """Return physical-file membership."""
        return self.span.file_id

    @property
    def file(self) -> Path:
        """Return the source file for this symbol."""
        return self.span.file

    @property
    def start_line(self) -> int:
        """Return the 1-indexed starting line."""
        return self.span.start_line

    @property
    def end_line(self) -> int:
        """Return the 1-indexed ending line."""
        return self.span.end_line

    @property
    def return_operations(self) -> tuple[OperationIR, ...]:
        """Return normalized `return` operations in this symbol."""
        return tuple(
            operation
            for operation in self.body
            if operation.kind is OperationKind.RETURN
        )

    def is_high_cc(self) -> bool:
        """Return True if the symbol exceeds the cyclomatic cutoff."""
        return self.cyc_complexity > HIGH_COMPLEXITY_THRESHOLD

    def is_high_cog(self) -> bool:
        """Return True if the symbol exceeds the cognitive cutoff."""
        return self.cog_complexity > HIGH_COMPLEXITY_THRESHOLD


type CoverageStatus = Literal["complete", "partial", "unavailable"]


class FactCoverage(IRModel):
    """Parser-declared support for documented fact subsets, not fact counts."""

    entities: CoverageStatus = "unavailable"
    signatures: CoverageStatus = "unavailable"
    complexity: CoverageStatus = "unavailable"
    sloc: CoverageStatus = "unavailable"
    imports: CoverageStatus = "unavailable"
    references: CoverageStatus = "unavailable"
    operations: CoverageStatus = "unavailable"
    roles: CoverageStatus = "unavailable"
    effects: CoverageStatus = "unavailable"


class ModuleIR(IRModel):
    """A parsed source module with generic code facts."""

    language: Language
    file: Path
    module_name: str
    span: SourceSpan
    coverage: FactCoverage = Field(default_factory=FactCoverage)
    imports: tuple[ImportIR, ...] = ()
    symbols: tuple[SymbolIR, ...] = ()
    operations: tuple[OperationIR, ...] = ()
    references: tuple[ReferenceIR, ...] = ()
    sloc_lines: frozenset[int] = frozenset()

    @property
    def id(self) -> str:
        """Return logical-module identity, distinct from physical-file identity."""
        return self.span.entity_id(SymbolKind.MODULE)

    @property
    def file_id(self) -> str:
        """Return physical-file membership."""
        return self.span.file_id

    @property
    def kind(self) -> SymbolKind:
        """Return the logical entity kind."""
        return SymbolKind.MODULE

    @property
    def name(self) -> str:
        """Return the parser's descriptive module name."""
        return self.module_name

    @property
    def qualified_name(self) -> str:
        """Return searchable module metadata, not unique identity."""
        return self.module_name

    @model_validator(mode="after")
    def _attach_membership(self) -> Self:
        """Bind declarations to this module without inferring unknown owners."""
        symbols = tuple(
            symbol.model_copy(
                update={
                    "module_id": self.id,
                    "owner_id": (
                        self.id
                        if symbol.owner_qualified_name is None
                        else symbol.owner_id
                    ),
                }
            )
            for symbol in self.symbols
        )
        object.__setattr__(self, "symbols", symbols)
        return self


type ModuleLookup = Mapping[str, ModuleIR]
type ModulesByFile = Mapping[Path, ModuleIR]
type PhysicalFiles = Mapping[str, Path]
type SymbolLookup = Mapping[str, SymbolIR]
type SymbolEffects = Mapping[str, tuple[EffectIR, ...]]


class ProjectIR(IRModel):
    """Retained module inventory with derived, read-only lookup indexes."""

    modules: tuple[ModuleIR, ...] = ()
    effects_by_symbol: SymbolEffects = Field(
        default_factory=lambda: MappingProxyType({}),
    )

    @field_validator("effects_by_symbol")
    @classmethod
    def _freeze_effects(cls, effects: SymbolEffects) -> SymbolEffects:
        """Own a read-only copy of derived effects."""
        return MappingProxyType(dict(effects))

    _modules_by_id: ModuleLookup = PrivateAttr()
    _modules_by_file: ModulesByFile = PrivateAttr()
    _files_by_id: PhysicalFiles = PrivateAttr()
    _symbols_by_id: SymbolLookup = PrivateAttr()
    _symbols_by_qualified_name: SymbolLookup = PrivateAttr()

    def model_post_init(self, _context: object) -> None:
        """Derive privately owned lookup views from the sole module inventory."""
        symbols = tuple(
            symbol for module in self.modules for symbol in module.symbols
        )
        self._modules_by_id = MappingProxyType(
            {module.id: module for module in self.modules}
        )
        self._modules_by_file = MappingProxyType(
            {module.file: module for module in self.modules}
        )
        self._files_by_id = MappingProxyType(
            {module.file_id: module.file for module in self.modules}
        )
        self._symbols_by_id = MappingProxyType(
            {symbol.id: symbol for symbol in symbols}
        )
        self._symbols_by_qualified_name = MappingProxyType(
            {symbol.qualified_name: symbol for symbol in symbols}
        )

    @property
    def modules_by_id(self) -> ModuleLookup:
        """Look up logical modules by identity."""
        return self._modules_by_id

    @property
    def modules_by_file(self) -> ModulesByFile:
        """Look up the one logical module per successfully parsed file."""
        return self._modules_by_file

    @property
    def files_by_id(self) -> PhysicalFiles:
        """Look up physical source paths independently of logical-module IDs."""
        return self._files_by_id

    @property
    def symbols_by_id(self) -> SymbolLookup:
        """Look up every retained declaration, including repeated names."""
        return self._symbols_by_id

    @property
    def symbols_by_qualified_name(self) -> SymbolLookup:
        """Provide the existing last-declaration name selection for semantic queries."""
        return self._symbols_by_qualified_name


class RuleFinding(IRModel):
    """A structural rule finding."""

    rule_id: str
    severity: Severity
    message: str
    span: SourceSpan
    subject_name: str
    subject_qualified_name: str
    subject_kind: SymbolKind

    @property
    def file(self) -> Path:
        """Return the source file for this finding."""
        return self.span.file

    @property
    def start_line(self) -> int:
        """Return the 1-indexed starting line."""
        return self.span.start_line

    @property
    def end_line(self) -> int:
        """Return the 1-indexed ending line."""
        return self.span.end_line
