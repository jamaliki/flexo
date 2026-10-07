"""Kind-specific component rendering using shallow native SVG primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.artwork import node_artwork, picture_href
from flexo.badges import badge_icon, draw_badge, draw_icon
from flexo.components import (
    MOTIF_LABEL_KINDS,
    OP_SYMBOLS,
    VectorGrid,
    motif_area,
    motif_enabled,
    node_tone,
    vector_cells,
    vector_grid,
    volume_geometry,
)
from flexo.drawn import DRAWN_KINDS
from flexo.geometry import Rect
from flexo.ir.fitted import FittedNode
from flexo.ir.semantic import NodeSpec
from flexo.render_common import (
    SHADOW_LAYERS,
    base_rect,
    paint_attributes,
    paint_override,
    render_runs,
    soft_shadow,
)
from flexo.render_scientific import render_scientific
from flexo.shapes import SHAPE_KINDS, label_area, outline
from flexo.style import RAMP_ROLES, LayoutStyle, Palette
from flexo.svg import element, number


def render_node(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> ET.Element:
    spec = node.measured.spec
    palette = toned(palette, spec, style)
    group = element(
        parent,
        "g",
        id=spec.id,
        data__flexo__entity="component",
        data__flexo__kind=spec.kind,
        data__flexo__role=spec.role,
    )
    if spec.kind in DRAWN_KINDS:
        from flexo.render_drawn import render_drawn

        render_drawn(group, node, style, palette)
        return group
    if spec.kind == "icon":
        bounds = node.bounds
        radius = min(bounds.width, bounds.height) / 2.0
        centre = bounds.center
        icon = badge_icon(str(spec.property("badge")))
        draw_icon(group, spec.id, icon, centre.x, centre.y, radius)
        return group
    if spec.kind in SHAPE_KINDS:
        _shape(group, node, style, palette)
    elif spec.kind == "text" and not any(run.text.strip() for run in spec.label):
        # Text with no words yet: an unseen box where they will go, to be pointed at.
        bounds = node.bounds
        element(
            group, "rect", id=f"{spec.id}.body", x=bounds.x, y=bounds.y, width=bounds.width,
            height=bounds.height, fill="none", stroke="none", pointer_events="all",
        )
    elif spec.kind not in {"label", "spacer", "text"}:
        # Behind the body, so the box's own fill hides all but the ring.
        if spec.shadow:
            soft_shadow(group, spec.id, node.bounds, style.corner_radius.points, style, palette)
        _render_kind(group, node, style, palette)
    _render_label(group, node, style, palette)
    badge = spec.property("badge")
    if badge:
        draw_badge(
            group,
            spec.id,
            badge_icon(str(badge)),
            node.bounds,
            size=style.typography.size.points,
            page=palette.get("canvas"),
            outline=None if spec.kind in {"text", "label"} else palette.get("block-stroke"),
        )
    return group


def toned(palette: Palette, spec: NodeSpec, style: LayoutStyle) -> Palette:
    """``palette`` as seen by one component: its tone's roles standing in for the body's."""

    tone = node_tone(spec, style.kind_tones)
    index = palette.tone_index(tone) if tone is not None else None
    if index is None:
        return palette
    aliases = {
        f"{family}-{part}": f"tone-{index}-{part}"
        for family in ("block", "accent", "warm")
        for part in ("fill", "stroke", "motif")
    }
    aliases["ink"] = f"tone-{index}-ink"
    if spec.property("tone") is not None:
        # An author who tones an illustration means its frame and paper too.
        aliases["inset-fill"] = f"tone-{index}-fill"
        aliases["container-stroke"] = f"tone-{index}-stroke"
        aliases["inset-stroke"] = f"tone-{index}-stroke"
        aliases["container-fill"] = f"tone-{index}-fill"
    return palette.with_aliases(aliases)


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
    elif kind == "op":
        _op(parent, node, style, palette)
    elif kind == "circle":
        _circle(parent, node, style, palette)
    elif kind == "decision":
        _decision(parent, node, style, palette)
    elif kind == "volume":
        _volume(parent, node, style, palette)
    elif kind == "terminal":
        _terminal(parent, node, style, palette)
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
    bounds = node.bounds
    y = bounds.bottom - 6.0
    # The words come first: a label long enough to reach the motif's band (two
    # lines, say) keeps it, and the block goes without its little drawing.
    label_bottom = bounds.center.y + node.measured.label.height / 2.0
    if y - 3.0 < label_bottom + 1.5:
        return
    motif = element(parent, "g", id=f"{spec.id}.motif")
    if kind == "mlp":
        for index, radius in enumerate((1.2, 1.6, 1.2)):
            element(
                motif,
                "circle",
                cx=bounds.center.x + (index - 1) * 5.0,
                cy=y,
                r=radius,
                **paint_attributes(palette=palette, fill_role="block-motif"),
            )
    else:
        element(
            motif,
            "path",
            d=f"M {number(bounds.center.x - 9)} {number(y)} l 4 -3 l 4 3 l 4 -3 l 4 3",
            **paint_attributes(
                palette=palette,
                stroke_role="block-motif",
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
            **paint_attributes(palette=palette, fill_role="accent-motif"),
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
            **paint_attributes(palette=palette, fill_role="block-motif"),
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


def _volume(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """A feature map: a box in oblique projection, lit from above.

    Three faces, back to front: the side, shaded with the stroke colour; the
    top, the fill lightened toward the page; the front, the plain fill. Each is
    a closed path in the component's own paint roles, so a tone or a retheme
    recolours all three together.
    """

    spec = node.measured.spec
    bounds = node.bounds
    geometry = volume_geometry(spec)
    depth, thickness, face = geometry.depth, geometry.thickness, geometry.face
    left, top = bounds.x, bounds.y
    front = (
        (left, top + depth),
        (left + thickness, top + depth),
        (left + thickness, top + depth + face),
        (left, top + depth + face),
    )
    lid = (
        (left, top + depth),
        (left + depth, top),
        (left + depth + thickness, top),
        (left + thickness, top + depth),
    )
    side = (
        (left + thickness, top + depth),
        (left + thickness + depth, top),
        (left + thickness + depth, top + face),
        (left + thickness, top + depth + face),
    )
    stroke = style.stroke_width.points
    for name, corners, fill_role, opacity in (
        ("side", side, "block-stroke", 0.35),
        ("top", lid, "block-fill", 0.55),
        ("body", front, "block-fill", None),
    ):
        element(
            parent,
            "path",
            id=f"{spec.id}.{name}",
            d="M " + " L ".join(f"{number(x)} {number(y)}" for x, y in corners) + " Z",
            fill__opacity=opacity,
            stroke__linejoin="round",
            **paint_attributes(
                palette=palette,
                fill_role=fill_role,
                stroke_role="block-stroke",
                stroke_width=stroke,
            ),
        )


def _decision(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """A flowchart decision: a diamond touching the middle of each side of its box."""

    spec = node.measured.spec
    bounds = node.bounds
    inset = style.stroke_width.points / 2.0
    corners = (
        (bounds.center.x, bounds.top + inset),
        (bounds.right - inset, bounds.center.y),
        (bounds.center.x, bounds.bottom - inset),
        (bounds.left + inset, bounds.center.y),
    )
    element(
        parent,
        "path",
        id=f"{spec.id}.body",
        d="M " + " L ".join(f"{number(x)} {number(y)}" for x, y in corners) + " Z",
        stroke__linejoin="round",
        **paint_attributes(
            palette=palette,
            fill_role="block-fill",
            stroke_role="block-stroke",
            stroke_width=style.stroke_width.points,
            fill=paint_override(spec, "fill"),
            stroke=paint_override(spec, "stroke"),
        ),
    )


def _terminal(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """A flowchart start or end: a box whose short sides are half circles."""

    body = base_rect(parent, node, style, palette)
    body.set("rx", number(node.bounds.height / 2.0))


def _shape(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """A shape drawn from its outline (``flexo.shapes``): a cylinder, a cloud, a page.

    The body is one closed path in the component's fill and stroke; what is drawn
    over it -- a lid's rim, a server's rack units, a queue's slots -- is stroked
    in the same ink, so a tone, an author's paint, or a dark theme recolours the
    whole shape together. Each part is its own path, so every editor (and
    PowerPoint) opens it as a shape it can change.
    """

    spec = node.measured.spec
    drawn = outline(spec.kind, node.bounds, node.measured.label, style)
    stroke = style.stroke_width.points
    fill, ink = paint_override(spec, "fill"), paint_override(spec, "stroke")
    if spec.shadow:
        _outline_shadow(parent, spec.id, spec.kind, node, style, palette)
    element(
        parent,
        "path",
        id=f"{spec.id}.body",
        d=drawn.body,
        stroke__linejoin="round",
        **paint_attributes(
            palette=palette,
            fill_role="block-fill",
            stroke_role="block-stroke",
            stroke_width=stroke,
            fill=fill,
            stroke=ink,
        ),
    )
    if drawn.cells:
        element(
            parent,
            "path",
            id=f"{spec.id}.cells",
            d=drawn.cells,
            fill__opacity=0.35,
            **paint_attributes(palette=palette, fill_role="block-motif", fill=ink),
        )
    if drawn.lines:
        element(
            parent,
            "path",
            id=f"{spec.id}.lines",
            d=drawn.lines,
            stroke__linecap="round",
            **paint_attributes(
                palette=palette, stroke_role="block-stroke", stroke_width=stroke, stroke=ink
            ),
        )
    if drawn.marks:
        element(
            parent,
            "path",
            id=f"{spec.id}.marks",
            d=drawn.marks,
            **paint_attributes(palette=palette, fill_role="block-motif", fill=ink),
        )


def _outline_shadow(
    parent: ET.Element,
    entity_id: str,
    kind: str,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    """A shape's drop shadow: its own outline, offset down and right.

    ``soft_shadow`` stacks rounded rectangles, which behind a cylinder or a cloud
    would show their corners. This draws the outline itself instead -- solid for a
    hard shadow, or as the same five faint layers, each spread by a stroke as wide
    as its reach -- so the shadow is the shape's, and still plain vector paths.
    """

    bounds = node.bounds
    hard = style.shadow_style == "hard"
    offset = style.shadow_offset.points if hard else max(
        style.shadow_offset.points, style.shadow_spread.points
    )
    moved = Rect(bounds.x + offset, bounds.y + offset, bounds.width, bounds.height)
    data = outline(kind, moved, node.measured.label, style).body
    group = element(parent, "g", id=f"{entity_id}.shadow")
    if hard:
        element(
            group,
            "path",
            d=data,
            opacity=min(1.0, style.shadow_opacity),
            **paint_attributes(palette=palette, fill_role="shadow"),
        )
        return
    spread = style.shadow_spread.points
    if spread <= 0.0 or style.shadow_opacity <= 0.0:
        return
    layer_opacity = 1.0 - (1.0 - style.shadow_opacity) ** (1.0 / SHADOW_LAYERS)
    for index in range(SHADOW_LAYERS):
        reach = spread * (SHADOW_LAYERS - index) / SHADOW_LAYERS
        element(
            group,
            "path",
            d=data,
            opacity=layer_opacity,
            stroke__linejoin="round",
            **paint_attributes(
                palette=palette, fill_role="shadow", stroke_role="shadow", stroke_width=2.0 * reach
            ),
        )


SHADED_OPACITY = 0.2
"""How much ink a shaded circle -- an observed variable -- is filled with."""


def _circle(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """A labelled circle; ``shaded`` fills it grey, as an observed variable is drawn."""

    spec = node.measured.spec
    centre = node.bounds.center
    radius = min(node.bounds.width, node.bounds.height) / 2.0
    stroke = style.stroke_width.points
    shaded = bool(spec.property("shaded", False))
    element(
        parent,
        "circle",
        id=f"{spec.id}.body",
        cx=centre.x,
        cy=centre.y,
        r=radius - stroke / 2.0,
        # Shading is the ink itself, thinned: a light grey on a light page and a
        # light tint on a dark one, so the label stays legible in every theme.
        fill__opacity=SHADED_OPACITY if shaded else None,
        **paint_attributes(
            palette=palette,
            fill_role="ink" if shaded else "block-fill",
            stroke_role="block-stroke",
            stroke_width=stroke,
            fill=paint_override(spec, "fill"),
            stroke=paint_override(spec, "stroke"),
        ),
    )


def _op(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """An operator: a circle with its symbol drawn in it as strokes."""

    spec = node.measured.spec
    centre = node.bounds.center
    radius = min(node.bounds.width, node.bounds.height) / 2.0
    stroke = style.stroke_width.points
    element(
        parent,
        "circle",
        id=f"{spec.id}.body",
        cx=centre.x,
        cy=centre.y,
        r=radius - stroke / 2.0,
        **paint_attributes(
            palette=palette,
            fill_role="block-fill",
            stroke_role="block-stroke",
            stroke_width=stroke,
            fill=paint_override(spec, "fill"),
            stroke=paint_override(spec, "stroke"),
        ),
    )
    symbol = str(spec.property("symbol", "+"))
    shape = OP_SYMBOLS.get(symbol.strip().lower(), OP_SYMBOLS.get(symbol.strip()))
    arm = radius * 0.5
    ink = paint_override(spec, "stroke")
    if shape in {"plus", "times", "minus"}:
        if shape == "times":
            reach = arm / 2.0**0.5 * 1.1
            strokes = (
                (centre.x - reach, centre.y - reach, centre.x + reach, centre.y + reach),
                (centre.x - reach, centre.y + reach, centre.x + reach, centre.y - reach),
            )
        else:
            strokes = ((centre.x - arm, centre.y, centre.x + arm, centre.y),)
            if shape == "plus":
                strokes += ((centre.x, centre.y - arm, centre.x, centre.y + arm),)
        element(
            parent,
            "path",
            id=f"{spec.id}.symbol",
            d=" ".join(
                f"M {number(x1)} {number(y1)} L {number(x2)} {number(y2)}"
                for x1, y1, x2, y2 in strokes
            ),
            stroke__linecap="round",
            **paint_attributes(
                palette=palette,
                stroke_role="block-motif",
                stroke_width=stroke * 1.25,
                stroke=ink,
            ),
        )
    elif shape == "sine":
        # One period of a sine, the positional-encoding mark.
        reach = arm * 1.25
        rise = arm * 0.8
        data = (
            f"M {number(centre.x - reach)} {number(centre.y)} "
            f"C {number(centre.x - reach * 0.6)} {number(centre.y - rise * 1.6)}, "
            f"{number(centre.x - reach * 0.2)} {number(centre.y - rise * 1.6)}, "
            f"{number(centre.x)} {number(centre.y)} "
            f"S {number(centre.x + reach * 0.6)} {number(centre.y + rise * 1.6)}, "
            f"{number(centre.x + reach)} {number(centre.y)}"
        )
        element(
            parent,
            "path",
            id=f"{spec.id}.symbol",
            d=data,
            stroke__linecap="round",
            **paint_attributes(
                palette=palette,
                stroke_role="block-motif",
                stroke_width=stroke * 1.15,
                stroke=ink,
            ),
        )
    elif shape == "dot":
        element(
            parent,
            "circle",
            id=f"{spec.id}.symbol",
            cx=centre.x,
            cy=centre.y,
            r=max(0.9, radius * 0.16),
            **paint_attributes(palette=palette, fill_role="block-motif", fill=ink),
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
            **paint_attributes(palette=palette, fill_role="block-motif"),
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


def _ramp_fill_opacity(index: int, count: int, toned: bool = False) -> float:
    # A tone's colour is a strong one, made to outline a box: shaded from a lighter start to
    # short of it, so a vector in a tone reads as light as one along a theme's ramp.
    lightest, darkest = _TONED_RAMP if toned else (_RAMP_LIGHTEST, _RAMP_DARKEST)
    if count < 2:
        return darkest
    return lightest + (darkest - lightest) * index / (count - 1)


def _tone_ramp(palette: Palette, tone: str) -> str | None:
    """The theme's vector ramp made from the same colour as ``tone``, if it has one: its
    tones and its ramps come from one list of colours, so tone 3 and ``ramp-q`` are both its
    green. None for the neutral tone, or a theme with no ramp near the tone's colour."""

    from flexo.colour import hue_distance
    from flexo.components import NEUTRAL_TONES

    if tone.lower() in NEUTRAL_TONES:
        return None
    index = palette.tone_index(tone)
    if index is None:
        return None
    colour = palette.get(f"tone-{index}-stroke")
    distance, role = min((hue_distance(colour, palette.get(role)), role) for role in RAMP_ROLES)
    return role if distance < _SAME_RAMP else None


_SAME_RAMP = 0.17
"""How near (in Oklab, its lightness counted a quarter) a ramp's colour has to be to a
tone's to be that tone's ramp: a theme's tone is its ramp colour made darker for words."""

_TONED_RAMP = (0.3, 0.8)
"""The lightest and darkest a toned vector's cells are of its tone's colour."""

_TONED_OUTLINE = 0.6
"""How strongly a toned vector's cells are outlined in its colour."""


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
    bounds = vector_cells(spec, node.bounds, node.measured.label, style)
    for column in range(grid.columns):
        for row in range(grid.cells):
            cell = grid.cell_bounds(bounds, column, row)
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
    # (One with words of its own has them under its cells: vector_cells.)
    bounds = vector_cells(spec, node.bounds, node.measured.label, style)
    if bounds != node.bounds:
        # Its words and the room over its cells are its own too: an unseen box over it all,
        # to be pointed at -- between two columns of cells, it is still the vector.
        box = node.bounds
        element(
            parent, "rect", id=f"{spec.id}.body", x=box.x, y=box.y, width=box.width,
            height=box.height, fill="none", stroke="none", pointer_events="all",
        )
    grid = vector_grid(spec, style, bounds=bounds)
    encoded = spec.property("shades")
    if encoded is not None:
        _preset_vector(parent, node, style, grid, str(encoded))
        return
    # A vector given a tone is shaded along the theme's ramp made from that tone's colour
    # (paper's green tone is the ramp its Q vectors take), as the theme's own vectors are;
    # with no ramp of that colour (``neutral``, the theme's grey), from the tone itself.
    tone = str(spec.property("tone") or "").strip()
    matched = _tone_ramp(palette, tone) if tone else None
    toned = bool(tone) and matched is None
    ramp = matched or ("block-stroke" if toned else str(spec.property("ramp", "ramp-node")))
    fill, stroke = paint_override(spec, "fill"), paint_override(spec, "stroke")
    stack = element(parent, "g", id=f"{spec.id}.grid", data__flexo__ramp=ramp)
    for column in range(grid.columns):
        for row in range(grid.cells):
            cell = grid.cell_bounds(bounds, column, row)
            element(
                stack,
                "rect",
                id=f"{spec.id}.cell.{column + 1}.{row + 1}",
                x=cell.x,
                y=cell.y,
                width=cell.width,
                height=cell.height,
                rx=style.vector_cell_radius.points,
                fill__opacity=_ramp_fill_opacity(row, grid.cells, toned),
                stroke__opacity=_TONED_OUTLINE if toned else None,
                **paint_attributes(
                    palette=palette,
                    fill_role=ramp,
                    stroke_role=ramp,
                    stroke_width=style.stroke_width.points * _CELL_STROKE_SCALE,
                    fill=fill,
                    stroke=stroke or fill,
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
    if artwork.format in {"png", "jpeg"}:
        element(
            parent,
            "image",
            id=f"{spec.id}.artwork",
            x=bounds.x,
            y=bounds.y,
            width=bounds.width,
            height=bounds.height,
            preserveAspectRatio=_ARTWORK_FIT,
            href=picture_href(artwork),
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
            **paint_attributes(palette=palette, fill_role="accent-motif"),
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
    if spec.kind == "vector" and metrics.lines:
        # A vector's words are under its cells (vector_caption_band).
        cells = vector_cells(spec, bounds, metrics, style)
        return cells.bottom + style.vector_label_gap.points + metrics.baseline
    if spec.kind in MOTIF_LABEL_KINDS and motif_enabled(spec):
        return bounds.y + style.padding_y.points + metrics.baseline
    if spec.kind in SHAPE_KINDS:
        # Centred in the room the outline leaves: under a lid, over a wavy foot.
        bounds = label_area(spec.kind, bounds, metrics, style)
    if metrics.cap_height > 0.0 and metrics.lines:
        # Centred the way the eye reads it: from the top of the first line's
        # capitals to the last baseline, not the font's line box -- which in a
        # face with tall accents (Latin Modern) sits the words visibly low.
        visual = metrics.cap_height + (len(metrics.lines) - 1) * metrics.line_height
        return bounds.y + bounds.height / 2.0 - visual / 2.0 + metrics.cap_height
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
        x=(
            label_area(spec.kind, node.bounds, node.measured.label, style).center.x
            if spec.kind in SHAPE_KINDS
            else node.bounds.center.x
        ),
        y=_label_baseline(node, style),
        typography=style.typography,
        palette=palette,
        fill_role="muted-ink" if spec.role == CAPTION_ROLE else "ink",
        # Author paint carries no role, so retheme leaves it alone (render_common).
        fill=paint_override(spec, "label"),
        anchor="middle",
    )
