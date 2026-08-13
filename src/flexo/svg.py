"""Minimal deterministic helpers for native SVG construction."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import pairwise
from math import hypot
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

ET.register_namespace("", SVG_NS)
ET.register_namespace("inkscape", INKSCAPE_NS)


def svg_tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def inkscape_attr(name: str) -> str:
    return f"{{{INKSCAPE_NS}}}{name}"


def number(value: float) -> str:
    if abs(value) < 5e-8:
        value = 0.0
    rendered = f"{value:.5f}".rstrip("0").rstrip(".")
    return rendered or "0"


def attributes(**values: object) -> dict[str, str]:
    return {
        re.sub(r"_+", "-", name): number(value)
        if isinstance(value, float)
        else str(value)
        for name, value in values.items()
        if value is not None
    }


def element(parent: ET.Element, name: str, **values: object) -> ET.Element:
    return ET.SubElement(parent, svg_tag(name), attributes(**values))


def layer(parent: ET.Element, layer_id: str, label: str) -> ET.Element:
    result = element(parent, "g", id=layer_id)
    result.set(inkscape_attr("groupmode"), "layer")
    result.set(inkscape_attr("label"), label)
    return result


def polyline_path(points: tuple[object, ...]) -> str:
    if not points:
        return ""
    commands = [f"M {number(points[0].x)} {number(points[0].y)}"]
    for previous, point in pairwise(points):
        if previous.y == point.y:
            commands.append(f"H {number(point.x)}")
        elif previous.x == point.x:
            commands.append(f"V {number(point.y)}")
        else:
            commands.append(f"L {number(point.x)} {number(point.y)}")
    return " ".join(commands)


def rounded_polyline_path(points: tuple[object, ...], radius: float) -> str:
    """Fillet through-corners while preserving endpoints and orthogonal rails."""

    if radius <= 0.0 or len(points) < 3:
        return polyline_path(points)
    commands = [f"M {number(points[0].x)} {number(points[0].y)}"]
    cursor_x, cursor_y = points[0].x, points[0].y
    for previous, corner, following in zip(points, points[1:], points[2:], strict=False):
        incoming = hypot(corner.x - previous.x, corner.y - previous.y)
        outgoing = hypot(following.x - corner.x, following.y - corner.y)
        cross = (corner.x - previous.x) * (following.y - corner.y) - (
            corner.y - previous.y
        ) * (following.x - corner.x)
        if incoming == 0.0 or outgoing == 0.0 or abs(cross) < 1e-9:
            if (cursor_x, cursor_y) != (corner.x, corner.y):
                commands.append(f"L {number(corner.x)} {number(corner.y)}")
            cursor_x, cursor_y = corner.x, corner.y
            continue
        actual = min(radius, incoming / 2.0, outgoing / 2.0)
        entry_x = corner.x + (previous.x - corner.x) * actual / incoming
        entry_y = corner.y + (previous.y - corner.y) * actual / incoming
        exit_x = corner.x + (following.x - corner.x) * actual / outgoing
        exit_y = corner.y + (following.y - corner.y) * actual / outgoing
        if (cursor_x, cursor_y) != (entry_x, entry_y):
            commands.append(f"L {number(entry_x)} {number(entry_y)}")
        commands.append(
            f"Q {number(corner.x)} {number(corner.y)} {number(exit_x)} {number(exit_y)}"
        )
        cursor_x, cursor_y = exit_x, exit_y
    final = points[-1]
    if (cursor_x, cursor_y) != (final.x, final.y):
        commands.append(f"L {number(final.x)} {number(final.y)}")
    return " ".join(commands)


@dataclass(frozen=True, slots=True)
class SVGDocument:
    text: str
    width_mm: float
    height_mm: float

    def write(self, destination: str | Path) -> Path:
        target_file = Path(destination)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(self.text, encoding="utf-8")
        return target_file

    def normalized(self) -> str:
        return re.sub(r">\s+<", "><", self.text.strip())
