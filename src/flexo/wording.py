"""A shape's words in a weight, a slant, a size and an alignment of their own.

A figure's words are all set alike, as its theme has them. A shape says otherwise for
the whole of its label, in its properties:

    - {id: note, kind: text, label: Trained once, properties: {align: left, size: 6pt}}
    - {id: head, label: Encoder, properties: {bold: true}}
    - {id: gene, kind: text, label: lacZ, properties: {italic: true}}

``bold`` and ``italic`` are of every word (maths keeps its own letters); ``size`` is a
length (``6pt``; a bare number is points); ``align`` is ``left``, ``center`` (as ever) or
``right``, of the label's lines in the shape.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from flexo.ir.semantic import NodeSpec, TextRun
from flexo.style import TypographyStyle
from flexo.units import Length

ALIGNS = {"left": "start", "center": "middle", "centre": "middle", "right": "end"}
BOLD = 700


def worded(node: NodeSpec) -> NodeSpec:
    """``node`` with its words in the weight and slant it asks for (``bold``, ``italic``)."""

    bold, italic = bool(node.property("bold", False)), bool(node.property("italic", False))
    if not (bold or italic) or not node.label:
        return node
    return replace(
        node,
        label=tuple(
            run if run.math else _set(run, bold, italic)
            for run in node.label
        ),
    )


def _set(run: TextRun, bold: bool, italic: bool) -> TextRun:
    weight = max(run.weight, BOLD) if bold else run.weight
    return replace(run, weight=weight, italic=run.italic or italic)


def size_of(node: NodeSpec) -> Length | None:
    """The size the node's words are set at, where it says: ``6pt``, or a number of points."""

    written = node.property("size")
    if written in (None, "", False):
        return None
    try:
        number = isinstance(written, int | float)
        size = Length(float(written)) if number else Length.parse(str(written))
    except (ValueError, TypeError):
        return None
    return size if size.points > 0 else None


def typography_of(node: NodeSpec, typography: TypographyStyle) -> TypographyStyle:
    """``typography`` at the node's own size, where it has one: else itself."""

    size = size_of(node)
    return typography if size is None else _sized(typography, size.points)


@lru_cache(maxsize=64)
def _sized(typography: TypographyStyle, points: float) -> TypographyStyle:
    return replace(
        typography,
        size=Length(points),
        minimum_size=Length(min(points, typography.minimum_size.points)),
    )


def anchor_of(node: NodeSpec) -> str:
    """Where the node's lines are anchored: ``start``, ``middle`` (as ever) or ``end``."""

    return ALIGNS.get(str(node.property("align", "center")).strip().lower(), "middle")
