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

import heapq
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import count

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
    ) -> None:
        self.xs = _merged(xs)
        self.ys = _merged(ys)
        self.zones = zones
        self.boundary = boundary
        self.outside_cost = outside_cost
        self._row_zones: dict[int, list[tuple[float, float, float]]] = {}
        self._column_zones: dict[int, list[tuple[float, float, float]]] = {}
        self._steps: dict[tuple[int, int, int], float] = {}

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

        key = (ix, iy, heading)
        cached = self._steps.get(key)
        if cached is not None:
            return cached
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
        value = (high - low) * rate
        self._steps[key] = value
        return value

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
    ) -> tuple[tuple[Point, ...], float]:
        """Cheapest route from any of ``sources`` to ``goal``, arriving heading ``arrive``.

        Each source is ``(point, heading, initial cost)``; a heading of ``None``
        means the route may leave that point in any direction (a point on an
        existing tree, where the new branch will make a T).

        ``alternatives`` are further goals, each ``(point, surcharge)``: the
        route may end at any of them instead, paying the surcharge on top.
        """

        gx, gy = self.index(goal)
        endings = {(gx, gy): 0.0}
        for point, surcharge in alternatives:
            endings.setdefault(self.index(point), surcharge)
        targets = [(self.xs[ex], self.ys[ey], charge) for (ex, ey), charge in endings.items()]

        # The estimate depends only on the state's cell and heading, and a state is
        # pushed each time its cost improves: remember it rather than recompute it
        # against every goal (a long pin edge is many goals).
        estimates: dict[tuple[float, float, int], float] = {}
        single = targets[0] if len(targets) == 1 else None

        def estimate_from(px: float, py: float, heading: int) -> float:
            key = (px, py, heading)
            known = estimates.get(key)
            if known is None:
                if single is not None:
                    tx, ty, charge = single
                    known = charge + _heuristic(px, py, heading, tx, ty, arrive, bend)
                else:
                    known = min(
                        charge + _heuristic(px, py, heading, tx, ty, arrive, bend)
                        for tx, ty, charge in targets
                    )
                estimates[key] = known
            return known

        # A traffic price depends only on the step: remember it for the search.
        priced: dict[tuple[int, int, int], float] = {}
        xs, ys = self.xs, self.ys
        columns, rows = len(xs), len(ys)
        step_cost = self.step_cost
        push, pop = heapq.heappush, heapq.heappop
        inf = float("inf")
        # A state is (x, y, heading, turned): ``turned`` says the last move was a
        # turn in place, and a second one there would reverse the route on itself.
        frontier: list[tuple[float, float, int, int, int, int, int]] = []
        best: dict[tuple[int, int, int, int], float] = {}
        best_of = best.get
        previous: dict[tuple[int, int, int, int], tuple[int, int, int, int] | None] = {}
        serial = count()
        for point, heading, initial in sources:
            ix, iy = self.index(point)
            headings = (heading,) if heading is not None else (EAST, WEST, SOUTH, NORTH)
            for current in headings:
                state = (ix, iy, current, 0)
                if initial < best_of(state, inf):
                    best[state] = initial
                    previous[state] = None
                    estimate = initial + estimate_from(xs[ix], ys[iy], current)
                    push(frontier, (estimate, initial, next(serial), ix, iy, current, 0))
        final: tuple[int, int, int, int] | None = None
        final_cost = inf
        finished: dict[tuple[int, int, int, int], tuple[int, int, int, int]] = {}
        finished_cost: dict[tuple[int, int, int, int], float] = {}
        work = 0
        while frontier:
            _, cost, _, ix, iy, heading, turned = pop(frontier)
            work += 1
            if turned == _DONE:
                final, final_cost = (ix, iy, heading, 0), cost
                final = finished[final]
                break
            state = (ix, iy, heading, turned)
            if cost > best_of(state, inf) + 1e-9:
                continue
            surcharge = endings.get((ix, iy))
            if surcharge is not None and (arrive is None or heading == arrive):
                # Finishing is one more move, priced by where it finishes.
                done = (ix, iy, heading, 0)
                total = cost + surcharge
                if total < finished_cost.get(done, inf):
                    finished_cost[done] = total
                    finished[done] = state
                    push(frontier, (total, total, next(serial), ix, iy, heading, _DONE))
            nx, ny = ix + _DX[heading], iy + _DY[heading]
            if 0 <= nx < columns and 0 <= ny < rows:
                price = step_cost(ix, iy, heading)
                if extra is not None:
                    step = (ix, iy, heading)
                    charge = priced.get(step)
                    if charge is None:
                        charge = extra(self, ix, iy, heading)
                        priced[step] = charge
                    price += charge
                following = (nx, ny, heading, 0)
                total = cost + price
                if total + 1e-9 < best_of(following, inf):
                    best[following] = total
                    previous[following] = state
                    estimate = total + estimate_from(xs[nx], ys[ny], heading)
                    push(frontier, (estimate, total, next(serial), nx, ny, heading, 0))
            if not turned:
                total = cost + bend
                for turn in _PERPENDICULAR[heading]:
                    following = (ix, iy, turn, 1)
                    if total + 1e-9 < best_of(following, inf):
                        best[following] = total
                        previous[following] = state
                        estimate = total + estimate_from(xs[ix], ys[iy], turn)
                        push(frontier, (estimate, total, next(serial), ix, iy, turn, 1))
        _WORK[0] += work
        if final is None:
            raise RuntimeError("routing grid is disconnected")
        cells: list[tuple[int, int]] = []
        walk: tuple[int, int, int, int] | None = final
        while walk is not None:
            if not cells or cells[-1] != walk[:2]:
                cells.append(walk[:2])
            walk = previous[walk]
        cells.reverse()
        return simplify(tuple(self.point(ix, iy) for ix, iy in cells)), final_cost


type StepPrice = "callable[[Grid, int, int, int], float]"

_WORK = [0]
"""Search steps taken in this process: a machine-independent measure of effort."""


def search_work() -> int:
    """How many search steps have been taken so far (see ``router.REPAIR_WORK``)."""

    return _WORK[0]


def _heuristic(
    px: float, py: float, heading: int, gx: float, gy: float, arrive: int | None, bend: float
) -> float:
    distance = abs(gx - px) + abs(gy - py)
    if arrive is None:
        return distance
    return distance + bend * _minimum_bends(px, py, heading, gx, gy, arrive)


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
