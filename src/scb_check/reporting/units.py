"""Measurement units declared by metrics, separate from numerical results."""

from typing import Literal

type Unit = Literal[
    "fraction",
    "files",
    "lines",
    "findings",
    "functions",
    "mass",
    "trees",
    "nodes",
]
