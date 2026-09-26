"""The portable SVG: the figure as plain shapes, its words drawn as outlines.

The editable SVG sets its words as live text in the fonts Flexo measured them
in, embedded as subsets; that is what lets them be edited. A program that
ignores embedded fonts, or a pipeline that strips them, then draws the words in
a fallback face that no longer fits the boxes. The portable SVG removes that
dependence: it is written from ``flexo.drawing``, and every run of words becomes
one path of its glyphs' outlines, shaped exactly as they were measured. Groups
keep their ids and layer names, and each text keeps its words as an
``aria-label``, so the file stays searchable and accessible.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable

from flexo.drawing import Drawing, Group, Image, Paint, Run, Segment, Shape, Text, read_drawing
from flexo.outline import glyph_outline, shape
from flexo.svg import INKSCAPE_NS, SVG_NS, inkscape_attr, number, svg_tag

SYNTHETIC_SLANT = 0.25
"""How far an italic set in an upright face leans (as browsers draw it)."""


def portable_svg(
    source: str | Drawing, *, width: str | None = None, height: str | None = None
) -> str:
    """``source`` (a Flexo SVG, or a drawing read from one) with text as outlines.

    The size of an SVG given as text is kept (``180mm``); a drawing is sized in
    points unless ``width`` and ``height`` say otherwise.
    """

    if isinstance(source, str):
        root = ET.fromstring(source)
        width = width or root.get("width")
        height = height or root.get("height")
        drawing = read_drawing(source)
    else:
        drawing = source
    svg = ET.Element(
        svg_tag("svg"),
        {
            "width": width or f"{number(drawing.width)}pt",
            "height": height or f"{number(drawing.height)}pt",
            "viewBox": f"0 0 {number(drawing.width)} {number(drawing.height)}",
            "version": "1.1",
        },
    )
    if drawing.root.id:
        svg.set("id", drawing.root.id)
    _items(svg, drawing.root.items)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("inkscape", INKSCAPE_NS)
    ET.indent(svg, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(svg, encoding="unicode") + "\n"


def path_data(segments: Iterable[Segment]) -> str:
    """Drawing segments as SVG path data."""

    parts = []
    for segment in segments:
        points = " ".join(f"{number(x)} {number(y)}" for x, y in segment.points)
        parts.append(f"{segment.kind} {points}" if points else segment.kind)
    return " ".join(parts)


def _items(parent: ET.Element, items: Iterable[Shape | Text | Image | Group]) -> None:
    for item in items:
        if isinstance(item, Group):
            group = ET.SubElement(parent, svg_tag("g"))
            if item.id:
                group.set("id", item.id)
            if item.label:
                group.set(inkscape_attr("label"), item.label)
            for name, value in item.data.items():
                group.set(name, value)
            _items(group, item.items)
            if not len(group) and not item.id:
                parent.remove(group)
        elif isinstance(item, Shape):
            _shape(parent, item)
        elif isinstance(item, Text):
            _text(parent, item)
        elif isinstance(item, Image):
            image = ET.SubElement(
                parent,
                svg_tag("image"),
                {
                    "x": number(item.x),
                    "y": number(item.y),
                    "width": number(item.width),
                    "height": number(item.height),
                    "preserveAspectRatio": item.fit,
                    "href": item.href,
                },
            )
            if item.id:
                image.set("id", item.id)


def _paint(element: ET.Element, paint: Paint) -> None:
    element.set("fill", paint.fill or "none")
    if paint.fill and paint.fill_opacity != 1.0:
        element.set("fill-opacity", number(paint.fill_opacity))
    if paint.stroke:
        element.set("stroke", paint.stroke)
        element.set("stroke-width", number(paint.stroke_width))
        if paint.stroke_opacity != 1.0:
            element.set("stroke-opacity", number(paint.stroke_opacity))
        if paint.dash:
            element.set("stroke-dasharray", " ".join(number(value) for value in paint.dash))
        if paint.linecap != "butt":
            element.set("stroke-linecap", paint.linecap)
        if paint.linejoin != "miter":
            element.set("stroke-linejoin", paint.linejoin)
    if paint.opacity != 1.0:
        element.set("opacity", number(paint.opacity))
    if paint.blend != "normal":
        element.set("style", f"mix-blend-mode:{paint.blend}")


def _shape(parent: ET.Element, shape_: Shape) -> None:
    if shape_.kind == "rect":
        element = ET.SubElement(
            parent,
            svg_tag("rect"),
            {
                "x": number(shape_.x),
                "y": number(shape_.y),
                "width": number(shape_.width),
                "height": number(shape_.height),
            },
        )
        if shape_.radius:
            element.set("rx", number(shape_.radius))
    elif shape_.kind == "ellipse":
        element = ET.SubElement(
            parent,
            svg_tag("ellipse"),
            {
                "cx": number(shape_.x + shape_.width / 2.0),
                "cy": number(shape_.y + shape_.height / 2.0),
                "rx": number(shape_.width / 2.0),
                "ry": number(shape_.height / 2.0),
            },
        )
    else:
        element = ET.SubElement(parent, svg_tag("path"), {"d": path_data(shape_.segments)})
    if shape_.id:
        element.set("id", shape_.id)
    _paint(element, shape_.paint)
    for head in shape_.arrowheads:
        drawn = ET.SubElement(parent, svg_tag("path"), {"d": path_data(head.outline)})
        _paint(drawn, head.paint)


def run_outline(run: Run) -> tuple[Segment, ...]:
    """Every glyph of ``run`` as one outline, slanted if its face has no italic."""

    segments = [segment for glyph in shape(run) for segment in glyph_outline(run, glyph)]
    if run.italic and not run.face.italic:
        slant = SYNTHETIC_SLANT
        segments = [
            Segment(s.kind, tuple((x + (run.baseline - y) * slant, y) for x, y in s.points))
            for s in segments
        ]
    return tuple(segments)


def _text(parent: ET.Element, text: Text) -> None:
    group = ET.SubElement(parent, svg_tag("g"))
    if text.id:
        group.set("id", text.id)
    words = "\n".join("".join(run.text for run in line.runs) for line in text.lines)
    group.set("aria-label", words)
    group.set("fill", text.fill)
    for line in text.lines:
        for run in line.runs:
            if run.face is None or not run.text.strip():
                continue
            outline = run_outline(run)
            if not outline:
                continue
            path = ET.SubElement(group, svg_tag("path"), {"d": path_data(outline)})
            if run.fill != text.fill:
                path.set("fill", run.fill)
