"""The routing plan: the ends of every connection, their pins, and their bundles.

Every end of every connection (an ``End``) gets a side -- an authored one, a
``via``, a hint, or the side facing its counterpart -- and then a place on that
side (a ``Pin``), ordered by where its lines go and aligned with the pin it
faces across a gap. Connections that share a pin form a ``Bundle``, routed as
one tree by ``flexo.routing.router``.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from flexo.components import TRANSPARENT_KINDS, TRANSPARENT_ROLES, route_clearance
from flexo.geometry import Point, Rect, Side
from flexo.hierarchy import lowest_common_group, parent_map
from flexo.ir.fitted import FittedFigure, FittedNode
from flexo.ir.semantic import EdgeSpec, NetSpec, PortRef, PortSpec
from flexo.routing.vpsc import solve
from flexo.style import LayoutStyle

SPREAD_PIN_WEIGHT = 0.25
"""Weight of an evenly spread pin's wish against a partner pin's own centre."""

DOMINANT_GAP = 2.0
"""How many times wider one gap must be than the other to overrule a port's own side."""

_SAME_VALUE = {"junction": {"output": "output", "branch": "output"}}
"""Ports of one kind that carry the same value, and so share one pin.

A junction's ``output`` and ``branch`` are one value leaving on two names; two
pins a hair apart on an eight-point dot are the doubled line the Transformer
figure used to draw where its skip left the positional-encoding sum.
"""


@dataclass(slots=True)
class End:
    """One end of one connection."""

    member: int
    reference: PortRef
    arriving: bool
    node: FittedNode
    counterpart: Rect
    group: tuple[str, str, Side, bool] | None = None
    fixed: bool = False
    """Whether an authored side or a ``via`` hint chose this end's side."""


@dataclass(slots=True)
class Pin:
    """Where one or more ends attach: a point on a side, and how far to escape."""

    key: tuple[str, str, Side, bool]
    node: FittedNode
    side: Side
    point: Point
    arriving: bool
    clearance: float

    @property
    def escape(self) -> Point:
        return self.side.escaped(self.point, self.clearance)


@dataclass(slots=True)
class Member:
    kind: str
    spec: EdgeSpec | NetSpec
    ends: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Bundle:
    key: str
    hub: tuple[str, str, Side, bool]
    members: list[int]
    pinned: bool = False


def _flow_defaults(fitted: FittedFigure, members: list[Member], ends: list[End]) -> dict[int, Side]:
    """The side each end takes when its two gaps are comparable: the layout's flow.

    A connection whose ends share a column runs vertically, and one whose ends
    share a row runs horizontally -- whichever way its component's grammar
    points. Ends whose innermost shared group is a grid or an overlay keep the
    grammar's side.
    """

    semantic = fitted.measured.semantic
    parents = parent_map(semantic.groups)
    groups = {group.id: group for group in semantic.groups}
    result: dict[int, Side] = {}
    for member in members:
        spec = member.spec
        node_ids = (
            (spec.source.node_id, spec.target.node_id)
            if isinstance(spec, EdgeSpec)
            else tuple(reference.node_id for reference in spec.sources + spec.targets)
        )
        kind = groups[lowest_common_group(parents, node_ids)].layout.kind
        for index in member.ends:
            end = ends[index]
            here, there = end.node.bounds.center, end.counterpart.center
            if kind == "column":
                result[id(end)] = Side.SOUTH if there.y > here.y else Side.NORTH
            elif kind == "row":
                result[id(end)] = Side.EAST if there.x > here.x else Side.WEST
    return result


def _port_hints(figure) -> dict[tuple[str, str], Side]:
    """Sides that bind a port for every connection on it: ``depart``/``arrive``,
    and a net's ``via`` on target ports whose side is a default (an authored
    port side always wins). An edge's ``via`` binds only that edge's ends (see
    ``_via_side``), so it is left out here -- one hinted edge must not drag a
    neighbour arriving on the same port round to its side."""

    pins: dict[tuple[str, str], Side] = {}
    for edge in figure.edges:
        for reference, side in ((edge.source, edge.depart), (edge.target, edge.arrive)):
            if side is not None:
                pins.setdefault((reference.node_id, reference.port_name), side)
    for net in figure.nets:
        if net.via is None:
            continue
        for reference in net.targets:
            key = (reference.node_id, reference.port_name)
            if _declared_auto(figure, key):
                pins.setdefault(key, net.via)
    return pins


def _declared_auto(figure, key: tuple[str, str]) -> bool:
    """Whether the port ``key`` names has a default side a hint may replace."""

    node_id, port_name = key
    node = figure.node(node_id)
    return any(port.name == port_name and port.auto_side for port in node.ports)


def _split_side_by_side_departures(members: list[Member], ends: list[End]) -> None:
    """Give edges leaving one port for targets side by side an arrow each.

    A box facing several targets across its own width -- an encoder under its
    outputs, one per position -- sends each its own straight arrow rather than
    a tree that gathers them into one trunk only to spread them again. Targets
    stacked one behind another (a skip past the next block) keep the tree: that
    is one value branching off the main line.
    """

    groups: dict[tuple[str, str, Side, bool], list[End]] = defaultdict(list)
    for end in ends:
        member = members[end.member].spec
        if (
            not end.arriving
            and isinstance(member, EdgeSpec)
            and end.node.measured.spec.kind not in POINT_KINDS
            and end.group is not None
        ):
            groups[end.group].append(end)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        side = key[2]
        bounds = group[0].node.bounds
        if not all(_within_span(bounds, end.counterpart, side) for end in group):
            continue
        along_x = side in {Side.NORTH, Side.SOUTH}
        extents = sorted(
            (end.counterpart.left, end.counterpart.right)
            if along_x
            else (end.counterpart.top, end.counterpart.bottom)
            for end in group
        )
        if any(later[0] < earlier[1] for earlier, later in itertools.pairwise(extents)):
            continue
        for end in group:
            name = f"{key[1]}@{members[end.member].spec.id}"  # type: ignore[union-attr]
            end.group = (key[0], name, key[2], key[3])


def _within_span(bounds: Rect, other: Rect, side: Side) -> bool:
    """Whether ``other`` lies straight out from ``side`` of ``bounds``, within its span."""

    if side in {Side.NORTH, Side.SOUTH}:
        inside = bounds.left < other.center.x < bounds.right
        return inside and _faces(bounds, other, side)
    inside = bounds.top < other.center.y < bounds.bottom
    return inside and _faces(bounds, other, side)


def _authored_side(member: EdgeSpec | NetSpec, end: End) -> Side | None:
    """The side this edge's own ``depart=``/``arrive=`` names for this end."""

    if not isinstance(member, EdgeSpec):
        return None
    return member.arrive if end.arriving else member.depart


def _via_side(member: EdgeSpec | NetSpec, end: End) -> Side | None:
    """The side this end takes from its edge's ``via=``, if any.

    Ink that goes round the west arrives from the west, so the arriving end
    faces the hint. The departing end faces it too when the hint is across the
    line of travel -- a route from a box to the one above it, kept west, leaves
    west and comes back in a C -- but not when the hint lies along it, where
    leaving toward the hint would mean leaving backwards.
    """

    if not isinstance(member, EdgeSpec) or member.via is None:
        return None
    if end.arriving:
        return member.via
    here, there = end.node.bounds.center, end.counterpart.center
    vertical = abs(there.y - here.y) >= abs(there.x - here.x)
    return member.via if vertical == member.via.horizontal else None


def connections(
    fitted: FittedFigure, skip: set[str] = frozenset()
) -> tuple[list[Member], list[End]]:
    semantic = fitted.measured.semantic
    members: list[Member] = []
    ends: list[End] = []

    def add(member: int, reference: PortRef, arriving: bool, counterpart: Rect) -> None:
        members[member].ends.append(len(ends))
        ends.append(End(member, reference, arriving, fitted.node(reference.node_id), counterpart))

    for edge in semantic.edges:
        if edge.id in skip:
            continue
        members.append(Member("edge", edge))
        index = len(members) - 1
        source = fitted.node(edge.source.node_id).bounds
        target = fitted.node(edge.target.node_id).bounds
        add(index, edge.source, False, target)
        add(index, edge.target, True, source)
    for net in semantic.nets:
        members.append(Member("net", net))
        index = len(members) - 1
        fan_out = net.kind == "fan-out"
        hubs, spokes = (net.sources, net.targets) if fan_out else (net.targets, net.sources)
        hub_rect = fitted.node(hubs[0].node_id).bounds
        spread = Rect.union(fitted.node(reference.node_id).bounds for reference in spokes)
        for reference in net.sources:
            add(index, reference, False, spread if fan_out else hub_rect)
        for reference in net.targets:
            add(index, reference, True, hub_rect if fan_out else spread)
    return members, ends


def _facing_sides(node: Rect, other: Rect, default: Side) -> list[Side]:
    """Every side of ``node`` that faces ``other``, best first.

    A side faces the other box when its outward normal points at it; of those, the
    one across the wider gap is best. The grammar's own side wins when it is one
    of them and the two gaps are comparable -- within ``DOMINANT_GAP`` of each
    other -- since then either reads; a box set mostly below its counterpart
    connects through its bottom whatever the grammar says. Sides that face away
    come last, default first.
    """

    horizontal_gap = max(other.left - node.right, node.left - other.right)
    vertical_gap = max(other.top - node.bottom, node.top - other.bottom)
    east = other.center.x > node.center.x
    south = other.center.y > node.center.y
    across = Side.EAST if east else Side.WEST
    down = Side.SOUTH if south else Side.NORTH
    if horizontal_gap <= 0.0 and vertical_gap <= 0.0:
        ranked = [default]
    elif vertical_gap <= 0.0:
        ranked = [across]
    elif horizontal_gap <= 0.0:
        ranked = [down]
    else:
        ranked = [across, down] if horizontal_gap >= vertical_gap else [down, across]
        comparable = max(horizontal_gap, vertical_gap) < DOMINANT_GAP * min(
            horizontal_gap, vertical_gap
        )
        if default in ranked and comparable:
            ranked.remove(default)
            ranked.insert(0, default)
    rest = [side for side in (default, *Side) if side not in ranked]
    return ranked + list(dict.fromkeys(rest))


def _facing(node: Rect, other: Rect, default: Side) -> Side:
    """The side of ``node`` that faces ``other``, or ``default`` when it is unclear."""

    return _facing_sides(node, other, default)[0]


def plan_pins(
    fitted: FittedFigure,
    members: list[Member],
    ends: list[End],
    style: LayoutStyle,
    overrides: dict[tuple[str, Side], list] | None = None,
    chosen: dict[tuple[str, Side], list] | None = None,
    sides: dict[int, Side] | None = None,
) -> dict[tuple[str, str, Side, bool], Pin]:
    """Give every end a pin: a side, then a place on it.

    ``overrides`` fixes the order of the pins on a ``(node, side)``;
    ``chosen``, when given, receives the order every side ended up with; and
    ``sides`` fixes the side of an end, by its index in ``ends``.
    """

    hints = _port_hints(fitted.measured.semantic)
    flow = _flow_defaults(fitted, members, ends)
    edges = [member.spec for member in members if isinstance(member.spec, EdgeSpec)]
    directed = {(edge.source.node_id, edge.target.node_id) for edge in edges}
    both_ways = {pair for pair in directed if pair[::-1] in directed}
    repeats = Counter(
        (edge.source.node_id, edge.source.port_name, edge.target.node_id) for edge in edges
    )
    for index, end in enumerate(ends):
        spec = end.node.measured.spec
        port_spec = _authored_port(fitted, spec.id, end.reference.port_name)
        fitted_port = end.node.port(end.reference.port_name)
        side = fitted_port.side
        pinned = hints.get((spec.id, end.reference.port_name))
        member = members[end.member].spec
        steered = (
            isinstance(member, EdgeSpec)
            and (member.lane_hint is not None or bool(member.waypoints))
        ) or (isinstance(member, NetSpec) and member.rail_hint is not None)
        via = _via_side(member, end)
        authored = _authored_side(member, end)
        end.fixed = authored is not None or (via is not None and port_spec.auto_side)
        if authored is not None:
            side = authored
        elif via is not None and port_spec.auto_side:
            side = via
        elif pinned is not None:
            side = pinned
        elif port_spec.auto_side and not steered:
            side = _facing(end.node.bounds, end.counterpart, flow.get(id(end), port_spec.side))
        if sides and index in sides:
            side = sides[index]
            end.fixed = True
        name = _SAME_VALUE.get(spec.kind, {}).get(end.reference.port_name, end.reference.port_name)
        separate = style.conventions.arrivals == "separate"
        span = end.node.bounds.width if side in {Side.NORTH, Side.SOUTH} else end.node.bounds.height
        if (
            isinstance(member, EdgeSpec)
            and member.label
            and spec.kind != "op"
            and (end.arriving or span >= 3.0 * style.port_spacing.points)
        ):
            # A caption names the value an edge carries, so a captioned edge is
            # its own line end to end, even beside another between the same
            # ports -- unless it leaves a side too short for a pin each, where
            # the edges share a stem and each caption goes on its own branch.
            name = f"{name}@{member.id}"
        elif (
            not end.arriving
            and isinstance(member, EdgeSpec)
            and spec.kind not in POINT_KINDS
            and (member.source.node_id, member.target.node_id) in both_ways
            and repeats[(member.source.node_id, member.source.port_name, member.target.node_id)]
            == 1
        ):
            # A value sent to a box that sends one back: each departure is its
            # own arrow, so every pair of arrows can sit side by side -- a
            # server broadcasting to clients that each report back. (A circle's
            # pins stay at the middle of its sides, so its lines still share.)
            name = f"{name}@{member.id}"
        elif end.arriving and separate and isinstance(member, EdgeSpec) and spec.kind != "op":
            # Two values arriving at one port are two arrows, not a merge: only
            # a ``merge`` net joins lines before they arrive.
            name = f"{name}@{member.source.node_id}.{member.source.port_name}"
        end.group = (spec.id, name, side, end.arriving)
    _split_side_by_side_departures(members, ends)
    _common_net_sides(fitted, members, ends, hints)
    _clear_approaches(fitted, ends, hints, style)
    _separate_directions(fitted, ends, members, hints, style)
    _spill_crowded_sides(fitted, ends, hints, style)
    _spread_operator_inputs(ends)
    _one_end_per_corner(ends)
    _self_loops(fitted, members, ends)
    by_side: dict[tuple[str, Side], dict[tuple[str, str, Side, bool], list[End]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for end in ends:
        assert end.group is not None
        by_side[(end.group[0], end.group[2])][end.group].append(end)
    blockers = tuple(
        rect.inflated(style.caption_clearance.points)
        for group in fitted.groups
        if group.measured.spec.role not in TRANSPARENT_ROLES
        for rect in (title_rect(group, style),)
        if rect is not None
    ) + tuple(
        node.bounds for node in fitted.nodes if node.measured.spec.kind not in TRANSPARENT_KINDS
    )
    slots: dict[tuple[str, str, Side, bool], _Slot] = {}
    orders: list[list[tuple[str, str, Side, bool]]] = []
    for (node_id, side), groups in by_side.items():
        node = fitted.node(node_id)
        order = (overrides or {}).get((node_id, side))
        if order is not None and set(order) != set(groups):
            order = None
        placed = _place_on_side(node, side, groups, style, blockers, order)
        orders.append(list(placed))
        if chosen is not None:
            chosen[(node_id, side)] = list(placed)
        slots.update(placed)
    links = _facing_links(members, ends, slots)
    obstacles = tuple(
        node.bounds.inflated(route_clearance(node.measured.spec, style))
        for node in fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    )
    positions = _align(slots, orders, links, style.port_spacing.points, obstacles)
    pins: dict[tuple[str, str, Side, bool], Pin] = {}
    for key, slot in slots.items():
        coordinate = positions[key]
        along_x = slot.side in {Side.NORTH, Side.SOUTH}
        point = Point(coordinate, slot.edge) if along_x else Point(slot.edge, coordinate)
        arriving = key[3]
        clearance = style.arrival_clearance.points if arriving else style.route_clearance.points
        pins[key] = Pin(key, slot.node, slot.side, point, arriving, clearance)
    return pins


def _common_net_sides(
    fitted: FittedFigure,
    members: list[Member],
    ends: list[End],
    hints: dict[tuple[str, str], Side],
) -> None:
    """Give the spokes of one net one side, across the line they spread along.

    Branches set side by side read as one bus with a drop to each; the same
    branches entered each from its own nearest side read as a tangle. So the
    spokes of a net spread mostly along x attach on their north or south side --
    whichever faces the hub -- and spokes spread along y on east or west. The
    hub leaves on the side that faces them. A spoke that does not lie wholly
    beyond the hub on that side keeps the side it had.
    """

    for member_index, member in enumerate(members):
        net = member.spec
        if not isinstance(net, NetSpec) or net.rail_hint is not None:
            continue
        fan_out = net.kind == "fan-out"
        member_ends = [ends[index] for index in member.ends]
        hub_ends = [end for end in member_ends if end.arriving != fan_out]
        spokes = [end for end in member_ends if end.arriving == fan_out]
        spoke_nodes = {end.node.measured.spec.id: end.node.bounds for end in spokes}
        if len(hub_ends) != 1 or len(spoke_nodes) < 2:
            continue
        hub = hub_ends[0].node.bounds
        centres = [bounds.center for bounds in spoke_nodes.values()]
        spread_x = max(point.x for point in centres) - min(point.x for point in centres)
        spread_y = max(point.y for point in centres) - min(point.y for point in centres)
        spread = Rect.union(spoke_nodes.values())
        if spread_x >= spread_y:
            toward = Side.SOUTH if spread.center.y >= hub.center.y else Side.NORTH
        else:
            toward = Side.EAST if spread.center.x >= hub.center.x else Side.WEST
        # Beside the row rather than over it, the hub still feeds a row from
        # above: the bus runs along the row, each branch dropping in.
        level = (spread_x >= spread_y and hub.bottom > spread.top and hub.top < spread.bottom) or (
            spread_x < spread_y and hub.right > spread.left and hub.left < spread.right
        )

        def movable(end: End) -> bool:
            spec = end.node.measured.spec
            port = _authored_port(fitted, spec.id, end.reference.port_name)
            return (
                not end.fixed and port.auto_side and (spec.id, end.reference.port_name) not in hints
            )

        # In line with the hub, the nearest spoke is entered straight on, and
        # the bus to the rest branches off that stem.
        straight: End | None = None
        if level:
            ahead = [
                end
                for end in spokes
                if any(_faces(hub, end.node.bounds, side) for side in _along(spread_x >= spread_y))
            ]
            if ahead:
                straight = min(ahead, key=lambda end: _gap(hub, end.node.bounds))
        # The side the spokes would share already sends the other way -- actors
        # each feeding a queue on the side a learner's parameters would come
        # back in by: the spokes take the far side, and the rail goes round.
        side = toward.opposite
        clashing = [
            end
            for end in spokes
            if any(
                other.node is end.node
                and other.member != member_index
                and other.arriving != end.arriving
                and other.group is not None
                and other.group[2] is side
                for other in ends
            )
        ]
        if spokes and len(clashing) == len(spokes) and all(movable(end) for end in spokes):
            for end in spokes:
                end.group = (end.group[0], end.group[1], side.opposite, end.group[3])  # type: ignore[index]
                end.fixed = True
            continue
        changed = False
        for end in spokes:
            if end is straight:
                continue
            if movable(end) and (level or _faces(hub, end.node.bounds, toward)):
                end.group = (end.group[0], end.group[1], toward.opposite, end.group[3])  # type: ignore[index]
                changed = True
        hub_end = hub_ends[0]
        if changed and movable(hub_end) and _faces(hub, spread, toward):
            hub_end.group = (hub_end.group[0], hub_end.group[1], toward, hub_end.group[3])  # type: ignore[index]


def _along(horizontal: bool) -> tuple[Side, Side]:
    """The two sides that face along a row (east, west) or a column (south, north)."""

    return (Side.EAST, Side.WEST) if horizontal else (Side.SOUTH, Side.NORTH)


def _gap(a: Rect, b: Rect) -> float:
    """The larger of the horizontal and vertical gaps between two boxes."""

    return max(b.left - a.right, a.left - b.right, b.top - a.bottom, a.top - b.bottom, 0.0)


def _clear_approaches(
    fitted: FittedFigure,
    ends: list[End],
    hints: dict[tuple[str, str], Side],
    style: LayoutStyle,
) -> None:
    """Move a pin off a side whose straight approach would run into another box.

    An arrow needs ``arrival_clearance`` of straight line before its target, and
    a departure ``route_clearance`` after its source. When the gap in front of
    the chosen side is narrower than that -- two rows of a grid set close
    together -- the approach would start inside the next box over, and nothing
    downstream can route out of that. The next side that faces the counterpart
    and has a clear approach takes the pin instead.
    """

    boxes = [
        node.bounds for node in fitted.nodes if node.measured.spec.kind not in TRANSPARENT_KINDS
    ]
    for end in ends:
        assert end.group is not None
        spec = end.node.measured.spec
        port_spec = _authored_port(fitted, spec.id, end.reference.port_name)
        if end.fixed or not port_spec.auto_side or (spec.id, end.reference.port_name) in hints:
            continue
        reach = style.arrival_clearance.points if end.arriving else style.route_clearance.points
        side = end.group[2]
        if _approach_clear(end.node.bounds, side, reach, boxes):
            continue
        ranked = _facing_sides(end.node.bounds, end.counterpart, side)[1:]
        # A side facing the counterpart first; failing that, any clear side --
        # a route that comes round beats one drawn through the component
        # standing in front of the only facing side.
        clear = [
            candidate
            for candidate in ranked
            if _approach_clear(end.node.bounds, candidate, reach, boxes)
        ]
        facing = [
            candidate for candidate in clear if _faces(end.node.bounds, end.counterpart, candidate)
        ]
        choice = facing or [candidate for candidate in clear if candidate is not side.opposite]
        if choice:
            end.group = (end.group[0], end.group[1], choice[0], end.group[3])


def _approach_clear(bounds: Rect, side: Side, reach: float, boxes: list[Rect]) -> bool:
    """Whether the band ``reach`` deep in front of the middle of ``side`` is empty."""

    centre = bounds.point_on(side, 0.5)
    tip = side.escaped(centre, reach)
    band = Rect.from_points(centre, tip).inflated(0.5)
    return not any(box != bounds and box.intersects(band, strict=True) for box in boxes)


def _authored_port(fitted: FittedFigure, node_id: str, port_name: str) -> PortSpec:
    """A port as the grammar or the author declared it, before layout re-sided it."""

    node = fitted.measured.semantic.node(node_id)
    return next(port for port in node.ports if port.name == port_name)


def _separate_directions(
    fitted: FittedFigure,
    ends: list[End],
    members: list[Member],
    hints: dict[tuple[str, str], Side],
    style: LayoutStyle,
) -> None:
    """Keep what leaves a box off the side where something else arrives.

    A side that takes an arrow in and sends a different value out reads as a
    collision at the box edge. Whichever of the two is off its grammar's own
    side -- an output facing backwards, inputs pulled round to the output's
    side -- moves to the next side that still faces its counterpart; an end on
    the side the grammar gave it stays, because that is where a reader looks.
    With no other facing side, a departure joins the same value leaving by its
    own side, and an arrival comes in over the top or under the bottom.
    """

    boxes = [
        node.bounds for node in fitted.nodes if node.measured.spec.kind not in TRANSPARENT_KINDS
    ]
    by_side: dict[tuple[str, Side], list[End]] = defaultdict(list)
    for end in ends:
        assert end.group is not None
        by_side[(end.group[0], end.group[2])].append(end)
    for (_, side), members_on_side in by_side.items():
        arriving = {end.group[1] for end in members_on_side if end.arriving}  # type: ignore[index]
        leaving = {end.group[1] for end in members_on_side if not end.arriving}  # type: ignore[index]
        if not arriving or not leaving:
            continue
        for end in members_on_side:
            assert end.group is not None
            others = leaving if end.arriving else arriving
            if end.group[1] in others or not others - {end.group[1]}:
                continue
            spec = end.node.measured.spec
            port_spec = _authored_port(fitted, spec.id, end.reference.port_name)
            if end.fixed or not port_spec.auto_side or (spec.id, end.reference.port_name) in hints:
                continue
            if side is port_spec.side:
                continue  # The side the grammar gives this port: sharing it is by design.
            ranked = _facing_sides(end.node.bounds, end.counterpart, side)
            reach = style.arrival_clearance.points if end.arriving else style.route_clearance.points
            alternatives = [
                candidate
                for candidate in ranked[1:]
                if _faces(end.node.bounds, end.counterpart, candidate)
                and _approach_clear(end.node.bounds, candidate, reach, boxes)
            ]
            if alternatives:
                end.group = (end.group[0], end.group[1], alternatives[0], end.group[3])
            elif (
                not end.arriving
                and not any(
                    other.arriving and other.counterpart == end.counterpart
                    for other in members_on_side
                )
                and any(
                    other.group is not None
                    and not other.group[3]
                    and other.group[0] == end.group[0]
                    and other.group[2] is port_spec.side
                    and other.reference.port_name == end.reference.port_name
                    for other in ends
                )
            ):
                # Nothing else faces the target, but the same value already
                # leaves by its own side: branch off that line -- the feedback
                # tapped from a plant's output -- instead of leaving backwards.
                # A pair of arrows each way between two boxes stays as it is.
                end.group = (end.group[0], end.group[1], port_spec.side, end.group[3])
            elif end.arriving and not any(
                not other.arriving and other.counterpart == end.counterpart
                for other in members_on_side
            ) and any(
                not other.arriving
                and _gap(end.node.bounds, other.counterpart)
                < _gap(end.node.bounds, end.counterpart) - 1e-6
                for other in members_on_side
            ):
                # Nothing else faces where it comes from, and what leaves by
                # this side goes somewhere nearer: the arrival turns in over the
                # top or under the bottom -- an action fed back into an
                # environment that also feeds the buffer beside it.
                across = [
                    candidate
                    for candidate in ranked[1:]
                    if candidate not in {side, side.opposite}
                    and _approach_clear(end.node.bounds, candidate, reach, boxes)
                ]
                if across:
                    end.group = (end.group[0], end.group[1], across[0], end.group[3])


def _spill_crowded_sides(
    fitted: FittedFigure,
    ends: list[End],
    hints: dict[tuple[str, str], Side],
    style: LayoutStyle,
) -> None:
    """Move pins a side has no room for onto the sides at either end of it.

    A side holds two pins fewer than fit exactly a lane apart, so its lines
    have room to spread -- but at least two, where two fit. Past that, the
    outermost pins -- in the order their lines arrive, so nothing crosses --
    go round the corner nearest them, onto a side that faces where they go:
    six phases of a compiler reading one symbol table meet it on three sides,
    not squeezed onto one.
    """

    spacing = style.port_spacing.points
    by_side: dict[tuple[str, Side], dict[tuple, list[End]]] = defaultdict(lambda: defaultdict(list))
    for end in ends:
        assert end.group is not None
        by_side[(end.group[0], end.group[2])][end.group].append(end)
    for (_, side), groups in list(by_side.items()):
        node = next(iter(groups.values()))[0].node
        if node.measured.spec.kind in POINT_KINDS:
            continue
        along_x = side in {Side.NORTH, Side.SOUTH}
        span = node.bounds.width if along_x else node.bounds.height
        # Pins keep off the rounded corners (see ``_place_on_side``).
        inset = min(style.corner_radius.points + style.connector_width.points, span / 2.0)
        fit = int((span - 2.0 * inset) / spacing) + 1  # pins exactly a lane apart
        capacity = max(min(fit, 2), fit - 2)
        if len(groups) <= capacity:
            continue

        position = {
            key: sum(
                end.counterpart.center.x if along_x else end.counterpart.center.y
                for end in group
            )
            / len(group)
            for key, group in groups.items()
        }
        ordered = sorted(groups, key=position.__getitem__)
        low_side, high_side = (Side.WEST, Side.EAST) if along_x else (Side.NORTH, Side.SOUTH)
        low, high = 0, len(ordered) - 1
        excess = len(ordered) - capacity
        while excess > 0 and low <= high:
            # Alternate ends, taking whichever outer pin is further out.
            centre = node.bounds.center.x if along_x else node.bounds.center.y
            take_low = centre - position[ordered[low]] >= position[ordered[high]] - centre
            index = low if take_low else high
            key = ordered[index]
            target = low_side if take_low else high_side
            # Round the corner only onto a side every counterpart lies beyond.
            if _free_to_move(fitted, hints, groups[key]) and all(
                _faces(node.bounds, end.counterpart, target) for end in groups[key]
            ):
                for end in groups[key]:
                    end.group = (key[0], key[1], target, key[3])
                excess -= 1
            if take_low:
                low += 1
            else:
                high -= 1


def _free_to_move(
    fitted: FittedFigure, hints: dict[tuple[str, str], Side], group: list[End]
) -> bool:
    """Whether every end of ``group`` may change side: none authored, fixed, or hinted."""

    for end in group:
        key = (end.node.measured.spec.id, end.reference.port_name)
        if end.fixed or key in hints or not _authored_port(fitted, *key).auto_side:
            return False
    return True


def _spread_operator_inputs(ends: list[End]) -> None:
    """Give every value arriving at an operator circle its own side.

    Several arrows into one point of a circle read as one arrow; an addition
    reads as values arriving from different directions. Each arrival takes the
    best facing side nobody else uses -- the output's side included -- and only
    when the four sides run out do arrivals share one (and so merge). Three or
    more values arriving from the same direction -- the experts of a mixture
    summed below them -- join on that side as one arrow instead of wrapping
    round the circle to reach the other sides.
    """

    by_node: dict[str, list[End]] = defaultdict(list)
    for end in ends:
        if end.node.measured.spec.kind == "op":
            by_node[end.node.measured.spec.id].append(end)
    for node_ends in by_node.values():
        taken = {end.group[2] for end in node_ends if not end.arriving}  # type: ignore[index]
        arriving = [end for end in node_ends if end.arriving]
        from_side: dict[Side, list[End]] = defaultdict(list)
        for end in arriving:
            assert end.group is not None
            from_side[_facing_sides(end.node.bounds, end.counterpart, end.group[2])[0]].append(end)
        for side, joined in from_side.items():
            if len(joined) >= 3 and side not in taken and not any(end.fixed for end in joined):
                for end in joined:
                    assert end.group is not None
                    end.group = (end.group[0], f"{end.group[1]}#joined", side, end.group[3])
                taken.add(side)
                arriving = [end for end in arriving if end not in joined]
        for end in sorted(arriving, key=_alignment_first):
            assert end.group is not None
            ranked = _facing_sides(end.node.bounds, end.counterpart, end.group[2])
            free = [side for side in ranked if side not in taken]
            side = free[0] if free else end.group[2]
            taken.add(side)
            end.group = (end.group[0], f"{end.group[1]}#{side.value}", side, end.group[3])


CORNER_KINDS = frozenset({"circle", "decision"})
"""Kinds a line can only meet squarely at the middle of each side of their box.

A circle and a diamond touch their box at four points; a pin anywhere else on
the box edge would leave a gap between the arrowhead and the ink.
"""

POINT_KINDS = CORNER_KINDS | {"op"}
"""Kinds whose pins stay at the middle of their side: operators too."""


def _one_end_per_corner(ends: list[End]) -> None:
    """Give each end at a circle or a diamond a side of its own, while sides last.

    Arrivals choose first, so a decision keeps its question's input where the
    flow brings it and the branches leave by the other corners -- the "no"
    of a loop back out of the side, not out of the top the input came in by.
    """

    by_node: dict[str, list[End]] = defaultdict(list)
    for end in ends:
        if end.node.measured.spec.kind in CORNER_KINDS:
            by_node[end.node.measured.spec.id].append(end)
    for node_ends in by_node.values():
        taken: set[Side] = set()
        claimed: dict[tuple[str, str, Side, bool], Side] = {}
        ordered = sorted(node_ends, key=lambda end: (not end.arriving, _alignment_first(end)))
        for end in ordered:
            assert end.group is not None
            if end.fixed:
                taken.add(end.group[2])
                continue
            if end.group in claimed:
                # Ends sharing one pin (a tree) move together.
                end.group = (end.group[0], end.group[1], claimed[end.group], end.group[3])
                continue
            original = end.group
            # The side the end already has comes first: it may have been moved off
            # a facing side whose approach another component blocks.
            ranked = [end.group[2]] + [
                side
                for side in _facing_sides(end.node.bounds, end.counterpart, end.group[2])
                if side is not end.group[2]
            ]
            free = [side for side in ranked if side not in taken]
            side = free[0] if free else end.group[2]
            taken.add(side)
            claimed[original] = side
            end.group = (end.group[0], end.group[1], side, end.group[3])


LOOP_SIDES = (Side.EAST, Side.NORTH, Side.WEST, Side.SOUTH)
"""The sides a loop tries, in order of preference among equally free ones."""


def _self_loops(fitted: FittedFigure, members: list[Member], ends: list[End]) -> None:
    """Put an edge from a component back to itself on the side nothing else uses.

    A box's loop leaves and re-enters one side -- the emptiest -- as a C. A
    circle or a diamond meets lines only at the middle of each side, so its
    loop leaves one side and comes back in by the next one round, over the
    corner between the two emptiest neighbours.
    """

    for member in members:
        edge = member.spec
        if not isinstance(edge, EdgeSpec) or edge.source.node_id != edge.target.node_id:
            continue
        mine = [ends[index] for index in member.ends]
        node = mine[0].node
        used: Counter[Side] = Counter(
            end.group[2]  # type: ignore[index]
            for end in ends
            if end.node is node and end not in mine and end.group is not None
        )
        # Straight edges are not routed, but leave by the side facing their
        # other end all the same.
        routed = {member.spec.id for member in members}
        node_id = node.measured.spec.id
        for other in fitted.measured.semantic.edges:
            if other.id in routed or other.source.node_id == other.target.node_id:
                continue
            ids = (other.source.node_id, other.target.node_id)
            if node_id in ids:
                far = fitted.node(ids[1] if ids[0] == node_id else ids[0]).bounds
                used[_facing(node.bounds, far, Side.EAST)] += 1
        departure, arrival = sorted(mine, key=lambda end: end.arriving)
        if node.measured.spec.kind in POINT_KINDS:
            pairs = list(itertools.pairwise((*LOOP_SIDES, LOOP_SIDES[0])))
            leave, enter = min(pairs, key=lambda pair: used[pair[0]] + used[pair[1]])
        else:
            leave = enter = min(LOOP_SIDES, key=lambda side: used[side])
        for end, side in ((departure, leave), (arrival, enter)):
            assert end.group is not None
            end.group = (end.group[0], f"{end.group[1]}@{edge.id}", side, end.group[3])
            end.fixed = True


def _alignment_first(end: End) -> float:
    """Arrivals most squarely in line with the circle choose their side first."""

    node, other = end.node.bounds, end.counterpart
    horizontal = max(other.left - node.right, node.left - other.right)
    vertical = max(other.top - node.bottom, node.top - other.bottom)
    return 0.0 if min(horizontal, vertical) <= 0.0 else min(horizontal, vertical)


def _faces(node: Rect, other: Rect, side: Side) -> bool:
    return {
        Side.EAST: other.left >= node.right,
        Side.WEST: other.right <= node.left,
        Side.SOUTH: other.top >= node.bottom,
        Side.NORTH: other.bottom <= node.top,
    }[side]


@dataclass(slots=True)
class _Slot:
    """A pin before alignment: its side, where it would sit, and how far it may move."""

    node: FittedNode
    side: Side
    edge: float
    desired: float
    low: float
    high: float
    movable: bool
    weight: float = 1.0
    """How much where this pin wants to be counts when a facing pair is aligned.

    A pin spread evenly among several on one side has no position of its own
    to defend, so it gives way to its partner's: an arrow leaves the middle of
    a small box and lands wherever that falls on the wide box it feeds.
    """


def _place_on_side(
    node: FittedNode,
    side: Side,
    groups: dict[tuple[str, str, Side, bool], list[End]],
    style: LayoutStyle,
    blockers: tuple[Rect, ...] = (),
    order: list[tuple[str, str, Side, bool]] | None = None,
) -> dict[tuple[str, str, Side, bool], _Slot]:
    """Where each group of ends would attach along one side, in the order they leave.

    Groups are ordered by where their lines go, so no two of them cross on the
    way out. A side whose ports all sit where the layout put them, already in
    that order, keeps those places; otherwise the groups take evenly spaced
    slots. Alignment (``_align``) then moves the movable ones.
    """

    along_x = side in {Side.NORTH, Side.SOUTH}
    bounds = node.bounds
    low, high = (bounds.left, bounds.right) if along_x else (bounds.top, bounds.bottom)
    edge = {
        Side.NORTH: bounds.top,
        Side.SOUTH: bounds.bottom,
        Side.WEST: bounds.left,
        Side.EAST: bounds.right,
    }[side]

    def target(key: tuple[str, str, Side, bool]) -> float:
        values = [
            end.counterpart.center.x if along_x else end.counterpart.center.y for end in groups[key]
        ]
        return sum(values) / len(values)

    specs = {port.name: port for port in node.measured.spec.ports}

    def movable(key: tuple[str, str, Side, bool]) -> bool:
        if node.measured.spec.kind in POINT_KINDS:
            return False
        return all(
            specs[end.reference.port_name].adaptive or specs[end.reference.port_name].auto_side
            for end in groups[key]
        )

    def home(key: tuple[str, str, Side, bool]) -> float | None:
        """Where the grammar or the author put this port on this side, if on this side.

        A fixed port keeps its fitted position exactly. A movable one starts from
        its declared offset -- the side centre for a plain port -- rather than from
        wherever earlier adaptation slid it; alignment decides where it ends up.
        """

        for end in groups[key]:
            port = node.port(end.reference.port_name)
            if port.side is not side:
                continue
            if not movable(key):
                return port.position.x if along_x else port.position.y
            return low + (high - low) * specs[end.reference.port_name].offset
        return None

    def reach(key: tuple[str, str, Side, bool]) -> float:
        values = [
            abs(end.counterpart.center.y - bounds.center.y)
            if along_x
            else abs(end.counterpart.center.x - bounds.center.x)
            for end in groups[key]
        ]
        return max(values)

    # Ties -- groups whose counterparts sit level with each other -- put the
    # farthest first, so skips over a row of boxes nest instead of crossing; a
    # pair of boxes joined both ways then breaks by connection, which gives both
    # sides the same order and two parallel lines rather than two crossing ones.
    keys = order or sorted(
        groups,
        key=lambda key: (
            round(target(key), 6),
            -round(reach(key), 6),
            min(end.member for end in groups[key]),
            key[1],
        ),
    )
    current = [home(key) for key in keys]
    spread = False
    if len(keys) == 1:
        desired = [current[0] if current[0] is not None else (low + high) / 2.0]
    elif all(value is not None for value in current) and len(set(current)) == len(current):
        values = [value for value in current if value is not None]
        in_order = all(a <= b + 1e-9 for a, b in itertools.pairwise(values))
        desired = values if in_order else sorted(values)
    else:
        desired = [low + (high - low) * (index + 1) / (len(keys) + 1) for index in range(len(keys))]
        spread = True
    inset = min(style.corner_radius.points + style.connector_width.points, (high - low) / 2.0)
    open_low, open_high = _open_stretch(
        node.bounds, side, low + inset, high - inset, blockers, style.arrival_clearance.points
    )
    result = {}
    for key, value in zip(keys, desired, strict=True):
        free = movable(key)
        if free and (open_low, open_high) != (low + inset, high - inset):
            # Squeeze the pins onto the stretch of side nothing stands in front of.
            fraction = (value - low) / (high - low) if high > low else 0.5
            value = open_low + (open_high - open_low) * fraction
        result[key] = _Slot(
            node,
            side,
            edge,
            value,
            open_low if free else value,
            open_high if free else value,
            free,
            SPREAD_PIN_WEIGHT if spread else 1.0,
        )
    return result


def _open_stretch(
    bounds: Rect,
    side: Side,
    low: float,
    high: float,
    blockers: tuple[Rect, ...],
    depth: float,
) -> tuple[float, float]:
    """The longest stretch of a side with nothing in the band just in front of it.

    A stub leaves a side straight out for a clearance or so; a group title or
    another box standing in that band would be run through. Titles are the
    usual case -- a module's first component sits right under its title -- and
    pins slide along the side to the part of it that is clear.
    """

    along_x = side in {Side.NORTH, Side.SOUTH}
    band = {
        Side.NORTH: Rect(bounds.left, bounds.top - depth, bounds.width, depth),
        Side.SOUTH: Rect(bounds.left, bounds.bottom, bounds.width, depth),
        Side.WEST: Rect(bounds.left - depth, bounds.top, depth, bounds.height),
        Side.EAST: Rect(bounds.right, bounds.top, depth, bounds.height),
    }[side]
    stretches = [(low, high)]
    for rect in blockers:
        if rect == bounds or not rect.intersects(band, strict=True):
            continue
        cut_low, cut_high = (rect.left, rect.right) if along_x else (rect.top, rect.bottom)
        pieces = []
        for start, end in stretches:
            if cut_high <= start or cut_low >= end:
                pieces.append((start, end))
                continue
            if cut_low > start:
                pieces.append((start, cut_low))
            if cut_high < end:
                pieces.append((cut_high, end))
        stretches = pieces
    if not stretches:
        return low, high
    start, end = max(stretches, key=lambda piece: piece[1] - piece[0])
    if end - start < min(8.0, high - low):
        return low, high
    return start, end


def _facing_links(
    members: list[Member],
    ends: list[End],
    slots: dict[tuple[str, str, Side, bool], _Slot],
) -> list[tuple[tuple[str, str, Side, bool], tuple[str, str, Side, bool]]]:
    """Pairs of pins that face each other across a gap: a straight line is possible."""

    opposite = {
        Side.EAST: Side.WEST,
        Side.WEST: Side.EAST,
        Side.NORTH: Side.SOUTH,
        Side.SOUTH: Side.NORTH,
    }
    links = []
    for member in members:
        keys = [ends[end].group for end in member.ends]
        if member.kind == "net":
            net = member.spec
            assert isinstance(net, NetSpec)
            hub = keys[0] if net.kind == "fan-out" else keys[len(net.sources)]
            spokes = {key[0] for key in keys if key != hub}
            # A hub feeding several boxes is a trunk: it stays at the middle of
            # its side rather than lining up with whichever branch is nearest.
            pairs = [(hub, key) for key in keys if key != hub] if len(spokes) < 2 else []
        else:
            pairs = [(keys[0], keys[1])]
        for first, second in pairs:
            assert first is not None and second is not None
            one, two = slots[first], slots[second]
            if opposite[one.side] is not two.side:
                continue
            ahead = {
                Side.EAST: two.edge > one.edge,
                Side.WEST: two.edge < one.edge,
                Side.SOUTH: two.edge > one.edge,
                Side.NORTH: two.edge < one.edge,
            }[one.side]
            if ahead:
                links.append((first, second))
    return links


def _align(
    slots: dict[tuple[str, str, Side, bool], _Slot],
    orders: list[list[tuple[str, str, Side, bool]]],
    links: list[tuple[tuple[str, str, Side, bool], tuple[str, str, Side, bool]]],
    spacing: float,
    obstacles: tuple[Rect, ...] = (),
) -> dict[tuple[str, str, Side, bool], float]:
    """Slide pins so facing pairs line up exactly, keeping every side's order.

    Two pins facing each other across a gap are merged into one variable when the
    ranges they may occupy overlap -- closest pairs first, and never when the
    merge would contradict the order of pins on either side -- so their line is
    exactly straight. Every variable then wants the mean of where its pins
    wanted to be, pins on one side stay a lane apart and in order, and the
    separation solver finds the nearest arrangement. This is ``adapt_ports``
    done once, on pins, with the side orders as constraints rather than a
    repacking loop.
    """

    parent = {key: key for key in slots}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    ranges = {key: (slot.low, slot.high) for key, slot in slots.items()}
    candidates = sorted(
        links,
        key=lambda pair: abs(slots[pair[0]].desired - slots[pair[1]].desired),
    )
    for first, second in candidates:
        root_one, root_two = find(first), find(second)
        if root_one == root_two:
            continue
        low = max(ranges[root_one][0], ranges[root_two][0])
        high = min(ranges[root_one][1], ranges[root_two][1])
        if low > high + 1e-9:
            continue
        # The shared line must actually be clear: something standing in the gap
        # between the two sides takes its stretch out of the range, and the pair
        # settles on the clear stretch nearest to where they wanted to be.
        wanted = (slots[first].desired + slots[second].desired) / 2.0
        clear = _clear_stretch(slots[first], slots[second], low, high, wanted, obstacles)
        if clear is None:
            continue
        low, high = clear
        trial = dict(parent)
        trial[root_two] = root_one
        if not _orders_consistent(trial, orders):
            continue
        # A straight line is worth nothing if the pins beside it on either
        # side are then squeezed closer than a lane: the merge must fit.
        trial_ranges = {**ranges, root_one: (low, high)}
        if not _orders_fit(trial, trial_ranges, orders, spacing):
            continue
        parent[root_two] = root_one
        ranges[root_one] = (low, high)
    for axis in (True, False):
        keys = [
            key for key, slot in slots.items() if (slot.side in {Side.NORTH, Side.SOUTH}) is axis
        ]
        if not keys:
            continue
        classes = sorted({find(key) for key in keys})
        index = {root: position for position, root in enumerate(classes)}
        desired = [0.0] * len(classes)
        weights = [0.0] * len(classes)
        for key in keys:
            slot = slots[key]
            position = index[find(key)]
            weight = 1e6 if not slot.movable else slot.weight
            desired[position] += weight * slot.desired
            weights[position] += weight
        desired = [value / weight for value, weight in zip(desired, weights, strict=True)]
        constraints: list[tuple[int, int, float]] = []
        for order in orders:
            if not order or (slots[order[0]].side in {Side.NORTH, Side.SOUTH}) is not axis:
                continue
            for first, second in itertools.pairwise(order):
                one, two = index[find(first)], index[find(second)]
                if one != two:
                    constraints.append((one, two, spacing))
        for root in classes:
            low, high = ranges[root]
            position = index[root]
            for value, is_low in ((low, True), (high, False)):
                dummy = len(desired)
                desired.append(value)
                weights.append(1e7)
                constraints.append((dummy, position, 0.0) if is_low else (position, dummy, 0.0))
        constraints = _without_cycles(constraints)
        solved = solve(desired, weights, constraints)
        anchored = {find(key): slots[key].desired for key in keys if not slots[key].movable}
        for key in keys:
            root = find(key)
            low, high = ranges[root]
            # A class holding a fixed pin sits exactly on it: the solver's
            # weighted mean would leave it a rounding error off, which is a
            # diagonal hair in the drawing.
            value = anchored.get(root, solved[index[root]])
            slots[key].desired = min(max(value, low), high)
    return {key: slot.desired for key, slot in slots.items()}


def _clear_stretch(
    one: _Slot,
    two: _Slot,
    low: float,
    high: float,
    wanted: float,
    obstacles: tuple[Rect, ...],
) -> tuple[float, float] | None:
    """The part of ``low..high`` a straight line between two facing sides can use."""

    along_x = one.side in {Side.NORTH, Side.SOUTH}
    near, far = sorted((one.edge, two.edge))
    stretches = [(low, high)]
    for rect in obstacles:
        if rect.intersects(one.node.bounds) or rect.intersects(two.node.bounds):
            continue
        across_low, across_high = (rect.top, rect.bottom) if along_x else (rect.left, rect.right)
        if across_high <= near or across_low >= far:
            continue
        cut_low, cut_high = (rect.left, rect.right) if along_x else (rect.top, rect.bottom)
        pieces = []
        for start, end in stretches:
            if cut_high <= start or cut_low >= end:
                pieces.append((start, end))
                continue
            if cut_low > start:
                pieces.append((start, cut_low))
            if cut_high < end:
                pieces.append((cut_high, end))
        stretches = pieces
    if not stretches:
        return None

    def distance(stretch: tuple[float, float]) -> float:
        start, end = stretch
        return 0.0 if start <= wanted <= end else min(abs(wanted - start), abs(wanted - end))

    return min(stretches, key=distance)


def _orders_fit(
    parent: dict,
    ranges: dict,
    orders: list[list],
    spacing: float,
) -> bool:
    """Whether every side can still hold its pins in order, a lane apart, in their ranges."""

    def find(key):
        while parent[key] != key:
            key = parent[key]
        return key

    for order in orders:
        position = float("-inf")
        previous = None
        for key in order:
            root = find(key)
            low, high = ranges[root]
            if root == previous:
                continue
            position = max(low, position + spacing)
            if position > high + 1e-6:
                return False
            previous = root
    return True


def _orders_consistent(parent: dict, orders: list[list]) -> bool:
    """False when merged pins would have to sit both before and after each other."""

    def find(key):
        while parent[key] != key:
            key = parent[key]
        return key

    successors: dict = defaultdict(set)
    for order in orders:
        roots = [find(key) for key in order]
        if len(set(roots)) != len(roots):
            return False
        for first, second in itertools.pairwise(roots):
            successors[first].add(second)
    state: dict = {}

    def cyclic(node) -> bool:
        state[node] = 1
        for following in successors.get(node, ()):
            mark = state.get(following, 0)
            if mark == 1 or (mark == 0 and cyclic(following)):
                return True
        state[node] = 2
        return False

    return not any(state.get(node, 0) == 0 and cyclic(node) for node in list(successors))


def _without_cycles(constraints: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    successors: dict[int, set[int]] = defaultdict(set)
    kept = []
    for left, right, gap in constraints:
        stack, seen, cycle = [right], {right}, False
        while stack:
            item = stack.pop()
            if item == left:
                cycle = True
                break
            for following in successors[item]:
                if following not in seen:
                    seen.add(following)
                    stack.append(following)
        if cycle:
            continue
        successors[left].add(right)
        kept.append((left, right, gap))
    return kept


def plan_bundles(members: list[Member], ends: list[End]) -> list[Bundle]:
    """Group connections that share a pin into trees rooted at that pin."""

    claimed: dict[int, int] = {}
    bundles: list[Bundle] = []
    shared: dict[tuple[str, str, Side, bool], list[int]] = defaultdict(list)
    for index, member in enumerate(members):
        if member.kind == "edge":
            edge = member.spec
            assert isinstance(edge, EdgeSpec)
            if edge.lane_hint is not None or edge.waypoints:
                claimed[index] = len(bundles)
                bundles.append(
                    Bundle(edge.id, ends[member.ends[0]].group, [index], pinned=True)  # type: ignore[arg-type]
                )
                continue
            for end in member.ends:
                shared[ends[end].group].append(index)  # type: ignore[index]
        else:
            net = member.spec
            assert isinstance(net, NetSpec)
            hub_end = member.ends[0] if net.kind == "fan-out" else member.ends[len(net.sources)]
            shared[ends[hub_end].group].append(index)  # type: ignore[index]
    for group in sorted(shared, key=lambda key: (-len(shared[key]), key[:2], key[3])):
        users = [member for member in shared[group] if member not in claimed]
        nets = [member for member in users if members[member].kind == "net"]
        if len(users) < 2 and not nets:
            continue
        key = members[nets[0]].spec.id if nets else "bundle." + ".".join(group[:2])
        for member in users:
            claimed[member] = len(bundles)
        bundles.append(Bundle(key, group, users))
    for index, member in enumerate(members):
        if index in claimed:
            continue
        claimed[index] = len(bundles)
        bundles.append(Bundle(member.spec.id, ends[member.ends[0]].group, [index]))  # type: ignore[arg-type]
    return bundles


def title_rect(group, style: LayoutStyle) -> Rect | None:
    """Where a container's title is written: words routes must not run through."""

    label = group.measured.label
    if not label.lines:
        return None
    spec = group.measured.spec
    padding = spec.layout.authored_padding(style.group_padding)
    top = group.bounds.y + padding.top
    if spec.title_side == "right":
        left = group.bounds.right - padding.right - label.width
    else:
        left = group.bounds.x + padding.left
    return Rect(left, top, label.width, label.height)
