"""Route every connector of a fitted figure: pins, search, trees, separation.

The pipeline follows the routers that draw connectors well (libavoid, ELK):

1. **Pins.** Every end of every connection gets its own attachment point. A
   port the grammar placed on a default side (``auto_side``) is attached on the
   side that faces the thing at the other end *of that connection*, so a value
   that goes both down and sideways leaves from two sides instead of wrapping
   around the box. Ends of one port that leave the same side share one pin, and
   the pins on a side are ordered by where their lines go, so lines leaving one
   box never cross each other on the way out.
2. **Bundles.** Connections that share a pin are one value going to several
   places (or several values arriving at one place), so they are routed as one
   tree rooted at the shared pin. A net is a bundle too.
3. **Search.** Each bundle grows its tree one branch at a time, cheapest first,
   over a grid of the figure's interesting lines (``search``). Every point
   already on the tree is a free place to branch from, and bends are priced
   high, so the tree comes out the way a person draws one: a long straight trunk
   with branches off it. Components, their clearance rings and containers a
   route does not belong to are priced, never forbidden, so a route always
   exists.
4. **Separate** (``separate``): runs of different bundles that ended up sharing
   a corridor are ordered so they cross least and spread one lane apart; the
   crossbar of a Z and the trunk of a tree are centred in the room they have.

The result is the ``RoutedFigure`` the rest of the compiler reads. Where three or
more pieces of a tree meet -- a branch point, never a bend -- the figure's
conventions (``flexo.conventions``) decide the mark: a plain T, an arrowhead into
the line joined, or a dot.
"""

from __future__ import annotations

import copy
import itertools
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace

from flexo.components import CAPTION_KINDS, TRANSPARENT_KINDS, TRANSPARENT_ROLES, route_clearance
from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Point, Rect, Side, segments
from flexo.hierarchy import ancestors, parent_map, routing_boundary
from flexo.ir.fitted import FittedFigure, FittedNode
from flexo.ir.routed import RoutedEdge, RoutedFigure, RoutedNet, RoutedStem
from flexo.ir.semantic import EdgeSpec, NetSpec, PortRef, PortSpec
from flexo.routing.hints import SideBias, forced_points, via_diagnostics
from flexo.routing.ink import (
    edge_label_position,
    edge_shaft,
    rail_label_position,
    shorten_end,
    shorten_start,
)
from flexo.routing.labels import label_box, place_edge_labels
from flexo.routing.search import EAST, NORTH, SOUTH, WEST, Grid, Zone, simplify
from flexo.routing.separate import Terminal, Wire, _perpendicular_cross, separate
from flexo.routing.vpsc import solve
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer
from flexo.themes import figure_style

NODE_COST = 60.0
"""Price per point of running through a component: only when there is no way round."""

CAPTION_COST = 25.0
"""Price per point of running through a caption or a group title."""

RING_COST = 6.0
"""Price per point of running inside a component's clearance ring."""

FOREIGN_COST = 4.0
"""Price per point inside a container that owns neither end of the route."""

LEAVE_COST = 1.2
"""Price per point inside a container the route belongs to but has to leave."""

CROSSING_COST = 1.5
"""Price of crossing another connector, in bends: a short detour beats a crossing."""

OVERLAP_COST = 0.03
"""Price per point of running exactly on top of another connector."""

REROUTE_PASSES = 2

DOMINANT_GAP = 2.0
"""How many times wider one gap must be than the other to overrule a port's own side."""

SHORT_APPROACH_COST = 1.0
"""Per point of arrival stub given up to come straight in instead of jogging."""
"""How many times every bundle is routed again with the others in view."""

OFF_SIDE_COST = 1.5
"""Price per point spent beyond the endpoints on the side a ``via`` or ``rail`` refused.

High enough that the near corridor wins wherever it exists, low enough that the
far one is still available when it is the only one.
"""

BORDER_COST = 1.5
"""Price per point of running along a container's edge instead of clear of it."""

OUTSIDE_COST = 12.0
"""Price per point outside the container that owns the route."""

_HEADING = {Side.EAST: EAST, Side.WEST: WEST, Side.SOUTH: SOUTH, Side.NORTH: NORTH}
_INTO = {Side.EAST: WEST, Side.WEST: EAST, Side.SOUTH: NORTH, Side.NORTH: SOUTH}
_SAME_VALUE = {"junction": {"output": "output", "branch": "output"}}
"""Ports of one kind that carry the same value, and so share one pin.

A junction's ``output`` and ``branch`` are one value leaving on two names; two
pins a hair apart on an eight-point dot are the doubled line the Transformer
figure used to draw where its skip left the positional-encoding sum.
"""


# -- the plan: ends, pins, bundles ------------------------------------------------------


@dataclass(slots=True)
class _End:
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
class _Pin:
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
class _Member:
    kind: str
    spec: EdgeSpec | NetSpec
    ends: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _Bundle:
    key: str
    hub: tuple[str, str, Side, bool]
    members: list[int]
    pinned: bool = False


def route_figure(
    fitted: FittedFigure,
    *,
    style: LayoutStyle | None = None,
    measurer: TextMeasurer | None = None,
) -> RoutedFigure:
    layout_style = style or figure_style(fitted.measured.semantic)
    text_measurer = measurer or TextMeasurer(layout_style.typography)
    semantic = fitted.measured.semantic
    straight = {
        edge.id for edge in semantic.edges if _is_straight(edge, layout_style)
    }
    members, ends = _connections(fitted, straight)
    scene = _Scene(fitted, layout_style, text_measurer)

    def attempt(overrides: dict[tuple[str, Side], list]) -> tuple:
        orders: dict[tuple[str, Side], list] = {}
        pins = _pins(fitted, members, ends, layout_style, overrides, orders)
        bundles = _bundles(members, ends)
        wires = [scene.grow(bundle, members, ends, pins) for bundle in bundles]
        # Rip up and reroute: every bundle again, now able to see the others.
        for _ in range(REROUTE_PASSES):
            for index, bundle in enumerate(bundles):
                if bundle.pinned:
                    continue
                traffic = _Traffic(
                    [wire for position, wire in enumerate(wires) if position != index],
                    crossing=CROSSING_COST * layout_style.bend_penalty,
                )
                wires[index] = scene.grow(bundle, members, ends, pins, traffic)
        return pins, bundles, wires, orders

    def separated(wires: list[Wire]) -> list[Wire]:
        wires = copy.deepcopy(wires)
        separate(
            wires,
            scene.separation_obstacles(),
            scene.walls(),
            spacing=layout_style.port_spacing.points,
        )
        return wires

    pins, bundles, wires, orders = attempt({})
    pins, bundles, wires = _reorder_crossing_pins(
        attempt, separated, pins, bundles, wires, orders, members, ends
    )
    wires = separated(wires)
    routed_edges: dict[str, RoutedEdge] = {}
    routed_nets: dict[str, RoutedNet] = {}
    for bundle, wire in zip(bundles, wires, strict=True):
        graph = _Graph(wire)
        shared = len(bundle.members) > 1
        dots_given = False
        hub = pins[bundle.hub]
        joins = (
            graph.joins(hub.point)
            if _arrows_at_joins(bundle, members, pins, layout_style)
            else set()
        )
        marked = _dots_at_joins(bundle, members, pins, layout_style)
        cut = _edge_cuts(bundle, members, ends, pins, graph, joins)
        for member_index in bundle.members:
            member = members[member_index]
            member_pins = [pins[ends[end].group] for end in member.ends]  # type: ignore[index]
            if member.kind == "edge":
                assert isinstance(member.spec, EdgeSpec)
                dots = graph.dots() if shared and marked and not dots_given else ()
                dots_given = dots_given or bool(dots)
                routed_edges[member.spec.id] = _routed_edge(
                    member.spec,
                    graph.path(member_pins[0].point, member_pins[1].point),
                    layout_style,
                    text_measurer,
                    dots=dots,
                    joints=graph.dots() if shared else (),
                    bundle=bundle.key if shared else None,
                    joined_at=cut.get(member_index),
                )
            else:
                assert isinstance(member.spec, NetSpec)
                routed_nets[member.spec.id] = _routed_net(
                    member.spec,
                    graph,
                    wire,
                    [(ends[end], pins[ends[end].group]) for end in member.ends],  # type: ignore[index]
                    layout_style,
                    text_measurer,
                    bundle=bundle.key if shared else None,
                    all_dots=not dots_given,
                    draw_dots=marked,
                    joins=joins,
                )
                dots_given = True
    pairs: dict[frozenset[str], list[EdgeSpec]] = defaultdict(list)
    for edge in semantic.edges:
        if edge.id in straight:
            pairs[frozenset((edge.source.node_id, edge.target.node_id))].append(edge)
    for together in pairs.values():
        # Straight edges between one pair of components run side by side,
        # a lane apart, rather than on top of each other.
        for index, edge in enumerate(together):
            offset = (index - (len(together) - 1) / 2.0) * layout_style.port_spacing.points
            routed_edges[edge.id] = _straight_edge(
                edge, fitted, layout_style, text_measurer, offset=offset
            )
    edges = [routed_edges[edge.id] for edge in semantic.edges]
    nets = [routed_nets[net.id] for net in semantic.nets]
    edges = place_edge_labels(
        edges,
        solids=(
            *(node.bounds for node in fitted.nodes),
            *(
                rect
                for group in fitted.groups
                if group.measured.spec.role not in TRANSPARENT_ROLES
                for rect in (_title_rect(group, layout_style),)
                if rect is not None
            ),
        ),
        fixed_labels=(
            label_box(net.label_position, net.label_metrics)
            for net in nets
            if net.label_position is not None and net.label_metrics is not None
        ),
        lines=(
            *((edge.spec.id, edge.centerline) for edge in edges),
            *((net.spec.id, piece) for net in nets for piece in net.pieces or ()),
            # A caption stays on one side of every container outline.
            *(
                (group.measured.spec.id, _outline(group.bounds))
                for group in fitted.groups
                if group.measured.spec.role not in TRANSPARENT_ROLES
            ),
        ),
        canvas=scene.canvas,
        style=layout_style,
    )
    return RoutedFigure(fitted, tuple(edges), tuple(nets))


PIN_ORDER_TRIALS = 12
"""Most pin orders tried, per figure, to take a crossing out."""


def _reorder_crossing_pins(attempt, separated, pins, bundles, wires, orders, members, ends):
    """Swap neighbouring pins on the sides crossing routes attach to, while it helps.

    Pins are ordered along a side by where their counterparts sit, which cannot
    tell which way round an obstacle a route will go. Two routes that cross
    near a box usually uncross when their pins there trade places, so each side
    a crossing route attaches to has its neighbouring pins swapped in turn, the
    figure rerouted, and the order kept when the figure crosses less.
    """

    best = _crossing_pairs(separated(wires))
    trials = 0
    tried: set[tuple] = set()
    overrides: dict[tuple[str, Side], list] = {}
    while best and trials < PIN_ORDER_TRIALS:
        involved = {index for pair in best for index in pair}
        keys = {
            ends[end].group
            for index in involved
            for member in bundles[index].members
            for end in members[member].ends
        }
        improved = False
        for side_key, order in sorted(orders.items(), key=lambda item: str(item[0])):
            if len(order) < 2 or not keys.intersection(order):
                continue
            for position in range(len(order) - 1):
                if not {order[position], order[position + 1]} & keys:
                    continue
                swapped = list(order)
                swapped[position], swapped[position + 1] = swapped[position + 1], swapped[position]
                signature = (side_key, tuple(swapped))
                if signature in tried or trials >= PIN_ORDER_TRIALS:
                    continue
                tried.add(signature)
                trials += 1
                trial = attempt({**overrides, side_key: swapped})
                crossings = _crossing_pairs(separated(trial[2]))
                if len(crossings) < len(best):
                    overrides[side_key] = swapped
                    pins, bundles, wires, orders = trial
                    best = crossings
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return pins, bundles, wires


def _crossing_pairs(wires: list[Wire]) -> list[tuple[int, int]]:
    """Pairs of wires whose lines cross at a right angle somewhere."""

    runs = [_straight_runs(wire) for wire in wires]
    pairs = []
    for first, second in itertools.combinations(range(len(wires)), 2):
        if any(
            _perpendicular_cross(a, b, c, d)
            for a, b in runs[first]
            for c, d in runs[second]
        ):
            pairs.append((first, second))
    return pairs


def _straight_runs(wire: Wire) -> list[tuple[Point, Point]]:
    """A wire's ink as maximal straight runs.

    A wire is stored in pieces -- the escape stub, then the route -- and a run
    that carries on straight through the joint between two pieces is one run.
    Split, a line crossing it exactly at the joint would touch two endpoints
    and cross neither.
    """

    pieces = [
        (start, end)
        for path in wire.paths
        for start, end in itertools.pairwise(path)
        if start.distance_to(end) > 1e-9
    ]
    merged = True
    while merged:
        merged = False
        for index, (a, b) in enumerate(pieces):
            for other, (c, d) in enumerate(pieces):
                if other == index:
                    continue
                joined = _joined(a, b, c, d)
                if joined is not None:
                    pieces[index] = joined
                    del pieces[other]
                    merged = True
                    break
            if merged:
                break
    return pieces


def _joined(a: Point, b: Point, c: Point, d: Point) -> tuple[Point, Point] | None:
    """``ab`` and ``cd`` as one run, when they are collinear and meet end to end."""

    horizontal = abs(a.y - b.y) < 1e-9 and abs(c.y - d.y) < 1e-9 and abs(a.y - c.y) < 1e-9
    vertical = abs(a.x - b.x) < 1e-9 and abs(c.x - d.x) < 1e-9 and abs(a.x - c.x) < 1e-9
    if not (horizontal or vertical):
        return None
    if not any(_key(p) == _key(q) for p in (a, b) for q in (c, d)):
        return None
    points = sorted((a, b, c, d), key=lambda point: point.x if horizontal else point.y)
    return points[0], points[-1]


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


def _split_side_by_side_departures(members: list[_Member], ends: list[_End]) -> None:
    """Give edges leaving one port for targets side by side an arrow each.

    A box facing several targets across its own width -- an encoder under its
    outputs, one per position -- sends each its own straight arrow rather than
    a tree that gathers them into one trunk only to spread them again. Targets
    stacked one behind another (a skip past the next block) keep the tree: that
    is one value branching off the main line.
    """

    groups: dict[tuple[str, str, Side, bool], list[_End]] = defaultdict(list)
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


def _authored_side(member: EdgeSpec | NetSpec, end: _End) -> Side | None:
    """The side this edge's own ``depart=``/``arrive=`` names for this end."""

    if not isinstance(member, EdgeSpec):
        return None
    return member.arrive if end.arriving else member.depart


def _via_side(member: EdgeSpec | NetSpec, end: _End) -> Side | None:
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


def _outline(bounds: Rect) -> tuple[Point, ...]:
    corners = (
        Point(bounds.left, bounds.top),
        Point(bounds.right, bounds.top),
        Point(bounds.right, bounds.bottom),
        Point(bounds.left, bounds.bottom),
    )
    return (*corners, corners[0])


def _is_straight(edge: EdgeSpec, style: LayoutStyle) -> bool:
    if edge.shape == "auto":
        return style.conventions.lines == "straight"
    return edge.shape == "straight"


ROUND_KINDS = frozenset({"op", "circle"})
"""Kinds whose outline is the circle inscribed in their box."""


def _straight_edge(
    edge: EdgeSpec,
    fitted: FittedFigure,
    style: LayoutStyle,
    measurer: TextMeasurer,
    *,
    offset: float = 0.0,
) -> RoutedEdge:
    """One segment from outline to outline, on the line between the two centres.

    ``offset`` moves the line sideways (to the right of its direction of travel
    for a positive value), so two edges between one pair can run side by side.
    """

    source = fitted.node(edge.source.node_id)
    target = fitted.node(edge.target.node_id)
    first, second = source.bounds.center, target.bounds.center
    dx, dy = second.x - first.x, second.y - first.y
    length = max((dx * dx + dy * dy) ** 0.5, 1e-9)
    # Offsets are measured in one fixed frame per pair, so a pair of opposite
    # edges lands on opposite sides instead of both sliding the same way.
    if (first.x, first.y) > (second.x, second.y):
        offset = -offset
    shift = Point(-dy / length * offset, dx / length * offset)
    start = _outline_along(source, first.translated(shift.x, shift.y), (dx, dy))
    end = _outline_along(target, second.translated(shift.x, shift.y), (-dx, -dy))
    return replace(_routed_edge(edge, (start, end), style, measurer), straight=True)


def _outline_along(node: FittedNode, origin: Point, direction: tuple[float, float]) -> Point:
    """Where the ray from ``origin`` (inside ``node``) along ``direction`` leaves its outline."""

    bounds = node.bounds
    dx, dy = direction
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-9:
        return origin
    dx, dy = dx / length, dy / length
    if node.measured.spec.kind == "decision":
        # |x - cx| / a + |y - cy| / b = 1 along the ray from the origin.
        centre = bounds.center
        a, b = bounds.width / 2.0, bounds.height / 2.0
        ox, oy = origin.x - centre.x, origin.y - centre.y
        best = float("inf")
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                rate = sx * dx / a + sy * dy / b
                if rate > 1e-12:
                    t = (1.0 - sx * ox / a - sy * oy / b) / rate
                    if t >= 0.0:
                        best = min(best, t)
        if best < float("inf"):
            return Point(origin.x + dx * best, origin.y + dy * best)
    if node.measured.spec.kind in ROUND_KINDS:
        centre = bounds.center
        radius = min(bounds.width, bounds.height) / 2.0
        ox, oy = origin.x - centre.x, origin.y - centre.y
        # |o + t d| = r, the positive root.
        along = ox * dx + oy * dy
        t = -along + max(0.0, along * along - (ox * ox + oy * oy - radius * radius)) ** 0.5
        return Point(origin.x + dx * t, origin.y + dy * t)
    limits = []
    if abs(dx) > 1e-9:
        limits.append(((bounds.right if dx > 0 else bounds.left) - origin.x) / dx)
    if abs(dy) > 1e-9:
        limits.append(((bounds.bottom if dy > 0 else bounds.top) - origin.y) / dy)
    t = min(limits)
    return Point(origin.x + dx * t, origin.y + dy * t)


def _connections(
    fitted: FittedFigure, skip: set[str] = frozenset()
) -> tuple[list[_Member], list[_End]]:
    semantic = fitted.measured.semantic
    members: list[_Member] = []
    ends: list[_End] = []

    def add(member: int, reference: PortRef, arriving: bool, counterpart: Rect) -> None:
        members[member].ends.append(len(ends))
        ends.append(
            _End(member, reference, arriving, fitted.node(reference.node_id), counterpart)
        )

    for edge in semantic.edges:
        if edge.id in skip:
            continue
        members.append(_Member("edge", edge))
        index = len(members) - 1
        source = fitted.node(edge.source.node_id).bounds
        target = fitted.node(edge.target.node_id).bounds
        add(index, edge.source, False, target)
        add(index, edge.target, True, source)
    for net in semantic.nets:
        members.append(_Member("net", net))
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


def _pins(
    fitted: FittedFigure,
    members: list[_Member],
    ends: list[_End],
    style: LayoutStyle,
    overrides: dict[tuple[str, Side], list] | None = None,
    chosen: dict[tuple[str, Side], list] | None = None,
) -> dict[tuple[str, str, Side, bool], _Pin]:
    """Give every end a pin: a side, then a place on it.

    ``overrides`` fixes the order of the pins on a ``(node, side)``, and
    ``chosen``, when given, receives the order every side ended up with.
    """

    hints = _port_hints(fitted.measured.semantic)
    for end in ends:
        spec = end.node.measured.spec
        port_spec = _authored_port(fitted, spec.id, end.reference.port_name)
        fitted_port = end.node.port(end.reference.port_name)
        side = fitted_port.side
        pinned = hints.get((spec.id, end.reference.port_name))
        member = members[end.member].spec
        steered = (isinstance(member, EdgeSpec) and (
            member.lane_hint is not None or bool(member.waypoints)
        )) or (isinstance(member, NetSpec) and member.rail_hint is not None)
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
            side = _facing(end.node.bounds, end.counterpart, port_spec.side)
        name = _SAME_VALUE.get(spec.kind, {}).get(end.reference.port_name, end.reference.port_name)
        separate = style.conventions.arrivals == "separate"
        if isinstance(member, EdgeSpec) and member.label and spec.kind != "op":
            # A caption names the value an edge carries, so a captioned edge is
            # its own line end to end, even beside another between the same ports.
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
    _spread_operator_inputs(ends)
    _one_end_per_corner(ends)
    by_side: dict[tuple[str, Side], dict[tuple[str, str, Side, bool], list[_End]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for end in ends:
        assert end.group is not None
        by_side[(end.group[0], end.group[2])][end.group].append(end)
    blockers = tuple(
        rect.inflated(style.caption_clearance.points)
        for group in fitted.groups
        if group.measured.spec.role not in TRANSPARENT_ROLES
        for rect in (_title_rect(group, style),)
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
    pins: dict[tuple[str, str, Side, bool], _Pin] = {}
    for key, slot in slots.items():
        coordinate = positions[key]
        along_x = slot.side in {Side.NORTH, Side.SOUTH}
        point = Point(coordinate, slot.edge) if along_x else Point(slot.edge, coordinate)
        arriving = key[3]
        clearance = style.arrival_clearance.points if arriving else style.route_clearance.points
        pins[key] = _Pin(key, slot.node, slot.side, point, arriving, clearance)
    return pins


def _common_net_sides(
    fitted: FittedFigure,
    members: list[_Member],
    ends: list[_End],
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

    for member in members:
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
        level = (
            spread_x >= spread_y and hub.bottom > spread.top and hub.top < spread.bottom
        ) or (spread_x < spread_y and hub.right > spread.left and hub.left < spread.right)

        def movable(end: _End) -> bool:
            spec = end.node.measured.spec
            port = _authored_port(fitted, spec.id, end.reference.port_name)
            return (
                not end.fixed
                and port.auto_side
                and (spec.id, end.reference.port_name) not in hints
            )

        changed = False
        for end in spokes:
            if movable(end) and (level or _faces(hub, end.node.bounds, toward)):
                end.group = (end.group[0], end.group[1], toward.opposite, end.group[3])  # type: ignore[index]
                changed = True
        hub_end = hub_ends[0]
        if changed and movable(hub_end) and _faces(hub, spread, toward):
            hub_end.group = (hub_end.group[0], hub_end.group[1], toward, hub_end.group[3])  # type: ignore[index]


def _clear_approaches(
    fitted: FittedFigure,
    ends: list[_End],
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
        node.bounds
        for node in fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
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
        for candidate in _facing_sides(end.node.bounds, end.counterpart, side)[1:]:
            if _faces(end.node.bounds, end.counterpart, candidate) and _approach_clear(
                end.node.bounds, candidate, reach, boxes
            ):
                end.group = (end.group[0], end.group[1], candidate, end.group[3])
                break


def _approach_clear(bounds: Rect, side: Side, reach: float, boxes: list[Rect]) -> bool:
    """Whether the band ``reach`` deep in front of the middle of ``side`` is empty."""

    centre = bounds.point_on(side, 0.5)
    tip = side.escaped(centre, reach)
    band = Rect.from_points(centre, tip).inflated(0.5)
    return not any(
        box != bounds and box.intersects(band, strict=True) for box in boxes
    )


def _authored_port(fitted: FittedFigure, node_id: str, port_name: str) -> PortSpec:
    """A port as the grammar or the author declared it, before layout re-sided it."""

    node = fitted.measured.semantic.node(node_id)
    return next(port for port in node.ports if port.name == port_name)


def _separate_directions(
    fitted: FittedFigure,
    ends: list[_End],
    members: list[_Member],
    hints: dict[tuple[str, str], Side],
    style: LayoutStyle,
) -> None:
    """Keep what leaves a box off the side where something else arrives.

    A side that takes an arrow in and sends a different value out reads as a
    collision at the box edge. Whichever of the two is off its grammar's own
    side -- an output facing backwards, inputs pulled round to the output's
    side -- moves to the next side that still faces its counterpart; an end on
    the side the grammar gave it stays, because that is where a reader looks.
    """

    boxes = [
        node.bounds
        for node in fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    ]
    by_side: dict[tuple[str, Side], list[_End]] = defaultdict(list)
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
            reach = (
                style.arrival_clearance.points if end.arriving else style.route_clearance.points
            )
            alternatives = [
                candidate
                for candidate in ranked[1:]
                if _faces(end.node.bounds, end.counterpart, candidate)
                and _approach_clear(end.node.bounds, candidate, reach, boxes)
            ]
            if alternatives:
                end.group = (end.group[0], end.group[1], alternatives[0], end.group[3])


def _spread_operator_inputs(ends: list[_End]) -> None:
    """Give every value arriving at an operator circle its own side.

    Several arrows into one point of a circle read as one arrow; an addition
    reads as values arriving from different directions. Each arrival takes the
    best facing side nobody else uses -- the output's side included -- and only
    when the four sides run out do arrivals share one (and so merge).
    """

    by_node: dict[str, list[_End]] = defaultdict(list)
    for end in ends:
        if end.node.measured.spec.kind == "op":
            by_node[end.node.measured.spec.id].append(end)
    for node_ends in by_node.values():
        taken = {end.group[2] for end in node_ends if not end.arriving}  # type: ignore[index]
        arriving = [end for end in node_ends if end.arriving]
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


def _one_end_per_corner(ends: list[_End]) -> None:
    """Give each end at a circle or a diamond a side of its own, while sides last.

    Arrivals choose first, so a decision keeps its question's input where the
    flow brings it and the branches leave by the other corners -- the "no"
    of a loop back out of the side, not out of the top the input came in by.
    """

    by_node: dict[str, list[_End]] = defaultdict(list)
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
            ranked = _facing_sides(end.node.bounds, end.counterpart, end.group[2])
            free = [side for side in ranked if side not in taken]
            side = free[0] if free else end.group[2]
            taken.add(side)
            claimed[original] = side
            end.group = (end.group[0], end.group[1], side, end.group[3])


def _alignment_first(end: _End) -> float:
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


def _place_on_side(
    node: FittedNode,
    side: Side,
    groups: dict[tuple[str, str, Side, bool], list[_End]],
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
            end.counterpart.center.x if along_x else end.counterpart.center.y
            for end in groups[key]
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
    if len(keys) == 1:
        desired = [current[0] if current[0] is not None else (low + high) / 2.0]
    elif all(value is not None for value in current) and len(set(current)) == len(current):
        values = [value for value in current if value is not None]
        in_order = all(a <= b + 1e-9 for a, b in itertools.pairwise(values))
        desired = values if in_order else sorted(values)
    else:
        desired = [low + (high - low) * (index + 1) / (len(keys) + 1) for index in range(len(keys))]
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
    members: list[_Member],
    ends: list[_End],
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
            weight = 1e6 if not slot.movable else 1.0
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
        anchored = {
            find(key): slots[key].desired for key in keys if not slots[key].movable
        }
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


def _bundles(members: list[_Member], ends: list[_End]) -> list[_Bundle]:
    """Group connections that share a pin into trees rooted at that pin."""

    claimed: dict[int, int] = {}
    bundles: list[_Bundle] = []
    shared: dict[tuple[str, str, Side, bool], list[int]] = defaultdict(list)
    for index, member in enumerate(members):
        if member.kind == "edge":
            edge = member.spec
            assert isinstance(edge, EdgeSpec)
            if edge.lane_hint is not None or edge.waypoints:
                claimed[index] = len(bundles)
                bundles.append(
                    _Bundle(edge.id, ends[member.ends[0]].group, [index], pinned=True)  # type: ignore[arg-type]
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
        bundles.append(_Bundle(key, group, users))
    for index, member in enumerate(members):
        if index in claimed:
            continue
        claimed[index] = len(bundles)
        bundles.append(_Bundle(member.spec.id, ends[member.ends[0]].group, [index]))  # type: ignore[arg-type]
    return bundles


# -- the scene: zones, grids, growing trees -----------------------------------------------


class _Scene:
    """Everything routing needs to know about the fitted figure, computed once."""

    def __init__(self, fitted: FittedFigure, style: LayoutStyle, measurer: TextMeasurer) -> None:
        self.fitted = fitted
        self.style = style
        self.parents = parent_map(fitted.measured.semantic.groups)
        self.solid = tuple(
            node for node in fitted.nodes if node.measured.spec.kind not in TRANSPARENT_KINDS
        )
        self.containers = tuple(
            group for group in fitted.groups if group.measured.spec.role not in TRANSPARENT_ROLES
        )
        self.titles = tuple(_title_rect(group, style) for group in self.containers)
        self.titles = tuple(rect for rect in self.titles if rect is not None)
        self.canvas = Rect(0.0, 0.0, fitted.canvas_size.width, fitted.canvas_size.height)
        clearance = style.route_clearance.points
        base_x: list[float] = [self.canvas.left, self.canvas.right]
        base_y: list[float] = [self.canvas.top, self.canvas.bottom]
        for node in self.solid:
            ring = node.bounds.inflated(route_clearance(node.measured.spec, style))
            for rect in (node.bounds, ring):
                base_x.extend((rect.left, rect.right))
                base_y.extend((rect.top, rect.bottom))
        for group in self.containers:
            for amount in (0.0, clearance, -clearance):
                if amount < 0 and -2 * amount > min(group.bounds.width, group.bounds.height):
                    continue
                rect = group.bounds.inflated(amount)
                base_x.extend((rect.left, rect.right))
                base_y.extend((rect.top, rect.bottom))
        for rect in self.titles:
            ring = rect.inflated(style.caption_clearance.points)
            base_x.extend((ring.left, ring.right))
            base_y.extend((ring.top, ring.bottom))
        self.base_x = _with_midlines(base_x)
        self.base_y = _with_midlines(base_y)
        band = style.route_clearance.points
        self.border_zones = tuple(
            Zone(rect, BORDER_COST)
            for group in self.containers
            for rect in _border_bands(group.bounds, band)
        )
        self.title_zones = tuple(
            zone
            for rect in self.titles
            for zone in (
                Zone(rect, CAPTION_COST),
                Zone(rect.inflated(style.caption_clearance.points), RING_COST),
            )
        )

    def _node_zones(self, node: FittedNode, clearance: float) -> tuple[Zone, ...]:
        core = CAPTION_COST if node.measured.spec.kind in CAPTION_KINDS else NODE_COST
        # The core takes in the outline itself: a line drawn *on* a box's edge --
        # squeezed between two boxes that touch -- is through the box, not past it.
        return (
            Zone(node.bounds.inflated(0.5), core),
            Zone(node.bounds.inflated(clearance), RING_COST),
        )

    def _zones(self, pins: list[_Pin]) -> tuple[Zone, ...]:
        # Every box keeps its ordinary ring, the route's own ends included: the
        # arrow's longer straight approach is guaranteed by where its pin escapes
        # to, and ringing the whole target with it would push every other branch
        # of the same tree off the box's far sides.
        zones: list[Zone] = list(self.title_zones) + list(self.border_zones)
        for node in self.solid:
            zones.extend(self._node_zones(node, route_clearance(node.measured.spec, self.style)))
        owned: set[str] = set()
        for pin in pins:
            owned.update(ancestors(self.parents, pin.node.measured.spec.id))
        points = tuple(pin.point for pin in pins) + tuple(pin.escape for pin in pins)
        for group in self.containers:
            group_id = group.measured.spec.id
            if group_id in owned:
                if not all(group.bounds.contains_point(point) for point in points):
                    zones.append(Zone(group.bounds, LEAVE_COST))
            elif not any(group.bounds.contains_point(point) for point in points):
                zones.append(
                    Zone(group.bounds.inflated(self.style.route_clearance.points), FOREIGN_COST)
                )
        return tuple(zones)

    def _grid(
        self,
        pins: list[_Pin],
        extra: tuple[Point, ...] = (),
        *,
        lean: Side | None = None,
    ) -> Grid:
        node_ids = tuple(pin.node.measured.spec.id for pin in pins)
        boundary = routing_boundary(
            self.fitted, node_ids, self.style.route_boundary_clearance.points
        )
        xs = list(self.base_x)
        ys = list(self.base_y)
        for point in (*(pin.point for pin in pins), *(pin.escape for pin in pins), *extra):
            xs.append(point.x)
            ys.append(point.y)
        xs.extend((boundary.left, boundary.right))
        ys.extend((boundary.top, boundary.bottom))
        zones = self._zones(pins)
        if lean is not None:
            region = Rect.union(
                Rect.from_points(pin.point, pin.escape) for pin in pins
            )
            refused = _refused(lean, region, self.canvas.inflated(1000.0))
            zones = (*zones, Zone(refused, OFF_SIDE_COST))
            if lean in {Side.EAST, Side.WEST}:
                xs.extend((refused.left, refused.right))
            else:
                ys.extend((refused.top, refused.bottom))
        return Grid(xs, ys, zones, boundary=boundary, outside_cost=OUTSIDE_COST)

    def grow(
        self,
        bundle: _Bundle,
        members: list[_Member],
        ends: list[_End],
        pins: dict[tuple[str, str, Side, bool], _Pin],
        others: _Traffic | None = None,
    ) -> Wire:
        """Route one bundle as a tree rooted at its hub pin.

        ``others`` is the ink every other bundle drew in the previous pass;
        crossing it or running on top of it is priced, so the second pass
        steers around what the first pass could not see.
        """

        hub = pins[bundle.hub]
        spoke_keys: list[tuple[str, str, Side, bool]] = []
        for member_index in bundle.members:
            for end in members[member_index].ends:
                key = ends[end].group
                assert key is not None
                if key != bundle.hub and key not in spoke_keys:
                    spoke_keys.append(key)
        spokes = [pins[key] for key in spoke_keys]
        everything = [hub, *spokes]
        bend = self.style.bend_penalty
        if bundle.pinned:
            member = members[bundle.members[0]].spec
            assert isinstance(member, EdgeSpec)
            return self._forced_route(member, hub, spokes[0], bend)
        lean = _lean(bundle, members)
        shortest = self.style.shortest_arrival.points
        short = {
            spoke.key: spoke.side.escaped(spoke.point, shortest)
            for spoke in spokes
            if spoke.arriving and spoke.clearance > shortest + 1e-6
        }
        grid = self._grid(everything, tuple(short.values()), lean=lean)
        stubs: dict[tuple[str, str, Side, bool], Point] = {}
        paths: list[list[Point]] = [[hub.point, hub.escape]]
        seeds: list[tuple[Point, int | None, float]] = [(hub.escape, _HEADING[hub.side], 0.0)]
        remaining = list(spokes)
        while remaining:
            best: tuple[float, int, tuple[Point, ...]] | None = None
            for index, spoke in enumerate(remaining):
                # An arrow may turn in closer than the full clearance -- down to
                # its head and one elbow -- at a price, so a route one lane off
                # comes straight in rather than jogging out to the full stub.
                alternatives = (
                    ((short[spoke.key], SHORT_APPROACH_COST * (spoke.clearance - shortest)),)
                    if spoke.key in short
                    else ()
                )
                path, cost = grid.route_from_tree(
                    tuple(seeds),
                    spoke.escape,
                    _INTO[spoke.side],
                    bend=bend,
                    extra=others.price if others is not None else None,
                    alternatives=alternatives,
                )
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, index, path)
            assert best is not None
            _, index, path = best
            spoke = remaining.pop(index)
            stubs[spoke.key] = path[-1]
            paths.append(list(simplify((*path, spoke.point))))
            seeds.extend(_tree_seeds(grid, path))
        terminals = []
        for pin in everything:
            stub = stubs.get(pin.key, pin.escape)
            terminals.append(Terminal(pin.point, stub.distance_to(pin.point), stub))
        wire = Wire(bundle.key, paths, terminals)
        for member_index in bundle.members:
            spec = members[member_index].spec
            if isinstance(spec, NetSpec):
                count = len(spec.sources)
                sources = [pins[ends[end].group] for end in members[member_index].ends[:count]]
                targets = [
                    pins[ends[end].group]
                    for end in members[member_index].ends[len(spec.sources) :]
                ]
                wire.flow_from = Point(
                    sum(pin.point.x for pin in sources) / len(sources),
                    sum(pin.point.y for pin in sources) / len(sources),
                )
                if spec.kind == "fan-out":
                    far = max(targets, key=lambda pin: pin.point.distance_to(wire.flow_from))
                    wire.flow_to = far.point
                else:
                    wire.flow_to = targets[0].point
                    wire.flow_from = max(
                        sources, key=lambda pin: -abs(
                            (pin.point.y - targets[0].point.y)
                            if targets[0].side in {Side.EAST, Side.WEST}
                            else (pin.point.x - targets[0].point.x)
                        )
                    ).point
                # A captioned net hands its run to the caption: the joint goes to
                # the far end of its corridor unless the author placed it.
                wire.rail_at = (
                    spec.rail_at if spec.rail_at is not None else (1.0 if spec.label else None)
                )
                wire.rail_side = spec.rail_hint
        return wire

    def _forced_route(self, edge: EdgeSpec, source: _Pin, target: _Pin, bend: float) -> Wire:

        forced = forced_points(
            self.fitted,
            edge,
            source.escape,
            target.escape,
            self.style.route_boundary_clearance.points,
        )
        grid = self._grid([source, target], forced)
        waypoints = (source.escape, *forced, target.escape)
        points: list[Point] = [source.point]
        heading: int | None = _HEADING[source.side]
        for index, (start, end) in enumerate(itertools.pairwise(waypoints)):
            last = index == len(waypoints) - 2
            leg, _ = grid.route_from_tree(
                ((start, heading, 0.0),), end, _INTO[target.side] if last else None, bend=bend
            )
            points.extend(leg if leg[0] != points[-1] else leg[1:])
            steps = segments(leg)
            if steps:
                heading = _heading_between(steps[-1].start, steps[-1].end)
        points.append(target.point)
        return Wire(
            edge.id,
            [list(simplify(tuple(points)))],
            [Terminal(source.point, source.clearance), Terminal(target.point, target.clearance)],
            pinned=True,
        )

    def separation_obstacles(self) -> tuple[Rect, ...]:
        """What a run may not be moved across: each box with its ring, and the box.

        The bare box is listed too: a run the search had to lay inside a ring
        (the gap was narrower than two clearances) is past the ring's edge, so
        the ring alone would not stop the spacing pass sliding it into the box.
        """

        return (
            tuple(
                node.bounds.inflated(route_clearance(node.measured.spec, self.style))
                for node in self.solid
            )
            + tuple(node.bounds for node in self.solid)
            + tuple(rect.inflated(self.style.caption_clearance.points) for rect in self.titles)
        )

    def walls(self) -> tuple[Rect, ...]:
        margin = self.style.route_clearance.points / 2.0
        return (
            self.canvas.inflated(-margin),
            *(group.bounds for group in self.containers),
        )


class _Traffic:
    """The ink of other bundles, indexed for pricing one search step against it."""

    def __init__(self, wires: list[Wire], *, crossing: float) -> None:
        self.crossing = crossing
        self.vertical: dict[float, list[tuple[float, float, float]]] = defaultdict(list)
        self.horizontal: dict[float, list[tuple[float, float, float]]] = defaultdict(list)
        vertical_xs: list[tuple[float, float, float]] = []
        horizontal_ys: list[tuple[float, float, float]] = []
        for wire in wires:
            for path in wire.paths:
                for start, end in itertools.pairwise(path):
                    # A run that ends at a port cannot be moved apart from
                    # anything lying on it later: sharing it is as bad as a crossing.
                    stuck = (
                        wire.terminal_clearance(start) is not None
                        or wire.terminal_clearance(end) is not None
                    )
                    rate = self.crossing if stuck else OVERLAP_COST
                    if abs(start.x - end.x) < 1e-9 and abs(start.y - end.y) > 1e-9:
                        low, high = sorted((start.y, end.y))
                        self.vertical[round(start.x, 6)].append((low, high, rate))
                        vertical_xs.append((start.x, low, high))
                    elif abs(start.y - end.y) < 1e-9 and abs(start.x - end.x) > 1e-9:
                        low, high = sorted((start.x, end.x))
                        self.horizontal[round(start.y, 6)].append((low, high, rate))
                        horizontal_ys.append((start.y, low, high))
        self.vertical_xs = sorted(vertical_xs)
        self.horizontal_ys = sorted(horizontal_ys)
        self._keys_x = [item[0] for item in self.vertical_xs]
        self._keys_y = [item[0] for item in self.horizontal_ys]

    def price(self, grid: Grid, ix: int, iy: int, heading: int) -> float:
        from bisect import bisect_left

        if heading in (EAST, WEST):
            y = grid.ys[iy]
            other = grid.xs[ix + (1 if heading == EAST else -1)]
            low, high = sorted((grid.xs[ix], other))
            cost = 0.0
            # Half-open: another route's run lies on a grid line, so it meets
            # this step at an end; counting [low, high) charges it exactly once.
            start = bisect_left(self._keys_x, low - 1e-9)
            stop = bisect_left(self._keys_x, high - 1e-9)
            for _, top, bottom in self.vertical_xs[start:stop]:
                if top + 1e-9 < y < bottom - 1e-9:
                    cost += self.crossing
            for left, right, rate in self.horizontal.get(round(y, 6), ()):
                shared = min(high, right) - max(low, left)
                if shared > 1e-9:
                    cost += rate if rate > OVERLAP_COST else shared * rate
            return cost
        x = grid.xs[ix]
        other = grid.ys[iy + (1 if heading == SOUTH else -1)]
        low, high = sorted((grid.ys[iy], other))
        cost = 0.0
        start = bisect_left(self._keys_y, low - 1e-9)
        stop = bisect_left(self._keys_y, high - 1e-9)
        for _, left, right in self.horizontal_ys[start:stop]:
            if left + 1e-9 < x < right - 1e-9:
                cost += self.crossing
        for top, bottom, rate in self.vertical.get(round(x, 6), ()):
            shared = min(high, bottom) - max(low, top)
            if shared > 1e-9:
                cost += rate if rate > OVERLAP_COST else shared * rate
        return cost


def _lean(bundle: _Bundle, members: list[_Member]) -> Side | None:
    """The side a bundle was asked to keep to: a ``via``, or a net's ``rail``."""

    for member_index in bundle.members:
        spec = members[member_index].spec
        if isinstance(spec, NetSpec) and spec.rail_hint is not None:
            return spec.rail_hint
        if spec.via is not None:
            return spec.via
    return None


def _refused(side: Side, region: Rect, world: Rect) -> Rect:
    """Everything beyond ``region`` on the side opposite ``side``."""

    if side is Side.WEST:
        return Rect(region.right, world.top, world.right - region.right, world.height)
    if side is Side.EAST:
        return Rect(world.left, world.top, region.left - world.left, world.height)
    if side is Side.NORTH:
        return Rect(world.left, region.bottom, world.width, world.bottom - region.bottom)
    return Rect(world.left, world.top, world.width, region.top - world.top)


def _border_bands(bounds: Rect, band: float) -> tuple[Rect, ...]:
    """Thin strips straddling each edge of a container: its border and a little either side."""

    half = band / 2.0
    return (
        Rect(bounds.left - half, bounds.top - half, bounds.width + band, band),
        Rect(bounds.left - half, bounds.bottom - half, bounds.width + band, band),
        Rect(bounds.left - half, bounds.top - half, band, bounds.height + band),
        Rect(bounds.right - half, bounds.top - half, band, bounds.height + band),
    )


def _title_rect(group, style: LayoutStyle) -> Rect | None:
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


def _with_midlines(values: list[float]) -> list[float]:
    ordered = sorted(set(values))
    result = list(ordered)
    for low, high in itertools.pairwise(ordered):
        if high - low > 1.0:
            result.append((low + high) / 2.0)
    return result


def _heading_between(start: Point, end: Point) -> int:
    if abs(end.x - start.x) >= abs(end.y - start.y):
        return EAST if end.x > start.x else WEST
    return SOUTH if end.y > start.y else NORTH


def _tree_seeds(grid: Grid, path: tuple[Point, ...]) -> list[tuple[Point, int | None, float]]:
    """Every grid point on ``path``, as a place a later branch may leave from."""

    seeds: list[tuple[Point, int | None, float]] = []
    for start, end in itertools.pairwise(path):
        if abs(start.y - end.y) < 1e-9:
            low, high = sorted((start.x, end.x))
            for x in grid.xs:
                if low - 1e-9 <= x <= high + 1e-9:
                    seeds.append((Point(x, start.y), None, 0.0))
        else:
            low, high = sorted((start.y, end.y))
            for y in grid.ys:
                if low - 1e-9 <= y <= high + 1e-9:
                    seeds.append((Point(start.x, y), None, 0.0))
    return seeds


# -- back to the routed IR ------------------------------------------------------------------


def _key(point: Point) -> tuple[float, float]:
    return (round(point.x, 5), round(point.y, 5))


class _Graph:
    """A routed wire as an undirected graph, split wherever a vertex lies on a segment."""

    def __init__(self, wire: Wire) -> None:
        self.points: dict[tuple[float, float], Point] = {}
        for path in wire.paths:
            for point in path:
                self.points.setdefault(_key(point), point)
        self.adjacency: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
        for path in wire.paths:
            for start, end in itertools.pairwise(path):
                if _key(start) == _key(end):
                    continue
                horizontal = abs(start.y - end.y) < 1e-6
                low, high = sorted((start.x, end.x)) if horizontal else sorted((start.y, end.y))
                inside = [
                    point
                    for point in self.points.values()
                    if (
                        abs(point.y - start.y) < 1e-6 and low - 1e-6 <= point.x <= high + 1e-6
                        if horizontal
                        else abs(point.x - start.x) < 1e-6 and low - 1e-6 <= point.y <= high + 1e-6
                    )
                ]
                inside.sort(key=lambda point: point.x if horizontal else point.y)
                for first, second in itertools.pairwise(inside):
                    if _key(first) != _key(second):
                        self.adjacency[_key(first)].add(_key(second))
                        self.adjacency[_key(second)].add(_key(first))

    def path(self, start: Point, end: Point) -> tuple[Point, ...]:
        """The tree path between two of its vertices."""

        origin, goal = _key(start), _key(end)
        previous: dict[tuple[float, float], tuple[float, float] | None] = {origin: None}
        queue = deque([origin])
        while queue:
            item = queue.popleft()
            if item == goal:
                break
            for following in sorted(self.adjacency[item]):
                if following not in previous:
                    previous[following] = item
                    queue.append(following)
        chain = []
        walk: tuple[float, float] | None = goal
        while walk is not None:
            chain.append(self.points[walk])
            walk = previous.get(walk)
        chain.reverse()
        return simplify(tuple(chain))

    def subtree(self, terminals: list[Point]) -> dict[tuple[float, float], set]:
        """The part of the tree spanning ``terminals``, as adjacency."""

        adjacency: dict[tuple[float, float], set] = defaultdict(set)
        for point in terminals[1:]:
            chain = self.path(terminals[0], point)
            for first, second in itertools.pairwise(chain):
                self._add_run(adjacency, first, second)
        return adjacency

    def _add_run(self, adjacency: dict, first: Point, second: Point) -> None:
        horizontal = abs(first.y - second.y) < 1e-6
        low, high = sorted((first.x, second.x)) if horizontal else sorted((first.y, second.y))
        inside = sorted(
            (
                key
                for key, point in self.points.items()
                if (
                    abs(point.y - first.y) < 1e-6 and low - 1e-6 <= point.x <= high + 1e-6
                    if horizontal
                    else abs(point.x - first.x) < 1e-6 and low - 1e-6 <= point.y <= high + 1e-6
                )
            ),
            key=lambda key: key[0] if horizontal else key[1],
        )
        for a, b in itertools.pairwise(inside):
            adjacency[a].add(b)
            adjacency[b].add(a)

    def joins(self, hub: Point) -> set[tuple[tuple[float, float], tuple[float, float]]]:
        """``(junction, neighbour)`` for every branch that merges *across* the line
        leading on to ``hub``: the pieces that end in an arrowhead at a merge.

        At a junction the line carrying the flow on is the neighbour nearer the hub;
        a piece arriving in line with it is the same line, one arriving across it
        joins it.
        """

        distance = {_key(hub): 0}
        queue = deque([_key(hub)])
        while queue:
            item = queue.popleft()
            for following in self.adjacency[item]:
                if following not in distance:
                    distance[following] = distance[item] + 1
                    queue.append(following)
        result = set()
        for junction, neighbours in self.adjacency.items():
            if len(neighbours) < 3 or junction not in distance:
                continue
            onward = min(neighbours, key=lambda key: (distance.get(key, 1 << 30), key))
            onward_horizontal = abs(onward[1] - junction[1]) < 1e-6
            for neighbour in neighbours:
                if neighbour == onward:
                    continue
                horizontal = abs(neighbour[1] - junction[1]) < 1e-6
                if horizontal != onward_horizontal:
                    result.add((junction, neighbour))
        return result

    def dots(self, adjacency: dict | None = None) -> tuple[Point, ...]:
        graph = self.adjacency if adjacency is None else adjacency
        return tuple(self.points[key] for key in sorted(graph) if len(graph[key]) >= 3)


def _joint_of(bundle: _Bundle, members: list[_Member]) -> str:
    """The ``joint`` a bundle's nets ask for: ``"arrow"``, ``"dot"``, or ``"auto"``."""

    joints = {
        members[index].spec.joint  # type: ignore[union-attr]
        for index in bundle.members
        if members[index].kind == "net"
    }
    return "arrow" if "arrow" in joints else "dot" if "dot" in joints else "auto"


def _dots_at_joins(
    bundle: _Bundle,
    members: list[_Member],
    pins: dict[tuple[str, str, Side, bool], _Pin],
    style: LayoutStyle,
) -> bool:
    """Whether this bundle's joins get dots: its net asks, or the conventions do."""

    joint = _joint_of(bundle, members)
    if joint != "auto":
        return joint == "dot"
    if pins[bundle.hub].arriving:
        return style.conventions.merge == "dot"
    return style.conventions.branch == "dot"


def _arrows_at_joins(
    bundle: _Bundle,
    members: list[_Member],
    pins: dict[tuple[str, str, Side, bool], _Pin],
    style: LayoutStyle,
) -> bool:
    """Whether the branches of this bundle end in arrowheads where they merge.

    Under ``merge="auto"``, a merge of two -- one line joining another that
    carries on -- marks the join with an arrowhead pointing into the line, and a
    merge of three or more is a bus: the branches meet it plainly and the one
    arrow is into the destination. ``merge="arrow"`` arrows every join and
    ``"plain"``/``"dot"`` none. A branch point of a fan-out is never an arrow.
    A net's own ``joint=`` overrules the conventions.
    """

    if not pins[bundle.hub].arriving:
        return False
    joint = _joint_of(bundle, members)
    if joint != "auto":
        return joint == "arrow"
    if style.conventions.merge != "auto":
        return style.conventions.merge == "arrow"
    sources = sum(
        len(members[index].spec.sources) if members[index].kind == "net" else 1  # type: ignore[union-attr]
        for index in bundle.members
    )
    return sources == 2


def _edge_cuts(
    bundle: _Bundle,
    members: list[_Member],
    ends: list[_End],
    pins: dict[tuple[str, str, Side, bool], _Pin],
    graph: _Graph,
    joins: set,
) -> dict[int, Point]:
    """Where each merging edge of a bundle stops and points into the line it joins.

    An edge that reaches a junction across the onward line joins it there. The
    onward line itself has to be drawn by someone: by an edge passing straight
    through the junction if there is one, otherwise by the first edge that
    arrives there, which keeps its whole route.
    """

    if not joins:
        return {}
    arrivals: dict[tuple[float, float], list[int]] = defaultdict(list)
    through: set[tuple[float, float]] = set()
    for member_index in bundle.members:
        member = members[member_index]
        if member.kind != "edge":
            through.update(junction for junction, _ in joins)
            continue
        source = pins[ends[member.ends[0]].group].point  # type: ignore[index]
        target = pins[ends[member.ends[1]].group].point  # type: ignore[index]
        chain = [_key(point) for point in graph.path(source, target)]
        full = _expanded(graph, chain)
        joined = None
        for before, here in itertools.pairwise(full):
            if (here, before) in joins:
                joined = here
                break
            if len(graph.adjacency.get(here, ())) >= 3:
                through.add(here)
        if joined is not None:
            arrivals[joined].append(member_index)
    cuts: dict[int, Point] = {}
    for junction, arriving in arrivals.items():
        keep = () if junction in through else arriving[:1]
        for member_index in arriving:
            if member_index not in keep:
                cuts[member_index] = graph.points[junction]
    return cuts


def _expanded(graph: _Graph, chain: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """``chain`` with every graph vertex lying between consecutive corners put back."""

    result = chain[:1]
    for first, second in itertools.pairwise(chain):
        horizontal = abs(first[1] - second[1]) < 1e-6
        low, high = sorted((first[0], second[0])) if horizontal else sorted((first[1], second[1]))
        inside = sorted(
            (
                key
                for key in graph.adjacency
                if key not in (first, second)
                and (
                    abs(key[1] - first[1]) < 1e-6 and low < key[0] < high
                    if horizontal
                    else abs(key[0] - first[0]) < 1e-6 and low < key[1] < high
                )
            ),
            key=lambda key: abs(key[0] - first[0]) + abs(key[1] - first[1]),
        )
        result.extend(inside)
        result.append(second)
    return result


def _routed_edge(
    edge: EdgeSpec,
    centerline: tuple[Point, ...],
    style: LayoutStyle,
    measurer: TextMeasurer,
    *,
    dots: tuple[Point, ...] = (),
    joints: tuple[Point, ...] = (),
    bundle: str | None = None,
    joined_at: Point | None = None,
) -> RoutedEdge:
    drawn = centerline
    if joined_at is not None:
        # Merges into another edge of its bundle: the ink stops at the joint
        # and points into the line that carries on; that line is drawn by the
        # edge it merges into.
        index = next(
            position for position, point in enumerate(centerline) if _key(point) == _key(joined_at)
        )
        drawn = centerline[: index + 1]
    shaft = _shaft(edge, drawn, style)
    metrics = measurer.measure(edge.label) if edge.label else None
    position = edge_label_position(centerline, metrics, style) if metrics is not None else None
    diagnostics: tuple[Diagnostic, ...] = ()
    if edge.via is not None and len(centerline) >= 2:

        region = Rect.union(
            (
                Rect.from_points(centerline[0], centerline[-1]),
                Rect.from_points(
                    _along(centerline[0], centerline[1], style.route_clearance.points),
                    _along(centerline[-1], centerline[-2], style.arrival_clearance.points),
                ),
            )
        )
        diagnostics = via_diagnostics(edge, centerline, SideBias.of(edge.via, region))
    return RoutedEdge(
        edge,
        centerline,
        shaft,
        metrics,
        position,
        diagnostics,
        dots=dots,
        joints=joints,
        bundle=bundle,
        joined_at=joined_at,
    )


def _shaft(edge: EdgeSpec, drawn: tuple[Point, ...], style: LayoutStyle) -> tuple[Point, ...]:
    """The painted line: short of each end by its arrowhead and the standoff.

    An end with no arrowhead meets its component; an end with one stops a
    head's length plus ``connector_standoff`` short, so the tip lands just clear.
    """

    head = style.arrow_length.points + style.connector_standoff.points
    if edge.arrow == "none":
        return drawn
    shaft = edge_shaft(
        drawn,
        arrow_length=style.arrow_length.points,
        standoff=style.connector_standoff.points,
    )
    if edge.arrow == "both":
        shaft = shorten_start(shaft, head - style.connector_standoff.points)
    return shaft


def _routed_net(
    net: NetSpec,
    graph: _Graph,
    wire: Wire,
    terminals: list[tuple[_End, _Pin]],
    style: LayoutStyle,
    measurer: TextMeasurer,
    *,
    bundle: str | None,
    all_dots: bool,
    draw_dots: bool = True,
    joins: set | None = None,
) -> RoutedNet:
    hub_index = 0 if net.kind == "fan-out" else len(net.sources)
    ordered = [terminals[hub_index], *terminals[:hub_index], *terminals[hub_index + 1 :]]
    adjacency = graph.subtree([pin.point for _, pin in ordered])
    points = graph.points
    sources = {_key(pin.point): end for end, pin in terminals if not end.arriving}
    targets = {_key(pin.point): end for end, pin in terminals if end.arriving}
    # Split at the bundle's junctions too: where an edge of the same bundle
    # carries on straight, the net's corner there is a T, not a fillet.
    special = {
        key
        for key, neighbours in adjacency.items()
        if len(neighbours) != 2
        or key in sources
        or key in targets
        or len(graph.adjacency.get(key, ())) >= 3
    }
    pieces: list[list[tuple[float, float]]] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for start in sorted(special):
        for neighbour in sorted(adjacency[start]):
            if (start, neighbour) in seen:
                continue
            chain = [start, neighbour]
            seen.add((start, neighbour))
            while chain[-1] not in special:
                following = next(key for key in adjacency[chain[-1]] if key != chain[-2])
                seen.add((chain[-1], following))
                chain.append(following)
            seen.add((chain[-1], chain[-2]))
            pieces.append(chain)
    source_stems: list[RoutedStem] = []
    target_stems: list[RoutedStem] = []
    trunks: list[tuple[Point, ...]] = []
    standoff = style.connector_standoff.points
    reach = style.arrow_length.points + standoff
    for chain in pieces:
        head, tail = chain[0], chain[-1]
        if head in targets or (tail in sources and head not in sources):
            chain = chain[::-1]
            head, tail = tail, head
        line = simplify(tuple(points[key] for key in chain))
        if head in sources and tail in targets:
            first, second = _split(line)
            source_stems.append(
                RoutedStem(sources[head].reference, first, shorten_start(first, standoff))
            )
            target_stems.append(
                RoutedStem(targets[tail].reference, second, shorten_end(second, reach), True)
            )
        elif head in sources:
            source_stems.append(
                RoutedStem(sources[head].reference, line, shorten_start(line, standoff))
            )
        elif tail in targets:
            target_stems.append(
                RoutedStem(targets[tail].reference, line, shorten_end(line, reach), True)
            )
        else:
            trunks.append(line)
    dots_removed: set[tuple[float, float]] = set()
    marked: list[tuple[Point, ...]] = []
    if joins:
        source_stems, trunks, marked, dots_removed = _mark_joins(
            source_stems, trunks, joins, reach
        )
    order = {reference: index for index, reference in enumerate(net.sources + net.targets)}
    source_stems.sort(key=lambda stem: order[stem.port])
    target_stems.sort(key=lambda stem: order[stem.port])
    trunks.sort(key=lambda line: -sum(segment.length for segment in segments(line)))
    junctions = graph.dots() if all_dots else graph.dots(adjacency)
    junctions = tuple(point for point in junctions if _key(point) not in dots_removed)
    dots = junctions if draw_dots else ()
    if trunks:
        rail = trunks[0]
    elif junctions:
        rail = (junctions[0],)
    else:
        rail = (source_stems[0].centerline[-1],)
    metrics = measurer.measure(net.label) if net.label else None
    position = None
    if metrics is not None:
        position = rail_label_position(
            rail,
            tuple(trunks[1:]) + tuple(stem.shaft for stem in (*source_stems, *target_stems)),
            metrics,
            style,
        )
    return RoutedNet(
        net,
        rail,
        tuple(source_stems),
        tuple(target_stems),
        metrics,
        position,
        _rail_notes(net, wire),
        trunks=tuple(trunks[1:]),
        dots=dots,
        bundle=bundle,
        joins=tuple(marked),
    )


def _rail_notes(net: NetSpec, wire: Wire) -> tuple[Diagnostic, ...]:
    """Say out loud that an authored ``rail_at`` had to give way to clearances."""

    if net.rail_at is None or wire.rail_clamped is None:
        return ()
    return (
        Diagnostic(
            "routing.net.rail-at.clamped",
            f"Requested rail_at {net.rail_at:.3f} leaves no clearance; "
            f"the nearest clear rail sits at {wire.rail_clamped:.3f}.",
            Severity.WARNING,
            entity_id=net.id,
            hint="Open a gap at that fraction of the run, or request a clearer one.",
        ),
    )


def _mark_joins(
    source_stems: list[RoutedStem],
    trunks: list[tuple[Point, ...]],
    joins: set,
    reach: float,
) -> tuple[list[RoutedStem], list[tuple[Point, ...]], list[tuple[Point, ...]], set]:
    """A merge's branches end in arrowheads where they join the onward line.

    A source stem or a trunk piece that reaches a junction *across* the line
    leading on to the destination stops one arrow and a standoff short of it and
    points in; the junction needs no dot, because the arrowhead marks the join.
    """

    removed: set = set()
    stems = []
    for stem in source_stems:
        line = stem.centerline
        if len(line) >= 2 and (_key(line[-1]), _key(line[-2])) in joins:
            removed.add(_key(line[-1]))
            stems.append(RoutedStem(stem.port, line, shorten_end(stem.shaft, reach), True))
        else:
            stems.append(stem)
    plain: list[tuple[Point, ...]] = []
    marked: list[tuple[Point, ...]] = []
    for line in trunks:
        if len(line) >= 2 and (_key(line[0]), _key(line[1])) in joins:
            line = line[::-1]
        if len(line) >= 2 and (_key(line[-1]), _key(line[-2])) in joins:
            removed.add(_key(line[-1]))
            marked.append(shorten_end(line, reach))
        else:
            plain.append(line)
    return stems, plain, marked, removed


def _along(start: Point, toward: Point, distance: float) -> Point:
    span = start.distance_to(toward)
    if span <= 0.0:
        return start
    ratio = min(1.0, distance / span)
    return Point(start.x + (toward.x - start.x) * ratio, start.y + (toward.y - start.y) * ratio)


def _split(line: tuple[Point, ...]) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    """A source-to-target piece cut in two in the middle of its longest run."""

    runs = segments(line)
    index = max(range(len(runs)), key=lambda position: runs[position].length)
    middle = Point(
        (runs[index].start.x + runs[index].end.x) / 2.0,
        (runs[index].start.y + runs[index].end.y) / 2.0,
    )
    return (*line[: index + 1], middle), (middle, *line[index + 1 :])
