"""What a connector carries on the far side of its line from its caption.

A reaction arrow is written on both sides: the enzyme above, the cofactors it
spends below as a curved arrow that dips to touch the line (ATP in, ADP out);
a reversible step has its forward rate constant over the line and the reverse
one under it. Both are an *aside*: words, and perhaps a small arc, placed
together with the caption -- the caption on one side of a run, the aside
mirrored on the other -- so the two are priced, moved, and given room as one.

Everything here is geometry in the page's frame, from a point on the line, the
unit direction the line travels there, and the unit normal pointing to the
aside's side. The same numbers place the aside during layout and draw it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from flexo.geometry import Point, Rect
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import EdgeSpec, TextRun
from flexo.style import LayoutStyle


def harpoon_offset(style: LayoutStyle) -> float:
    """How far each line of a reversible (⇌) connector sits from its centerline."""

    return max(1.2, style.arrow_width.points * 0.4)


def line_reach(edge: EdgeSpec, style: LayoutStyle) -> float:
    """How far the connector's ink reaches either side of its centerline."""

    if edge.arrow == "reversible":
        return harpoon_offset(style) + style.arrow_width.points / 2.0
    return 0.0


@dataclass(frozen=True, slots=True)
class AsideWords:
    metrics: TextMetrics
    position: Point
    """Centre x and baseline y, as a connector caption is placed."""


@dataclass(frozen=True, slots=True)
class Aside:
    """An aside placed beside one point of its connector's line."""

    at: Point
    along: Point
    """The unit direction the line travels at ``at``."""
    normal: Point
    """The unit normal from the line toward the aside."""
    box: Rect
    words: tuple[AsideWords, ...]
    arc: tuple[Point, ...] = ()
    """A cubic Bezier (four points) or two joined (seven): the cofactors' curve."""
    head: tuple[Point, Point] | None = None
    """The arc's arrowhead: where it starts and where its tip is."""


def aside_metrics(
    edge: EdgeSpec, measure: Callable[[tuple[TextRun, ...]], TextMetrics]
) -> tuple[TextMetrics | None, ...]:
    """The words of ``edge``'s aside, measured: its back label, or its two cofactors."""

    if edge.back_label:
        return (measure(edge.back_label),)
    if edge.cofactors:
        return tuple(measure(runs) if runs else None for runs in edge.cofactors)
    return ()


def _extent(metrics: TextMetrics, direction: Point) -> float:
    """Half the words' box measured along ``direction``."""

    return abs(direction.x) * metrics.width / 2.0 + abs(direction.y) * metrics.height / 2.0


def _words_at(centre: Point, metrics: TextMetrics) -> AsideWords:
    return AsideWords(metrics, Point(centre.x, centre.y - metrics.height / 2.0 + metrics.baseline))


def _words_box(words: AsideWords) -> Rect:
    metrics = words.metrics
    return Rect(
        words.position.x - metrics.width / 2.0,
        words.position.y - metrics.baseline,
        metrics.width,
        metrics.height,
    )


def _step(point: Point, direction: Point, distance: float) -> Point:
    return Point(point.x + direction.x * distance, point.y + direction.y * distance)


def place_aside(
    edge: EdgeSpec,
    metrics: tuple[TextMetrics | None, ...],
    at: Point,
    along: Point,
    normal: Point,
    style: LayoutStyle,
) -> Aside:
    """``edge``'s aside beside ``at``, on the side ``normal`` points to."""

    reach = line_reach(edge, style)
    clear = reach + caption_reach_for(style)
    if edge.back_label:
        (label,) = metrics
        assert label is not None
        centre = _step(at, normal, clear + _extent(label, normal))
        words = _words_at(centre, label)
        return Aside(at, along, normal, _words_box(words), (words,))
    taken, given = metrics
    present = [item for item in metrics if item is not None]
    height = max(item.height for item in present)
    depth = max(1.4 * height, 3.0 * style.arrow_length.points)
    gap = style.caption_clearance.points * 0.6
    head = style.arrow_length.points * 0.8
    ends = sum(_extent(item, along) for item in present)
    span = max(ends + 1.2 * height, 2.6 * height)
    # The curve dips to touch the line (its outer harpoon, when reversible).
    near = _step(at, normal, reach)
    start = _step(_step(near, normal, depth), along, -span / 2.0)
    end = _step(_step(near, normal, depth), along, span / 2.0)
    pull = depth * 4.0 / 3.0
    if taken is not None and given is not None:
        arc: tuple[Point, ...] = (
            start,
            _step(start, normal, -pull),
            _step(end, normal, -pull),
            end,
        )
    elif taken is not None:
        # Taken in, nothing given off: the curve runs from the words into the line.
        arc = (start, _step(start, normal, -depth * 0.55), _step(near, along, -span * 0.2), near)
    else:
        arc = (near, _step(near, along, span * 0.2), _step(end, normal, -depth * 0.55), end)
    words: list[AsideWords] = []
    points = [*arc]
    arrowhead: tuple[Point, Point] | None = None
    if taken is not None:
        centre = _step(start, normal, gap + head + _extent(taken, normal))
        words.append(_words_at(centre, taken))
    if given is not None:
        tip = _step(end, normal, head)
        arrowhead = (end, tip)
        points.append(tip)
        centre = _step(tip, normal, gap + _extent(given, normal))
        words.append(_words_at(centre, given))
    boxes = [_words_box(item) for item in words]
    xs = [p.x for p in points] + [b.left for b in boxes] + [b.right for b in boxes]
    ys = [p.y for p in points] + [b.top for b in boxes] + [b.bottom for b in boxes]
    box = Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    # Where the curve touches the line is its own; the box that asks for room
    # (and keeps other ink off) starts a little way out from it.
    keep = reach + style.connector_width.points
    if abs(normal.x) < 1e-9:
        line = at.y + normal.y * keep
        top, bottom = (
            (max(box.top, line), box.bottom) if normal.y > 0 else (box.top, min(box.bottom, line))
        )
        box = Rect(box.left, top, box.width, bottom - top)
    elif abs(normal.y) < 1e-9:
        line = at.x + normal.x * keep
        left, right = (
            (max(box.left, line), box.right) if normal.x > 0 else (box.left, min(box.right, line))
        )
        box = Rect(left, box.top, right - left, box.height)
    return Aside(at, along, normal, box, tuple(words), arc, arrowhead)


def caption_reach_for(style: LayoutStyle) -> float:
    """The air between a line and anything written beside it."""

    return style.connector_width.points / 2.0 + style.caption_clearance.points


def arrowhead_outline(base: Point, tip: Point, style: LayoutStyle) -> tuple[Point, ...]:
    """A small filled head from ``base`` to ``tip``, for the cofactors' arc."""

    length = math.hypot(tip.x - base.x, tip.y - base.y) or 1.0
    ux, uy = (tip.x - base.x) / length, (tip.y - base.y) / length
    half = style.arrow_width.points * 0.4
    return (
        Point(base.x - uy * half, base.y + ux * half),
        tip,
        Point(base.x + uy * half, base.y - ux * half),
    )


def writing_room(
    edge: EdgeSpec,
    label: TextMetrics,
    measure: Callable[[tuple[TextRun, ...]], TextMetrics],
    style: LayoutStyle,
) -> TextMetrics:
    """The room ``edge``'s writing needs beside its run, for sizing the gap it crosses.

    Layout widens a gap by its connector's caption; an aside sits across the line
    from the caption, beside the same stretch of it, so the gap has to take the
    longer of the two -- along a horizontal run their widths, along a vertical
    one their heights.
    """

    metrics = aside_metrics(edge, measure)
    if not metrics:
        return label
    origin = Point(0.0, 0.0)
    across = place_aside(edge, metrics, origin, Point(1.0, 0.0), Point(0.0, 1.0), style).box
    down = place_aside(edge, metrics, origin, Point(0.0, 1.0), Point(-1.0, 0.0), style).box
    room = style.arrow_length.points + style.connector_standoff.points
    return replace(
        label,
        width=max(label.width, across.width + room),
        height=max(label.height, down.height + room),
    )
