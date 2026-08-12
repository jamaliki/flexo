"""Resolve semantic ports and hints into obstacle-free orthogonal routes."""

from __future__ import annotations

from itertools import pairwise

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Point, Rect, Segment, Side, segments
from flexo.ir.fitted import FittedFigure
from flexo.ir.routed import RoutedEdge, RoutedFigure
from flexo.ir.semantic import EdgeSpec, Waypoint
from flexo.routing.nudge import shorten_end
from flexo.routing.visibility import PathCosts, shortest_orthogonal_path
from flexo.style import STYLES, LayoutStyle
from flexo.text import TextMeasurer


def route_figure(
    fitted: FittedFigure,
    *,
    style: LayoutStyle | None = None,
    measurer: TextMeasurer | None = None,
) -> RoutedFigure:
    layout_style = style or STYLES[fitted.measured.semantic.style]
    text_measurer = measurer or TextMeasurer(layout_style.typography)
    occupied: tuple[Segment, ...] = ()
    routed: list[RoutedEdge] = []
    for edge in fitted.measured.semantic.edges:
        result = _route_edge(fitted, edge, layout_style, text_measurer, occupied)
        routed.append(result)
        occupied += segments(result.centerline)
    return RoutedFigure(fitted, tuple(routed))


def _route_edge(
    fitted: FittedFigure,
    edge: EdgeSpec,
    style: LayoutStyle,
    measurer: TextMeasurer,
    occupied: tuple[Segment, ...],
) -> RoutedEdge:
    source_node = fitted.node(edge.source.node_id)
    target_node = fitted.node(edge.target.node_id)
    source_port = source_node.port(edge.source.port_name)
    target_port = target_node.port(edge.target.port_name)
    if edge.depart is not None and edge.depart is not source_port.side:
        raise FlexoError(
            Diagnostic(
                "routing.depart.port-mismatch",
                f'Depart hint "{edge.depart}" conflicts with port side "{source_port.side}".',
                entity_id=edge.id,
                hint="Choose a port on the requested side instead.",
            )
        )
    if edge.arrive is not None and edge.arrive is not target_port.side:
        raise FlexoError(
            Diagnostic(
                "routing.arrive.port-mismatch",
                f'Arrive hint "{edge.arrive}" conflicts with port side "{target_port.side}".',
                entity_id=edge.id,
                hint="Choose a port on the requested side instead.",
            )
        )
    source_side = source_port.side
    target_side = target_port.side
    clearance = style.route_clearance.points
    source_escape = _escape(source_port.position, source_side, clearance)
    target_clearance = max(
        clearance,
        2.0 * style.arrow_length.points,
    )
    target_escape = _escape(target_port.position, target_side, target_clearance)
    obstacles = tuple(
        node.bounds.inflated(
            target_clearance
            if node.measured.spec.id == target_node.measured.spec.id
            else clearance
        )
        for node in fitted.nodes
        if node.measured.spec.kind not in {"label", "spacer", "junction"}
    )
    boundary = _routing_boundary(fitted, edge, style.route_boundary_clearance.points)
    forced = _forced_points(
        fitted,
        edge,
        source_escape,
        target_escape,
        style.route_boundary_clearance.points,
    )
    anchors = (source_escape, *forced, target_escape)
    interior: list[Point] = []
    costs = PathCosts(style.bend_penalty)
    local_occupied = occupied
    for start, end in pairwise(anchors):
        leg = shortest_orthogonal_path(
            start,
            end,
            obstacles,
            costs=costs,
            occupied=local_occupied,
            boundary=boundary,
        )
        if leg is None:
            raise FlexoError(
                Diagnostic(
                    "routing.no-path",
                    f'No obstacle-free route exists from "{edge.source}" to "{edge.target}".',
                    entity_id=edge.id,
                    hint="Add a semantic lane or waypoint, or increase container spacing.",
                )
            )
        interior.extend(leg if not interior else leg[1:])
        local_occupied += segments(leg)
    centerline = _simplify((source_port.position, *interior, target_port.position))
    shaft = shorten_end(centerline, style.arrow_length.points)
    label_metrics = measurer.measure(edge.label) if edge.label else None
    label_position = _label_position(centerline) if label_metrics is not None else None
    return RoutedEdge(edge, centerline, shaft, label_metrics, label_position)


def _forced_points(
    fitted: FittedFigure,
    edge: EdgeSpec,
    source_escape: Point,
    target_escape: Point,
    boundary_clearance: float,
) -> tuple[Point, ...]:
    result: list[Point] = []
    if edge.lane_hint:
        result.extend(
            _lane_points(
                fitted,
                edge.lane_hint,
                source_escape,
                target_escape,
                boundary_clearance,
                edge.id,
            )
        )
    result.extend(_waypoint(fitted, waypoint, edge.id) for waypoint in edge.waypoints)
    return tuple(result)


def _lane_points(
    fitted: FittedFigure,
    lane: str,
    source: Point,
    target: Point,
    boundary_clearance: float,
    edge_id: str,
) -> tuple[Point, Point]:
    if "-" not in lane:
        raise FlexoError(
            Diagnostic(
                "routing.lane.syntax",
                f'Lane "{lane}" must end in -top, -bottom, -left, or -right.',
                entity_id=edge_id,
            )
        )
    reference, suffix = lane.rsplit("-", 1)
    try:
        bounds = fitted.group(reference).bounds
    except StopIteration as exc:
        raise FlexoError(
            Diagnostic(
                "routing.lane.unknown",
                f'Lane group "{reference}" does not exist.',
                entity_id=edge_id,
            )
        ) from exc
    if suffix == "bottom":
        y = bounds.bottom - boundary_clearance
        return Point(source.x, y), Point(target.x, y)
    if suffix == "top":
        y = bounds.top + boundary_clearance
        return Point(source.x, y), Point(target.x, y)
    if suffix == "left":
        x = bounds.left + boundary_clearance
        return Point(x, source.y), Point(x, target.y)
    if suffix == "right":
        x = bounds.right - boundary_clearance
        return Point(x, source.y), Point(x, target.y)
    raise FlexoError(
        Diagnostic(
            "routing.lane.syntax",
            f'Unknown lane side "{suffix}".',
            entity_id=edge_id,
            hint="Use top, bottom, left, or right.",
        )
    )


def _routing_boundary(
    fitted: FittedFigure,
    edge: EdgeSpec,
    clearance: float,
) -> Rect:
    groups = {group.id: group for group in fitted.measured.semantic.groups}
    fitted_groups = {
        group.measured.spec.id: group for group in fitted.groups
    }
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

    target_ancestors = set(ancestors(edge.target.node_id))
    owner = next(
        group_id
        for group_id in ancestors(edge.source.node_id)
        if group_id in target_ancestors
    )
    while groups[owner].role == "layout" and owner in parents:
        owner = parents[owner]
    bounds = fitted_groups[owner].bounds
    return bounds.inflated(-clearance)


def _waypoint(fitted: FittedFigure, waypoint: Waypoint, edge_id: str) -> Point:
    if waypoint.reference is None:
        assert waypoint.x is not None and waypoint.y is not None
        return Point(waypoint.x.points, waypoint.y.points)
    bounds: Rect
    try:
        bounds = fitted.node(waypoint.reference).bounds
    except StopIteration:
        try:
            bounds = fitted.group(waypoint.reference).bounds
        except StopIteration as exc:
            raise FlexoError(
                Diagnostic(
                    "routing.waypoint.unknown",
                    f'Waypoint reference "{waypoint.reference}" does not exist.',
                    entity_id=edge_id,
                )
            ) from exc
    origin = (
        bounds.center
        if waypoint.side is None
        else bounds.point_on(waypoint.side, waypoint.offset)
    )
    return origin.translated(waypoint.dx.points, waypoint.dy.points)


def _escape(point: Point, side: Side, distance: float) -> Point:
    vector = side.vector
    return point.translated(vector.x * distance, vector.y * distance)


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


def _label_position(points: tuple[Point, ...]) -> Point:
    candidates = segments(points)
    longest = max(candidates, key=lambda segment: segment.length)
    midpoint = Point(
        (longest.start.x + longest.end.x) / 2.0,
        (longest.start.y + longest.end.y) / 2.0,
    )
    return midpoint.translated(dy=-4.0) if longest.horizontal else midpoint.translated(dx=4.0)
