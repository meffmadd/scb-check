"""Destinations with same-module, recursive, and ownerless calls."""


def destination():
    return 1


def recursive(depth):
    return recursive(depth - 1) if depth else 0


def dormant():
    pass


class Base:
    def work(self):
        return 1


class Override(Base):
    def work(self):
        return 2


def local():
    destination()
    destination()


destination()


class Initialization:
    value = destination()
