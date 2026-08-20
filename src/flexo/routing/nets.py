"""Route authored fan-out buses and many-to-one merge rails."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from flexo.components import TRANSPARENT_KINDS, TRANSPARENT_ROLES, route_clearance
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Segment, Side, segments
from flexo.hierarchy import ancestors, parent_map, routing_boundary
from flexo.ir.fitted import FittedFigure, ResolvedPort
from flexo.ir.measured import TextMetrics
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

_INFINITY = float("inf")

_RAIL_TOLERANCE = 1e-6
"""How far a placed rail may sit from the requested one and still count as honoured."""

_OPPOSITE = {
    Side.NORTH: Side.SOUTH,
    Side.SOUTH: Side.NORTH,
    Side.EAST: Side.WEST,
    Side.WEST: Side.EAST,
}


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

    parents = parent_map(fitted.measured.semantic.groups)
    protected: set[str] = set()
    for node_id in node_ids:
        protected.update(ancestors(parents, node_id))
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

    parents = parent_map(fitted.measured.semantic.groups)
    owned: set[str] = set()
    for node_id in node_ids:
        owned.update(ancestors(parents, node_id))
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
    boundary = routing_boundary(
        fitted,
        tuple(ref.node_id for ref in net.sources + net.targets),
        style.route_boundary_clearance.points,
    )
    target_clearance = style.arrival_clearance.points
    source_escapes = tuple(
        (_escape(port, style.route_clearance.points), ref) for port, ref in sources
    )
    target_escapes = tuple((_escape(port, target_clearance), ref) for port, ref in targets)
    hub_port = sources[0][0] if net.kind == "fan-out" else targets[0][0]
    hub_escape = source_escapes[0][0] if net.kind == "fan-out" else target_escapes[0][0]
    spokes = targets if net.kind == "fan-out" else sources
    vertical = _vertical_rail(
        net.rail_hint,
        net.via,
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
        node.bounds.inflated(route_clearance(node.measured.spec, style))
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
    label_metrics = measurer.measure(net.label) if net.label else None
    coordinate = _rail_coordinate(
        net,
        boundary,
        hub_escape,
        trunk_escapes,
        escape_sides,
        obstacles,
        vertical,
        requested=None if run is None else run.requested,
        caption=_caption_run(label_metrics, style, vertical),
    )
    trunk_escapes = _balanced_trunk(
        net,
        trunk_escapes,
        hub_escape,
        hub_port.side,
        vertical,
        coordinate,
        obstacles,
        hub_index=0 if net.kind == "fan-out" else len(sources),
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
    label_position = (
        rail_label_position(
            rail,
            tuple(stem.shaft for stem in (*source_stems, *target_stems)),
            label_metrics,
            style,
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
        _rail_clamp_diagnostics(net, run, coordinate)
        + _via_clamp_diagnostics(net, coordinate, all_escapes, vertical),
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
    return port.side.escaped(port.position, distance)


def _vertical_rail(
    hint: Side | None,
    via: Side | None,
    hub_side: Side,
    spoke_sides: tuple[Side, ...],
) -> bool:
    """Which axis the shared rail runs along, decided by the spokes it feeds.

    An explicit hint always wins, and a ``via`` hint answers the same question
    the same way -- a rail on the west is a rail that runs north to south -- so
    the two read the side identically and differ only in what they then do with
    the coordinate. Otherwise the spoke ports vote: east/west spokes are entered
    from a vertical rail, north/south spokes from a horizontal one. A tie runs
    the trunk *along* the hub port axis, so a south hub keeps one straight drop
    instead of doglegging into a cross rail.
    """

    if hint is not None:
        return hint.horizontal
    if via is not None:
        return via.horizontal
    votes = sum(1 if side.horizontal else -1 for side in spoke_sides)
    if votes == 0:
        return not hub_side.horizontal
    return votes > 0


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


_BOUNDARY_EDGE = {
    Side.WEST: lambda bounds: bounds.left,
    Side.EAST: lambda bounds: bounds.right,
    Side.NORTH: lambda bounds: bounds.top,
    Side.SOUTH: lambda bounds: bounds.bottom,
}
"""The coordinate a side names on a routing boundary: one reading for two hints."""


_VIA_TOLERANCE = 0.5
"""How far past its ports a rail may sit before it counts as taking that side."""


def _via_clamp_diagnostics(
    net: NetSpec,
    coordinate: float,
    escapes: tuple[Point, ...],
    vertical: bool,
) -> tuple[Diagnostic, ...]:
    """Say out loud that an authored ``via`` could not have the side it asked for.

    The hint is honoured as long as the rail is not parked beyond every port on
    the side it refused: anywhere between them is the corridor the layout left,
    and the search already took it as far toward ``via`` as the clearances allow.
    """

    if net.via is None:
        return ()
    values = tuple(point.x if vertical else point.y for point in escapes)
    low, high = min(values), max(values)
    refused = (
        coordinate > high + _VIA_TOLERANCE
        if net.via in {Side.WEST, Side.NORTH}
        else coordinate < low - _VIA_TOLERANCE
    )
    if not refused:
        return ()
    achieved = _OPPOSITE[net.via]
    return (
        Diagnostic(
            "routing.net.via.clamped",
            f"Requested via {net.via.value} leaves no clear rail; the shared rail "
            f"sits {achieved.value} of this net's ports instead.",
            Severity.WARNING,
            entity_id=net.id,
            hint=f"Open a corridor {net.via.value} of the ports, or drop the hint.",
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
    caption: float = 0.0,
) -> float:
    if net.rail_hint is not None:
        return _BOUNDARY_EDGE[net.rail_hint](boundary)
    transverse = tuple(point.y if vertical else point.x for point in escapes)
    low, high = _rail_interval(boundary, escape_sides, vertical)
    # An authored fraction replaces the corridor midpoint as the preference; the
    # search below already walks candidates outward from it, so an infeasible
    # request lands on the nearest rail that clears every obstacle. A ``via``
    # hint prefers the boundary edge on its own side the way ``rail`` pins to it
    # -- and then, unlike ``rail``, lets the candidate search walk back inward
    # until the rail is clear, which is what makes it a lean rather than a pin.
    preferred_value = (
        requested
        if requested is not None
        else _BOUNDARY_EDGE[net.via](boundary)
        if net.via is not None
        else _preferred_rail(
            _corridor(escape_sides, vertical),
            preferred.x if vertical else preferred.y,
            caption,
        )
    )
    candidates = _rail_candidates(preferred_value, boundary, obstacles, vertical)
    if low <= high:
        # The band edge is the closest a preference outside the band can be
        # honoured, and it is nothing any obstacle offers, so the clamp target is
        # added by hand: a corridor too narrow to hold its own midpoint still
        # rails as close to the middle as the stems allow.
        clamped = min(high, max(low, preferred_value))
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


def _corridor(
    escape_sides: tuple[tuple[Point, Side], ...],
    vertical: bool,
) -> tuple[float, float]:
    """The gap this net's stems leave for its rail, as seen from the ports alone.

    Each port facing along the trunk axis walls off everything behind its own
    escape -- a rail there would make the stem double back -- so what is left
    between the walls is the corridor the layout opened for this net. A port
    facing *across* the axis walls off nothing: its stem turns at the rail
    whatever coordinate the rail has. Either end may therefore come back
    unbounded, which is the honest answer that there is no corridor on that side.
    """

    low = -_INFINITY
    high = _INFINITY
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


def _caption_run(
    label: TextMetrics | None,
    style: LayoutStyle,
    vertical: bool,
) -> float:
    """How much straight run this net's caption needs beside its rail.

    A caption is written above the horizontal run its net reads along. When the
    rail is horizontal, that run *is* the rail, and the caption rides on top of it
    however the rail is placed. When the rail is vertical, the captioned run is
    the trunk crossing it, and the rail may not be parked in the middle of the
    words -- so a vertical rail is told how wide the caption is and stays out of
    its way.
    """

    if label is None or not vertical:
        return 0.0
    return label.width + 2.0 * style.padding_x.points


def _preferred_rail(
    corridor: tuple[float, float],
    escape: float,
    caption: float,
) -> float:
    """Where an unhinted rail would rather sit: the middle of its free corridor.

    A rail one escape short of the hub -- what this used to be -- is a line drawn
    against the box the branches come out of, with the space the layout opened
    for them left empty beyond it. The middle of the corridor reads as a corridor
    the figure meant to leave: the same distance from the row above as from the
    row below, and the trunk and the stems each get half the run.

    A corridor too narrow to hold both halves of a captioned run is the exception.
    Halving it would leave the caption nowhere to sit but across the rail, so such
    a rail stays at the end of the corridor and hands the whole run to the words.

    Either way it is a *preference*. The candidate search still moves it to the
    nearest rail that clears every obstacle, and an authored ``rail`` or
    ``rail_at`` replaces it outright.
    """

    low, high = corridor
    if low == -_INFINITY or high == _INFINITY or low > high:
        return escape
    if caption > 0.0 and (high - low) / 2.0 < caption:
        return escape
    return (low + high) / 2.0


def _rail_interval(
    boundary: Rect,
    escape_sides: tuple[tuple[Point, Side], ...],
    vertical: bool,
) -> tuple[float, float]:
    """The rail band whose stems never double back, inside the routing boundary."""

    low, high = _corridor(escape_sides, vertical)
    return (
        max(low, boundary.left if vertical else boundary.top),
        min(high, boundary.right if vertical else boundary.bottom),
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

    if vertical is hub_side.horizontal:
        return escapes
    if vertical:
        reach = max if hub_side is Side.SOUTH else min
        return tuple(Point(point.x, reach(point.y, hub_escape.y)) for point in escapes)
    reach = max if hub_side is Side.EAST else min
    return tuple(Point(reach(point.x, hub_escape.x), point.y) for point in escapes)


def _balanced_trunk(
    net: NetSpec,
    escapes: tuple[Point, ...],
    hub_escape: Point,
    hub_side: Side,
    vertical: bool,
    coordinate: float,
    obstacles: tuple[Rect, ...],
    *,
    hub_index: int,
) -> tuple[Point, ...]:
    """Put the trunk's own junction in the middle of the run it has to itself.

    A trunk that leaves along the rail's own axis and finds the rail offset from
    it -- the encoder's output crossing the page into a decoder's cross-attention
    -- draws a Z: a stretch along the port axis, a crossbar over to the rail, and
    the rail carrying on the same way. ``_trunk_escapes`` puts the crossbar at the
    hub escape, which is the earliest place it can go, and the result is a
    one-sided L: a stub, a long crossbar drawn against the box it just left, then
    the whole run on the far side of it.

    The crossbar's own free run is from that escape to the nearest junction ahead
    of it, and its middle is the reading of that shape a figure means: two arms of
    roughly equal length with the crossing between them. Same default as
    ``_preferred_rail`` one axis over, and a preference in the same way -- the
    candidates walk outward from the midpoint until the arm and the crossbar both
    clear every obstacle, and an authored ``rail``, ``rail_at`` or ``via`` keeps
    the placement it asked for.

    Nothing moves unless the crossbar is the trunk's alone: a spoke behind the hub
    escape rides on the same coordinate (``_trunk_escapes`` clamps it there), and
    dragging that with the trunk would reshape a stem this has nothing to say
    about.
    """

    if net.rail_hint is not None or net.rail_at is not None or net.via is not None:
        return escapes
    if vertical is hub_side.horizontal:
        return escapes
    start = hub_escape.y if vertical else hub_escape.x
    if abs(coordinate - (hub_escape.x if vertical else hub_escape.y)) <= _RAIL_TOLERANCE:
        return escapes  # Trunk and rail are one straight line; there is no crossbar.
    forward = -1.0 if hub_side in {Side.NORTH, Side.WEST} else 1.0
    spokes = tuple(
        (point.y if vertical else point.x)
        for index, point in enumerate(escapes)
        if index != hub_index
    )
    if not spokes or any((value - start) * forward <= 0.0 for value in spokes):
        return escapes
    limit = min(spokes, key=lambda value: (value - start) * forward)
    for candidate in _trunk_candidates(start, limit, obstacles, vertical):
        if _trunk_clear(hub_escape, candidate, coordinate, vertical, obstacles):
            hub = escapes[hub_index]
            moved = Point(hub.x, candidate) if vertical else Point(candidate, hub.y)
            return (*escapes[:hub_index], moved, *escapes[hub_index + 1 :])
    return escapes


def _trunk_candidates(
    start: float,
    limit: float,
    obstacles: tuple[Rect, ...],
    vertical: bool,
) -> tuple[float, ...]:
    """Where the trunk's crossbar may sit, midpoint first and outward from it."""

    low, high = sorted((start, limit))
    preferred = (low + high) / 2.0
    values = {preferred, start}
    for obstacle in obstacles:
        edges = (obstacle.top, obstacle.bottom) if vertical else (obstacle.left, obstacle.right)
        values.update(value for value in edges if low <= value <= high)
    for first, second in tuple(pairwise(sorted(values))):
        values.add((first + second) / 2.0)
    return tuple(sorted(values, key=lambda value: (abs(value - preferred), value)))


def _trunk_clear(
    hub_escape: Point,
    candidate: float,
    coordinate: float,
    vertical: bool,
    obstacles: tuple[Rect, ...],
) -> bool:
    """Whether the trunk's arm and crossbar both clear every obstacle at ``candidate``."""

    corner = (
        Point(hub_escape.x, candidate) if vertical else Point(candidate, hub_escape.y)
    )
    junction = Point(coordinate, candidate) if vertical else Point(candidate, coordinate)
    return not any(
        segment.intersects_rect_interior(obstacle)
        for segment in (Segment(hub_escape, corner), Segment(corner, junction))
        for obstacle in obstacles
    )


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
        departure=port.side.horizontal,
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
        arrival=port.side.horizontal,
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
        node.bounds.inflated(route_clearance(node.measured.spec, style))
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



