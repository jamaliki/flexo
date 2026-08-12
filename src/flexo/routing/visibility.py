"""Orthogonal visibility graph construction and deterministic path search."""

from __future__ import annotations

import heapq
from bisect import bisect_left, insort
from collections import defaultdict
from dataclasses import dataclass
from itertools import count, pairwise

from flexo.geometry import Point, Rect, Segment

_EPSILON = 1e-8
_MERGE_TOLERANCE = 0.5
"""Candidate coordinates closer than this (in points) collapse onto one track."""


@dataclass(frozen=True, slots=True)
class PathCosts:
    """Route quality prices. Every field except ``bend`` is in points of length.

    Pricing the untidiness in length means a detour is taken only when it is
    shorter than the defect it avoids, instead of at any cost.
    """

    bend: float
    crossing: float = 80.0
    overlap: float = 20.0
    """Cost per point of length shared with an existing parallel track.

    A rate rather than a flat charge, so the total does not depend on how many
    candidate coordinates a run happens to be split across.
    """

    separation: float = 0.0
    clearance: float = 0.0
    hug: float = 0.25
    """Extra cost per point of length for a run grazing an obstacle boundary.

    It rides on the distance term, never on the bend term, so centring a run in
    its gutter can never buy an extra elbow.
    """

    confinement: float = 0.3
    """Extra cost per point of length spent inside a container the route leaves."""


@dataclass(frozen=True, slots=True)
class _Track:
    """An occupied orthogonal run reduced to numbers for tight cost loops."""

    horizontal: bool
    coordinate: float
    low: float
    high: float


def shortest_orthogonal_path(
    start: Point,
    end: Point,
    obstacles: tuple[Rect, ...],
    *,
    costs: PathCosts,
    occupied: tuple[Segment, ...] = (),
    boundary: Rect | None = None,
    confined: tuple[Rect, ...] = (),
    departure: bool | None = None,
    arrival: bool | None = None,
) -> tuple[Point, ...] | None:
    """The cheapest orthogonal route, counting bends against the port stubs.

    ``departure`` and ``arrival`` state whether the fixed stub before ``start``
    and after ``end`` runs horizontally. Supplying them makes the bend count
    match the assembled route instead of the leg in isolation. ``confined``
    holds containers the route owns but should leave promptly.
    """

    if start == end:
        return (start,)
    if boundary is not None and not (
        boundary.contains_point(start) and boundary.contains_point(end)
    ):
        return None
    tracks = _tracks(occupied, boundary, costs.separation)
    direct = _direct_path(start, end, obstacles, tracks, costs)
    if direct is not None:
        return direct
    points, relevant = _candidate_points(start, end, obstacles, boundary, tracks, costs)
    if not points:
        return None
    index = {point: position for position, point in enumerate(points)}
    adjacency = _visibility_edges(points, relevant)
    start_index = index[start]
    end_index = index[end]

    # State orientation: 0 initial, 1 horizontal, 2 vertical.
    # Cost order: sharing a lane at all is a publication defect, so it outranks
    # elbow count. Everything else -- crossings, grazing, container confinement
    # -- is priced in points of length, so avoiding it trades against detours.
    initial = 0 if departure is None else (1 if departure else 2)
    frontier: list[tuple[int, int, float, float, int, int, int]] = []
    serial = count()
    heapq.heappush(frontier, (0, 0, 0.0, 0.0, next(serial), start_index, initial))
    best: dict[tuple[int, int], tuple[int, int, float, float]] = {
        (start_index, initial): (0, 0, 0.0, 0.0)
    }
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    final_state: tuple[int, int] | None = None
    interactions: dict[tuple[int, int], tuple[float, float, float, bool]] = {}
    unreached = (1, 1, float("inf"), float("inf"))

    while frontier:
        (
            overlapped,
            interacted,
            bend_cost,
            weighted,
            _,
            point_index,
            orientation,
        ) = heapq.heappop(frontier)
        state = (point_index, orientation)
        if best.get(state) != (overlapped, interacted, bend_cost, weighted):
            continue
        if point_index == end_index:
            final_state = state
            break
        for neighbor_index in adjacency.get(point_index, ()):
            key = (
                (point_index, neighbor_index)
                if point_index < neighbor_index
                else (neighbor_index, point_index)
            )
            cached = interactions.get(key)
            if cached is None:
                segment = Segment(points[point_index], points[neighbor_index])
                added_overlap, added_crossing = _interaction_cost(segment, tracks, costs)
                cached = (
                    added_overlap,
                    added_crossing,
                    segment.length
                    + _hug_cost(segment, relevant, costs)
                    + _confinement_cost(segment, confined, costs),
                    segment.horizontal,
                )
                interactions[key] = cached
            added_overlap, added_crossing, added_length, horizontal = cached
            next_orientation = 1 if horizontal else 2
            added_bend = costs.bend if orientation and orientation != next_orientation else 0.0
            if neighbor_index == end_index and arrival is not None and horizontal is not arrival:
                added_bend += costs.bend
            next_state = (neighbor_index, next_orientation)
            candidate = (
                int(bool(overlapped or added_overlap)),
                int(bool(interacted or added_overlap or added_crossing)),
                bend_cost + added_bend,
                weighted + added_length + added_overlap + added_crossing,
            )
            if candidate < best.get(next_state, unreached):
                best[next_state] = candidate
                previous[next_state] = state
                heapq.heappush(
                    frontier,
                    (*candidate, next(serial), neighbor_index, next_orientation),
                )

    if final_state is None:
        return None
    route = []
    state = final_state
    while True:
        route.append(points[state[0]])
        if state == (start_index, initial):
            break
        state = previous[state]
    route.reverse()
    return _simplify(tuple(route))


def _direct_path(
    start: Point,
    end: Point,
    obstacles: tuple[Rect, ...],
    tracks: tuple[_Track, ...],
    costs: PathCosts,
) -> tuple[Point, ...] | None:
    """The exact straight run, when the ports already align and nothing blocks it."""

    segment = Segment(start, end)
    if not segment.orthogonal:
        return None
    if any(segment.intersects_rect_interior(obstacle) for obstacle in obstacles):
        return None
    if _parallel_conflict(segment, tracks, costs.separation):
        return None
    return (start, end)


def _parallel_conflict(
    segment: Segment,
    tracks: tuple[_Track, ...],
    separation: float,
) -> bool:
    if separation <= 0.0:
        return False
    horizontal = segment.horizontal
    coordinate = segment.start.y if horizontal else segment.start.x
    low, high = (
        sorted((segment.start.x, segment.end.x))
        if horizontal
        else sorted((segment.start.y, segment.end.y))
    )
    tolerance = max(separation - _EPSILON, _EPSILON)
    return any(
        track.horizontal == horizontal
        and abs(track.coordinate - coordinate) < tolerance
        and min(high, track.high) - max(low, track.low) > _EPSILON
        for track in tracks
    )


def _tracks(
    occupied: tuple[Segment, ...],
    boundary: Rect | None,
    separation: float,
) -> tuple[_Track, ...]:
    """Occupied runs near this route's own corridor, reduced to numeric tracks."""

    region = None if boundary is None else boundary.inflated(max(separation, 0.0))
    result = []
    for segment in occupied:
        if region is not None and not segment.bounds.intersects(region, strict=False):
            continue
        if segment.horizontal:
            low, high = sorted((segment.start.x, segment.end.x))
            result.append(_Track(True, segment.start.y, low, high))
        elif segment.vertical:
            low, high = sorted((segment.start.y, segment.end.y))
            result.append(_Track(False, segment.start.x, low, high))
    return tuple(result)


def _candidate_points(
    start: Point,
    end: Point,
    obstacles: tuple[Rect, ...],
    boundary: Rect | None,
    tracks: tuple[_Track, ...],
    costs: PathCosts,
) -> tuple[tuple[Point, ...], tuple[Rect, ...]]:
    region = None if boundary is None else boundary.inflated(max(costs.clearance, 0.0))
    relevant = (
        obstacles
        if region is None
        else tuple(obstacle for obstacle in obstacles if obstacle.intersects(region, strict=False))
    )
    offset_xs, offset_ys = _occupied_offsets(start, end, tracks, costs.separation)
    xs = _axis_values(
        (start.x, end.x),
        tuple(value for item in relevant for value in (item.left, item.right)) + offset_xs,
        None if region is None else (region.left, region.right),
    )
    ys = _axis_values(
        (start.y, end.y),
        tuple(value for item in relevant for value in (item.top, item.bottom)) + offset_ys,
        None if region is None else (region.top, region.bottom),
    )
    points: list[Point] = []
    for x in xs:
        blockers = tuple(
            obstacle for obstacle in relevant if obstacle.left < x < obstacle.right
        )
        for y in ys:
            if any(obstacle.top < y < obstacle.bottom for obstacle in blockers):
                continue
            point = Point(x, y)
            if boundary is not None and not boundary.contains_point(point):
                continue
            points.append(point)
    unique = set(points)
    unique.update((start, end))
    return tuple(sorted(unique, key=lambda point: (point.x, point.y))), relevant


def _axis_values(
    anchors: tuple[float, ...],
    values: tuple[float, ...],
    limits: tuple[float, float] | None,
) -> tuple[float, ...]:
    """Merged candidate coordinates: anchors are exact, the rest keep 0.5pt apart."""

    kept = sorted(set(anchors))
    candidates = sorted(set(values))
    if limits is not None:
        low, high = limits
        candidates = [value for value in candidates if low <= value <= high]
    for value in candidates:
        _insert_spaced(kept, value)
    for first, second in tuple(pairwise(tuple(kept))):
        if second - first >= 2.0 * _MERGE_TOLERANCE:
            _insert_spaced(kept, (first + second) / 2.0)
    return tuple(kept)


def _insert_spaced(values: list[float], value: float) -> None:
    position = bisect_left(values, value)
    if position < len(values) and values[position] - value < _MERGE_TOLERANCE:
        return
    if position > 0 and value - values[position - 1] < _MERGE_TOLERANCE:
        return
    insort(values, value)


def _occupied_offsets(
    start: Point,
    end: Point,
    tracks: tuple[_Track, ...],
    separation: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Coordinates one lane away from occupied tracks near this route."""

    if separation <= 0.0 or not tracks:
        return (), ()
    margin = 4.0 * separation
    window = Rect.from_points(start, end).inflated(margin)
    xs: set[float] = set()
    ys: set[float] = set()
    for track in tracks:
        low, high = (
            (window.left, window.right) if track.horizontal else (window.top, window.bottom)
        )
        if min(track.high, high) < max(track.low, low):
            continue
        if track.horizontal:
            if window.top <= track.coordinate <= window.bottom:
                ys.update((track.coordinate - separation, track.coordinate + separation))
        elif window.left <= track.coordinate <= window.right:
            xs.update((track.coordinate - separation, track.coordinate + separation))
    return tuple(sorted(xs)), tuple(sorted(ys))


def _visibility_edges(
    points: tuple[Point, ...],
    obstacles: tuple[Rect, ...],
) -> dict[int, tuple[int, ...]]:
    by_x: defaultdict[float, list[int]] = defaultdict(list)
    by_y: defaultdict[float, list[int]] = defaultdict(list)
    for index, point in enumerate(points):
        by_x[point.x].append(index)
        by_y[point.y].append(index)
    neighbors: defaultdict[int, set[int]] = defaultdict(set)
    # Points arrive sorted by (x, y), so every line below is already ordered.
    for x, line in by_x.items():
        blockers = tuple(
            (obstacle.top, obstacle.bottom)
            for obstacle in obstacles
            if obstacle.left < x < obstacle.right
        )
        for first, second in pairwise(line):
            low = points[first].y
            high = points[second].y
            if any(max(low, top) < min(high, bottom) for top, bottom in blockers):
                continue
            neighbors[first].add(second)
            neighbors[second].add(first)
    for y, line in by_y.items():
        blockers = tuple(
            (obstacle.left, obstacle.right)
            for obstacle in obstacles
            if obstacle.top < y < obstacle.bottom
        )
        for first, second in pairwise(line):
            low = points[first].x
            high = points[second].x
            if any(max(low, left) < min(high, right) for left, right in blockers):
                continue
            neighbors[first].add(second)
            neighbors[second].add(first)
    return {
        index: tuple(
            sorted(
                values,
                key=lambda neighbor: (points[neighbor].x, points[neighbor].y),
            )
        )
        for index, values in neighbors.items()
    }


def _interaction_cost(
    segment: Segment,
    tracks: tuple[_Track, ...],
    costs: PathCosts,
) -> tuple[float, float]:
    """Penalties for sharing a lane with, and for crossing, existing routes."""

    tolerance = max(costs.separation - _EPSILON, _EPSILON)
    horizontal = segment.horizontal
    if horizontal:
        coordinate = segment.start.y
        low, high = sorted((segment.start.x, segment.end.x))
    else:
        coordinate = segment.start.x
        low, high = sorted((segment.start.y, segment.end.y))
    shared = 0.0
    crossings = 0.0
    for track in tracks:
        if track.horizontal == horizontal:
            if abs(track.coordinate - coordinate) < tolerance:
                overlap = min(high, track.high) - max(low, track.low)
                if overlap > _EPSILON:
                    shared += costs.overlap * overlap
        elif (
            low + _EPSILON < track.coordinate < high - _EPSILON
            and track.low + _EPSILON < coordinate < track.high - _EPSILON
        ):
            crossings += costs.crossing
    return shared, crossings


def _hug_cost(segment: Segment, obstacles: tuple[Rect, ...], costs: PathCosts) -> float:
    """A mild penalty for runs that graze an obstacle instead of centring.

    The graph only ever offers short hops between neighbouring candidate
    coordinates, so the penalty is charged per unit length: a long haul pays
    proportionally more for hugging than a two-point jog does.
    """

    clearance = costs.clearance
    if clearance <= 0.0 or costs.hug <= 0.0:
        return 0.0
    nearest = clearance
    if segment.horizontal:
        coordinate = segment.start.y
        low, high = sorted((segment.start.x, segment.end.x))
        for obstacle in obstacles:
            if min(high, obstacle.right) - max(low, obstacle.left) <= _EPSILON:
                continue
            nearest = min(
                nearest,
                abs(coordinate - obstacle.top),
                abs(coordinate - obstacle.bottom),
            )
    else:
        coordinate = segment.start.x
        low, high = sorted((segment.start.y, segment.end.y))
        for obstacle in obstacles:
            if min(high, obstacle.bottom) - max(low, obstacle.top) <= _EPSILON:
                continue
            nearest = min(
                nearest,
                abs(coordinate - obstacle.left),
                abs(coordinate - obstacle.right),
            )
    if nearest >= clearance:
        return 0.0
    return costs.hug * (clearance - nearest) / clearance * segment.length


def _confinement_cost(
    segment: Segment,
    confined: tuple[Rect, ...],
    costs: PathCosts,
) -> float:
    """Charge for the stretch a route spends beneath a container it must leave."""

    if not confined or costs.confinement <= 0.0:
        return 0.0
    midpoint = Point(
        (segment.start.x + segment.end.x) / 2.0,
        (segment.start.y + segment.end.y) / 2.0,
    )
    if not any(rectangle.contains_point(midpoint) for rectangle in confined):
        return 0.0
    return costs.confinement * segment.length


def _simplify(points: tuple[Point, ...]) -> tuple[Point, ...]:
    if len(points) < 3:
        return points
    result = [points[0]]
    for point in points[1:]:
        if point == result[-1]:
            continue
        if len(result) >= 2:
            first, middle = result[-2:]
            if (first.x == middle.x == point.x) or (first.y == middle.y == point.y):
                result[-1] = point
                continue
        result.append(point)
    return tuple(result)
