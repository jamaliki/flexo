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
from dataclasses import dataclass, replace

from flexo.geometry import Point, Rect, Segment, segment_crosses_rect, segments
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedEdge, RoutedNet
from flexo.routing.aside import Aside, line_reach, place_aside
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

CROWDED = 10.0
"""Price of a caption within two lanes of another connector's line.

Clear of it, but close enough that where lines converge -- the weights into a
perceptron's sum -- two captions end up side by side between two lines; a
place with open space round it reads as one line's own."""

AT_HEAD = 150.0
"""Price of a caption beside the arrowhead its line ends in.

There it reads as naming the part the line comes to, not the line: it goes along
the line instead, leaving the canvas to grow for it if it must."""

OUTSIDE = 100.0
"""Price of a caption leaving the canvas.

The cheapest defect: the canvas grows to take the caption on the next layout
round, while a caption over a line or a box stays there."""


def label_box(position: Point, metrics: TextMetrics) -> Rect:
    """The box a caption centred at ``position.x`` with its baseline at ``position.y`` fills."""

    top = position.y - metrics.baseline
    return Rect(position.x - metrics.width / 2.0, top, metrics.width, metrics.height)


@dataclass(frozen=True, slots=True)
class _Spot:
    """One place for a connector's writing: its caption, its aside, or both."""

    label: Point | None
    aside: Aside | None = None


def place_captions(
    edges: Sequence[RoutedEdge],
    nets: Sequence[RoutedNet],
    *,
    solids: Iterable[Rect],
    lines: Sequence[tuple[str, tuple[Point, ...]]],
    canvas: Rect,
    style: LayoutStyle,
    from_start: frozenset[str] = frozenset(),
) -> tuple[list[RoutedEdge], list[RoutedNet]]:
    """``edges`` and ``nets`` with each caption moved to its cheapest clear position.

    A net's caption first tries the place its tree reads along (see
    ``rail_label_position``), then the same places an edge's caption would.
    An edge in ``from_start`` -- a branch out of a decision -- tries the places
    nearest where it starts first, so "yes" and "no" sit by the question.
    An edge with an aside (``flexo.routing.aside``) places caption and aside
    together, one each side of the same point of its line.
    """

    items: list[RoutedEdge | RoutedNet] = [*edges, *nets]
    solid = list(solids)
    fixed: list[Rect] = []
    # A caption keeps off every line, its own included: beside a run it
    # clears it by construction, but beside a diagonal it would not.
    others = [line for _, line in lines]
    near = style.port_spacing.points
    candidates: dict[int, list[_Spot]] = {}
    for index, item in enumerate(items):
        if isinstance(item, RoutedEdge) and (item.aside_metrics or item.spec.arrow == "reversible"):
            if item.label_metrics is None and not item.aside_metrics:
                continue
            candidates[index] = _paired(item, style, from_start=item.spec.id in from_start)
            continue
        if item.label_metrics is None or item.label_position is None:
            continue
        if isinstance(item, RoutedEdge):
            places = _candidates(
                (item.centerline,),
                item.label_metrics,
                style,
                from_start=item.spec.id in from_start,
            )
        else:
            places = [item.label_position, *_candidates(item.pieces, item.label_metrics, style)]
        candidates[index] = [_Spot(place) for place in places]
    labelled = [index for index in candidates if candidates[index]]
    # Close beside another connector costs a little; a container outline (a
    # closed line) is not a connector.
    foreign = {
        index: [line for key, line in lines if key != items[index].spec.id and line[0] != line[-1]]
        for index in labelled
    }
    chosen: dict[int, _Spot] = {}

    def boxes_of(index: int, spot: _Spot) -> list[Rect]:
        item = items[index]
        boxes = []
        if spot.label is not None and item.label_metrics is not None:
            boxes.append(label_box(spot.label, item.label_metrics))
        if spot.aside is not None:
            boxes.append(spot.aside.box)
        return boxes

    def price(index: int, spot: _Spot, captions: Iterable[Rect]) -> float:
        captions = list(captions)
        cost = 0.0
        item = items[index]
        ends = isinstance(item, RoutedEdge) and item.spec.arrow == "end"
        head = item.centerline[-1] if ends else None
        for box in boxes_of(index, spot):
            cost += _price(box, solid, [*fixed, *captions], others, canvas)
            if head is not None and box.inflated(2.0 * near).contains_point(head):
                cost += AT_HEAD
            for line in foreign[index]:
                pieces = list(itertools.pairwise(line))
                if any(_crosses(box.inflated(near), a, b) for a, b in pieces):
                    cost += NEAR_LINE
                elif any(_crosses(box.inflated(2.0 * near), a, b) for a, b in pieces):
                    cost += CROWDED
        return cost

    def placed_except(*skipped: int) -> list[Rect]:
        return [
            box
            for other, at in chosen.items()
            if other not in skipped
            for box in boxes_of(other, at)
        ]

    def best_place(index: int, captions: list[Rect]) -> tuple[float, _Spot] | None:
        best: tuple[float, _Spot] | None = None
        for rank, spot in enumerate(candidates[index]):
            cost = rank * 0.01 + price(index, spot, captions)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, spot)
            if cost < 1.0:
                break
        return best

    # The caption with the fewest clear places chooses first, so one that fits
    # in only one gap is not crowded out by one that would fit anywhere.
    order = sorted(
        labelled,
        key=lambda index: (
            sum(price(index, spot, ()) < 1.0 for spot in candidates[index]),
            index,
        ),
    )
    for index in order:
        best = best_place(index, placed_except())
        assert best is not None
        chosen[index] = best[1]
    # Repair: a caption left with no clear place takes one that a single other
    # caption blocks, when moving that caption elsewhere costs the two of them
    # less in all -- a caption near a line is better than one over a line.
    for index in order:
        current = price(index, chosen[index], placed_except(index))
        if current < 1.0:
            continue
        for spot in candidates[index]:
            if price(index, spot, placed_except(index)) < 1.0:
                chosen[index] = spot  # freed by an earlier repair
                break
            if price(index, spot, ()) >= 1.0:
                continue
            boxes = boxes_of(index, spot)
            blockers = [
                other
                for other, at in chosen.items()
                if other != index
                and any(
                    theirs.intersects(box, strict=True)
                    for theirs in boxes_of(other, at)
                    for box in boxes
                )
            ]
            if len(blockers) != 1:
                continue
            blocker = blockers[0]
            captions = [*placed_except(index, blocker), *boxes]
            before = current + price(blocker, chosen[blocker], placed_except(blocker))
            cost, rank = min(
                (price(blocker, elsewhere, captions), rank)
                for rank, elsewhere in enumerate(candidates[blocker])
            )
            after = cost + price(index, spot, placed_except(index, blocker))
            if after < before - 1.0:
                chosen[index], chosen[blocker] = spot, candidates[blocker][rank]
                current = after - cost
                break
    result = list(items)
    for index, spot in chosen.items():
        item = items[index]
        if isinstance(item, RoutedEdge):
            result[index] = replace(
                item,
                label_position=spot.label if spot.label is not None else item.label_position,
                aside=spot.aside,
            )
        elif spot.label is not None:
            result[index] = replace(item, label_position=spot.label)
    return result[: len(edges)], result[len(edges) :]  # type: ignore[return-value]


def _runs(
    polylines: Iterable[tuple[Point, ...]], *, from_start: bool = False
) -> list[tuple[float, Segment]]:
    """The places along ``polylines`` a caption may sit by, most preferred first."""

    runs = [
        segment for points in polylines for segment in segments(points) if segment.length > 1e-6
    ]
    if from_start:
        return [(fraction, segment) for segment in runs for fraction in sorted(FRACTIONS)]
    horizontal = sorted(
        (segment for segment in runs if segment.horizontal), key=lambda s: -s.length
    )
    vertical = sorted(
        (segment for segment in runs if not segment.horizontal), key=lambda s: -s.length
    )  # vertical runs, and the diagonals of straight edges
    return [(fraction, segment) for fraction in FRACTIONS for segment in (*horizontal, *vertical)]


def _paired(edge: RoutedEdge, style: LayoutStyle, *, from_start: bool) -> list[_Spot]:
    """Places for a caption and an aside together, one each side of the line.

    The caption keeps its classic side -- above a horizontal run, right of a
    vertical one -- with the aside across the line from it; then the two swap.
    A reversible connector's writing stands clear of both its lines.
    """

    metrics = edge.label_metrics
    extra = line_reach(edge.spec, style)
    spots: list[_Spot] = []
    for fraction, segment in _runs((edge.centerline,), from_start=from_start):
        short = metrics is not None and segment.length < metrics.width * 0.6
        if segment.horizontal and short and fraction != 0.5:
            continue
        at = Point(
            segment.start.x + (segment.end.x - segment.start.x) * fraction,
            segment.start.y + (segment.end.y - segment.start.y) * fraction,
        )
        along = Point(
            (segment.end.x - segment.start.x) / segment.length,
            (segment.end.y - segment.start.y) / segment.length,
        )
        if segment.horizontal:
            first = Point(0.0, -1.0)
        elif segment.vertical:
            first = Point(1.0, 0.0)
        else:
            first = Point(-along.y, along.x)
        for side in (first, Point(-first.x, -first.y)):
            label = _beside(at, side, metrics, style, extra) if metrics is not None else None
            across = Point(-side.x, -side.y)
            aside = (
                place_aside(edge.spec, edge.aside_metrics, at, along, across, style)
                if edge.aside_metrics
                else None
            )
            spots.append(_Spot(label, aside))
    return spots


def _beside(
    at: Point, side: Point, metrics: TextMetrics, style: LayoutStyle, extra: float
) -> Point:
    """A caption's position beside ``at``, on the side ``side`` points to."""

    if abs(side.x) < 1e-9 and side.y < 0.0:
        return at.translated(dy=-(extra + caption_rise(metrics, style)))
    half = abs(side.x) * metrics.width / 2.0 + abs(side.y) * metrics.height / 2.0
    distance = extra + caption_reach(metrics, style) + half
    centre = Point(at.x + side.x * distance, at.y + side.y * distance)
    return Point(centre.x, centre.y - metrics.height / 2.0 + metrics.baseline)


def _candidates(
    polylines: Iterable[tuple[Point, ...]],
    metrics: TextMetrics,
    style: LayoutStyle,
    *,
    from_start: bool = False,
) -> list[Point]:
    """Places for a caption beside ``polylines``, most preferred first.

    By default the longest horizontal runs come first, at their middles; with
    ``from_start`` the runs are taken in the order the line draws them, each
    from the end nearest its start -- a decision's "yes" beside the decision.
    """

    order = _runs(polylines, from_start=from_start)
    rise = caption_rise(metrics, style)
    reach = caption_reach(metrics, style)
    candidates: list[Point] = []
    for fraction, segment in order:
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


TOUCH = 1.0
"""How far (points) a caption keeps from a component it would otherwise touch."""


def _price(
    box: Rect,
    solids: list[Rect],
    placed: list[Rect],
    lines: list[tuple[Point, ...]],
    canvas: Rect,
) -> float:
    cost = 0.0
    # A caption touching a box's edge reads as part of the box: it keeps a hair off.
    near = box.inflated(TOUCH)
    for rect in solids:
        if rect.intersects(near, strict=True):
            cost += OVERLAP
    for rect in placed:
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
