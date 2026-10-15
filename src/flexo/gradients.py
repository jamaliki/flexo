"""A shape's fill as a gradient: its colours running across it, or out from a point in it.

A shape (``flexo.freeform``) is filled with one colour, or with a gradient written in its
``fill``::

    fill: {gradient: linear, angle: 90, stops: [[0, accent], [1, "#ffffff"]]}
    fill: {gradient: radial, centre: [0.5, 0.5], radius: 0.5, stops: [[0, paper], [1, accent]]}

- ``linear``: its colours run ``angle`` degrees clockwise from left to right (0: left to
  right, 90: top to bottom), across the shape's box from corner to corner along that way, as
  a slide program and CSS run theirs;
- ``radial``: out from ``centre`` (its place in the box, a share of its width and of its
  height), its last colour ``radius`` from it -- a share of the box's width and height, so
  a circle in a square box and an oval in another; ``[rx, ry]`` gives each its own;
- ``stops``: where each colour is, from 0 to 1, as ``[offset, colour]`` or ``[offset,
  colour, opacity]``; a colour as any shape's (a theme's by name, so a theme repaints it, or
  ``#rrggbb``), in order.

The box is the shape's own, unturned: a turned shape turns its gradient with it. Before its
first stop and after its last, the gradient is the colour of that stop.
"""

from __future__ import annotations

import itertools
import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from typing import Any

GRADIENTS = ("linear", "radial")
MOST_STOPS = 64
EXAMPLE = '{gradient: linear, angle: 90, stops: [[0, accent], [1, "#ffffff"]]}'

type Box = tuple[float, float, float, float]
"""``x, y, width, height``."""


def is_gradient(value: object) -> bool:
    """Whether a fill is a gradient (else a colour, or none)."""

    return isinstance(value, Mapping) and "gradient" in value


def checked(value: object, colour_of: Any, key: str = "fill") -> dict[str, Any]:
    """A gradient as written, checked: what is wrong said in words (``ValueError``), its
    colours read by ``colour_of`` (a shape's colour reader)."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a colour, none, or a gradient such as {EXAMPLE}.")
    kind = value.get("gradient")
    if kind not in GRADIENTS:
        raise ValueError(
            f"{key}'s gradient must be linear or radial, not {kind!r}: such as {EXAMPLE}."
        )
    allowed = (
        ("gradient", "stops", "angle")
        if kind == "linear"
        else ("gradient", "stops", "centre", "radius")
    )
    unknown = [str(name) for name in value if name not in allowed]
    if unknown:
        raise ValueError(
            f"A {kind} gradient has no {', '.join(unknown)}: it takes {', '.join(allowed)}."
        )
    made: dict[str, Any] = {"gradient": kind}
    if kind == "linear":
        angle = value.get("angle", 0.0)
        if (
            isinstance(angle, bool)
            or not isinstance(angle, int | float)
            or not math.isfinite(angle)
        ):
            raise ValueError(
                f"{key}'s angle must be a number of degrees, such as 90, not {angle!r}."
            )
        made["angle"] = float(angle) % 360.0
    else:
        centre = value.get("centre", [0.5, 0.5])
        if (
            isinstance(centre, str)
            or not isinstance(centre, Sequence)
            or len(centre) != 2
            or not all(_number(item) and -10.0 <= item <= 10.0 for item in centre)
        ):
            raise ValueError(
                f"{key}'s centre must be its place in the shape, [across, down] as shares of "
                f"its width and height, such as [0.5, 0.5], not {centre!r}."
            )
        made["centre"] = [float(centre[0]), float(centre[1])]
        radius = value.get("radius", 0.5)
        pair = (
            not isinstance(radius, str)
            and isinstance(radius, Sequence)
            and len(radius) == 2
            and all(_number(item) and 0.0 < item <= 20.0 for item in radius)
        )
        if not pair and not (_number(radius) and 0.0 < radius <= 20.0):
            raise ValueError(
                f"{key}'s radius must be a share of the shape's size, such as 0.5 (or [0.5, 0.3] "
                f"across and down), not {radius!r}."
            )
        made["radius"] = [float(radius[0]), float(radius[1])] if pair else float(radius)
    stops = value.get("stops")
    if isinstance(stops, str) or not isinstance(stops, Sequence) or len(stops) < 2:
        raise ValueError(
            f"{key}'s stops must be two colours or more, each [offset, colour], such as "
            f'[[0, accent], [1, "#ffffff"]], not {stops!r}.'
        )
    if len(stops) > MOST_STOPS:
        raise ValueError(f"{key} has {len(stops)} stops: a gradient has {MOST_STOPS} at most.")
    out = []
    last = 0.0
    for index, stop in enumerate(stops):
        if isinstance(stop, str) or not isinstance(stop, Sequence) or len(stop) not in (2, 3):
            raise ValueError(
                f"{key}'s stop {index + 1} must be [offset, colour] or [offset, colour, opacity], "
                f"such as [0.5, accent], not {stop!r}."
            )
        offset = stop[0]
        if not _number(offset) or not 0.0 <= offset <= 1.0:
            raise ValueError(
                f"{key}'s stop {index + 1} must be at an offset from 0 to 1, not {offset!r}."
            )
        if offset < last - 1e-9:
            raise ValueError(
                f"{key}'s stops must be in order: stop {index + 1} comes before the last."
            )
        last = float(offset)
        colour = colour_of(stop[1], key)
        if colour == "none":
            raise ValueError(f"{key}'s stop {index + 1} must be a colour, not none.")
        item: list[Any] = [float(offset), colour]
        if len(stop) == 3:
            opacity = stop[2]
            if not _number(opacity) or not 0.0 <= opacity <= 1.0:
                raise ValueError(
                    f"{key}'s stop {index + 1}'s opacity must be from 0 to 1, not {opacity!r}."
                )
            item.append(float(opacity))
        out.append(item)
    made["stops"] = out
    return made


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def stops_of(fill: Mapping[str, Any], paint: Any) -> list[tuple[float, str, float, str | None]]:
    """A gradient's stops painted: (offset, colour, opacity, the palette role that names
    the colour). ``paint`` is a shape's painter (``flexo.freeform.paint`` with its palette)."""

    out = []
    for stop in fill.get("stops") or []:
        colour, role = paint(stop[1])
        out.append(
            (float(stop[0]), colour or "#000000", float(stop[2]) if len(stop) > 2 else 1.0, role)
        )
    return out


def radii(fill: Mapping[str, Any]) -> tuple[float, float]:
    radius = fill.get("radius", 0.5)
    if isinstance(radius, Sequence) and not isinstance(radius, str):
        return float(radius[0]), float(radius[1])
    return float(radius), float(radius)


def linear_ends(fill: Mapping[str, Any], box: Box) -> tuple[float, float, float, float]:
    """Where a linear gradient starts and ends in ``box``: through its middle, at its
    ``angle``, from the corner it starts at to the opposite one."""

    x, y, w, h = box
    angle = math.radians(float(fill.get("angle", 0.0)))
    ux, uy = math.cos(angle), math.sin(angle)
    half = (abs(w * ux) + abs(h * uy)) / 2.0
    cx, cy = x + w / 2.0, y + h / 2.0
    return (cx - ux * half, cy - uy * half, cx + ux * half, cy + uy * half)


def radial_frame(fill: Mapping[str, Any], box: Box) -> tuple[float, float, float, float]:
    """A radial gradient's centre and radii in ``box``: ``cx, cy, rx, ry``."""

    x, y, w, h = box
    centre = fill.get("centre") or [0.5, 0.5]
    rx, ry = radii(fill)
    return (x + float(centre[0]) * w, y + float(centre[1]) * h, rx * w, ry * h)


def matrix(fill: Mapping[str, Any], box: Box) -> tuple[float, float, float, float, float, float]:
    """What carries the gradient's own frame onto the box: a linear gradient's run from
    (0, 0) to (1, 0), a radial one's unit circle about (0, 0)."""

    if fill.get("gradient") == "radial":
        cx, cy, rx, ry = radial_frame(fill, box)
        return (rx, 0.0, 0.0, ry, cx, cy)
    x1, y1, x2, y2 = linear_ends(fill, box)
    dx, dy = x2 - x1, y2 - y1
    # (Across the run, as far again: any way across keeps its colours.)
    return (dx, dy, -dy, dx, x1, y1)


def middle(fill: Mapping[str, Any], paint: Any) -> str:
    """A gradient's colour half way along it: what words on it are read against, and what
    paints it where a gradient cannot be drawn."""

    stops = stops_of(fill, paint)
    for (a, ca, _, _), (b, cb, _, _) in itertools.pairwise(stops):
        if a <= 0.5 <= b:
            share = 0.0 if b - a < 1e-12 else (0.5 - a) / (b - a)
            return _mixed(ca, cb, share)
    return stops[-1][1] if stops and stops[-1][0] < 0.5 else stops[0][1] if stops else "#888888"


def _mixed(first: str, second: str, share: float) -> str:
    a, b = _rgb(first), _rgb(second)
    return "#" + "".join(
        f"{max(0, min(255, round((x + (y - x) * share) * 255))):02x}"
        for x, y in zip(a, b, strict=True)
    )


def _rgb(colour: str) -> tuple[float, float, float]:
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return (int(text[0:2], 16) / 255.0, int(text[2:4], 16) / 255.0, int(text[4:6], 16) / 255.0)
    except ValueError:
        return (0.5, 0.5, 0.5)


def element(parent: ET.Element, ident: str, fill: Mapping[str, Any], box: Box, paint: Any) -> str:
    """The gradient drawn as SVG into ``parent`` (in the box's own units), and the ``url``
    that fills with it."""

    from flexo.svg import number, svg_tag

    name = f"{ident}.fill"
    if fill.get("gradient") == "radial":
        cx, cy, rx, ry = radial_frame(fill, box)
        attributes = {
            "id": name,
            "gradientUnits": "userSpaceOnUse",
            "cx": number(cx),
            "cy": number(cy),
            "r": number(max(rx, 1e-6)),
        }
        if abs(rx - ry) > 1e-9 and rx > 0:
            attributes["gradientTransform"] = (
                f"translate({number(cx)} {number(cy)}) scale(1 {number(ry / rx)}) "
                f"translate({number(-cx)} {number(-cy)})"
            )
        gradient = ET.SubElement(parent, svg_tag("radialGradient"), attributes)
    else:
        x1, y1, x2, y2 = linear_ends(fill, box)
        gradient = ET.SubElement(
            parent,
            svg_tag("linearGradient"),
            {
                "id": name,
                "gradientUnits": "userSpaceOnUse",
                "x1": number(x1),
                "y1": number(y1),
                "x2": number(x2),
                "y2": number(y2),
            },
        )
    for offset, colour, opacity, role in stops_of(fill, paint):
        stop = ET.SubElement(
            gradient, svg_tag("stop"), {"offset": number(offset), "stop-color": colour}
        )
        if opacity < 1.0:
            stop.set("stop-opacity", number(opacity))
        if role:
            stop.set("data-flexo-stop", role)
    return f"url(#{name})"


__all__ = [
    "GRADIENTS",
    "checked",
    "element",
    "is_gradient",
    "linear_ends",
    "matrix",
    "middle",
    "radial_frame",
    "stops_of",
]
