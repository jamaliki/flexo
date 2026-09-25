"""From routed wires back to the routed IR: ``RoutedEdge``s and ``RoutedNet``s.

A bundle's routed tree is read as a graph (``WireGraph``) and cut into the
edges and nets it carries, each with its shaft, caption position and
diagnostics; the joins where its lines meet get their marks -- a plain T, an
arrowhead into the joined line, or a dot. Straight edges, which skip the grid,
are drawn here too: one segment from outline to outline.
"""

from __future__ import annotations

import itertools
from collections import defaultdict, deque
from dataclasses import replace

from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Point, Rect, Side, segments
from flexo.ir.fitted import FittedFigure, FittedNode
from flexo.ir.routed import RoutedEdge, RoutedNet, RoutedStem
from flexo.ir.semantic import EdgeSpec, NetSpec
from flexo.routing.hints import SideBias, via_diagnostics
from flexo.routing.ink import (
    edge_label_position,
    edge_shaft,
    rail_label_position,
    shorten_end,
    shorten_start,
)
from flexo.routing.pins import Bundle, End, Member, Pin
from flexo.routing.search import simplify
from flexo.routing.separate import Wire
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer


def point_key(point: Point) -> tuple[float, float]:
    return (round(point.x, 5), round(point.y, 5))


class WireGraph:
    """A routed wire as an undirected graph, split wherever a vertex lies on a segment."""

    def __init__(self, wire: Wire) -> None:
        self.points: dict[tuple[float, float], Point] = {}
        for path in wire.paths:
            for point in path:
                self.points.setdefault(point_key(point), point)
        self.adjacency: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
        for path in wire.paths:
            for start, end in itertools.pairwise(path):
                if point_key(start) == point_key(end):
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
                    if point_key(first) != point_key(second):
                        self.adjacency[point_key(first)].add(point_key(second))
                        self.adjacency[point_key(second)].add(point_key(first))

    def path(self, start: Point, end: Point) -> tuple[Point, ...]:
        """The tree path between two of its vertices."""

        origin, goal = point_key(start), point_key(end)
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

        distance = {point_key(hub): 0}
        queue = deque([point_key(hub)])
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


def _joint_of(bundle: Bundle, members: list[Member]) -> str:
    """The ``joint`` a bundle's nets ask for: ``"arrow"``, ``"dot"``, or ``"auto"``."""

    joints = {
        members[index].spec.joint  # type: ignore[union-attr]
        for index in bundle.members
        if members[index].kind == "net"
    }
    return "arrow" if "arrow" in joints else "dot" if "dot" in joints else "auto"


def dots_at_joins(
    bundle: Bundle,
    members: list[Member],
    pins: dict[tuple[str, str, Side, bool], Pin],
    style: LayoutStyle,
) -> bool:
    """Whether this bundle's joins get dots: its net asks, or the conventions do."""

    joint = _joint_of(bundle, members)
    if joint != "auto":
        return joint == "dot"
    if pins[bundle.hub].arriving:
        return style.conventions.merge == "dot"
    return style.conventions.branch == "dot"


def arrows_at_joins(
    bundle: Bundle,
    members: list[Member],
    pins: dict[tuple[str, str, Side, bool], Pin],
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


def edge_cuts(
    bundle: Bundle,
    members: list[Member],
    ends: list[End],
    pins: dict[tuple[str, str, Side, bool], Pin],
    graph: WireGraph,
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
        chain = [point_key(point) for point in graph.path(source, target)]
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


def _expanded(graph: WireGraph, chain: list[tuple[float, float]]) -> list[tuple[float, float]]:
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


def routed_edge(
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
            position
            for position, point in enumerate(centerline)
            if point_key(point) == point_key(joined_at)
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


def routed_net(
    net: NetSpec,
    graph: WireGraph,
    wire: Wire,
    terminals: list[tuple[End, Pin]],
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
    sources = {point_key(pin.point): end for end, pin in terminals if not end.arriving}
    targets = {point_key(pin.point): end for end, pin in terminals if end.arriving}
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
        source_stems, trunks, marked, dots_removed = _mark_joins(source_stems, trunks, joins, reach)
    order = {reference: index for index, reference in enumerate(net.sources + net.targets)}
    source_stems.sort(key=lambda stem: order[stem.port])
    target_stems.sort(key=lambda stem: order[stem.port])
    trunks.sort(key=lambda line: -sum(segment.length for segment in segments(line)))
    junctions = graph.dots() if all_dots else graph.dots(adjacency)
    junctions = tuple(point for point in junctions if point_key(point) not in dots_removed)
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
        if len(line) >= 2 and (point_key(line[-1]), point_key(line[-2])) in joins:
            removed.add(point_key(line[-1]))
            stems.append(RoutedStem(stem.port, line, shorten_end(stem.shaft, reach), True))
        else:
            stems.append(stem)
    plain: list[tuple[Point, ...]] = []
    marked: list[tuple[Point, ...]] = []
    for line in trunks:
        if len(line) >= 2 and (point_key(line[0]), point_key(line[1])) in joins:
            line = line[::-1]
        if len(line) >= 2 and (point_key(line[-1]), point_key(line[-2])) in joins:
            removed.add(point_key(line[-1]))
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


# -- straight edges -------------------------------------------------------------------


ROUND_KINDS = frozenset({"op", "circle"})
"""Kinds whose outline is the circle inscribed in their box."""


def straight_edge(
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
    return replace(routed_edge(edge, (start, end), style, measurer), straight=True)


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
