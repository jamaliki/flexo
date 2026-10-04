"""Slide a group across its parent's axis so the arrows leaving it can run straight.

A column centres what it holds, and a row of inputs above a block is centred like
anything else. When those inputs feed ports near one end of the block, or feed two
blocks, the centred row leaves an input outside the stretch its port can slide
to, and its arrow jogs sideways. Port adaptation cannot mend that: it moves ports,
not boxes.

This pass moves boxes, within limits. A group whose parent stacks the other way
(a row in a column, a column in a row) may slide along its own axis, as far as
its parent's content box allows; siblings sit above and below it, so nothing can
collide. It slides only when that lets more of its arrows reach their ports
straight, and then by the least distance that does, so a figure that already
reads straight is left exactly as it was.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from flexo.geometry import Point, Rect, Side
from flexo.ir.fitted import FittedGroup, FittedNode, ResolvedPort
from flexo.ir.semantic import FigureSpec, LayoutKind, layout_connections
from flexo.style import LayoutStyle

_CENTER_BAND_FRACTION = 0.3
"""How far port adaptation may slide a port, as a fraction of its side (see ``ports``)."""

_SLIDING_ALIGNMENTS = frozenset({"center", "ports"})
"""Parents whose cross placement is a default, not a request to sit at one edge."""

_EPSILON = 1e-6


def slide_groups(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...],
    kinds: dict[str, LayoutKind],
    style: LayoutStyle,
) -> tuple[tuple[FittedNode, ...], tuple[FittedGroup, ...]]:
    """Nodes and groups, with each slidable group moved to straighten its arrows.

    Parents go first: a group slides with everything in it, and its children then
    judge their own slides from where it ended up.
    """

    parent = {
        child: group.measured.spec.id for group in groups for child in group.measured.spec.children
    }
    order = {group.measured.spec.id: index for index, group in enumerate(groups)}
    by_node = {node.measured.spec.id: node for node in nodes}
    written = {node.id: index for index, node in enumerate(figure.nodes)}
    by_group = {group.measured.spec.id: group for group in groups}
    every = layout_connections(figure)
    served = Counter(
        (end.node_id, end.port_name)
        for connection in every
        for end in (connection.source, connection.target)
    )
    # A straight-drawn or lane-routed line goes where it is told, whatever the
    # ports do, and a net meets its taps with a shared rail, not a straight run. A
    # fixed port that serves several arrows (a diamond's vertex) can send only one
    # of them straight, and the router picks which, so none of them can vouch for
    # a slide.
    connections = tuple(
        connection
        for connection in every
        if connection.source.node_id != connection.target.node_id
        and not connection.externally_routed
        and not connection.from_net
        and not any(
            served[(end.node_id, end.port_name)] > 1
            and not _adaptive(by_node[end.node_id], end.port_name)
            for end in (connection.source, connection.target)
        )
    )
    for group_id in sorted(by_group, key=lambda name: (_depth(name, parent), order[name])):
        owner = parent.get(group_id)
        if owner is None:
            continue
        across = _slide_axis(kinds.get(owner), by_group[owner].measured.spec.layout.align)
        if across is None:
            continue
        members = _nodes_within(group_id, by_group)
        shift = _best_shift(
            by_group[group_id].bounds,
            by_group[owner].content_bounds,
            across,
            members,
            connections,
            by_node,
            style,
            written,
        )
        if abs(shift) <= _EPSILON:
            continue
        dx, dy = (shift, 0.0) if across == "x" else (0.0, shift)
        for node_id in members:
            by_node[node_id] = _moved_node(by_node[node_id], dx, dy)
        for inner in _groups_within(group_id, by_group):
            by_group[inner] = _moved_group(by_group[inner], dx, dy)
    return (
        tuple(by_node[node.measured.spec.id] for node in nodes),
        tuple(by_group[group.measured.spec.id] for group in groups),
    )


def _depth(group_id: str, parent: dict[str, str]) -> int:
    depth = 0
    while group_id in parent:
        group_id = parent[group_id]
        depth += 1
    return depth


def _slide_axis(kind: LayoutKind | None, align: str) -> str | None:
    """The axis a child of this parent may slide along, or None when it may not."""

    if align not in _SLIDING_ALIGNMENTS:
        return None
    if kind in {"column", "stack"}:
        return "x"
    if kind == "row":
        return "y"
    return None


def _nodes_within(group_id: str, groups: dict[str, FittedGroup]) -> set[str]:
    found: set[str] = set()
    for child in groups[group_id].measured.spec.children:
        if child in groups:
            found |= _nodes_within(child, groups)
        else:
            found.add(child)
    return found


def _groups_within(group_id: str, groups: dict[str, FittedGroup]) -> list[str]:
    found = [group_id]
    for child in groups[group_id].measured.spec.children:
        if child in groups:
            found += _groups_within(child, groups)
    return found


def _best_shift(
    bounds: Rect,
    room: Rect,
    across: str,
    members: set[str],
    connections: tuple,
    nodes: dict[str, FittedNode],
    style: LayoutStyle,
    written: dict[str, int] | None = None,
) -> float:
    """The slide that lets the most arrows run straight, centred among them, or 0.

    Of slides that straighten as many, one that straightens an arrow running on, from
    a part written earlier to one written later, beats one that straightens a loop back:
    a part stays where its flow put it when a line back to it is drawn.
    """

    if across == "x":
        low, high = room.left - bounds.left, room.right - bounds.right
    else:
        low, high = room.top - bounds.top, room.bottom - bounds.bottom
    if high - low <= _EPSILON:
        return 0.0
    low, high = min(low, 0.0), max(high, 0.0)
    pairs = []
    forward: set[int] = set()
    for connection in connections:
        ends = (connection.source, connection.target)
        inside = [end for end in ends if end.node_id in members]
        if len(inside) != 1:
            continue
        mine = inside[0]
        other = connection.target if mine is connection.source else connection.source
        pair = _reaches(
            nodes[mine.node_id],
            mine.port_name,
            nodes[other.node_id],
            other.port_name,
            across,
            style,
        )
        if pair is not None and not _blocked(
            nodes, members, other.node_id, bounds, pair[1], across
        ):
            pairs.append(pair)
            onward = (written or {}).get(connection.source.node_id, 0) <= (written or {}).get(
                connection.target.node_id, 0
            )
            if onward:
                forward.add(len(pairs) - 1)
    if not pairs:
        return 0.0
    # Each arrow runs straight over a window of slides; the best slide lies at a
    # window's edge, or where one arrow's two ends sit exactly opposite each other.
    candidates = {0.0, low, high}
    for (mine_low, mine_high), (other_low, other_high) in pairs:
        candidates |= {
            other_high - mine_low,
            other_low - mine_high,
            (other_low + other_high - mine_low - mine_high) / 2.0,
        }
    choices = [value for value in candidates if low - _EPSILON <= value <= high + _EPSILON]

    def straight(shift: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        return [pairs[index] for index in straightened(shift)]

    def straightened(shift: float) -> list[int]:
        return [
            index
            for index, pair in enumerate(pairs)
            if pair[0][0] + shift <= pair[1][1] + _EPSILON
            and pair[1][0] <= pair[0][1] + shift + _EPSILON
        ]

    def off_centre(shift: float) -> float:
        return sum(
            abs((mine_low + mine_high) / 2.0 + shift - (other_low + other_high) / 2.0)
            for (mine_low, mine_high), (other_low, other_high) in straight(shift)
        )

    # Only more straight arrows justify a slide: a bend that stays a bend is no
    # better for being shorter, and a nudge of a point or two is port adaptation's job.
    best = min(
        choices,
        key=lambda value: (
            -len(straight(value)),
            -len(forward.intersection(straightened(value))),
            round(off_centre(value), 3),
            abs(value),
        ),
    )
    return best if len(straight(best)) > len(straight(0.0)) else 0.0


def _reaches(
    mine: FittedNode,
    mine_port: str,
    other: FittedNode,
    other_port: str,
    across: str,
    style: LayoutStyle,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Where each end of an arrow can sit along the slide axis, if the arrow runs
    across it: from one box to a box beyond it along the parent's stacking axis.

    Judged from where the boxes sit, not from the sides the ports are on yet: a
    port several arrows share takes the side most of them want, and the router
    still brings an odd one in on the face it arrives at.
    """

    if across == "x":
        beyond = other.bounds.bottom <= mine.bounds.top or other.bounds.top >= mine.bounds.bottom
    else:
        beyond = other.bounds.right <= mine.bounds.left or other.bounds.left >= mine.bounds.right
    if not beyond:
        return None
    faces = {Side.NORTH, Side.SOUTH} if across == "x" else {Side.EAST, Side.WEST}
    first, second = mine.port(mine_port), other.port(other_port)
    if first.side in faces and first.side is second.side:
        return None
    return _reach(mine, first, across, faces, style), _reach(other, second, across, faces, style)


def _blocked(
    nodes: dict[str, FittedNode],
    members: set[str],
    other_id: str,
    bounds: Rect,
    reach: tuple[float, float],
    across: str,
) -> bool:
    """True when some box stands between the group and the arrow's far end, across
    every place that end could be: the arrow bends around it wherever the group sits,
    so it has no say in where the group goes."""

    other = nodes[other_id].bounds
    if across == "x":
        near, far = (
            (bounds.bottom, other.top) if other.top >= bounds.bottom else (other.bottom, bounds.top)
        )
    else:
        near, far = (
            (bounds.right, other.left) if other.left >= bounds.right else (other.right, bounds.left)
        )
    for node_id, node in nodes.items():
        if node_id in members or node_id == other_id:
            continue
        box = node.bounds
        along = (box.top, box.bottom) if across == "x" else (box.left, box.right)
        side = (box.left, box.right) if across == "x" else (box.top, box.bottom)
        if (
            along[0] < far - _EPSILON
            and along[1] > near + _EPSILON
            and (side[0] <= reach[0] + _EPSILON and side[1] >= reach[1] - _EPSILON)
        ):
            return True
    return False


def _reach(
    node: FittedNode, port: ResolvedPort, across: str, faces: set[Side], style: LayoutStyle
) -> tuple[float, float]:
    """The stretch of its face a port may slide to (a point, if it does not adapt).

    A port on another face for now is taken from the middle of the facing one.
    """

    bounds = node.bounds
    start, length = (bounds.left, bounds.width) if across == "x" else (bounds.top, bounds.height)
    if port.side in faces:
        at = port.position.x if across == "x" else port.position.y
    else:
        at = start + length / 2.0
    if not _adaptive(node, port.name):
        return at, at
    margin = min(style.corner_radius.points, length / 2.0)
    reach = _CENTER_BAND_FRACTION * length
    return max(start + margin, at - reach), min(start + length - margin, at + reach)


def _adaptive(node: FittedNode, name: str) -> bool:
    return next(port for port in node.measured.spec.ports if port.name == name).adaptive


def _moved_node(node: FittedNode, dx: float, dy: float) -> FittedNode:
    return replace(
        node,
        bounds=Rect(node.bounds.x + dx, node.bounds.y + dy, node.bounds.width, node.bounds.height),
        ports=tuple(
            ResolvedPort(port.name, port.side, Point(port.position.x + dx, port.position.y + dy))
            for port in node.ports
        ),
    )


def _moved_group(group: FittedGroup, dx: float, dy: float) -> FittedGroup:
    def moved(rect: Rect) -> Rect:
        return Rect(rect.x + dx, rect.y + dy, rect.width, rect.height)

    return replace(group, bounds=moved(group.bounds), content_bounds=moved(group.content_bounds))
