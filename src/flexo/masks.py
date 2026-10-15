"""A picture shown only inside a shape: Keynote's Mask with Shape.

A slide's picture is cropped as Keynote masks one (flexo-talk): its ``crop`` is the part of
it kept, a rectangle; ``mask: circle`` draws that part round. A mask may be any closed shape
of ``flexo.freeform`` instead -- a star, a cloud, a hexagon, a speech bubble, a polygon or a
line drawn by hand round a cell, closed -- written as the shape is, its places fractions of
the part kept::

    crop: [0.2, 0.1, 0.5, 0.6]       # the part kept, as ever
    mask: {kind: star, tips: 6}      # drawn in all of that part (at [0, 0], size [1, 1])
    mask: {kind: polyline, points: [[0, 0], [1, 0.2], [0.6, 1]]}   # a line round it, closed

A shape in a box fills the part kept unless its ``at`` and ``size`` say otherwise (a rotated
one is drawn turned in its box, as it was on the slide); its own settings (a corner, a
star's points) are as the shape had them, in points, at the size the picture is drawn. A
shape through points -- or any other closed one -- is drawn from its places as fractions of
the part kept, however large that is drawn. The picture is moved, sized and cropped again
as ever; the mask goes with the part kept.

``outline`` draws the mask where the part kept is; ``checked`` reads one as written.
``studio/static/studio/masks.js`` does the same in the page (kept the same by a test).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from flexo import freeform

type Box = tuple[float, float, float, float]
type Point = tuple[float, float]

ROUND = "circle"
"""The mask a picture has had all along: what is kept, drawn round."""


def maskable(kind: object) -> bool:
    """Whether a shape of ``kind`` can mask a picture: any that may be closed (a box, a shape
    through points, any other of an outline of its own), but a zoom inset and a box of words."""

    if kind not in freeform.KINDS or kind in ("inset", "text"):
        return False
    return freeform.family(str(kind)) not in ("line", "text", "group")


def checked(value: object, key: str = "mask") -> str | dict[str, Any] | None:
    """A mask as written: ``circle``, a closed shape (``freeform.checked``, its places fractions
    of the part kept, a shape through points closed), or none. Wrong, it says so
    (``freeform.ShapeError``, under ``key``)."""

    if value is None or value is False or value == "":
        return None
    if value == ROUND:
        return ROUND
    if not isinstance(value, Mapping):
        raise freeform.ShapeError(
            key,
            f"{key} must be circle, or a closed shape such as {{kind: star}} or "
            f"{{kind: polyline, points: [[0, 0], [1, 0], [0.5, 1]]}}, not {value!r}.",
        )
    kind = value.get("kind")
    if not maskable(kind):
        raise freeform.ShapeError(
            f"{key}.kind",
            f"A picture is masked by a closed shape -- a rectangle, an oval, a star, a cloud, "
            f"a polygon, a polyline closed -- not {kind!r}.",
        )
    form = freeform.family(str(kind))
    written = dict(value)
    if form == "box":
        written.setdefault("at", [0.0, 0.0])
        written.setdefault("size", [1.0, 1.0])
    try:
        made = freeform.checked(written)
    except freeform.ShapeError as error:
        raise freeform.ShapeError(f"{key}.{error.key}", error.message) from None
    if form == "points":
        made["closed"] = True
    if form == "box":
        # (The whole of the part kept goes unsaid.)
        if made.get("at") == [0.0, 0.0]:
            del made["at"]
        if made.get("size") == [1.0, 1.0]:
            del made["size"]
    return made


def mapped(spec: Mapping[str, Any], to: Callable[[Point], Point]) -> dict[str, Any]:
    """``spec`` with every point it is placed by mapped by ``to``: its box (by its corners: for
    a map that only stretches and moves), its tail, its points, its ends."""

    made = dict(spec)
    if made.get("at") is not None:
        a = to((float(made["at"][0]), float(made["at"][1])))
        if made.get("size") is not None:
            w, h = (float(value) for value in made["size"])
            b = to((float(made["at"][0]) + w, float(made["at"][1]) + h))
            made["at"] = [min(a[0], b[0]), min(a[1], b[1])]
            made["size"] = [abs(b[0] - a[0]), abs(b[1] - a[1])]
        else:
            made["at"] = [a[0], a[1]]
    if made.get("tail") is not None:
        made["tail"] = list(to((float(made["tail"][0]), float(made["tail"][1]))))
    if made.get("points") is not None:
        made["points"] = [list(to((float(x), float(y)))) for x, y in made["points"]]
    for key in ("from", "to"):
        end = made.get(key)
        if isinstance(end, Sequence) and not isinstance(end, str) and len(end) == 2:
            made[key] = list(to((float(end[0]), float(end[1]))))
    return made


def outline(mask: Mapping[str, Any], kept: Box) -> list[freeform.Segment]:
    """The outline a picture is shown within, masked by ``mask`` (a shape, its places
    fractions of the part kept), the part kept drawn at ``kept``: turned as it is."""

    kx, ky, kw, kh = kept

    def page(point: Point) -> Point:
        return (kx + point[0] * kw, ky + point[1] * kh)

    kind = str(mask.get("kind"))
    if freeform.family(kind) == "box":
        # Placed where it is drawn, so its corners and points are its own, in points.
        spec = mapped({"at": [0.0, 0.0], "size": [1.0, 1.0], **mask}, page)
        made = freeform.geometry(spec)
        if not made.turn:
            return list(made.segments)
        return [_turned(segment, made.centre, made.turn) for segment in made.segments]
    # Any other: drawn in fractions of the part kept, and stretched over it.
    made = freeform.geometry({**mask, "closed": True})
    return [_moved(segment, page) for segment in made.segments]


def _moved(segment: freeform.Segment, to: Callable[[Point], Point]) -> freeform.Segment:
    values = segment[1:]
    points = [to((values[n], values[n + 1])) for n in range(0, len(values), 2)]
    return (segment[0], *(value for point in points for value in point))


def _turned(segment: freeform.Segment, centre: Point, degrees: float) -> freeform.Segment:
    return _moved(segment, lambda point: freeform._turned(point, centre, degrees))


__all__ = ["ROUND", "checked", "mapped", "maskable", "outline"]
