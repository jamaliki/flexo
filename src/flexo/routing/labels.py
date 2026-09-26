"""Where connector captions go: beside their own line, clear of everything else.

A caption is placed after every line is routed, because only then is it known
what it could collide with. Each labelled edge -- the one with the fewest clear
places first, then in authoring order -- tries a
fixed list of positions -- above and below each horizontal run, right and left
of each vertical run, at the middle and then further toward either end -- and
takes the cheapest. A position pays for every component, title, or earlier
caption it overlaps, for every other line it covers, for leaving the canvas,
and a little for sitting within reach of another connector, which a reader
would take it to name; ties go to the earlier candidate, so an uncrowded caption keeps the
classic place: centred above the longest horizontal run.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import replace

from flexo.geometry import Point, Rect, segment_crosses_rect, segments
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedEdge, RoutedNet
from flexo.routing.ink import caption_reach, caption_rise
from flexo.style import LayoutStyle

FRACTIONS = (0.5, 0.35, 0.65, 0.2, 0.8)
"""Where along a run a caption may sit, most preferred first."""

OVERLAP = 1000.0
"""Price of a caption overlapping a component, a title, or another caption."""

COVERS_LINE = 200.0
"""Price of a caption drawn over another connector's line."""

NEAR_LINE = 50.0
"""Price of a caption within a lane of another connector's line.

A reader takes a caption to name the line nearest it, so one that sits a lane
from someone else's arrow reads as that arrow's."""

OUTSIDE = 100.0
"""Price of a caption leaving the canvas.

The cheapest defect: the canvas grows to take the caption on the next layout
round, while a caption over a line or a box stays there."""


def label_box(position: Point, metrics: TextMetrics) -> Rect:
    """The box a caption centred at ``position.x`` with its baseline at ``position.y`` fills."""

    top = position.y - metrics.baseline
    return Rect(position.x - metrics.width / 2.0, top, metrics.width, metrics.height)


def place_captions(
    edges: Sequence[RoutedEdge],
    nets: Sequence[RoutedNet],
    *,
    solids: Iterable[Rect],
    lines: Sequence[tuple[str, tuple[Point, ...]]],
    canvas: Rect,
    style: LayoutStyle,
) -> tuple[list[RoutedEdge], list[RoutedNet]]:
    """``edges`` and ``nets`` with each caption moved to its cheapest clear position.

    A net's caption first tries the place its tree reads along (see
    ``rail_label_position``), then the same places an edge's caption would.
    """

    items: list[RoutedEdge | RoutedNet] = [*edges, *nets]
    solid = list(solids)
    fixed: list[Rect] = []
    # A caption keeps off every line, its own included: beside a run it
    # clears it by construction, but beside a diagonal it would not.
    others = [line for _, line in lines]
    near = style.port_spacing.points
    labelled = [
        index
        for index, item in enumerate(items)
        if item.label_metrics is not None and item.label_position is not None
    ]
    candidates: dict[int, list[Point]] = {}
    for index in labelled:
        item = items[index]
        assert item.label_metrics is not None and item.label_position is not None
        if isinstance(item, RoutedEdge):
            candidates[index] = _candidates((item.centerline,), item.label_metrics, style)
        else:
            candidates[index] = [
                item.label_position,
                *_candidates(item.pieces, item.label_metrics, style),
            ]
    # Close beside another connector costs a little; a container outline (a
    # closed line) is not a connector.
    foreign = {
        index: [
            line
            for key, line in lines
            if key != items[index].spec.id and line[0] != line[-1]
        ]
        for index in labelled
    }
    chosen: dict[int, Point] = {}

    def box_of(index: int, position: Point) -> Rect:
        return label_box(position, items[index].label_metrics)  # type: ignore[arg-type]

    def price(index: int, position: Point, captions: Iterable[Rect]) -> float:
        box = box_of(index, position)
        return _price(box, solid, [*fixed, *captions], others, canvas) + NEAR_LINE * sum(
            1
            for line in foreign[index]
            if any(_crosses(box.inflated(near), a, b) for a, b in itertools.pairwise(line))
        )

    def placed_except(*skipped: int) -> list[Rect]:
        return [box_of(other, at) for other, at in chosen.items() if other not in skipped]

    def best_place(index: int, captions: list[Rect]) -> tuple[float, Point] | None:
        best: tuple[float, Point] | None = None
        for rank, position in enumerate(candidates[index]):
            cost = rank * 0.01 + price(index, position, captions)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, position)
            if cost < 1.0:
                break
        return best

    # The caption with the fewest clear places chooses first, so one that fits
    # in only one gap is not crowded out by one that would fit anywhere.
    order = sorted(
        labelled,
        key=lambda index: (
            sum(price(index, position, ()) < 1.0 for position in candidates[index]),
            index,
        ),
    )
    for index in order:
        best = best_place(index, placed_except())
        # No run to sit beside (the connector has no length): keep the
        # position it was given.
        chosen[index] = best[1] if best is not None else items[index].label_position  # type: ignore[assignment]
    # Repair: a caption left with no clear place takes one that a single other
    # caption blocks, when that caption has a clear place of its own elsewhere.
    for index in order:
        if price(index, chosen[index], placed_except(index)) < 1.0:
            continue
        for position in candidates[index]:
            if price(index, position, placed_except(index)) < 1.0:
                chosen[index] = position  # freed by an earlier repair
                break
            if price(index, position, ()) >= 1.0:
                continue
            box = box_of(index, position)
            blockers = [
                other
                for other, at in chosen.items()
                if other != index and box_of(other, at).intersects(box, strict=True)
            ]
            if len(blockers) != 1:
                continue
            blocker = blockers[0]
            captions = [*placed_except(index, blocker), box]
            moved = next(
                (
                    elsewhere
                    for elsewhere in candidates[blocker]
                    if price(blocker, elsewhere, captions) < 1.0
                ),
                None,
            )
            if moved is not None:
                chosen[index], chosen[blocker] = position, moved
                break
    result = list(items)
    for index, position in chosen.items():
        result[index] = replace(items[index], label_position=position)
    return result[: len(edges)], result[len(edges) :]  # type: ignore[return-value]


def _candidates(
    polylines: Iterable[tuple[Point, ...]], metrics: TextMetrics, style: LayoutStyle
) -> list[Point]:
    runs = [
        segment
        for points in polylines
        for segment in segments(points)
        if segment.length > 1e-6
    ]
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
