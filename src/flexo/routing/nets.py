"""Route authored fan-out buses and many-to-one merge rails."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from flexo.components import TRANSPARENT_KINDS
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Segment, Side, segments
from flexo.ir.fitted import FittedFigure, ResolvedPort
from flexo.ir.routed import RoutedNet, RoutedStem
from flexo.ir.semantic import NetSpec, PortRef
from flexo.routing.nudge import (
    collapse_zigzags,
    rail_label_position,
    shorten_end,
    shorten_start,
    simplify_polyline,
)
from flexo.routing.visibility import PathCosts, shortest_orthogonal_path
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer

TRANSPARENT_ROLES = frozenset({"layout", "canvas"})
"""Group roles that draw no boundary and therefore never block a route."""

_RAIL_TOLERANCE = 1e-6
"""How far a placed rail may sit from the requested one and still count as honoured."""


def parent_map(fitted: FittedFigure) -> dict[str, str]:
    return {
        child_id: group.id
        for group in fitted.measured.semantic.groups
        for child_id in group.children
    }


def ancestor_ids(parents: Mapping[str, str], entity_id: str) -> tuple[str, ...]:
    result: list[str] = []
    current = entity_id
    while current in parents:
        current = parents[current]
        result.append(current)
    return tuple(result)


def group_obstacles(
    fitted: FittedFigure,
    node_ids: tuple[str, ...],
    positions: tuple[Point, ...],
    clearance: float,
) -> tuple[Rect, ...]:
    """Opaque containers that own none of these endpoints, as routing obstacles.

    A container is transparent to a route when it is an ancestor of one of the
    route's endpoint components, or when its bounds already hold one of the
    route's endpoint positions: such a route has to cross the boundary through
    the container's own padding.
    """

    parents = parent_map(fitted)
    protected: set[str] = set()
    for node_id in node_ids:
        protected.update(ancestor_ids(parents, node_id))
    return tuple(
        group.bounds.inflated(clearance)
        for group in fitted.groups
        if group.measured.spec.role not in TRANSPARENT_ROLES
        and group.measured.spec.id not in protected
        and not any(group.bounds.contains_point(position) for position in positions)
    )


def confined_groups(
    fitted: FittedFigure,
    node_ids: tuple[str, ...],
    positions: tuple[Point, ...],
) -> tuple[Rect, ...]:
    """Opaque containers this route owns but has to leave.

    Such a container is transparent -- the route starts inside it -- yet every
    point it spends in there is drawn beneath the container fill, so the router
    is charged for lingering and leaves through the nearest padding instead.
    """

    parents = parent_map(fitted)
    owned: set[str] = set()
    for node_id in node_ids:
        owned.update(ancestor_ids(parents, node_id))
    return tuple(
        group.bounds
        for group in fitted.groups
        if group.measured.spec.role not in TRANSPARENT_ROLES
        and group.measured.spec.id in owned
        and not all(group.bounds.contains_point(position) for position in positions)
    )


def route_net(
    fitted: FittedFigure,
    net: NetSpec,
    style: LayoutStyle,
    measurer: TextMeasurer,
    occupied: tuple[Segment, ...],
) -> RoutedNet:
    sources = tuple((_resolved(fitted, ref), ref) for ref in net.sources)
    targets = tuple((_resolved(fitted, ref), ref) for ref in net.targets)
    boundary = net_routing_boundary(fitted, net, style.route_boundary_clearance.points)
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
    spokes = targets if net.kind == "fan-out" else sources
    vertical = _vertical_rail(
        net.rail_hint,
        hub_port.side,
        tuple(port.side for port, _ in spokes),
    )
    all_escapes = tuple(point for point, _ in source_escapes + target_escapes)
    escape_sides = tuple(
        (escape, port.side)
        for (port, _), (escape, _) in zip(
            sources + targets,
            source_escapes + target_escapes,
            strict=True,
        )
    )
    endpoint_ids = tuple(ref.node_id for ref in net.sources + net.targets)
    endpoint_positions = tuple(port.position for port, _ in sources + targets) + all_escapes
    obstacles = tuple(
        node.bounds.inflated(style.route_clearance.points)
        for node in fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    ) + group_obstacles(
        fitted,
        endpoint_ids,
        endpoint_positions,
        style.route_clearance.points,
    )
    trunk_escapes = _trunk_escapes(all_escapes, hub_escape, hub_port.side, vertical)
    run = _trunk_run(net, hub_port, tuple(port for port, _ in spokes), vertical)
    coordinate = _rail_coordinate(
        net,
        boundary,
        hub_escape,
        trunk_escapes,
        escape_sides,
        obstacles,
        vertical,
        requested=None if run is None else run.requested,
    )
    junctions = tuple(_junction(point, coordinate, vertical) for point in trunk_escapes)
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
    label_position = (
        rail_label_position(
            rail,
            tuple(stem.shaft for stem in (*source_stems, *target_stems)),
        )
        if label_metrics is not None
        else None
    )
    return RoutedNet(
        net,
        rail,
        source_stems,
        target_stems,
        label_metrics,
        label_position,
        _rail_clamp_diagnostics(net, run, coordinate),
    )


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


def _vertical_rail(hint: Side | None, hub_side: Side, spoke_sides: tuple[Side, ...]) -> bool:
    """Which axis the shared rail runs along, decided by the spokes it feeds.

    An explicit hint always wins. Otherwise the spoke ports vote: east/west
    spokes are entered from a vertical rail, north/south spokes from a
    horizontal one. A tie runs the trunk *along* the hub port axis, so a south
    hub keeps one straight drop instead of doglegging into a cross rail.
    """

    if hint is not None:
        return _horizontal(hint)
    votes = sum(1 if _horizontal(side) else -1 for side in spoke_sides)
    if votes == 0:
        return not _horizontal(hub_side)
    return votes > 0


def _horizontal(side: Side) -> bool:
    return side in {Side.EAST, Side.WEST}


@dataclass(frozen=True, slots=True)
class _TrunkRun:
    """The run a ``rail_at`` fraction measures along, in rail-transverse units.

    Only the coordinate the rail is free to slide along matters here: a vertical
    rail is placed by an x, a horizontal one by a y. The run points from the
    trunk's start toward its destination, so fraction 0 sits at the far end of
    the trunk and fraction 1 on the destination port itself.
    """

    start: float
    end: float
    fraction: float

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def requested(self) -> float:
        return self.start + self.fraction * self.length

    def fraction_of(self, value: float) -> float | None:
        return None if self.length == 0.0 else (value - self.start) / self.length


def _trunk_run(
    net: NetSpec,
    hub_port: ResolvedPort,
    spoke_ports: tuple[ResolvedPort, ...],
    vertical: bool,
) -> _TrunkRun | None:
    """Where fraction 0 and fraction 1 of this net's trunk run lie.

    A merge reads from its furthest source into the sink, a fan-out from its
    shared source out to the furthest target, so the two kinds run the same
    measurement in opposite directions.
    """

    if net.rail_at is None:
        return None
    hub = hub_port.position.x if vertical else hub_port.position.y
    spokes = tuple(port.position.x if vertical else port.position.y for port in spoke_ports)
    far = max(spokes, key=lambda value: (abs(value - hub), value))
    if net.kind == "merge":
        return _TrunkRun(far, hub, net.rail_at)
    return _TrunkRun(hub, far, net.rail_at)


def _rail_clamp_diagnostics(
    net: NetSpec,
    run: _TrunkRun | None,
    coordinate: float,
) -> tuple[Diagnostic, ...]:
    """Say out loud that an authored ``rail_at`` had to give way to clearances."""

    if run is None or abs(coordinate - run.requested) <= _RAIL_TOLERANCE:
        return ()
    achieved = run.fraction_of(coordinate)
    placement = (
        "the trunk run has no length to measure along"
        if achieved is None
        else f"the nearest clear rail sits at {achieved:.3f}"
    )
    return (
        Diagnostic(
            "routing.net.rail-at.clamped",
            f"Requested rail_at {run.fraction:.3f} leaves no clearance; {placement}.",
            Severity.WARNING,
            entity_id=net.id,
            hint="Open a gap at that fraction of the run, or request a clearer one.",
        ),
    )


def _rail_coordinate(
    net: NetSpec,
    boundary: Rect,
    preferred: Point,
    escapes: tuple[Point, ...],
    escape_sides: tuple[tuple[Point, Side], ...],
    obstacles: tuple[Rect, ...],
    vertical: bool,
    *,
    requested: float | None = None,
) -> float:
    if net.rail_hint is not None:
        return {
            Side.WEST: boundary.left,
            Side.EAST: boundary.right,
            Side.NORTH: boundary.top,
            Side.SOUTH: boundary.bottom,
        }[net.rail_hint]
    # An authored fraction replaces the hub escape as the preference; the search
    # below already walks candidates outward from it, so an infeasible request
    # lands on the nearest rail that clears every obstacle.
    preferred_value = (
        requested if requested is not None else (preferred.x if vertical else preferred.y)
    )
    transverse = tuple(point.y if vertical else point.x for point in escapes)
    low, high = _rail_interval(boundary, escape_sides, vertical)
    candidates = _rail_candidates(preferred_value, boundary, obstacles, vertical)
    if requested is not None and low <= high:
        # The band edge is the closest a request outside the band can be honoured,
        # and it is nothing any obstacle offers, so the clamp target is added by
        # hand -- only for an authored request, so unhinted rails never move.
        clamped = min(high, max(low, requested))
        candidates = (clamped, *(value for value in candidates if value != clamped))
    if low <= high:
        feasible = tuple(value for value in candidates if low <= value <= high)
        candidates = feasible + tuple(
            value for value in candidates if value not in set(feasible)
        )
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


def _rail_interval(
    boundary: Rect,
    escape_sides: tuple[tuple[Point, Side], ...],
    vertical: bool,
) -> tuple[float, float]:
    """The rail band whose stems never double back against their port sides."""

    low = boundary.left if vertical else boundary.top
    high = boundary.right if vertical else boundary.bottom
    for escape, side in escape_sides:
        if vertical:
            if side is Side.WEST:
                high = min(high, escape.x)
            elif side is Side.EAST:
                low = max(low, escape.x)
        elif side is Side.NORTH:
            high = min(high, escape.y)
        elif side is Side.SOUTH:
            low = max(low, escape.y)
    return low, high


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


def _trunk_escapes(
    escapes: tuple[Point, ...],
    hub_escape: Point,
    hub_side: Side,
    vertical: bool,
) -> tuple[Point, ...]:
    """Junction reach when the rail runs along the hub port axis.

    Such a trunk starts at the hub escape, so a junction behind that point would
    drag the rail back across the hub component. Perpendicular rails keep every
    junction, and `_rail_interval` guards their coordinate instead.
    """

    if vertical is _horizontal(hub_side):
        return escapes
    if vertical:
        reach = max if hub_side is Side.SOUTH else min
        return tuple(Point(point.x, reach(point.y, hub_escape.y)) for point in escapes)
    reach = max if hub_side is Side.EAST else min
    return tuple(Point(reach(point.x, hub_escape.x), point.y) for point in escapes)


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
    leg = _route_leg(
        fitted,
        reference,
        escape,
        junction,
        style,
        boundary,
        occupied,
        departure=_horizontal(port.side),
    )
    centerline = simplify_polyline((port.position, *leg))
    # Only the node end takes the standoff; the junction end has to stay on the
    # rail exactly, or the net opens a gap at its own joint.
    shaft = shorten_start(centerline, style.connector_standoff.points)
    return RoutedStem(reference, centerline, shaft)


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
    leg = _route_leg(
        fitted,
        reference,
        junction,
        escape,
        style,
        boundary,
        occupied,
        arrival=_horizontal(port.side),
    )
    centerline = simplify_polyline((*leg, port.position))
    # Node end only: the junction end stays on the rail (see ``_source_stem``).
    shaft = shorten_end(
        centerline,
        style.arrow_length.points + style.connector_standoff.points,
    )
    return RoutedStem(reference, centerline, shaft, True)


def _route_leg(
    fitted: FittedFigure,
    endpoint: PortRef,
    start: Point,
    end: Point,
    style: LayoutStyle,
    boundary: Rect,
    occupied: tuple[Segment, ...],
    *,
    departure: bool | None = None,
    arrival: bool | None = None,
) -> tuple[Point, ...]:
    clearance = style.route_clearance.points
    obstacles = tuple(
        node.bounds.inflated(clearance)
        for node in fitted.nodes
        if node.measured.spec.id != endpoint.node_id
        and node.measured.spec.kind not in TRANSPARENT_KINDS
    ) + group_obstacles(fitted, (endpoint.node_id,), (start, end), clearance)
    confined = confined_groups(fitted, (endpoint.node_id,), (start, end))
    route = shortest_orthogonal_path(
        start,
        end,
        obstacles,
        costs=PathCosts(
            style.bend_penalty,
            separation=style.port_spacing.points,
            clearance=clearance,
        ),
        occupied=occupied,
        boundary=boundary,
        confined=confined,
        departure=departure,
        arrival=arrival,
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
    return collapse_zigzags(route, obstacles, style.elbow_radius.points, occupied)


def net_routing_boundary(
    fitted: FittedFigure,
    net: NetSpec,
    clearance: float,
) -> Rect:
    groups = {group.id: group for group in fitted.measured.semantic.groups}
    fitted_groups = {group.measured.spec.id: group for group in fitted.groups}
    parents = parent_map(fitted)
    node_ids = tuple(ref.node_id for ref in net.sources + net.targets)
    common = set(ancestor_ids(parents, node_ids[0]))
    for node_id in node_ids[1:]:
        common.intersection_update(ancestor_ids(parents, node_id))
    owner = next(
        group_id for group_id in ancestor_ids(parents, node_ids[0]) if group_id in common
    )
    while groups[owner].role == "layout" and owner in parents:
        owner = parents[owner]
    return fitted_groups[owner].bounds.inflated(-clearance)
