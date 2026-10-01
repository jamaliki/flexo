"""Curly arrows drawn: from a lone pair or a bond, to an atom or where a bond will be.

An arrow leaves a lone pair from its dots, outward, and a bond from the middle of the
line whose electrons move (a double bond's second line); it ends just short of the
atom that takes a lone pair, pointing at the atom a new bond reaches, or at the middle
of a bond made stronger. It bends to whichever side keeps it off labels, bonds and the
other arrows of its step, bulging away from the molecule rather than into it. A pair of
electrons has a full head, one electron (a fishhook) half a head, on the outside of its
curve.
"""

from __future__ import annotations

import itertools
import math

from flexo.chemistry.draw import Drawn, Pen
from flexo.chemistry.electrons import Arrow
from flexo.chemistry.molecule import Molecule
from flexo.drawn import Shape, path

type Point = tuple[float, float]


def toward(molecule: Molecule, arrow: Arrow) -> float | None:
    """The direction (radians, y down) a lone-pair arrow leaves its atom: toward the atom
    it reaches. None for an arrow from a bond."""

    if len(arrow.source) != 1:
        return None
    (atom,) = arrow.source
    target = [other for other in arrow.target if other != atom] or list(arrow.target)
    x = sum(molecule.atoms[other].x for other in target) / len(target)
    y = sum(molecule.atoms[other].y for other in target) / len(target)
    return math.atan2(y - molecule.atoms[atom].y, x - molecule.atoms[atom].x)


def draw_arrows(
    molecule: Molecule,
    drawn: Drawn,
    arrows: list[Arrow],
    pen: Pen,
    *,
    prefix: str,
    tone: str | None,
) -> None:
    """Each arrow as a curve and its head, added to ``drawn``."""

    routes: list[list[Point]] = []
    centre = _centre(drawn)
    for number, arrow in enumerate(arrows):
        best = None
        for side in (1.0, -1.0):
            for depth in (1.0, 1.4, 0.75):
                curve = _curve(molecule, drawn, arrow, pen, side, depth)
                if curve is None:
                    continue
                score = _score(molecule, drawn, arrow, curve, routes, pen, centre)
                if best is None or score < best[0]:
                    best = (score, curve, side)
        if best is None:
            continue
        _, curve, side = best
        routes.append(_samples(curve, 24))
        _draw(drawn, curve, arrow.electrons, side, pen, f"{prefix}.arrow{number}", tone)


def _curve(
    molecule: Molecule, drawn: Drawn, arrow: Arrow, pen: Pen, side: float, depth: float
) -> tuple[Point, Point, Point, Point] | None:
    """The arrow's cubic, going round ``side`` (1 or -1) of what it starts from, ``depth``
    times as deep as usual. One side, kept from start to end: an arrow from a bond leaves
    the line on that side and ends on that side of the atom or bond it reaches."""

    atoms = drawn.atoms
    u = pen.u
    normal = _side_normal(molecule, drawn, arrow, side)
    # Where it starts, and the way it leaves.
    if len(arrow.source) == 1:
        (atom,) = arrow.source
        place = atoms[atom]
        aim = toward(molecule, arrow) or 0.0
        marks = place.pairs
        if arrow.electrons == 1 and place.radical is not None:
            marks = [place.radical]  # a fishhook leaves the radical's own electron
        if marks:
            angle, (px, py) = min(
                marks, key=lambda item: abs(math.remainder(item[0] - aim, 2 * math.pi))
            )
            start = (px + math.cos(angle) * pen.dot * 2.2, py + math.sin(angle) * pen.dot * 2.2)
        else:
            angle = aim
            reach = _reach(place, angle, pen) + u * 0.25
            start = (
                place.point[0] + math.cos(angle) * reach,
                place.point[1] + math.sin(angle) * reach,
            )
        out = (math.cos(angle), math.sin(angle))
        # From its dots, turned toward its side: an arc, not a dart.
        leave = _unit(out[0] + normal[0] * 0.8, out[1] + normal[1] * 0.8)
    else:
        lines = drawn.lines.get(frozenset(arrow.source))
        if not lines:
            return None
        line = max(
            lines, key=lambda item: _middle(item)[0] * normal[0] + _middle(item)[1] * normal[1]
        )
        middle = _middle(line)
        start = (middle[0] + normal[0] * u * 0.14, middle[1] + normal[1] * u * 0.14)
        leave = normal
    end, arrive = _end(molecule, drawn, arrow, pen, normal)
    distance = math.dist(start, end)
    if distance < 1e-6:
        return None
    reach = max(0.45 * distance, 0.75 * u) * depth
    first = (start[0] + leave[0] * reach, start[1] + leave[1] * reach)
    second = (end[0] - arrive[0] * reach, end[1] - arrive[1] * reach)
    return (start, first, second, end)


def _side_normal(molecule: Molecule, drawn: Drawn, arrow: Arrow, side: float) -> Point:
    """The way an arrow bulges: across its source bond (or its chord, from a lone pair) to
    ``side``; for a bond moved onto a neighbour, out of (or into) the angle they make."""

    atoms = drawn.atoms
    if len(arrow.source) == 2 and len(arrow.target) == 2:
        shared = set(arrow.source) & set(arrow.target)
        if len(shared) == 1:
            (pivot,) = shared
            (x,) = set(arrow.source) - shared
            (z,) = set(arrow.target) - shared
            p = atoms[pivot].point
            a = _unit(atoms[x].point[0] - p[0], atoms[x].point[1] - p[1])
            b = _unit(atoms[z].point[0] - p[0], atoms[z].point[1] - p[1])
            outside = (-(a[0] + b[0]), -(a[1] + b[1]))
            if math.hypot(*outside) < 1e-6:  # a straight line through the pivot: either side
                outside = (-a[1], a[0])
            outside = _unit(*outside)
            return outside if side > 0 else (-outside[0], -outside[1])
    if len(arrow.source) == 2:
        first, second = arrow.source
        if len(arrow.target) == 1 and arrow.target[0] == first:
            first, second = second, first
    else:
        (first,) = arrow.source
        others = [atom for atom in arrow.target if atom != first] or list(arrow.target)
        second = others[-1]
    p, q = atoms[first].point, atoms[second].point
    axis = _unit(q[0] - p[0], q[1] - p[1])
    return (-axis[1] * side, axis[0] * side)


def _end(
    molecule: Molecule, drawn: Drawn, arrow: Arrow, pen: Pen, normal: Point
) -> tuple[Point, Point]:
    """Where an arrow ends, and the way it is going there."""

    atoms = drawn.atoms
    u = pen.u
    if len(arrow.target) == 1 and len(arrow.source) == 2:
        # Its bond's electrons become a lone pair on this atom: end beside it, on the
        # arrow's side, a little past the bond, pointing in at it.
        (atom,) = arrow.target
        other = arrow.source[0] if arrow.source[1] == atom else arrow.source[1]
        place = atoms[atom]
        along = _unit(
            place.point[0] - atoms[other].point[0], place.point[1] - atoms[other].point[1]
        )
        # Beside the atom, a little before it, coming down onto it along the bond: the
        # arrow arcs out from the bond and back, a C, not a hook.
        direction = _unit(normal[0] - along[0] * 0.45, normal[1] - along[1] * 0.45)
        reach = _reach(place, math.atan2(direction[1], direction[0]), pen) + u * 0.22
        end = (place.point[0] + direction[0] * reach, place.point[1] + direction[1] * reach)
        return end, _unit(along[0] - normal[0] * 0.45, along[1] - normal[1] * 0.45)
    pair = arrow.target if len(arrow.target) == 2 else (arrow.source[0], arrow.target[0])
    first, second = pair
    if molecule.bond(first, second) is not None:
        # A bond made stronger: end at its middle, on the arrow's side, pointing into it.
        lines = drawn.lines.get(frozenset(pair))
        p, q = atoms[first].point, atoms[second].point
        middle = _middle(lines[0]) if lines else _middle((p, q))
        axis = _unit(q[0] - p[0], q[1] - p[1])
        across = (-axis[1], axis[0])
        if across[0] * normal[0] + across[1] * normal[1] < 0:
            across = (-across[0], -across[1])
        if lines:
            outer = max(
                lines, key=lambda item: _middle(item)[0] * across[0] + _middle(item)[1] * across[1]
            )
            middle = _middle(outer)
        end = (middle[0] + across[0] * u * 0.32, middle[1] + across[1] * u * 0.32)
        return end, (-across[0], -across[1])
    (x1, y1), (x2, y2) = atoms[first].point, atoms[second].point
    giver_atoms = set(arrow.source)
    # Two atoms near enough to see as one place (a bond about to form, as in a
    # cycloaddition): the arrow ends between them.
    if math.hypot(x2 - x1, y2 - y1) <= 2.2 * pen.bond and len(arrow.target) == 2:
        middle = ((x1 + x2) / 2, (y1 + y2) / 2)
        axis = _unit(x2 - x1, y2 - y1)
        across = (-axis[1], axis[0])
        if across[0] * normal[0] + across[1] * normal[1] < 0:
            across = (-across[0], -across[1])
        return (middle[0] + across[0] * u * 0.15, middle[1] + across[1] * u * 0.15), (
            -across[0],
            -across[1],
        )
    # A new bond to a far atom: point at it, from the atom that brings the bond.
    reached = second if first in giver_atoms else first
    giver = first if reached == second else second
    end = _short_of(drawn, reached, giver, pen)
    inward = _unit(atoms[reached].point[0] - end[0], atoms[reached].point[1] - end[1])
    return end, _unit(inward[0] - normal[0] * 0.45, inward[1] - normal[1] * 0.45)


def _short_of(drawn: Drawn, atom: int, giver: int, pen: Pen) -> Point:
    place = drawn.atoms[atom]
    back = _unit(
        drawn.atoms[giver].point[0] - place.point[0], drawn.atoms[giver].point[1] - place.point[1]
    )
    angle = math.atan2(back[1], back[0])
    # A vertex's bonds meet at it: stop well short, so the head sits clear of them.
    reach = _reach(place, angle, pen) + pen.u * (0.2 if place.radius[0] else 0.3)
    return (place.point[0] + back[0] * reach, place.point[1] + back[1] * reach)


def _reach(place, angle: float, pen: Pen) -> float:
    rx, ry = place.radius
    if rx <= 0.0:
        return pen.u * 0.15
    cos, sin = math.cos(angle), math.sin(angle)
    return 1.0 / math.sqrt((cos / rx) ** 2 + (sin / ry) ** 2)


def _score(
    molecule: Molecule,
    drawn: Drawn,
    arrow: Arrow,
    curve,
    routes: list[list[Point]],
    pen: Pen,
    centre: Point,
) -> float:
    """How badly a curve runs into things: labels, vertices, bonds, the step's other arrows."""

    points = _samples(curve, 24)[2:-2]
    own = set(arrow.source) | set(arrow.target)
    score = 0.0
    u = pen.u
    for index, place in drawn.atoms.items():
        if index in own:
            continue
        rx, ry = place.radius
        for x, y in points:
            dx, dy = x - place.point[0], y - place.point[1]
            if rx > 0 and (dx / (rx * 1.15)) ** 2 + (dy / (ry * 1.15)) ** 2 < 1:
                score += 4
            elif rx <= 0 and math.hypot(dx, dy) < u * 0.35:
                score += 2
    for key, lines in drawn.lines.items():
        if key == frozenset(arrow.source) or key == frozenset(arrow.target):
            continue
        for line in lines:
            for point in points:
                if _distance_to_segment(point, line) < u * 0.22:
                    score += 1.5
    for route in routes:
        for point in points:
            if any(math.dist(point, other) < u * 0.45 for other in route):
                score += 2
    for x0, y0, x1, y1 in drawn.boxes:
        for x, y in points:
            if x0 - u * 0.05 < x < x1 + u * 0.05 and y0 - u * 0.05 < y < y1 + u * 0.05:
                score += 1
    # Bulging into the molecule reads worse than out of it.
    middle = _bezier(curve, 0.5)
    chord_middle = ((curve[0][0] + curve[3][0]) / 2, (curve[0][1] + curve[3][1]) / 2)
    out = (middle[0] - chord_middle[0], middle[1] - chord_middle[1])
    inward = (centre[0] - chord_middle[0], centre[1] - chord_middle[1])
    if out[0] * inward[0] + out[1] * inward[1] > 0:
        score += 0.75
    # Shorter is better, all else equal.
    score += _length(curve) / (pen.bond * 20)
    return score


def _draw(
    drawn: Drawn, curve, electrons: int, side: float, pen: Pen, identifier: str, tone: str | None
) -> None:
    head = pen.u * 0.56
    width = pen.u * 0.4
    tip = curve[3]
    # The line stops where the head's notch is, so it does not poke through the tip.
    cut = _cut_back(curve, head * 0.7)
    shaft = path(
        "M",
        cut[0][0],
        cut[0][1],
        "C",
        cut[1][0],
        cut[1][1],
        cut[2][0],
        cut[2][1],
        cut[3][0],
        cut[3][1],
    )
    drawn.shapes.append(Shape(identifier, shaft, "line", tone=tone, width=pen.line * 1.05))
    # The head carries on from where its shaft stops.
    direction = _unit(tip[0] - cut[3][0], tip[1] - cut[3][1])
    normal = (-direction[1], direction[0])
    back = (tip[0] - direction[0] * head, tip[1] - direction[1] * head)
    notch = (tip[0] - direction[0] * head * 0.72, tip[1] - direction[1] * head * 0.72)
    left = (back[0] + normal[0] * width / 2, back[1] + normal[1] * width / 2)
    right = (back[0] - normal[0] * width / 2, back[1] - normal[1] * width / 2)
    if electrons == 1:
        # A fishhook's half head, on the outside of its curve.
        outside = _bezier(curve, 0.5)
        chord_middle = ((curve[0][0] + tip[0]) / 2, (curve[0][1] + tip[1]) / 2)
        towards = (outside[0] - chord_middle[0]) * normal[0] + (
            outside[1] - chord_middle[1]
        ) * normal[1]
        barb = left if towards > 0 else right
        on_line = (tip[0] - direction[0] * head * 0.72, tip[1] - direction[1] * head * 0.72)
        d = path("M", tip[0], tip[1], "L", barb[0], barb[1], "L", on_line[0], on_line[1], "Z")
    else:
        d = path(
            "M",
            tip[0],
            tip[1],
            "L",
            left[0],
            left[1],
            "L",
            notch[0],
            notch[1],
            "L",
            right[0],
            right[1],
            "Z",
        )
    drawn.shapes.append(Shape(f"{identifier}.head", d, "solid", tone=tone, width=pen.line * 0.5))
    drawn.boxes.append(
        (
            min(left[0], right[0], tip[0]),
            min(left[1], right[1], tip[1]),
            max(left[0], right[0], tip[0]),
            max(left[1], right[1], tip[1]),
        )
    )
    for x, y in _samples(curve, 12):
        drawn.boxes.append((x - pen.line, y - pen.line, x + pen.line, y + pen.line))
    del side


# -- curves ------------------------------------------------------------------------------


def _bezier(curve, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve
    u = 1 - t
    return (
        u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
        u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
    )


def _samples(curve, count: int) -> list[Point]:
    return [_bezier(curve, step / count) for step in range(count + 1)]


def _length(curve) -> float:
    points = _samples(curve, 16)
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def _cut_back(curve, length: float):
    """The curve up to the point ``length`` (straight) before its end."""

    end = curve[3]
    low, high = 0.0, 1.0
    for _ in range(40):
        middle = (low + high) / 2
        if math.dist(_bezier(curve, middle), end) > length:
            low = middle
        else:
            high = middle
    return _split(curve, low)


def _split(curve, t: float):
    """The part of a cubic from its start to ``t`` (de Casteljau)."""

    p0, p1, p2, p3 = curve

    def lerp(a: Point, b: Point) -> Point:
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    a, b, c = lerp(p0, p1), lerp(p1, p2), lerp(p2, p3)
    d, e = lerp(a, b), lerp(b, c)
    f = lerp(d, e)
    return (p0, a, d, f)


def _distance_to_segment(point: Point, segment) -> float:
    (x1, y1), (x2, y2) = segment
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    t = (
        0.0
        if length == 0
        else max(0.0, min(1.0, ((point[0] - x1) * dx + (point[1] - y1) * dy) / length))
    )
    return math.dist(point, (x1 + t * dx, y1 + t * dy))


def _middle(line) -> Point:
    (x1, y1), (x2, y2) = line
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _rotate(vector: Point, angle: float) -> Point:
    cos, sin = math.cos(angle), math.sin(angle)
    return (vector[0] * cos - vector[1] * sin, vector[0] * sin + vector[1] * cos)


def _unit(x: float, y: float) -> Point:
    length = math.hypot(x, y) or 1e-9
    return (x / length, y / length)


def _centre(drawn: Drawn) -> Point:
    points = [place.point for place in drawn.atoms.values()]
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
