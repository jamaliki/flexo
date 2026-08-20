"""Route cleanup: shaft trimming, zigzag collapse, and parallel-track nudging."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

from flexo.components import TRANSPARENT_KINDS, route_clearance
from flexo.geometry import Point, Rect, Segment, segments
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedEdge, RoutedFigure, RoutedNet, RoutedStem
from flexo.style import LayoutStyle
from flexo.text import ink_descent

_EPSILON = 1e-7
_NUDGE_OBSTACLE_FRACTION = 0.5
"""Fraction of the routing clearance a nudged track must keep from a component."""


def shorten_end(points: tuple[Point, ...], distance: float) -> tuple[Point, ...]:
    """Shorten an orthogonal polyline while preserving its earlier vertices."""
    if not points or distance <= 0.0:
        return points
    remaining = distance
    result = list(points)
    while len(result) >= 2:
        end = result[-1]
        previous = result[-2]
        segment_length = previous.distance_to(end)
        if segment_length > remaining:
            ratio = (segment_length - remaining) / segment_length
            result[-1] = Point(
                previous.x + (end.x - previous.x) * ratio,
                previous.y + (end.y - previous.y) * ratio,
            )
            return tuple(result)
        remaining -= segment_length
        result.pop()
    return (points[0],)


def shorten_start(points: tuple[Point, ...], distance: float) -> tuple[Point, ...]:
    """Shorten an orthogonal polyline from its head, preserving its later vertices."""
    if not points or distance <= 0.0:
        return points
    remaining = distance
    result = list(points)
    while len(result) >= 2:
        start = result[0]
        following = result[1]
        segment_length = following.distance_to(start)
        if segment_length > remaining:
            ratio = (segment_length - remaining) / segment_length
            result[0] = Point(
                following.x + (start.x - following.x) * ratio,
                following.y + (start.y - following.y) * ratio,
            )
            return tuple(result)
        remaining -= segment_length
        result.pop(0)
    return (points[-1],)


def edge_shaft(
    centerline: tuple[Point, ...],
    *,
    arrow_length: float,
    standoff: float,
) -> tuple[Point, ...]:
    """The painted polyline for a port-to-port centerline.

    Both trims are ink-only; the centerline itself stays port-to-port. The arrow
    marker is anchored at the path end with its tip a full ``arrow_length``
    further on, so trimming ``arrow_length + standoff`` leaves the tip
    ``standoff`` short of the target port.
    """

    return shorten_start(shorten_end(centerline, arrow_length + standoff), standoff)


def simplify_polyline(points: tuple[Point, ...]) -> tuple[Point, ...]:
    """Drop repeated vertices and merge collinear runs."""
    result: list[Point] = []
    for point in points:
        if result and point == result[-1]:
            continue
        if len(result) >= 2:
            first, middle = result[-2:]
            if (first.x == middle.x == point.x) or (first.y == middle.y == point.y):
                result[-1] = point
                continue
        result.append(point)
    return tuple(result)


def caption_rise(metrics: TextMetrics, style: LayoutStyle) -> float:
    """How far above a run's centerline a caption's baseline has to sit.

    A connector caption is route geometry, not a node, so the caption-obstacle
    rule that keeps routes off component captions cannot reach it: nothing stops
    a caption of its own from landing on the arrow it labels. This is the same
    clearance measured from the other side -- half the shaft's stroke, then
    ``caption_clearance`` of air, then the depth of the caption's own lowest ink,
    which is what a subscript makes deeper than the font's descender.
    """

    return (
        style.connector_width.points / 2.0
        + style.caption_clearance.points
        + ink_descent(metrics, style.typography)
    )


def caption_reach(metrics: TextMetrics, style: LayoutStyle) -> float:
    """How far beside a run's centerline a caption's near edge has to sit."""

    return style.connector_width.points / 2.0 + style.caption_clearance.points


def edge_label_position(
    points: tuple[Point, ...],
    metrics: TextMetrics,
    style: LayoutStyle,
) -> Point:
    candidates = segments(points)
    horizontal = tuple(segment for segment in candidates if segment.horizontal)
    longest = max(horizontal or candidates, key=lambda segment: segment.length)
    midpoint = Point(
        (longest.start.x + longest.end.x) / 2.0,
        (longest.start.y + longest.end.y) / 2.0,
    )
    if longest.horizontal:
        return midpoint.translated(dy=-caption_rise(metrics, style))
    return midpoint.translated(dx=metrics.width / 2.0 + caption_reach(metrics, style))


def rail_label_position(
    rail: tuple[Point, ...],
    stems: tuple[tuple[Point, ...], ...],
    metrics: TextMetrics,
    style: LayoutStyle,
) -> Point:
    """Anchor a net caption above the horizontal run the net reads along.

    A net's caption belongs to its *arrow*, not to its rail: panel-b writes
    ``softmax(QK^T)V`` above the horizontal run that carries Q into the attended
    value, and that run is a source stem, a stretch of rail and a target stem
    drawn as one line. So the anchor is the midpoint of the longest horizontal
    run the net draws -- collinear pieces counted as one -- and a net whose ink
    is purely vertical keeps its rail midpoint, captioned beside it.

    The run is not all the words have to clear. A riser climbing out of either
    end of it -- in panel-b the one carrying K and V up to the merge -- passes
    straight through the band the caption occupies, so the ends the risers claim
    come off the run before the caption is centred on what is left.
    """

    runs: dict[float, list[Segment]] = {}
    risers: list[Segment] = []
    for polyline in (rail, *stems):
        for segment in segments(polyline):
            if segment.length <= _EPSILON:
                continue
            if segment.horizontal:
                runs.setdefault(segment.start.y, []).append(segment)
            else:
                risers.append(segment)
    if runs:
        coordinate = min(
            runs,
            key=lambda value: (-sum(segment.length for segment in runs[value]), value),
        )
        bounds = tuple(
            value
            for segment in runs[coordinate]
            for value in (segment.start.x, segment.end.x)
        )
        centre = _captioned_centre(
            min(bounds),
            max(bounds),
            coordinate,
            risers,
            metrics.width,
            caption_reach(metrics, style),
        )
        return Point(centre, coordinate - caption_rise(metrics, style))
    first, last = rail[0], rail[-1]
    midpoint = Point((first.x + last.x) / 2.0, (first.y + last.y) / 2.0)
    return midpoint.translated(dx=metrics.width / 2.0 + caption_reach(metrics, style))


def _captioned_centre(
    left: float,
    right: float,
    coordinate: float,
    risers: list[Segment],
    width: float,
    clearance: float,
) -> float:
    """Centre a caption on the stretch of run no riser reaches up through.

    A riser that climbs out of the middle of the run cuts it in two -- panel-b's
    K,V riser leaves the merge run a long stretch on one side and a stub on the
    other -- so the caption takes the widest stretch that is left, not the
    midpoint of a run it would be sitting across.
    """

    free = [(left, right)]
    for riser in risers:
        if min(riser.start.y, riser.end.y) >= coordinate - _EPSILON:
            continue  # Drops away below the run; the caption sits above it.
        blocked = (riser.start.x - clearance, riser.start.x + clearance)
        free = [piece for span in free for piece in _without(span, blocked)]
    if not free:
        return (left + right) / 2.0
    start, end = max(free, key=lambda span: span[1] - span[0])
    if end - start >= width:
        return (start + end) / 2.0
    # More words than the widest stretch holds. Centre them on it anyway -- it is
    # still the best place on the run -- but keep the overflow over the run
    # itself rather than out past its ends.
    return min(max((start + end) / 2.0, left + width / 2.0), right - width / 2.0)


_Span = tuple[float, float]


def _without(span: _Span, blocked: _Span) -> tuple[_Span, ...]:
    """``span`` with ``blocked`` cut out of it: nothing, one piece, or two."""

    pieces = ((span[0], min(span[1], blocked[0])), (max(span[0], blocked[1]), span[1]))
    return tuple(piece for piece in pieces if piece[1] - piece[0] > _EPSILON)


@dataclass(frozen=True, slots=True)
class Stubs:
    """Minimum lengths the first and final segments of a route must keep."""

    head: float = 0.0
    tail: float = 0.0


NO_STUBS = Stubs()


def collapse_zigzags(
    points: tuple[Point, ...],
    obstacles: tuple[Rect, ...],
    radius: float,
    occupied: tuple[Segment, ...] = (),
    separation: float = 0.0,
    stubs: Stubs = NO_STUBS,
) -> tuple[Point, ...]:
    """Straighten interior micro-jogs whose offset is smaller than two elbows.

    Only interior vertices move, and the first and final segments keep their
    departure direction and their minimum stub length, so ports and net
    junctions survive untouched.
    """

    current = simplify_polyline(points)
    runs = segments(current)
    if len(runs) < 3:
        return current
    head_axis = _direction(runs[0])
    tail_axis = _direction(runs[-1])
    limit = 2.0 * radius
    while True:
        replacement = _collapse_once(
            current,
            obstacles,
            limit,
            occupied,
            separation,
            stubs,
            head_axis,
            tail_axis,
        )
        if replacement is None:
            return current
        current = replacement


def _direction(segment: Segment) -> tuple[int, int]:
    delta_x = segment.end.x - segment.start.x
    delta_y = segment.end.y - segment.start.y
    return (
        0 if abs(delta_x) <= _EPSILON else (1 if delta_x > 0.0 else -1),
        0 if abs(delta_y) <= _EPSILON else (1 if delta_y > 0.0 else -1),
    )


def _collapse_once(
    points: tuple[Point, ...],
    obstacles: tuple[Rect, ...],
    limit: float,
    occupied: tuple[Segment, ...],
    separation: float,
    stubs: Stubs,
    head_axis: tuple[int, int],
    tail_axis: tuple[int, int],
) -> tuple[Point, ...] | None:
    for index in range(1, len(points) - 2):
        before = Segment(points[index - 1], points[index])
        middle = Segment(points[index], points[index + 1])
        after = Segment(points[index + 1], points[index + 2])
        if not 0.0 < middle.length < limit:
            continue
        if before.horizontal != after.horizontal or before.horizontal == middle.horizontal:
            continue
        for candidate in _aligned_variants(points, index, before.horizontal):
            simplified = simplify_polyline(candidate)
            runs = segments(simplified)
            if len(runs) < 2:
                continue
            if _direction(runs[0]) != head_axis or _direction(runs[-1]) != tail_axis:
                continue
            if runs[0].length + _EPSILON < stubs.head:
                continue
            if runs[-1].length + _EPSILON < stubs.tail:
                continue
            if _polyline_is_clear(simplified, obstacles, occupied, separation):
                return simplified
    return None


def _aligned_variants(
    points: tuple[Point, ...],
    index: int,
    horizontal: bool,
) -> tuple[tuple[Point, ...], ...]:
    """Both ways of removing the jog: align the later run, or the earlier one."""

    near = points[index - 1]
    far = points[index + 2]
    variants: list[tuple[Point, ...]] = []
    if index + 2 < len(points) - 1:
        moved = Point(far.x, near.y) if horizontal else Point(near.x, far.y)
        variants.append((*points[:index], moved, *points[index + 3 :]))
    if index >= 2:
        moved = Point(near.x, far.y) if horizontal else Point(far.x, near.y)
        variants.append((*points[: index - 1], moved, *points[index + 2 :]))
    return tuple(variants)


def _polyline_is_clear(
    points: tuple[Point, ...],
    obstacles: tuple[Rect, ...],
    occupied: tuple[Segment, ...],
    separation: float,
) -> bool:
    for segment in segments(points):
        if not segment.orthogonal:
            return False
        if any(segment.intersects_rect_interior(obstacle) for obstacle in obstacles):
            return False
        if separation > 0.0 and any(
            _too_close(segment, other, separation) for other in occupied
        ):
            return False
    return True


def _too_close(first: Segment, second: Segment, minimum: float) -> bool:
    if first.horizontal and second.horizontal:
        distance = abs(first.start.y - second.start.y)
        overlap = _overlap(first.start.x, first.end.x, second.start.x, second.end.x)
    elif first.vertical and second.vertical:
        distance = abs(first.start.x - second.start.x)
        overlap = _overlap(first.start.y, first.end.y, second.start.y, second.end.y)
    else:
        return False
    return overlap > _EPSILON and distance + _EPSILON < minimum


def _overlap(first_a: float, first_b: float, second_a: float, second_b: float) -> float:
    first_low, first_high = sorted((first_a, first_b))
    second_low, second_high = sorted((second_a, second_b))
    return max(0.0, min(first_high, second_high) - max(first_low, second_low))


@dataclass(frozen=True, slots=True)
class Run:
    """One routed polyline plus what ties it to the rest of the figure."""

    owner: str
    key: str
    boundary: Rect
    stubs: Stubs = NO_STUBS
    rail: bool = False
    junction: int | None = None
    """Index of the vertex pinned to this run's owning rail, if any."""
    pinned: bool = False
    """True when the author placed this run themselves and nudging may not move it."""
    hinted: bool = False
    """True when the author aimed this route -- a lane, a waypoint, a ``via`` side.

    Such a route keeps the corridor it was sent through, so the jog-balancing
    default below leaves it alone. Lane nudging still applies: spacing two runs a
    lane apart is not a change of route.
    """


@dataclass(frozen=True, slots=True)
class _Corridor:
    """A movable straight run and everything that travels with it."""

    key: str
    owner: str
    horizontal: bool
    coordinate: float
    low: float
    high: float
    pins: tuple[tuple[int, int], ...]
    slack: float


def balance_jogs(
    runs: tuple[Run, ...],
    polylines: tuple[tuple[Point, ...], ...],
    *,
    style: LayoutStyle,
    obstacles: tuple[Rect, ...],
) -> tuple[tuple[Point, ...], ...]:
    """Centre the crossbar of every single-jog route in the run it has free.

    A Z -- two parallel end segments pointing the same way, joined by one crossbar
    -- has a whole span to put that crossbar in, and the search that found the
    route took whichever coordinate it reached first. Against one endpoint the
    shape reads as an L with a kink in it; in the middle it reads as the step
    across it is, with an arm of the same length on either side. So the default is
    the midpoint of the crossbar's free span: the stretch between the two
    endpoints' clearance boundaries, less anything an obstacle takes out of it.

    A C -- end segments pointing *opposite* ways, which is how a route wraps a
    module or runs back up a margin -- is left alone. Its crossbar has no span
    between the endpoints to be centred in: the two arms overlap, and the corridor
    it sits in was chosen against the whole figure rather than between two ports.

    Every move is provisional. It is kept only if it leaves no route touching an
    obstacle, crowding another lane, or losing a port stub that was intact before
    -- which is also what keeps a fan of parallel jogs spread: the second of them
    to reach for the shared midpoint finds the first already there.
    """

    spacing = style.port_spacing.points
    current = polylines
    baseline = _defects(current, runs, obstacles, spacing, polylines)
    for index, run in enumerate(runs):
        if run.rail or run.pinned or run.hinted:
            continue
        candidate = _balanced_jog(current[index], run, obstacles)
        if candidate is None:
            continue
        trial = (*current[:index], candidate, *current[index + 1 :])
        if not _no_worse(_defects(trial, runs, obstacles, spacing, polylines), baseline):
            continue
        current = trial
    return current


def _balanced_jog(
    points: tuple[Point, ...],
    run: Run,
    obstacles: tuple[Rect, ...],
) -> tuple[Point, ...] | None:
    """``points`` with its one crossbar moved to the middle of its free span."""

    simplified = simplify_polyline(points)
    runs = segments(simplified)
    if len(runs) != 3:
        return None
    first, crossbar, last = runs
    if first.horizontal != last.horizontal or first.horizontal == crossbar.horizontal:
        return None
    if _direction(first) != _direction(last):
        return None  # A C, not a Z: the arms double back over each other.
    horizontal = first.horizontal
    step = _direction(first)[0] if horizontal else _direction(first)[1]
    head, tail = run.stubs.head, run.stubs.tail
    start = (simplified[0].x if horizontal else simplified[0].y) + step * head
    end = (simplified[3].x if horizontal else simplified[3].y) - step * tail
    low, high = sorted((start, end))
    coordinate = crossbar.start.x if horizontal else crossbar.start.y
    low, high = _free_span(crossbar, obstacles, coordinate, horizontal, low, high)
    if high - low <= _EPSILON:
        return None
    target = (low + high) / 2.0
    if abs(target - coordinate) <= _EPSILON:
        return None
    moved = tuple(
        Point(target, point.y) if horizontal else Point(point.x, target)
        for point in simplified[1:3]
    )
    return (simplified[0], *moved, simplified[3])


def _free_span(
    crossbar: Segment,
    obstacles: tuple[Rect, ...],
    coordinate: float,
    horizontal: bool,
    low: float,
    high: float,
) -> tuple[float, float]:
    """``[low, high]`` narrowed to the obstacle-free stretch holding ``coordinate``.

    An obstacle counts when it stands across the crossbar's own extent: such a box
    is what the crossbar would have to cut through, so the span stops at its near
    edge. One standing clear of that extent is behind or in front of the crossing
    and takes nothing away from it.

    That one test covers the arms as well. Each arm runs at one end of the
    crossbar's extent, so a box in an arm's way reaches into that extent by
    definition, and the near edge that stops the crossbar is the same edge that
    stops the arm sweeping over it.
    """

    span_low, span_high = (
        sorted((crossbar.start.y, crossbar.end.y))
        if horizontal
        else sorted((crossbar.start.x, crossbar.end.x))
    )
    for obstacle in obstacles:
        low_across, high_across = (
            (obstacle.top, obstacle.bottom) if horizontal else (obstacle.left, obstacle.right)
        )
        if low_across >= span_high - _EPSILON or high_across <= span_low + _EPSILON:
            continue
        near, far = (
            (obstacle.left, obstacle.right) if horizontal else (obstacle.top, obstacle.bottom)
        )
        if near < coordinate < far:
            return coordinate, coordinate
        if far <= coordinate:
            low = max(low, far)
        else:
            high = min(high, near)
    return low, high


def nudge_routes(
    runs: tuple[Run, ...],
    polylines: tuple[tuple[Point, ...], ...],
    *,
    style: LayoutStyle,
    obstacles: tuple[Rect, ...],
) -> tuple[tuple[Point, ...], ...]:
    """Redistribute shared corridors so parallel tracks sit one lane apart."""

    spacing = style.port_spacing.points
    if spacing <= 0.0:
        return polylines
    current = polylines
    baseline = _defects(current, runs, obstacles, spacing, polylines)
    for group in _corridor_groups(_corridors(current, runs), spacing):
        candidate = _apply_group(current, group, spacing)
        if candidate is None:
            continue
        if not _no_worse(_defects(candidate, runs, obstacles, spacing, polylines), baseline):
            continue
        current = candidate
    return current


def _corridors(
    polylines: tuple[tuple[Point, ...], ...],
    runs: tuple[Run, ...],
) -> tuple[_Corridor, ...]:
    rails = {run.owner: index for index, run in enumerate(runs) if run.rail}
    attached: dict[int, list[tuple[int, int]]] = {index: [] for index in rails.values()}
    for index, run in enumerate(runs):
        if run.rail or run.junction is None or run.owner not in rails:
            continue
        attached[rails[run.owner]].append((index, run.junction % len(polylines[index])))
    result: list[_Corridor] = []
    for index, run in enumerate(runs):
        if run.pinned:
            continue
        points = polylines[index]
        count = len(points) - 1
        movable = (0,) if run.rail and count == 1 else tuple(range(1, count - 1))
        for position in movable:
            segment = Segment(points[position], points[position + 1])
            if not segment.orthogonal or segment.length <= _EPSILON:
                continue
            pins = ((index, position), (index, position + 1))
            if run.rail:
                pins = pins + tuple(attached[index])
            slack = _slack(polylines, pins, segment.horizontal)
            if slack <= _EPSILON:
                continue
            low, high = (
                sorted((segment.start.x, segment.end.x))
                if segment.horizontal
                else sorted((segment.start.y, segment.end.y))
            )
            result.append(
                _Corridor(
                    f"{run.key}#{position}",
                    run.owner,
                    segment.horizontal,
                    segment.start.y if segment.horizontal else segment.start.x,
                    low,
                    high,
                    pins,
                    slack,
                )
            )
    return tuple(sorted(result, key=lambda corridor: corridor.key))


def _slack(
    polylines: tuple[tuple[Point, ...], ...],
    pins: tuple[tuple[int, int], ...],
    horizontal: bool,
) -> float:
    """How far the pinned vertices may travel before a neighbour run vanishes."""

    moved = set(pins)
    limit = float("inf")
    for polyline_index, point_index in pins:
        points = polylines[polyline_index]
        anchor = points[point_index]
        for neighbour in (point_index - 1, point_index + 1):
            if not 0 <= neighbour < len(points):
                continue
            if (polyline_index, neighbour) in moved:
                continue
            other = points[neighbour]
            travel = abs(other.y - anchor.y) if horizontal else abs(other.x - anchor.x)
            limit = min(limit, travel)
    return 0.0 if limit == float("inf") else limit


def _corridor_groups(
    corridors: tuple[_Corridor, ...],
    spacing: float,
) -> tuple[tuple[_Corridor, ...], ...]:
    parent = list(range(len(corridors)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for (first, one), (second, two) in combinations(enumerate(corridors), 2):
        if one.horizontal != two.horizontal or one.owner == two.owner:
            continue
        if abs(one.coordinate - two.coordinate) >= spacing:
            continue
        if _overlap(one.low, one.high, two.low, two.high) <= _EPSILON:
            continue
        parent[find(first)] = find(second)
    buckets: dict[int, list[_Corridor]] = {}
    for index, corridor in enumerate(corridors):
        buckets.setdefault(find(index), []).append(corridor)
    return tuple(
        tuple(sorted(members, key=lambda item: (item.coordinate, item.key)))
        for _, members in sorted(buckets.items())
        if len(members) > 1
    )


def _apply_group(
    polylines: tuple[tuple[Point, ...], ...],
    group: tuple[_Corridor, ...],
    spacing: float,
) -> tuple[tuple[Point, ...], ...] | None:
    count = len(group)
    mean = sum(corridor.coordinate for corridor in group) / count
    shifts = tuple(
        mean + (position - (count - 1) / 2.0) * spacing - corridor.coordinate
        for position, corridor in enumerate(group)
    )
    if all(abs(shift) <= _EPSILON for shift in shifts):
        return None
    if any(
        abs(shift) + _EPSILON >= corridor.slack
        for shift, corridor in zip(shifts, group, strict=True)
    ):
        return None
    result = [list(points) for points in polylines]
    for shift, corridor in zip(shifts, group, strict=True):
        for polyline_index, point_index in corridor.pins:
            point = result[polyline_index][point_index]
            result[polyline_index][point_index] = (
                point.translated(dy=shift) if corridor.horizontal else point.translated(dx=shift)
            )
    return tuple(tuple(points) for points in result)


def _defects(
    polylines: tuple[tuple[Point, ...], ...],
    runs: tuple[Run, ...],
    obstacles: tuple[Rect, ...],
    spacing: float,
    original: tuple[tuple[Point, ...], ...],
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    blocked: set[tuple[str, str]] = set()
    for index, run in enumerate(runs):
        points = polylines[index]
        if any(not run.boundary.contains_point(point) for point in points):
            blocked.add((run.key, "boundary"))
        if not _stubs_intact(points, original[index], run.stubs):
            blocked.add((run.key, "stub"))
        # Port stubs always sit inside their own component's clearance ring and
        # never move, so only the interior runs are judged against obstacles.
        # A rail owns no port, so every one of its segments counts.
        run_segments = segments(points)
        judged = run_segments if run.rail else run_segments[1:-1]
        if any(
            not segment.orthogonal
            or any(segment.intersects_rect_interior(obstacle) for obstacle in obstacles)
            for segment in judged
        ):
            blocked.add((run.key, "obstacle"))
    close: set[tuple[str, str]] = set()
    for (first, one), (second, two) in combinations(enumerate(runs), 2):
        if one.owner == two.owner:
            continue
        pair = (one.owner, two.owner) if one.owner < two.owner else (two.owner, one.owner)
        if pair in close:
            continue
        if any(
            _too_close(left, right, spacing)
            for left in segments(polylines[first])
            for right in segments(polylines[second])
        ):
            close.add(pair)
    return frozenset(blocked), frozenset(close)


def _stubs_intact(
    points: tuple[Point, ...],
    original: tuple[Point, ...],
    stubs: Stubs,
) -> bool:
    """The port stubs keep their direction and their reserved clearance."""

    runs = segments(points)
    reference = segments(original)
    if not runs or not reference:
        return True
    if _direction(runs[0]) != _direction(reference[0]):
        return False
    if _direction(runs[-1]) != _direction(reference[-1]):
        return False
    return (
        runs[0].length + _EPSILON >= stubs.head and runs[-1].length + _EPSILON >= stubs.tail
    )


def _no_worse(
    candidate: tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]],
    baseline: tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]],
) -> bool:
    return candidate[0] <= baseline[0] and candidate[1] <= baseline[1]


def figure_runs(
    routed: RoutedFigure,
    boundaries: dict[str, Rect],
    style: LayoutStyle,
) -> tuple[tuple[Run, ...], tuple[tuple[Point, ...], ...]]:
    """Flatten every routed centerline, rail, and stem into one indexed list."""

    departure = style.route_clearance.points
    arrival = style.arrival_clearance.points
    runs: list[Run] = []
    polylines: list[tuple[Point, ...]] = []
    for edge in routed.edges:
        runs.append(
            Run(
                edge.spec.id,
                edge.spec.id,
                boundaries[edge.spec.id],
                Stubs(departure, arrival),
                hinted=bool(edge.spec.lane_hint or edge.spec.waypoints or edge.spec.via),
            )
        )
        polylines.append(edge.centerline)
    for net in routed.nets:
        boundary = boundaries[net.spec.id]
        hinted = bool(net.spec.rail_hint or net.spec.rail_at is not None or net.spec.via)
        runs.append(
            Run(
                net.spec.id,
                f"{net.spec.id}.rail",
                boundary,
                rail=True,
                pinned=net.spec.rail_at is not None,
                hinted=hinted,
            )
        )
        polylines.append(net.rail)
        for index, stem in enumerate(net.source_stems):
            runs.append(
                Run(
                    net.spec.id,
                    f"{net.spec.id}.source.{index}",
                    boundary,
                    Stubs(head=departure),
                    junction=-1,
                    hinted=hinted,
                )
            )
            polylines.append(stem.centerline)
        for index, stem in enumerate(net.target_stems):
            runs.append(
                Run(
                    net.spec.id,
                    f"{net.spec.id}.target.{index}",
                    boundary,
                    Stubs(tail=arrival),
                    junction=0,
                    hinted=hinted,
                )
            )
            polylines.append(stem.centerline)
    return tuple(runs), tuple(polylines)


def rebuild_figure(
    routed: RoutedFigure,
    polylines: tuple[tuple[Point, ...], ...],
    style: LayoutStyle,
) -> RoutedFigure:
    """Re-derive shafts and label anchors from nudged centerlines."""

    arrow_length = style.arrow_length.points
    standoff = style.connector_standoff.points
    position = 0
    edges: list[RoutedEdge] = []
    for edge in routed.edges:
        centerline = simplify_polyline(polylines[position])
        position += 1
        edges.append(
            replace(
                edge,
                centerline=centerline,
                shaft=edge_shaft(centerline, arrow_length=arrow_length, standoff=standoff),
                label_position=(
                    edge_label_position(centerline, edge.label_metrics, style)
                    if edge.label_metrics is not None
                    else None
                ),
            )
        )
    nets: list[RoutedNet] = []
    for net in routed.nets:
        rail = polylines[position]
        position += 1
        source_stems: list[RoutedStem] = []
        for stem in net.source_stems:
            centerline = simplify_polyline(polylines[position])
            position += 1
            source_stems.append(
                replace(
                    stem,
                    centerline=centerline,
                    shaft=shorten_start(centerline, standoff),
                )
            )
        target_stems: list[RoutedStem] = []
        for stem in net.target_stems:
            centerline = simplify_polyline(polylines[position])
            position += 1
            target_stems.append(
                replace(
                    stem,
                    centerline=centerline,
                    shaft=shorten_end(centerline, arrow_length + standoff),
                )
            )
        nets.append(
            replace(
                net,
                rail=rail,
                source_stems=tuple(source_stems),
                target_stems=tuple(target_stems),
                label_position=(
                    rail_label_position(
                        rail,
                        tuple(stem.shaft for stem in (*source_stems, *target_stems)),
                        net.label_metrics,
                        style,
                    )
                    if net.label_metrics is not None
                    else None
                ),
            )
        )
    return replace(routed, edges=tuple(edges), nets=tuple(nets))


def nudge_obstacles(
    routed: RoutedFigure,
    style: LayoutStyle,
    fraction: float = _NUDGE_OBSTACLE_FRACTION,
) -> tuple[Rect, ...]:
    """Component bounds a post-pass may not approach, at ``fraction`` of clearance.

    Lane nudging asks for half a clearance: it moves a run a lane at a time to
    separate it from another run, and refusing a move that ends a couple of points
    nearer a box than the router would have gone leaves the runs on top of each
    other instead. Jog balancing asks for the whole of it, because it is choosing
    where a crossing goes rather than rescuing one, and the whole clearance is what
    "clear of that box" means everywhere else in the router.
    """

    return tuple(
        node.bounds.inflated(route_clearance(node.measured.spec, style) * fraction)
        for node in routed.fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    )
