"""Drawn components painted: the shapes and words of a ``flexo.drawn`` picture.

Every shape is a plain path painted by role -- a gene's or a domain's colour by
its tone, backbones and axes in ink -- so ``flexo retheme`` recolours a drawing,
the portable SVG and PDF carry it, and a sketched theme draws it by hand.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import replace

from flexo.drawn import Picture, Shape, Words, picture
from flexo.ir.fitted import FittedNode
from flexo.render_common import paint_attributes, render_runs
from flexo.style import LayoutStyle, Palette
from flexo.svg import element
from flexo.units import pt

_ARGUMENTS = {"M": 2, "L": 2, "A": 7, "C": 6, "Z": 0}


def _moved(d: str, dx: float, dy: float) -> str:
    """A path of absolute M, L, A, C and Z commands (as ``flexo.genetics`` and
    ``flexo.chemistry`` write them), moved by ``(dx, dy)``: an arc's end point moves, and
    every point of a line or a curve."""

    out: list[str] = []
    command, values = "", []
    for token in re.findall(r"[MLACZ]|-?\d+(?:\.\d+)?(?:e[-+]?\d+)?", d):
        if token in _ARGUMENTS:
            command, values = token, []
            out.append(token)
            continue
        values.append(float(token))
        if len(values) == _ARGUMENTS[command]:
            first = len(values) - 2 if command == "A" else 0  # an arc's radii stay
            pairs = range(first, len(values), 2)
            for at in pairs:
                values[at] += dx
                values[at + 1] += dy
            out.extend(_number(value) for value in values)
            values = []
    return " ".join(out)


def _number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def render_drawn(
    parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette
) -> None:
    """Draw a drawn component, centred in the bounds layout gave it."""

    spec = node.measured.spec
    drawing: Picture = picture(spec, style)
    dx = node.bounds.x + (node.bounds.width - drawing.size.width) / 2.0
    dy = node.bounds.y + (node.bounds.height - drawing.size.height) / 2.0
    # Its name first, as it is read (a PDF's tags, a slide program and a screen reader read
    # in the order drawn): before its parts, then theirs. Set apart from them, it is under none.
    name = f"{spec.id}.label"
    named = [words for words in drawing.words if words.id == name]
    for words in named:
        _words(parent, words, style, palette, dx, dy)
    for shape in drawing.shapes:
        element(
            parent,
            "path",
            id=shape.id,
            d=_moved(shape.d, dx, dy),
            **_paint(shape, palette),
            **_caps(shape),
        )
    for identifier, x, y, width, height in drawing.images:
        _image(parent, identifier, spec, style, palette, x + dx, y + dy, width, height)
    for words in drawing.words:
        if words.id != name:
            _words(parent, words, style, palette, dx, dy)


def _words(
    parent: ET.Element, words: Words, style: LayoutStyle, palette: Palette, dx: float, dy: float
) -> None:
    """One of a drawing's labels, moved to where the drawing is."""

    typography = style.typography
    if words.size is not None:
        typography = replace(typography, size=pt(words.size), minimum_size=pt(min(words.size, 6.0)))
    role = words.role
    if role == "tone-ink":
        index = palette.tone_index(words.tone) if words.tone else None
        role = f"tone-{index}-ink" if index is not None else "ink"
    render_runs(
        parent,
        words.id,
        words.metrics,
        x=words.x + dx,
        y=words.y + dy,
        typography=typography,
        palette=palette,
        fill_role=role,
        anchor=words.anchor,
        weight=words.weight,
    )


def _roles(shape: Shape, palette: Palette) -> tuple[str, str, str]:
    """The fill, stroke, and line role a shape paints with: its tone's, or ink's."""

    index = palette.tone_index(shape.tone) if shape.tone else None
    if index is None:
        return "block-fill", "block-stroke", "ink"
    return f"tone-{index}-fill", f"tone-{index}-stroke", f"tone-{index}-stroke"


def _paint(shape: Shape, palette: Palette) -> dict[str, object]:
    fill, stroke, line = _roles(shape, palette)
    width = shape.width
    if shape.color is not None and not shape.color.startswith("#"):
        # A role the author chose (the ink, an accent): painted by it, so it follows the theme.
        if shape.paint in {"line", "backbone", "tick", "leader", "guide"}:
            return paint_attributes(palette=palette, stroke_role=shape.color, stroke_width=width)
        return paint_attributes(
            palette=palette, fill_role=shape.color, stroke_role=shape.color, stroke_width=width
        )
    if shape.color is not None:
        # The author's exact colour: painted literally, so retheming leaves it be.
        if shape.paint in {"line", "backbone", "tick", "leader", "guide"}:
            return paint_attributes(palette=palette, stroke=shape.color, stroke_width=width)
        return paint_attributes(
            palette=palette, fill=shape.color, stroke=shape.color, stroke_width=width
        )
    if shape.paint == "backbone":
        return paint_attributes(palette=palette, stroke_role="ink", stroke_width=width)
    if shape.paint in {"tick", "leader"}:
        return paint_attributes(palette=palette, stroke_role="muted-ink", stroke_width=width)
    if shape.paint == "guide":
        # A dotted guide: a name led to where it is written, lighter than any line.
        return {
            **paint_attributes(palette=palette, stroke_role="muted-ink", stroke_width=width * 0.6),
            "stroke__dasharray": f"0 {_number(width * 2.2)}",
        }
    if shape.paint == "line":
        return paint_attributes(palette=palette, stroke_role=line, stroke_width=width)
    if shape.paint == "solid":
        return paint_attributes(
            palette=palette, fill_role=line, stroke_role=line, stroke_width=width
        )
    if shape.paint == "hollow":
        return paint_attributes(
            palette=palette, fill_role="canvas", stroke_role=line, stroke_width=width
        )
    return paint_attributes(palette=palette, fill_role=fill, stroke_role=stroke, stroke_width=width)


def _caps(shape: Shape) -> dict[str, object]:
    if shape.paint in {"line", "backbone", "tick", "leader", "guide"}:
        return {"stroke__linecap": "round", "stroke__linejoin": "round"}
    return {"stroke__linejoin": "round"}


def _image(
    parent: ET.Element,
    identifier: str,
    spec,
    style: LayoutStyle,
    palette: Palette,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    """A picture's image box, filled: a molecule drawn by mol-sketch, embedded as a PNG."""

    import base64

    from flexo.structures import structure_png

    data = structure_png(spec, style, palette, width, height)
    element(
        parent,
        "image",
        id=identifier,
        x=x,
        y=y,
        width=width,
        height=height,
        preserveAspectRatio="xMidYMid meet",
        href="data:image/png;base64," + base64.b64encode(data).decode("ascii"),
    )
