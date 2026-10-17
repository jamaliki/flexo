"""A drawing's name, over it or under it: a structure's, and a picture's.

A molecule (a ``structure``) and a picture (an ``image``) are drawings with nothing round
them -- no outline, no fill -- so a name given one is set as it is given the other: in the
theme's title weight, centred on the drawing, ``TITLE_GAP`` type sizes from it, over it
(``title_side: top``, as it is unless written) or under it (``title_side: bottom``). A row of
molecules and pictures named under them has its names on one line, in one hand.

The name's band -- its lines and the gap -- is as tall over the drawing as under it, so where
it stands moves nothing round it. A line meets either kind at the middle of its drawing, not
of its box, and keeps off the side its name stands on (``flexo.components.title_edge``).
"""

from __future__ import annotations

import functools

from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Rect
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec
from flexo.style import LayoutStyle, TypographyStyle
from flexo.text import TextMeasurer

TITLE_SIDES = ("top", "bottom")
"""Where a drawing's name is set: over it (``title_side: top``, as it is unless written) or
under it (``bottom``)."""

SIDED_KINDS = frozenset({"structure", "image"})
"""Kinds whose name is set over their drawing, or under it, as ``title_side`` says."""

TITLE_GAP = 0.3
"""The air between a drawing and its name, in type sizes."""

_CALLED = {"structure": ("structure", "molecule"), "image": ("picture", "picture")}
"""Each kind as a person calls it, and what it draws."""


def _written(node: NodeSpec) -> str:
    return str(node.property("title_side") or TITLE_SIDES[0]).strip().lower()


def title_side(node: NodeSpec) -> str:
    """Where ``node``'s name is set (``TITLE_SIDES``): over its drawing, unless it says
    under."""

    written = _written(node)
    return written if written in TITLE_SIDES else TITLE_SIDES[0]


def title_side_problem(node: NodeSpec) -> Diagnostic | None:
    """A title side written that is neither, as a warning: the name is set over the
    drawing."""

    written = _written(node)
    if node.kind not in SIDED_KINDS or written in TITLE_SIDES:
        return None
    called, drawn = _CALLED[node.kind]
    return Diagnostic(
        f"{node.kind}.title-side",
        f"A {called}\u2019s name can\u2019t stand at \u201c{written}\u201d: it is set over the "
        f"{drawn}.",
        Severity.WARNING,
        entity_id=node.id,
        hint=f"Its properties.title_side is top (over the {drawn}) or bottom (under it).",
    )


@functools.lru_cache(maxsize=8)
def _measurer(typography: TypographyStyle) -> TextMeasurer:
    return TextMeasurer(typography)


def drawing_title(node: NodeSpec, style: LayoutStyle, width: float | None) -> TextMetrics:
    """``node``'s name as it is set on its drawing: in the theme's type, at the title's
    weight, wrapped to ``width`` (``None``: on as few lines as it is written)."""

    return _measurer(style.typography).measure(
        node.label, weight=style.typography.title_weight, max_width=width
    )


def title_gap(style: LayoutStyle) -> float:
    """The air between a drawing and its name, in points."""

    return TITLE_GAP * style.typography.size.points


def title_band(title: TextMetrics, style: LayoutStyle) -> float:
    """How much of its box a drawing's name takes: its lines and the gap (none, unnamed)."""

    return title.height + title_gap(style) if title.lines else 0.0


def drawing_box(bounds: Rect, side: str, band: float) -> Rect:
    """What of ``bounds`` the drawing has: all of it but the name's band, off the side the
    name stands on."""

    top = 0.0 if side == "bottom" else band
    return Rect(bounds.x, bounds.y + top, bounds.width, max(0.0, bounds.height - band))


def title_baseline(side: str, title: TextMetrics, style: LayoutStyle, drawn: float) -> float:
    """The name's first baseline, down from the top of the box: over a drawing ``drawn``
    points tall, or under it."""

    if side == "bottom":
        return drawn + title_gap(style) + title.baseline
    return title.baseline


def drawing_middle(side: str, band: float, height: float) -> float:
    """How far down a box ``height`` points tall the middle of its drawing is, as a fraction
    of it: where a line meets it from either side."""

    if height <= 0.0:
        return 0.5
    top = 0.0 if side == "bottom" else band
    return min(1.0, max(0.0, (top + (height - band) / 2.0) / height))


def drawn_between(
    node: NodeSpec, title: TextMetrics, bounds: Rect, style: LayoutStyle
) -> tuple[float, float] | None:
    """The top and bottom of a named structure's or picture's drawing in its ``bounds``, its
    name (``title``, as measured) aside: the stretch of its left and right a line meets it
    on. ``None`` for any other node, and for one with no name."""

    if node.kind not in SIDED_KINDS or not title.lines:
        return None
    drawn = drawing_box(bounds, title_side(node), title_band(title, style))
    return drawn.top, drawn.bottom
