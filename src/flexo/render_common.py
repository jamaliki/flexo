"""Shared paint metadata and component-body primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.geometry import Rect
from flexo.ir.fitted import FittedNode
from flexo.ir.semantic import NodeSpec
from flexo.style import PAINT_PROPERTY_PREFIX, LayoutStyle, Palette
from flexo.svg import element


def paint_override(spec: NodeSpec, part: str) -> str | None:
    """The author's literal colour for one part of ``spec``, if any."""

    value = spec.property(f"{PAINT_PROPERTY_PREFIX}{part}")
    return None if value is None else str(value)


def paint_attributes(
    *,
    palette: Palette,
    fill_role: str | None = None,
    stroke_role: str | None = None,
    stroke_width: float | None = None,
    fill: str | None = None,
    stroke: str | None = None,
) -> dict[str, object]:
    """Paint one element by role, or literally where the author overrode it.

    An overridden part emits its colour and *no* ``data-flexo-fill`` or
    ``data-flexo-stroke``, so ``flexo retheme`` -- which rewrites paint by role
    -- leaves author paint exactly as written, the same convention preset vector
    cells follow.
    """

    values: dict[str, object] = {}
    if fill is not None:
        values["fill"] = fill
    elif fill_role:
        values["fill"] = palette.get(fill_role)
        values["data__flexo__fill"] = fill_role
    else:
        values["fill"] = "none"
    if stroke is not None:
        values["stroke"] = stroke
    elif stroke_role:
        values["stroke"] = palette.get(stroke_role)
        values["data__flexo__stroke"] = stroke_role
    if stroke_width is not None:
        values["stroke__width"] = stroke_width
    return values


SHADOW_LAYERS = 5
"""Nested rectangles one drop shadow is built from.

Enough that the steps between them fall below what a 300 dpi press can resolve
across a 2.5 pt band -- three were still visible as rings under magnification --
and few enough that a figure of shadowed modules stays a handful of rectangles
rather than a gradient mesh.
"""


def soft_shadow(
    parent: ET.Element,
    entity_id: str,
    bounds: Rect,
    radius: float,
    style: LayoutStyle,
    palette: Palette,
) -> ET.Element | None:
    """A soft drop shadow drawn as pure vector geometry, never as a filter.

    Flexo's figures leave as editable SVG and arrive as PDF through Inkscape,
    and Inkscape rasterizes any region it has to filter -- ``feDropShadow`` is
    not even a shape it knows, and ``feGaussianBlur`` turns its whole subtree
    into a 96 dpi bitmap. Either would put a raster patch behind every module in
    a vector figure, so the shadow is made of the only thing that survives the
    trip: rounded rectangles.

    Five of them, nested and equally faint, offset together *down and to the
    right*. Each reaches a fifth less far than the last, so one layer covers the
    outer band and five the ring against the box -- a stepped falloff that
    composites to ``style.shadow_opacity`` where they all overlap. Everything
    under the box itself is hidden by its own fill.

    The light comes from the top left, so the shadow shows along the bottom and
    right edges and nowhere else. That is geometry rather than clipping: with the
    stack offset by at least its own spread, the widest layer's top-left corner
    lands on the box's own top-left corner and every narrower layer starts
    further in, so no layer can put ink above the top edge or left of the left
    edge -- true at any corner radius, and still five plain rectangles.
    """

    spread = style.shadow_spread.points
    if spread <= 0.0 or style.shadow_opacity <= 0.0:
        return None
    # A shorter offset than the spread would let the outer layers ring the top
    # and left edges, which is the halo this shadow exists not to be.
    offset = max(style.shadow_offset.points, spread)
    # Alpha per layer, chosen so all of them together reach the authored opacity.
    layer_opacity = 1.0 - (1.0 - style.shadow_opacity) ** (1.0 / SHADOW_LAYERS)
    group = element(parent, "g", id=f"{entity_id}.shadow")
    for index in range(SHADOW_LAYERS):
        reach = spread * (SHADOW_LAYERS - index) / SHADOW_LAYERS
        element(
            group,
            "rect",
            x=bounds.x + offset - reach,
            y=bounds.y + offset - reach,
            width=bounds.width + 2.0 * reach,
            height=bounds.height + 2.0 * reach,
            rx=radius + reach,
            opacity=layer_opacity,
            **paint_attributes(palette=palette, fill_role="shadow"),
        )
    return group


def base_rect(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
    *,
    fill_role: str = "block-fill",
    stroke_role: str = "block-stroke",
) -> ET.Element:
    bounds = node.bounds
    spec = node.measured.spec
    return element(
        parent,
        "rect",
        id=f"{spec.id}.body",
        x=bounds.x,
        y=bounds.y,
        width=bounds.width,
        height=bounds.height,
        rx=style.corner_radius.points,
        **paint_attributes(
            palette=palette,
            fill_role=fill_role,
            stroke_role=stroke_role,
            stroke_width=style.stroke_width.points,
            fill=paint_override(spec, "fill"),
            stroke=paint_override(spec, "stroke"),
        ),
    )
