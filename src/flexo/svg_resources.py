"""Embedded fonts, arrow markers, and compiler metadata for SVG documents."""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from functools import cache
from io import BytesIO

from flexo.fonts import select_face
from flexo.ir.routed import RoutedFigure
from flexo.render_common import paint_attributes
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, local_name, number
from flexo.text import font_stack, load_face


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


def add_definitions(parent: ET.Element, style: LayoutStyle, palette: Palette) -> ET.Element:
    """Arrowhead markers and the (still empty) font stylesheet.

    The stylesheet is filled by ``embed_fonts`` once the document is written,
    because only then is it known which characters the figure actually uses.
    """

    definitions = element(parent, "defs", id="flexo.defs")
    stylesheet = element(definitions, "style", id="flexo.fonts", type="text/css")
    for role, paint_role in (("flow", "connector"), ("residual", "residual")):
        _arrow_marker(definitions, role, paint_role, style, palette)
        # The same head for the start of a line, turned to point back along it.
        _arrow_marker(definitions, role, paint_role, style, palette, start=True)
    return stylesheet


def _arrow_marker(
    definitions: ET.Element,
    role: str,
    paint_role: str,
    style: LayoutStyle,
    palette: Palette,
    *,
    start: bool = False,
) -> None:
    """One arrowhead, in the style's shape, tip ``arrow_length`` beyond the path end.

    ``start=True`` makes the marker for the other end of a line
    (``arrow.<role>.start``), turned round with ``auto-start-reverse``.

    ``triangle`` is a plain filled wedge. ``stealth`` is TikZ's Stealth: a dart
    whose back is notched in by a third of its length. ``latex`` is TikZ's Latex:
    a wedge with gently convex flanks. ``open`` is two strokes, no fill -- the
    lightest mark, for technical-drawing looks.
    """

    length = style.arrow_length.points
    half = style.arrow_width.points / 2.0
    width = style.connector_width.points
    marker = element(
        definitions,
        "marker",
        id=f"arrow.{role}.start" if start else f"arrow.{role}",
        viewBox=f"{number(-width)} {number(-half - width)} "
        f"{number(length + 2 * width)} {number(2 * half + 2 * width)}",
        refX=0.0,
        refY=0.0,
        markerWidth=length + 2 * width,
        markerHeight=2 * half + 2 * width,
        markerUnits="userSpaceOnUse",
        orient="auto-start-reverse" if start else "auto",
        overflow="visible",
    )
    if start:
        role = f"{role}.start"
    shape = style.arrow_shape
    if shape == "open":
        element(
            marker,
            "path",
            id=f"arrow.{role}.shape",
            d=f"M 0 {number(-half)} L {number(length)} 0 L 0 {number(half)}",
            fill="none",
            stroke__linecap="round",
            stroke__linejoin="round",
            **paint_attributes(palette=palette, stroke_role=paint_role, stroke_width=width),
        )
        return
    if shape == "stealth":
        notch = length / 3.0
        data = (
            f"M 0 {number(-half)} L {number(length)} 0 L 0 {number(half)} "
            f"L {number(notch)} 0 Z"
        )
    elif shape == "latex":
        bulge = half * 0.35
        data = (
            f"M 0 {number(-half)} "
            f"Q {number(length * 0.55)} {number(-half + bulge)} {number(length)} 0 "
            f"Q {number(length * 0.55)} {number(half - bulge)} 0 {number(half)} Z"
        )
    else:
        data = f"M 0 {number(-half)} L {number(length)} 0 L 0 {number(half)} Z"
    element(
        marker,
        "path",
        id=f"arrow.{role}.shape",
        d=data,
        stroke__linejoin="miter",
        **paint_attributes(palette=palette, fill_role=paint_role),
    )


def embed_fonts(stylesheet: ET.Element, root: ET.Element, style: LayoutStyle) -> None:
    """Embed the bundled faces the figure uses, cut down to the characters it uses.

    Only bundled faces are embedded: their licences (SIL OFL, GUST) allow it,
    and a registered or installed face may not. The embedded copy is a subset,
    so a figure carries a few kilobytes of font rather than the whole family --
    the SVG stays self-contained in a browser without weighing a megabyte.
    Inkscape and PDF export read installed and bundled fonts directly (see
    ``flexo.export``), so the subset is for viewers only.
    """

    characters = set()
    styles: set[tuple[int, bool]] = set()
    for item in root.iter():
        if local_name(item.tag) != "text":
            continue
        weight = int(item.get("font-weight") or 400)
        italic = item.get("font-style") == "italic"
        characters.update(item.text or "")
        styles.add((weight, italic))
        for span in item.iter():
            if local_name(span.tag) != "tspan":
                continue
            characters.update(span.text or "")
            styles.add(
                (
                    int(span.get("font-weight") or weight),
                    span.get("font-style", "italic" if italic else "") == "italic",
                )
            )
    characters.discard("\n")
    if not characters:
        return
    stack = font_stack(style.typography)
    rules = []
    remaining = {character for character in characters if not character.isspace()}
    for faces in stack.families:
        # A character is drawn in the first family that has it, exactly as it
        # was measured, so only that family needs to carry it.
        mine = {
            character
            for character in remaining
            if any(load_face(face).has(character) for face in faces)
        }
        remaining -= mine
        if not mine:
            continue
        mine |= {" "}
        drawn = {select_face(faces, weight, italic) for weight, italic in styles}
        for face in faces:
            if not face.bundled or face not in drawn:
                continue
            loaded = load_face(face)
            used = {ord(character) for character in mine if loaded.has(character)}
            if not used:
                continue
            data = _subset(face, loaded.raw, frozenset(used))
            weight = (
                f"{face.weight_min} {face.weight_max}" if face.variable else str(face.weight)
            )
            fmt = "opentype" if face.source.lower().endswith(".otf") else "truetype"
            mime = "font/otf" if fmt == "opentype" else "font/ttf"
            encoded = base64.b64encode(data).decode("ascii")
            rules.append(
                f"@font-face{{font-family:'{face.family}';"
                f"font-style:{'italic' if face.italic else 'normal'};font-weight:{weight};"
                f"src:url(data:{mime};base64,{encoded}) format('{fmt}');}}"
            )
    stylesheet.text = "".join(rules)


@cache
def _subset(face: object, raw: bytes, codepoints: frozenset[int]) -> bytes:
    import logging

    from fontTools import subset

    logging.getLogger("fontTools.subset").setLevel(logging.ERROR)
    options = subset.Options()
    options.layout_features = ["kern", "liga", "calt", "ccmp", "locl", "mark", "mkmk"]
    options.notdef_outline = True
    options.name_IDs = ["*"]
    options.drop_tables += ["DSIG"]
    from fontTools.ttLib import TTFont

    font = TTFont(BytesIO(raw), fontNumber=getattr(face, "index", 0))
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(codepoints))
    subsetter.subset(font)
    output = BytesIO()
    font.save(output)
    return output.getvalue()
