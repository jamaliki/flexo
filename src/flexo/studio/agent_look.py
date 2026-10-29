"""What an agent sees of a document's pages (the ``look`` tool): each page as a picture, drawn by
the same pipeline as every export, with what the drawing says of it.

Three ways of looking besides:

- a **sheet**: many pages tiled small in one picture, each numbered as in the document -- a
  talk's consistency seen at a glance, for the price of about two pages;
- **annotated**: each object, shape and figure part outlined and labelled with where it is in
  the YAML (``body[1]``, ``shapes[0]``, a part's id), with its place and size listed, so the
  agent can name what it sees -- what is outlined is the kind's to say (``marks``);
- at a **build step**: a slide as it stands after so many clicks (the kind's ``at_step``).

Pictures are kept small: a page's long side is ``LOOK_EDGE`` pixels, a sheet's
``SHEET_EDGE``.
"""

from __future__ import annotations

import base64
import math
import re
import struct
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

MAX_LOOK = 4
"""Pages drawn per call to ``look``, each a picture of its own."""
MAX_SHEET = 36
"""Pages a sheet holds."""
LOOK_EDGE = 960
"""Pixels along a page's long side: a slide 960 by 540, a figure as wide (or as tall)."""
SHEET_EDGE = 1560
"""Pixels across a sheet at most (wider, a model would shrink it)."""
TILE = 320
"""Pixels across a page on a sheet at most."""
LABEL_FONT = "IBM Plex Mono"
"""The face the labels are set in: one flexo brings, so it is there to draw them with."""

COLOURS = {"object": "#1c7ed6", "field": "#7048e8", "shape": "#e8590c", "part": "#2b8a3e"}
"""Each sort of thing outlined, in its colour."""


@dataclass(frozen=True, slots=True)
class Mark:
    """One thing on a page to outline: the ``id`` it is drawn with, where it is written
    (``path``, as the YAML has it), a short ``label`` for the picture, what it is (``what``:
    List, Figure, ring, ...), and its ``sort`` (``object``, ``field``, ``shape``, ``part``)."""

    id: str
    path: str
    label: str
    what: str = ""
    sort: str = "object"


# -- pictures --


def page_size(svg: str) -> tuple[float, float, tuple[float, float, float, float]]:
    """A page's width and height in points, and its view box."""

    root = re.search(r"<svg\b[^>]*>", svg)
    head = root.group(0) if root else ""

    def attribute(name: str) -> str | None:
        found = re.search(rf'\b{name}="([^"]*)"', head)
        return found.group(1) if found else None

    view = [
        float(value) for value in re.split(r"[ ,]+", (attribute("viewBox") or "").strip()) if value
    ]
    width, height = _points(attribute("width")), _points(attribute("height"))
    if len(view) != 4:
        view = [0.0, 0.0, width or 960.0, height or 540.0]
    return width or view[2], height or view[3], (view[0], view[1], view[2], view[3])


_UNITS = {"pt": 1.0, "px": 0.75, "": 0.75, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "pc": 12.0}


def _points(value: str | None) -> float:
    found = re.fullmatch(r"\s*([0-9.]+)\s*([a-z]*)\s*", value or "")
    if not found or found.group(2) not in _UNITS:
        return 0.0
    return float(found.group(1)) * _UNITS[found.group(2)]


def picture(svg: str, edge: float = LOOK_EDGE, box: tuple[float, float] | None = None) -> bytes:
    """A page as a PNG, its long side ``edge`` pixels -- or as large as fits ``box`` (width,
    height in pixels)."""

    from flexo.export import rasterise
    from flexo.portable import portable_svg

    width, height, _ = page_size(svg)
    scale = edge / max(width, height, 1.0)
    if box is not None:
        scale = min(box[0] / max(width, 1.0), box[1] / max(height, 1.0))
    return rasterise(portable_svg(svg), dpi=max(4.0, min(72.0 * scale, 400.0)))


def png_size(data: bytes) -> tuple[int, int]:
    """A PNG's width and height in pixels."""

    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def image(data: bytes) -> dict[str, Any]:
    """A PNG as the Messages API's image block."""

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


def sheet(tiles: list[tuple[int, str, bool]]) -> bytes:
    """Pages tiled in one picture, each small and numbered above its top left as in the
    document: ``tiles`` are each a page's number, its SVG, and whether the drawing warns of it
    (its number shown red)."""

    from flexo.export import rasterise

    count = len(tiles)
    columns = min(max(1, math.ceil(math.sqrt(count * 0.9))), 6, count)
    gap, strip = 8, 18  # (between tiles; above each, for its number)
    wide = min(TILE, (SHEET_EDGE - gap * (columns + 1)) // columns)
    width0, height0, _ = page_size(tiles[0][1])
    tall = round(wide * min(max(height0 / max(width0, 1.0), 0.3), 1.5))
    rows = math.ceil(count / columns)
    width, height = gap + columns * (wide + gap), gap + rows * (strip + tall + gap)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#dee2e6"/>',
    ]
    for place, (number, svg, warned) in enumerate(tiles):
        x = gap + (place % columns) * (wide + gap)
        y = gap + (place // columns) * (strip + tall + gap) + strip
        data = picture(svg, box=(wide, tall))
        w, h = png_size(data)
        left, top = x + (wide - w) / 2, y + (tall - h) / 2
        href = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        parts.append(f'<rect x="{x}" y="{y}" width="{wide}" height="{tall}" fill="#ffffff"/>')
        parts.append(
            f'<image x="{left:.1f}" y="{top:.1f}" width="{w}" height="{h}" href="{href}"/>'
        )
        parts.append(
            f'<rect x="{x - 0.5}" y="{y - 0.5}" width="{wide + 1}" height="{tall + 1}" fill="none" '
            'stroke="#868e96" stroke-width="1"/>'
        )
        said = str(number)
        badge = 9 + 8 * len(said)
        parts.append(
            f'<rect x="{x - 0.5}" y="{y - strip + 1}" width="{badge}" height="{strip - 1}" rx="3" '
            f'fill="{"#e03131" if warned else "#343a40"}"/>'
        )
        parts.append(
            f'<text x="{x - 0.5 + badge / 2}" y="{y - 5}" text-anchor="middle" '
            f'font-family="{LABEL_FONT}" font-size="12" font-weight="700" fill="#ffffff">'
            f"{said}</text>"
        )
    parts.append("</svg>")
    return rasterise("\n".join(parts), dpi=72.0)


# -- outlines --


def boxes(svg: str, ids: set[str]) -> dict[str, tuple[float, float, float, float]]:
    """Where each of ``ids`` is drawn on a page, as left, top, right and bottom in the page's
    own units (from its view box's corner): the ink it lays down, as the exports place it."""

    from flexo.drawing import Drawing, Group, ink_bounds, read_drawing

    drawing = read_drawing(svg)
    whole = (0.0, 0.0, drawing.width, drawing.height)
    found: dict[str, tuple[float, float, float, float]] = {}
    stack = [drawing.root]
    while stack:
        group = stack.pop()
        for item in group.items:
            ident = getattr(item, "id", None)
            if ident in ids and ident not in found:
                box = ink_bounds(Drawing(drawing.width, drawing.height, Group(None, [item])))
                if box != whole:  # (nothing drawn, said as the page)
                    found[ident] = box
            if isinstance(item, Group):
                stack.append(item)
    return found


def annotated(
    svg: str, marks: list[Mark], edge: float = LOOK_EDGE
) -> tuple[str, list[tuple[Mark, tuple]]]:
    """``svg`` with each of ``marks`` found on it outlined (dashed, in its sort's colour) and
    labelled; with the marks found and where each is."""

    _, _, view = page_size(svg)
    found = boxes(svg, {mark.id for mark in marks})
    placed = [(mark, found[mark.id]) for mark in marks if mark.id in found]
    if not placed:
        return svg, []
    # Units of the page per pixel of the picture (its long side ``edge``): lines and labels
    # the same size on any page.
    unit = max(view[2], view[3]) / edge
    size, stroke = 10.5 * unit, 1.4 * unit
    taken: list[tuple[float, float, float, float]] = []
    parts = [f'<g id="flexo-look-marks" transform="translate({view[0]:g} {view[1]:g})">']
    # (Objects first, parts last: a part's label over its object's outline.)
    order = {"field": 0, "object": 1, "shape": 2, "part": 3}
    for mark, (left, top, right, bottom) in sorted(
        placed, key=lambda item: order.get(item[0].sort, 1)
    ):
        colour = COLOURS.get(mark.sort, COLOURS["object"])
        pad = 1.5 * unit
        parts.append(
            f'<rect x="{left - pad:.2f}" y="{top - pad:.2f}" width="{right - left + 2 * pad:.2f}" '
            f'height="{bottom - top + 2 * pad:.2f}" fill="none" stroke="{colour}" '
            f'stroke-width="{stroke:.2f}" stroke-dasharray="{4 * unit:.2f} {2.5 * unit:.2f}"/>'
        )
        label_w, label_h = (len(mark.label) * 0.62 + 0.9) * size, size * 1.45
        spots = [
            (left - pad, top - pad - label_h),  # above, at its left
            (left, top),  # inside, at its top left
            (left - pad, bottom + pad),  # below
            (right - label_w, top),  # inside, at its top right
            (right + pad, top),  # beside it, on the right
            (left - pad - label_w, top),  # beside it, on the left
        ]
        # The first spot clear of the page's edges and the other labels -- else the one that
        # covers the least of them.
        spot = min(spots, key=lambda s: _hits(s, label_w, label_h, taken, view))
        taken.append((spot[0], spot[1], spot[0] + label_w, spot[1] + label_h))
        parts.append(
            f'<rect x="{spot[0]:.2f}" y="{spot[1]:.2f}" width="{label_w:.2f}" '
            f'height="{label_h:.2f}" rx="{2 * unit:.2f}" fill="{colour}"/>'
        )
        parts.append(
            f'<text x="{spot[0] + 0.45 * size:.2f}" y="{spot[1] + 1.08 * size:.2f}" '
            f'font-family="{LABEL_FONT}" font-size="{size:.2f}" font-weight="500" '
            f'fill="#ffffff">{escape(mark.label)}</text>'
        )
    parts.append("</g>")
    end = svg.rfind("</svg>")
    return svg[:end] + "\n".join(parts) + svg[end:], placed


def _hits(spot, width, height, taken, view) -> float:
    """How badly a label at ``spot`` sits: off the page counts most, then how much of the other
    labels it covers; 0 where it is clear."""

    x, y = spot
    off = (
        max(0.0, -x) + max(0.0, -y) + max(0.0, x + width - view[2]) + max(0.0, y + height - view[3])
    )
    covered = sum(
        max(0.0, min(x + width, b[2]) - max(x, b[0]))
        * max(0.0, min(y + height, b[3]) - max(y, b[1]))
        for b in taken
    )
    return off * 1000.0 + covered


def listed(placed: list[tuple[Mark, tuple]]) -> list[str]:
    """The marks found on a page, a line each: label, where it is written, what it is, and its
    place and size on the page (in the units shapes are placed in)."""

    lines = []
    for mark, (left, top, right, bottom) in placed:
        what = f" ({mark.what})" if mark.what else ""
        where = f"at [{left:.0f}, {top:.0f}], size [{right - left:.0f}, {bottom - top:.0f}]"
        path = f": {mark.path}" if mark.path != mark.label else ""
        lines.append(f"- {mark.label}{path}{what} {where}")
    return lines


# -- the tool --


def look(
    workspace: Any,
    who: dict[str, Any],
    file: str,
    pages: list[int] | None = None,
    sheet_of: bool = False,
    annotate: bool = False,
    step: int | None = None,
) -> list[dict[str, Any]]:
    """The ``look`` tool's answer: pictures of the pages asked for (a sheet of them; outlined;
    at a build step), then what the drawing says of the document."""

    if step is not None and step < 1:
        raise ValueError("step counts from 1: the page as it first appears, before any click")
    doc = workspace.open(file)
    first = (pages or [1])[0]
    workspace.set_presence(who, doc.name, {"page": first}, None)
    drawing = workspace.drawing_of(doc.name, {"focus": first - 1})
    count, cap = len(drawing.pages), MAX_SHEET if sheet_of else MAX_LOOK
    wanted = list(pages or range(1, min(count, cap) + 1))
    missing = [number for number in wanted if not 1 <= number <= count]
    shown = [number for number in wanted if 1 <= number <= count][:cap]
    warned = {
        message.page
        for message in drawing.messages
        if message.page and message.severity in ("error", "warning")
    }
    blocks: list[dict[str, Any]] = []
    for number in missing:
        blocks.append(_text(f"There is no page {number}; {doc.name} has {count}."))
    head: list[str] = []
    if sheet_of:
        tiles = [
            (number, svg, drawing.pages[number - 1].id in warned)
            for number in shown
            if (svg := _at(doc.kind, drawing.pages[number - 1], step))
        ]
        if tiles:
            blocks.append(_text(_sheet_said(doc.name, [number for number, _, _ in tiles], step)))
            blocks.append(image(sheet(tiles)))
        if annotate:
            head.append(
                "Outlines are drawn on single pages, not on a sheet: look at a page or two."
            )
    else:
        marker = getattr(doc.kind, "marks", None)
        for number in shown:
            page = drawing.pages[number - 1]
            svg = _at(doc.kind, page, step)
            if not svg:
                continue
            said = f"Page {number} ({page.label or page.id})"
            if page.steps > 1:
                said += (
                    f", build step {min(step, page.steps)} of {page.steps}"
                    if step is not None
                    else f", all {page.steps} build steps shown"
                )
            listing: list[str] = []
            if annotate:
                with doc.lock:
                    document = doc.document
                marks = marker(document, number, page) if marker else []
                svg, placed = annotated(svg, marks)
                listing = listed(placed) or ["Nothing on it to outline."]
            blocks.append(_text(said + ":" + ("\n" + "\n".join(listing) if listing else "")))
            blocks.append(image(picture(svg)))
    messages = [message for message in drawing.messages if message.severity != "note"]
    notes = [message for message in drawing.messages if message.severity == "note"]
    summary = [f"{doc.name}: {count} page(s).", *head]
    if len(wanted) - len(missing) > cap:
        summary.append(f"Showing the first {cap} asked for.")
    for message in messages[:30]:
        place = f" [{message.page or message.where}]" if (message.page or message.where) else ""
        summary.append(f"{message.severity}{place}: {message.text}")
    for message in notes[:10]:
        summary.append(f"note: {message.text}")
    if not messages:
        summary.append("No warnings. If these pages read as you intend, you are done with them.")
    else:
        summary.append(
            "Fix what is warned of, then look again at those pages only. Where valid YAML lays "
            "out badly, say so as a Flexo bug rather than nudging places and sizes."
        )
    return [*blocks, _text("\n".join(summary))]


def _at(kind: Any, page: Any, step: int | None) -> str:
    """A page's drawing as it stands at build ``step`` (the whole of it, with none given)."""

    at_step = getattr(kind, "at_step", None)
    if step is None or page.steps <= 1 or at_step is None or not page.svg:
        return page.svg
    return at_step(page, min(step, page.steps))


def _sheet_said(name: str, numbers: list[int], step: int | None) -> str:
    runs: list[str] = []
    for number in numbers:
        if runs and runs[-1].split("-")[-1] == str(number - 1):
            runs[-1] = f"{runs[-1].split('-')[0]}-{number}"
        else:
            runs.append(str(number))
    at = f", each at build step {step}" if step is not None else ""
    return (
        f"A sheet of {name}'s pages {', '.join(runs)}{at}, each numbered above its top left as in "
        "the document (red: the drawing warns of it):"
    )


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}
