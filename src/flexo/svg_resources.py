"""Embedded fonts, arrow markers, and compiler metadata for SVG documents."""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET

from flexo.ir.routed import RoutedFigure
from flexo.render_common import paint_attributes
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, number
from flexo.text import font_bytes


def add_metadata(parent: ET.Element, routed: RoutedFigure, palette: Palette) -> None:
    semantic = routed.fitted.measured.semantic
    metadata = element(parent, "metadata", id="flexo.metadata")
    metadata.text = json.dumps(
        {
            "compiler": "flexo",
            "figure_id": semantic.id,
            "palette": palette.name,
            "schema_version": semantic.schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def add_definitions(parent: ET.Element, style: LayoutStyle, palette: Palette) -> None:
    definitions = element(parent, "defs", id="flexo.defs")
    stylesheet = element(definitions, "style", id="flexo.fonts", type="text/css")
    regular = base64.b64encode(font_bytes()).decode("ascii")
    italic = base64.b64encode(font_bytes(True)).decode("ascii")
    stylesheet.text = (
        "@font-face{font-family:'IBM Plex Sans';font-style:normal;font-weight:100 700;"
        f"src:url(data:font/ttf;base64,{regular}) format('truetype');}}"
        "@font-face{font-family:'IBM Plex Sans';font-style:italic;font-weight:100 700;"
        f"src:url(data:font/ttf;base64,{italic}) format('truetype');}}"
    )
    for role, paint_role in (("flow", "connector"), ("residual", "residual")):
        marker = element(
            definitions,
            "marker",
            id=f"arrow.{role}",
            viewBox=(
                f"0 {number(-style.arrow_width.points / 2.0)} "
                f"{number(style.arrow_length.points)} {number(style.arrow_width.points)}"
            ),
            refX=0.0,
            refY=0.0,
            markerWidth=style.arrow_length.points,
            markerHeight=style.arrow_width.points,
            markerUnits="userSpaceOnUse",
            orient="auto",
            overflow="visible",
        )
        element(
            marker,
            "path",
            id=f"arrow.{role}.shape",
            d=(
                f"M 0 {number(-style.arrow_width.points / 2.0)} "
                f"L {number(style.arrow_length.points)} 0 "
                f"L 0 {number(style.arrow_width.points / 2.0)} Z"
            ),
            **paint_attributes(palette=palette, fill_role=paint_role),
        )
