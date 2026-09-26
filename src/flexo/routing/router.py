"""Route every connector of a fitted figure: pins, search, trees, separation.

The pipeline follows the routers that draw connectors well (libavoid, ELK):

1. **Pins** (``pins``). Every end of every connection gets its own attachment
   point. A port the grammar placed on a default side (``auto_side``) is
   attached on the side that faces the thing at the other end *of that
   connection*, so a value that goes both down and sideways leaves from two
   sides instead of wrapping around the box. Ends of one port that leave the
   same side share one pin, and the pins on a side are ordered by where their
   lines go, so lines leaving one box never cross each other on the way out.
2. **Bundles** (``pins``). Connections that share a pin are one value going to
   several places (or several values arriving at one place), so they are routed
   as one tree rooted at the shared pin. A net is a bundle too.
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

The result is the ``RoutedFigure`` the rest of the compiler reads, built from
each routed tree by ``trees``. Where three or more pieces of a tree meet -- a
branch point, never a bend -- the figure's conventions (``flexo.conventions``)
decide the mark: a plain T, an arrowhead into the line joined, or a dot.

This module is the orchestrator: ``route_figure``, the scene every search runs
in (zones, grids, growing a tree), the pricing of other bundles' ink, the pin
swaps that take crossings out, and the search's cost constants.
"""

from __future__ import annotations

import copy
import itertools
from collections import defaultdict

from flexo.components import CAPTION_KINDS, TRANSPARENT_KINDS, TRANSPARENT_ROLES, route_clearance
from flexo.geometry import Point, Rect, Side, segments
from flexo.hierarchy import ancestors, parent_map, routing_boundary
from flexo.ir.fitted import FittedFigure, FittedNode
from flexo.ir.routed import RoutedEdge, RoutedFigure, RoutedNet
from flexo.ir.semantic import EdgeSpec, NetSpec
from flexo.routing.hints import forced_points
from flexo.routing.ink import caption_reach, caption_rise
from flexo.routing.labels import place_captions
from flexo.routing.pins import (
    POINT_KINDS,
    Bundle,
    End,
    Member,
    Pin,
    connections,
    plan_bundles,
    plan_pins,
    title_rect,
)
from flexo.routing.search import EAST, NORTH, SOUTH, WEST, Grid, Zone, simplify
from flexo.routing.separate import (
    CaptionRoom,
    Terminal,
    Wire,
    _perpendicular_cross,
    separate,
)
from flexo.routing.trees import (
    WireGraph,
    arrows_at_joins,
    dots_at_joins,
    edge_cuts,
    point_key,
    routed_edge,
    routed_net,
    straight_edge,
)
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

CROSSING_COST = 4.0
"""Price of crossing another connector, in bends: a short detour beats a crossing."""

OVERLAP_COST = 0.03
"""Price per point of running exactly on top of another connector."""

REROUTE_PASSES = 2
"""How many times every bundle is routed again with the others in view."""

SHORT_APPROACH_COST = 1.0
"""Per point of arrival stub given up to come straight in instead of jogging."""

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


def route_figure(
    fitted: FittedFigure,
    *,
    style: LayoutStyle | None = None,
    measurer: TextMeasurer | None = None,
) -> RoutedFigure:
    layout_style = style or figure_style(fitted.measured.semantic)
    text_measurer = measurer or TextMeasurer(layout_style.typography)
    semantic = fitted.measured.semantic
    straight = {edge.id for edge in semantic.edges if _is_straight(edge, layout_style)}
    members, ends = connections(fitted, straight)
    scene = _Scene(fitted, layout_style, text_measurer)

    def attempt(
        overrides: dict[tuple[str, Side], list], sides: dict[int, Side] | None = None
    ) -> tuple:
        orders: dict[tuple[str, Side], list] = {}
        pins = plan_pins(fitted, members, ends, layout_style, overrides, orders, sides)
        bundles = plan_bundles(members, ends)
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
        routed = wires
        wires = copy.deepcopy(wires)
        separate(
            wires,
            scene.separation_obstacles(),
            scene.walls(),
            spacing=layout_style.port_spacing.points,
        )
        # Separation only slides runs along their normal. A wire it bent off
        # the axis anyway keeps the geometry the search gave it: a crowded line
        # is a flaw lint reports, a diagonal in an orthogonal figure is a break.
        return [
            spaced if _orthogonal(spaced) else copy.deepcopy(original)
            for spaced, original in zip(wires, routed, strict=True)
        ]

    pins, bundles, wires, orders = attempt({})
    pins, bundles, wires = _reorder_crossing_pins(
        attempt,
        separated,
        pins,
        bundles,
        wires,
        orders,
        members,
        ends,
        layout_style.port_spacing.points,
    )
    wires = separated(wires)
    routed_edges: dict[str, RoutedEdge] = {}
    routed_nets: dict[str, RoutedNet] = {}
    for bundle, wire in zip(bundles, wires, strict=True):
        graph = WireGraph(wire)
        shared = len(bundle.members) > 1
        dots_given = False
        hub = pins[bundle.hub]
        # Where branches merge, each stops at the line it joins -- with an
        # arrowhead into it, or plainly at a bus -- and one draws on.
        arrowed = arrows_at_joins(bundle, members, pins, layout_style)
        joins = graph.joins(hub.point) if hub.arriving else set()
        marked = dots_at_joins(bundle, members, pins, layout_style)
        cut = edge_cuts(bundle, members, ends, pins, graph, joins)
        for member_index in bundle.members:
            member = members[member_index]
            member_pins = [pins[ends[end].group] for end in member.ends]  # type: ignore[index]
            if member.kind == "edge":
                assert isinstance(member.spec, EdgeSpec)
                dots = graph.dots() if shared and marked and not dots_given else ()
                dots_given = dots_given or bool(dots)
                routed_edges[member.spec.id] = routed_edge(
                    member.spec,
                    graph.path(member_pins[0].point, member_pins[1].point),
                    layout_style,
                    text_measurer,
                    dots=dots,
                    joints=graph.dots() if shared else (),
                    bundle=bundle.key if shared else None,
                    joined_at=cut.get(member_index),
                    join_arrow=arrowed,
                )
            else:
                assert isinstance(member.spec, NetSpec)
                routed_nets[member.spec.id] = routed_net(
                    member.spec,
                    graph,
                    wire,
                    [(ends[end], pins[ends[end].group]) for end in member.ends],  # type: ignore[index]
                    layout_style,
                    text_measurer,
                    bundle=bundle.key if shared else None,
                    all_dots=not dots_given,
                    draw_dots=marked,
                    joins=joins if arrowed else set(),
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
            routed_edges[edge.id] = straight_edge(
                edge, fitted, layout_style, text_measurer, offset=offset
            )
    edges = [routed_edges[edge.id] for edge in semantic.edges]
    nets = [routed_nets[net.id] for net in semantic.nets]
    edges, nets = place_captions(
        edges,
        nets,
        solids=(
            *(node.bounds for node in fitted.nodes),
            *(
                rect
                for group in fitted.groups
                if group.measured.spec.role not in TRANSPARENT_ROLES
                for rect in (title_rect(group, layout_style),)
                if rect is not None
            ),
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


SIDE_TRIALS = 8
"""Most end sides tried, per figure, to take a crossing out."""

CROWDING_WEIGHT = 3
"""How many crossings one pair of lines drawn too close counts as, in a trial."""

LOOP_TRIALS = 4
"""Most two-ended loop trials, per figure, after the single-end ones."""

PIN_ORDER_TRIALS = 12
"""Most pin orders tried, per figure, to take a crossing out."""


def _reorder_crossing_pins(
    attempt, separated, pins, bundles, wires, orders, members, ends, spacing
):
    """Swap neighbouring pins on the sides crossing routes attach to, while it helps.

    Pins are ordered along a side by where their counterparts sit, which cannot
    tell which way round an obstacle a route will go. Two routes that cross
    near a box usually uncross when their pins there trade places, so each side
    a crossing route attaches to has its neighbouring pins swapped in turn, the
    figure rerouted, and the order kept when the figure crosses less.
    """

    best = _defects(separated(wires), spacing)
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
                defects = _defects(separated(trial[2]), spacing)
                if len(defects) < len(best):
                    overrides[side_key] = swapped
                    pins, bundles, wires, orders = trial
                    best = defects
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return _turn_crossing_ends(
        attempt,
        separated,
        pins,
        bundles,
        wires,
        overrides,
        best,
        members,
        ends,
        spacing,
    )


def _turn_crossing_ends(
    attempt, separated, pins, bundles, wires, overrides, best, members, ends, spacing
):
    """Try the other sides of a crossing edge's ends, while that helps.

    A pin's side is chosen before any route exists, from where the other end
    is. A line that has to come back round -- a loop from a decision back to
    the step it repeats -- then arrives on the side facing its source and cuts
    through everything between. Entering from above or below instead, it can
    go round. So each end of a crossing edge whose side is a default is tried
    on the two sides across from its own, and kept where the figure crosses less.
    """

    sides: dict[int, Side] = {}
    trials = 0
    tried: set[tuple] = set()
    # Which ends may turn -- those whose side is a default, never an authored
    # one -- decided once, since every trial marks the ends it turns as fixed.
    free = {
        index
        for index, end in enumerate(ends)
        if not end.fixed
        # Operators, circles and diamonds take their sides from their own rules
        # (one corner each, arrivals first), which a turned end would contradict.
        and end.node.measured.spec.kind not in POINT_KINDS
        and any(
            port.name == end.reference.port_name and port.auto_side
            for port in end.node.measured.spec.ports
        )
    }
    while best and trials < SIDE_TRIALS:
        involved = {index for pair in best for index in pair}
        # A pin is one candidate: the ends that share it move together, or
        # the tree they form would be split. Pins of lone edges go first --
        # turning a whole tree is the bigger change, and rarely the one needed.
        pins_of: dict[tuple, list[int]] = {}
        size_of: dict[tuple, int] = {}
        for index in sorted(involved):
            for member in bundles[index].members:
                if not isinstance(members[member].spec, EdgeSpec):
                    continue
                for end_index in members[member].ends:
                    if end_index not in free or end_index in sides:
                        continue
                    key = ends[end_index].group
                    pins_of.setdefault(key, []).append(end_index)
                    size_of[key] = len(bundles[index].members)
        candidates = sorted(pins_of, key=lambda key: (size_of[key], str(key)))
        improved = False
        for key in candidates:
            group = pins_of[key]
            current = key[2]
            for side in (turn for turn in Side if turn.horizontal != current.horizontal):
                if (key, side) in tried or trials >= SIDE_TRIALS:
                    continue
                tried.add((key, side))
                trials += 1
                chosen = {**sides, **dict.fromkeys(group, side)}
                trial = attempt(overrides, chosen)
                defects = _defects(separated(trial[2]), spacing)
                if len(defects) < len(best):
                    sides = chosen
                    pins, bundles, wires, _ = trial
                    best = defects
                    improved = True
                    break
            if improved:
                break
        if not improved:
            improved, trials = _try_loops(
                attempt,
                separated,
                overrides,
                bundles,
                members,
                ends,
                free,
                sides,
                tried,
                trials,
                spacing,
                best,
            )
            if improved is None:
                break
            sides, (pins, bundles, wires), best = improved
    if trials:
        # Every trial re-plans the ends in place; plan once more with the sides
        # that were kept, so the ends agree with the pins returned.
        pins, bundles, wires, _ = attempt(overrides, sides)
    return pins, bundles, wires


def _try_loops(
    attempt, separated, overrides, bundles, members, ends, free, sides, tried, trials, spacing, best
):
    """Both ends of a defective edge on one side: the edge becomes a C round the rest.

    A feedback loop -- a decision back to the step it repeats -- is drawn out of
    the top of one and into the top of the other, over everything between;
    turning one end at a time never finds that, because half a loop is worse
    than none. Each defective edge is tried with both ends on each side across
    from the line joining them.
    """

    involved = {index for pair in best for index in pair}
    for index in sorted(involved):
        for member in bundles[index].members:
            spec = members[member].spec
            if not isinstance(spec, EdgeSpec):
                continue
            first, second = members[member].ends
            if first not in free or second not in free:
                continue
            here, there = ends[first].node.bounds.center, ends[second].node.bounds.center
            across = abs(there.x - here.x) >= abs(there.y - here.y)
            for side in (Side.NORTH, Side.SOUTH) if across else (Side.WEST, Side.EAST):
                key = (first, second, side)
                if key in tried or trials >= SIDE_TRIALS + LOOP_TRIALS:
                    continue
                tried.add(key)
                trials += 1
                chosen = {**sides, first: side, second: side}
                trial = attempt(overrides, chosen)
                defects = _defects(separated(trial[2]), spacing)
                if len(defects) < len(best):
                    return (chosen, trial[:3], defects), trials
    return None, trials


def _orthogonal(wire: Wire) -> bool:
    """Whether every piece of ``wire`` runs horizontally or vertically."""

    return all(
        abs(start.x - end.x) < 1e-6 or abs(start.y - end.y) < 1e-6
        for path in wire.paths
        for start, end in itertools.pairwise(path)
    )


def _defects(wires: list[Wire], spacing: float) -> list[tuple[int, int]]:
    """What a trial is judged by: pairs of wires that cross or run too close.

    A pair drawn closer than a lane is listed ``CROWDING_WEIGHT`` times: lint
    calls it an error and a crossing a warning, so no trial may trade one
    crossing for a pair of lines a hair apart.
    """

    runs = [_straight_runs(wire) for wire in wires]
    pairs = []
    for first, second in itertools.combinations(range(len(wires)), 2):
        crowded = any(
            _too_close(a, b, c, d, spacing) for a, b in runs[first] for c, d in runs[second]
        )
        crossed = crowded or any(
            _perpendicular_cross(a, b, c, d) for a, b in runs[first] for c, d in runs[second]
        )
        if crowded:
            pairs.extend([(first, second)] * CROWDING_WEIGHT)
        elif crossed:
            pairs.append((first, second))
    return pairs


def _too_close(a: Point, b: Point, c: Point, d: Point, spacing: float) -> bool:
    """Parallel runs that overlap along their length closer than ``spacing``."""

    if abs(a.y - b.y) < 1e-9 and abs(c.y - d.y) < 1e-9:
        low, high = sorted((a.x, b.x))
        other_low, other_high = sorted((c.x, d.x))
        overlap = min(high, other_high) - max(low, other_low)
        return overlap > 1e-6 and abs(a.y - c.y) + 1e-6 < spacing
    if abs(a.x - b.x) < 1e-9 and abs(c.x - d.x) < 1e-9:
        low, high = sorted((a.y, b.y))
        other_low, other_high = sorted((c.y, d.y))
        overlap = min(high, other_high) - max(low, other_low)
        return overlap > 1e-6 and abs(a.x - c.x) + 1e-6 < spacing
    return False


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
    if not any(point_key(p) == point_key(q) for p in (a, b) for q in (c, d)):
        return None
    points = sorted((a, b, c, d), key=lambda point: point.x if horizontal else point.y)
    return points[0], points[-1]


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


# -- the scene: zones, grids, growing trees -----------------------------------------------


class _Scene:
    """Everything routing needs to know about the fitted figure, computed once."""

    def __init__(self, fitted: FittedFigure, style: LayoutStyle, measurer: TextMeasurer) -> None:
        self.fitted = fitted
        self.style = style
        self.measurer = measurer
        self.parents = parent_map(fitted.measured.semantic.groups)
        self.solid = tuple(
            node for node in fitted.nodes if node.measured.spec.kind not in TRANSPARENT_KINDS
        )
        self.containers = tuple(
            group for group in fitted.groups if group.measured.spec.role not in TRANSPARENT_ROLES
        )
        self.titles = tuple(title_rect(group, style) for group in self.containers)
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

    def _zones(self, pins: list[Pin]) -> tuple[Zone, ...]:
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
        pins: list[Pin],
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
            region = Rect.union(Rect.from_points(pin.point, pin.escape) for pin in pins)
            refused = _refused(lean, region, self.canvas.inflated(1000.0))
            zones = (*zones, Zone(refused, OFF_SIDE_COST))
            if lean in {Side.EAST, Side.WEST}:
                xs.extend((refused.left, refused.right))
            else:
                ys.extend((refused.top, refused.bottom))
        return Grid(xs, ys, zones, boundary=boundary, outside_cost=OUTSIDE_COST)

    def grow(
        self,
        bundle: Bundle,
        members: list[Member],
        ends: list[End],
        pins: dict[tuple[str, str, Side, bool], Pin],
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
        wire = Wire(bundle.key, paths, terminals, caption=self._caption(bundle, members))
        for member_index in bundle.members:
            spec = members[member_index].spec
            if isinstance(spec, NetSpec):
                count = len(spec.sources)
                sources = [pins[ends[end].group] for end in members[member_index].ends[:count]]
                targets = [
                    pins[ends[end].group] for end in members[member_index].ends[len(spec.sources) :]
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
                        sources,
                        key=lambda pin: (
                            -abs(
                                (pin.point.y - targets[0].point.y)
                                if targets[0].side in {Side.EAST, Side.WEST}
                                else (pin.point.x - targets[0].point.x)
                            )
                        ),
                    ).point
                # A captioned net hands its run to the caption: the joint goes to
                # the far end of its corridor unless the author placed it.
                wire.rail_at = (
                    spec.rail_at if spec.rail_at is not None else (1.0 if spec.label else None)
                )
                wire.rail_side = spec.rail_hint
        return wire

    def _caption(self, bundle: Bundle, members: list[Member]) -> CaptionRoom | None:
        """The room a lone captioned edge's caption needs beside its run: see ``Wire``."""

        if len(bundle.members) != 1:
            return None
        edge = members[bundle.members[0]].spec
        if not isinstance(edge, EdgeSpec) or not edge.label:
            return None
        metrics = self.measurer.measure(edge.label)
        # The caption's far edge, then clearance and half a stroke before the
        # next line may pass.
        margin = self.style.caption_clearance.points + self.style.connector_width.points / 2.0
        return CaptionRoom(
            above=caption_rise(metrics, self.style) + metrics.baseline + margin,
            width=metrics.width,
            beside=caption_reach(metrics, self.style) + metrics.width + margin,
            height=metrics.height,
        )

    def _forced_route(self, edge: EdgeSpec, source: Pin, target: Pin, bend: float) -> Wire:

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


def _lean(bundle: Bundle, members: list[Member]) -> Side | None:
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
