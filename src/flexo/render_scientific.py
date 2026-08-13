"""Matrix, attention, graph, and scientific-inset motifs."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

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
        _grid(parent, node, palette, rows=4, columns=4, top_fraction=0.42)
    elif kind == "attention":
        base_rect(
            parent,
            node,
            style,
            palette,
            fill_role="accent-fill",
            stroke_role="accent-stroke",
        )
        _grid(parent, node, palette, rows=4, columns=5, top_fraction=0.38)
    elif kind == "graph":
        _graph(parent, node, style, palette)
    else:
        _inset(parent, node, style, palette)


def _grid(
    parent: ET.Element,
    node: FittedNode,
    palette: Palette,
    *,
    rows: int,
    columns: int,
    top_fraction: float,
) -> None:
    bounds = node.bounds
    motif = element(parent, "g", id=f"{node.measured.spec.id}.grid")
    left = bounds.x + 7.0
    top = bounds.y + bounds.height * top_fraction
    width = bounds.width - 14.0
    height = bounds.bottom - top - 6.0
    for row in range(rows):
        for column in range(columns):
            fraction = ((row * 3 + column * 2) % 7) / 8.0 + 0.12
            element(
                motif,
                "rect",
                x=left + column * width / columns,
                y=top + row * height / rows,
                width=max(0.8, width / columns - 0.8),
                height=max(0.8, height / rows - 0.8),
                rx=0.4,
                opacity=fraction,
                **paint_attributes(palette=palette, fill_role="accent-stroke"),
            )


def _graph(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(parent, node, style, palette, fill_role="inset-fill", stroke_role="container-stroke")
    bounds = node.bounds
    motif = element(parent, "g", id=f"{node.measured.spec.id}.network")
    points = (
        (bounds.x + 15, bounds.bottom - 13),
        (bounds.center.x - 2, bounds.bottom - 20),
        (bounds.center.x + 15, bounds.bottom - 10),
        (bounds.right - 12, bounds.bottom - 25),
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
            r=2.5,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _inset(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(parent, node, style, palette, fill_role="inset-fill", stroke_role="container-stroke")
    bounds = node.bounds
    motif = element(parent, "g", id=f"{node.measured.spec.id}.illustration")
    center = (bounds.center.x, bounds.y + bounds.height * 0.67)
    for index in range(3):
        angle = math.radians(120 * index - 90)
        x = center[0] + math.cos(angle) * 13.0
        y = center[1] + math.sin(angle) * 10.0
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
            r=4.0 if index == 0 else 3.2,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )
    element(
        motif,
        "circle",
        cx=center[0],
        cy=center[1],
        r=4.5,
        **paint_attributes(palette=palette, fill_role="warm-stroke"),
    )
