"""Initial component grammar and intrinsic sizing rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from flexo.artwork import node_artwork
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Rect, Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec
from flexo.style import LayoutStyle

TRANSPARENT_KINDS = frozenset({"spacer", "junction"})
"""Node kinds nothing has to keep clear of: they paint no ink a route can spoil.

Routing, port adaptation, and lint all read this one set, so a kind treated as an
obstacle in only some of those passes cannot happen. A spacer holds a lane open
and a junction *is* connector ink, which is why neither blocks a run -- but a
caption is words on the page, and words are not transparent (see
``CAPTION_KINDS``).
"""

CAPTION_KINDS = frozenset({"label"})
"""Kinds that paint text and nothing else.

A caption has no boundary to hug and no fill to hide behind, so it takes a couple
of points of air rather than a component's full routing clearance. It is still
ink: a run through the middle of "Attended value" is a defect, not a shortcut,
which is what makes a caption an obstacle at all.
"""

TRANSPARENT_ROLES = frozenset({"layout", "canvas"})
"""Group roles that draw no boundary and therefore never block a route.

The container counterpart of ``TRANSPARENT_KINDS``, and read the same way by
every pass that asks what is in the way.
"""


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    kind: str
    minimum_size: Size
    ports: tuple[PortSpec, ...]
    motif_height: float = 0.0
    """Least room this kind's motif needs *under* its label, if it draws one.

    Only the kinds in ``MOTIF_LABEL_KINDS`` have a motif that sits below the
    words rather than behind them, and only they read this. It is what stops a
    two-line caption from being sized as though the illustration underneath it
    were free.
    """


MOTIF_LABEL_KINDS = frozenset(
    {
        "attention",
        "channels",
        "concat",
        "feature-strip",
        "graph",
        "image",
        "inset",
        "matrix",
        "sequence",
    }
)
"""Kinds whose label owns a band at the top and whose motif draws below it.

The alternative -- a label centred in the box with the motif drawn wherever it
happens to fit -- is how "Edge rectangles" came to sit on top of its own
molecule. Sizing (``intrinsic_node_size``), the label baseline, and every motif
that paints read the same two functions below, so the band a label is given and
the area a motif is allowed are the same band and the same area by construction.

``image`` belongs here for the same reason (R27), and its "motif" is the author's
own artwork: a label centred over a positional-encoding glyph is a caption
printed across the drawing it names. An *unlabelled* image asks for no band and
therefore gets none -- its bounds stay exactly its artwork, which is the whole
promise of the kind.
"""


def _default_port(
    name: str,
    side: Side,
    offset: float = 0.5,
    *,
    adaptive: bool = False,
) -> PortSpec:
    """One port of the component grammar, whose side the author may not have meant.

    Every default port declares a side because geometry needs one, and the
    grammar can only guess the common case (values enter west and leave east).
    Marking them ``auto_side`` is what lets a figure that reads downward get
    north and south ports without the author restating the whole port table.
    """

    return PortSpec(name, side, offset, adaptive, auto_side=True)


_INPUT = _default_port("input", Side.WEST, adaptive=True)
_OUTPUT = _default_port("output", Side.EAST, adaptive=True)
_STANDARD = (_INPUT, _OUTPUT)
_QKV = (
    _default_port("q", Side.WEST, 0.24, adaptive=True),
    _default_port("k", Side.WEST, 0.5, adaptive=True),
    _default_port("v", Side.WEST, 0.76, adaptive=True),
    _OUTPUT,
)
_MULTI_OUTPUT = (
    _INPUT,
    _default_port("output", Side.EAST, 0.3, adaptive=True),
    _default_port("branch", Side.EAST, 0.7, adaptive=True),
    _default_port("residual", Side.WEST, 0.8),
)
_CONCAT = (
    _default_port("input1", Side.WEST, 0.3, adaptive=True),
    _default_port("input2", Side.WEST, 0.7, adaptive=True),
    _OUTPUT,
)
_RESIDUAL_TARGET = (
    _INPUT,
    _default_port("skip", Side.WEST, 0.8, adaptive=True),
    _OUTPUT,
    _default_port("branch", Side.EAST, 0.8, adaptive=True),
)
"""A component that adds a bypassed value to a sublayer's output (R27).

Such a component sits on *two* wires, not one, and the second is not a copy of
the first: ``input`` carries what the sublayer computed and ``skip`` carries what
went round it. One defaulted ``input`` for both is what put two arrowheads on one
point in the first Transformer figure authored with Flexo -- two runs a hair
apart, each with a hook where the router pulled it off its twin, and a
``routing.track.separation`` error for the pair.

``branch`` is the same story read forwards. The value leaving one residual block
feeds the next sublayer *and* bypasses it, so two runs leave here too;
``branch`` is the second departure, named as ``feature-strip`` and ``junction``
already name theirs. A figure that taps it instead of doubling up on ``output``
comes out with one arrow per wire, which is what the reference Transformer
figure draws.

All four are auto-sided, so a tower that reads upward gets them on the edges its
ink actually uses without a port table.
"""
_VECTOR_PORTS = (
    PortSpec("input", Side.WEST),
    PortSpec("output", Side.EAST),
    PortSpec("north", Side.NORTH),
    PortSpec("south", Side.SOUTH),
)
"""One fixed centre port per side (R18/R19).

A vector is only a couple of cells wide, so an adaptive port would slide off the
middle cell for a gain of a pt or two. Keeping all four ports pinned to the side
centres makes the *counterpart* port adapt instead, which is what puts an arrow
on the middle cell.

None of the four is auto-sided: a component that offers every side has already
handed the choice to the author, who makes it by naming ``north`` rather than
``south``. Moving those ports would move the very thing their names promise.
"""

_IMAGE_PORTS = _VECTOR_PORTS
"""Author artwork wires like any other node: one fixed centre port per side.

An adaptive port slides along its edge to meet its counterpart, which is a good
trade when the compiler drew the body and knows where its ink is. It does not
know that about an illustration the author drew, so an image pins all four side
centres and lets the counterpart adapt instead.
"""

_DEFAULT_CELLS = 3
_DEFAULT_COLUMNS = 1

INSET_BOND = (13.0, 10.0)
"""Horizontal and vertical reach of one bond in the scientific-inset molecule."""

INSET_ATOM = (4.0, 3.2)
"""Radius of the inset molecule's leading atom and of its other two."""

INSET_CORE = 4.5
"""Radius of the inset molecule's central atom."""

INSET_INK = Rect(
    -(INSET_BOND[0] * 0.8660254037844387 + INSET_ATOM[1]),
    -(INSET_BOND[1] + INSET_ATOM[0]),
    2.0 * (INSET_BOND[0] * 0.8660254037844387 + INSET_ATOM[1]),
    INSET_BOND[1] + INSET_ATOM[0] + INSET_BOND[1] / 2.0 + INSET_ATOM[1],
)
"""The molecule's ink, measured from its central atom.

Its two lower bonds leave at 30 degrees, so they reach ``cos(30)`` of the
horizontal bond length sideways and half the vertical one down. Sizing needs this
box to know how tall an inset has to be; painting needs it to scale the drawing
into the room an inset actually has. One constant, so they cannot disagree.
"""

GRAPH_INK_HEIGHT = 20.0
"""Vertical extent of the graph motif's ink, node radii included.

The graph spreads its nodes across whatever width it is given but keeps this
height, so a tall box gets a graph centred in it rather than a stretched one.
"""


@dataclass(frozen=True, slots=True)
class VectorGrid:
    """The cell layout of one ``vector`` glyph, shared by measurement and paint.

    Measurement asks for the grid a node *wants* (square cells at the style
    token); rendering asks for the grid that fits the bounds the layout handed
    back, so an authored ``width``/``height`` stretches the cells instead of
    letting the ink drift out of the component.
    """

    cells: int
    columns: int
    cell_width: float
    cell_height: float
    row_gap: float
    column_gap: float

    @property
    def size(self) -> Size:
        return Size(
            self.columns * self.cell_width + (self.columns - 1) * self.column_gap,
            self.cells * self.cell_height + (self.cells - 1) * self.row_gap,
        )

    def cell_bounds(self, bounds: Rect, column: int, row: int) -> Rect:
        return Rect(
            bounds.x + column * (self.cell_width + self.column_gap),
            bounds.y + row * (self.cell_height + self.row_gap),
            self.cell_width,
            self.cell_height,
        )


def vector_grid(
    node: NodeSpec,
    style: LayoutStyle,
    *,
    bounds: Rect | None = None,
) -> VectorGrid:
    cells = max(1, int(node.property("cells", _DEFAULT_CELLS) or _DEFAULT_CELLS))
    columns = max(1, int(node.property("columns", _DEFAULT_COLUMNS) or _DEFAULT_COLUMNS))
    row_gap = style.vector_cell_gap.points
    column_gap = style.vector_column_gap.points
    side = style.vector_cell.points
    cell_width = side if bounds is None else (bounds.width - (columns - 1) * column_gap) / columns
    cell_height = side if bounds is None else (bounds.height - (cells - 1) * row_gap) / cells
    return VectorGrid(
        cells,
        columns,
        max(0.0, cell_width),
        max(0.0, cell_height),
        row_gap,
        column_gap,
    )


COMPONENTS: dict[str, ComponentDefinition] = {
    definition.kind: definition
    for definition in (
        ComponentDefinition("block", Size(44.0, 28.0), _STANDARD),
        ComponentDefinition("mlp", Size(48.0, 32.0), _STANDARD),
        ComponentDefinition("cnn", Size(48.0, 32.0), _STANDARD),
        ComponentDefinition("add-norm", Size(50.0, 34.0), _RESIDUAL_TARGET),
        ComponentDefinition("attention", Size(60.0, 58.0), _QKV, motif_height=22.0),
        ComponentDefinition("concat", Size(32.0, 42.0), _CONCAT, motif_height=8.0),
        ComponentDefinition("channels", Size(22.0, 34.0), _STANDARD),
        ComponentDefinition("feature-strip", Size(58.0, 25.0), _MULTI_OUTPUT, motif_height=6.0),
        ComponentDefinition("tensor", Size(54.0, 26.0), _STANDARD),
        ComponentDefinition("matrix", Size(50.0, 48.0), _STANDARD, motif_height=22.0),
        ComponentDefinition("sequence", Size(66.0, 26.0), _STANDARD, motif_height=6.0),
        ComponentDefinition(
            "prediction",
            Size(58.0, 34.0),
            (_INPUT, _default_port("residual", Side.SOUTH), _OUTPUT),
        ),
        ComponentDefinition("loss", Size(44.0, 32.0), (_INPUT,)),
        ComponentDefinition("junction", Size(8.0, 8.0), _MULTI_OUTPUT),
        ComponentDefinition("graph", Size(70.0, 62.0), _STANDARD, motif_height=GRAPH_INK_HEIGHT),
        ComponentDefinition("inset", Size(82.0, 60.0), _STANDARD, motif_height=INSET_INK.height),
        # A vector's size is exactly its cell grid, so it comes from the style
        # tokens through vector_grid() rather than from a minimum here.
        ComponentDefinition("vector", Size(0.0, 0.0), _VECTOR_PORTS),
        # An image is exactly as big as the artwork it carries, or as big as the
        # author asked; a minimum here would pad a drawing away from its size.
        ComponentDefinition("image", Size(0.0, 0.0), _IMAGE_PORTS),
        ComponentDefinition("label", Size(0.0, 0.0), ()),
        ComponentDefinition("spacer", Size(0.0, 0.0), ()),
    )
}


def component_names() -> tuple[str, ...]:
    return tuple(COMPONENTS)


def component_port_offsets(kind: str, names: Sequence[str]) -> tuple[float, ...]:
    """The offsets the component grammar gives ``kind``'s ``names`` ports.

    The grammar is the single place that knows an attention block reads its query
    at 0.24 of its width and its value at 0.76. A composite that has to put
    something *under* those ports asks here rather than restating the fractions,
    so moving a port in ``COMPONENTS`` moves whatever the composite aligned to it.
    """

    offsets = {port.name: port.offset for port in COMPONENTS[kind].ports}
    missing = [name for name in names if name not in offsets]
    if missing:
        raise ValueError(
            f'component "{kind}" has no port(s) {", ".join(missing)}; '
            f"its ports are {', '.join(offsets)}"
        )
    return tuple(offsets[name] for name in names)


def attachment_lane_tracks(offsets: Sequence[float], width: float) -> tuple[float, ...]:
    """Grid tracks that centre one child under each of ``offsets`` of ``width``.

    Returns ``2n + 1`` widths for ``n`` offsets -- a pad, then a lane and a pad
    for every offset -- which sum to exactly ``width``. Reserved as the column
    widths of a one-row grid that wide, they put each lane's centre on its
    offset, so a glyph centred in its lane is centred under the port it feeds and
    the connector between them is a plain vertical. That is the arithmetic a
    figure used to do by hand as a magic inter-glyph gap, and it is arithmetic
    only this side of the pipeline can do: the offsets belong to the component
    grammar and the width is the author's.

    Every lane is the same width, and that width is the widest one that keeps the
    lanes disjoint and inside the box -- half the first offset's reach, half the
    last one's, and the closest spacing between neighbours. Wider would overlap a
    neighbour; narrower would waste room a caption could have used.
    """

    if not offsets:
        raise ValueError("attachment lanes need at least one offset")
    if width <= 0.0:
        raise ValueError(f"attachment lanes need a positive width, not {width}")
    if any(second <= first for first, second in pairwise(offsets)):
        raise ValueError(f"attachment lane offsets must ascend, not {tuple(offsets)}")
    centres = tuple(offset * width for offset in offsets)
    lane = min(
        2.0 * centres[0],
        2.0 * (width - centres[-1]),
        *(second - first for first, second in pairwise(centres)),
    )
    if lane <= 0.0:
        raise ValueError(
            f"offsets {tuple(offsets)} leave no room for a lane in {width:.1f} pt"
        )
    tracks = [centres[0] - lane / 2.0]
    for index, centre in enumerate(centres):
        tracks.append(lane)
        following = width if index + 1 == len(centres) else centres[index + 1] - lane / 2.0
        tracks.append(following - (centre + lane / 2.0))
    return tuple(tracks)


def motif_enabled(spec: NodeSpec) -> bool:
    """Whether ``spec`` draws its decorative motif.

    A motif is ornament -- the MLP's three dots, a matrix's cell grid -- so
    ``motif=False`` suppresses it and changes nothing else about the component:
    same size, same body, same ports.
    """

    return bool(spec.property("motif", True))


def route_clearance(spec: NodeSpec, style: LayoutStyle) -> float:
    """How much air a route has to leave around ``spec``.

    A body wants the full routing clearance: a run any closer reads as touching
    the box. A caption wants a couple of points -- enough that the arrow does not
    graze the letters, little enough that a caption never elbows a route out of a
    corridor a component would have let through.
    """

    if spec.kind in CAPTION_KINDS:
        return style.caption_clearance.points
    return style.route_clearance.points


def label_band_height(kind: str, label: TextMetrics, style: LayoutStyle) -> float:
    """Height of the top band a motif-label component reserves for its words.

    Zero for every other kind, and zero for a component with nothing written on
    it, so an unlabelled inset hands its whole interior to the illustration.
    """

    if kind not in MOTIF_LABEL_KINDS or not label.lines:
        return 0.0
    return style.padding_y.points + label.height


def motif_area(kind: str, bounds: Rect, label: TextMetrics, style: LayoutStyle) -> Rect:
    """The interior a motif may paint in: below the label band, inside the padding.

    A caption and the drawing it names are not allowed to negotiate for the same
    points. The band comes off the top, ``motif_label_gap`` of air comes off after
    it, and what is left is the motif's -- which is why an authored height too
    small for both makes the drawing smaller instead of making it collide.
    """

    band = label_band_height(kind, label, style)
    top = bounds.y + (band + style.motif_label_gap.points if band else style.padding_y.points)
    bottom = bounds.bottom - style.padding_y.points
    return Rect(
        bounds.x + style.padding_x.points,
        top,
        max(0.0, bounds.width - 2.0 * style.padding_x.points),
        max(0.0, bottom - top),
    )


def normalize_node(node: NodeSpec) -> NodeSpec:
    if node.ports or node.kind not in COMPONENTS:
        return node
    return replace(node, ports=COMPONENTS[node.kind].ports)


def image_size(node: NodeSpec, label: TextMetrics, style: LayoutStyle) -> Size:
    """The bounds of an ``image``: its artwork, its label band, or the author's box.

    One authored extent is enough. Artwork arrives with an aspect ratio, and a
    figure that scales a molecule icon to a column width should not have to
    restate the height that ratio already fixes -- so ``width`` alone scales the
    height, ``height`` alone scales the width, and giving both is the deliberate
    act of boxing the artwork, which then letterboxes inside those bounds rather
    than distorting.

    A label is *not* part of the artwork, so it takes its own band off the top
    (``label_band_height`` and ``motif_area``, the same two functions every other
    motif-label kind reads) and the drawing gets what is left. Which is why an
    authored extent shrinks the drawing rather than the words: ``height`` names
    the box, and the caption's line is the one thing in it whose size the author
    did not choose. An image with no label reserves nothing and comes out exactly
    as large as the file it carries.
    """

    artwork = node_artwork(node)
    band = label_band_height(node.kind, label, style)
    chrome = (
        Size(
            2.0 * style.padding_x.points,
            band + style.motif_label_gap.points + style.padding_y.points,
        )
        if band
        else Size(0.0, 0.0)
    )
    least_width = label.width + 2.0 * style.padding_x.points if band else 0.0
    width = style.resolve_extent(node.width).points if node.width is not None else None
    height = style.resolve_extent(node.height).points if node.height is not None else None
    if width is not None and height is not None:
        return Size(width, height)
    aspect = artwork.aspect
    if aspect is None:
        raise FlexoError(
            Diagnostic(
                "image.size.unknown",
                f"The artwork declares no size, so this image needs one. "
                f"Source: {artwork.path}.",
                entity_id=node.id,
                hint="Give width and height, or export the artwork with a viewBox.",
            )
        )
    if width is not None:
        drawn = max(0.0, width - chrome.width)
        return Size(width, drawn / aspect + chrome.height)
    if height is not None:
        drawn = max(0.0, height - chrome.height)
        return Size(max(drawn * aspect + chrome.width, least_width), height)
    return Size(
        max((artwork.width or 0.0) + chrome.width, least_width),
        (artwork.height or 0.0) + chrome.height,
    )


def intrinsic_node_size(
    node: NodeSpec,
    label: TextMetrics,
    style: LayoutStyle,
) -> Size:
    definition = COMPONENTS[node.kind]
    if node.kind == "label":
        natural = Size(label.width, label.height)
    elif node.kind == "spacer":
        natural = Size(0.0, 0.0)
    elif node.kind == "vector":
        # Exactly the cell grid: a vector carries no inline label, so nothing
        # here may pad it. Its label is a sibling node (see GroupBuilder.vector).
        natural = vector_grid(node, style).size
    elif node.kind == "image":
        # Artwork has a size of its own, and one authored extent implies the
        # other, so image sizing answers on its own rather than through the
        # declared-or-natural tail below.
        return image_size(node, label, style)
    else:
        # A motif-label kind stacks its band, its gap and its motif; every other
        # kind centres its words, so the label alone sets the height it needs.
        stacked = (
            label_band_height(node.kind, label, style)
            + style.motif_label_gap.points
            + definition.motif_height
            + style.padding_y.points
            if node.kind in MOTIF_LABEL_KINDS and label.lines
            else label.height + 2.0 * style.padding_y.points
        )
        natural = Size(
            max(
                definition.minimum_size.width,
                label.width + 2.0 * style.padding_x.points,
            ),
            max(definition.minimum_size.height, stacked),
        )
    width = style.resolve_extent(node.width).points if node.width is not None else natural.width
    height = style.resolve_extent(node.height).points if node.height is not None else natural.height
    return Size(width, height)
