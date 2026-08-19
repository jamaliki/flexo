"""Shared paint metadata and component-body primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

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


def motif_enabled(spec: NodeSpec) -> bool:
    """Whether ``spec`` draws its decorative motif.

    A motif is ornament -- the MLP's three dots, a matrix's cell grid -- so
    ``motif=False`` suppresses it and changes nothing else about the component:
    same size, same body, same ports.
    """

    return bool(spec.property("motif", True))


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
