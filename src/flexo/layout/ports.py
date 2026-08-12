"""Adaptive attachment-port placement after component bounds are known."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from statistics import fmean

from flexo.geometry import Point, Side
from flexo.ir.fitted import FittedNode, ResolvedPort
from flexo.ir.semantic import FigureSpec, PortSpec, layout_connections
from flexo.style import LayoutStyle


def adapt_ports(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    style: LayoutStyle,
) -> tuple[FittedNode, ...]:
    """Align generated target and source ports without changing explicit anchors."""

    result = nodes
    for move_targets in (True, False, True):
        result = _adapt_endpoint_ports(figure, result, style, move_targets=move_targets)
    return result


def _adapt_endpoint_ports(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    style: LayoutStyle,
    *,
    move_targets: bool,
) -> tuple[FittedNode, ...]:
    by_id = {node.measured.spec.id: node for node in nodes}
    desired: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
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
        if moving_spec.side in {Side.NORTH, Side.SOUTH}:
            coordinate = opposite.position.x
        else:
            coordinate = opposite.position.y
        desired[(moving_ref.node_id, moving_ref.port_name)].append(coordinate)

    result = []
    for node in nodes:
        positions = {port.name: port.position for port in node.ports}
        specs_by_side: defaultdict[Side, list[PortSpec]] = defaultdict(list)
        for port in node.measured.spec.ports:
            specs_by_side[port.side].append(port)
        for side, specs in specs_by_side.items():
            candidates = [
                (port, fmean(desired[(node.measured.spec.id, port.name)]))
                for port in specs
                if desired[(node.measured.spec.id, port.name)]
            ]
            if not candidates or any(not port.adaptive for port in specs):
                continue
            vertical = side in {Side.EAST, Side.WEST}
            start = node.bounds.top if vertical else node.bounds.left
            end = node.bounds.bottom if vertical else node.bounds.right
            margin = style.corner_radius.points
            packed = _pack_coordinates(
                candidates,
                start + margin,
                end - margin,
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
