"""Curly arrows drawn the way a chemist draws them.

Both ends of an arrow are *directions*, not just places. An arrow off a bond leaves it
square, a gap clear of the line; an arrow into a bond arrives square; an arrow off a
lone pair comes out of its atom, radially, the pair drawn at its tail; an arrow into an
atom points at it, along a radius, so which atom it is about is never in doubt.
Everything else -- how wide it swings, which side it passes on, whether it is a C or an
S, which side of the target it arrives on -- is searched for, against every atom and
bond on the page and the arrows already drawn. The curve is a cubic whose two control
points lie along the two end directions, which is what fixing them means; how far
along each is the only freedom it has, and it is enough.

A curve may not cross a bond, double back past its own ends, or wind through more
than two-thirds of a turn; it keeps clear of what it is not about, and bulges enough
to read as a curl rather than a line with a barb. An arrow off a lone pair, reaching
across to what it attacks, is an S where it has room -- it leaves its pair and arrives
travelling the same way, swinging across between; an arrow off a bond, pushing its
electrons along, is a C, and a short hook always is. Of the curves that pass, the
smoothest is drawn.

A head stops the same small gap short of whatever its atom is drawn with: its letters,
the lines of its bonds, its charge -- so it points at an O, or at a carbon's bare
vertex, without touching either.

The whole arrow is one stroke, in one ink: the curve, a short straight run in, and the
head as two ticks off the end of it, opening sixty degrees about it -- what a pen
does. A fishhook, moving one electron, has one tick.

These are the rules of mechazyme's ``dsl/curly_arrows.py``, which draws a mechanism's
arrows in its editor; the measures are its own, in bond lengths.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from flexo.chemistry.draw import Drawn, Pen, pair_spots
from flexo.chemistry.electrons import Arrow
from flexo.chemistry.molecule import Molecule
from flexo.drawn import Shape, path

type Point = tuple[float, float]

INK = "#d466d6"
"""Every curly arrow is drawn in one ink, as a chemist drawing a scheme has one pen."""

BOND_GAP = 0.20
"""How far an arrow keeps from the bond it comes off or goes into (bond lengths)."""
PAIR = 0.26
PAIR_SPREAD = 0.15
PAIR_DOT = 0.055
"""The lone pair an arrow leaves: the room it takes between the letter and the tail,
how far apart its two electrons are, and the size of each."""
RUN = 0.22
"""How much of an arrow's end is straight, so its head sits on a line, not a bend."""
OVERSHOOT = 0.08
OVERSHOOT_LEAST = 0.12
"""How far past its own ends a curve may reach, as a share of the span between them --
or, for a short hook, in bond lengths."""
CLEAR = 60.0
"""How far, in degrees, a lone pair an arrow leaves sits from the atom's bonds and marks."""
CLEAR_OF_WORDS = 75.0
"""... and from the hydrogens written beside its letter, which reach further."""
TURN_MOST = 240.0
"""The most a curve may turn over its length, in degrees: a bend, not a loop."""
AGAINST = 12.0
"""How far, in degrees, a curve may bend back against its main bend and still be a C."""
TILTS = (25.0, -25.0, 50.0, -50.0)
"""How far, in degrees, a tail may turn from leaving square (or radially) when no
curve leaving that way keeps clear."""
S_SPAN = 1.0
"""How long an arrow must be, in bond lengths, to be drawn as an S."""
S_LEAN = 50.0
"""The most, in degrees, an S's tail leans off the line to its head."""
S_CURL = 0.06
"""How far each half of an S must bulge off its chord, as a share of it."""
ATOM_GAP = 0.04
"""The gap between an atom's letter and the lone pair an arrow leaves."""
HEAD_GAP = 0.10
"""The gap a head leaves before its atom's ink -- its letters, its bonds' lines, its
charge -- in bond lengths: it points at the atom without touching it."""
LANDING_MOST = 0.5
"""How much further out than its letter (or vertex) a head may stop to keep that gap;
a way in that needs more runs along a bond, and is not taken."""
VERTEX = 0.13
"""What a bare carbon vertex takes up, where its bond lines meet."""
ROOMY = 1.3
"""How much more room an atom's letter takes than an arrow has to keep off it."""
CHARGED = 0.18
REACHES = (0.32, 0.45, 0.62, 0.85, 1.15, 1.55)
"""How far the controls run along the end directions, as shares of the span, tightest
first: an arrow with a free run stays tight, a boxed-in one swings no wider than it must."""
REACH_LEAST = 0.42
SHARES = ((1.0, 1.0), (0.6, 1.5), (1.5, 0.6))
"""How the reach is shared between the ends: a plain curve, or an S turning near one end."""
REACH_PRICE = 0.16
ROOM = 0.22
"""The room a curve wants past whatever it passes."""
NEAR = 0.85
"""How near its own ends a curve may come close to what it joins."""
SAMPLES = (0.12, 0.25, 0.38, 0.5, 0.62, 0.75, 0.88)
STEPS = 19
CURL = 0.15
"""How far off its chord a curve must bulge to read as a curly arrow, as a share of it."""
APPROACHES = 24
ARRIVALS = 5
FACING = 0.8
OUTWARD = 0.45
SQUARE = 1.2
SPAN = 0.7
SPAN_ENOUGH = 1.4
SPAN_LEAST = 0.75
HOOK_LEAST = 0.45
"""How long a hook (a bond's electrons onto one of its own atoms) is drawn if it can be."""
OWN_ROOM = 0.06
"""How far a curve keeps off the letters of the atoms it joins, in bond lengths."""
ROOM_ENOUGH = 0.55
TICK = 0.18
TICK_ANGLE = 30.0
STROKE = 0.055


@dataclass(frozen=True, slots=True)
class End:
    """Where a curve touches, which way it travels there, and -- for a head -- the tip a
    short straight run further on, where the ticks go."""

    at: Point
    way: Point
    tip: Point | None = None

    def end(self) -> Point:
        return self.tip if self.tip is not None else self.at


class _Frame:
    """The drawn molecule as the arrows see it: where each atom is, what it takes up,
    which way its own bonds leave open."""

    def __init__(self, molecule: Molecule, drawn: Drawn, pen: Pen) -> None:
        self.molecule = molecule
        self.drawn = drawn
        self.pen = pen
        self.bond = pen.bond
        self.at = {index: place.point for index, place in drawn.atoms.items()}
        self.neighbours = {index: molecule.neighbours(index) for index in self.at}
        self.bonded = {frozenset((bond.a, bond.b)) for bond in molecule.bonds}
        self.radius: dict[int, float] = {}
        for index, place in drawn.atoms.items():
            letter = max(place.radius) - pen.margin * 0.5 if place.radius[0] else 0.0
            if place.label is not None:
                left, top, right, bottom = place.label
                middle = ((left + right) / 2, (top + bottom) / 2)
                letter = max(letter, math.dist(place.point, middle) + (right - left) / 2 * 0.8)
            charged = CHARGED * self.bond if molecule.charge_of(index) else 0.0
            self.radius[index] = letter * ROOMY + charged
        self._ink: dict[int, tuple] = {}

    def segments(self):
        for pair in self.bonded:
            first, second = tuple(pair)
            yield first, second

    def edge(self, atom: int, way: Point, gap: float) -> float:
        """How far from an atom's centre, going ``way``, something drawn about it sits:
        past its letter (or its vertex), then the gap."""

        place = self.drawn.atoms[atom]
        if not place.radius[0]:
            letter = VERTEX * self.bond
        else:
            rx, ry = place.radius
            reach = 1.0 / math.sqrt((way[0] / rx) ** 2 + (way[1] / ry) ** 2)
            letter = reach - self.pen.margin * 0.7
            if place.label is not None:
                letter = max(letter, _box_edge(place.point, place.label, way))
        return letter + gap * self.bond

    def ink(self, atom: int) -> tuple[list, list, list]:
        """What an atom is drawn with: the boxes of its letters, the lines of its bonds,
        its circled charge."""

        if atom not in self._ink:
            place = self.drawn.atoms[atom]
            boxes = list(place.ink)
            if place.radius[0]:
                (x, y), (rx, ry), margin = place.point, place.radius, self.pen.margin
                boxes.append((x - rx + margin, y - ry + margin, x + rx - margin, y + ry - margin))
            lines = [
                line for pair, drawn in self.drawn.lines.items() if atom in pair for line in drawn
            ]
            circles = [(x, y, r) for owner, x, y, r in self.drawn.marks if owner == atom]
            self._ink[atom] = (boxes, lines, circles)
        return self._ink[atom]

    def landing(self, atom: int, way: Point) -> float | None:
        """How far out from an atom along ``way`` a head's tip stops, for it and its ticks
        to keep ``HEAD_GAP`` off the atom's ink -- or None, if only far along a bond."""

        boxes, lines, circles = self.ink(atom)
        here = self.at[atom]
        half = self.pen.line / 2
        gap = self.bond * HEAD_GAP + max(self.pen.line, self.bond * STROKE) / 2
        tick = self.bond * TICK
        spread = (_turn(way, TICK_ANGLE), _turn(way, -TICK_ANGLE))

        def short(points) -> float:
            nearest = math.inf
            for x, y in points:
                for left, top, right, bottom in boxes:
                    nearest = min(
                        nearest,
                        math.hypot(max(left - x, 0.0, x - right), max(top - y, 0.0, y - bottom)),
                    )
                for a, b in lines:
                    nearest = min(nearest, _to_segment((x, y), a, b) - half)
                for cx, cy, r in circles:
                    nearest = min(nearest, math.hypot(x - cx, y - cy) - r)
            return gap - nearest

        start = self.edge(atom, way, 0.0)
        reach = start
        while reach <= start + self.bond * LANDING_MOST:
            tip = _step(here, way, reach)
            # The tip first, which is nearest; then the ticks, which may reach a bond.
            wanting = short((tip,))
            if wanting <= 1e-9:
                wanting = short(
                    [_step(tip, side, tick * share) for side in spread for share in (0.5, 1.0)]
                )
                if wanting <= 1e-9:
                    return reach
            reach += max(wanting, self.bond * 0.02)
        return None

    def midpoint(self, pair) -> Point:
        a, b = (self.at[atom] for atom in pair)
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    def axis(self, pair) -> Point:
        a, b = (self.at[atom] for atom in pair)
        return _unit(_minus(b, a))

    def joined(self, pair) -> bool:
        return frozenset(pair) in self.bonded

    def outward(self, atom: int, toward: Point | None = None) -> Point:
        """Which way points away from an atom's neighbours (and from the hydrogens
        written beside it): where its lone pairs are, and where an arrow off it starts."""

        here = self.at[atom]
        away = [_unit(_minus(here, self.at[other])) for other in self.neighbours[atom]]
        place = self.drawn.atoms[atom]
        if place.label is not None and place.label_side:
            away.append((-1.0, 0.0) if place.label_side == "right" else (1.0, 0.0))
        if not away:
            return _unit(_minus(toward, here)) if toward is not None else (0.0, -1.0)
        total = (sum(v[0] for v in away), sum(v[1] for v in away))
        if _length(total) > 1e-6:
            return _unit(total)
        side = _perpendicular(away[0])
        if toward is not None and _dot(side, _minus(toward, here)) < 0:
            side = (-side[0], -side[1])
        return side

    def facing(
        self, atom: int, toward: Point | None, words: bool = True, lean: float = 0.0
    ) -> list[Point]:
        """The ways a lone pair may sit for an arrow off it to set out toward ``toward``
        (turned ``lean`` radians off it), best first: as near that way as the atom's bonds,
        the hydrogens written beside it, its charge and its other lone pairs leave room
        for -- the pair a textbook draws on the side facing what it attacks, not round the
        back. ``words=False`` leaves the hydrogens out: they are written where the pair is
        not."""

        here = self.at[atom]
        if toward is None:
            return [self.outward(atom)]
        want = math.atan2(toward[1] - here[1], toward[0] - here[0]) + lean
        blocked: list[tuple[float, float]] = []
        for other in self.neighbours[atom]:
            there = self.at[other]
            blocked.append((math.atan2(there[1] - here[1], there[0] - here[0]), CLEAR))
        place = self.drawn.atoms[atom]
        if words and place.label is not None and place.label_side:
            blocked.append((0.0 if place.label_side == "right" else math.pi, CLEAR_OF_WORDS))
        for owner, x, y, _ in self.drawn.marks:
            if owner == atom:
                blocked.append((math.atan2(y - here[1], x - here[0]), CLEAR))
        for angle, _ in place.pairs:
            blocked.append((angle, CLEAR))
        if place.radical is not None:
            blocked.append((place.radical[0], CLEAR))

        def apart(angle: float) -> float:
            return min(
                (
                    abs(math.remainder(angle - other, math.tau)) - math.radians(room)
                    for other, room in blocked
                ),
                default=math.pi,
            )

        ways = [math.radians(step * 5) for step in range(72)]
        clear = [angle for angle in ways if apart(angle) >= 0]
        if not clear:
            best = max(ways, key=apart)
            return [(math.cos(best), math.sin(best))]
        clear.sort(key=lambda angle: abs(math.remainder(angle - want, math.tau)))
        best = clear[0]
        chosen = [best]
        for offset in (20, -20, 40, -40):
            angle = best + math.radians(offset)
            if apart(angle) >= 0:
                chosen.append(angle)
        return [(math.cos(angle), math.sin(angle)) for angle in chosen]


def _box_edge(centre: Point, box, way: Point) -> float:
    left, top, right, bottom = box
    reach = []
    if abs(way[0]) > 1e-9:
        reach.append(((right if way[0] > 0 else left) - centre[0]) / way[0])
    if abs(way[1]) > 1e-9:
        reach.append(((bottom if way[1] > 0 else top) - centre[1]) / way[1])
    found = [value for value in reach if value >= 0]
    return min(found) if found else 0.0


# -- what an arrow is, as ends ------------------------------------------------------------


def _ends(arrow: Arrow) -> tuple[dict, dict]:
    """An arrow as a tail (``lp`` an atom, or ``bond``) and a head (``atom``: electrons
    landing on it; ``bond``: a bond made or made stronger)."""

    if len(arrow.source) == 1:
        (giver,) = arrow.source
        if len(arrow.target) == 1:
            return {"lp": giver}, {"bond": (giver, arrow.target[0])}
        return {"lp": giver}, {"bond": tuple(arrow.target)}
    tail = {"bond": tuple(arrow.source)}
    if len(arrow.target) == 1:
        return tail, {"atom": arrow.target[0]}
    return tail, {"bond": tuple(arrow.target)}


def _source_atoms(tail: dict) -> set[int]:
    return {tail["lp"]} if "lp" in tail else set(tail["bond"])


def _named(arrow: Arrow) -> set[int]:
    return set(arrow.source) | set(arrow.target)


def _off_bond(frame: _Frame, pair, sign: int, into: bool = False) -> End:
    """An end square to a bond, a gap off it, on one side; ``into`` makes it a head,
    coming straight down onto the bond."""

    middle = frame.midpoint(pair)
    across = _perpendicular(frame.axis(pair))
    out = (across[0] * sign, across[1] * sign)
    tip = _step(middle, out, frame.bond * BOND_GAP)
    if not into:
        return End(tip, out)
    return End(_step(tip, out, frame.bond * RUN), (-out[0], -out[1]), tip)


def _tails(
    frame: _Frame, tail: dict, aim: Point | None, arriving: Point | None = None
) -> list[End]:
    """Where the arrow may leave, best first: out of a lone pair's atom on the side
    facing where it is going, past its letter and its pair -- leaning off the way there
    as its head arrives (``arriving``) leans, for an S, or the other way, for a C, or
    straight at it, as near each as the atom leaves room; or square off either side of
    a bond, the side facing where it is going first."""

    if "lp" in tail:
        atom = tail["lp"]
        anchor = frame.at[atom]
        leans = [0.0]
        if aim is not None and arriving is not None:
            chord = _minus(aim, anchor)
            lean = math.atan2(_cross(chord, arriving), _dot(chord, arriving))
            lean = max(-math.radians(S_LEAN), min(math.radians(S_LEAN), lean))
            leans = [lean, -lean, 0.0]
        ways: list[Point] = []
        for lean in leans:
            for way in frame.facing(atom, aim, lean=lean):
                if all(_dot(way, other) < math.cos(math.radians(8)) for other in ways):
                    ways.append(way)
        return [
            End(_step(anchor, out, frame.edge(atom, out, ATOM_GAP) + frame.bond * PAIR), out)
            for out in ways
        ]
    pair = tail["bond"]
    middle = frame.midpoint(pair)
    toward = _minus(aim, middle) if aim is not None else None
    first = 1 if toward is None or _dot(_perpendicular(frame.axis(pair)), toward) >= 0 else -1
    return [_off_bond(frame, pair, first), _off_bond(frame, pair, -first)]


def _arrivals(frame: _Frame, target: int, tail: dict, square_to: Point | None) -> list[End]:
    """Which sides of an atom a head may come in on, best first: always along a radius,
    pointing at the atom; where there is room, on the face its bonds leave open, facing
    the electrons -- and never back down a bond the electrons are leaving."""

    anchor = frame.at[target]
    coming = [frame.at[n] for n in _source_atoms(tail) if n != target]
    toward = middle = None
    if coming:
        middle = (sum(p[0] for p in coming) / len(coming), sum(p[1] for p in coming) / len(coming))
        toward = _unit(_minus(middle, anchor))
    out = frame.outward(target)
    obstacles = _obstacles(frame, _source_atoms(tail) | {target})
    scored = []
    for step in range(APPROACHES):
        angle = 2 * math.pi * step / APPROACHES
        way = (math.cos(angle), math.sin(angle))
        reach = frame.landing(target, way)
        if reach is None:
            continue  # in along a bond
        point = _step(anchor, way, reach)
        here = min(_room([point], obstacles), frame.bond * ROOM_ENOUGH)
        here += frame.bond * OUTWARD * _dot(way, out)
        if toward is not None and middle is not None:
            if _dot(way, toward) < -1e-9:
                continue  # never arrive from behind
            here += frame.bond * FACING * _dot(way, toward)
            here += frame.bond * SPAN * min(math.dist(point, middle) / frame.bond, SPAN_ENOUGH)
        if square_to is not None:
            here -= frame.bond * SQUARE * abs(_dot(way, square_to))
        scored.append((here, way, reach))
    if not scored:
        way = toward or out
        scored = [(0.0, way, frame.edge(target, way, HEAD_GAP))]
    scored.sort(key=lambda row: -row[0])
    return [
        End(
            _step(anchor, way, reach + frame.bond * RUN),
            (-way[0], -way[1]),
            _step(anchor, way, reach),
        )
        for _, way, reach in scored[:ARRIVALS]
    ]


def _own_bond(frame: _Frame, atom: int, partner: int) -> list[list[tuple[End, End]]]:
    """A lone pair closing onto a bond its own atom is in (an alkoxide re-forming C=O),
    or a radical's electron going to meet another's: the electrons square to the bond,
    the arrow curling from them down onto it -- on the side the atoms' other bonds leave
    open, else the other."""

    here, axis = frame.at[atom], frame.axis((atom, partner))
    across = _perpendicular(axis)
    middle = frame.midpoint((atom, partner))
    crowd = [0.0, 0.0]
    for end in (atom, partner):
        for other in frame.neighbours[end]:
            if other not in (atom, partner):
                way = _unit(_minus(frame.at[other], middle))
                crowd[0] += way[0]
                crowd[1] += way[1]
    first = -1 if _dot(across, (crowd[0], crowd[1])) > 1e-6 else 1
    out = []
    for sign in (first, -first):
        side = (across[0] * sign, across[1] * sign)
        tail = End(_step(here, side, frame.edge(atom, side, ATOM_GAP) + frame.bond * PAIR), side)
        out.append([(tail, _off_bond(frame, (atom, partner), sign, into=True))])
    return out


def _pairs(frame: _Frame, arrow: Arrow) -> list[list[tuple[End, End]]]:
    """Every (tail, head) the arrow might be drawn between, in groups tried in turn.
    Electrons making a bond that is there stronger go into it, square; making a bond
    that is not there yet, to the atom under attack -- or, one electron of two meeting,
    to the middle of the gap, square, from one side; landing on an atom, to it -- not
    along the bond they leave."""

    tail, head = _ends(arrow)
    if _closes_own(frame, arrow):
        partner = next(n for n in head["bond"] if n != tail["lp"])
        return _own_bond(frame, tail["lp"], partner)
    source = _source_atoms(tail)
    if "bond" in head and (frame.joined(head["bond"]) or arrow.electrons == 1):
        pair = head["bond"]
        middle, across = frame.midpoint(pair), _perpendicular(frame.axis(pair))
        starts = [frame.at[n] for n in source]
        start_at = (
            sum(p[0] for p in starts) / len(starts),
            sum(p[1] for p in starts) / len(starts),
        )
        first = -1 if _dot(across, _minus(start_at, middle)) < 0 else 1
        found = []
        for side in (first, -first):
            into = _off_bond(frame, pair, side, into=True)
            found += [(start, into) for start in _tails(frame, tail, into.end(), into.way)]
        return [found]
    if "bond" in head:
        far = [n for n in head["bond"] if n not in source]
        target = far[0] if (source & set(head["bond"]) and len(far) == 1) else None
        if target is None:
            landing = frame.midpoint(head["bond"])
            found = []
            for start in _tails(frame, tail, landing):
                way = _unit(_minus(landing, start.at))
                found.append((start, End(_step(landing, way, -frame.bond * RUN), way, landing)))
            return [found]
        square = None
    else:
        target = head["atom"]
        others = [n for n in source if n != target]
        square = frame.axis((others[0], target)) if others else None
    return [
        [
            (start, into)
            for into in _arrivals(frame, target, tail, square)
            for start in _tails(frame, tail, into.end(), into.way)
        ]
    ]


def _closes_own(frame: _Frame, arrow: Arrow) -> bool:
    """Whether an atom's own electrons go into a bond it is in: a lone pair making a bond
    there stronger, or a radical's electron going to make one."""

    tail, head = _ends(arrow)
    return (
        "lp" in tail
        and "bond" in head
        and tail["lp"] in head["bond"]
        and (frame.joined(head["bond"]) or arrow.electrons == 1)
    )


# -- the search ----------------------------------------------------------------------------


def _controls(tail: End, head: End, out: float, back: float) -> tuple[Point, Point]:
    return _step(tail.at, tail.way, out), _step(head.at, head.way, -back)


def _weights(ts) -> list[tuple[float, float, float, float]]:
    return [((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3) for t in ts]


_WALKED = _weights([index / STEPS for index in range(STEPS + 1)])
_SAMPLED = _weights(SAMPLES)


def _points(weights, start: Point, first: Point, second: Point, finish: Point) -> list[Point]:
    """The cubic at each of a fixed set of places along it, weighed out once."""

    (ax, ay), (bx, by), (cx, cy), (dx, dy) = start, first, second, finish
    return [
        (p * ax + q * bx + r * cx + s * dx, p * ay + q * by + r * cy + s * dy)
        for p, q, r, s in weights
    ]


def _walk(tail: End, head: End, controls, steps: int = STEPS) -> list[Point]:
    first, second = controls
    weights = _WALKED if steps == STEPS else _weights([i / steps for i in range(steps + 1)])
    out = _points(weights, tail.at, first, second, head.at)
    if head.tip is not None:
        out.append(head.tip)
    return out


def _along(tail: End, head: End, controls) -> list[Point]:
    first, second = controls
    return _points(_SAMPLED, tail.at, first, second, head.at)


def _obstacles(frame: _Frame, ignore: set[int]):
    """What a curve keeps off: atoms (with the room their letters take), circled charges
    -- even those of the atoms it joins -- and bonds."""

    circles = [(p[0], p[1], frame.radius[i]) for i, p in frame.at.items() if i not in ignore]
    circles += [(x, y, r) for _, x, y, r in frame.drawn.marks]
    lines = [
        (*frame.at[a], *frame.at[b])
        for a, b in frame.segments()
        if a not in ignore and b not in ignore
    ]
    return circles, lines


def _room(points: list[Point], obstacles) -> float:
    circles, lines = obstacles
    worst = math.inf
    for x, y in points:
        for cx, cy, r in circles:
            here = math.hypot(x - cx, y - cy) - r
            if here < worst:
                worst = here
        for ax, ay, bx, by in lines:
            # The distance to the segment, worked out here: this is the search's inner loop.
            ex, ey = bx - ax, by - ay
            size = ex * ex + ey * ey
            t = 0.0 if size < 1e-9 else ((x - ax) * ex + (y - ay) * ey) / size
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            here = math.hypot(x - ax - ex * t, y - ay - ey * t)
            if here < worst:
                worst = here
    return worst


def _crossing(points: list[Point], lines) -> bool:
    left, right = min(x for x, _ in points), max(x for x, _ in points)
    low, high = min(y for _, y in points), max(y for _, y in points)
    for ax, ay, bx, by in lines:
        if max(ax, bx) < left or min(ax, bx) > right or max(ay, by) < low or min(ay, by) > high:
            continue
        for first, second in itertools.pairwise(points):
            if _cuts(first, second, (ax, ay), (bx, by)):
                return True
    return False


def _cuts(a: Point, b: Point, c: Point, d: Point) -> bool:
    def side(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _turns(points: list[Point]) -> list[float]:
    legs = [_unit(_minus(b, a)) for a, b in itertools.pairwise(points) if math.dist(a, b) > 1e-9]
    return [
        math.degrees(math.acos(max(-1.0, min(1.0, _dot(p, q)))))
        for p, q in itertools.pairwise(legs)
    ]


def _shape(points: list[Point]) -> str | None:
    return _bends(points)[1]


def _bends(points: list[Point]) -> tuple[float, str | None]:
    """How far a curve turns in all, in degrees, and its shape: ``C`` for one that bends
    one way (or all but), ``S`` for one that bends one way and then, once, the other --
    None for one that wavers more than that."""

    legs = [
        (bx - ax, by - ay)
        for (ax, ay), (bx, by) in itertools.pairwise(points)
        if abs(bx - ax) + abs(by - ay) > 1e-9
    ]
    left = right = 0.0
    signs = []
    for (px, py), (qx, qy) in itertools.pairwise(legs):
        angle = math.degrees(math.atan2(px * qy - py * qx, px * qx + py * qy))
        if angle > 0:
            left += angle
        else:
            right -= angle
        if abs(angle) > 0.5:
            signs.append(angle > 0)
    if min(left, right) <= AGAINST:
        return left + right, "C"
    changes = sum(a != b for a, b in itertools.pairwise(signs))
    return left + right, ("S" if changes == 1 else None)


def _doubles_back(tail: End, head: End, points: list[Point], least: float) -> bool:
    """Whether a curve runs ahead of its end, or behind its start, along its chord, by
    more than a share of it, or ``least``."""

    start, finish = tail.at, head.end()
    along = _minus(finish, start)
    span = _length(along)
    if span < 1e-6:
        return True
    wx, wy = along[0] / span, along[1] / span
    sx, sy = start
    slack = max(span * OVERSHOOT, least)
    return any(not -slack <= (x - sx) * wx + (y - sy) * wy <= span + slack for x, y in points)


def _curl(tail: End, head: End, controls) -> float:
    return max(_lobes(tail, head, controls))


def _lobes(tail: End, head: End, controls, along: list[Point] | None = None) -> tuple[float, float]:
    """How far a curve bulges off the line between its ends, to either side."""

    if math.dist(tail.at, head.at) < 1e-6:
        return 0.0, 0.0
    across = _perpendicular(_unit(_minus(head.at, tail.at)))
    x, y = tail.at
    offsets = [
        (px - x) * across[0] + (py - y) * across[1]
        for px, py in (along or _along(tail, head, controls))
    ]
    return max(max(offsets), 0.0), max(-min(offsets), 0.0)


def _room_along(frame: _Frame, tail: End, head: End, controls, close, far, enough: float) -> float:
    """The room along a curve -- strict except near its own ends, where it must pass what
    it joins -- or as soon as it is known to be under ``enough``, that."""

    edge = frame.bond * NEAR
    worst = math.inf
    for point in _along(tail, head, controls):
        near = math.dist(point, tail.at) < edge or math.dist(point, head.at) < edge
        worst = min(worst, _room([point], close if near else far))
        if worst < enough:
            break
    return worst


def _clears(
    frame: _Frame, tail: End, head: End, controls, close, far, bonds, letters, wanted: float
) -> str | None:
    """The shape of a curve that keeps clear -- no faults, and room all along it (as
    ``_best`` weighs) -- or None; asked cheapest first, so that most curves are turned away
    after a glance. A C bulges a share of its span off it; an S, long enough to be one,
    less to each side."""

    span = math.dist(tail.at, head.at)
    along = _along(tail, head, controls)
    one, other = _lobes(tail, head, controls, along)
    if max(one, other) < span * S_CURL:
        return None
    walked = _walk(tail, head, controls)
    if _doubles_back(tail, head, walked, frame.bond * OVERSHOOT_LEAST):
        return None
    turned, shape = _bends(walked)
    if turned > TURN_MOST:
        return None
    if shape == "C" and max(one, other) < span * CURL:
        return None
    if shape == "S" and (min(one, other) < span * S_CURL or span < frame.bond * S_SPAN):
        return None
    if shape is None:
        return None
    edge = frame.bond * NEAR
    for point in along:
        near = math.dist(point, tail.at) < edge or math.dist(point, head.at) < edge
        if _room([point], close if near else far) < wanted:
            return None
    if _touches(walked, letters, frame.bond * OWN_ROOM):
        return None
    return None if _crossing(walked, bonds) else shape


def _touches(points: list[Point], boxes, room: float) -> bool:
    """Whether a curve comes within ``room`` of any of these letters."""

    for left, top, right, bottom in boxes:
        for x, y in points:
            if math.hypot(max(left - x, 0.0, x - right), max(top - y, 0.0, y - bottom)) < room:
                return True
    return False


def _curves(frame: _Frame, pairs):
    """Every curve the search tries, by how far it reaches: (key, step, tail, head,
    controls), the key the same for the same curve however it is come to."""

    for step, reach in enumerate(REACHES):
        for tail, head in pairs:
            span = math.dist(tail.at, head.at)
            if span < 1e-3:
                continue
            length = max(span * reach, frame.bond * REACH_LEAST)
            for share, (out, back) in enumerate(SHARES):
                controls = _controls(tail, head, length * out, length * back)
                yield (id(tail), id(head), step, share), step, tail, head, controls


def _try(frame: _Frame, pairs, close, far, bonds, letters, wanted: float, seen: dict, shape: str):
    """The smoothest curve of ``shape`` that keeps clear, reaching no further than it must
    -- or None. ``seen`` holds what is known of curves already tried for the same arrow."""

    cleared: list = []
    reached = None
    for key, step, tail, head, controls in _curves(frame, pairs):
        if reached is not None and step > reached:
            break
        if key not in seen:
            seen[key] = _clears(frame, tail, head, controls, close, far, bonds, letters, wanted)
        if seen[key] == shape:
            cleared.append((tail, head, controls))
            reached = step
    if not cleared:
        return None
    # The smoothest of those that keep clear: drawn, not steered.
    return min(cleared, key=lambda found: max(_turns(_walk(*found)), default=0.0))


def _best(frame: _Frame, pairs, close, far, bonds, letters, wanted: float, price: float, seen: set):
    """When nothing keeps clear: the curve worth most, and its worth -- its room, less its
    faults (crossing a bond or another arrow worst, then doubling back, winding round,
    wavering), with its curl and span, less how far it reaches. Each curve is weighed once
    (``seen``), and given up as soon as it cannot be worth the best so far."""

    best = most = None
    for key, step, tail, head, controls in _curves(frame, pairs):
        if key in seen:
            continue
        seen.add(key)
        span = math.dist(tail.at, head.at)
        curl = _curl(tail, head, controls)
        worth = (
            min(curl / span, CURL) * frame.bond
            + min(span / frame.bond, SPAN_LEAST) * frame.bond * 0.3
            - step * price
        )
        walked = _walk(tail, head, controls)
        worth -= frame.bond * (
            _doubles_back(tail, head, walked, frame.bond * OVERSHOOT_LEAST)
            + (_bends(walked)[0] > TURN_MOST)
            + (_bends(walked)[1] is None)
            + _touches(walked, letters, frame.bond * OWN_ROOM)
        )
        if most is not None and worth + wanted <= most:
            continue
        floor = -math.inf if most is None else most - worth
        worth += min(_room_along(frame, tail, head, controls, close, far, floor), wanted)
        if most is not None and worth <= most:
            continue
        if _crossing(walked, bonds):
            worth -= 3.0 * frame.bond
            if most is not None and worth <= most:
                continue
        best, most = (tail, head, controls), worth
    return best, most


def _segments_of(points: list[Point]):
    return [(a[0], a[1], b[0], b[1]) for a, b in itertools.pairwise(points)]


def _around(frame: _Frame, arrow: Arrow, others: list):
    """What an arrow's curve keeps off: near its ends (``close``), along it (``far``), the
    bonds and other arrows it may not cross, and the letters of its own atoms, which it
    passes as near as it must but never over."""

    own = _named(arrow)
    around = set(own)
    for atom in own:
        around.update(frame.neighbours.get(atom, ()))
    close = _obstacles(frame, around)
    far = _obstacles(frame, own)
    close = (close[0], close[1] + others)
    far = (far[0], far[1] + others)
    bonds = _obstacles(frame, set())[1] + others
    letters = [box for atom in sorted(own) for box in frame.ink(atom)[0]]
    return close, far, bonds, letters


def _draw_one(frame: _Frame, arrow: Arrow, others: list, heads: list[Point], prefer=None):
    wanted = frame.bond * ROOM
    if prefer is not None:
        # A curve found for this arrow before (its structure drawn once already) stays,
        # if it still keeps clear of everything here: it is not looked for again.
        tail, head, controls = prefer
        if all(math.dist(head.end(), h) > frame.bond * 0.1 for h in heads) and (
            _clears(frame, tail, head, controls, *_around(frame, arrow, others), wanted) is not None
        ):
            return prefer
    groups = _pairs(frame, arrow)
    # Two heads never land on one spot: two half arrows making a bond meet from either side.
    spaced = [
        [
            pair
            for pair in group
            if all(math.dist(pair[1].end(), h) > frame.bond * 0.1 for h in heads)
        ]
        for group in groups
    ]
    groups = [group for group in spaced if group] or groups
    if not any(groups):
        return None
    close, far, bonds, letters = _around(frame, arrow, others)
    tilted = [
        [(End(tail.at, _turn(tail.way, angle)), head) for tail, head in group for angle in TILTS]
        for group in groups
    ]
    choices = []
    for pairs in groups + tilted:
        # The longest ways of drawing it first: a hook as long as it can be, not a scratch.
        for least in (SPAN_LEAST, HOOK_LEAST, 0.0):
            some = [p for p in pairs if math.dist(p[0].at, p[1].at) >= frame.bond * least]
            if some and (not choices or some != choices[-1]):
                choices.append(some)
    # An arrow off a lone pair reaching across to what it attacks is an S where there is
    # room for one; an arrow off a bond, pushing electrons along, a C.
    shapes = ("S", "C") if "lp" in _ends(arrow)[0] else ("C", "S")
    tried: dict = {}
    for pairs in choices:
        for shape in shapes:
            found = _try(frame, pairs, close, far, bonds, letters, wanted, tried, shape)
            if found is not None:
                return found
    # Nothing keeps clear: the curve worth most of all of them.
    fallback = scored = None
    measured: set = set()
    for pairs in choices:
        best, worth = _best(
            frame, pairs, close, far, bonds, letters, wanted, frame.bond * REACH_PRICE, measured
        )
        if best is not None and (scored is None or worth > scored):
            fallback, scored = best, worth
    return fallback


# -- drawing --------------------------------------------------------------------------------


def tail_ways(
    molecule: Molecule, drawn: Drawn, arrows: list[Arrow], pen: Pen
) -> dict[int, list[float]]:
    """For each atom, the directions its arrows leave its own electrons: where its other
    marks keep clear of (``draw_molecule``'s ``used``)."""

    frame = _Frame(molecule, drawn, pen)
    ways: dict[int, list[float]] = {}
    for arrow in arrows:
        if len(arrow.source) != 1:
            continue
        (atom,) = arrow.source
        others = [n for n in arrow.target if n != atom] or list(arrow.target)
        if _closes_own(frame, arrow):
            continue  # square to its own bond, on whichever side the search takes
        way = frame.facing(atom, frame.at[others[0]], words=False)[0]
        ways.setdefault(atom, []).append(math.atan2(way[1], way[0]))
    return ways


def draw_arrows(
    molecule: Molecule,
    drawn: Drawn,
    arrows: list[Arrow],
    pen: Pen,
    *,
    prefix: str,
    colour: str = INK,
    prefer: list | None = None,
    chosen: list | None = None,
) -> list[list[Point]]:
    """Each arrow, one after another, each keeping off those already down, added to
    ``drawn`` as one stroke and the electrons it takes. Returns the strokes drawn.

    ``chosen``, given a list, is told each arrow's curve; ``prefer`` gives curves found
    so for the same structure, kept where they still keep clear rather than looked for
    again."""

    frame = _Frame(molecule, drawn, pen)
    others: list = []
    heads: list[Point] = []
    strokes: list[list[Point]] = []
    width = max(pen.line, frame.bond * STROKE)
    tick = frame.bond * TICK
    for number, arrow in enumerate(arrows):
        found = _draw_one(
            frame,
            arrow,
            others,
            heads,
            (prefer or [])[number] if number < len(prefer or []) else None,
        )
        if chosen is not None:
            chosen.append(found)
        if found is None:
            continue
        tail, head, (first, second) = found
        curve = _walk(tail, head, (first, second))
        ticks = _ticks(head, tick, arrow.electrons, curve)
        others += _segments_of(curve) + _segments_of(ticks)
        heads.append(head.end())
        strokes.append(curve)
        identifier = f"{prefix}.arrow{number}"
        if len(arrow.source) == 1:
            _electrons(drawn, frame, arrow, tail, pen, identifier, colour)
        tip = head.end()
        pieces: list[object] = [
            "M",
            tail.at[0],
            tail.at[1],
            "C",
            first[0],
            first[1],
            second[0],
            second[1],
            head.at[0],
            head.at[1],
            "L",
            tip[0],
            tip[1],
            "M",
            ticks[0][0],
            ticks[0][1],
        ]
        for point in ticks[1:]:
            pieces += ["L", point[0], point[1]]
        drawn.shapes.append(Shape(identifier, path(*pieces), "line", width=width, color=colour))
        xs = [p[0] for p in curve + ticks]
        ys = [p[1] for p in curve + ticks]
        drawn.boxes.append((min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width))
    return strokes


def _ticks(head: End, length: float, electrons: int, curve: list[Point]) -> list[Point]:
    """The head: two ticks off the tip, opening sixty degrees about the way the arrow
    arrives -- one tick, on the outside of the curve, for a fishhook."""

    tip = head.end()
    back = (-head.way[0], -head.way[1])
    one = _step(tip, _turn(back, TICK_ANGLE), length)
    two = _step(tip, _turn(back, -TICK_ANGLE), length)
    if electrons == 2:
        return [one, tip, two]
    middle = curve[len(curve) // 2]
    chord_middle = ((curve[0][0] + tip[0]) / 2, (curve[0][1] + tip[1]) / 2)
    bulge = _minus(middle, chord_middle)
    outside = one if _dot(_minus(one, tip), bulge) > _dot(_minus(two, tip), bulge) else two
    return [outside, tip]


def _electrons(
    drawn: Drawn, frame: _Frame, arrow: Arrow, tail: End, pen: Pen, identifier: str, colour: str
) -> None:
    """The electrons the arrow takes, at its tail in its ink: a lone pair's two dots,
    square to the way it leaves -- or a radical's one."""

    (atom,) = arrow.source
    single = arrow.electrons == 1 and frame.molecule.atoms[atom].lone % 2 == 1
    centre = _step(tail.at, tail.way, -frame.bond * PAIR * 0.55)
    # Drawn now, as the atom's other marks are: what is put round it after keeps off it.
    place = drawn.atoms[atom]
    place.taken.append(math.atan2(tail.way[1], tail.way[0]))
    if not single:
        place.pairs.append((math.atan2(tail.way[1], tail.way[0]), centre))
    across = _perpendicular(tail.way)
    gap = frame.bond * PAIR_SPREAD / 2
    radius = max(pen.dot * 0.9, frame.bond * PAIR_DOT)
    spots = (
        [centre]
        if single
        else [
            (centre[0] + across[0] * gap * side, centre[1] + across[1] * gap * side)
            for side in (1, -1)
        ]
    )
    d = " ".join(
        path(
            "M",
            x - radius,
            y,
            "A",
            radius,
            radius,
            0,
            1,
            1,
            x + radius,
            y,
            "A",
            radius,
            radius,
            0,
            1,
            1,
            x - radius,
            y,
            "Z",
        )
        for x, y in spots
    )
    drawn.shapes.append(
        Shape(f"{identifier}.electrons", d, "solid", width=radius * 0.2, color=colour)
    )
    reach = gap + radius
    drawn.boxes.append((centre[0] - reach, centre[1] - reach, centre[0] + reach, centre[1] + reach))


def lone_pair_spots(
    molecule: Molecule, drawn: Drawn, pen: Pen, atom: int, given: int = 0
) -> list[tuple[Point, Point]]:
    """Where an atom's lone pairs are, as the two dots of each -- for an editor to show
    under the pointer: those the arrows drawn have not taken (``given``), where a drawing
    showing every pair puts them. A hydrogen has none, and none sits on its letter."""

    return pair_spots(molecule, drawn, pen, atom, molecule.atoms[atom].lone // 2 - given)


# -- vectors ----------------------------------------------------------------------------


def _minus(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _length(v: Point) -> float:
    return math.hypot(v[0], v[1])


def _unit(v: Point) -> Point:
    size = _length(v)
    return (v[0] / size, v[1] / size) if size > 1e-9 else (0.0, -1.0)


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _perpendicular(v: Point) -> Point:
    return (-v[1], v[0])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _step(point: Point, way: Point, reach: float) -> Point:
    return (point[0] + way[0] * reach, point[1] + way[1] * reach)


def _turn(way: Point, degrees: float) -> Point:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return (way[0] * cos - way[1] * sin, way[0] * sin + way[1] * cos)


def _to_segment(point: Point, a: Point, b: Point) -> float:
    along = _minus(b, a)
    size = along[0] ** 2 + along[1] ** 2
    if size < 1e-9:
        return math.dist(point, a)
    t = max(0.0, min(1.0, ((point[0] - a[0]) * along[0] + (point[1] - a[1]) * along[1]) / size))
    return math.dist(point, (a[0] + along[0] * t, a[1] + along[1] * t))
