"""Cross-module callers with a nested function and unresolved incoming use."""

from math import sqrt

from callers_targets import Base
from callers_targets import destination


def first():
    destination()
    destination()

    def nested():
        return destination()

    return nested()


def second(value: Base):
    destination()
    value.work()


def uncertain(value, callback):
    value.work()
    callback()
    sqrt(4)
