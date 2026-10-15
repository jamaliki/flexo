"""Zoom insets: part of a picture, a figure or a part of one, shown magnified in a box of its own.

Every micrograph figure has one: a small box drawn round a region of the picture, a larger
box elsewhere showing that region magnified, and two lines joining the corners of the one
to the corners of the other. An inset is a shape (``flexo.freeform``, ``kind: inset``)
written where the other shapes are -- a slide's ``shapes``, a figure's -- so it is chosen,
moved, sized, stacked, built in and copied as they are::

    - kind: inset
      of: body[0]                  # what it magnifies: a slide's object (a figure's part, by id)
      region: [0.55, 0.3, 0.2, 0.15]   # the part shown: x, y, width, height, fractions of it
      at: [640, 300]               # the box it is shown in, as any box shape's
      size: [240, 180]
      line: accent                 # the box's outline (none: no border), its width and dash
      frame_line: accent           # the frame round the region, as the box's outline unless said
      connector_line: muted        # the two lines joining them (none: no lines)
      connector_dash: dashed
      text: b                      # a label in its top left corner (align, valign: another)

The region is a share of what it shows part of, so it stays on the same part of a picture
however the slide lays the picture out, and of a figure's part however the figure is laid
out. What the box shows is that region exactly, at the box's size -- drawn again, not a
picture of it: vectors stay vectors (``<use>`` of what it magnifies, clipped to the box),
however large. Should the box and the region differ in proportions, the region fills the
box, centred. The lines join the corners of the region to those of the box on the side
they face, so they never cross either; none are drawn where the box covers the region.

``placed`` works out where everything goes; ``draw`` draws it. ``studio/static/studio/
insets.js`` does the same in the page, as an inset is dragged (kept the same by a test).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from flexo import freeform
from flexo.svg import element, number

type Box = tuple[float, float, float, float]
"""x, y, width, height."""
type Point = tuple[float, float]

REGION: Box = (0.35, 0.35, 0.3, 0.3)
"""The part of what it shows that an inset written without one shows: the middle."""

PIECES = ("frame", "connector")
"""The pieces drawn besides the box: the frame round the region, and the lines joining them."""


@dataclass(frozen=True, slots=True)
class Placed:
    """An inset as it is drawn: its box, the region it shows (both in the page's units),
    how much it magnifies it, and the lines joining them."""

    box: Box
    region: Box
    scale: float
    """How many times larger the region is drawn in the box."""
    offset: Point
    """Where the region's top left corner would be drawn, magnified: the view is the page
    scaled by ``scale`` about the origin, then moved by this."""
    connectors: tuple[tuple[Point, Point], ...]


def region_of(spec: Mapping[str, Any]) -> Box:
    """The part an inset shows, as fractions of what it shows part of."""

    region = spec.get("region")
    if isinstance(region, Sequence) and not isinstance(region, str) and len(region) == 4:
        x, y, w, h = (float(value) for value in region)
        if w > 0.0 and h > 0.0:
            return (x, y, w, h)
    return REGION


def region_box(source: Box, region: Box) -> Box:
    """``region`` (fractions of ``source``) on the page."""

    x, y, w, h = source
    return (x + region[0] * w, y + region[1] * h, region[2] * w, region[3] * h)


def connectors(region: Box, box: Box) -> tuple[tuple[Point, Point], ...]:
    """The two lines joining the region to the box: from the region's corners on the side
    facing the box to the box's corners facing it -- across the wider of the gaps between
    them where the box is off a corner. None where the box and the region overlap."""

    rx, ry, rw, rh = region
    bx, by, bw, bh = box
    right = bx - (rx + rw)
    left = rx - (bx + bw)
    below = by - (ry + rh)
    above = ry - (by + bh)
    across = max(right, left)
    down = max(below, above)
    if across < 0.0 and down < 0.0:
        return ()
    if across >= down:
        if right >= left:
            return (((rx + rw, ry), (bx, by)), ((rx + rw, ry + rh), (bx, by + bh)))
        return (((rx, ry), (bx + bw, by)), ((rx, ry + rh), (bx + bw, by + bh)))
    if below >= above:
        return (((rx, ry + rh), (bx, by)), ((rx + rw, ry + rh), (bx + bw, by)))
    return (((rx, ry), (bx, by + bh)), ((rx + rw, ry), (bx + bw, by + bh)))


def view(region: Box, box: Box) -> tuple[float, Point]:
    """How the region is drawn in the box: the scale, and the offset after it -- the region
    filling the box, centred where their proportions differ."""

    rx, ry, rw, rh = region
    bx, by, bw, bh = box
    scale = max(bw / max(rw, 1e-9), bh / max(rh, 1e-9))
    return scale, (bx + bw / 2.0 - scale * (rx + rw / 2.0), by + bh / 2.0 - scale * (ry + rh / 2.0))


def placed(spec: Mapping[str, Any], source: Box) -> Placed:
    """An inset placed: its box as written (``at``, ``size``), its region on ``source`` (the
    box of what it shows part of, in the same units)."""

    x, y = (float(value) for value in spec["at"])
    w, h = (float(value) for value in spec["size"])
    box = (x, y, max(w, 0.0), max(h, 0.0))
    region = region_box(source, region_of(spec))
    scale, offset = view(region, box)
    return Placed(box, region, scale, offset, connectors(region, box))


def piece(spec: Mapping[str, Any], name: str) -> dict[str, Any]:
    """How a piece of an inset is drawn (``frame``, ``connector``): its line, width and dash
    as it says, else as the box's outline."""

    made = freeform.normalised(spec)
    line = made.get(f"{name}_line")
    width = made.get(f"{name}_width")
    dash = made.get(f"{name}_dash")
    return {
        "line": made.get("line") if line is None else line,
        "line_width": float(made.get("line_width") or 0.0) if width is None else float(width),
        "dash": made.get("dash") or "solid" if dash is None else dash,
        "cap": "butt",
        "join": "miter",
    }


def draw(
    parent: ET.Element,
    spec: Mapping[str, Any],
    made: freeform.Geometry,
    ident: str,
    palette: object,
    *,
    source: Box | None,
    target: str | None,
    unit: float = 1.0,
    shadow: freeform.Shadow | None = None,
) -> ET.Element:
    """An inset drawn into ``parent`` as ``ident``: the frame round its region on what it
    magnifies (``source``, its box in the shapes' units), the lines joining them, its box's
    fill, what it shows -- ``target``, the id of what it magnifies, drawn again
    (``<use>``) magnified and clipped to the box -- and its outline. ``unit``: how large one
    of the shapes' units is in ``target``'s (a slide's shapes are drawn scaled to it). With
    nothing to magnify it is its box alone. Its words are its writer's to set, in
    ``made.area``."""

    spec = freeform.normalised(spec)
    group = element(parent, "g", id=ident)
    if float(spec.get("opacity", 1.0)) < 1.0:
        group.set("opacity", number(float(spec["opacity"])))
    shown = placed(spec, source) if source is not None else None
    if shown is not None:
        group.set("data-flexo-region", " ".join(number(value) for value in shown.region))
        rx, ry, rw, rh = shown.region
        frame = {"kind": "rectangle", "at": [rx, ry], "size": [rw, rh], "fill": "none"}
        frame |= piece(spec, "frame")
        freeform.draw(group, frame, freeform.geometry(frame), f"{ident}.frame", palette)
        joining = piece(spec, "connector")
        if shown.connectors and joining["line"] not in (None, "none") and joining["line_width"] > 0:
            lines = element(group, "g", id=f"{ident}.connectors")
            for count, (a, b) in enumerate(shown.connectors):
                line = {"kind": "line", "from": list(a), "to": list(b), **joining}
                made_line = freeform.geometry(line)
                freeform.draw(lines, line, made_line, f"{ident}.connector{count}", palette)
    under = {**spec, "line": "none"}
    shade = shadow if spec.get("shadow") else None
    freeform.draw(group, under, made, f"{ident}.box", palette, shade)
    if shown is not None and target:
        x, y, w, h = shown.box
        clip = element(group, "clipPath", id=f"{ident}.clip")
        element(clip, "rect", x=x, y=y, width=w, height=h)
        held = element(
            group,
            "g",
            id=f"{ident}.view",
            clip_path=f"url(#{ident}.clip)",
            data__flexo__inset="view",
        )
        k = shown.scale / unit
        matrix = (k, 0.0, 0.0, k, shown.offset[0], shown.offset[1])
        element(
            held,
            "use",
            href=f"#{target}",
            transform=f"matrix({' '.join(number(value) for value in matrix)})",
        )
    over = {**spec, "fill": "none", "shadow": False}
    freeform.draw(group, over, made, f"{ident}.border", palette)
    return group


def view_svg(view: Any, box: tuple[float, float, float, float]) -> str:
    """What an inset's view shows (``view``, a ``flexo.drawing.Group`` read from it) as an SVG
    of its own, exactly ``box`` (``left, top, right, bottom`` on the page): its words as
    outlines -- for a writer that draws it as one picture (a slide program)."""

    import itertools

    from flexo.portable import _items
    from flexo.svg import svg_tag

    left, top, right, bottom = box
    width, height = max(right - left, 1e-3), max(bottom - top, 1e-3)
    root = ET.Element(
        svg_tag("svg"),
        {
            "width": f"{number(width)}pt",
            "height": f"{number(height)}pt",
            "viewBox": " ".join(number(value) for value in (left, top, width, height)),
            "version": "1.1",
        },
    )
    _items(root, [view], itertools.count(1))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def reach(spec: Mapping[str, Any], made: freeform.Geometry, source: Box | None) -> Box:
    """``left, top, right, bottom`` of all an inset draws: its box, and its region's frame."""

    left, top, right, bottom = freeform.bounds(spec, made)
    if source is not None:
        x, y, w, h = placed(spec, source).region
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x + w), max(bottom, y + h)
    return (left, top, right, bottom)


__all__ = [
    "PIECES",
    "REGION",
    "Placed",
    "connectors",
    "draw",
    "piece",
    "placed",
    "reach",
    "region_box",
    "region_of",
    "view",
    "view_svg",
]
