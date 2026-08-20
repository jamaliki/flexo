"""Kind-specific component rendering using shallow native SVG primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.artwork import node_artwork
from flexo.components import (
    MOTIF_LABEL_KINDS,
    VectorGrid,
    motif_area,
    motif_enabled,
    vector_grid,
)
from flexo.ir.fitted import FittedNode
from flexo.render_common import (
    base_rect,
    paint_attributes,
    paint_override,
    render_runs,
    soft_shadow,
)
from flexo.render_scientific import render_scientific
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, number


def render_node(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> ET.Element:
    spec = node.measured.spec
    group = element(
        parent,
        "g",
        id=spec.id,
        data__flexo__entity="component",
        data__flexo__kind=spec.kind,
        data__flexo__role=spec.role,
    )
    if spec.kind not in {"label", "spacer"}:
        # Behind the body, so the box's own fill hides all but the ring.
        if spec.shadow:
            soft_shadow(group, spec.id, node.bounds, style.corner_radius.points, style, palette)
        _render_kind(group, node, style, palette)
    _render_label(group, node, style, palette)
    return group


def _render_kind(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    kind = node.measured.spec.kind
    if kind == "feature-strip":
        _feature_strip(parent, node, style, palette)
    elif kind == "sequence":
        _sequence(parent, node, style, palette)
    elif kind == "tensor":
        _tensor(parent, node, style, palette)
    elif kind == "junction":
        _junction(parent, node, style, palette)
    elif kind == "concat":
        _concat(parent, node, style, palette)
    elif kind == "channels":
        _channels(parent, node, style, palette)
    elif kind == "vector":
        _vector(parent, node, style, palette)
    elif kind == "image":
        _image(parent, node, style)
    elif kind in {"matrix", "attention", "graph", "inset"}:
        render_scientific(parent, node, style, palette)
    else:
        _block(parent, node, style, palette)


_STRIP_CELL_HEIGHT = 4.0
"""Height of one cell of a feature strip's motif, when its band has the room."""

_TOKEN_RADIUS = 1.6
"""Radius of one token dot of a sequence's motif, when its band has the room."""

_CONCAT_PITCH = 3.0
_CONCAT_BAR = 1.5
"""Row pitch and bar height of the concat motif's stack of tapering bars."""


def _block(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    spec = node.measured.spec
    kind = spec.kind
    fill_role = "warm-fill" if kind in {"prediction", "loss"} else "block-fill"
    stroke_role = "warm-stroke" if kind in {"prediction", "loss"} else "block-stroke"
    base_rect(parent, node, style, palette, fill_role=fill_role, stroke_role=stroke_role)
    if kind not in {"mlp", "cnn"} or not motif_enabled(spec):
        return
    motif = element(parent, "g", id=f"{spec.id}.motif")
    bounds = node.bounds
    y = bounds.bottom - 6.0
    if kind == "mlp":
        for index, radius in enumerate((1.2, 1.6, 1.2)):
            element(
                motif,
                "circle",
                cx=bounds.center.x + (index - 1) * 5.0,
                cy=y,
                r=radius,
                **paint_attributes(palette=palette, fill_role="block-stroke"),
            )
    else:
        element(
            motif,
            "path",
            d=f"M {number(bounds.center.x - 9)} {number(y)} l 4 -3 l 4 3 l 4 -3 l 4 3",
            **paint_attributes(
                palette=palette,
                stroke_role="block-stroke",
                stroke_width=style.stroke_width.points,
            ),
        )


def _feature_strip(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    base_rect(parent, node, style, palette, fill_role="accent-fill", stroke_role="accent-stroke")
    spec = node.measured.spec
    if not motif_enabled(spec):
        return
    area = motif_area(spec.kind, node.bounds, node.measured.label, style)
    cells = int(spec.property("cells", 6))
    motif = element(parent, "g", id=f"{spec.id}.cells")
    cell_width = area.width / cells
    height = min(_STRIP_CELL_HEIGHT, area.height)
    for index in range(cells):
        element(
            motif,
            "rect",
            x=area.x + index * cell_width,
            y=area.center.y - height / 2.0,
            width=max(1.0, cell_width - 1.2),
            height=height,
            rx=0.7,
            opacity=0.35 + 0.55 * (index + 1) / cells,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _sequence(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(
        parent,
        node,
        style,
        palette,
        fill_role="container-fill",
        stroke_role="container-stroke",
    )
    spec = node.measured.spec
    if not motif_enabled(spec):
        return
    area = motif_area(spec.kind, node.bounds, node.measured.label, style)
    motif = element(parent, "g", id=f"{spec.id}.tokens")
    count = int(spec.property("tokens", 7))
    spacing = min(7.0, area.width / max(1, count - 1))
    x0 = area.center.x - spacing * (count - 1) / 2.0
    for index in range(count):
        element(
            motif,
            "circle",
            cx=x0 + index * spacing,
            cy=area.center.y,
            r=min(_TOKEN_RADIUS, area.height / 2.0),
            opacity=0.45 + 0.5 * index / max(1, count - 1),
            **paint_attributes(palette=palette, fill_role="block-stroke"),
        )


def _tensor(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    bounds = node.bounds
    for index in reversed(range(3)):
        inset = index * 2.0
        element(
            parent,
            "rect",
            id=f"{node.measured.spec.id}.slice.{index}",
            x=bounds.x + inset,
            y=bounds.y + 2.0 * (2 - index),
            width=bounds.width - 4.0,
            height=bounds.height - 4.0,
            rx=style.corner_radius.points,
            opacity=0.45 + 0.2 * index,
            **paint_attributes(
                palette=palette,
                fill_role="block-fill",
                stroke_role="block-stroke",
                stroke_width=style.stroke_width.points,
            ),
        )


def _junction(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    element(
        parent,
        "circle",
        id=f"{node.measured.spec.id}.body",
        cx=node.bounds.center.x,
        cy=node.bounds.center.y,
        r=min(node.bounds.width, node.bounds.height) / 2.0,
        **paint_attributes(
            palette=palette,
            fill_role="connector",
            stroke_role="canvas",
            stroke_width=style.stroke_width.points,
        ),
    )


def _concat(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(
        parent,
        node,
        style,
        palette,
        fill_role="container-fill",
        stroke_role="block-stroke",
    )
    spec = node.measured.spec
    if not motif_enabled(spec):
        return
    area = motif_area(spec.kind, node.bounds, node.measured.label, style)
    motif = element(parent, "g", id=f"{spec.id}.motif")
    widths = (14.0, 10.0, 6.0)
    pitch = min(_CONCAT_PITCH, area.height / len(widths))
    top = area.center.y - (pitch * (len(widths) - 1) + _CONCAT_BAR) / 2.0
    for index, width in enumerate(widths):
        element(
            motif,
            "rect",
            x=area.center.x - width / 2.0,
            y=top + index * pitch,
            width=width,
            height=_CONCAT_BAR,
            rx=0.75,
            opacity=0.45 + index * 0.2,
            **paint_attributes(palette=palette, fill_role="block-stroke"),
        )


_CELL_STROKE_SCALE = 0.75
"""Vector cells take a lighter outline than a component body.

A cell is a few points across; the body stroke width would eat a tenth of it.
"""

_RAMP_LIGHTEST = 0.42
_RAMP_DARKEST = 1.0
"""Fill-opacity ends of a vector ramp.

The ramp is paint, not geometry: every cell of a stack names the same palette
role and differs only by ``fill-opacity``, so ``flexo retheme`` rewrites the
role and the ramp comes along. Strokes stay fully opaque, which is what keeps
the pale cells crisp instead of washed out.
"""


def _ramp_fill_opacity(index: int, count: int) -> float:
    if count < 2:
        return _RAMP_DARKEST
    return _RAMP_LIGHTEST + (_RAMP_DARKEST - _RAMP_LIGHTEST) * index / (count - 1)


def _preset_vector(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    grid: VectorGrid,
    encoded: str,
) -> None:
    """Paint a vector whose cells carry the author's own shades.

    The shades are literal colour, not roles, so no ``data-flexo-fill`` is
    emitted and ``flexo retheme`` leaves the cells as authored.
    """

    spec = node.measured.spec
    shades = tuple(tuple(column.split(",")) for column in encoded.split(";"))
    if len(shades) != grid.columns or any(len(column) != grid.cells for column in shades):
        raise ValueError(f'vector "{spec.id}" carries shades that do not match its grid')
    stack = element(parent, "g", id=f"{spec.id}.grid", data__flexo__ramp="preset")
    for column in range(grid.columns):
        for row in range(grid.cells):
            cell = grid.cell_bounds(node.bounds, column, row)
            element(
                stack,
                "rect",
                id=f"{spec.id}.cell.{column + 1}.{row + 1}",
                x=cell.x,
                y=cell.y,
                width=cell.width,
                height=cell.height,
                rx=style.vector_cell_radius.points,
                fill=shades[column][row],
                stroke=shades[column][row],
                stroke__width=style.stroke_width.points * _CELL_STROKE_SCALE,
            )


def _vector(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    spec = node.measured.spec
    grid = vector_grid(spec, style, bounds=node.bounds)
    encoded = spec.property("shades")
    if encoded is not None:
        _preset_vector(parent, node, style, grid, str(encoded))
        return
    ramp = str(spec.property("ramp", "ramp-node"))
    stack = element(parent, "g", id=f"{spec.id}.grid", data__flexo__ramp=ramp)
    for column in range(grid.columns):
        for row in range(grid.cells):
            cell = grid.cell_bounds(node.bounds, column, row)
            element(
                stack,
                "rect",
                id=f"{spec.id}.cell.{column + 1}.{row + 1}",
                x=cell.x,
                y=cell.y,
                width=cell.width,
                height=cell.height,
                rx=style.vector_cell_radius.points,
                fill__opacity=_ramp_fill_opacity(row, grid.cells),
                **paint_attributes(
                    palette=palette,
                    fill_role=ramp,
                    stroke_role=ramp,
                    stroke_width=style.stroke_width.points * _CELL_STROKE_SCALE,
                ),
            )


_ARTWORK_FIT = "xMidYMid meet"
"""How artwork sits in bounds that are not its own aspect ratio.

Letterboxed and centred, never stretched: an author who boxes a molecule icon
into a grid cell wants the cell filled to the extent the drawing allows, not a
drawing that lies about its proportions.
"""


def _image(parent: ET.Element, node: FittedNode, style: LayoutStyle) -> None:
    """Place the author's artwork at the node's bounds, exactly as drawn.

    A labelled image hands the top of those bounds to its caption and draws in
    what ``motif_area`` leaves, exactly as a matrix or an inset does: the words
    name the drawing, so they may not be printed across it. An unlabelled image
    has no band to give up and fills its bounds.

    An SVG source becomes a nested ``<svg>`` viewport carrying the source's own
    viewBox, so the artwork stays real vector content -- crisp at any zoom, and
    still made of ordinary objects an editor can open. A PNG becomes an
    ``<image>`` holding its own bytes. Either way the ink is embedded, not
    linked, so the editable and portable SVG are each self-contained.

    Nothing here names a palette role. Author artwork is author paint, and
    ``flexo retheme`` rewrites paint by role, so an embedded illustration comes
    through a retheme untouched -- the same convention preset vector cells and
    ``paint`` overrides follow.
    """

    spec = node.measured.spec
    bounds = (
        motif_area(spec.kind, node.bounds, node.measured.label, style)
        if node.measured.label.lines
        else node.bounds
    )
    artwork = node_artwork(spec)
    if artwork.format == "png":
        element(
            parent,
            "image",
            id=f"{spec.id}.artwork",
            x=bounds.x,
            y=bounds.y,
            width=bounds.width,
            height=bounds.height,
            preserveAspectRatio=_ARTWORK_FIT,
            href=artwork.data_uri,
        )
        return
    nested = ET.fromstring(artwork.markup)
    for name, value in (
        ("id", f"{spec.id}.artwork"),
        ("x", number(bounds.x)),
        ("y", number(bounds.y)),
        ("width", number(bounds.width)),
        ("height", number(bounds.height)),
        ("preserveAspectRatio", _ARTWORK_FIT),
    ):
        nested.set(name, value)
    parent.append(nested)


def _channels(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    bounds = node.bounds
    labels = str(node.measured.spec.property("labels", "K")).split(",")
    outputs = node.ports[1:]
    input_port = node.port("input")
    split_x = bounds.left + 4.0
    label_x = bounds.left + 10.0
    bar_left = bounds.right - 5.0
    motif = element(parent, "g", id=f"{node.measured.spec.id}.channels")
    path_commands = [
        f"M {number(bounds.left)} {number(input_port.position.y)} H {number(split_x)}"
    ]
    port_ys = (input_port.position.y, *(output.position.y for output in outputs))
    if min(port_ys) != max(port_ys):
        path_commands.append(
            f"M {number(split_x)} {number(min(port_ys))} V {number(max(port_ys))}"
        )
    for output in outputs:
        path_commands.append(
            f"M {number(split_x)} {number(output.position.y)} H {number(label_x - 2.0)}"
        )
    element(
        motif,
        "path",
        d=" ".join(path_commands),
        stroke__linecap="square",
        stroke__linejoin="miter",
        **paint_attributes(
            palette=palette,
            stroke_role="connector",
            stroke_width=style.connector_width.points,
        ),
    )
    for index, (label, output) in enumerate(zip(labels, outputs, strict=True)):
        text = element(
            motif,
            "text",
            id=f"{node.measured.spec.id}.channel.{index + 1}.label",
            x=label_x,
            y=output.position.y + style.typography.size.points * 0.32,
            font__family=style.typography.family,
            font__size=style.typography.minimum_size.points,
            font__weight=style.typography.label_weight,
            fill=palette.get("ink"),
            data__flexo__fill="ink",
        )
        text.text = label
        element(
            motif,
            "rect",
            id=f"{node.measured.spec.id}.channel.{index + 1}.bar",
            x=bar_left,
            y=output.position.y - 3.0,
            width=5.0,
            height=6.0,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _label_baseline(node: FittedNode, style: LayoutStyle) -> float:
    """The y of the label's first baseline.

    A motif-label kind sets its words at the top of the band ``motif_area``
    reserves for them, so the band a caption is measured into is the band it is
    drawn in. Every other kind centres its label in the box -- and so does a
    motif-label kind whose motif is off: with nothing else in the interior,
    words at the top read as misaligned, not as a band.
    """

    metrics = node.measured.label
    bounds = node.bounds
    spec = node.measured.spec
    if spec.kind in MOTIF_LABEL_KINDS and motif_enabled(spec):
        return bounds.y + style.padding_y.points + metrics.baseline
    return bounds.y + bounds.height / 2.0 - metrics.height / 2.0 + metrics.baseline


CAPTION_ROLE = "caption"
"""Role that paints a node's words as secondary ink rather than as a statement.

The name of a thing paints ``ink``; a note *about* it paints ``muted-ink``, which
is already how a connector's caption is painted. A composite that grows its own
furniture -- the Q/K/V captions under an ``attention(..., vectors=...)`` glyph row
-- says so with this role rather than with a literal colour, so the words are
still secondary in every palette and ``flexo retheme`` still reaches them.

Only a node that asks for it is affected: a ``vector()`` caption an author wrote
keeps the ink it always had.
"""


def _render_label(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    spec = node.measured.spec
    render_runs(
        parent,
        f"{spec.id}.label",
        node.measured.label,
        x=node.bounds.center.x,
        y=_label_baseline(node, style),
        typography=style.typography,
        palette=palette,
        fill_role="muted-ink" if spec.role == CAPTION_ROLE else "ink",
        # Author paint carries no role, so retheme leaves it alone (render_common).
        fill=paint_override(spec, "label"),
        anchor="middle",
    )
