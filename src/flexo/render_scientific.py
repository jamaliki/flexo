"""Matrix, attention, graph, and scientific-inset motifs."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from flexo.components import (
    GRAPH_INK_HEIGHT,
    INSET_ATOM,
    INSET_BOND,
    INSET_CORE,
    INSET_INK,
    motif_area,
    motif_enabled,
)
from flexo.geometry import Rect
from flexo.ir.fitted import FittedNode
from flexo.render_common import base_rect, paint_attributes
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, number


def render_scientific(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    kind = node.measured.spec.kind
    if kind == "matrix":
        base_rect(
            parent,
            node,
            style,
            palette,
            fill_role="accent-fill",
            stroke_role="accent-stroke",
        )
        _grid(parent, node, style, palette, rows=4, columns=4)
    elif kind == "attention":
        base_rect(
            parent,
            node,
            style,
            palette,
            fill_role="accent-fill",
            stroke_role="accent-stroke",
        )
        _grid(parent, node, style, palette, rows=4, columns=5)
    elif kind == "graph":
        _graph(parent, node, style, palette)
    else:
        _inset(parent, node, style, palette)


def _motif_bounds(node: FittedNode, style: LayoutStyle) -> Rect:
    return motif_area(node.measured.spec.kind, node.bounds, node.measured.label, style)


def _grid(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
    *,
    rows: int,
    columns: int,
) -> None:
    if not motif_enabled(node.measured.spec):
        return
    area = _motif_bounds(node, style)
    motif = element(parent, "g", id=f"{node.measured.spec.id}.grid")
    for row in range(rows):
        for column in range(columns):
            fraction = ((row * 3 + column * 2) % 7) / 8.0 + 0.12
            element(
                motif,
                "rect",
                x=area.x + column * area.width / columns,
                y=area.y + row * area.height / rows,
                width=max(0.8, area.width / columns - 0.8),
                height=max(0.8, area.height / rows - 0.8),
                rx=0.4,
                opacity=fraction,
                **paint_attributes(palette=palette, fill_role="accent-stroke"),
            )


_GRAPH_NODES = ((0.143, 0.800), (0.464, 0.333), (0.768, 1.000), (0.911, 0.000))
"""The graph motif's four nodes, as fractions of its ink box.

Kept as fractions because a graph spreads across whatever width its box gives it
while its height stays ``GRAPH_INK_HEIGHT``, so the drawing reads the same in a
narrow inset and a wide one.
"""

_GRAPH_NODE_RADIUS = 2.5


def _graph(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(parent, node, style, palette, fill_role="inset-fill", stroke_role="container-stroke")
    if not motif_enabled(node.measured.spec):
        return
    area = _motif_bounds(node, style)
    motif = element(parent, "g", id=f"{node.measured.spec.id}.network")
    radius = min(_GRAPH_NODE_RADIUS, area.height / 2.0)
    height = min(GRAPH_INK_HEIGHT, area.height) - 2.0 * radius
    left = area.x + radius
    top = area.center.y - height / 2.0
    points = tuple(
        (left + fraction_x * (area.width - 2.0 * radius), top + fraction_y * height)
        for fraction_x, fraction_y in _GRAPH_NODES
    )
    for first, second in ((0, 1), (1, 2), (1, 3), (2, 3)):
        path_data = (
            f"M {number(points[first][0])} {number(points[first][1])} "
            f"L {number(points[second][0])} {number(points[second][1])}"
        )
        element(
            motif,
            "path",
            d=path_data,
            **paint_attributes(
                palette=palette,
                stroke_role="accent-stroke",
                stroke_width=style.stroke_width.points,
            ),
        )
    for index, (x, y) in enumerate(points):
        element(
            motif,
            "circle",
            id=f"{node.measured.spec.id}.node.{index}",
            cx=x,
            cy=y,
            r=radius,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _inset(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    """The molecule of a scientific inset, scaled into the room below its label.

    The drawing has a natural size (``INSET_INK``) and is centred in the motif
    area at that size whenever it fits. When the author's height leaves less room
    than that, it scales down to what is left -- a smaller molecule is a figure
    that still reads, where one drawn over its own caption is not.
    """

    base_rect(parent, node, style, palette, fill_role="inset-fill", stroke_role="container-stroke")
    if not motif_enabled(node.measured.spec):
        return
    area = _motif_bounds(node, style)
    scale = min(1.0, area.width / INSET_INK.width, area.height / INSET_INK.height)
    if scale <= 0.0:
        return
    motif = element(parent, "g", id=f"{node.measured.spec.id}.illustration")
    # Centre the ink, not the atom it is measured from: the molecule reaches
    # further up from its core than down, so the two differ.
    center = (
        area.center.x,
        area.center.y - (INSET_INK.y + INSET_INK.height / 2.0) * scale,
    )
    for index in range(3):
        angle = math.radians(120 * index - 90)
        x = center[0] + math.cos(angle) * INSET_BOND[0] * scale
        y = center[1] + math.sin(angle) * INSET_BOND[1] * scale
        element(
            motif,
            "path",
            d=f"M {number(center[0])} {number(center[1])} L {number(x)} {number(y)}",
            **paint_attributes(
                palette=palette,
                stroke_role="accent-stroke",
                stroke_width=style.connector_width.points,
            ),
        )
        element(
            motif,
            "circle",
            cx=x,
            cy=y,
            r=(INSET_ATOM[0] if index == 0 else INSET_ATOM[1]) * scale,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )
    element(
        motif,
        "circle",
        cx=center[0],
        cy=center[1],
        r=INSET_CORE * scale,
        **paint_attributes(palette=palette, fill_role="warm-stroke"),
    )
