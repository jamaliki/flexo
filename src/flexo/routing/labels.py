"""Where connector captions go: beside their own line, clear of everything else.

A caption is placed after every line is routed, because only then is it known
what it could collide with. Each labelled edge, in authoring order, tries a
fixed list of positions -- above and below each horizontal run, right and left
of each vertical run, at the middle and then further toward either end -- and
takes the cheapest. A position pays for every component, title, or earlier
caption it overlaps, for every other line it covers, and for leaving the
canvas; ties go to the earlier candidate, so an uncrowded caption keeps the
classic place: centred above the longest horizontal run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

from flexo.geometry import Point, Rect, segment_crosses_rect, segments
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedEdge
from flexo.routing.nudge import caption_reach, caption_rise
from flexo.style import LayoutStyle

FRACTIONS = (0.5, 0.35, 0.65, 0.2, 0.8)
"""Where along a run a caption may sit, most preferred first."""

OVERLAP = 1000.0
"""Price of a caption overlapping a component, a title, or another caption."""

COVERS_LINE = 200.0
"""Price of a caption drawn over another connector's line."""

OUTSIDE = 500.0
"""Price of a caption leaving the canvas."""


def label_box(position: Point, metrics: TextMetrics) -> Rect:
    """The box a caption centred at ``position.x`` with its baseline at ``position.y`` fills."""

    top = position.y - metrics.baseline
    return Rect(position.x - metrics.width / 2.0, top, metrics.width, metrics.height)


def place_edge_labels(
    edges: Sequence[RoutedEdge],
    *,
    solids: Iterable[Rect],
    fixed_labels: Iterable[Rect],
    lines: Sequence[tuple[str, tuple[Point, ...]]],
    canvas: Rect,
    style: LayoutStyle,
) -> list[RoutedEdge]:
    """``edges`` with each caption moved to its cheapest clear position."""

    solid = list(solids)
    placed = list(fixed_labels)
    result = []
    for edge in edges:
        if edge.label_metrics is None or edge.label_position is None:
            result.append(edge)
            continue
        # A caption keeps off every line, its own included: beside a run it
        # clears it by construction, but beside a diagonal it would not.
        others = [line for _, line in lines]
        best: tuple[float, Point] | None = None
        for rank, position in enumerate(_candidates(edge.centerline, edge.label_metrics, style)):
            box = label_box(position, edge.label_metrics)
            cost = rank * 0.01 + _price(box, solid, placed, others, canvas)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, position)
            if cost < 1.0:
                break
        assert best is not None
        placed.append(label_box(best[1], edge.label_metrics))
        result.append(replace(edge, label_position=best[1]))
    return result


def _candidates(
    points: tuple[Point, ...], metrics: TextMetrics, style: LayoutStyle
) -> list[Point]:
    runs = [segment for segment in segments(points) if segment.length > 1e-6]
    horizontal = sorted(
        (segment for segment in runs if segment.horizontal), key=lambda s: -s.length
    )
    vertical = sorted(
        (segment for segment in runs if not segment.horizontal), key=lambda s: -s.length
    )  # vertical runs, and the diagonals of straight edges
    rise = caption_rise(metrics, style)
    reach = caption_reach(metrics, style)
    candidates: list[Point] = []
    for fraction in FRACTIONS:
        for segment in (*horizontal, *vertical):
            at = Point(
                segment.start.x + (segment.end.x - segment.start.x) * fraction,
                segment.start.y + (segment.end.y - segment.start.y) * fraction,
            )
            if segment.horizontal:
                if segment.length < metrics.width * 0.6 and fraction != 0.5:
                    continue
                candidates.append(at.translated(dy=-rise))
                candidates.append(Point(at.x, at.y + reach + metrics.baseline))
            elif abs(segment.start.x - segment.end.x) < 1e-9:
                if segment.length < metrics.height * 1.2 and fraction != 0.5:
                    continue
                baseline = at.y - metrics.height / 2.0 + metrics.baseline
                candidates.append(Point(at.x + reach + metrics.width / 2.0, baseline))
                candidates.append(Point(at.x - reach - metrics.width / 2.0, baseline))
            else:
                # A diagonal (a straight edge): step out along its normal far
                # enough that the caption's nearest corner clears the line.
                dx = segment.end.x - segment.start.x
                dy = segment.end.y - segment.start.y
                nx, ny = -dy / segment.length, dx / segment.length
                half = abs(nx) * metrics.width / 2.0 + abs(ny) * metrics.height / 2.0
                for sign in (1.0, -1.0):
                    centre_x = at.x + sign * nx * (reach + half)
                    centre_y = at.y + sign * ny * (reach + half)
                    candidates.append(
                        Point(centre_x, centre_y - metrics.height / 2.0 + metrics.baseline)
                    )
    return candidates


def _price(
    box: Rect,
    solids: list[Rect],
    placed: list[Rect],
    lines: list[tuple[Point, ...]],
    canvas: Rect,
) -> float:
    cost = 0.0
    for rect in (*solids, *placed):
        if rect.intersects(box, strict=True):
            cost += OVERLAP
    for line in lines:
        for segment in segments(line):
            if _crosses(box, segment.start, segment.end):
                cost += COVERS_LINE
    if not canvas.contains_rect(box):
        cost += OUTSIDE
    return cost


def _crosses(box: Rect, start: Point, end: Point) -> bool:
    """Whether the run from ``start`` to ``end`` passes through ``box``."""

    return segment_crosses_rect(start, end, box)
