"""Components drawn from their own geometry: genetic designs, proteins, trees, plates.

Most of Flexo's components are a box and a label, sized by their words. These
are pictures of scientific things, each laid out by a module of its own from the
data the author wrote -- the parts of a construct, the domains of a protein, the
branches of a tree -- into outlines and words in the component's own
coordinates (a ``Picture``). Measurement sizes the component from that
picture, ``render_drawn`` paints it by role, and the rest of the pipeline treats
it as any other node: it sits in groups, is wired, and takes the theme.

This module holds what the pictures share and dispatches to the module that
draws each kind.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from flexo.geometry import Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, TextRun
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer
from flexo.units import pt

DRAWN_KINDS = frozenset({"construct", "plasmid", "protein", "tree", "wellplate", "timeline"})


# -- shapes and words ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shape:
    """One outline of a drawing, in the component's own coordinates.

    ``paint`` is ``"line"`` (stroked only), ``"body"`` (filled and outlined),
    ``"solid"`` (filled and outlined in the line colour), ``"hollow"`` (outlined over
    the page colour), ``"backbone"``, ``"tick"`` and ``"leader"`` (thin, muted), or
    ``"guide"`` (dotted); ``tone`` names the colour, or none for ink.
    """

    id: str
    d: str
    paint: str
    tone: str | None = None
    width: float = 1.0


@dataclass(frozen=True, slots=True)
class Words:
    """A label set at ``x``, its first baseline at ``y``, anchored start, middle, or end."""

    id: str
    runs: tuple[TextRun, ...]
    metrics: TextMetrics
    x: float
    y: float
    anchor: str = "middle"
    role: str = "ink"
    tone: str | None = None
    size: float | None = None
    weight: int | None = None


@dataclass(frozen=True, slots=True)
class Picture:
    """Everything a drawn component draws, and how big it is."""

    size: Size
    shapes: tuple[Shape, ...] = ()
    words: tuple[Words, ...] = ()
    ports: tuple[PortSpec, ...] = ()


def _f(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def path(*commands: object) -> str:
    return " ".join(_f(item) if isinstance(item, float | int) else str(item) for item in commands)


class Units:
    """The measures a drawing is made in: the label size ``u``, and the pen."""

    def __init__(self, style: LayoutStyle) -> None:
        self.style = style
        self.u = style.typography.size.points
        self.pen = style.stroke_width.points
        self.measurer = TextMeasurer(style.typography)
        small = replace(style.typography, size=pt(self.u * 0.78), minimum_size=pt(self.u * 0.6))
        self.small = TextMeasurer(small)
        self.small_size = self.u * 0.78

    def measure(
        self, runs: tuple[TextRun, ...], *, small: bool = False, weight: int | None = None
    ) -> TextMetrics:
        return (self.small if small else self.measurer).measure(runs, weight=weight)


def units(style: LayoutStyle) -> Units:
    return Units(style)


def nice_step(length: int) -> int:
    for step in (
        10,
        20,
        50,
        100,
        200,
        250,
        500,
        1000,
        2000,
        2500,
        5000,
        10000,
        20000,
        50000,
        100000,
    ):
        if length / step <= 8:
            return step
    return 10 ** int(math.log10(length))


def picture(node: NodeSpec, style: LayoutStyle) -> Picture:
    """What a drawn component draws, laid out by the module for its kind."""

    if node.kind in {"construct", "plasmid"}:
        from flexo.genetics import genetic_drawing

        return genetic_drawing(node, style)
    if node.kind == "protein":
        from flexo.proteins import protein_drawing

        return protein_drawing(node, style)
    if node.kind == "tree":
        from flexo.phylogeny import tree_drawing

        return tree_drawing(node, style)
    from flexo.bench import bench_drawing

    return bench_drawing(node, style)


def drawn_tones(node: NodeSpec) -> tuple[str, ...]:
    """The tones a drawn component paints with, in order, for the figure's tone map."""

    if node.kind in {"construct", "plasmid"}:
        from flexo.genetics import genetic_tones

        return genetic_tones(node)
    if node.kind == "protein":
        from flexo.proteins import protein_tones

        return protein_tones(node)
    if node.kind == "tree":
        from flexo.phylogeny import tree_tones

        return tree_tones(node)
    if node.kind in {"wellplate", "timeline"}:
        from flexo.bench import bench_tones

        return bench_tones(node)
    return ()
