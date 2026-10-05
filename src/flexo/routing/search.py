"""Bend-aware orthogonal path search over a sparse grid of interesting lines.

This is the libavoid-style core of the router. Every connector is routed on its
own, against the components and containers of the figure but *not* against the
other connectors: two routes that want the same corridor may both take it, and
the separation pass afterwards orders them through it and spaces them apart.
Routing each connector independently is what makes the result independent of
the order connectors are authored in.

The search runs over states ``(x index, y index, heading)`` of a grid whose
lines are the edges of every obstacle, every clearance ring, every port escape,
and the midlines between them. A move either continues one grid step along the
heading or turns 90 degrees in place for ``bend`` cost, so the cost of a route is
exactly its length plus its bends plus whatever it pays for the zones it passes
through. Obstacles are *zones with a price*, never walls: a route through a
component costs a great deal, a route grazing one a little, and so a route
always exists. When the only way is through something, the result says so and
lint reports it, instead of the whole figure failing to compile.

A* is guided by the Manhattan distance plus a lower bound on the bends still
needed to arrive heading the required way (after Wybrow, Marriott and Stuckey,
"Orthogonal connector routing", GD 2009). Ties are broken by insertion order --
straight on first, then the turns -- so the search is deterministic and prefers
the straighter of two equally cheap routes.
"""

from __future__ import annotations

import contextvars
import heapq
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count

from flexo.draft import GivenUp, newer_wanted
from flexo.geometry import Point, Rect

EAST, WEST, SOUTH, NORTH = 0, 1, 2, 3
_DX = (1, -1, 0, 0)
_DY = (0, 0, 1, -1)
_OPPOSITE = (WEST, EAST, NORTH, SOUTH)
_PERPENDICULAR = ((SOUTH, NORTH), (NORTH, SOUTH), (WEST, EAST), (EAST, WEST))
"""The two turns out of each heading, right-hand turn first."""

_DONE = 2
"""The ``turned`` value of a finished route in the frontier."""

_MERGE = 1e-6
"""Grid coordinates closer than this (points) are one line: ports must keep their exact lines."""


@dataclass(frozen=True, slots=True)
class Zone:
    """A rectangle a route pays ``cost`` per point of length to travel inside."""

    rect: Rect
    cost: float


def unit(heading: int) -> tuple[int, int]:
    return _DX[heading], _DY[heading]


def _minimum_bends(px: float, py: float, heading: int, gx: float, gy: float, arrive: int) -> int:
    """A lower bound on the bends between heading ``heading`` at p and ``arrive`` at g."""

    dx, dy = gx - px, gy - py
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        if heading == arrive:
            return 0
        return 2 if heading == _OPPOSITE[arrive] else 1
    ux, uy = _DX[heading], _DY[heading]
    ax, ay = _DX[arrive], _DY[arrive]
    forward = dx * ux + dy * uy
    lateral = abs(dx * uy - dy * ux)
    if heading == arrive:
        if forward > 1e-9:
            return 0 if lateral < 1e-9 else 2
        return 4
    if heading == _OPPOSITE[arrive]:
        return 2 if lateral > 1e-9 else 4
    ahead = dx * ax + dy * ay
    return 1 if forward >= -1e-9 and ahead > 1e-9 else 3


class Grid:
    """The interesting lines of one routing problem and the price of every step."""

    def __init__(
        self,
        xs: list[float],
        ys: list[float],
        zones: tuple[Zone, ...],
        *,
        boundary: Rect | None = None,
        outside_cost: float = 0.0,
        window: tuple[Rect, ...] = (),
    ) -> None:
        self.xs = _merged(xs)
        self.ys = _merged(ys)
        self.zones = zones
        self.boundary = boundary
        self.outside_cost = outside_cost
        # The cells a search may step to: all, or (given a ``window`` of rectangles) those
        # within them -- within their bounds (least x, y, greatest x, y), and marked in
        # ``inside`` by cell (x * rows + y).
        rows = len(self.ys)
        self.within = (0, 0, len(self.xs) - 1, rows - 1)
        self.inside: bytearray | None = None
        self.windowed = bool(window)
        if window:
            spans = [
                (
                    bisect_left(self.xs, rect.left - 1e-6),
                    bisect_left(self.ys, rect.top - 1e-6),
                    bisect_right(self.xs, rect.right + 1e-6) - 1,
                    bisect_right(self.ys, rect.bottom + 1e-6) - 1,
                )
                for rect in window
            ]
            self.within = (
                min(span[0] for span in spans),
                min(span[1] for span in spans),
                max(span[2] for span in spans),
                max(span[3] for span in spans),
            )
            self.inside = bytearray(len(self.xs) * rows)
            for left, top, right, bottom in spans:
                for column in range(left, right + 1):
                    start = column * rows
                    self.inside[start + top : start + bottom + 1] = b"\x01" * (bottom - top + 1)
        self._row_zones: dict[int, list[tuple[float, float, float]]] = {}
        self._column_zones: dict[int, list[tuple[float, float, float]]] = {}
        self._steps: dict[int, float] = {}
        self.reached: tuple[int, int, int, int] | None = None
        """The cells (least x, y, greatest x, y) searches priced a step out of, with their
        ``extra`` or in a window: nothing beyond a step from them changed what they found."""

    def index(self, point: Point) -> tuple[int, int]:
        return _nearest(self.xs, point.x), _nearest(self.ys, point.y)

    def point(self, ix: int, iy: int) -> Point:
        return Point(self.xs[ix], self.ys[iy])

    def _sweep(self) -> None:
        """Every row's and column's zones in one pass: each zone joins only the
        lines it strictly spans (found by bisection), in zone order."""

        rows: dict[int, list[tuple[float, float, float]]] = {i: [] for i in range(len(self.ys))}
        columns: dict[int, list[tuple[float, float, float]]] = {i: [] for i in range(len(self.xs))}
        for zone in self.zones:
            rect = zone.rect
            first = bisect_right(self.ys, rect.top + 1e-6)
            for iy in range(first, bisect_left(self.ys, rect.bottom - 1e-6)):
                rows[iy].append((rect.left, rect.right, zone.cost))
            first = bisect_right(self.xs, rect.left + 1e-6)
            for ix in range(first, bisect_left(self.xs, rect.right - 1e-6)):
                columns[ix].append((rect.top, rect.bottom, zone.cost))
        self._row_zones, self._column_zones = rows, columns

    def _row(self, iy: int) -> list[tuple[float, float, float]]:
        if not self._row_zones:
            self._sweep()
        return self._row_zones[iy]

    def _column(self, ix: int) -> list[tuple[float, float, float]]:
        if not self._column_zones:
            self._sweep()
        return self._column_zones[ix]

    def step_cost(self, ix: int, iy: int, heading: int) -> float:
        """The price of one grid step from ``(ix, iy)`` along ``heading``."""

        key = self._step(ix, iy, heading)
        cached = self._steps.get(key)
        if cached is None:
            cached = self._steps[key] = self._price(ix, iy, heading)
        return cached

    def _step(self, ix: int, iy: int, heading: int) -> int:
        """The step from ``(ix, iy)`` along ``heading`` as a number, the same both ways."""

        if heading == EAST:
            return (ix * len(self.ys) + iy) << 1
        if heading == WEST:
            return ((ix - 1) * len(self.ys) + iy) << 1
        if heading == SOUTH:
            return ((ix * len(self.ys) + iy) << 1) | 1
        return ((ix * len(self.ys) + iy - 1) << 1) | 1

    def _price(self, ix: int, iy: int, heading: int) -> float:
        if heading in (EAST, WEST):
            other = ix + _DX[heading]
            low, high = sorted((self.xs[ix], self.xs[other]))
            middle = (low + high) / 2.0
            rate = 1.0 + sum(cost for left, right, cost in self._row(iy) if left < middle < right)
            y = self.ys[iy]
            outside = self.boundary is not None and not (
                self.boundary.top - 1e-6 <= y <= self.boundary.bottom + 1e-6
                and self.boundary.left - 1e-6 <= middle <= self.boundary.right + 1e-6
            )
        else:
            other = iy + _DY[heading]
            low, high = sorted((self.ys[iy], self.ys[other]))
            middle = (low + high) / 2.0
            rate = 1.0 + sum(
                cost for top, bottom, cost in self._column(ix) if top < middle < bottom
            )
            x = self.xs[ix]
            outside = self.boundary is not None and not (
                self.boundary.left - 1e-6 <= x <= self.boundary.right + 1e-6
                and self.boundary.top - 1e-6 <= middle <= self.boundary.bottom + 1e-6
            )
        if outside:
            rate += self.outside_cost
        return (high - low) * rate

    def route(
        self,
        start: Point,
        depart: int,
        goal: Point,
        arrive: int | None,
        *,
        bend: float,
        extra: StepPrice | None = None,
    ) -> tuple[tuple[Point, ...], float]:
        """The cheapest route from ``start`` heading ``depart`` to ``goal`` heading ``arrive``.

        ``start`` and ``goal`` must be grid points (the caller puts their lines
        in). The route always exists on a connected grid; the second value is
        its cost, which says how much it had to pay to get through.
        """

        return self.route_from_tree(
            ((start, depart, 0.0),), goal, arrive, bend=bend, extra=extra
        )

    def route_from_tree(
        self,
        sources: tuple[tuple[Point, int | None, float], ...],
        goal: Point,
        arrive: int | None,
        *,
        bend: float,
        extra: StepPrice | None = None,
        alternatives: tuple[tuple[Point, float], ...] = (),
        haste: float = 1.0,
    ) -> tuple[tuple[Point, ...], float]:
        """Cheapest route from any of ``sources`` to ``goal``, arriving heading ``arrive``.

        Each source is ``(point, heading, initial cost)``; a heading of ``None``
        means the route may leave that point in any direction (a point on an
        existing tree, where the new branch will make a T).

        ``alternatives`` are further goals, each ``(point, surcharge)``: the
        route may end at any of them instead, paying the surcharge on top.

        A ``haste`` above 1 weighs the distance still to go that much more: the route
        found costs at most that many times the cheapest, found searching far less of
        the grid (a draft's: flexo.draft).
        """

        xs, ys = self.xs, self.ys
        columns, rows = len(xs), len(ys)
        gx, gy = self.index(goal)
        endings = {(gx, gy): 0.0}
        for point, surcharge in alternatives:
            endings.setdefault(self.index(point), surcharge)
        targets = [(xs[ex], ys[ey], charge) for (ex, ey), charge in endings.items()]
        # (Cells, steps and states are numbered, for speed: a cell is ``x * rows + y``, a
        # state ``(cell << 2 | heading) << 1 | turned``.)
        finishing = {ex * rows + ey: charge for (ex, ey), charge in endings.items()}

        # The estimate depends only on the state's cell and heading, and a state is
        # pushed each time its cost improves: remember it rather than recompute it
        # against every goal (a long pin edge is many goals).
        estimates: dict[int, float] = {}
        estimated = estimates.get
        inf = float("inf")
        bends = _minimum_bends

        def estimate_from(px: float, py: float, heading: int) -> float:
            # The distance to the nearest goal, and the bends still needed to arrive.
            found = inf
            for tx, ty, charge in targets:
                distance = abs(tx - px) + abs(ty - py)
                if arrive is not None:
                    distance = distance + bend * bends(px, py, heading, tx, ty, arrive)
                if charge + distance < found:
                    found = charge + distance
            return found if haste == 1.0 else found * haste

        # A traffic price depends only on the step: remember it for the search.
        priced: dict[int, float] = {}
        priced_of = priced.get
        steps = self._steps
        step_of = steps.get
        price_of = self._price
        dxs, dys, turns = _DX, _DY, _PERPENDICULAR
        push, pop = heapq.heappush, heapq.heappop
        # A state is (x, y, heading, turned): ``turned`` says the last move was a
        # turn in place, and a second one there would reverse the route on itself.
        frontier: list[tuple[float, float, int, int, int, int, int]] = []
        best: dict[int, float] = {}
        best_of = best.get
        previous: dict[int, int | None] = {}
        serial = count()
        for point, heading, initial in sources:
            ix, iy = self.index(point)
            headings = (heading,) if heading is not None else (EAST, WEST, SOUTH, NORTH)
            for current in headings:
                state = ((ix * rows + iy) << 2 | current) << 1
                if initial < best_of(state, inf):
                    best[state] = initial
                    previous[state] = None
                    estimate = initial + estimate_from(xs[ix], ys[iy], current)
                    push(frontier, (estimate, initial, next(serial), ix, iy, current, 0))
        final: int | None = None
        final_cost = inf
        finished: dict[int, int] = {}
        finished_cost: dict[int, float] = {}
        work = 0
        ceiling = _CEILING[0]
        least_x, least_y, most_x, most_y = columns, rows, -1, -1
        first_x, first_y, last_x, last_y = self.within
        inside = self.inside
        # (Where the search reached is kept where it says something: priced ink, or a window.)
        tracked = extra is not None or self.windowed
        # (A drawing given up for a newer one stops here: flexo.draft.)
        newer = newer_wanted()
        while frontier:
            _, cost, _, ix, iy, heading, turned = pop(frontier)
            work += 1
            if not work & 1023:
                if ceiling is not None and _WORK[0] + work > ceiling:
                    _WORK[0] += work
                    raise TooDear
                if newer is not None and newer():
                    _WORK[0] += work
                    raise GivenUp
            cell = ix * rows + iy
            if turned == _DONE:
                final, final_cost = finished[cell << 2 | heading], cost
                break
            state = (cell << 2 | heading) << 1 | turned
            if cost > best_of(state, inf) + 1e-9:
                continue
            surcharge = finishing.get(cell)
            if surcharge is not None and (arrive is None or heading == arrive):
                # Finishing is one more move, priced by where it finishes.
                done = cell << 2 | heading
                total = cost + surcharge
                if total < finished_cost.get(done, inf):
                    finished_cost[done] = total
                    finished[done] = state
                    push(frontier, (total, total, next(serial), ix, iy, heading, _DONE))
            nx, ny = ix + dxs[heading], iy + dys[heading]
            if (
                first_x <= nx <= last_x
                and first_y <= ny <= last_y
                and (inside is None or inside[nx * rows + ny])
            ):
                # The step's price, the same whichever way it is taken.
                if heading < SOUTH:
                    step = ((ix if heading == EAST else nx) * rows + iy) << 1
                else:
                    step = (ix * rows + (iy if heading == SOUTH else ny)) << 1 | 1
                price = step_of(step)
                if price is None:
                    price = steps[step] = price_of(ix, iy, heading)
                if tracked:
                    if ix < least_x:
                        least_x = ix
                    if ix > most_x:
                        most_x = ix
                    if iy < least_y:
                        least_y = iy
                    if iy > most_y:
                        most_y = iy
                if extra is not None:
                    toward = cell << 2 | heading
                    charge = priced_of(toward)
                    if charge is None:
                        charge = priced[toward] = extra(self, ix, iy, heading)
                    price += charge
                total = cost + price
                ahead = (nx * rows + ny) << 2 | heading
                following = ahead << 1
                if total + 1e-9 < best_of(following, inf):
                    best[following] = total
                    previous[following] = state
                    known = estimated(ahead)
                    if known is None:
                        known = estimates[ahead] = estimate_from(xs[nx], ys[ny], heading)
                    push(frontier, (total + known, total, next(serial), nx, ny, heading, 0))
            if not turned:
                total = cost + bend
                for turn in turns[heading]:
                    facing = cell << 2 | turn
                    following = facing << 1 | 1
                    if total + 1e-9 < best_of(following, inf):
                        best[following] = total
                        previous[following] = state
                        known = estimated(facing)
                        if known is None:
                            known = estimates[facing] = estimate_from(xs[ix], ys[iy], turn)
                        push(frontier, (total + known, total, next(serial), ix, iy, turn, 1))
        _WORK[0] += work
        if most_x >= 0:
            if self.reached is not None:
                least_x, least_y = min(least_x, self.reached[0]), min(least_y, self.reached[1])
                most_x, most_y = max(most_x, self.reached[2]), max(most_y, self.reached[3])
            self.reached = (least_x, least_y, most_x, most_y)
        if ceiling is not None and _WORK[0] > ceiling:
            raise TooDear
        if final is None:
            raise RuntimeError("routing grid is disconnected")
        counting = _COUNTING.get()
        if counting is not None:
            counting.append(work)
        cells: list[int] = []
        walk: int | None = final
        while walk is not None:
            if not cells or cells[-1] != walk >> 3:
                cells.append(walk >> 3)
            walk = previous[walk]
        cells.reverse()
        return simplify(tuple(self.point(*divmod(cell, rows)) for cell in cells)), final_cost


type StepPrice = "callable[[Grid, int, int, int], float]"

_WORK = [0]
"""Search steps taken in this process: a machine-independent measure of effort."""

_CEILING: list[int | None] = [None]
"""The search work past which a search gives up (``TooDear``), while one is set."""


class TooDear(Exception):
    """A search that went past the work it was allowed (``ceiling``)."""


def ceiling(limit: int | None) -> None:
    """Let searches run until the search work reaches ``limit`` -- or, given None, forever."""

    _CEILING[0] = limit


_COUNTING: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "flexo_counting", default=None
)


@contextmanager
def counted() -> Iterator[list[int]]:
    """The work each search made within took, in order (for ``spend``)."""

    works: list[int] = []
    token = _COUNTING.set(works)
    try:
        yield works
    finally:
        _COUNTING.reset(token)


def spend(works: list[int]) -> None:
    """Count searches as made that were not, their routes known (``counted`` when they were
    made): the search work goes up as theirs did, and gives up (``TooDear``) where theirs
    would have -- so what a budget of work allows is the same either way."""

    limit = _CEILING[0]
    for work in works:
        if limit is not None:
            # (A search asks every 1024 steps whether it is past the ceiling, and at its end.)
            asked = max(1024, ((limit - _WORK[0]) // 1024 + 1) * 1024)
            if asked <= work:
                _WORK[0] += asked
                raise TooDear
        _WORK[0] += work
        if limit is not None and _WORK[0] > limit:
            raise TooDear


def search_work() -> int:
    """How many search steps have been taken so far (see ``router.REPAIR_WORK``)."""

    return _WORK[0]


def simplify(points: tuple[Point, ...]) -> tuple[Point, ...]:
    """Drop repeated points and every vertex that lies on a straight run."""

    result: list[Point] = []
    for point in points:
        if result and abs(result[-1].x - point.x) < 1e-9 and abs(result[-1].y - point.y) < 1e-9:
            continue
        while len(result) >= 2:
            before, middle = result[-2], result[-1]
            vertical = abs(before.x - middle.x) < 1e-9 and abs(middle.x - point.x) < 1e-9
            horizontal = abs(before.y - middle.y) < 1e-9 and abs(middle.y - point.y) < 1e-9
            # Only a point *between* its neighbours is redundant; one where the
            # line doubles back on itself is a real vertex.
            between = (
                min(before.y, point.y) - 1e-9 <= middle.y <= max(before.y, point.y) + 1e-9
                if vertical
                else min(before.x, point.x) - 1e-9 <= middle.x <= max(before.x, point.x) + 1e-9
            )
            if not (vertical or horizontal) or not between:
                break
            result.pop()
        result.append(point)
    return tuple(result)


def _merged(values: list[float]) -> list[float]:
    ordered = sorted(values)
    result: list[float] = []
    for value in ordered:
        if result and value - result[-1] < _MERGE:
            continue
        result.append(value)
    return result


def _nearest(values: list[float], value: float) -> int:
    position = bisect_left(values, value)
    if position == 0:
        return 0
    if position == len(values):
        return len(values) - 1
    before, after = values[position - 1], values[position]
    return position if after - value < value - before else position - 1
