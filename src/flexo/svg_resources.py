"""Embedded fonts, arrow markers, and compiler metadata for SVG documents."""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from functools import cache
from io import BytesIO

from flexo.fonts import FontFace, bundled_families, family_faces, select_face
from flexo.ir.routed import RoutedFigure
from flexo.render_common import paint_attributes
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, local_name, number
from flexo.text import font_stack, load_face
from flexo.units import Length


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


def add_definitions(
    parent: ET.Element,
    style: LayoutStyle,
    palette: Palette,
    heads: Iterable[str] = (),
) -> ET.Element:
    """Arrowhead markers and the (still empty) font stylesheet.

    ``heads`` names the other heads the figure's connectors end in, as their
    marker ids (``arrow.flow.inhibition``, ``arrow.flow.harpoon``, with
    ``.start`` for the head at a line's start, and ``arrow.flow-s150`` for one
    drawn half as large again); only those are defined.

    The stylesheet is filled by ``embed_fonts`` once the document is written,
    because only then is it known which characters the figure actually uses.
    """

    definitions = element(parent, "defs", id="flexo.defs")
    stylesheet = element(definitions, "style", id="flexo.fonts", type="text/css")
    for role, paint_role in (("flow", "connector"), ("residual", "residual")):
        _arrow_marker(definitions, role, paint_role, style, palette)
        # The same head for the start of a line, turned to point back along it.
        _arrow_marker(definitions, role, paint_role, style, palette, start=True)
    for identifier in sorted(set(heads)):
        _, role, *rest = identifier.split(".")
        start = bool(rest) and rest[-1] == "start"
        head = rest[0] if rest and rest[0] != "start" else "arrow"
        family, scale = sized_family(role)
        drawn = scaled_heads(style, scale)
        if head == "arrow":
            # A coloured line's plain head (``arrow.tone-3``), or one of another size: flow's
            # and a residual's are defined above, whatever the figure has.
            if role not in {"flow", "residual"}:
                _arrow_marker(definitions, role, marker_paint(family), drawn, palette, start=start)
            continue
        if head in ARROW_SHAPES:
            # One of the theme's shapes, by name, whatever the theme draws.
            _arrow_marker(
                definitions, role, marker_paint(family), drawn, palette, start=start,
                shape=head, identifier=identifier,
            )
            continue
        paint = marker_paint(family)
        _head_marker(definitions, identifier, head, paint, drawn, palette, start=start)
    return stylesheet


def sized_family(role: str) -> tuple[str, float]:
    """A marker family and the size its heads are drawn at: ``flow-s150`` is the flow's,
    half as large again; ``tone-3`` a tone's, as the theme draws it."""

    family, _, size = role.rpartition("-s")
    if family and size.isdigit():
        return family, int(size) / 100.0
    return role, 1.0


def scaled_heads(style: LayoutStyle, scale: float) -> LayoutStyle:
    """``style`` with its arrowheads ``scale`` times as large, and the line they are drawn
    for as much wider (an open head is stroked as wide as its line)."""

    if scale == 1.0:
        return style
    return replace(
        style,
        arrow_length=Length(style.arrow_length.points * scale),
        arrow_width=Length(style.arrow_width.points * scale),
        connector_width=Length(style.connector_width.points * scale),
    )


def head_marker_id(role: str, head: str, *, start: bool = False, scale: float = 1.0) -> str:
    """The marker a connector of ``role`` ends in, for ``head`` (see ``EDGE_HEADS``),
    drawn ``scale`` times as large as the theme draws it (see ``sized_family``).

    ``role`` is the line's marker family: ``residual``, a coloured line's own
    (``tone-3``, ``neutral``; see ``marker_paint``), or anything else, the flow's.
    """

    base = role if role == "residual" or _coloured(role) else "flow"
    if round(scale * 100) != 100:
        base = f"{base}-s{round(scale * 100)}"
    name = f"arrow.{base}" if head == "arrow" else f"arrow.{base}.{head}"
    return f"{name}.start" if start else name


def marker_paint(role: str) -> str:
    """The paint role a marker family's heads are filled with: a tone's strong colour
    (``tone-3``), the theme's grey (``neutral``), a residual's, or the connector ink."""

    if role == "residual":
        return "residual"
    if role == "neutral":
        return "block-stroke"
    if _coloured(role):
        return f"{role}-stroke"
    return "connector"


def _coloured(role: str) -> bool:
    return role == "neutral" or (role.startswith("tone-") and role[5:].isdigit())


def _head_marker(
    definitions: ET.Element,
    identifier: str,
    head: str,
    paint_role: str,
    style: LayoutStyle,
    palette: Palette,
    *,
    start: bool,
) -> None:
    """A head that says something other than "goes to", after SBGN.

    Each is drawn in the arrow's own box -- from where the shaft stops to the
    tip ``arrow_length`` on -- so any head fits wherever an arrow fits:

    - ``inhibition``: the line runs on to a bar across it (⊣);
    - ``catalysis``: an open circle at the tip;
    - ``stimulation``: an open triangle; ``necessary``: a bar, then one;
    - ``modulation``: an open diamond;
    - ``harpoon``: half an arrowhead, on the left of the line's travel -- one
      of the two lines of a reversible reaction (⇌);
    - ``dot``, ``diamond``, ``square``: a filled one, its tip where an arrow's is
      (these say nothing of their own).
    """

    length = style.arrow_length.points
    half = style.arrow_width.points / 2.0
    width = style.connector_width.points
    marker = element(
        definitions,
        "marker",
        id=identifier,
        viewBox=f"{number(-width - half)} {number(-2 * half - width)} "
        f"{number(length + 2 * width + 2 * half)} {number(4 * half + 2 * width)}",
        refX=0.0,
        refY=0.0,
        markerWidth=length + 2 * width + 2 * half,
        markerHeight=4 * half + 2 * width,
        markerUnits="userSpaceOnUse",
        orient="auto-start-reverse" if start else "auto",
        overflow="visible",
    )
    n = number
    # Open heads are left unfilled: the shaft stops at their base, and the page
    # behind them may be anything.
    hollow = {"stroke_role": paint_role, "stroke_width": width}
    # A regulation head touches what it acts on: its tip goes on over the
    # standoff an arrow keeps, to the component's edge.
    tip = length + style.connector_standoff.points - width / 2.0
    if head == "inhibition":
        # Its bar a hair short of the edge: on it, it would read as a thick stretch of the
        # outline, not a bar of its own.
        bar, at = half * 2.1, tip - width * 2.2
        data = f"M 0 0 L {n(at)} 0 M {n(at)} {n(-bar)} L {n(at)} {n(bar)}"
        paint = {"stroke_role": paint_role, "stroke_width": width * 1.4}
    elif head == "catalysis":
        radius = half * 1.1
        left = tip - 2.0 * radius
        data = (
            f"M 0 0 L {n(left)} 0 M {n(left)} 0 "
            f"A {n(radius)} {n(radius)} 0 1 1 {n(tip)} 0 "
            f"A {n(radius)} {n(radius)} 0 1 1 {n(left)} 0 Z"
        )
        paint = hollow
    elif head in {"stimulation", "necessary"}:
        wide, base = half * 1.2, tip - length * 1.2
        data = f"M 0 0 L {n(base)} 0 M {n(base)} {n(-wide)} L {n(tip)} 0 L {n(base)} {n(wide)} Z"
        if head == "necessary":
            bar = base - 2.6 * width
            data = f"M {n(bar)} {n(-wide)} L {n(bar)} {n(wide)} " + data
        paint = hollow
    elif head == "modulation":
        wide, base = half * 1.2, tip - length * 1.5
        middle = (base + tip) / 2.0
        data = (
            f"M 0 0 L {n(base)} 0 M {n(base)} 0 L {n(middle)} {n(-wide)} "
            f"L {n(tip)} 0 L {n(middle)} {n(wide)} Z"
        )
        paint = hollow
    elif head == "dot":
        radius = length / 2.0
        data = (
            f"M 0 0 A {n(radius)} {n(radius)} 0 1 1 {n(length)} 0 "
            f"A {n(radius)} {n(radius)} 0 1 1 0 0 Z"
        )
        paint = {"fill_role": paint_role}
    elif head == "diamond":
        # As long again as it is wide, back over the end of the shaft: as weighty as a dot.
        back, wide = -0.4 * length, 0.5 * length
        middle = (back + length) / 2.0
        data = (
            f"M {n(back)} 0 L {n(middle)} {n(-wide)} L {n(length)} 0 "
            f"L {n(middle)} {n(wide)} Z"
        )
        paint = {"fill_role": paint_role}
    elif head == "square":
        side = length / 2.0
        data = f"M 0 {n(-side)} L {n(length)} {n(-side)} L {n(length)} {n(side)} L 0 {n(side)} Z"
        paint = {"fill_role": paint_role}
    elif head == "harpoon":
        if style.arrow_shape == "open":
            data = f"M 0 0 L {n(length)} 0 L 0 {n(-half)}"
            paint = {"stroke_role": paint_role, "stroke_width": width}
        else:
            data = f"M 0 {n(-half)} L {n(length)} 0 L 0 0 Z"
            paint = {"fill_role": paint_role}
    else:
        raise ValueError(f'unknown arrowhead "{head}"')
    element(
        marker,
        "path",
        id=f"{identifier}.shape",
        d=data,
        stroke__linecap="round",
        stroke__linejoin="miter" if head in {"harpoon", "diamond", "square"} else "round",
        **paint_attributes(palette=palette, **paint),  # type: ignore[arg-type]
    )


ARROW_SHAPES = ("triangle", "stealth", "latex", "open")
"""The shapes an arrow's head is drawn in: a theme's ``arrow_shape``, or one line's own."""


def _arrow_marker(
    definitions: ET.Element,
    role: str,
    paint_role: str,
    style: LayoutStyle,
    palette: Palette,
    *,
    start: bool = False,
    shape: str | None = None,
    identifier: str | None = None,
) -> None:
    """One arrowhead, in the style's shape (or ``shape``), tip ``arrow_length`` beyond the
    path end, as ``identifier`` (else ``arrow.<role>``).

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
    name = identifier or (f"arrow.{role}.start" if start else f"arrow.{role}")
    marker = element(
        definitions,
        "marker",
        id=name,
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
    shape = shape or style.arrow_shape
    if shape == "open":
        element(
            marker,
            "path",
            id=f"{name}.shape",
            d=f"M 0 {number(-half)} L {number(length)} 0 L 0 {number(half)}",
            stroke__linecap="round",
            stroke__linejoin="round",
            **paint_attributes(palette=palette, stroke_role=paint_role, stroke_width=width),
        )
        return
    if shape == "stealth":
        notch = length / 3.0
        data = f"M 0 {number(-half)} L {number(length)} 0 L 0 {number(half)} L {number(notch)} 0 Z"
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
        id=f"{name}.shape",
        d=data,
        stroke__linejoin="miter",
        **paint_attributes(palette=palette, fill_role=paint_role),
    )


_LINKED: ContextVar[bool] = ContextVar("flexo_fonts_linked", default=False)


@contextmanager
def fonts_linked() -> Iterator[None]:
    """Draw without embedding fonts, for a page that loads them once itself.

    A drawing's embedded subsets are the bulk of its bytes and much of the time
    it takes; a page showing many drawings -- the studio -- declares every
    bundled face once (``bundled_font_css``) and has the drawings name them.
    """

    token = _LINKED.set(True)
    try:
        yield
    finally:
        _LINKED.reset(token)


def bundled_faces() -> list[FontFace]:
    """Every bundled face, in a fixed order (a page's font URLs are indexes into it)."""

    return [face for family in bundled_families() for face in family_faces(family) if face.bundled]


def bundled_font_css(url: Callable[[int, FontFace], str]) -> str:
    """``@font-face`` rules for every bundled face; ``url`` says where each is served."""

    rules = []
    for index, face in enumerate(bundled_faces()):
        weight = f"{face.weight_min} {face.weight_max}" if face.variable else str(face.weight)
        fmt = "opentype" if face.source.lower().endswith(".otf") else "truetype"
        rules.append(
            f"@font-face{{font-family:'{face.family}';"
            f"font-style:{'italic' if face.italic else 'normal'};font-weight:{weight};"
            f"font-display:block;src:url({url(index, face)}) format('{fmt}');}}"
        )
    return "\n".join(rules)


def _css_weight(value: str | None, inherited: int) -> int:
    """A CSS font weight (``700``, ``bold``, ``normal``), from an SVG anyone may have
    written; what it does not say is the weight it inherits."""

    value = (value or "").strip().lower()
    if value.isdigit():
        return int(value)
    return {"normal": 400, "bold": 700, "bolder": 700, "lighter": 300}.get(value, inherited)


def embed_fonts(stylesheet: ET.Element, root: ET.Element, style: LayoutStyle) -> None:
    """Embed the bundled faces the figure uses, cut down to the characters it uses.

    Only bundled faces are embedded: their licences (SIL OFL, GUST) allow it,
    and a registered or installed face may not. The embedded copy is a subset,
    so a figure carries a few kilobytes of font rather than the whole family --
    the SVG stays self-contained in a browser without weighing a megabyte.
    The PDF embeds its own subsets and the portable SVG and PNG draw outlines
    (see ``flexo.export``), so this subset is for viewers of the editable SVG.
    """

    characters = set()
    styles: set[tuple[int, bool]] = set()
    for item in root.iter():
        if local_name(item.tag) != "text":
            continue
        weight = _css_weight(item.get("font-weight"), 400)
        italic = item.get("font-style") == "italic"
        characters.update(item.text or "")
        styles.add((weight, italic))
        for span in item.iter():
            if local_name(span.tag) != "tspan":
                continue
            characters.update(span.text or "")
            styles.add(
                (
                    _css_weight(span.get("font-weight"), weight),
                    span.get("font-style", "italic" if italic else "") == "italic",
                )
            )
    characters.discard("\n")
    if not characters or _LINKED.get():
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
            weight = f"{face.weight_min} {face.weight_max}" if face.variable else str(face.weight)
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

    # Keep the face's own modified date: fontTools would stamp the save time
    # into the subset, and the same figure would compile to different bytes.
    font = TTFont(BytesIO(raw), fontNumber=getattr(face, "index", 0), recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(codepoints))
    subsetter.subset(font)
    output = BytesIO()
    font.save(output)
    return output.getvalue()
