"""Badges: a small drawn mark on a component's corner, saying what state it is in.

Papers that train some parts of a model and freeze others mark each box: a
snowflake on what is frozen, a flame on what is trained, a lightning bolt on
what is fine-tuned. Flexo draws these marks itself, as vector paths -- never
an emoji font, which would be a bitmap in some renderers and missing in others
-- on a small disc of the page colour set on the box's top-right corner, so
the mark reads over the outline and over any fill.

``badge="frozen"`` (a snowflake), ``"trained"`` (a flame), and ``"tuned"``
(a bolt) name the states; ``"snowflake"``, ``"flame"`` (or ``"fire"``), and
``"bolt"`` (or ``"lightning"``) name the marks themselves. A legend keys them
with ``legend(badges={"frozen": "frozen", "trained": "trained"})``.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from flexo.geometry import Rect
from flexo.svg import element, number

ICONS = ("snowflake", "flame", "bolt")
"""The marks Flexo can draw."""

BADGES = {
    "frozen": "snowflake",
    "trained": "flame",
    "trainable": "flame",
    "tuned": "bolt",
    "fine-tuned": "bolt",
    "snowflake": "snowflake",
    "flame": "flame",
    "fire": "flame",
    "bolt": "bolt",
    "lightning": "bolt",
}
"""Every name a badge may be given, and the mark it draws."""

_ICE = "#3f8ed0"
_FLAME = "#ec6a2c"
_FLAME_CORE = "#ffc13b"
_BOLT = "#f2b50f"
_BOLT_EDGE = "#a86f00"


def badge_icon(name: str) -> str:
    """The mark ``name`` draws, or a ``ValueError`` listing the names there are."""

    key = name.strip().lower()
    if key not in BADGES:
        raise ValueError(
            f'unknown badge "{name}"; badges are frozen, trained, tuned '
            f"(or the marks themselves: {', '.join(ICONS)})"
        )
    return BADGES[key]


def draw_icon(
    parent: ET.Element, identifier: str, icon: str, cx: float, cy: float, r: float
) -> None:
    """The mark ``icon`` centred on ``(cx, cy)``, fitting a circle of radius ``r``."""

    def at(x: float, y: float) -> str:
        return f"{number(cx + x * r)} {number(cy + y * r)}"

    if icon == "snowflake":
        pieces = []
        for turn in range(3):
            angle = math.pi / 2 + turn * math.pi / 3
            dx, dy = math.cos(angle), math.sin(angle)
            pieces.append(f"M {at(-dx * 0.92, -dy * 0.92)} L {at(dx * 0.92, dy * 0.92)}")
            for sign in (1.0, -1.0):
                bx, by = dx * sign * 0.58, dy * sign * 0.58
                for side in (1.0, -1.0):
                    branch = angle + (math.pi if sign < 0 else 0.0) + side * math.radians(42)
                    tx, ty = math.cos(branch) * 0.3, math.sin(branch) * 0.3
                    pieces.append(f"M {at(bx, by)} L {at(bx + tx, by + ty)}")
        element(
            parent,
            "path",
            id=f"{identifier}.icon",
            d=" ".join(pieces),
            fill="none",
            stroke=_ICE,
            stroke__width=number(max(0.45, r * 0.2)),
            stroke__linecap="round",
        )
    elif icon == "flame":
        outer = (
            f"M {at(0.08, -1.0)} C {at(0.4, -0.55)} {at(0.78, -0.3)} {at(0.78, 0.28)} "
            f"C {at(0.78, 0.74)} {at(0.44, 1.0)} {at(0.0, 1.0)} "
            f"C {at(-0.44, 1.0)} {at(-0.78, 0.72)} {at(-0.78, 0.3)} "
            f"C {at(-0.78, -0.08)} {at(-0.52, -0.32)} {at(-0.36, -0.62)} "
            f"C {at(-0.22, -0.36)} {at(-0.1, -0.24)} {at(0.04, -0.2)} "
            f"C {at(0.16, -0.46)} {at(0.14, -0.76)} {at(0.08, -1.0)} Z"
        )
        core = (
            f"M {at(0.0, 0.08)} C {at(0.22, 0.32)} {at(0.4, 0.46)} {at(0.4, 0.64)} "
            f"C {at(0.4, 0.86)} {at(0.22, 0.98)} {at(0.0, 0.98)} "
            f"C {at(-0.22, 0.98)} {at(-0.4, 0.86)} {at(-0.4, 0.64)} "
            f"C {at(-0.4, 0.44)} {at(-0.2, 0.3)} {at(0.0, 0.08)} Z"
        )
        element(parent, "path", id=f"{identifier}.icon", d=outer, fill=_FLAME)
        element(parent, "path", id=f"{identifier}.icon-core", d=core, fill=_FLAME_CORE)
    elif icon == "bolt":
        points = (
            *((0.2, -1.0), (-0.58, 0.12), (-0.06, 0.12)),
            *((-0.24, 1.0), (0.6, -0.16), (0.06, -0.16)),
        )
        data = "M " + " L ".join(at(x, y) for x, y in points) + " Z"
        element(
            parent,
            "path",
            id=f"{identifier}.icon",
            d=data,
            fill=_BOLT,
            stroke=_BOLT_EDGE,
            stroke__width=number(max(0.3, r * 0.08)),
            stroke__linejoin="round",
        )
    else:  # pragma: no cover - badge_icon validates every name
        raise ValueError(f"no icon {icon!r}")


def badge_radius(size: float) -> float:
    """The disc a badge is drawn on, for type of ``size`` points."""

    return 0.62 * size


def draw_badge(
    parent: ET.Element,
    identifier: str,
    icon: str,
    bounds: Rect,
    *,
    size: float,
    page: str,
    outline: str | None,
) -> None:
    """A badge on the top-right corner of ``bounds``: the mark on a disc of the page.

    The disc sits on the corner, a little in from it, so the mark reads as the
    box's own and not as a neighbour's; its outline is the box's.
    """

    radius = badge_radius(size)
    cx = bounds.right - radius * 0.35
    cy = bounds.top + radius * 0.35
    element(
        parent,
        "circle",
        id=f"{identifier}.badge",
        cx=number(cx),
        cy=number(cy),
        r=number(radius),
        fill=page,
        stroke=outline or "none",
        stroke__width=number(0.6) if outline else None,
    )
    draw_icon(parent, f"{identifier}.badge", icon, cx, cy, radius * 0.72)
