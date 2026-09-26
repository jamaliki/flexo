"""Order and space the runs of every connector: the second half of routing.

Routes are searched one at a time and blind to one another, so two of them that
want the same corridor come back lying exactly on top of each other. This pass
turns that into a drawing, one axis at a time (after libavoid's nudging):

1. **Runs.** Every connector is a *wire*: one or more polylines that may share
   vertices (a net is a tree of them). Its maximal straight pieces on one axis
   are its runs; a run of a net that several branches share is one run.
2. **Order.** Runs of different wires that coincide are put in the order that
   crosses least, tried both ways on the actual geometry.
3. **Space.** Every run becomes a variable. Runs that would sit closer than a
   lane apart get a separation constraint in that order -- a caption's height
   instead of a lane above the run a caption sits on; everything a run must
   keep clear of -- components, container walls, the ports at the far end of the
   pieces attached to it -- bounds it. The crossbar of a Z and the trunk of a
   net *want* the middle of the alley they have; any other run wants to stay
   put. The constraint solver (``vpsc``) finds the nearest arrangement that
   honours all of it, and if lanes cannot fit at full spacing they shrink by
   tenths rather than the figure failing.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field

from flexo.geometry import Point, Rect, Side
from flexo.routing.search import simplify
from flexo.routing.vpsc import solve

_EPSILON = 1e-6
_FIXED = 1e6
_STAY = 1e-3
_CENTRE = 1e-5
_BOUND = 1e5
WALL_MARGIN = 5.0
"""Room a run would rather keep from a container edge: never drawn on the border."""


@dataclass(slots=True)
class Terminal:
    """A port a wire ends at, and how far its first bend must stay from it."""

    point: Point
    clearance: float
    escape: Point | None = None
    """Where the stub out of the port ends: a run may come right up to it."""


@dataclass(slots=True)
class Wire:
    """One connector's ink: polylines sharing vertices, plus the ports it ends at."""

    key: str
    paths: list[list[Point]]
    terminals: list[Terminal] = field(default_factory=list)
    pinned: bool = False
    """An author-placed route (a lane, a waypoint): its runs do not move."""
    rail_at: float | None = None
    """Where a net's trunk should sit in its corridor, as a fraction from its sources."""
    rail_side: Side | None = None
    """The side of its corridor a net's trunk was pinned to (``rail=``)."""
    flow_from: Point | None = None
    """Where the flow of a net starts, to read ``rail_at`` from."""
    flow_to: Point | None = None
    """Where the flow of a net ends: ``rail_at`` is a fraction of the way there."""
    rail_clamped: float | None = None
    """The fraction the trunk actually got, when ``rail_at`` could not be honoured."""
    caption: tuple[float, float] | None = None
    """``(room, width)`` a caption needs above the wire's longest horizontal run.

    A connector's caption sits above the middle of that run, so the run above
    it keeps ``room`` away, not just a lane, wherever it passes over the
    caption's ``width``.
    """

    def terminal_clearance(self, point: Point) -> float | None:
        for terminal in self.terminals:
            if _same(terminal.point, point):
                return terminal.clearance
        return None

    def margin(self, point: Point) -> float:
        """How far a run must stay from ``point`` when a piece joins them.

        A port by its clearance; the end of a port's stub not at all -- that is
        exactly where the stub is allowed to turn; anything else by a hair, so a
        piece never collapses and changes what it joins.
        """

        clearance = self.terminal_clearance(point)
        if clearance is not None:
            return clearance
        if any(
            terminal.escape is not None and _same(terminal.escape, point)
            for terminal in self.terminals
        ):
            return 0.0
        return 1.0


@dataclass(slots=True)
class _Run:
    wire: int
    coordinate: float
    low: float
    high: float
    members: list[tuple[int, int]]
    """``(path index, vertex index)`` of every vertex of the wire lying on the run."""
    fixed: bool = False
    lower: float = float("-inf")
    upper: float = float("inf")
    desired: float = 0.0
    weight: float = _STAY


def separate(
    wires: list[Wire],
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    *,
    spacing: float,
    boundary: Rect | None = None,
    passes: int = 2,
) -> list[Wire]:
    """Order and space every wire's runs, horizontally then vertically."""

    for _ in range(passes):
        for vertical in (True, False):
            _nudge_axis(wires, obstacles, walls, spacing, boundary, vertical)
            for wire in wires:
                wire.paths = [list(simplify(tuple(path))) for path in wire.paths]
    return wires


def _nudge_axis(
    wires: list[Wire],
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    spacing: float,
    boundary: Rect | None,
    vertical: bool,
) -> None:
    runs = [run for index, wire in enumerate(wires) for run in _runs(wire, index, vertical)]
    if not runs:
        return
    for run in runs:
        _bound(run, wires, obstacles, walls, boundary, vertical)
    runs = _unify(runs, wires, obstacles, walls, boundary, vertical)
    rooms = {} if vertical else _caption_rooms(runs, wires)
    order = _ordered(runs, wires, spacing, vertical, rooms)
    # Room for captions first; where it does not fit, lanes alone, shrinking.
    positions = _solve(runs, order, spacing, rooms) if rooms else None
    if positions is None:
        for attempt in range(11):
            gap = spacing * (1.0 - attempt / 10.0)
            positions = _solve(runs, order, gap)
            if positions is not None:
                break
        else:  # pragma: no cover - the last attempt has zero spacing and always fits
            positions = [run.coordinate for run in runs]
    for run, position in zip(runs, positions, strict=True):
        if run.fixed or abs(position - run.coordinate) < 1e-9:
            continue
        wire = wires[run.wire]
        for path_index, vertex_index in run.members:
            point = wire.paths[path_index][vertex_index]
            wire.paths[path_index][vertex_index] = (
                Point(position, point.y) if vertical else Point(point.x, position)
            )


# -- runs --------------------------------------------------------------------------


def _runs(wire: Wire, wire_index: int, vertical: bool) -> list[_Run]:
    """The maximal straight pieces of ``wire`` along one axis, shared pieces merged."""

    pieces: list[tuple[float, float, float]] = []
    for path in wire.paths:
        for start, end in itertools.pairwise(path):
            if vertical and abs(start.x - end.x) < _EPSILON and abs(start.y - end.y) > _EPSILON:
                pieces.append((start.x, *sorted((start.y, end.y))))
            elif (
                not vertical
                and abs(start.y - end.y) < _EPSILON
                and abs(start.x - end.x) > _EPSILON
            ):
                pieces.append((start.y, *sorted((start.x, end.x))))
    pieces.sort()
    merged: list[list[float]] = []
    for coordinate, low, high in pieces:
        if (
            merged
            and abs(merged[-1][0] - coordinate) < _EPSILON
            and low <= merged[-1][2] + _EPSILON
        ):
            merged[-1][2] = max(merged[-1][2], high)
        else:
            merged.append([coordinate, low, high])
    runs = []
    for coordinate, low, high in merged:
        members = [
            (path_index, vertex_index)
            for path_index, path in enumerate(wire.paths)
            for vertex_index, point in enumerate(path)
            if abs((point.x if vertical else point.y) - coordinate) < _EPSILON
            and low - _EPSILON <= (point.y if vertical else point.x) <= high + _EPSILON
        ]
        fixed = wire.pinned or any(
            wire.terminal_clearance(wire.paths[path_index][vertex_index]) is not None
            for path_index, vertex_index in members
        )
        runs.append(_Run(wire_index, coordinate, low, high, members, fixed))
    return runs


# -- bounds and wishes ---------------------------------------------------------------


def _space(
    low: float,
    high: float,
    position: float,
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    boundary: Rect | None,
    vertical: bool,
    margin: float = 0.0,
) -> tuple[float, float]:
    """How far a run spanning ``low..high`` at ``position`` may move before it hits something.

    With ``margin`` the walls count that much thicker: the room a run should
    keep from a container edge, rather than the room it must.
    """

    lower, upper = float("-inf"), float("inf")
    for rect in obstacles:
        near, far = (rect.left, rect.right) if vertical else (rect.top, rect.bottom)
        across_low, across_high = (rect.top, rect.bottom) if vertical else (rect.left, rect.right)
        if across_high <= low + _EPSILON or across_low >= high - _EPSILON:
            continue
        if far <= position + _EPSILON:
            lower = max(lower, far)
        elif near >= position - _EPSILON:
            upper = min(upper, near)
    for rect in walls:
        edges = (rect.left, rect.right) if vertical else (rect.top, rect.bottom)
        across_low, across_high = (rect.top, rect.bottom) if vertical else (rect.left, rect.right)
        if across_high <= low + _EPSILON or across_low >= high - _EPSILON:
            continue
        for edge in edges:
            if edge <= position + _EPSILON:
                lower = max(lower, edge + margin)
            else:
                upper = min(upper, edge - margin)
    if boundary is not None:
        low_edge, high_edge = (
            (boundary.left, boundary.right) if vertical else (boundary.top, boundary.bottom)
        )
        if low_edge <= position <= high_edge:
            lower, upper = max(lower, low_edge), min(upper, high_edge)
    return lower, upper


def _reach(
    wire: Wire,
    members: list[tuple[int, int]],
    vertical: bool,
) -> tuple[float, float, set[int]]:
    """How far the pieces hanging off a run let it travel, and which ways they go.

    A piece must neither vanish nor reach through the port at its far end, so its
    far end bounds the run -- a port by its clearance. Pieces joining two members
    of the same run are the run's own jogs and bound nothing.
    """

    own = set(members)
    reach_low, reach_high = float("-inf"), float("inf")
    sides: set[int] = set()
    for path_index, vertex_index in members:
        path = wire.paths[path_index]
        for neighbour in (vertex_index - 1, vertex_index + 1):
            if not 0 <= neighbour < len(path) or (path_index, neighbour) in own:
                continue
            here, there = path[vertex_index], path[neighbour]
            along = (there.x - here.x) if vertical else (there.y - here.y)
            if abs(along) < _EPSILON:
                continue
            far = there.x if vertical else there.y
            margin = wire.margin(there)
            if along < 0:
                sides.add(-1)
                reach_low = max(reach_low, far + margin)
            else:
                sides.add(1)
                reach_high = min(reach_high, far - margin)
    # A branch point sits *inside* a trunk piece of another path of the wire:
    # moving the run slides the branch along that trunk, which reaches both ways.
    for path_index, vertex_index in members:
        here = wire.paths[path_index][vertex_index]
        for path in wire.paths:
            for start, end in itertools.pairwise(path):
                level = abs(start.y - end.y) < _EPSILON and abs(start.y - here.y) < _EPSILON
                if vertical and level:
                    low, high = sorted((start.x, end.x))
                    inside = low + _EPSILON < here.x < high - _EPSILON
                    ends = ((start, start.x), (end, end.x))
                elif (
                    not vertical
                    and abs(start.x - end.x) < _EPSILON
                    and abs(start.x - here.x) < _EPSILON
                ):
                    low, high = sorted((start.y, end.y))
                    inside = low + _EPSILON < here.y < high - _EPSILON
                    ends = ((start, start.y), (end, end.y))
                else:
                    continue
                if not inside:
                    continue
                for point, far in ends:
                    margin = wire.margin(point)
                    if far < (here.x if vertical else here.y):
                        sides.add(-1)
                        reach_low = max(reach_low, far + margin)
                    else:
                        sides.add(1)
                        reach_high = min(reach_high, far - margin)
    return reach_low, reach_high, sides


def _bound(
    run: _Run,
    wires: list[Wire],
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    boundary: Rect | None,
    vertical: bool,
) -> None:
    """How far ``run`` may travel, and where it would like to be."""

    run.desired = run.coordinate
    if run.fixed:
        run.lower = run.upper = run.coordinate
        run.weight = _FIXED
        return
    position = run.coordinate
    lower, upper = _space(run.low, run.high, position, obstacles, walls, boundary, vertical)
    soft_lower, soft_upper = _space(
        run.low, run.high, position, obstacles, walls, boundary, vertical, WALL_MARGIN
    )
    reach_low, reach_high, sides = _reach(wires[run.wire], run.members, vertical)
    lower, upper = max(lower, reach_low), min(upper, reach_high)
    if lower > position:
        lower = position
    if upper < position:
        upper = position
    run.lower, run.upper = lower, upper
    run.weight = _STAY
    # Where it would rather be: clear of container edges when it can be.
    preferred_low = max(lower, soft_lower)
    preferred_high = min(upper, soft_upper)
    if preferred_low <= preferred_high:
        run.desired = min(max(position, preferred_low), preferred_high)
    wire = wires[run.wire]
    if sides == {-1, 1}:
        # A crossbar between two ports, or a trunk between a hub and its
        # branches: the middle of what it may occupy reads as meant, unless the
        # author said where in it the rail goes.
        left = max(lower, reach_low, soft_lower)
        right = min(upper, reach_high, soft_upper)
        if left <= right and left > float("-inf") and right < float("inf"):
            run.desired = (left + right) / 2.0
            run.weight = _CENTRE
            if wire.rail_at is not None and wire.flow_from is not None and wire.flow_to is not None:
                # A fraction of the way from where the flow starts to where it
                # ends, port to port; clamped into what clearances allow, and
                # said so when it has to be.
                start = wire.flow_from.x if vertical else wire.flow_from.y
                end = wire.flow_to.x if vertical else wire.flow_to.y
                if abs(end - start) > _EPSILON:
                    wanted = start + (end - start) * wire.rail_at
                    placed = min(max(wanted, left), right)
                    run.desired = placed
                    run.weight = _STAY
                    wire.rail_clamped = (
                        None if abs(placed - wanted) < 1e-6 else (placed - start) / (end - start)
                    )
    if wire.rail_side is not None and (wire.rail_side in {Side.EAST, Side.WEST}) is vertical:
        # A rail pinned to one side of its corridor goes as far that way as it may.
        high_side = wire.rail_side in {Side.EAST, Side.SOUTH}
        bound = min(upper, soft_upper) if high_side else max(lower, soft_lower)
        if bound not in (float("inf"), float("-inf")) and len(run.members) > 2:
            run.desired = bound
            run.weight = _STAY


def _unify(
    runs: list[_Run],
    wires: list[Wire],
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    boundary: Rect | None,
    vertical: bool,
) -> list[_Run]:
    """Merge parallel runs of one wire joined by a jog, wherever one line can serve both.

    After libavoid's unifying pre-pass: a route that steps sideways by a few
    points to get past something it has since been moved clear of -- or that the
    grid made it hug -- is drawn straight when a single coordinate lies within
    what both of its runs may occupy. Closest pairs merge first.
    """

    while True:
        candidates = []
        for first_index, first in enumerate(runs):
            for second_index in range(first_index + 1, len(runs)):
                second = runs[second_index]
                if first.wire != second.wire or (first.fixed and second.fixed):
                    continue
                if not _jogged(wires[first.wire], first, second, vertical):
                    continue
                candidates.append(
                    (abs(first.coordinate - second.coordinate), first_index, second_index)
                )
        merged = None
        for _, first_index, second_index in sorted(candidates):
            merged = _merged(
                runs[first_index], runs[second_index], wires, obstacles, walls, boundary, vertical
            )
            if merged is not None:
                runs = [
                    run
                    for index, run in enumerate(runs)
                    if index not in {first_index, second_index}
                ] + [merged]
                break
        if merged is None:
            return runs


def _jogged(wire: Wire, first: _Run, second: _Run, vertical: bool) -> bool:
    """True when a piece of ``wire`` steps straight from ``first`` across to ``second``.

    Read geometrically, not by vertex order: a branch of a tree may join its trunk
    in the middle of another branch's piece, and that step is a jog all the same.
    """

    low, high = sorted((first.coordinate, second.coordinate))
    for path in wire.paths:
        for start, end in itertools.pairwise(path):
            if vertical:
                if abs(start.y - end.y) > _EPSILON:
                    continue
                along, span = start.y, sorted((start.x, end.x))
            else:
                if abs(start.x - end.x) > _EPSILON:
                    continue
                along, span = start.x, sorted((start.y, end.y))
            if span[0] > low + _EPSILON or span[1] < high - _EPSILON:
                continue
            if all(run.low - _EPSILON <= along <= run.high + _EPSILON for run in (first, second)):
                return True
    return False


def _merged(
    first: _Run,
    second: _Run,
    wires: list[Wire],
    obstacles: tuple[Rect, ...],
    walls: tuple[Rect, ...],
    boundary: Rect | None,
    vertical: bool,
) -> _Run | None:
    members = first.members + second.members
    low, high = min(first.low, second.low), max(first.high, second.high)
    fixed = first.fixed or second.fixed
    if fixed:
        choices = [first.coordinate if first.fixed else second.coordinate]
    else:
        longer, shorter = (
            (first, second)
            if first.high - first.low >= second.high - second.low
            else (second, first)
        )
        choices = [longer.coordinate, shorter.coordinate]
    reach_low, reach_high, sides = _reach(wires[first.wire], members, vertical)
    for coordinate in choices:
        if not reach_low - _EPSILON <= coordinate <= reach_high + _EPSILON:
            continue
        lower, upper = _space(low, high, coordinate, obstacles, walls, boundary, vertical)
        if not lower - _EPSILON <= coordinate <= upper + _EPSILON:
            continue
        # Moving either run onto the shared line must not sweep through anything.
        if not all(
            _clear_sweep(run, coordinate, obstacles, vertical) for run in (first, second)
        ):
            continue
        run = _Run(first.wire, coordinate, low, high, members, fixed)
        run.lower, run.upper = (
            (coordinate, coordinate) if fixed else (max(lower, reach_low), min(upper, reach_high))
        )
        run.desired = coordinate
        run.weight = _FIXED if fixed else _STAY
        if not fixed and sides == {-1, 1}:
            left, right = run.lower, run.upper
            if left > float("-inf") and right < float("inf"):
                run.desired = (left + right) / 2.0
                run.weight = _CENTRE
        return run
    return None


def _clear_sweep(run: _Run, coordinate: float, obstacles: tuple[Rect, ...], vertical: bool) -> bool:
    low, high = sorted((run.coordinate, coordinate))
    for rect in obstacles:
        near, far = (rect.left, rect.right) if vertical else (rect.top, rect.bottom)
        across_low, across_high = (rect.top, rect.bottom) if vertical else (rect.left, rect.right)
        if across_high <= run.low + _EPSILON or across_low >= run.high - _EPSILON:
            continue
        if far > low + _EPSILON and near < high - _EPSILON:
            return False
    return True


# -- ordering ------------------------------------------------------------------------


def _overlap(first: _Run, second: _Run) -> float:
    return min(first.high, second.high) - max(first.low, second.low)


def _caption_rooms(runs: list[_Run], wires: list[Wire]) -> dict[tuple[int, int], float]:
    """``{(above, below): room}`` for each horizontal run over a captioned run's caption."""

    carriers: dict[int, int] = {}
    for index, run in enumerate(runs):
        if wires[run.wire].caption is None:
            continue
        best = carriers.get(run.wire)
        if best is None or run.high - run.low > runs[best].high - runs[best].low + _EPSILON:
            carriers[run.wire] = index
    rooms: dict[tuple[int, int], float] = {}
    for below in carriers.values():
        carrier = runs[below]
        room, width = wires[carrier.wire].caption  # type: ignore[misc]
        middle = (carrier.low + carrier.high) / 2.0
        low, high = middle - width / 2.0, middle + width / 2.0
        for above, run in enumerate(runs):
            if run.wire == carrier.wire or run.coordinate > carrier.coordinate + _EPSILON:
                continue
            if carrier.coordinate - run.coordinate >= room or (run.fixed and carrier.fixed):
                continue
            if min(run.high, high) - max(run.low, low) > _EPSILON:
                rooms[(above, below)] = room
    return rooms


def _ordered(
    runs: list[_Run],
    wires: list[Wire],
    spacing: float,
    vertical: bool,
    rooms: dict[tuple[int, int], float] | None = None,
) -> list[tuple[int, int]]:
    """Pairs ``(left, right)`` of runs that must keep a lane between them, in order.

    A pair in ``rooms`` is kept in the order it has -- the caption goes between.
    """

    by_position = sorted(range(len(runs)), key=lambda index: (runs[index].coordinate, index))
    pairs: list[tuple[int, int]] = []
    ties: dict[tuple[int, int], int] = {}
    for position, first in enumerate(by_position):
        for second in by_position[position + 1 :]:
            one, two = runs[first], runs[second]
            if rooms and (first, second) in rooms:
                pairs.append((first, second))
                continue
            # Runs that cannot come within a lane of each other need no constraint.
            if two.lower >= one.upper + spacing:
                continue
            if one.wire == two.wire or _overlap(one, two) < -_EPSILON:
                continue
            if one.fixed and two.fixed:
                continue
            if abs(one.coordinate - two.coordinate) < _EPSILON:
                ties[(first, second)] = _preferred(one, two, wires, spacing, vertical)
            elif abs(one.coordinate - two.coordinate) < 2.0 * spacing - _EPSILON:
                # Closer than a lane, so they are about to be pushed apart
                # anyway: their order is free, and it goes to whichever crosses
                # less, keeping the order the search found when neither does.
                before, after = _scores(one, two, wires, spacing, vertical)
                pairs.append((second, first) if after < before else (first, second))
            else:
                pairs.append((first, second))
    for (first, second), choice in ties.items():
        pairs.append((first, second) if choice <= 0 else (second, first))
    return _acyclic(pairs, runs)


def _scores(
    one: _Run, two: _Run, wires: list[Wire], spacing: float, vertical: bool
) -> tuple[int, int]:
    """Crossings between the two wires with ``one`` before ``two``, and after it."""

    middle = (one.coordinate + two.coordinate) / 2.0
    scores = []
    for sign in (-1, 1):
        first = _shifted(
            wires[one.wire], one, middle + sign * spacing / 2.0 - one.coordinate, vertical
        )
        second = _shifted(
            wires[two.wire], two, middle - sign * spacing / 2.0 - two.coordinate, vertical
        )
        scores.append(_crossings(first, second))
    return scores[0], scores[1]


def _preferred(one: _Run, two: _Run, wires: list[Wire], spacing: float, vertical: bool) -> int:
    """-1 if ``one`` should sit before ``two``, 1 if after: whichever crosses less."""

    scores = _scores(one, two, wires, spacing, vertical)
    if scores[0] != scores[1]:
        return -1 if scores[0] < scores[1] else 1
    # Equal: the run whose wire reaches further toward the low side goes low,
    # so a bundle fans out the way its members leave.
    first = _lean(wires[one.wire], one, vertical)
    second = _lean(wires[two.wire], two, vertical)
    return -1 if first <= second else 1


def _lean(wire: Wire, run: _Run, vertical: bool) -> float:
    """Where the pieces hanging off ``run`` go, as a signed amount along its normal."""

    total = 0.0
    for path_index, vertex_index in run.members:
        path = wire.paths[path_index]
        for neighbour in (vertex_index - 1, vertex_index + 1):
            if 0 <= neighbour < len(path):
                here, there = path[vertex_index], path[neighbour]
                total += (there.x - here.x) if vertical else (there.y - here.y)
    return total


def _shifted(wire: Wire, run: _Run, offset: float, vertical: bool) -> list[list[Point]]:
    paths = [list(path) for path in wire.paths]
    for path_index, vertex_index in run.members:
        point = paths[path_index][vertex_index]
        paths[path_index][vertex_index] = (
            Point(point.x + offset, point.y) if vertical else Point(point.x, point.y + offset)
        )
    return paths


def _crossings(first: list[list[Point]], second: list[list[Point]]) -> int:
    count = 0
    for path in first:
        for a, b in itertools.pairwise(path):
            for other in second:
                for c, d in itertools.pairwise(other):
                    if _cross(a, b, c, d):
                        count += 1
    return count


def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """True when two orthogonal segments cross, or lie on one line and overlap.

    An overlap counts as a crossing: two runs of different connectors drawn on
    top of each other read as one line that forks for no reason.
    """

    if abs(a.y - b.y) < _EPSILON and abs(c.y - d.y) < _EPSILON and abs(a.y - c.y) < _EPSILON:
        low, high = sorted((a.x, b.x))
        other_low, other_high = sorted((c.x, d.x))
        return min(high, other_high) - max(low, other_low) > _EPSILON
    if abs(a.x - b.x) < _EPSILON and abs(c.x - d.x) < _EPSILON and abs(a.x - c.x) < _EPSILON:
        low, high = sorted((a.y, b.y))
        other_low, other_high = sorted((c.y, d.y))
        return min(high, other_high) - max(low, other_low) > _EPSILON
    return _perpendicular_cross(a, b, c, d)


def _perpendicular_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    first_horizontal = abs(a.y - b.y) < _EPSILON
    second_horizontal = abs(c.y - d.y) < _EPSILON
    if first_horizontal == second_horizontal:
        return False
    (h1, h2), (v1, v2) = ((a, b), (c, d)) if first_horizontal else ((c, d), (a, b))
    x0, x1 = sorted((h1.x, h2.x))
    y0, y1 = sorted((v1.y, v2.y))
    return x0 + _EPSILON < v1.x < x1 - _EPSILON and y0 + _EPSILON < h1.y < y1 - _EPSILON


def _acyclic(pairs: list[tuple[int, int]], runs: list[_Run]) -> list[tuple[int, int]]:
    """Drop the constraints that would close a cycle, latest-added first."""

    successors: dict[int, set[int]] = defaultdict(set)
    kept = []
    for left, right in pairs:
        if _reaches(successors, right, left):
            continue
        successors[left].add(right)
        kept.append((left, right))
    return kept


def _reaches(successors: dict[int, set[int]], start: int, goal: int) -> bool:
    stack, seen = [start], {start}
    while stack:
        item = stack.pop()
        if item == goal:
            return True
        for following in successors.get(item, ()):
            if following not in seen:
                seen.add(following)
                stack.append(following)
    return False


# -- solving -------------------------------------------------------------------------


def _solve(
    runs: list[_Run],
    order: list[tuple[int, int]],
    gap: float,
    rooms: dict[tuple[int, int], float] | None = None,
) -> list[float] | None:
    """Positions for every run at lane ``gap`` -- or the room a caption between
    two runs needs -- or ``None`` if the bounds cannot hold."""

    desired = [run.desired for run in runs]
    weights = [run.weight for run in runs]
    constraints: list[tuple[int, int, float]] = [
        (left, right, max(gap, (rooms or {}).get((left, right), 0.0))) for left, right in order
    ]
    bounds: list[tuple[int, float, bool]] = []
    for index, run in enumerate(runs):
        if run.fixed:
            continue
        if run.lower > float("-inf"):
            bounds.append((index, run.lower, True))
        if run.upper < float("inf"):
            bounds.append((index, run.upper, False))
    for index, value, is_lower in bounds:
        dummy = len(desired)
        desired.append(value)
        weights.append(_BOUND)
        constraints.append((dummy, index, 0.0) if is_lower else (index, dummy, 0.0))
    positions = solve(desired, weights, constraints)
    anchors = positions[len(runs) :]
    for (_, value, _), placed in zip(bounds, anchors, strict=True):
        if abs(placed - value) > 0.05:
            return None
    for index, run in enumerate(runs):
        if run.fixed and abs(positions[index] - run.coordinate) > 0.05:
            return None
    return [
        run.coordinate if run.fixed else positions[index] for index, run in enumerate(runs)
    ]


def _same(first: Point, second: Point) -> bool:
    return abs(first.x - second.x) < 1e-6 and abs(first.y - second.y) < 1e-6
