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

import functools
import itertools
import math
from dataclasses import dataclass, replace

from flexo.geometry import Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, TextRun
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer
from flexo.units import pt

DRAWN_KINDS = frozenset(
    {"construct", "plasmid", "protein", "tree", "wellplate", "timeline", "structure"}
)


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
    images: tuple[tuple[str, float, float, float, float], ...] = ()
    """Boxes (id, x, y, width, height) a picture fills with an image drawn at render
    time -- a molecule, drawn by mol-sketch in the figure's colours."""


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


def check_port_id(node: NodeSpec, identifier: str, where: str, taken: set[str]) -> str:
    """``identifier`` if it can name a port of ``node``; a diagnostic saying why not otherwise.

    A drawn component's parts, features, and events with an ``id`` become its
    ports: each id has to be one a port can take, not ``input`` or ``output``
    (the component's own ends), and not another part's. ``taken`` collects them.
    """

    from flexo.diagnostics import Diagnostic, FlexoError
    from flexo.ir.semantic import ID_PATTERN

    if not ID_PATTERN.fullmatch(identifier) or identifier in {"input", "output"}:
        reason = (
            "is the component's own end"
            if identifier in {"input", "output"}
            else ("is not a usable id")
        )
        raise FlexoError(
            Diagnostic(
                f"{node.kind}.id",
                f'{where}: "{identifier}" {reason}.',
                entity_id=node.id,
                hint="Ids start with a letter and use letters, digits, '.', '_' and '-';"
                " input and output are taken.",
            )
        )
    if identifier in taken:
        raise FlexoError(
            Diagnostic(
                f"{node.kind}.id",
                f'{where}: "{identifier}" names another part already.',
                entity_id=node.id,
            )
        )
    taken.add(identifier)
    return identifier


@dataclass(slots=True)
class Name:
    """Words to set over one point of a drawing, pushed apart from their neighbours."""

    key: str
    runs: tuple[TextRun, ...]
    metrics: TextMetrics
    want: float
    """The x the words would centre on, left alone."""
    x: float = 0.0
    """The x they centre on, spread."""
    size: float | None = None
    """How wide a place it takes, when not its words' width (a lollipop's head)."""

    @property
    def width(self) -> float:
        return self.size if self.size is not None else self.metrics.width


def spread(
    names: list[Name], gap: float, low: float | None = None, high: float | None = None
) -> None:
    """Centre each name as near the x it wants as its neighbours allow, ``gap`` apart,
    within ``low`` and ``high`` when given. ``names`` ends sorted by the x it wants."""

    names.sort(key=lambda item: item.want)
    for item in names:
        item.x = item.want
    for _ in range(6):
        for before, after in itertools.pairwise(names):
            need = (before.width + after.width) / 2.0 + gap
            if after.x - before.x < need:
                push = (need - (after.x - before.x)) / 2.0
                before.x -= push
                after.x += push
        if low is not None and high is not None:
            for item in names:
                half = item.width / 2.0
                item.x = min(max(item.x, low + half), high - half)
    # A last sweep left to right, so what the bounds pushed back never overlaps.
    for before, after in itertools.pairwise(names):
        need = (before.width + after.width) / 2.0 + gap
        after.x = max(after.x, before.x + need)


def circle_path(x: float, y: float, r: float) -> str:
    """A circle as a path of two half arcs (an arc cannot end where it starts)."""

    return path("M", x - r, y, "A", r, r, 0, 1, 1, x + r, y, "A", r, r, 0, 1, 1, x - r, y, "Z")


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
    """What a drawn component draws, laid out by the module for its kind.

    Measurement sizes the component from its picture and rendering draws the same
    picture, so it is laid out once per node and style (both are frozen values),
    not once for each.
    """

    try:
        return _picture(node, style)
    except TypeError:  # an unhashable value somewhere in the style: lay it out afresh
        return _lay_out(node, style)


@functools.lru_cache(maxsize=256)
def _picture(node: NodeSpec, style: LayoutStyle) -> Picture:
    return _lay_out(node, style)


def _lay_out(node: NodeSpec, style: LayoutStyle) -> Picture:
    if node.kind in {"construct", "plasmid"}:
        from flexo.genetics import genetic_drawing

        return genetic_drawing(node, style)
    if node.kind == "protein":
        from flexo.proteins import protein_drawing

        return protein_drawing(node, style)
    if node.kind == "tree":
        from flexo.phylogeny import tree_drawing

        return tree_drawing(node, style)
    if node.kind == "structure":
        from flexo.structures import structure_drawing

        return structure_drawing(node, style)
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
    if node.kind == "structure":
        from flexo.structures import structure_tones

        return structure_tones(node)
    return ()
