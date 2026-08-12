"""Orthogonal visibility graph construction and deterministic path search."""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from itertools import count, pairwise

from flexo.geometry import Point, Rect, Segment

_EPSILON = 1e-8


@dataclass(frozen=True, slots=True)
class PathCosts:
    bend: float
    crossing: float = 80.0
    overlap: float = 120.0


def shortest_orthogonal_path(
    start: Point,
    end: Point,
    obstacles: tuple[Rect, ...],
    *,
    costs: PathCosts,
    occupied: tuple[Segment, ...] = (),
    boundary: Rect | None = None,
) -> tuple[Point, ...] | None:
    if start == end:
        return (start,)
    points = _candidate_points(start, end, obstacles, boundary)
    index = {point: position for position, point in enumerate(points)}
    adjacency = _visibility_edges(points, obstacles)
    start_index = index[start]
    end_index = index[end]

    # State orientation: 0 initial, 1 horizontal, 2 vertical.
    frontier: list[tuple[int, float, float, float, int, int, int]] = []
    serial = count()
    heapq.heappush(frontier, (0, 0.0, 0.0, 0.0, next(serial), start_index, 0))
    best: dict[tuple[int, int], tuple[int, float, float, float]] = {
        (start_index, 0): (0, 0.0, 0.0, 0.0)
    }
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    final_state: tuple[int, int] | None = None

    while frontier:
        interacted, bend_cost, interaction_cost, distance, _, point_index, orientation = (
            heapq.heappop(frontier)
        )
        state = (point_index, orientation)
        if best.get(state) != (interacted, bend_cost, interaction_cost, distance):
            continue
        if point_index == end_index:
            final_state = state
            break
        for neighbor_index in adjacency.get(point_index, ()):
            segment = Segment(points[point_index], points[neighbor_index])
            next_orientation = 1 if segment.horizontal else 2
            added_bend = costs.bend if orientation and orientation != next_orientation else 0.0
            added_interaction = _interaction_cost(segment, occupied, costs)
            next_distance = distance + segment.length
            next_state = (neighbor_index, next_orientation)
            candidate = (
                int(bool(interacted or added_interaction)),
                bend_cost + added_bend,
                interaction_cost + added_interaction,
                next_distance,
            )
            if candidate < best.get(
                next_state,
                (1, float("inf"), float("inf"), float("inf")),
            ):
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
        if state == (start_index, 0):
            break
        state = previous[state]
    route.reverse()
    return _simplify(tuple(route))


def _candidate_points(
    start: Point,
    end: Point,
    obstacles: tuple[Rect, ...],
    boundary: Rect | None,
) -> tuple[Point, ...]:
    obstacle_xs = (value for item in obstacles for value in (item.left, item.right))
    obstacle_ys = (value for item in obstacles for value in (item.top, item.bottom))
    xs = _with_midpoints({start.x, end.x, *obstacle_xs})
    ys = _with_midpoints({start.y, end.y, *obstacle_ys})
    points = {
        Point(x, y)
        for x in xs
        for y in ys
        if not any(obstacle.contains_point(Point(x, y), strict=True) for obstacle in obstacles)
        and (boundary is None or boundary.contains_point(Point(x, y)))
    }
    if boundary is not None and not (
        boundary.contains_point(start) and boundary.contains_point(end)
    ):
        return ()
    points.update((start, end))
    return tuple(sorted(points, key=lambda point: (point.x, point.y)))


def _with_midpoints(values: set[float]) -> tuple[float, ...]:
    ordered = sorted(values)
    return tuple(
        sorted(
            {
                *ordered,
                *((first + second) / 2.0 for first, second in pairwise(ordered)),
            }
        )
    )


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
    vertical_lines = (
        sorted(values, key=lambda index: points[index].y) for values in by_x.values()
    )
    horizontal_lines = (
        sorted(values, key=lambda index: points[index].x) for values in by_y.values()
    )
    for line in (*vertical_lines, *horizontal_lines):
        for first, second in pairwise(line):
            segment = Segment(points[first], points[second])
            if not any(segment.intersects_rect_interior(obstacle) for obstacle in obstacles):
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


def _interaction_cost(segment: Segment, occupied: tuple[Segment, ...], costs: PathCosts) -> float:
    total = 0.0
    for other in occupied:
        same_horizontal_line = (
            segment.horizontal
            and other.horizontal
            and abs(segment.start.y - other.start.y) < _EPSILON
        )
        same_vertical_line = (
            segment.vertical
            and other.vertical
            and abs(segment.start.x - other.start.x) < _EPSILON
        )
        if same_horizontal_line:
            overlap = _overlap(
                segment.start.x,
                segment.end.x,
                other.start.x,
                other.end.x,
            )
            if overlap > _EPSILON:
                total += costs.overlap + overlap
        elif same_vertical_line:
            overlap = _overlap(
                segment.start.y,
                segment.end.y,
                other.start.y,
                other.end.y,
            )
            if overlap > _EPSILON:
                total += costs.overlap + overlap
        elif _crosses(segment, other):
            total += costs.crossing
    return total


def _overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    a_low, a_high = sorted((a1, a2))
    b_low, b_high = sorted((b1, b2))
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def _crosses(first: Segment, second: Segment) -> bool:
    if first.horizontal == second.horizontal:
        return False
    horizontal, vertical = (first, second) if first.horizontal else (second, first)
    x_low, x_high = sorted((horizontal.start.x, horizontal.end.x))
    y_low, y_high = sorted((vertical.start.y, vertical.end.y))
    return (
        x_low + _EPSILON < vertical.start.x < x_high - _EPSILON
        and y_low + _EPSILON < horizontal.start.y < y_high - _EPSILON
    )


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
