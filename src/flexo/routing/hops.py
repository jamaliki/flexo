"""Where two connector shafts cross, and which of them bridges the other (R34).

A crossing the topology forces is not a defect to warn about; it is a thing to
*draw*, the way circuit diagrams have drawn it for decades -- one wire hops the
other with a small semicircular bridge. This module owns the geometry both ends
of that answer need: the router asks it which crossings exist and who hops, and
lint asks it the same question with the same arithmetic, so the two can never
disagree about what is on the page.

The hopper rule, in one line: **the route drawn later hops the one already on
the page**, and where the later route's own ink cannot take the arc -- a bend or
another hop too close -- the earlier one takes it instead; where neither can,
nobody hops and the crossing keeps its warning.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from itertools import combinations, pairwise
from math import hypot

from flexo.geometry import Point, Segment, segments
from flexo.ir.fitted import FittedFigure
from flexo.ir.routed import Hop, RoutedFigure
from flexo.ir.semantic import EdgeSpec
from flexo.style import LayoutStyle

_TOLERANCE = 1e-7
"""How near a run a point may sit and still count as lying on it."""


def routing_order(fitted: FittedFigure, edges: tuple[EdgeSpec, ...]) -> tuple[EdgeSpec, ...]:
    """Long haul first: the connectors with the least room to spare pick lanes first."""

    def span(edge: EdgeSpec) -> float:
        source = fitted.node(edge.source.node_id).port(edge.source.port_name).position
        target = fitted.node(edge.target.node_id).port(edge.target.port_name).position
        return abs(target.x - source.x) + abs(target.y - source.y)

    return tuple(sorted(edges, key=lambda edge: (-span(edge), edge.id)))


def routing_rank(routed: RoutedFigure) -> dict[str, int]:
    """When each route was drawn: nets first, then edges in ``routing_order``.

    The hopper rule reads exactly this. Rank comes from the *routing* order
    rather than from the final geometry, so nudging two runs past each other
    never swaps who hops whom.
    """

    semantic = routed.fitted.measured.semantic
    order = [net.id for net in semantic.nets]
    order += [edge.id for edge in routing_order(routed.fitted, semantic.edges)]
    return {entity_id: index for index, entity_id in enumerate(order)}


def figure_routes(routed: RoutedFigure) -> tuple[tuple[str, tuple[Point, ...]], ...]:
    """Every routed centerline in the figure, each tagged with its entity id.

    One net contributes several: its rail and one centerline per stem. They all
    answer to the net's id, which is what lets a caller skip a net crossing
    itself.
    """

    routes = [(edge.spec.id, edge.centerline) for edge in routed.edges]
    for net in routed.nets:
        routes.append((net.spec.id, net.rail))
        routes.extend((net.spec.id, stem.centerline) for stem in net.source_stems)
        routes.extend((net.spec.id, stem.centerline) for stem in net.target_stems)
    return tuple(routes)


def painted_ink(routed: RoutedFigure) -> dict[str, tuple[tuple[Point, ...], ...]]:
    """The polylines each entity actually paints, by id: shafts, rails, stems."""

    ink: dict[str, tuple[tuple[Point, ...], ...]] = {
        edge.spec.id: (edge.shaft,) for edge in routed.edges
    }
    for net in routed.nets:
        ink[net.spec.id] = (
            net.rail,
            *(stem.shaft for stem in net.source_stems + net.target_stems),
        )
    return ink


def segment_crossing(first: Segment, second: Segment) -> Point | None:
    """Where two orthogonal segments cross transversally, if they do.

    Transversal only: two parallel runs that overlap share ink but have no
    crossing *point*, so there is nothing to bridge and the caller keeps its
    warning. Endpoints are excluded at both ends -- a corner that lands on
    another run is a junction, not a crossing.
    """

    if first.horizontal == second.horizontal:
        return None
    horizontal, vertical = (first, second) if first.horizontal else (second, first)
    x_low, x_high = sorted((horizontal.start.x, horizontal.end.x))
    y_low, y_high = sorted((vertical.start.y, vertical.end.y))
    if (
        x_low + _TOLERANCE < vertical.start.x < x_high - _TOLERANCE
        and y_low + _TOLERANCE < horizontal.start.y < y_high - _TOLERANCE
    ):
        return Point(vertical.start.x, horizontal.start.y)
    return None


def crossing_points(
    first: tuple[Point, ...],
    second: tuple[Point, ...],
) -> tuple[Point, ...]:
    """Every point where two orthogonal polylines cross transversally."""

    found: list[Point] = []
    for one in segments(first):
        for other in segments(second):
            point = segment_crossing(one, other)
            if point is not None:
                found.append(point)
    return tuple(dict.fromkeys(found))


def fillet_lengths(points: tuple[Point, ...], radius: float) -> tuple[float, ...]:
    """How much of each run every corner spends on its elbow fillet.

    The same arithmetic ``rounded_polyline_path`` fillets with, read out per
    vertex: ends spend nothing, a corner spends ``radius`` unless one of its two
    runs is too short to give up that much at both ends. A hop has to fit in
    what is left over, and emit has to insert the arc into exactly the stretch
    this leaves straight, so both read it from here.
    """

    if len(points) < 2:
        return (0.0,) * len(points)
    result = [0.0] * len(points)
    if radius <= 0.0:
        return tuple(result)
    for index in range(1, len(points) - 1):
        previous, corner, following = points[index - 1], points[index], points[index + 1]
        incoming = hypot(corner.x - previous.x, corner.y - previous.y)
        outgoing = hypot(following.x - corner.x, following.y - corner.y)
        cross = (corner.x - previous.x) * (following.y - corner.y) - (
            corner.y - previous.y
        ) * (following.x - corner.x)
        if incoming == 0.0 or outgoing == 0.0 or abs(cross) < 1e-9:
            continue
        result[index] = min(radius, incoming / 2.0, outgoing / 2.0)
    return tuple(result)


def straight_runs(
    points: tuple[Point, ...],
    elbow: float,
) -> tuple[tuple[Point, Point], ...]:
    """Each run of a polyline, trimmed by the fillets its two corners take.

    What is left is the genuinely straight ink of that run: the stretch an arc
    may be inserted into without disturbing an elbow, and the only stretch a
    bridge belongs on. A bump growing out of a curve reads as a knot rather
    than as one wire passing over another -- which is why a hop keeps clear of
    the fillet instead of shortening it to make room.
    """

    fillets = fillet_lengths(points, elbow)
    result = []
    for index, (start, end) in enumerate(pairwise(points)):
        length = start.distance_to(end)
        head, tail = fillets[index], fillets[index + 1]
        if length <= 0.0 or head + tail >= length:
            continue
        unit = Point((end.x - start.x) / length, (end.y - start.y) / length)
        result.append(
            (
                Point(start.x + unit.x * head, start.y + unit.y * head),
                Point(end.x - unit.x * tail, end.y - unit.y * tail),
            )
        )
    return tuple(result)


def lies_on(point: Point, start: Point, end: Point) -> bool:
    """Whether ``point`` sits on the closed orthogonal stretch ``start``-``end``."""

    if abs(start.y - end.y) < _TOLERANCE:
        low, high = sorted((start.x, end.x))
        on_axis = abs(point.y - start.y) < _TOLERANCE
        return on_axis and low - _TOLERANCE <= point.x <= high + _TOLERANCE
    low, high = sorted((start.y, end.y))
    on_axis = abs(point.x - start.x) < _TOLERANCE
    return on_axis and low - _TOLERANCE <= point.y <= high + _TOLERANCE


def ink_covers(polylines: tuple[tuple[Point, ...], ...], point: Point) -> bool:
    """Whether any of these painted polylines actually passes through ``point``.

    A crossing of two centerlines near an endpoint may be pure arithmetic: the
    shaft there was trimmed away for the arrowhead and its standoff, so no ink
    of the crossed route reaches the point and there is nothing to hop over.
    """

    return any(
        lies_on(point, segment.start, segment.end)
        for polyline in polylines
        for segment in segments(polyline)
    )


def hop_site(
    shaft: tuple[Point, ...],
    point: Point,
    *,
    radius: float,
    elbow: float,
    taken: tuple[Point, ...] = (),
) -> bool:
    """Whether this shaft can carry a bridge arc of ``radius`` at ``point``.

    Three ways it cannot, and all three degrade the same way -- no hop, and the
    crossing keeps its warning rather than the figure keeping broken ink:

    * the point is not on this shaft's straight ink at all, because the shaft
      there was trimmed away for the arrowhead, or because it falls inside an
      elbow fillet;
    * the arc would not fit between the fillets of its run -- the "crossing
      within an arc radius of a bend" case, read against the ink the elbow
      actually leaves straight rather than against the bend's vertex;
    * another hop already sits within two radii, so the two arcs would run into
      each other.
    """

    if radius <= 0.0:
        return False
    if any(other.distance_to(point) < 2.0 * radius - _TOLERANCE for other in taken):
        return False
    for start, end in straight_runs(shaft, elbow):
        if not lies_on(point, start, end):
            continue
        return (
            start.distance_to(point) + _TOLERANCE >= radius
            and end.distance_to(point) + _TOLERANCE >= radius
        )
    return False


def hopped_by(
    routed: RoutedFigure,
    first_id: str,
    second_id: str,
    point: Point,
) -> str | None:
    """Which of these two entities recorded a hop over the other at ``point``."""

    for edge in routed.edges:
        entity_id = edge.spec.id
        if entity_id not in {first_id, second_id}:
            continue
        other = second_id if entity_id == first_id else first_id
        for hop in edge.hops:
            if hop.over == other and hop.point.distance_to(point) < _TOLERANCE:
                return entity_id
    return None


def assign_hops(routed: RoutedFigure, style: LayoutStyle) -> RoutedFigure:
    """Record a bridge arc on the hopping shaft of every crossing that can take one.

    Called once, on final geometry: hops are a property of where the ink ended
    up, so they are decided after nudging rather than during the search.
    """

    if not style.connector_hops:
        return routed
    radius = style.hop_radius.points
    elbow = style.elbow_radius.points
    routes = figure_routes(routed)
    rank = routing_rank(routed)
    ink = painted_ink(routed)
    shafts = {edge.spec.id: edge.shaft for edge in routed.edges}
    accepted: defaultdict[str, list[Hop]] = defaultdict(list)
    for (first_id, first_route), (second_id, second_route) in combinations(routes, 2):
        if first_id == second_id:
            continue
        for point in crossing_points(first_route, second_route):
            # Later-routed first, then the other: the rule, and its fallback.
            for hopper in sorted(
                (first_id, second_id), key=lambda item: (-rank.get(item, -1), item)
            ):
                crossed = second_id if hopper == first_id else first_id
                shaft = shafts.get(hopper)
                if shaft is None or not ink_covers(ink[crossed], point):
                    continue
                taken = tuple(hop.point for hop in accepted[hopper])
                if hop_site(shaft, point, radius=radius, elbow=elbow, taken=taken):
                    accepted[hopper].append(Hop(point, crossed))
                    break
    hops = {entity_id: tuple(found) for entity_id, found in accepted.items() if found}
    if not hops:
        return routed
    return replace(
        routed,
        edges=tuple(
            replace(edge, hops=hops[edge.spec.id]) if edge.spec.id in hops else edge
            for edge in routed.edges
        ),
    )
