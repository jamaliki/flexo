"""Minimal deterministic helpers for native SVG construction."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import pairwise
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
