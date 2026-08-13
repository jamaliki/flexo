"""Adaptive attachment-port placement after component bounds are known."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from statistics import fmean

from flexo.components import TRANSPARENT_KINDS
from flexo.geometry import Point, Rect, Side
from flexo.ir.fitted import FittedNode, ResolvedPort
from flexo.ir.semantic import (
    FigureSpec,
    LayoutConnection,
    PortSpec,
    layout_connections,
)
from flexo.style import LayoutStyle

_MAX_ADAPT_PASSES = 8
"""Upper bound on alternating target/source passes; the loop exits when settled."""

_VERTICAL_SIDES = frozenset({Side.EAST, Side.WEST})
"""Port sides whose adaptive coordinate runs down the component edge."""

_CENTER_BAND_FRACTION = 0.3
"""How far, as a fraction of the side length, adaptation may slide a port.

Adaptation fine-tunes alignment; it does not choose where an arrow meets a box.
An adapted coordinate is accepted only inside the authored offset plus or minus
this fraction of the side, which is wide enough to absorb the few-point
mismatches that would otherwise read as micro-jogs and narrow enough that no
attachment drifts toward a corner. Outside the band the authored offset wins:
a centred Z-bend is the author's design language, an off-centre attachment is
not.
"""

_EPSILON = 1e-7

_INFINITY = float("inf")


def adapt_ports(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    style: LayoutStyle,
) -> tuple[FittedNode, ...]:
    """Align generated target and source ports without changing explicit anchors.

    Target and source passes alternate until neither moves a port. A fixed pass
    count can stop mid-flight: when the last pass repacks a port -- a clamped
    neighbour on the same side pushing it along by one spacing step -- the port
    at the other end of that connection was already placed and stays behind,
    which reads as a 2-4 pt jog right after a multi-output port. Settling
    guarantees every remaining offset is one the packing constraints force.

    Every adapted coordinate is bounded by a centred band around the authored
    offset (`_CENTER_BAND_FRACTION`): inside it, adaptation slides the port and
    the run comes out straight; outside it, the port stays where the author put
    it and the router draws a centred Z-bend.

    Net legs adapt under two extra rules, because a net is joined by a shared
    rail rather than by a run between its two ports:

    - a leg whose ports face perpendicular axes contributes no desired
      coordinate at all -- the rail junction, not the port, does that turn, so
      pulling the port only drags it off the block it taps;
    - a leg's desired coordinate is taken all-or-nothing: a port whose desired
      coordinate is unreachable keeps its authored offset instead of clamping to
      the band edge, where it would sit visibly off-centre chasing a hub it can
      never line up with.
    """

    result = nodes
    settled = 0
    move_targets = True
    for _ in range(_MAX_ADAPT_PASSES):
        moved = _adapt_endpoint_ports(figure, result, style, move_targets=move_targets)
        settled = settled + 1 if _port_positions(moved) == _port_positions(result) else 0
        result = moved
        if settled == 2:
            break
        move_targets = not move_targets
    return _straighten_pairs(figure, result, style)


def _port_positions(nodes: tuple[FittedNode, ...]) -> tuple[tuple[Point, ...], ...]:
    return tuple(tuple(port.position for port in node.ports) for node in nodes)


def _straighten_pairs(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    style: LayoutStyle,
) -> tuple[FittedNode, ...]:
    """Slide collinear one-to-one pairs off the clearance ring of what they pass.

    Two ports that already share a cross-axis coordinate still route as an
    S-jog when the straight run between them grazes another component: the
    router lifts the middle segment out of that component's clearance ring.
    Moving *both* ends of such a pair by the same small amount keeps them
    collinear and gives the router the straight line instead.
    """

    result = nodes
    for connection in _solitary_pairs(figure, nodes):
        result = _straighten_pair(result, connection, style)
    return result


def _solitary_pairs(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
) -> tuple[LayoutConnection, ...]:
    """Connections whose two adaptive ports serve no other connection."""

    connections = layout_connections(figure)
    degree: defaultdict[tuple[str, str], int] = defaultdict(int)
    for connection in connections:
        for reference in (connection.source, connection.target):
            degree[(reference.node_id, reference.port_name)] += 1
    by_id = {node.measured.spec.id: node for node in nodes}
    return tuple(
        connection
        for connection in connections
        if connection.source.node_id != connection.target.node_id
        and all(
            degree[(reference.node_id, reference.port_name)] == 1
            and _freely_adaptive(by_id[reference.node_id], reference.port_name)
            for reference in (connection.source, connection.target)
        )
    )


def _freely_adaptive(node: FittedNode, port_name: str) -> bool:
    """True when this port adapts and shares its side only with adaptive ports."""

    spec = next(port for port in node.measured.spec.ports if port.name == port_name)
    return spec.adaptive and all(
        port.adaptive for port in node.measured.spec.ports if port.side is spec.side
    )


def _straighten_pair(
    nodes: tuple[FittedNode, ...],
    connection: LayoutConnection,
    style: LayoutStyle,
) -> tuple[FittedNode, ...]:
    by_id = {node.measured.spec.id: node for node in nodes}
    ends = tuple(
        (by_id[reference.node_id], by_id[reference.node_id].port(reference.port_name))
        for reference in (connection.source, connection.target)
    )
    (_, first), (_, second) = ends
    vertical = first.side in _VERTICAL_SIDES
    if (second.side in _VERTICAL_SIDES) is not vertical:
        return nodes
    coordinate = first.position.y if vertical else first.position.x
    if abs(coordinate - (second.position.y if vertical else second.position.x)) > _EPSILON:
        return nodes
    run = _interval(
        first.position.x if vertical else first.position.y,
        second.position.x if vertical else second.position.y,
    )
    if run[1] - run[0] <= _EPSILON:
        return nodes
    endpoint_ids = {connection.source.node_id, connection.target.node_id}
    blocked = tuple(
        _blocked_interval(node, vertical, style.route_clearance.points)
        for node in nodes
        if node.measured.spec.id not in endpoint_ids
        and node.measured.spec.kind not in TRANSPARENT_KINDS
        and _overlaps(_along_interval(node.bounds, vertical), run)
    )
    if not any(low - _EPSILON <= coordinate <= high + _EPSILON for low, high in blocked):
        return nodes
    window = _shared_window(ends, vertical, style)
    target = _nearest_clear(coordinate, window, blocked)
    if target is None:
        return nodes
    return tuple(
        _moved_port(node, connection, target, vertical)
        if node.measured.spec.id in endpoint_ids
        else node
        for node in nodes
    )


def _moved_port(
    node: FittedNode,
    connection: LayoutConnection,
    coordinate: float,
    vertical: bool,
) -> FittedNode:
    name = next(
        reference.port_name
        for reference in (connection.source, connection.target)
        if reference.node_id == node.measured.spec.id
    )
    return replace(
        node,
        ports=tuple(
            ResolvedPort(
                port.name,
                port.side,
                Point(port.position.x, coordinate)
                if vertical
                else Point(coordinate, port.position.y),
            )
            if port.name == name
            else port
            for port in node.ports
        ),
    )


def _shared_window(
    ends: tuple[tuple[FittedNode, ResolvedPort], ...],
    vertical: bool,
    style: LayoutStyle,
) -> tuple[float, float]:
    """Cross-axis values both ends can reach without disturbing their neighbours."""

    margin = style.corner_radius.points
    spacing = max(style.port_spacing.points, style.arrow_width.points)
    low = -_INFINITY
    high = _INFINITY
    for node, port in ends:
        bounds = node.bounds
        low = max(low, (bounds.top if vertical else bounds.left) + margin)
        high = min(high, (bounds.bottom if vertical else bounds.right) - margin)
        spec = next(item for item in node.measured.spec.ports if item.name == port.name)
        band = _center_band(
            _authored_coordinate(node, spec, vertical),
            bounds.height if vertical else bounds.width,
        )
        low = max(low, band[0])
        high = min(high, band[1])
        current = port.position.y if vertical else port.position.x
        for neighbour in node.ports:
            if neighbour.name == port.name or neighbour.side is not port.side:
                continue
            value = neighbour.position.y if vertical else neighbour.position.x
            if value < current:
                low = max(low, value + spacing)
            elif value > current:
                high = min(high, value - spacing)
    return low, high


def _nearest_clear(
    coordinate: float,
    window: tuple[float, float],
    blocked: tuple[tuple[float, float], ...],
) -> float | None:
    low, high = window
    if low > high:
        return None
    edges = tuple(edge for interval in blocked for edge in interval)
    candidates = sorted(
        {min(high, max(low, bound)) for bound in (low, high, *edges)},
        key=lambda value: (abs(value - coordinate), value),
    )
    for candidate in candidates:
        if not any(
            start + _EPSILON < candidate < end - _EPSILON for start, end in blocked
        ):
            return candidate
    return None


def _blocked_interval(
    node: FittedNode,
    vertical: bool,
    clearance: float,
) -> tuple[float, float]:
    bounds = node.bounds.inflated(clearance)
    return (bounds.top, bounds.bottom) if vertical else (bounds.left, bounds.right)


def _along_interval(bounds: Rect, vertical: bool) -> tuple[float, float]:
    return (bounds.left, bounds.right) if vertical else (bounds.top, bounds.bottom)


def _interval(first: float, second: float) -> tuple[float, float]:
    return (min(first, second), max(first, second))


def _overlaps(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return first[0] < second[1] - _EPSILON and second[0] < first[1] - _EPSILON


def _center_band(home: float, length: float) -> tuple[float, float]:
    """The stretch of a side an adapted coordinate may reach, around its offset."""

    reach = _CENTER_BAND_FRACTION * length
    return home - reach, home + reach


def _within(value: float, band: tuple[float, float]) -> bool:
    return band[0] - _EPSILON <= value <= band[1] + _EPSILON


def _authored_coordinate(node: FittedNode, spec: PortSpec, vertical: bool) -> float:
    """Where this port sits before any adaptation, along its side."""

    point = node.bounds.point_on(spec.side, spec.offset)
    return point.y if vertical else point.x


def _perpendicular(first: Side, second: Side) -> bool:
    """True when the two sides' adaptive coordinates run along different axes."""

    return (first in _VERTICAL_SIDES) is not (second in _VERTICAL_SIDES)


def _adapt_endpoint_ports(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    style: LayoutStyle,
    *,
    move_targets: bool,
) -> tuple[FittedNode, ...]:
    by_id = {node.measured.spec.id: node for node in nodes}
    desired: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    net_only: dict[tuple[str, str], bool] = {}
    for connection in layout_connections(figure):
        moving_ref = connection.target if move_targets else connection.source
        opposite_ref = connection.source if move_targets else connection.target
        moving_node = by_id[moving_ref.node_id]
        moving_spec = next(
            port for port in moving_node.measured.spec.ports if port.name == moving_ref.port_name
        )
        if not moving_spec.adaptive:
            continue
        opposite = by_id[opposite_ref.node_id].port(opposite_ref.port_name)
        if connection.from_net and _perpendicular(moving_spec.side, opposite.side):
            continue
        if moving_spec.side in {Side.NORTH, Side.SOUTH}:
            coordinate = opposite.position.x
        else:
            coordinate = opposite.position.y
        key = (moving_ref.node_id, moving_ref.port_name)
        desired[key].append(coordinate)
        net_only[key] = net_only.get(key, True) and connection.from_net

    result = []
    for node in nodes:
        positions = {port.name: port.position for port in node.ports}
        specs_by_side: defaultdict[Side, list[PortSpec]] = defaultdict(list)
        for port in node.measured.spec.ports:
            specs_by_side[port.side].append(port)
        for side, specs in specs_by_side.items():
            if any(not port.adaptive for port in specs):
                continue
            vertical = side in _VERTICAL_SIDES
            start = node.bounds.top if vertical else node.bounds.left
            end = node.bounds.bottom if vertical else node.bounds.right
            margin = style.corner_radius.points
            low = start + margin
            high = end - margin
            candidates: list[tuple[PortSpec, float]] = []
            for port in specs:
                key = (node.measured.spec.id, port.name)
                if not desired[key]:
                    continue
                coordinate = fmean(desired[key])
                home = _authored_coordinate(node, port, vertical)
                band = _center_band(home, end - start)
                # A net tap judges reachability against the tighter of the two
                # limits, because packing and the band bound it alike.
                feasible = (max(low, band[0]), min(high, band[1]))
                if not _within(coordinate, band) or (
                    net_only.get(key, False) and not _within(coordinate, feasible)
                ):
                    # All-or-nothing: an attachment that cannot line up nearby
                    # returns to its authored offset instead of clamping to a
                    # band edge. It still packs, so a neighbour on the same side
                    # keeps its lane.
                    coordinate = home
                candidates.append((port, coordinate))
            if not candidates:
                continue
            packed = _pack_coordinates(
                candidates,
                low,
                high,
                max(style.port_spacing.points, style.arrow_width.points),
            )
            for port, coordinate in packed:
                if vertical:
                    x = node.bounds.left if side is Side.WEST else node.bounds.right
                    positions[port.name] = Point(x, coordinate)
                else:
                    y = node.bounds.top if side is Side.NORTH else node.bounds.bottom
                    positions[port.name] = Point(coordinate, y)
        result.append(
            replace(
                node,
                ports=tuple(
                    ResolvedPort(port.name, port.side, positions[port.name])
                    for port in node.measured.spec.ports
                ),
            )
        )
    return tuple(result)


def _pack_coordinates(
    candidates: list[tuple[PortSpec, float]],
    low: float,
    high: float,
    spacing: float,
) -> tuple[tuple[PortSpec, float], ...]:
    ordered = sorted(candidates, key=lambda item: (item[1], item[0].name))
    if len(ordered) == 1:
        port, value = ordered[0]
        return ((port, min(high, max(low, value))),)
    if spacing * (len(ordered) - 1) > high - low:
        spacing = (high - low) / (len(ordered) - 1)
    values = [min(high, max(low, value)) for _, value in ordered]
    for index in range(1, len(values)):
        values[index] = max(values[index], values[index - 1] + spacing)
    values[-1] = min(values[-1], high)
    for index in reversed(range(len(values) - 1)):
        values[index] = min(values[index], values[index + 1] - spacing)
    return tuple((item[0], value) for item, value in zip(ordered, values, strict=True))
