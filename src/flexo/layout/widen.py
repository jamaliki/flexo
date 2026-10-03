"""Widen a box so the arrows that share one of its sides meet it across its middle.

Arrows that share a side of a box meet it within the central ``pin_spread`` of
that side (``flexo.conventions``), and an arrow alone on the side of the box it
leaves leaves from that side's middle. Routing keeps both wherever it can and,
where it cannot, draws the line straight and lets the shared end drift toward a
corner: three projections into a block no wider than they are land on its
corners.

Geometry can settle it before routing starts. A plain box -- a block, an MLP --
has no drawing that depends on its width, so it may grow across its parent's
axis, within the room its parent gives it, until every straight arrow sharing a
side lands inside the central spread. The boxes feeding it keep their centres,
and every line stays straight. Where the parent has no such room the box grows
as far as it can, and the arrows that still fall outside land nearer the
corners rather than leaving their own boxes off-centre.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from flexo.geometry import Point, Rect, Side
from flexo.ir.fitted import FittedGroup, FittedNode, ResolvedPort
from flexo.ir.semantic import FigureSpec, LayoutKind, layout_connections
from flexo.style import LayoutStyle

WIDENING_KINDS = frozenset(
    {"block", "mlp", "cnn", "terminal", "io", "database", "server", "queue", "document"}
)
"""Components whose drawing is centred in the box, whatever its width.

A cylinder's lid is an eighth of its shorter side, so a database widened is the
same cylinder, longer; a cloud's puffs would stretch and a person's figure would
not grow, so neither is here."""

_EPSILON = 1e-6

_SLACK = 0.25
"""Points of room past the spread's edge, so an arrival on it is not clamped by rounding."""


def widen_boxes(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...],
    kinds: dict[str, LayoutKind],
    style: LayoutStyle,
) -> tuple[FittedNode, ...]:
    """Nodes, with each plain box widened until the arrows sharing a side meet its middle."""

    parent = {child: group for group in groups for child in group.measured.spec.children}
    by_id = {node.measured.spec.id: node for node in nodes}
    lines = [
        connection
        for connection in layout_connections(figure)
        if connection.source.node_id != connection.target.node_id
        and not connection.externally_routed
        and not connection.from_net
    ]
    partners: defaultdict[str, list[str]] = defaultdict(list)
    for connection in lines:
        partners[connection.source.node_id].append(connection.target.node_id)
        partners[connection.target.node_id].append(connection.source.node_id)
    spread = style.conventions.pin_spread
    for node_id, others in partners.items():
        node = by_id[node_id]
        owner = parent.get(node_id)
        if node.measured.spec.kind not in WIDENING_KINDS or owner is None or spread <= 0.0:
            continue
        kind = kinds.get(owner.measured.spec.id)
        across = "x" if kind in {"column", "stack"} else "y" if kind == "row" else None
        if across is None:
            continue
        room = owner.content_bounds
        low, high = (room.left, room.right) if across == "x" else (room.top, room.bottom)
        wanted = _wanted_span(
            node, [by_id[other] for other in others], by_id, across, spread, (low, high)
        )
        if wanted is None:
            continue
        start, end = max(wanted[0], low), min(wanted[1], high)
        by_id[node_id] = _resized(node, start, end, across)
    return tuple(by_id[node.measured.spec.id] for node in nodes)


def _wanted_span(
    node: FittedNode,
    others: list[FittedNode],
    nodes: dict[str, FittedNode],
    across: str,
    spread: float,
    room: tuple[float, float],
) -> tuple[float, float] | None:
    """The extent along ``across`` that puts every shared side's arrows in its middle,
    or None when the box already does."""

    bounds = node.bounds
    start, end = (bounds.left, bounds.right) if across == "x" else (bounds.top, bounds.bottom)
    sides: defaultdict[bool, list[float]] = defaultdict(list)
    for other in others:
        box = other.bounds
        if across == "x":
            before, after = box.bottom <= bounds.top, box.top >= bounds.bottom
            centre = box.center.x
        else:
            before, after = box.right <= bounds.left, box.left >= bounds.right
            centre = box.center.y
        # Only an arrow that already lands on this box has a place to keep: one
        # whose box sits beyond it, level with it, with nothing between. Growing
        # to catch an arrow that misses the box would turn a block into a bus
        # bar -- a tall Discriminator, a wall of a Symbol table.
        if (before or after) and start < centre < end and not _between(node, other, nodes, across):
            sides[after].append(centre)
    shared = [centres for centres in sides.values() if len(centres) > 1]
    if not shared:
        return None
    margin = (1.0 - spread) / 2.0
    first = min(min(centres) for centres in shared)
    last = max(max(centres) for centres in shared)
    width = end - start
    if first >= start + margin * width - _EPSILON and last <= end - margin * width + _EPSILON:
        return None
    new_start, new_end = start, end
    for _ in range(50):  # each round shrinks the shortfall by 2 * margin
        length = new_end - new_start
        new_start = min(start, first - margin * length - _SLACK)
        new_end = max(end, last + margin * length + _SLACK)
        if abs((new_end - new_start) - length) <= _EPSILON:
            break
    return new_start, new_end


def _between(
    node: FittedNode, other: FittedNode, nodes: dict[str, FittedNode], across: str
) -> bool:
    """True when a third box stands in the straight run from ``other`` to ``node``."""

    a, b = node.bounds, other.bounds
    if across == "x":
        near, far = sorted((a.top, b.bottom)) if b.bottom <= a.top else sorted((a.bottom, b.top))
        line = b.center.x
    else:
        near, far = sorted((a.left, b.right)) if b.right <= a.left else sorted((a.right, b.left))
        line = b.center.y
    for third in nodes.values():
        if third is node or third is other:
            continue
        box = third.bounds
        along = (box.top, box.bottom) if across == "x" else (box.left, box.right)
        side = (box.left, box.right) if across == "x" else (box.top, box.bottom)
        if along[0] < far - _EPSILON and along[1] > near + _EPSILON and side[0] < line < side[1]:
            return True
    return False


def _resized(node: FittedNode, start: float, end: float, across: str) -> FittedNode:
    """``node`` spanning ``start`` to ``end`` along ``across``.

    Its ports keep where they are along each side -- a widened box only grows, so
    they stay on it -- and whatever they were lined up with stays lined up.
    """

    old = node.bounds
    if across == "x":
        bounds = Rect(start, old.y, end - start, old.height)
    else:
        bounds = Rect(old.x, start, old.width, end - start)
    edge = {
        Side.NORTH: lambda point: Point(point.x, bounds.top),
        Side.SOUTH: lambda point: Point(point.x, bounds.bottom),
        Side.WEST: lambda point: Point(bounds.left, point.y),
        Side.EAST: lambda point: Point(bounds.right, point.y),
    }
    return replace(
        node,
        bounds=bounds,
        ports=tuple(
            ResolvedPort(port.name, port.side, edge[port.side](port.position))
            for port in node.ports
        ),
    )
