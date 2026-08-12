"""Route authored fan-out buses and many-to-one merge rails."""

from __future__ import annotations

from itertools import pairwise

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Point, Rect, Segment, Side, segments
from flexo.ir.fitted import FittedFigure, ResolvedPort
from flexo.ir.routed import RoutedNet, RoutedStem
from flexo.ir.semantic import NetSpec, PortRef
from flexo.routing.nudge import shorten_end
from flexo.routing.visibility import PathCosts, shortest_orthogonal_path
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer


def route_net(
    fitted: FittedFigure,
    net: NetSpec,
    style: LayoutStyle,
    measurer: TextMeasurer,
    occupied: tuple[Segment, ...],
) -> RoutedNet:
    sources = tuple((_resolved(fitted, ref), ref) for ref in net.sources)
    targets = tuple((_resolved(fitted, ref), ref) for ref in net.targets)
    boundary = _routing_boundary(fitted, net, style.route_boundary_clearance.points)
    target_clearance = max(
        style.route_clearance.points,
        2.0 * style.arrow_length.points + style.elbow_radius.points,
    )
    source_escapes = tuple(
        (_escape(port, style.route_clearance.points), ref) for port, ref in sources
    )
    target_escapes = tuple((_escape(port, target_clearance), ref) for port, ref in targets)
    hub_port = sources[0][0] if net.kind == "fan-out" else targets[0][0]
    hub_escape = source_escapes[0][0] if net.kind == "fan-out" else target_escapes[0][0]
    vertical = _vertical_rail(net.rail_hint, hub_port.side)
    all_escapes = tuple(point for point, _ in source_escapes + target_escapes)
    obstacles = tuple(node.bounds.inflated(style.route_clearance.points) for node in fitted.nodes)
    coordinate = _rail_coordinate(
        net,
        boundary,
        hub_escape,
        all_escapes,
        obstacles,
        vertical,
    )
    junctions = tuple(_junction(point, coordinate, vertical) for point in all_escapes)
    rail = _rail(junctions, vertical)
    source_count = len(sources)
    source_stems = tuple(
        _source_stem(
            fitted,
            port,
            ref,
            escape,
            junctions[index],
            style,
            boundary,
            occupied,
        )
        for index, ((port, ref), (escape, _)) in enumerate(
            zip(sources, source_escapes, strict=True)
        )
    )
    target_stems = tuple(
        _target_stem(
            fitted,
            port,
            ref,
            junctions[source_count + index],
            escape,
            style,
            boundary,
            occupied,
        )
        for index, ((port, ref), (escape, _)) in enumerate(
            zip(targets, target_escapes, strict=True)
        )
    )
    label_metrics = measurer.measure(net.label) if net.label else None
    label_position = _label_position(rail) if label_metrics is not None else None
    return RoutedNet(net, rail, source_stems, target_stems, label_metrics, label_position)


def net_segments(net: RoutedNet) -> tuple[Segment, ...]:
    return (
        segments(net.rail)
        + tuple(segment for stem in net.source_stems for segment in segments(stem.centerline))
        + tuple(segment for stem in net.target_stems for segment in segments(stem.centerline))
    )


def _resolved(fitted: FittedFigure, reference: PortRef) -> ResolvedPort:
    return fitted.node(reference.node_id).port(reference.port_name)


def _escape(port: ResolvedPort, distance: float) -> Point:
    vector = port.side.vector
    return port.position.translated(vector.x * distance, vector.y * distance)


def _vertical_rail(hint: Side | None, hub_side: Side) -> bool:
    side = hint or hub_side
    return side in {Side.EAST, Side.WEST}


def _rail_coordinate(
    net: NetSpec,
    boundary: Rect,
    preferred: Point,
    escapes: tuple[Point, ...],
    obstacles: tuple[Rect, ...],
    vertical: bool,
) -> float:
    if net.rail_hint is not None:
        return {
            Side.WEST: boundary.left,
            Side.EAST: boundary.right,
            Side.NORTH: boundary.top,
            Side.SOUTH: boundary.bottom,
        }[net.rail_hint]
    preferred_value = preferred.x if vertical else preferred.y
    transverse = tuple(point.y if vertical else point.x for point in escapes)
    candidates = _rail_candidates(preferred_value, boundary, obstacles, vertical)
    for candidate in candidates:
        endpoints = (
            (Point(candidate, min(transverse)), Point(candidate, max(transverse)))
            if vertical
            else (Point(min(transverse), candidate), Point(max(transverse), candidate))
        )
        segment = Segment(*endpoints)
        if not any(segment.intersects_rect_interior(obstacle) for obstacle in obstacles):
            return candidate
    raise FlexoError(
        Diagnostic(
            "routing.net.no-rail",
            "No obstacle-free shared rail exists for this net.",
            entity_id=net.id,
            hint="Choose an explicit north, east, south, or west rail.",
        )
    )


def _rail_candidates(
    preferred: float,
    boundary: Rect,
    obstacles: tuple[Rect, ...],
    vertical: bool,
) -> tuple[float, ...]:
    low, high = (boundary.left, boundary.right) if vertical else (boundary.top, boundary.bottom)
    boundaries = {
        value
        for obstacle in obstacles
        for value in (
            (obstacle.left, obstacle.right) if vertical else (obstacle.top, obstacle.bottom)
        )
        if low <= value <= high
    }
    values = {min(high, max(low, preferred)), low, high, *boundaries}
    ordered = sorted(values)
    values.update((first + second) / 2.0 for first, second in pairwise(ordered))
    return tuple(sorted(values, key=lambda value: (abs(value - preferred), value)))


def _junction(point: Point, coordinate: float, vertical: bool) -> Point:
    return Point(coordinate, point.y) if vertical else Point(point.x, coordinate)


def _rail(junctions: tuple[Point, ...], vertical: bool) -> tuple[Point, ...]:
    if vertical:
        low = min(point.y for point in junctions)
        high = max(point.y for point in junctions)
        return (Point(junctions[0].x, low), Point(junctions[0].x, high))
    low = min(point.x for point in junctions)
    high = max(point.x for point in junctions)
    return (Point(low, junctions[0].y), Point(high, junctions[0].y))


def _source_stem(
    fitted: FittedFigure,
    port: ResolvedPort,
    reference: PortRef,
    escape: Point,
    junction: Point,
    style: LayoutStyle,
    boundary: Rect,
    occupied: tuple[Segment, ...],
) -> RoutedStem:
    leg = _route_leg(fitted, reference, escape, junction, style, boundary, occupied)
    centerline = _simplify((port.position, *leg))
    return RoutedStem(reference, centerline, centerline)


def _target_stem(
    fitted: FittedFigure,
    port: ResolvedPort,
    reference: PortRef,
    junction: Point,
    escape: Point,
    style: LayoutStyle,
    boundary: Rect,
    occupied: tuple[Segment, ...],
) -> RoutedStem:
    leg = _route_leg(fitted, reference, junction, escape, style, boundary, occupied)
    centerline = _simplify((*leg, port.position))
    shaft = shorten_end(centerline, style.arrow_length.points)
    return RoutedStem(reference, centerline, shaft, True)


def _route_leg(
    fitted: FittedFigure,
    endpoint: PortRef,
    start: Point,
    end: Point,
    style: LayoutStyle,
    boundary: Rect,
    occupied: tuple[Segment, ...],
) -> tuple[Point, ...]:
    obstacles = tuple(
        node.bounds.inflated(style.route_clearance.points)
        for node in fitted.nodes
        if node.measured.spec.id != endpoint.node_id
        and node.measured.spec.kind not in {"label", "spacer", "junction"}
    )
    route = shortest_orthogonal_path(
        start,
        end,
        obstacles,
        costs=PathCosts(style.bend_penalty),
        occupied=occupied,
        boundary=boundary,
    )
    if route is None:
        raise FlexoError(
            Diagnostic(
                "routing.net.no-stem",
                f'No obstacle-free stem exists for "{endpoint}".',
                entity_id=str(endpoint),
                hint="Choose an explicit rail or increase container spacing.",
            )
        )
    return route


def _routing_boundary(
    fitted: FittedFigure,
    net: NetSpec,
    clearance: float,
) -> Rect:
    groups = {group.id: group for group in fitted.measured.semantic.groups}
    fitted_groups = {group.measured.spec.id: group for group in fitted.groups}
    parents = {
        child_id: group.id
        for group in fitted.measured.semantic.groups
        for child_id in group.children
    }

    def ancestors(entity_id: str) -> tuple[str, ...]:
        result = []
        current = entity_id
        while current in parents:
            current = parents[current]
            result.append(current)
        return tuple(result)

    node_ids = tuple(ref.node_id for ref in net.sources + net.targets)
    common = set(ancestors(node_ids[0]))
    for node_id in node_ids[1:]:
        common.intersection_update(ancestors(node_id))
    owner = next(group_id for group_id in ancestors(node_ids[0]) if group_id in common)
    while groups[owner].role == "layout" and owner in parents:
        owner = parents[owner]
    return fitted_groups[owner].bounds.inflated(-clearance)


def _simplify(points: tuple[Point, ...]) -> tuple[Point, ...]:
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


def _label_position(rail: tuple[Point, ...]) -> Point:
    first, last = rail[0], rail[-1]
    midpoint = Point((first.x + last.x) / 2.0, (first.y + last.y) / 2.0)
    return midpoint.translated(dx=4.0) if first.x == last.x else midpoint.translated(dy=-4.0)
