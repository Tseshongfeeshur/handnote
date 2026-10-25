"""Drawing elements produced by layout and consumed by the renderer.

Coordinates are pixels.  During layout `y` values live in "scroll space"
(one tall page); pagination shifts them into per-page coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Union


@dataclass
class Glyph:
    ch: str
    x: float
    y: float  # baseline
    size: float
    font: int
    pen: str
    line_id: int
    k: int  # baseline line index (scroll space), used for pagination


@dataclass
class Deco:
    kind: str  # single | double | strike
    x0: float
    x1: float
    y: float  # baseline of the decorated text
    size: float
    pen: str
    line_id: int
    k: int


@dataclass
class Brace:
    x: float  # x of the tip (left side)
    y0: float
    y1: float
    size: float
    pen: str


@dataclass
class VBar:
    x: float
    y0: float
    y1: float
    pen: str


@dataclass
class Tri:
    """Hand-drawn triangle mark (quotation).  `x` is its left edge, `y` the baseline of the text line."""

    x: float
    y: float
    size: float
    pen: str
    k: int
    filled: bool = False


@dataclass
class HRule:
    x0: float
    x1: float
    y: float
    pen: str
    k: int


@dataclass
class Dot:
    x: float
    y: float
    r: float
    pen: str
    k: int


Element = Union[Glyph, Deco, Brace, VBar, HRule, Dot, Tri]


@dataclass
class Page:
    index: int
    elements: List[Element] = field(default_factory=list)
