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
from dataclasses import dataclass

from flexo.components import (
    CAPTION_KINDS,
    TRANSPARENT_KINDS,
    TRANSPARENT_ROLES,
    route_clearance,
    titled,
)
from flexo.draft import DRAFT, give_up_if_newer, recall, remember
from flexo.geometry import Point, Rect, Side, segment_crosses_rect, segments
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
from flexo.routing.search import (
    EAST,
    NORTH,
    SOUTH,
    WEST,
    Grid,
    TooDear,
    Zone,
    ceiling,
    counted,
    search_work,
    simplify,
    spend,
)
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
    curved_edge,
    dots_at_joins,
    edge_cuts,
    net_reach_outlines,
    point_key,
    reach_outlines,
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
    straight = {
        edge.id for edge in semantic.edges if _is_straight(edge, layout_style, fitted)
    }
    members, ends = connections(fitted, straight)
    scene = _Scene(fitted, layout_style, text_measurer)

    # Each plan made, by the pin orders and end sides it was made with: the ends as it left
    # them, and its routes.
    plans: dict[tuple, tuple] = {}
    # Each bundle routed, by its pins, with what it was routed among.
    routings: dict[tuple, list[_Routing]] = defaultdict(list)

    def routed(index: int, bundle: Bundle, pins: dict, wires: list[Wire] | None) -> Wire:
        """``bundle`` routed (among ``wires`` but its own, if given) -- as it was before,
        if it was routed between the same pins among the same ink where its search looked
        (the repair trials route the whole figure again, most of it as it was)."""

        give_up_if_newer()  # (a routing given up for a newer drawing: flexo.draft)
        key = (
            bundle.key,
            bundle.hub,
            tuple(bundle.members),
            bundle.pinned,
            tuple(
                (pin.key, pin.side, pin.point, pin.arriving, pin.clearance)
                for pin in (pins[name] for name in _pin_keys(bundle, members, ends))
            ),
        )
        for before in reversed(routings[key][-RECALLED_ROUTINGS:]):
            if (before.among is None) != (wires is None):
                continue
            if wires is None or (
                before.index == index
                and len(before.among) == len(wires)
                and _unchanged_near(before.among, wires, index, before.region)
            ):
                # Its searches counted as made: the repairs' budget is counted in them,
                # and must run out where it did.
                spend(before.searched)
                return before.wire
        traffic = (
            _Traffic(
                [wire for position, wire in enumerate(wires) if position != index],
                crossing=CROSSING_COST * layout_style.bend_penalty,
            )
            if wires is not None
            else None
        )
        reached: list[Rect] = []
        with counted() as searched:
            wire = scene.grow(bundle, members, ends, pins, traffic, reached)
        routings[key].append(
            _Routing(
                index,
                list(wires) if wires is not None else None,
                reached[0] if reached else None,
                searched,
                wire,
            )
        )
        return wire

    def attempt(
        overrides: dict[tuple[str, Side], list],
        sides: dict[int, Side] | None = None,
        *,
        again: bool = False,
    ) -> tuple:
        key = (
            frozenset((place, tuple(order)) for place, order in overrides.items()),
            frozenset((sides or {}).items()),
        )
        if again and key in plans:
            # Made before (the trial the repairs kept): planned and routed again it would be
            # the same, so it is given as it was, its ends put back as it left them.
            state, made = plans[key]
            for end, (group, fixed) in zip(ends, state, strict=True):
                end.group, end.fixed = group, fixed
            return made
        orders: dict[tuple[str, Side], list] = {}
        pins = plan_pins(fitted, members, ends, layout_style, overrides, orders, sides)
        bundles = plan_bundles(members, ends)
        wires = [routed(index, bundle, pins, None) for index, bundle in enumerate(bundles)]
        # Rip up and reroute: every bundle again, now able to see the others.
        for _ in range(REROUTE_PASSES):
            for index, bundle in enumerate(bundles):
                if bundle.pinned:
                    continue
                wire = routed(index, bundle, pins, wires)
                if wire != wires[index]:
                    wires[index] = wire
        plans[key] = ([(end.group, end.fixed) for end in ends], (pins, bundles, wires, orders))
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
            _squared(spaced) if _orthogonal(spaced) else copy.deepcopy(original)
            for spaced, original in zip(wires, routed, strict=True)
        ]

    # A figure drawn before is remembered: its draft starts from that drawing (flexo.draft).
    memory = _memory_key(semantic, layout_style)
    last = recall("routes", memory)
    if DRAFT.get():
        overrides, sides = _recalled_choices(last, members)
        pins, bundles, wires = _drafted(
            scene, fitted, members, ends, layout_style, overrides, sides, last
        )
    else:
        started = search_work()
        pins, bundles, wires, orders = attempt({})
        # Each repair trial routes the whole figure again: one whose routing alone costs
        # more than the repairs may spend gets none, rather than a trial past the budget;
        # and the repairs of any figure spend no more than so many routings of it.
        first = search_work() - started
        affordable = first <= REPAIR_WORK
        budget = min(REPAIR_WORK, max(REPAIR_ROUTINGS * first, REPAIR_LEAST))
        _REPAIR_LIMIT[0] = search_work() + (budget if affordable else 0)
        _TRIAL_WORK[0] = TRIAL_ROUTINGS * max(first, TRIAL_LEAST)
        kept: dict = {}
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
            kept,
        )
        overrides, sides = kept.get("overrides", {}), kept.get("sides", {})
    remember(
        "routes",
        memory,
        _Drawn(fitted, layout_style, members, ends, pins, bundles, wires, overrides, sides),
    )
    give_up_if_newer()
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
    # (A curved edge bows away from the figure's middle.)
    middle = Rect.union(node.bounds for node in fitted.nodes).center if fitted.nodes else None
    for together in pairs.values():
        # Straight edges between one pair of components run side by side,
        # a lane apart, rather than on top of each other.
        for index, edge in enumerate(together):
            offset = (index - (len(together) - 1) / 2.0) * layout_style.port_spacing.points
            if edge.shape == "curved":
                routed_edges[edge.id] = curved_edge(
                    edge, fitted, layout_style, text_measurer, offset=offset,
                    paired=len(together) > 1, middle=middle,
                )
                continue
            routed_edges[edge.id] = straight_edge(
                edge, fitted, layout_style, text_measurer, offset=offset
            )
    # Ink meets a drawn shape's outline, not the box round it.
    edges = [reach_outlines(routed_edges[edge.id], fitted, layout_style) for edge in semantic.edges]
    nets = [net_reach_outlines(routed_nets[net.id], fitted, layout_style) for net in semantic.nets]
    give_up_if_newer()
    edges, nets = place_captions(
        edges,
        nets,
        solids=(
            *(rect for node in fitted.nodes for rect in caption_solids(node)),
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
        from_start=frozenset(
            edge.spec.id
            for edge in edges
            if fitted.node(edge.spec.source.node_id).measured.spec.kind == "decision"
        ),
    )
    return RoutedFigure(fitted, tuple(edges), tuple(nets))


RECALLED_ROUTINGS = 4
"""How many of a bundle's last routings between the same pins are looked through for one
to give again, rather than route it afresh."""


@dataclass(slots=True)
class _Routing:
    """A bundle as routed: where it sat among the bundles, every wire it was routed among
    (None, none), where its search priced their ink, the work of its searches, and its wire."""

    index: int
    among: list[Wire] | None
    region: Rect | None
    searched: list[int]
    wire: Wire


def _unchanged_near(seen: list[Wire], wires: list[Wire], index: int, region: Rect | None) -> bool:
    """Whether every wire but ``index``'s is as it was (``seen``) within ``region``: where
    its search priced their ink (None, nowhere)."""

    for position, (before, now) in enumerate(zip(seen, wires, strict=True)):
        if position == index or before is now:
            continue
        if region is not None and (_inks(before, region) or _inks(now, region)) and before != now:
            return False
    return True


def _inks(wire: Wire, region: Rect) -> bool:
    """Whether any run of ``wire`` comes within a hair of ``region``."""

    left, top = region.left - 1e-6, region.top - 1e-6
    right, bottom = region.right + 1e-6, region.bottom + 1e-6
    for path in wire.paths:
        for start, end in itertools.pairwise(path):
            if (
                min(start.x, end.x) <= right
                and max(start.x, end.x) >= left
                and min(start.y, end.y) <= bottom
                and max(start.y, end.y) >= top
            ):
                return True
    return False


SIDE_TRIALS = 8
"""Most end sides tried, per figure, to take a crossing out."""

CROWDING_WEIGHT = 3
"""How many crossings one pair of lines drawn too close counts as, in a trial."""

LOOP_TRIALS = 4
"""Most two-ended loop trials, per figure, after the single-end ones."""

PIN_ORDER_TRIALS = 12

REPAIR_WORK = 1_000_000
"""How much route search (steps of the A* frontier) the crossing repairs may spend
on one figure, beyond its first routing.

The trials above are capped in number, but each reroutes the whole figure, so a
large figure that keeps crossing could spend minutes on them. Counted in search
steps, not seconds, so a figure routes the same on every machine; the densest
figure in the literature set spends under a million on its whole routing."""
REPAIR_ROUTINGS = 16
"""How many times its own first routing the crossing repairs may spend on a figure.

A repair that takes a crossing out costs a few routings of the figure; across the
examples and the literature set the dearest that helped cost 15. A crossing the
repairs cannot take out costs far more -- a line that must come back round tried
every way round -- so a small figure, laid out for a slide again and again as it is
dragged into shape, would otherwise spend seconds each time on one it keeps."""

REPAIR_LEAST = 20_000
"""The least the repairs may spend, however cheap the first routing: a few trials of
the smallest figures, whose one routing is a few hundred steps."""

TRIAL_ROUTINGS = 6
"""How many times the figure's first routing one repair trial may spend before it is
given up. A trial that took a crossing out has cost at most about 3 (across the
examples and the literature set); one that sends a line the long way round every
other part can cost 30, and is never the one kept."""

TRIAL_LEAST = 2_000
"""The least a trial is allowed, however cheap the first routing."""

_REPAIR_LIMIT = [0]
_TRIAL_WORK = [0]


def _trial(attempt, *args):
    """``attempt(*args)`` as a repair trial: None if it searches past what a trial may."""

    ceiling(min(search_work() + _TRIAL_WORK[0], _REPAIR_LIMIT[0]))
    try:
        return attempt(*args)
    except TooDear:
        return None
    finally:
        ceiling(None)


def _within_budget() -> bool:
    return search_work() < _REPAIR_LIMIT[0]
"""Most pin orders tried, per figure, to take a crossing out."""

SPACING_TOLERANCE = 1e-3
"""Points by which two runs may fall short of a lane and not count as crowded.

The same as lint's: the spacing solver leaves rounding error, and a trial must
not trade a crossing for two lines exactly a lane apart.
"""


def _reorder_crossing_pins(
    attempt, separated, pins, bundles, wires, orders, members, ends, spacing, kept=None
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
    while best and trials < PIN_ORDER_TRIALS and _within_budget():
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
                if signature in tried or trials >= PIN_ORDER_TRIALS or not _within_budget():
                    continue
                tried.add(signature)
                trials += 1
                trial = _trial(attempt, {**overrides, side_key: swapped})
                if trial is None:
                    continue
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
        kept,
    )


def _turn_crossing_ends(
    attempt, separated, pins, bundles, wires, overrides, best, members, ends, spacing, kept=None
):
    """Try the other sides of a crossing edge's ends, while that helps.

    A pin's side is chosen before any route exists, from where the other end
    is. A line that has to come back round -- a loop from a decision back to
    the step it repeats -- then arrives on the side facing its source and cuts
    through everything between. Entering from above or below instead, it can
    go round. So each end of a crossing edge whose side is a default is tried
    on the two sides across from its own -- and, at an operator or a circle,
    first on the opposite one -- and kept where the figure crosses less.
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
        # What leaves an operator, circle or diamond keeps the side its own
        # rules gave it; what arrives may turn -- a skip into a sum from the
        # far side.
        and (end.arriving or end.node.measured.spec.kind not in POINT_KINDS)
        and any(
            port.name == end.reference.port_name and port.auto_side
            for port in end.node.measured.spec.ports
        )
    }
    # A line back to a step before it (a loop) is first tried as a C round the rest, both
    # ends turned at once, while there is time for it: by the time single ends have been
    # turned, there may be none left -- and the loop drawn through the middle, across the
    # lines there, with the side beside the figure empty.
    looped = _on_cycles(members)
    if best and looped and _within_budget():
        improved, used = _try_loops(
            attempt, separated, overrides, bundles, members, ends, free, sides, tried,
            SIDE_TRIALS, spacing, best, only=looped,
        )
        trials = used - SIDE_TRIALS
        if improved is not None:
            sides, (pins, bundles, wires), best = improved
    while best and trials < SIDE_TRIALS and _within_budget():
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
            turns = [turn for turn in Side if turn.horizontal != current.horizontal]
            if titled(ends[group[0]].node.measured.spec):
                # (Never onto a top a name is set across.)
                turns = [turn for turn in turns if turn is not Side.NORTH]
            if ends[group[0]].node.measured.spec.kind in POINT_KINDS:
                # A circle's opposite side is as near as any: a skip into a sum
                # from the left is as natural as from the right.
                turns.insert(0, current.opposite)
            for side in turns:
                if (key, side) in tried or trials >= SIDE_TRIALS or not _within_budget():
                    continue
                tried.add((key, side))
                trials += 1
                chosen = {**sides, **dict.fromkeys(group, side)}
                trial = _trial(attempt, overrides, chosen)
                if trial is None:
                    continue
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
        pins, bundles, wires, _ = attempt(overrides, sides, again=True)
    if kept is not None:
        # (What the repairs kept, for a draft of the figure to keep too: flexo.draft.)
        kept["overrides"], kept["sides"] = dict(overrides), dict(sides)
    return pins, bundles, wires


def _on_cycles(members) -> set[int]:
    """The edges (by their index among ``members``) that close a loop: a line back to a
    step whose lines lead on to where it starts (a decision's "try again")."""

    onward: dict[str, set[str]] = defaultdict(set)
    edges = [
        (index, member.spec.source.node_id, member.spec.target.node_id)
        for index, member in enumerate(members)
        if isinstance(member.spec, EdgeSpec)
    ]
    for _, source, target in edges:
        onward[source].add(target)

    def reaches(start: str, goal: str) -> bool:
        seen, stack = {start}, [start]
        while stack:
            at = stack.pop()
            if at == goal:
                return True
            for following in onward[at] - seen:
                seen.add(following)
                stack.append(following)
        return False

    return {
        index for index, source, target in edges if source != target and reaches(target, source)
    }


def _try_loops(
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
    only=None,
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
            if not isinstance(spec, EdgeSpec) or (only is not None and member not in only):
                continue
            first, second = members[member].ends
            if first not in free or second not in free:
                continue
            here, there = ends[first].node.bounds.center, ends[second].node.bounds.center
            across = abs(there.x - here.x) >= abs(there.y - here.y)
            for side in (Side.NORTH, Side.SOUTH) if across else (Side.WEST, Side.EAST):
                key = (first, second, side)
                if side is Side.NORTH and any(
                    titled(ends[end].node.measured.spec) for end in (first, second)
                ):
                    continue  # never onto a top a name is set across
                if key in tried or trials >= SIDE_TRIALS + LOOP_TRIALS or not _within_budget():
                    continue
                tried.add(key)
                trials += 1
                chosen = {**sides, first: side, second: side}
                trial = _trial(attempt, overrides, chosen)
                if trial is None:
                    continue
                defects = _defects(separated(trial[2]), spacing)
                if len(defects) < len(best):
                    return (chosen, trial[:3], defects), trials
    return None, trials


def _squared(wire: Wire) -> Wire:
    """``wire`` with coordinates that differ by rounding alone made equal.

    Two runs meant to line up can come out a rounding error apart, which is a
    diagonal hair in the drawing. Each point takes the coordinate of the one
    before it where they agree to within ``_HAIR``; the last point of a path is
    a pin and stays put, so the point before it takes the pin's instead.
    """

    for path in wire.paths:
        for index in range(1, len(path)):
            before, point = path[index - 1], path[index]
            last = index == len(path) - 1
            if abs(before.x - point.x) < _HAIR and before.x != point.x:
                if last:
                    path[index - 1] = Point(point.x, before.y)
                else:
                    path[index] = Point(before.x, point.y)
            before, point = path[index - 1], path[index]
            if abs(before.y - point.y) < _HAIR and before.y != point.y:
                if last:
                    path[index - 1] = Point(before.x, point.y)
                else:
                    path[index] = Point(point.x, before.y)
    return wire


_HAIR = 1e-6
"""Coordinates closer than this, in points, are one coordinate."""


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
        return overlap > 1e-6 and abs(a.y - c.y) + SPACING_TOLERANCE < spacing
    if abs(a.x - b.x) < 1e-9 and abs(c.x - d.x) < 1e-9:
        low, high = sorted((a.y, b.y))
        other_low, other_high = sorted((c.y, d.y))
        overlap = min(high, other_high) - max(low, other_low)
        return overlap > 1e-6 and abs(a.x - c.x) + SPACING_TOLERANCE < spacing
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


def caption_solids(node: FittedNode) -> tuple[Rect, ...]:
    """What a caption must keep off of a component: its box -- or, for a decision's
    diamond, the diamond in steps, so "yes" may sit in the corner beside where it starts."""

    box = node.bounds
    if node.measured.spec.kind != "decision":
        return (box,)
    steps = 6
    bands = []
    for index in range(steps):
        # Each band as wide as the diamond at its edge nearer the middle.
        near = min(abs(index - steps / 2.0), abs(index + 1 - steps / 2.0))
        width = box.width * (1.0 - near / (steps / 2.0))
        bands.append(
            Rect(box.x + (box.width - width) / 2.0, box.y + box.height * index / steps,
                 width, box.height / steps)
        )
    return tuple(bands)


def _outline(bounds: Rect) -> tuple[Point, ...]:
    corners = (
        Point(bounds.left, bounds.top),
        Point(bounds.right, bounds.top),
        Point(bounds.right, bounds.bottom),
        Point(bounds.left, bounds.bottom),
    )
    return (*corners, corners[0])


def _is_straight(edge: EdgeSpec, style: LayoutStyle, fitted: FittedFigure) -> bool:
    """Whether an edge is drawn between its outlines rather than routed: straight, or
    curved."""

    if edge.source.node_id == edge.target.node_id:
        return False  # a loop has no line between two outlines to draw
    if edge.shape == "curved":
        return True
    if edge.shape == "auto":
        wanted = style.conventions.lines == "straight"
    else:
        wanted = edge.shape == "straight"
    if not wanted or style.conventions.lines != "straight":
        return wanted
    # Straight by the figure's convention: a line that would run through
    # another component is routed round it instead. (An edge made straight on
    # its own, in a routed figure, was asked for as it is.)
    first = fitted.node(edge.source.node_id).bounds.center
    second = fitted.node(edge.target.node_id).bounds.center
    return not any(
        segment_crosses_rect(first, second, node.bounds.inflated(-0.5))
        for node in fitted.nodes
        if node.measured.spec.id not in {edge.source.node_id, edge.target.node_id}
        and node.measured.spec.kind not in TRANSPARENT_KINDS
    )


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
        window: tuple[Rect, ...] = (),
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
        for rect in window:
            xs.extend((rect.left, rect.right))
            ys.extend((rect.top, rect.bottom))
        return Grid(xs, ys, zones, boundary=boundary, outside_cost=OUTSIDE_COST, window=window)

    def grow(
        self,
        bundle: Bundle,
        members: list[Member],
        ends: list[End],
        pins: dict[tuple[str, str, Side, bool], Pin],
        others: _Traffic | None = None,
        reached: list[Rect] | None = None,
        window: tuple[Rect, ...] = (),
        haste: float = 1.0,
    ) -> Wire:
        """Route one bundle as a tree rooted at its hub pin.

        ``others`` is the ink every other bundle drew in the previous pass;
        crossing it or running on top of it is priced, so the second pass
        steers around what the first pass could not see. ``reached``, if given,
        is told the region the search priced that ink in: ink beyond it changed
        nothing. A ``window`` (of rectangles) keeps the search within it, and
        ``haste`` hurries it (``Grid.route_from_tree``): a draft's (flexo.draft).
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
        grid = self._grid(everything, tuple(short.values()), lean=lean, window=window)
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
                    haste=haste,
                )
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, index, path)
            assert best is not None
            _, index, path = best
            spoke = remaining.pop(index)
            stubs[spoke.key] = path[-1]
            paths.append(list(simplify((*path, spoke.point))))
            seeds.extend(_tree_seeds(grid, path))
        if reached is not None and grid.reached is not None:
            # (A step was priced out of each cell reached: one grid line further.)
            least_x, least_y, most_x, most_y = grid.reached
            left, right = grid.xs[max(least_x - 1, 0)], grid.xs[min(most_x + 1, len(grid.xs) - 1)]
            top, bottom = grid.ys[max(least_y - 1, 0)], grid.ys[min(most_y + 1, len(grid.ys) - 1)]
            reached.append(Rect(left, top, right - left, bottom - top))
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


# -- drafts --
# While a figure is drawn as a draft (flexo.draft), its lines are drawn as they were the last
# time it was drawn wherever nothing about them changed, and only the rest are routed again.

DRAFT_MARGIN = 12.0
"""How near a line (points) nothing may have changed for it to be drawn as before."""

DRAFT_REACH = 48.0
"""How far from where it ran, and from its ends, a draft's line may be routed afresh."""

DRAFT_HASTE = 1.6
"""How hurried a draft's search for a line is (``Grid.route_from_tree``'s ``haste``)."""

DRAFT_NEAR_WORK = 60_000
"""How much a draft's search for a line near where it ran may take (steps) before it is
searched for further afield."""

DRAFT_AFIELD = 0.25
"""How much further afield (a share of the figure's size) a draft's line is searched for when
near where it ran it would cut through something."""


class _Drawn:
    """A figure's routing, as kept for its next draft: each bundle's wire (as routed, before
    separation) and the pins it ran between, the boxes about it, and the repairs chosen."""

    def __init__(self, fitted, style, members, ends, pins, bundles, wires, overrides, sides):
        self.wires = {bundle.key: wire for bundle, wire in zip(bundles, wires, strict=True)}
        self.pins = {
            bundle.key: {
                key: (pins[key].point, pins[key].side) for key in _pin_keys(bundle, members, ends)
            }
            for bundle in bundles
        }
        self.hubs = {bundle.key: bundle.hub for bundle in bundles}
        self.boxes = _boxes(fitted, style)
        self.overrides = dict(overrides)
        # Ends by their line and place on it, not their index: another line added shifts those.
        self.sides = {}
        for index, side in sides.items():
            member = members[ends[index].member]
            self.sides[(member.spec.id, member.ends.index(index))] = side


def _memory_key(semantic, style: LayoutStyle) -> tuple:
    """Which figure a routing is of, for its drafts: by its id, the way its groups run and
    its spacing (a figure turned to fit a slide, or set closer, is another drawing of it)."""

    return (semantic.id, tuple((group.id, group.layout.kind) for group in semantic.groups), style)


def _pin_keys(bundle: Bundle, members: list[Member], ends: list[End]) -> list:
    keys = [bundle.hub]
    for member in bundle.members:
        for end in members[member].ends:
            if ends[end].group not in keys:
                keys.append(ends[end].group)
    return keys


def _boxes(fitted: FittedFigure, style: LayoutStyle) -> dict[str, tuple[Rect, bool]]:
    """What a line is routed round, each with whether it is a container: every part, every
    container drawn, and each one's title."""

    found = {node.measured.spec.id: (node.bounds, False) for node in fitted.nodes}
    for group in fitted.groups:
        if group.measured.spec.role in TRANSPARENT_ROLES:
            continue
        found[group.measured.spec.id] = (group.bounds, True)
        title = title_rect(group, style)
        if title is not None:
            found[f"{group.measured.spec.id}\0title"] = (title, False)
    return found


def _recalled_choices(last: _Drawn | None, members: list[Member]) -> tuple[dict, dict]:
    """The pin orders and end sides the last full routing kept, for ends there are still."""

    if last is None:
        return {}, {}
    where = {
        (member.spec.id, position): end
        for member in members
        for position, end in enumerate(member.ends)
    }
    sides = {where[key]: side for key, side in last.sides.items() if key in where}
    return dict(last.overrides), sides


def _drafted(scene, fitted, members, ends, style, overrides, sides, last):
    """A draft's routing: each bundle's last wire, moved with its ends, where nothing about
    it changed; the rest routed once."""

    pins = plan_pins(fitted, members, ends, style, overrides, {}, sides)
    bundles = plan_bundles(members, ends)
    boxes = _boxes(fitted, style)
    changed: dict[tuple[float, float], list] = {}
    wires: list[Wire | None] = [
        _moved_wire(bundle, members, ends, pins, last, boxes, changed, scene.canvas)
        if last
        else None
        for bundle in bundles
    ]
    for index, bundle in enumerate(bundles):
        if wires[index] is None:
            # (Not in view of the others: pricing their ink makes a search wander far, and
            # the separation that follows spreads what shares a corridor all the same. Nor
            # far from where it ran, moved with its ends, or from its ends: a line kept from
            # the long way round a full drawing may take, rather than searched for over the
            # whole figure.)
            # Kept near, a line that would cut through a part or a group is searched for
            # further afield, and then everywhere.
            # (One not drawn before has nowhere it ran to go by: further afield at once.)
            corridor = _corridor(bundle, members, ends, pins, last)
            reach = max(scene.canvas.width, scene.canvas.height) * DRAFT_AFIELD
            wider = (Rect.union(corridor).inflated(reach),)
            known = last is not None and bundle.key in last.wires
            # (Further afield taking in the whole figure, everywhere is no further.)
            tries = [corridor] if known else []
            tries += [wider] if wider[0].contains_rect(scene.canvas) else [wider, ()]
            wire = None
            for window in tries:
                # (Near where it ran, a line found at all is found soon: a search that runs
                # on there is one with no way through, and is given up for one further out.)
                ceiling(search_work() + DRAFT_NEAR_WORK if window is corridor else None)
                reached: list[Rect] = []
                try:
                    wire = scene.grow(
                        bundle, members, ends, pins, None, reached, window, DRAFT_HASTE
                    )
                except (RuntimeError, TooDear):  # (or its ends too far from where it ran)
                    continue
                finally:
                    ceiling(None)
                if window is tries[-1] or not _through(scene, wire, bundle, members, ends, pins):
                    break
                # (A search that never reached the edge of its window would find the same
                # line anywhere: it is the line there is.)
                if window is wider and reached and _within(reached[0], wider[0]):
                    break
            wires[index] = wire
    return pins, bundles, wires


def _corridor(bundle, members, ends, pins, last: _Drawn | None) -> tuple[Rect, ...]:
    """Where a draft's search for ``bundle`` may go: about each run of its last wire, moved
    with its hub, and from there to each of its ends -- or, with no wire to go by, about
    all its ends at once."""

    keys = _pin_keys(bundle, members, ends)
    ends_at = [point for key in keys for point in (pins[key].point, pins[key].escape)]
    wire = last.wires.get(bundle.key) if last is not None else None
    before = last.pins.get(bundle.key) if last is not None else None
    if wire is None or before is None or bundle.hub not in before:
        return (_around(ends_at),)
    was, _ = before[bundle.hub]
    dx, dy = pins[bundle.hub].point.x - was.x, pins[bundle.hub].point.y - was.y
    moved = _shifted(wire, dx, dy)
    rects = [
        _around((start, end))
        for path in moved.paths
        for start, end in itertools.pairwise(path)
        if start is not None and end is not None
    ]
    for key in keys:
        pin = pins[key]
        old = before.get(key)
        then = Point(old[0].x + dx, old[0].y + dy) if old is not None else pins[bundle.hub].escape
        rects.append(_around((then, pin.point, pin.escape)))
    return tuple(rects)


def _through(scene, wire: Wire, bundle, members, ends, pins) -> bool:
    """Whether ``wire`` runs through a part not its own, or a group that holds none of its
    ends."""

    nodes = {pins[key].node.measured.spec.id for key in _pin_keys(bundle, members, ends)}
    owners = {owner for node in nodes for owner in ancestors(scene.parents, node)}
    runs = [
        (start, end)
        for path in wire.paths
        for start, end in itertools.pairwise(path)
        if start is not None and end is not None
    ]
    boxes = [node.bounds for node in scene.solid if node.measured.spec.id not in nodes]
    boxes += [
        group.bounds for group in scene.containers if group.measured.spec.id not in owners
    ]
    return any(segment_crosses_rect(start, end, box) for box in boxes for start, end in runs)


def _within(inner: Rect, outer: Rect) -> bool:
    """Whether ``inner`` lies inside ``outer``, clear of its edges."""

    return (
        outer.left < inner.left - 1e-6
        and inner.right + 1e-6 < outer.right
        and outer.top < inner.top - 1e-6
        and inner.bottom + 1e-6 < outer.bottom
    )


def _around(points) -> Rect:
    points = list(points)
    left, top = min(point.x for point in points), min(point.y for point in points)
    right, bottom = max(point.x for point in points), max(point.y for point in points)
    return Rect(left, top, right - left, bottom - top).inflated(DRAFT_REACH)


def _moved_wire(bundle, members, ends, pins, last: _Drawn, boxes, changed, canvas) -> Wire | None:
    """``bundle``'s wire as last drawn, moved as its ends moved -- should every one of them
    have moved alike, and nothing near the line have changed beside it; else None.

    ``changed`` keeps, for each way a line may have moved, what did not move that way."""

    wire = last.wires.get(bundle.key)
    before = last.pins.get(bundle.key)
    if wire is None or before is None or bundle.pinned or last.hubs.get(bundle.key) != bundle.hub:
        return None
    keys = _pin_keys(bundle, members, ends)
    if set(keys) != set(before):
        return None
    was, _ = before[bundle.hub]
    dx, dy = pins[bundle.hub].point.x - was.x, pins[bundle.hub].point.y - was.y
    for key in keys:
        point, side = before[key]
        now = pins[key]
        off = abs(now.point.x - point.x - dx) + abs(now.point.y - point.y - dy)
        if now.side is not side or off > 1e-6:
            return None
    moved = _shifted(wire, dx, dy)
    runs = [
        (start, end)
        for path in moved.paths
        for start, end in itertools.pairwise(path)
        if start is not None and end is not None
    ]
    if not runs or not all(canvas.contains_point(point) for run in runs for point in run):
        return None
    left = min(min(start.x, end.x) for start, end in runs) - DRAFT_MARGIN
    top = min(min(start.y, end.y) for start, end in runs) - DRAFT_MARGIN
    right = max(max(start.x, end.x) for start, end in runs) + DRAFT_MARGIN
    bottom = max(max(start.y, end.y) for start, end in runs) + DRAFT_MARGIN
    reach = Rect(left, top, right - left, bottom - top)
    # The line's own ends may have changed about it (a box grown on its far side): the line
    # need only keep out of them.
    own = {pins[key].node.measured.spec.id for key in keys}
    delta = (round(dx, 6), round(dy, 6))
    if delta not in changed:
        changed[delta] = [
            (name, box, container)
            for name, (box, container) in boxes.items()
            if not _moved_alike(last.boxes.get(name), box, dx, dy)
        ]
    for name, box, container in changed[delta]:
        if not box.intersects(reach):
            continue
        if name in own:
            if any(segment_crosses_rect(start, end, box) for start, end in runs):
                return None
        elif any(_near(start, end, box, container) for start, end in runs):
            return None
    return moved


def _moved_alike(before: tuple[Rect, bool] | None, box: Rect, dx: float, dy: float) -> bool:
    if before is None:
        return False
    was = before[0]
    return (
        abs(was.x + dx - box.x) < 1e-6
        and abs(was.y + dy - box.y) < 1e-6
        and abs(was.width - box.width) < 1e-6
        and abs(was.height - box.height) < 1e-6
    )


def _near(start: Point, end: Point, box: Rect, container: bool) -> bool:
    """Whether a run passes within ``DRAFT_MARGIN`` of a box -- of a container's outline,
    for a container: a line may run inside one, as one may run past a part."""

    if not segment_crosses_rect(start, end, box.inflated(DRAFT_MARGIN)):
        return False
    if not container or min(box.width, box.height) <= 2 * DRAFT_MARGIN:
        return True
    inner = box.inflated(-DRAFT_MARGIN)
    return not (inner.contains_point(start) and inner.contains_point(end))


def _shifted(wire: Wire, dx: float, dy: float) -> Wire:
    def at(point: Point | None) -> Point | None:
        return None if point is None else Point(point.x + dx, point.y + dy)

    copied = copy.copy(wire)
    copied.paths = [[at(point) for point in path] for path in wire.paths]
    copied.terminals = [
        Terminal(at(terminal.point), terminal.clearance, at(terminal.escape))
        for terminal in wire.terminals
    ]
    copied.flow_from, copied.flow_to = at(wire.flow_from), at(wire.flow_to)
    return copied
