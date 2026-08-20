"""Choose which side a defaulted attachment port leaves from.

A component's port table has to name a side for every port, and the grammar can
only name the common one: values enter west and leave east. Figures are not all
read that way. A spine of residual blocks reads downward, a readout row hangs
under its trunk, a recycle loop climbs a margin -- and every one of those used
to cost the author a hand-written ``PortSpec`` table per node, restating
offsets and adaptivity that were already right just to move a side.

So a port whose side is a *default* (``PortSpec.auto_side``) picks its side here,
once bounds are known and before anything adapts or routes: the side whose
outward normal points at whatever the port is wired to. An authored ``PortSpec``
is pinned -- writing the side down is the choice -- and so is a port named by an
edge that already carries a ``depart``/``arrive`` hint.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from math import hypot

from flexo.components import TRANSPARENT_KINDS, TRANSPARENT_ROLES
from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Point, Rect, Side
from flexo.hierarchy import ancestors, parent_map
from flexo.ir.fitted import FittedGroup, FittedNode, ResolvedPort
from flexo.ir.semantic import FigureSpec, PortRef, PortSpec

_SIDES = (Side.NORTH, Side.EAST, Side.SOUTH, Side.WEST)

_NORMALS = {
    Side.NORTH: Point(0.0, -1.0),
    Side.SOUTH: Point(0.0, 1.0),
    Side.WEST: Point(-1.0, 0.0),
    Side.EAST: Point(1.0, 0.0),
}

_DECISIVE_MARGIN = 0.25
"""How much better than its default a side has to score before a port moves.

The score of a side is how squarely it faces the counterparts the port serves,
between -1 and 1, so this margin is roughly "the dominant axis has to be about
twice the other one". A near-diagonal relationship names no side: it would flip
on a few points of layout drift, and flipping a port is a much louder change
than the fraction of a bend it would save. Below the margin the component
grammar's own side stands.
"""

_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class _Vote:
    """One connection's claim on one port: which way it leaves, and how far it goes."""

    direction: Point
    reach: float
    inbound: bool


def choose_port_sides(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...] = (),
) -> tuple[tuple[FittedNode, ...], tuple[Diagnostic, ...]]:
    """Re-side defaulted ports toward what they are wired to, and say when unsure.

    Both the fitted port positions and the node's own port specs are rewritten,
    so everything downstream -- adaptation, routing, lint, paint -- reads one
    side per port. The authored ``FigureSpec`` is untouched: a figure serializes
    as it was written, and re-compiles to the same picture.
    """

    votes = _incident_votes(figure, nodes)
    pins = _hint_pins(figure)
    if not votes and not pins:
        return nodes, ()
    margins = _margins(figure, nodes, groups)
    result: list[FittedNode] = []
    diagnostics: list[Diagnostic] = []
    for node in nodes:
        specs = node.measured.spec.ports
        if not any(port.auto_side for port in specs):
            result.append(node)
            continue
        chosen: dict[str, Side] = {}
        claims: dict[str, tuple[_Vote, ...]] = {}
        for port in specs:
            if not port.auto_side:
                continue
            key = (node.measured.spec.id, port.name)
            pin = pins.get(key)
            if pin is not None:
                chosen[port.name] = pin
                continue
            claims[port.name] = votes.get(key, ())
            if not claims[port.name]:
                continue
            side = _best_side(port.side, claims[port.name])
            chosen[port.name] = side
            if _conflicted(side, claims[port.name]):
                diagnostics.append(_conflict_diagnostic(node, port, side))
        _separate_opposing(chosen, claims, margins.get(node.measured.spec.id))
        if not chosen:
            result.append(node)
            continue
        result.append(_resided(node, chosen))
    return tuple(result), tuple(diagnostics)


def _separate_opposing(
    chosen: dict[str, Side],
    claims: dict[str, tuple[_Vote, ...]],
    margins: dict[Side, float] | None,
) -> None:
    """Move the long haul off a side that would carry ink both ways.

    A recycle loop asks one block for two sides at once: the spine leaves for the
    block below, and the loop comes back from far downstream -- and the counterpart
    of both sits south, so both ports land there. The router then draws the return
    run alongside the outgoing one, a hair apart, which reads as a doubled line
    rather than as a loop.

    The two claims are not equal, though. The short one is an adjacency: it *is*
    the straight run, and moving it would bend the figure's spine. The long one
    already has to travel, and travelling means a margin, so it gives way to
    whichever side of the node has more clear space beside it -- exactly the lane
    an author would have sent it down by hand.
    """

    for side in tuple(chosen.values()):
        sharing = tuple(name for name, value in chosen.items() if value is side)
        if len(sharing) < 2:
            continue
        roles = {name: _role(claims.get(name, ())) for name in sharing}
        if True not in roles.values() or False not in roles.values():
            # Ink all one way is a fan, not a doubled line: those ports pack.
            continue
        loser = max(sharing, key=lambda name: (_reach(claims.get(name, ())), name))
        if roles[loser] is None:
            continue
        chosen[loser] = _sidestep(side, claims.get(loser, ()), margins)


def _role(votes: tuple[_Vote, ...]) -> bool | None:
    """``True`` for a port only ever entered, ``False`` for one only ever left."""

    if not votes:
        return None
    directions = {vote.inbound for vote in votes}
    return directions.pop() if len(directions) == 1 else None


def _reach(votes: tuple[_Vote, ...]) -> float:
    return max((vote.reach for vote in votes), default=0.0)


def _sidestep(
    side: Side,
    votes: tuple[_Vote, ...],
    margins: dict[Side, float] | None,
) -> Side:
    """The better of the two sides perpendicular to ``side`` for a displaced port.

    "Better" is the wider margin between this component and whatever stands next
    to it, because that margin is where the run is going to travel; where the two
    margins match, the port still leans the way its counterpart lies.
    """

    options = (
        (Side.WEST, Side.EAST) if side in {Side.NORTH, Side.SOUTH} else (Side.NORTH, Side.SOUTH)
    )
    return max(
        options,
        key=lambda option: (
            0.0 if margins is None else margins[option],
            _score(option, votes),
        ),
    )


def _margins(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...],
) -> dict[str, dict[Side, float]]:
    """Clear space beside every component, per side, out to the nearest body.

    Only what paints counts: a spacer holding a lane open, or a layout group with
    no boundary, is exactly the free space this measures rather than a wall in it.
    """

    parents = parent_map(figure.groups)
    obstacles = tuple(
        (node.measured.spec.id, node.bounds)
        for node in nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    ) + tuple(
        (group.measured.spec.id, group.bounds)
        for group in groups
        if group.measured.spec.role not in TRANSPARENT_ROLES
    )
    canvas = next(
        (group.bounds for group in groups if group.measured.spec.id == figure.root),
        _canvas_union(tuple(bounds for _, bounds in obstacles)),
    )
    return {
        node.measured.spec.id: _node_margins(
            node.bounds,
            canvas,
            tuple(
                bounds
                for entity_id, bounds in obstacles
                if entity_id != node.measured.spec.id
                and entity_id not in ancestors(parents, node.measured.spec.id)
            ),
        )
        for node in nodes
    }


def _node_margins(
    bounds: Rect,
    canvas: Rect,
    obstacles: tuple[Rect, ...],
) -> dict[Side, float]:
    horizontal = tuple(
        other for other in obstacles if other.top < bounds.bottom and bounds.top < other.bottom
    )
    vertical = tuple(
        other for other in obstacles if other.left < bounds.right and bounds.left < other.right
    )
    return {
        Side.WEST: min(
            (bounds.left - other.right for other in horizontal if other.right <= bounds.left),
            default=bounds.left - canvas.left,
        ),
        Side.EAST: min(
            (other.left - bounds.right for other in horizontal if other.left >= bounds.right),
            default=canvas.right - bounds.right,
        ),
        Side.NORTH: min(
            (bounds.top - other.bottom for other in vertical if other.bottom <= bounds.top),
            default=bounds.top - canvas.top,
        ),
        Side.SOUTH: min(
            (other.top - bounds.bottom for other in vertical if other.top >= bounds.bottom),
            default=canvas.bottom - bounds.bottom,
        ),
    }


def _incident_votes(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
) -> dict[tuple[str, str], tuple[_Vote, ...]]:
    """For every named port, the unit direction its ink leaves in.

    An edge leaves toward its counterpart's node centre. A net leg leaves toward
    the *trunk* instead: a stem never runs to the far port, it runs to the shared
    rail, so five heads spread across a row do not each pull the source port
    their own way -- they are all fed by one trunk, and the whole net votes once
    per port for the direction that trunk runs (see ``_trunk_direction``).

    A connection routed through an authored corridor -- a ``lane`` hint, a rail
    pinned to a boundary -- casts no vote: its ink is going where the author sent
    it, not where its counterpart happens to sit.
    """

    centres = {node.measured.spec.id: node.bounds.center for node in nodes}
    votes: defaultdict[tuple[str, str], list[_Vote]] = defaultdict(list)
    for edge in figure.edges:
        if edge.lane_hint is not None or edge.source.node_id == edge.target.node_id:
            continue
        span = centres[edge.source.node_id].distance_to(centres[edge.target.node_id])
        for near, far, inbound in (
            (edge.source, edge.target, False),
            (edge.target, edge.source, True),
        ):
            direction = _unit(centres[near.node_id], centres[far.node_id])
            if direction is not None:
                votes[(near.node_id, near.port_name)].append(_Vote(direction, span, inbound))
    for net in figure.nets:
        if net.rail_hint is not None:
            continue
        fan_out = net.kind == "fan-out"
        hubs, spokes = (
            (net.sources, net.targets) if fan_out else (net.targets, net.sources)
        )
        trunk = _trunk_direction(centres, hubs[0], spokes)
        if trunk is None:
            continue
        back = Point(-trunk.x, -trunk.y)
        for hub in hubs:
            span = max(centres[hub.node_id].distance_to(centres[ref.node_id]) for ref in spokes)
            votes[(hub.node_id, hub.port_name)].append(_Vote(trunk, span, not fan_out))
        for spoke in spokes:
            span = centres[spoke.node_id].distance_to(centres[hubs[0].node_id])
            votes[(spoke.node_id, spoke.port_name)].append(_Vote(back, span, fan_out))
    return {key: tuple(value) for key, value in votes.items()}


def _trunk_direction(
    centres: dict[str, Point],
    hub: PortRef,
    spokes: tuple[PortRef, ...],
) -> Point | None:
    """Which way a net's trunk leaves its hub, from the spread of its spokes.

    A net is a rail plus stems, and the rail runs along whichever axis its spokes
    are spread over -- a row of readout heads is entered from a rail above them,
    a column of them from a rail beside them. The trunk crosses to that rail
    along the other axis, so it is that axis, and not the direction of any one
    spoke, that says which side of the hub the whole net leaves from.
    """

    origin = centres[hub.node_id]
    points = tuple(centres[spoke.node_id] for spoke in spokes)
    xs = tuple(point.x for point in points)
    ys = tuple(point.y for point in points)
    along_x = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    offset = (
        sum(ys) / len(ys) - origin.y if along_x else sum(xs) / len(xs) - origin.x
    )
    if abs(offset) <= _EPSILON:
        return None
    sign = 1.0 if offset > 0.0 else -1.0
    return Point(0.0, sign) if along_x else Point(sign, 0.0)


def _hint_pins(figure: FigureSpec) -> dict[tuple[str, str], Side]:
    """Sides a connection already named, in the order they overrule each other.

    ``depart``/``arrive`` name a port's side outright, so they go in first and a
    later hint cannot displace them. Then comes ``via``, which names the side a
    route travels on: ink that comes round the west arrives *from* the west, so
    the port it arrives on faces west, and the author who wrote one word about
    the corridor should not also have to write a port table about the arrival.
    That is the entry side only -- the departure keeps its own vote, because a
    route may perfectly well leave east and still be asked to keep west of the
    tower it is crossing to.
    """

    pins: dict[tuple[str, str], Side] = {}
    for edge in figure.edges:
        for reference, side in ((edge.source, edge.depart), (edge.target, edge.arrive)):
            if side is not None:
                pins.setdefault((reference.node_id, reference.port_name), side)
    for edge in figure.edges:
        if edge.via is not None:
            pins.setdefault((edge.target.node_id, edge.target.port_name), edge.via)
    for net in figure.nets:
        if net.via is None:
            continue
        for reference in net.targets:
            pins.setdefault((reference.node_id, reference.port_name), net.via)
    return pins


def _unit(origin: Point, destination: Point) -> Point | None:
    dx = destination.x - origin.x
    dy = destination.y - origin.y
    length = hypot(dx, dy)
    if length <= _EPSILON:
        return None
    return Point(dx / length, dy / length)


def _canvas_union(bounds: tuple[Rect, ...]) -> Rect:
    """The bounding box of everything that paints, or the origin if nothing does."""

    return Rect.union(bounds) if bounds else Rect(0.0, 0.0, 0.0, 0.0)


def _score(side: Side, votes: tuple[_Vote, ...]) -> float:
    """Mean agreement between a side's outward normal and the ink it would carry."""

    if not votes:
        return 0.0
    normal = _NORMALS[side]
    return sum(
        vote.direction.x * normal.x + vote.direction.y * normal.y for vote in votes
    ) / len(votes)


def _best_side(default: Side, votes: tuple[_Vote, ...]) -> Side:
    """The side facing these counterparts, or the default when they do not agree."""

    scores = {side: _score(side, votes) for side in _SIDES}
    top = max(scores.values())
    tied = tuple(side for side in _SIDES if scores[side] >= top - _EPSILON)
    best = tied[0] if len(tied) == 1 else _dominant_axis_side(tied, votes)
    return best if scores[best] - scores[default] >= _DECISIVE_MARGIN else default


def _dominant_axis_side(tied: tuple[Side, ...], votes: tuple[_Vote, ...]) -> Side:
    """Break a tie on the dominant axis of the summed centre-to-centre delta."""

    total = Point(
        sum(vote.direction.x for vote in votes),
        sum(vote.direction.y for vote in votes),
    )
    horizontal = abs(total.x) >= abs(total.y)
    preferred = (
        (Side.EAST if total.x >= 0.0 else Side.WEST)
        if horizontal
        else (Side.SOUTH if total.y >= 0.0 else Side.NORTH)
    )
    return preferred if preferred in tied else tied[0]


def _conflicted(side: Side, votes: tuple[_Vote, ...]) -> bool:
    """True when one port is asked to face two ways at once."""

    normal = _NORMALS[side]
    return len(votes) > 1 and any(
        vote.direction.x * normal.x + vote.direction.y * normal.y < -_EPSILON for vote in votes
    )

def _conflict_diagnostic(node: FittedNode, port: PortSpec, side: Side) -> Diagnostic:
    return Diagnostic(
        "layout.port.side.conflicted",
        f'Port "{port.name}" serves connections on opposite sides; '
        f"defaulted to {side.value}.",
        Severity.INFO,
        entity_id=node.measured.spec.id,
        hint=(
            f'Give "{node.measured.spec.id}" explicit ports, or split the traffic '
            "across two ports, to say which side each connection uses."
        ),
    )


def _resided(node: FittedNode, chosen: dict[str, Side]) -> FittedNode:
    """Rewrite one node's port sides, and the positions that follow from them."""

    specs = tuple(
        replace(port, side=chosen[port.name]) if port.name in chosen else port
        for port in node.measured.spec.ports
    )
    return replace(
        node,
        measured=replace(
            node.measured,
            spec=replace(node.measured.spec, ports=specs),
        ),
        ports=tuple(
            ResolvedPort(port.name, port.side, node.bounds.point_on(port.side, port.offset))
            for port in specs
        ),
    )
