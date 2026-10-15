"""A ``picture`` shape: part of a drawing kept exactly as it was drawn.

A drawing imported as shapes (``flexo.svgimport``) may hold what no shape draws -- a
photograph, a group cut by a clip or a mask, a blur, a pattern. Each is kept as a picture
where it was, among the shapes, so nothing of the drawing is lost::

    - kind: picture
      at: [120, 80]
      size: [140, 90]
      source: assets/drawing-1.svg

It is a box (``at``, ``size``, ``rotate``, ``flip``, ``opacity``) holding its ``source``, a file
beside the document: an SVG of that part alone, or its bitmap (PNG or JPEG), stretched to
fill the box. Its writer says how a source is drawn (``href_of``): a slide, by the picture's
data or the studio's address for it; on its own, the file named as it is.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from flexo.svg import element, number

href_of: ContextVar[Callable[[str], str | None] | None] = ContextVar(
    "flexo_shape_picture_href", default=None
)
"""How a picture's ``source`` is named in a drawing (its data, an address for it), where its
writer names it its own way; unset, as a figure's pictures are (``placed``)."""


def draw(group: ET.Element, spec: Mapping[str, Any], made: Any) -> ET.Element | None:
    """A picture drawn into its shape's ``group`` (which turns it): its source filling its
    box, mirrored as it says."""

    source = str(spec.get("source") or "")
    if not source:
        return None
    find = href_of.get() or placed
    try:
        href = find(source)
    except Exception:  # (a file gone, unreadable: drawn as its box, faintly)
        href = None
    x, y, w, h = made.box
    if not href:
        return element(
            group,
            "rect",
            x=float(x),
            y=float(y),
            width=float(w),
            height=float(h),
            fill="none",
            stroke="#999999",
            stroke_width=0.75,
            stroke_dasharray="3 2",
        )
    flip = spec.get("flip")
    picture = element(
        group,
        "image",
        x=float(x),
        y=float(y),
        width=float(max(w, 0.0)),
        height=float(max(h, 0.0)),
        preserveAspectRatio="none",
        href=href,
        data__flexo__source=source,
    )
    if flip:
        sx = -1.0 if flip in ("horizontal", "both") else 1.0
        sy = -1.0 if flip in ("vertical", "both") else 1.0
        cx, cy = x + w / 2.0, y + h / 2.0
        picture.set(
            "transform",
            f"translate({number(cx)} {number(cy)}) scale({number(sx)} {number(sy)}) "
            f"translate({number(-cx)} {number(-cy)})",
        )
    return picture


def placed(source: str) -> str | None:
    """A picture's file as a drawing names it, as a figure's picture is placed: an SVG's
    drawing (made safe to place, ``flexo.artwork``) as data; a photograph by the studio's
    address for it, or as data. None for a file that is not there."""

    from pathlib import Path

    path = Path(source)
    if not path.is_file():
        return None
    from flexo.artwork import load_artwork, picture_href, picture_link

    stamp = path.stat().st_mtime_ns
    if path.suffix.lower() == ".svg" or picture_link.get() is None:
        return _placed(str(path.resolve()), stamp)
    # (A photograph the studio names by an address of its own: asked of it each time.)
    return picture_href(load_artwork("picture", str(path.resolve())))


@lru_cache(maxsize=128)
def _placed(source: str, stamp: int) -> str:
    import base64

    from flexo.artwork import load_artwork, picture_href

    art = load_artwork("picture", source)
    if art.format == "svg":
        return "data:image/svg+xml;base64," + base64.b64encode(art.markup.encode()).decode()
    return picture_href(art)


def anchored(shapes: Any, base: Any) -> Any:
    """``shapes`` with each picture's ``source`` found from ``base`` (a document's folder),
    where it is there: as a document's pictures are found."""

    from pathlib import Path

    if not isinstance(shapes, list):
        return shapes
    out = []
    for spec in shapes:
        if isinstance(spec, Mapping) and spec.get("kind") == "group":
            spec = {**spec, "shapes": anchored(spec.get("shapes"), base)}
        elif isinstance(spec, Mapping) and spec.get("kind") == "picture":
            source = spec.get("source")
            if isinstance(source, str) and source and not Path(source).is_absolute():
                found = Path(base) / source
                if found.is_file():
                    spec = {**spec, "source": str(found.resolve())}
        out.append(spec)
    return out


def sources(shapes: Any) -> list[str]:
    """Every picture's ``source`` among ``shapes`` (a group's too)."""

    found: list[str] = []
    for spec in shapes or []:
        if not isinstance(spec, Mapping):
            continue
        if spec.get("kind") == "picture" and spec.get("source"):
            found.append(str(spec["source"]))
        if spec.get("kind") == "group":
            found += sources(spec.get("shapes"))
    return found


__all__ = ["anchored", "draw", "href_of", "placed", "sources"]
