"""Side-margin corridors: how wide a margin must be, and which run takes which track.

A run is *margin-bound* when it cannot travel through the gap between two
siblings the way ``flexo.layout.gaps`` provides for, and has to run *beside* the
cells it passes instead, in the margin between a group's content and its own
boundary. Two readings of the same sentence, and a figure meets both:

* **Past a cell** -- the endpoints sit in cells of one group with an occupied
  cell between them along the route axis. The gap is not a way through: the
  cell in the middle is.
* **Into a subtree** (R33 round 14) -- the run enters or leaves a container
  through a *side* port whose side lies across the route axis. Nothing about
  the cells says it is long; the port does. A value dropping from one band into
  the east flank of a block four rows down inside the next band has to travel
  the whole depth of that container's margin to reach the height it attaches
  at, and it shares that margin with every other run doing the same.

One long run fits in the margin every group already has: the router finds it,
and that is the behaviour this module deliberately leaves alone. Two do not.
Both want the same coordinate -- one clearance out from the deepest child -- and
the figure ends up either with two shafts drawn on top of each other or with no
route at all, which is what the see-more suite worked around by hand-building
nested spacer groups. So a *contested* margin is the engine's to size and to
hand out, and this module answers both questions from one walk of the group tree
so the phases that ask can never disagree:

* **Before fit** (``CorridorPlan.padding``) -- a margin that has to hold ``n``
  tracks is padded to ``route_boundary_clearance + arrival_clearance +
  (n - 1) * pitch``: room for the outermost run to sit inside the routing
  boundary, room for the innermost to clear the components -- at the arrival
  clearance, because a run in this corridor turns into a port at either end of
  it -- and one pitch for every step between them. The same arithmetic
  ``flexo.layout.gaps`` reserves a crossed sibling boundary with, read across
  the margin instead of along the axis.
* **During routing** (``track_coordinate``) -- which of those tracks each edge
  takes, in the nesting order proved planar below.

An edge claims at most one margin: the *deepest* container it threads. That
container's margin is the tightest one the run has to fit through, and the runs
sharing it are the runs it can collide with; the wider margins further out are
the same corridor seen from further away, and allocating in both would draw two
bundles a few points apart instead of one.

Authored ``lane=`` hints, waypoints and nets are never touched: an author who
aimed a route has already chosen its corridor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import count

from flexo.components import TRANSPARENT_KINDS, TRANSPARENT_ROLES
from flexo.geometry import Insets, Rect, Side
from flexo.hierarchy import ancestors, lowest_common_group, parent_map
from flexo.ir.fitted import FittedFigure, FittedGroup
from flexo.ir.semantic import EdgeSpec, FigureSpec, GroupSpec, PortRef
from flexo.layout.grid import grid_plan
from flexo.style import LayoutStyle

_DEFAULT_SIDE = (Side.EAST, Side.SOUTH)
"""Where a run with nothing to say about its side goes.

A run leaves and arrives on the route axis -- a plain north-to-south skip down a
column -- and nothing in the semantics names a margin for it. East for a
vertical run and south for a horizontal one is the convention the shipped
figures already read in: the transformer's residual skips bow east, and a row's
bypass drops below. ``_corridor_side`` picks whichever of these the run's own
two transverse sides offers.
"""

_CONTESTED = 2
"""How many tracks a margin must owe before the engine takes it over.

One long run per margin is what the router already does well: the margin the
group has is the corridor and the search finds it. Stepping in below this
threshold would move ink in every figure that routes clean today for no gain,
so the arithmetic is armed only where two runs would otherwise land on the same
coordinate.
"""


def track_pitch(style: LayoutStyle) -> float:
    """Distance between two parallel tracks in one corridor.

    The same number ``nudge`` spaces parallel runs by and ``lint`` reports an
    error below, so a margin reserved at this pitch is a margin the router is
    allowed to fill: reserving less would hand it a gutter it has to refuse.
    """

    return max(style.route_lane_spacing.points, style.port_spacing.points)


def margin_clearance(style: LayoutStyle) -> float:
    """Air between the innermost track of a corridor and the components beside it.

    The *arrival* clearance rather than the plain routing one. A margin run has
    a port at both ends and turns into the second of them straight off the
    track, and the router already holds a target component that far off for the
    arrowhead and its elbow. A corridor built any nearer would be a corridor its
    own runs are not allowed to use.
    """

    return max(style.route_clearance.points, style.arrival_clearance.points)


@dataclass(frozen=True, slots=True)
class Corridor:
    """One long edge's engine-allocated track in a group's side margin."""

    group_id: str
    side: Side
    track: int
    """0 is the innermost track, nearest the components; each step is one pitch out."""
    tracks: int
    """How many tracks this margin holds in all."""


@dataclass(frozen=True, slots=True)
class CorridorPlan:
    """Every contested margin in a figure, and who travels where in it."""

    corridors: Mapping[str, Corridor]
    """Edge ID to its allocated track -- contested margins only."""
    margins: Mapping[tuple[str, Side], int]
    """``(group ID, side)`` to the number of tracks that margin owes."""
    claimants: Mapping[tuple[str, Side], tuple[str, ...]] = field(default_factory=dict)
    """``(group ID, side)`` to the edges travelling it -- contested margins only.

    The corridor is one line shared by all of them, so where that line runs is
    a question about the whole margin rather than about any one run: it has to
    clear everything any of them passes (see ``track_coordinate``).
    """

    def corridor(self, edge_id: str) -> Corridor | None:
        return self.corridors.get(edge_id)

    def reserve(self, group_id: str, style: LayoutStyle) -> Insets:
        """Padding this group's margins need to hold every run that crosses them."""

        pitch = track_pitch(style)
        base = style.route_boundary_clearance.points + margin_clearance(style)
        widths = {
            side: base + (tracks - 1) * pitch
            for (owner, side), tracks in self.margins.items()
            if owner == group_id and tracks >= _CONTESTED
        }
        return Insets(
            widths.get(Side.NORTH, 0.0),
            widths.get(Side.EAST, 0.0),
            widths.get(Side.SOUTH, 0.0),
            widths.get(Side.WEST, 0.0),
        )

    def padding(self, group: GroupSpec, style: LayoutStyle) -> Insets:
        """``group``'s padding, widened where a margin has runs to hold.

        Widened, never narrowed: an author who asked for more air than the
        corridors need keeps it.
        """

        declared = group.layout.resolved_padding(style.group_padding)
        reserve = self.reserve(group.id, style)
        if reserve == _NOTHING:
            return declared
        return Insets(
            max(declared.top, reserve.top),
            max(declared.right, reserve.right),
            max(declared.bottom, reserve.bottom),
            max(declared.left, reserve.left),
        )


_NOTHING = Insets()

EMPTY_PLAN = CorridorPlan({}, {})
"""The plan of a figure with no long edges: what every phase falls back to."""


@dataclass(frozen=True, slots=True)
class _Span:
    """A long edge seen as the stretch of cells its run has to pass.

    ``low`` and ``high`` are cell coordinates along the route axis -- rows for a
    run in a west or east margin, columns for one in a north or south margin.
    Half-integers appear at either end when the run leaves the group entirely:
    ``-0.5`` and ``count - 0.5`` are the near sides of the first and last cell,
    which is as far as the margin goes.
    """

    edge_id: str
    group_id: str
    side: Side
    low: float
    high: float
    depth: int
    """How deeply the claimed container is nested; the deepest claim wins."""

    @property
    def reach(self) -> float:
        return self.high - self.low

    def overlaps(self, other: _Span) -> bool:
        """Whether both runs occupy the margin over a shared stretch of it.

        Cell indices name the *ends* of a run, so two runs meeting at one cell --
        a skip into the block the next skip leaves from -- touch at a point and
        can share a track. A whole cell in common is what makes them parallel.
        """

        return min(self.high, other.high) - max(self.low, other.low) >= 1


def corridor_plan(figure: FigureSpec) -> CorridorPlan:
    """Which side margins this figure contests, and the planar order to fill them."""

    context = _Context(figure)
    claimed: dict[str, _Span] = {}
    for edge in figure.edges:
        for span in _margin_spans(context, edge):
            best = claimed.get(edge.id)
            if best is None or (span.depth, span.reach, span.group_id) > (
                best.depth,
                best.reach,
                best.group_id,
            ):
                claimed[edge.id] = span
    spans: dict[tuple[str, Side], list[_Span]] = {}
    for span in claimed.values():
        spans.setdefault((span.group_id, span.side), []).append(span)
    corridors: dict[str, Corridor] = {}
    margins: dict[tuple[str, Side], int] = {}
    claimants: dict[tuple[str, Side], tuple[str, ...]] = {}
    for (group_id, side), members in spans.items():
        tracks = _assign_tracks(members)
        total = max(tracks.values()) + 1
        margins[(group_id, side)] = total
        if total < _CONTESTED:
            continue
        claimants[(group_id, side)] = tuple(sorted(tracks))
        for edge_id, track in tracks.items():
            corridors[edge_id] = Corridor(group_id, side, track, total)
    return CorridorPlan(corridors, margins, claimants)


class _Context:
    """The one walk of the group tree every claim is read off.

    Cells are indices into a group's ``children``; positions are the
    ``(row, column)`` those children occupy, which is the index itself for a
    linear group and the grid plan for a grid. ``occupied`` drops the cells that
    hold nothing but spacers and lane holders, so a run threading a reserved
    lane is not charged for a cell that was opened for it.
    """

    def __init__(self, figure: FigureSpec) -> None:
        self.figure = figure
        self.groups = {group.id: group for group in figure.groups}
        self.nodes = {node.id: node for node in figure.nodes}
        self.parents = parent_map(figure.groups)
        self.cells = {
            group_id: _cell_index(self.groups, group_id) for group_id in self.groups
        }
        self.positions = {
            group_id: _cell_positions(self.groups, group_id) for group_id in self.groups
        }
        self.occupied = {
            group_id: self._occupied(group_id) for group_id in self.groups
        }
        self.depth = {
            group_id: len(ancestors(self.parents, group_id)) for group_id in self.groups
        }

    def _occupied(self, group_id: str) -> frozenset[tuple[int, int]]:
        positions = self.positions[group_id]
        if not positions:
            return frozenset()
        solid: set[tuple[int, int]] = set()
        for node_id, cell in self.cells[group_id].items():
            node = self.nodes.get(node_id)
            if node is not None and node.kind not in TRANSPARENT_KINDS:
                solid.add(positions[cell])
        return frozenset(solid)

    def container(self, node_id: str, owner: str) -> str | None:
        """The innermost drawn container holding ``node_id`` strictly inside ``owner``."""

        for group_id in ancestors(self.parents, node_id):
            if group_id == owner:
                return None
            if self.groups[group_id].role not in TRANSPARENT_ROLES:
                return group_id
        return None

    def position(self, group_id: str, node_id: str, vertical: bool) -> float | None:
        cell = self.cells[group_id].get(node_id)
        positions = self.positions[group_id]
        if cell is None or not positions:
            return None
        row, column = positions[cell]
        return float(row if vertical else column)

    def extent(self, group_id: str, vertical: bool) -> float:
        positions = self.positions[group_id]
        return float(max(row if vertical else column for row, column in positions))

    def blocked(self, group_id: str, low: float, high: float, lane: int, vertical: bool) -> bool:
        """Whether an occupied cell of ``lane`` stands between ``low`` and ``high``."""

        return any(
            (step, lane) in self.occupied[group_id]
            if vertical
            else (lane, step) in self.occupied[group_id]
            for step in range(int(low) + 1, int(high) + 1)
            if step < high
        )


def _margin_spans(context: _Context, edge: EdgeSpec) -> tuple[_Span, ...]:
    """Every margin ``edge`` might claim, before the deepest of them is chosen."""

    if edge.lane_hint is not None or edge.waypoints:
        return ()  # The author aimed this one; the engine does not re-aim it.
    parents = context.parents
    if edge.source.node_id not in parents or edge.target.node_id not in parents:
        return ()
    owner = lowest_common_group(parents, (edge.source.node_id, edge.target.node_id))
    if not context.positions[owner]:
        return ()  # An overlay has no cells, so it has no margins to hand out.
    source_cell = context.cells[owner].get(edge.source.node_id)
    target_cell = context.cells[owner].get(edge.target.node_id)
    if source_cell is None or target_cell is None:
        return ()
    source_row, source_column = context.positions[owner][source_cell]
    target_row, target_column = context.positions[owner][target_cell]
    vertical = source_row != target_row
    if not vertical and source_column == target_column:
        return ()
    sides = (Side.WEST, Side.EAST) if vertical else (Side.NORTH, Side.SOUTH)
    found: list[_Span] = []
    past = _past_a_cell(
        context, edge, owner, sides, vertical,
        (source_row, source_column), (target_row, target_column),
    )
    if past is not None:
        found.append(past)
    found.extend(_into_a_subtree(context, edge, owner, sides, vertical))
    return tuple(found)


def _past_a_cell(
    context: _Context,
    edge: EdgeSpec,
    owner: str,
    sides: tuple[Side, Side],
    vertical: bool,
    source: tuple[int, int],
    target: tuple[int, int],
) -> _Span | None:
    """The owner's own margin, when a cell between the endpoints stands in the way."""

    low, high = sorted(
        (float(source[0]), float(target[0])) if vertical else (float(source[1]), float(target[1]))
    )
    lane = source[1] if vertical else source[0]
    if (source[1] if vertical else source[0]) != (target[1] if vertical else target[0]):
        return None  # Different lanes: the run steps across rather than past.
    if not context.blocked(owner, low, high, lane, vertical):
        return None
    side = _corridor_side(context, edge, sides, fallback=True)
    if side is None:
        return None
    return _Span(edge.id, owner, side, low, high, context.depth[owner])


def _into_a_subtree(
    context: _Context,
    edge: EdgeSpec,
    owner: str,
    sides: tuple[Side, Side],
    vertical: bool,
) -> tuple[_Span, ...]:
    """A container's margin, for an endpoint attached across the route axis.

    The run reaches this port by travelling the container's margin from
    wherever it crosses the container's boundary down (or up) to the port's own
    cell. Where the other endpoint is inside the same container the two cells
    bound the run between them; where it is outside, the run runs to the end of
    the margin, which is what the half-integer sentinel says.
    """

    found: list[_Span] = []
    for near, far in ((edge.source, edge.target), (edge.target, edge.source)):
        side = edge.via if edge.via in sides else _port_side(context.figure, near)
        if side not in sides:
            continue
        container = context.container(near.node_id, owner)
        if container is None or not context.positions[container]:
            continue
        position = context.position(container, near.node_id, vertical)
        if position is None:
            continue
        outside = context.position(container, far.node_id, vertical)
        if outside is not None:
            low, high = sorted((position, outside))
        else:
            near_owner = context.position(owner, near.node_id, vertical)
            far_owner = context.position(owner, far.node_id, vertical)
            if near_owner is None or far_owner is None:
                continue
            low, high = (
                (-0.5, position)
                if far_owner < near_owner
                else (position, context.extent(container, vertical) + 0.5)
            )
        if high - low <= 0.0:
            continue
        found.append(_Span(edge.id, container, side, low, high, context.depth[container]))
    return tuple(found)


def _assign_tracks(members: list[_Span]) -> dict[str, int]:
    """Nesting order: the run that reaches furthest takes the outermost track.

    Two runs sharing a margin each cross it twice, once at either end. Take a
    run A whose cells enclose a run B's. Put B outside A and B's two crossings
    both land inside A's extent, so each of them cuts A: two crossings, one
    figure. Put A outside B and neither crossing reaches the other run -- A's
    cross the outer lane at cells beyond B's extent, B's never leave the inner
    one -- so the pair draws clean. Nesting is therefore the planar order
    wherever the spans nest, and nested spans always differ in reach, so
    handing out tracks shortest-reach-first *is* that order.

    Runs whose cells only touch, or miss entirely, share a track: the greedy
    below gives each run the innermost track no run it is parallel to has taken,
    which is the usual interval colouring and uses the fewest tracks a margin
    can be built with. Spans that interleave rather than nest have no planar
    order at all (R34's business); they still come out of here separated, which
    is what makes the crossing a clean single hop rather than a shared lane.
    """

    ordered = sorted(members, key=lambda span: (span.reach, span.low, span.edge_id))
    result: dict[str, int] = {}
    placed: list[_Span] = []
    for span in ordered:
        taken = {result[other.edge_id] for other in placed if span.overlaps(other)}
        result[span.edge_id] = next(track for track in count() if track not in taken)
        placed.append(span)
    return result


def _cell_index(groups: Mapping[str, GroupSpec], group_id: str) -> dict[str, int]:
    """Every node under ``group_id`` mapped to the index of the child holding it."""

    result: dict[str, int] = {}

    def walk(entity_id: str, index: int) -> None:
        group = groups.get(entity_id)
        if group is None:
            result[entity_id] = index
            return
        for child_id in group.children:
            walk(child_id, index)

    for index, child_id in enumerate(groups[group_id].children):
        walk(child_id, index)
    return result


def _cell_positions(
    groups: Mapping[str, GroupSpec],
    group_id: str,
) -> tuple[tuple[int, int], ...]:
    """The ``(row, column)`` each child of ``group_id`` occupies.

    One reading for both layout families: a linear group is a grid one cell
    wide (or one cell tall), so a column's third child is row 3 and a row's is
    column 3, and a grid's children are wherever ``grid_plan`` puts them. That
    is what lets a run down a grid's margin be measured the same way as a run
    down a column's. An overlay stacks its children on one spot and gets
    nothing, which is the honest answer that it has no axis to run beside.
    """

    group = groups[group_id]
    count = len(group.children)
    kind = group.layout.kind
    if kind == "row":
        return tuple((0, index) for index in range(count))
    if kind in {"column", "stack"}:
        return tuple((index, 0) for index in range(count))
    if kind == "grid":
        return grid_plan(group.layout, group.children).cells
    return ()


def _corridor_side(
    context: _Context,
    edge: EdgeSpec,
    sides: tuple[Side, Side],
    *,
    fallback: bool,
) -> Side | None:
    """Which of the two margins this run travels in, read off the semantics.

    A ``via`` hint names it outright. Failing that the ports do: a run leaving
    or arriving on a transverse side has already committed to that margin, since
    its stub points into it. A run that leaves east and arrives west has
    committed to *both* and belongs to neither, so it is left to the router.
    ``fallback`` supplies the convention for a run with nothing to say -- both
    its ports on the route axis -- which only the past-a-cell reading has.
    """

    if edge.via in sides:
        return edge.via
    named = tuple(
        dict.fromkeys(
            side
            for side in (
                _port_side(context.figure, edge.source),
                _port_side(context.figure, edge.target),
            )
            if side in sides
        )
    )
    if len(named) > 1:
        return None
    if named:
        return named[0]
    if not fallback:
        return None
    return next(side for side in _DEFAULT_SIDE if side in sides)


def _port_side(figure: FigureSpec, reference: PortRef) -> Side | None:
    return next(
        (
            port.side
            for port in figure.node(reference.node_id).ports
            if port.name == reference.port_name
        ),
        None,
    )


def track_coordinate(
    fitted: FittedFigure,
    plan: CorridorPlan,
    corridor: Corridor,
    style: LayoutStyle,
) -> float:
    """The one coordinate a corridor's track runs along, in fitted geometry.

    Track 0 sits one ``margin_clearance`` out from the deepest child on that
    side, and each further track one pitch further out again, into the padding
    the reservation bought. The deepest child rather than the content edge:
    where a group's children do not fill it, the margin starts where the
    children stop, which is the corridor the figure looks like it left.

    One more thing can stand in a margin. A run that reaches into a container
    from outside it passes components that are nobody's child of that group --
    the boundary strip above a layer, a glyph beside the band overhead -- and
    the whole corridor has to clear them or none of its tracks are routable. So
    the base is pushed out past anything that intrudes into the margin over the
    stretch the corridor covers, and the tracks step out from there together.
    """

    group = fitted.group(corridor.group_id)
    inner = _inner_edge(fitted, group, corridor.side)
    base = _cleared_base(fitted, plan, group, corridor.side, inner, style)
    outward = -1.0 if corridor.side in {Side.WEST, Side.NORTH} else 1.0
    return base + outward * corridor.track * track_pitch(style)


def _inner_edge(fitted: FittedFigure, group: FittedGroup, side: Side) -> float:
    """Where this group's own children stop, on ``side``."""

    bounds = tuple(
        _child_bounds(fitted, child_id) for child_id in group.measured.spec.children
    )
    if side is Side.WEST:
        return min(rect.left for rect in bounds)
    if side is Side.EAST:
        return max(rect.right for rect in bounds)
    if side is Side.NORTH:
        return min(rect.top for rect in bounds)
    return max(rect.bottom for rect in bounds)


def _cleared_base(
    fitted: FittedFigure,
    plan: CorridorPlan,
    group: FittedGroup,
    side: Side,
    inner: float,
    style: LayoutStyle,
) -> float:
    """``inner``, pushed out past everything standing in this margin, plus clearance."""

    clearance = margin_clearance(style)
    outward = -1.0 if side in {Side.WEST, Side.NORTH} else 1.0
    limit = _inner_edge_of(group.bounds, side)
    low, high = _margin_span(fitted, plan, group.measured.spec.id, side)
    base = inner
    for node in fitted.nodes:
        if node.measured.spec.kind in TRANSPARENT_KINDS:
            continue
        rect = node.bounds
        across = (rect.top, rect.bottom) if side.horizontal else (rect.left, rect.right)
        if across[1] <= low or across[0] >= high:
            continue  # Stands clear of the stretch this corridor covers.
        edge = _inner_edge_of(rect, side)
        if (edge - inner) * outward > 0.0 and (limit - edge) * outward >= 0.0:
            base = edge if (edge - base) * outward > 0.0 else base
    return base + outward * clearance


def _inner_edge_of(rect: Rect, side: Side) -> float:
    if side is Side.WEST:
        return rect.left
    if side is Side.EAST:
        return rect.right
    if side is Side.NORTH:
        return rect.top
    return rect.bottom


def _margin_span(
    fitted: FittedFigure,
    plan: CorridorPlan,
    group_id: str,
    side: Side,
) -> tuple[float, float]:
    """The stretch of the margin this corridor's runs cover, port to port."""

    semantic = fitted.measured.semantic
    edges = {edge.id: edge for edge in semantic.edges}
    values: list[float] = []
    for edge_id in plan.claimants.get((group_id, side), ()):
        edge = edges.get(edge_id)
        if edge is None:
            continue
        for reference in (edge.source, edge.target):
            position = fitted.node(reference.node_id).port(reference.port_name).position
            values.append(position.y if side.horizontal else position.x)
    if not values:
        return (float("inf"), float("-inf"))
    return min(values), max(values)


def _child_bounds(fitted: FittedFigure, child_id: str) -> Rect:
    try:
        return fitted.node(child_id).bounds
    except StopIteration:
        return fitted.group(child_id).bounds
