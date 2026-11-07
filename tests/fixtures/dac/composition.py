"""Known attribute volume: Base 1, Child 7, Nested 1, all others 0."""

from typing import ClassVar, Optional, Self
from library import External


class Part:
    pass


class Box:
    pass


Alias = 1


class Base:
    inherited: Part


class Child(Base):
    first: Part
    second: Part
    ancestor: Base
    self_type: Self
    quoted: "Child"
    boxed: Box[Part]
    primitive: int
    nonclass: Alias
    collection: list[Part]
    union: Part | None
    optional: Optional[Part]
    wrapped: ClassVar[Part]
    unknown: Missing
    external: External
    inferred = Part()

    def __init__(self, parameter: Part):
        local: Part = parameter
        self.instance: Part = parameter
        self.instance: Part = parameter

    class Nested:
        value: Part


class EmptyChild(Base):
    pass
