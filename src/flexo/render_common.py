"""Shared paint metadata and component-body primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.ir.fitted import FittedNode
from flexo.style import LayoutStyle, Palette
from flexo.svg import element


def paint_attributes(
    *,
    palette: Palette,
    fill_role: str | None = None,
    stroke_role: str | None = None,
    stroke_width: float | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    if fill_role:
        values["fill"] = palette.get(fill_role)
        values["data__flexo__fill"] = fill_role
    else:
        values["fill"] = "none"
    if stroke_role:
        values["stroke"] = palette.get(stroke_role)
        values["data__flexo__stroke"] = stroke_role
    if stroke_width is not None:
        values["stroke__width"] = stroke_width
    return values


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
    return element(
        parent,
        "rect",
        id=f"{node.measured.spec.id}.body",
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
        ),
    )
