"""Route cleanup: shaft trimming, zigzag collapse, and parallel-track nudging."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

from flexo.geometry import Point, Rect, Segment, segments
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedEdge, RoutedFigure, RoutedNet, RoutedStem
from flexo.style import LayoutStyle

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


def edge_label_position(points: tuple[Point, ...], metrics: TextMetrics) -> Point:
    candidates = segments(points)
    horizontal = tuple(segment for segment in candidates if segment.horizontal)
    longest = max(horizontal or candidates, key=lambda segment: segment.length)
    midpoint = Point(
        (longest.start.x + longest.end.x) / 2.0,
        (longest.start.y + longest.end.y) / 2.0,
    )
    if longest.horizontal:
        return midpoint.translated(dy=-(metrics.descent + 2.0))
    return midpoint.translated(dx=metrics.width / 2.0 + 4.0)


def rail_label_position(
    rail: tuple[Point, ...],
    stems: tuple[tuple[Point, ...], ...] = (),
) -> Point:
    """Anchor a net caption above the horizontal run the net reads along.

    A net's caption belongs to its *arrow*, not to its rail: panel-b writes
    ``softmax(QK^T)V`` above the horizontal run that carries Q into the attended
    value, and that run is a source stem, a stretch of rail and a target stem
    drawn as one line. So the anchor is the midpoint of the longest horizontal
    run the net draws -- collinear pieces counted as one -- and a net whose ink
    is purely vertical keeps its rail midpoint, captioned beside it.
    """

    runs: dict[float, list[Segment]] = {}
    for polyline in (rail, *stems):
        for segment in segments(polyline):
            if segment.horizontal and segment.length > _EPSILON:
                runs.setdefault(segment.start.y, []).append(segment)
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
        return Point((min(bounds) + max(bounds)) / 2.0, coordinate - 4.0)
    first, last = rail[0], rail[-1]
    midpoint = Point((first.x + last.x) / 2.0, (first.y + last.y) / 2.0)
    return midpoint.translated(dx=4.0)


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
        judged = segments(points) if run.rail else segments(points)[1:-1]
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
    arrival = max(
        departure,
        2.0 * style.arrow_length.points + style.elbow_radius.points,
    )
    runs: list[Run] = []
    polylines: list[tuple[Point, ...]] = []
    for edge in routed.edges:
        runs.append(
            Run(
                edge.spec.id,
                edge.spec.id,
                boundaries[edge.spec.id],
                Stubs(departure, arrival),
            )
        )
        polylines.append(edge.centerline)
    for net in routed.nets:
        boundary = boundaries[net.spec.id]
        runs.append(Run(net.spec.id, f"{net.spec.id}.rail", boundary, rail=True))
        polylines.append(net.rail)
        for index, stem in enumerate(net.source_stems):
            runs.append(
                Run(
                    net.spec.id,
                    f"{net.spec.id}.source.{index}",
                    boundary,
                    Stubs(head=departure),
                    junction=-1,
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
                )
            )
            polylines.append(stem.centerline)
    return tuple(runs), tuple(polylines)


def rebuild_figure(
    routed: RoutedFigure,
    polylines: tuple[tuple[Point, ...], ...],
    *,
    arrow_length: float,
) -> RoutedFigure:
    """Re-derive shafts and label anchors from nudged centerlines."""

    position = 0
    edges: list[RoutedEdge] = []
    for edge in routed.edges:
        centerline = simplify_polyline(polylines[position])
        position += 1
        edges.append(
            replace(
                edge,
                centerline=centerline,
                shaft=shorten_end(centerline, arrow_length),
                label_position=(
                    edge_label_position(centerline, edge.label_metrics)
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
            source_stems.append(replace(stem, centerline=centerline, shaft=centerline))
        target_stems: list[RoutedStem] = []
        for stem in net.target_stems:
            centerline = simplify_polyline(polylines[position])
            position += 1
            target_stems.append(
                replace(
                    stem,
                    centerline=centerline,
                    shaft=shorten_end(centerline, arrow_length),
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
                        tuple(
                            stem.shaft for stem in (*source_stems, *target_stems)
                        ),
                    )
                    if net.label_metrics is not None
                    else None
                ),
            )
        )
    return replace(routed, edges=tuple(edges), nets=tuple(nets))


def nudge_obstacles(routed: RoutedFigure, style: LayoutStyle) -> tuple[Rect, ...]:
    """Component bounds a nudged track may not approach."""

    margin = style.route_clearance.points * _NUDGE_OBSTACLE_FRACTION
    return tuple(
        node.bounds.inflated(margin)
        for node in routed.fitted.nodes
        if node.measured.spec.kind not in {"label", "spacer", "junction"}
    )
