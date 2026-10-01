"""Where each atom goes: a molecule laid out flat as a chemist would draw it.

Bonds are one unit long. A ring is a regular polygon, and rings that share a bond
are polygons on either side of it (naphthalene, a steroid); a ring that shares one
atom turns away from the first (a spiro centre). Chains zigzag at 120 degrees, a
triple bond runs straight on, and a branch takes the widest gap its atom has.
Branches that land on other atoms are turned over about their bond until none do.
A double bond keeps the side its SMILES gives each substituent (``F/C=C/F`` is
trans).

The molecule is then turned so that its bonds lie on ChemDraw's 30-degree grid,
preferring the turn that lays a chain out as a horizontal zigzag and a benzene
ring point up, the molecule wider than tall, and its first atom on the left.

Coordinates are y-down, as a page's are; a unit is one bond.
"""

from __future__ import annotations

import math
from collections import deque

from flexo.chemistry.molecule import Molecule

type Point = tuple[float, float]


def lay_out(molecule: Molecule, atoms: list[int] | None = None) -> None:
    """Give the atoms of ``molecule`` (or only ``atoms``, one of its fragments) their
    place, each fragment centred on the origin."""

    fragments = [atoms] if atoms is not None else molecule.fragments()
    for fragment in fragments:
        places = _place(molecule, fragment)
        _keep_double_bond_sides(molecule, places)
        _untangle(molecule, places)
        places = _turned(molecule, places)
        for atom, (x, y) in places.items():
            molecule.atoms[atom].x, molecule.atoms[atom].y = x, y


# -- rings -------------------------------------------------------------------------------


def rings(molecule: Molecule, atoms: list[int]) -> list[list[int]]:
    """The smallest set of smallest rings, each its atoms in order round it."""

    inside = set(atoms)
    edges = [bond for bond in molecule.bonds if bond.a in inside and bond.b in inside]
    rank = len(edges) - len(inside) + 1
    if rank <= 0:
        return []
    candidates: dict[frozenset[int], list[int]] = {}
    for removed in edges:
        route = _shortest(molecule, removed.a, removed.b, inside, removed)
        if route is not None:
            candidates.setdefault(frozenset(route), route)
    chosen: list[list[int]] = []
    basis: list[int] = []  # each chosen ring's bonds, as a bit set, reduced
    index = {frozenset((bond.a, bond.b)): position for position, bond in enumerate(edges)}
    for ring in sorted(candidates.values(), key=len):
        bits = 0
        for first, second in zip(ring, [*ring[1:], ring[0]], strict=True):
            bits |= 1 << index[frozenset((first, second))]
        for row in basis:
            bits = min(bits, bits ^ row)
        if bits:
            basis.append(bits)
            basis.sort(reverse=True)
            chosen.append(ring)
        if len(chosen) == rank:
            break
    return chosen


def _shortest(
    molecule: Molecule, start: int, end: int, inside: set[int], without
) -> list[int] | None:
    before = {start: start}
    queue = deque([start])
    while queue:
        atom = queue.popleft()
        if atom == end:
            route = [end]
            while route[-1] != start:
                route.append(before[route[-1]])
            return route[::-1]
        for bond in molecule.bonds_of(atom):
            if bond is without:
                continue
            other = bond.other(atom)
            if other in inside and other not in before:
                before[other] = atom
                queue.append(other)
    return None


def _systems(found: list[list[int]]) -> list[list[list[int]]]:
    """Rings that share atoms, together: each fused, bridged or spiro system."""

    systems: list[list[list[int]]] = []
    for ring in found:
        joined = [system for system in systems if any(set(ring) & set(other) for other in system)]
        merged = [ring]
        for system in joined:
            merged.extend(system)
            systems.remove(system)
        systems.append(merged)
    return systems


def _system_places(system: list[list[int]]) -> dict[int, Point]:
    """A ring system in coordinates of its own: each ring a regular polygon."""

    order = [max(system, key=len)]
    left = [ring for ring in system if ring is not order[0]]
    places: dict[int, Point] = {}
    _polygon(order[0], places, None)
    while left:
        # The next ring is the one most bound to what is placed: fused before spiro.
        ring = max(left, key=lambda item: (len(set(item) & set(places)), len(item)))
        left.remove(ring)
        shared = [atom for atom in ring if atom in places]
        if not shared:
            left.append(ring)
            continue
        _polygon(ring, places, shared)
    return places


def _polygon(ring: list[int], places: dict[int, Point], shared: list[int] | None) -> None:
    count = len(ring)
    radius = 1.0 / (2.0 * math.sin(math.pi / count))
    if not shared:
        # Point up: an atom at the top, a hexagon's sides upright.
        for step, atom in enumerate(ring):
            angle = -math.pi / 2 + 2 * math.pi * step / count
            places[atom] = (radius * math.cos(angle), radius * math.sin(angle))
        return
    centre_before = _centre([places[atom] for atom in places])
    if len(shared) == 1:
        # Spiro: the new ring turns away from what is there, through the shared atom.
        (atom,) = shared
        x, y = places[atom]
        away = _unit(x - centre_before[0], y - centre_before[1])
        centre = (x + away[0] * radius, y + away[1] * radius)
        start = math.atan2(y - centre[1], x - centre[0])
        at = ring.index(atom)
        for step in range(count):
            angle = start + 2 * math.pi * step / count
            places.setdefault(
                ring[(at + step) % count],
                (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)),
            )
        return
    # Fused or bridged: walk the ring from a placed atom, setting each run of new atoms
    # on a polygon's arc between the placed atoms it joins, bulging away from the rest.
    at = next(index for index, atom in enumerate(ring) if atom in places)
    walk = ring[at:] + ring[:at]
    runs: list[tuple[int, list[int], int]] = []
    run: list[int] = []
    previous = walk[0]
    for atom in [*walk[1:], walk[0]]:
        if atom in places:
            if run:
                runs.append((previous, run, atom))
                run = []
            previous = atom
        else:
            run.append(atom)
    for first, middle, last in runs:
        _arc(places, first, middle, last, centre_before, count)


def _arc(
    places: dict[int, Point], first: int, middle: list[int], last: int, away_from: Point, size: int
) -> None:
    """Atoms ``middle`` between placed ``first`` and ``last``, each a bond from the next,
    on the circle through both that bulges away from ``away_from``: a fused ring's
    regular polygon when the two are a bond apart, a bridge's arc when they are not."""

    del size
    (x1, y1), (x2, y2) = places[first], places[last]
    chord = math.hypot(x2 - x1, y2 - y1) or 1e-6
    steps = len(middle) + 1
    middle_point = ((x1 + x2) / 2, (y1 + y2) / 2)
    normal = _unit(-(y2 - y1), x2 - x1)
    if (middle_point[0] - away_from[0]) * normal[0] + (middle_point[1] - away_from[1]) * normal[
        1
    ] < 0:
        normal = (-normal[0], -normal[1])
    step = _arc_angle(chord, steps)
    if step <= 1e-6:  # the ends are as far apart as the atoms between can reach: a line
        for index, atom in enumerate(middle, start=1):
            places[atom] = (x1 + (x2 - x1) * index / steps, y1 + (y2 - y1) * index / steps)
        return
    radius = 1.0 / (2.0 * math.sin(step / 2.0))
    # The centre sits off the chord's middle: behind it for a shallow arc, past it for a
    # deep one (more than half a circle, a fused ring's).
    behind = radius * math.cos(steps * step / 2.0)
    centre = (middle_point[0] - normal[0] * behind, middle_point[1] - normal[1] * behind)
    start = math.atan2(y1 - centre[1], x1 - centre[0])
    bulge = math.atan2(normal[1], normal[0])
    halfway = start + steps * step / 2.0
    direction = 1.0 if abs(math.remainder(halfway - bulge, 2 * math.pi)) < 1e-3 else -1.0
    for index, atom in enumerate(middle, start=1):
        angle = start + direction * step * index
        places[atom] = (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle))


def _arc_angle(chord: float, steps: int) -> float:
    """The angle each of ``steps`` unit chords takes at the centre of the circle on which,
    together, they span a chord ``chord`` long: sin(steps t / 2) / sin(t / 2) = chord."""

    if chord >= steps - 1e-9:
        return 0.0
    low, high = 1e-9, 2 * math.pi / steps
    for _ in range(100):
        middle = (low + high) / 2
        if math.sin(steps * middle / 2) / math.sin(middle / 2) > chord:
            low = middle
        else:
            high = middle
    return (low + high) / 2


# -- the whole fragment ------------------------------------------------------------------


def _place(molecule: Molecule, atoms: list[int]) -> dict[int, Point]:
    found = rings(molecule, atoms)
    systems = _systems(found)
    system_of = {
        atom: number for number, system in enumerate(systems) for ring in system for atom in ring
    }
    placed_systems: set[int] = set()
    places: dict[int, Point] = {}
    turn: dict[int, float] = {}
    if systems:
        biggest = max(
            range(len(systems)), key=lambda number: len({a for r in systems[number] for a in r})
        )
        places.update(_system_places(systems[biggest]))
        placed_systems.add(biggest)
    else:
        start = _chain_end(molecule, atoms)
        places[start] = (0.0, 0.0)
        turn[start] = 1.0
    queue = deque(sorted(places))
    weights = _branch_sizes(molecule, atoms)
    while queue:
        atom = queue.popleft()
        new = [other for other in molecule.neighbours(atom) if other not in places]
        if not new:
            continue
        x, y = places[atom]
        known = [
            math.atan2(places[o][1] - y, places[o][0] - x)
            for o in molecule.neighbours(atom)
            if o in places
        ]
        new.sort(key=lambda other: -weights.get((atom, other), 1))
        angles = _directions(molecule, atom, known, len(new), turn.get(atom, 1.0), places)
        for other, angle in zip(new, angles, strict=True):
            target = (x + math.cos(angle), y + math.sin(angle))
            number = system_of.get(other)
            if number is not None and number not in placed_systems:
                local = _system_places(systems[number])
                _fit_system(local, other, target, angle)
                for ring_atom, point in local.items():
                    places.setdefault(ring_atom, point)
                placed_systems.add(number)
                queue.extend(sorted(local))
                continue
            places[other] = target
            # The next bond turns the other way: a zigzag.
            turn[other] = -turn.get(atom, 1.0) if len(known) == 1 else turn.get(atom, 1.0)
            queue.append(other)
    return places


def _chain_end(molecule: Molecule, atoms: list[int]) -> int:
    """An end of the longest chain: the far end of the far end from the first atom."""

    def farthest(start: int) -> int:
        seen = {start}
        queue = deque([start])
        last = start
        while queue:
            last = queue.popleft()
            for other in molecule.neighbours(last):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return last

    return farthest(farthest(atoms[0]))


def _branch_sizes(molecule: Molecule, atoms: list[int]) -> dict[tuple[int, int], int]:
    """For each bond (from, to), the atoms reached through it: bigger branches lead."""

    sizes: dict[tuple[int, int], int] = {}
    for atom in atoms:
        for other in molecule.neighbours(atom):
            seen = {atom, other}
            stack = [other]
            while stack:
                here = stack.pop()
                for next_atom in molecule.neighbours(here):
                    if next_atom not in seen:
                        seen.add(next_atom)
                        stack.append(next_atom)
            sizes[(atom, other)] = len(seen) - 1
    return sizes


def _linear(molecule: Molecule, atom: int) -> bool:
    """Whether an atom's bonds run straight through it: a triple bond's, an allene's middle."""

    orders = [bond.order for bond in molecule.bonds_of(atom)]
    return 3 in orders or orders.count(2) >= 2


def _directions(
    molecule: Molecule,
    atom: int,
    known: list[float],
    count: int,
    sign: float,
    places: dict[int, Point],
) -> list[float]:
    if not known:
        if count == 1:
            return [-math.pi / 6]
        return [-math.pi / 6 + 2 * math.pi * step / count for step in range(count)]
    if len(known) == 1:
        back = known[0]
        if _linear(molecule, atom) and count == 1:
            return [back + math.pi]
        if count == 1:
            first = back + sign * 2 * math.pi / 3
            other = back - sign * 2 * math.pi / 3
            x, y = places[atom]
            return [
                min(
                    (first, other),
                    key=lambda angle: _crowding(places, (x + math.cos(angle), y + math.sin(angle))),
                )
            ]
        if count == 2:
            return [back + sign * 2 * math.pi / 3, back - sign * 2 * math.pi / 3]
        if count == 3:
            return [back + math.pi, back + math.pi / 2, back - math.pi / 2]
        return [back + 2 * math.pi * step / (count + 1) for step in range(1, count + 1)]
    # Several bonds placed (a ring atom): spread the new ones over the widest gap.
    ordered = sorted(angle % (2 * math.pi) for angle in known)
    gaps = [
        ((ordered[(i + 1) % len(ordered)] - ordered[i]) % (2 * math.pi) or 2 * math.pi, ordered[i])
        for i in range(len(ordered))
    ]
    gap, start = max(gaps)
    if count == 2 and gap > math.pi:
        # Two on one ring atom: sixty degrees apart about the bisector, as gem-dimethyl is drawn.
        middle = start + gap / 2
        return (
            [middle - math.pi / 6, middle + math.pi / 6]
            if gap < 4.5
            else [middle - math.pi / 3, middle + math.pi / 3]
        )
    return [start + gap * step / (count + 1) for step in range(1, count + 1)]


def _crowding(places: dict[int, Point], point: Point) -> float:
    return sum(1.0 / max(math.dist(point, other), 0.2) ** 2 for other in places.values())


def _fit_system(local: dict[int, Point], atom: int, target: Point, angle: float) -> None:
    """Move a ring system's own coordinates so ``atom`` lands on ``target``, its ring
    bonds splayed evenly about the bond that brought it there."""

    x, y = local[atom]
    outward = [0.0, 0.0]
    for other, (ox, oy) in local.items():
        if other != atom and math.isclose(math.dist((x, y), (ox, oy)), 1.0, abs_tol=0.05):
            ux, uy = _unit(x - ox, y - oy)
            outward[0] += ux
            outward[1] += uy
    if abs(outward[0]) + abs(outward[1]) < 1e-9:
        centre = _centre(list(local.values()))
        outward = [x - centre[0], y - centre[1]]
    have = math.atan2(outward[1], outward[0])
    want = angle + math.pi  # pointing back to the atom it hangs from
    turn = want - have
    cos, sin = math.cos(turn), math.sin(turn)
    for other, (ox, oy) in list(local.items()):
        dx, dy = ox - x, oy - y
        local[other] = (target[0] + dx * cos - dy * sin, target[1] + dx * sin + dy * cos)


# -- tidying -------------------------------------------------------------------------------


def _keep_double_bond_sides(molecule: Molecule, places: dict[int, Point]) -> None:
    """Turn over one end of each double bond whose substituents lie on the wrong sides."""

    found = {frozenset(ring) for ring in rings(molecule, list(places))}
    for bond in molecule.bonds:
        if bond.order != 2 or bond.a not in places:
            continue
        if any({bond.a, bond.b} <= ring for ring in found):
            continue
        first = _marked(molecule, bond.a, bond)
        second = _marked(molecule, bond.b, bond)
        if first is None or second is None:
            continue
        (left, left_side), (right, right_side) = first, second
        want_same = left_side == right_side
        a, b = places[bond.a], places[bond.b]
        same = _side(a, b, places[left]) == _side(a, b, places[right])
        if same != want_same:
            for atom in _beyond(molecule, bond.b, bond.a):
                places[atom] = _reflected(places[atom], a, b)


def _marked(molecule: Molecule, atom: int, double) -> tuple[int, int] | None:
    """A neighbour of a double bond's atom whose bond says which side it is on, and the
    side: -1 below, 1 above (from ``atom``'s point of view)."""

    for bond in molecule.bonds_of(atom):
        if bond is double or not bond.stereo:
            continue
        other = bond.other(atom)
        written_toward = bond.b == atom  # written other, then atom
        up = (bond.stereo == "/") != written_toward
        return other, 1 if up else -1
    return None


def _side(a: Point, b: Point, point: Point) -> bool:
    return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0]) > 0


def _beyond(molecule: Molecule, start: int, behind: int) -> list[int]:
    """The atoms reached from ``start`` without going through ``behind`` (``start`` too)."""

    seen = {start, behind}
    stack = [start]
    found = [start]
    while stack:
        atom = stack.pop()
        for other in molecule.neighbours(atom):
            if other not in seen:
                seen.add(other)
                found.append(other)
                stack.append(other)
    return found


def _reflected(point: Point, a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy or 1e-9
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
    foot = (a[0] + t * dx, a[1] + t * dy)
    return (2 * foot[0] - point[0], 2 * foot[1] - point[1])


def _clashes(molecule: Molecule, places: dict[int, Point]) -> list[tuple[int, int]]:
    atoms = list(places)
    found = []
    for i, first in enumerate(atoms):
        for second in atoms[i + 1 :]:
            if (
                math.dist(places[first], places[second]) < 0.6
                and molecule.bond(first, second) is None
            ):
                found.append((first, second))
    return found


def _untangle(molecule: Molecule, places: dict[int, Point]) -> None:
    """Turn over branches about their bonds until no two atoms sit on one another."""

    in_ring = {atom for ring in rings(molecule, list(places)) for atom in ring}
    for _ in range(12):
        clashes = _clashes(molecule, places)
        if not clashes:
            return
        best, best_count = None, len(clashes)
        for bond in molecule.bonds:
            if bond.a not in places or (bond.a in in_ring and bond.b in in_ring):
                continue
            for start, behind in ((bond.b, bond.a), (bond.a, bond.b)):
                moved = _beyond(molecule, start, behind)
                if len(moved) * 2 > len(places):
                    continue
                trial = dict(places)
                for atom in moved:
                    trial[atom] = _reflected(places[atom], places[bond.a], places[bond.b])
                count = len(_clashes(molecule, trial))
                if count < best_count:
                    best, best_count = trial, count
        if best is None:
            return
        places.update(best)


def _turned(molecule: Molecule, places: dict[int, Point]) -> dict[int, Point]:
    """``places`` turned onto the 30-degree grid -- the turn that lays chains out as a
    horizontal zigzag and rings point up, wider than tall, first atom on the left --
    and centred on the origin."""

    if len(places) == 1:
        return {atom: (0.0, 0.0) for atom in places}
    bonds = [bond for bond in molecule.bonds if bond.a in places and bond.b in places]
    first_angle = 0.0
    if bonds:
        a, b = places[bonds[0].a], places[bonds[0].b]
        first_angle = math.atan2(b[1] - a[1], b[0] - a[0])
    found = rings(molecule, list(places))
    turns = [-first_angle + math.radians(30 * step + 30) for step in range(12)]
    for ring in found:
        if len(ring) % 2:
            # An odd ring sits level only with one of its atoms straight up or down.
            cx = sum(places[atom][0] for atom in ring) / len(ring)
            cy = sum(places[atom][1] for atom in ring) / len(ring)
            for atom in ring:
                angle = math.atan2(places[atom][1] - cy, places[atom][0] - cx)
                turns += [-math.pi / 2 - angle, math.pi / 2 - angle]
    best = None
    for turn in turns:
        for mirror in (False, True):
            trial = _rotated(places, turn, mirror)
            xs = [p[0] for p in trial.values()]
            ys = [p[1] for p in trial.values()]
            width, height = max(xs) - min(xs), max(ys) - min(ys)
            upright = 0
            for bond in bonds:
                (x1, y1), (x2, y2) = trial[bond.a], trial[bond.b]
                degrees = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 60
                upright += min(abs(degrees - 30), abs(degrees + 30 - 60)) < 3
            level = sum(_level(molecule, trial, ring) for ring in found)
            first = min(places)
            leftmost = trial[first][0] - min(xs)
            score = (upright + 2 * level, round(width - height, 3), -round(leftmost, 3), not mirror)
            if best is None or score > best[0]:
                best = (score, trial)
    turned = best[1]  # type: ignore[index]
    xs = [p[0] for p in turned.values()]
    ys = [p[1] for p in turned.values()]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {atom: (x - cx, y - cy) for atom, (x, y) in turned.items()}


def _level(molecule: Molecule, places: dict[int, Point], ring: list[int]) -> float:
    """How well a ring stands: level (an atom straight above or below its centre), better
    with that atom not carbon, best with it below (furan, pyrrole, as they are drawn)."""

    cx = sum(places[atom][0] for atom in ring) / len(ring)
    cy = sum(places[atom][1] for atom in ring) / len(ring)
    best = 0.0
    for atom in ring:
        if abs(places[atom][0] - cx) < 1e-3:
            score = 1.0
            if molecule.atoms[atom].element != "C":
                score += 1.0 + 0.25 * (places[atom][1] > cy)
            best = max(best, score)
    return best


def _rotated(places: dict[int, Point], turn: float, mirror: bool) -> dict[int, Point]:
    cos, sin = math.cos(turn), math.sin(turn)
    out = {}
    for atom, (x, y) in places.items():
        x, y = x * cos - y * sin, x * sin + y * cos
        out[atom] = (-x, y) if mirror else (x, y)
    return out


def _unit(x: float, y: float) -> Point:
    length = math.hypot(x, y) or 1e-9
    return (x / length, y / length)


def _centre(points: list[Point]) -> Point:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


# -- several molecules, and the steps of a mechanism -------------------------------------


def assemble(molecule: Molecule, meetings: list[tuple[int, int]], gap: float = 2.1) -> None:
    """Lay out each fragment, then set them together: a fragment an arrow bonds to another
    beside the atom it will bond to, ``gap`` bonds off on that atom's freest side, facing
    it; the rest in a row to the right. ``meetings`` are the pairs of atoms that bond."""

    fragments = molecule.fragments()
    for fragment in fragments:
        lay_out(molecule, fragment)
    if len(fragments) < 2:
        return
    group = {atom: number for number, fragment in enumerate(fragments) for atom in fragment}
    biggest = max(range(len(fragments)), key=lambda number: len(fragments[number]))
    placed = {biggest}
    moving = True
    while moving:
        moving = False
        for first, second in meetings:
            for anchor, mover in ((first, second), (second, first)):
                if group[anchor] in placed and group[mover] not in placed:
                    fixed = [atom for number in placed for atom in fragments[number]]
                    _approach(molecule, fixed, fragments[group[mover]], anchor, mover, gap)
                    placed.add(group[mover])
                    moving = True
    for number, fragment in enumerate(fragments):
        if number in placed:
            continue
        fixed = [atom for done in placed for atom in fragments[done]]
        right = max(molecule.atoms[atom].x for atom in fixed)
        middle = sum(molecule.atoms[atom].y for atom in fixed) / len(fixed)
        left = min(molecule.atoms[atom].x for atom in fragment)
        centre = sum(molecule.atoms[atom].y for atom in fragment) / len(fragment)
        for atom in fragment:
            molecule.atoms[atom].x += right + 1.6 - left
            molecule.atoms[atom].y += middle - centre
        placed.add(number)
    _separate(molecule)


def follow(before: Molecule, after: Molecule) -> None:
    """Place ``after`` -- ``before`` once its arrows have moved their electrons -- where
    ``before`` was drawn: atoms keep their places; a fragment newly bonded to another
    comes to it, a bond's length off; one broken away stands a little apart."""

    for atom, old in zip(after.atoms, before.atoms, strict=True):
        atom.x, atom.y = old.x, old.y
    old_bonds = {frozenset((bond.a, bond.b)) for bond in before.bonds}
    new_bonds = {frozenset((bond.a, bond.b)) for bond in after.bonds}
    group = {
        atom: number for number, fragment in enumerate(before.fragments()) for atom in fragment
    }
    members: dict[int, list[int]] = {}
    for atom, number in group.items():
        members.setdefault(number, []).append(atom)
    for pair in sorted(new_bonds - old_bonds, key=sorted):
        a, b = sorted(pair)
        if group[a] == group[b]:
            continue
        first, second = members[group[a]], members[group[b]]
        anchor, mover, fixed, moved = (
            (a, b, first, second) if len(first) >= len(second) else (b, a, second, first)
        )
        _approach(after, fixed, moved, anchor, mover, 1.0)
        keep, gone = group[anchor], group[mover]
        for atom in moved:
            group[atom] = keep
        members[keep] = fixed + moved
        del members[gone]
    fragments = after.fragments()
    where = {atom: number for number, fragment in enumerate(fragments) for atom in fragment}
    for pair in sorted(old_bonds - new_bonds, key=sorted):
        a, b = sorted(pair)
        if where[a] == where[b]:
            continue
        stay, go = (a, b) if len(fragments[where[a]]) >= len(fragments[where[b]]) else (b, a)
        dx, dy = after.atoms[go].x - after.atoms[stay].x, after.atoms[go].y - after.atoms[stay].y
        length = math.hypot(dx, dy) or 1.0
        for atom in fragments[where[go]]:
            after.atoms[atom].x += dx / length * 0.9
            after.atoms[atom].y += dy / length * 0.9
    changed = {atom for pair in (new_bonds ^ old_bonds) for atom in pair}
    closed = [pair for pair in new_bonds - old_bonds if _in_ring(after, pair)]
    if closed:
        # A ring closed (a cyclisation, a cycloaddition): its molecule laid out afresh, as a
        # ring is drawn, and turned onto where its atoms were.
        for fragment in after.fragments():
            if any(set(pair) <= set(fragment) for pair in closed):
                old = {atom: (after.atoms[atom].x, after.atoms[atom].y) for atom in fragment}
                lay_out(after, fragment)
                transform = _fit(
                    [((after.atoms[atom].x, after.atoms[atom].y), old[atom]) for atom in fragment]
                )
                for atom in fragment:
                    after.atoms[atom].x, after.atoms[atom].y = transform(
                        (after.atoms[atom].x, after.atoms[atom].y)
                    )
    else:
        for atom in sorted(changed):
            _spread_branches(after, atom)
    _separate(after)


def _in_ring(molecule: Molecule, pair) -> bool:
    """Whether a bond lies in a ring: its atoms are joined another way too."""

    a, b = sorted(pair)
    bond = molecule.bond(a, b)
    if bond is None:
        return False
    fragment = next(f for f in molecule.fragments() if a in f)
    return _shortest(molecule, a, b, set(fragment), bond) is not None


def foresee(
    molecule: Molecule, made: Molecule, meetings: list[tuple[int, int]], apart: float = 0.65
) -> bool:
    """Lay out a step that closes a ring between its molecules (a cycloaddition) in the
    shape of what it makes -- a diene curled s-cis, as it must be to react -- its molecules
    drawn apart along the bonds they will form. False, and nothing done, for any other step."""

    fragments = molecule.fragments()
    where = {atom: number for number, fragment in enumerate(fragments) for atom in fragment}
    across: dict[frozenset[int], int] = {}
    for a, b in meetings:
        if where[a] != where[b]:
            key = frozenset((where[a], where[b]))
            across[key] = across.get(key, 0) + 1
    if not any(count >= 2 for count in across.values()):
        return False
    lay_out(made)
    for atom, shaped in zip(molecule.atoms, made.atoms, strict=True):
        atom.x, atom.y = shaped.x, shaped.y
    biggest = max(range(len(fragments)), key=lambda number: len(fragments[number]))
    cx = sum(molecule.atoms[atom].x for atom in fragments[biggest]) / len(fragments[biggest])
    cy = sum(molecule.atoms[atom].y for atom in fragments[biggest]) / len(fragments[biggest])
    for number, fragment in enumerate(fragments):
        if number == biggest:
            continue
        fx = sum(molecule.atoms[atom].x for atom in fragment) / len(fragment)
        fy = sum(molecule.atoms[atom].y for atom in fragment) / len(fragment)
        ux, uy = _unit(fx - cx, fy - cy)
        for atom in fragment:
            molecule.atoms[atom].x += ux * apart
            molecule.atoms[atom].y += uy * apart
    return True


def _spread_branches(molecule: Molecule, atom: int) -> None:
    """Spread an atom's branches evenly round it again -- an atom that gains a fourth bond
    stands as a cross, one that loses a bond opens to 120 degrees -- turning each branch
    whole about the atom; its largest branch, and any ring through it, stay."""

    neighbours = molecule.neighbours(atom)
    if len(neighbours) < 2:
        return
    found = rings(
        molecule, molecule.fragments()[[atom in f for f in molecule.fragments()].index(True)]
    )
    if any(atom in ring for ring in found):
        return
    atoms = molecule.atoms
    cx, cy = atoms[atom].x, atoms[atom].y
    branches = {other: _beyond(molecule, other, atom) for other in neighbours}
    if any(atom in branch for branch in branches.values()):
        return
    angles = {other: math.atan2(atoms[other].y - cy, atoms[other].x - cx) for other in neighbours}
    keep = max(neighbours, key=lambda other: len(branches[other]))
    order = sorted(neighbours, key=lambda other: (angles[other] - angles[keep]) % (2 * math.pi))
    count = len(order)
    if (
        count == 2
        and any(bond.order >= 2 for bond in molecule.bonds_of(atom))
        and _linear(molecule, atom)
    ):
        step = math.pi
    else:
        step = 2 * math.pi / count if count != 2 else 2 * math.pi / 3
    for position, other in enumerate(order[1:], start=1):
        want = angles[keep] + step * position * (
            1 if count != 2 else _turn_sign(angles, keep, other)
        )
        turn = want - angles[other]
        cos, sin = math.cos(turn), math.sin(turn)
        for moved in branches[other]:
            dx, dy = atoms[moved].x - cx, atoms[moved].y - cy
            atoms[moved].x, atoms[moved].y = cx + dx * cos - dy * sin, cy + dx * sin + dy * cos


def _turn_sign(angles: dict[int, float], keep: int, other: int) -> float:
    """For two branches, which way round the second lies from the first."""

    return 1.0 if math.remainder(angles[other] - angles[keep], 2 * math.pi) >= 0 else -1.0


def align(before: Molecule, after: Molecule) -> None:
    """Lay out ``after`` (a step drawn by hand) and turn each of its fragments onto the
    atoms of ``before`` that share their maps, so the reader sees what moved."""

    for fragment in after.fragments():
        lay_out(after, fragment)
    known = {atom.map: atom for atom in before.atoms if atom.map is not None}
    for fragment in after.fragments():
        pairs = [
            (
                (after.atoms[atom].x, after.atoms[atom].y),
                (known[after.atoms[atom].map].x, known[after.atoms[atom].map].y),
            )
            for atom in fragment
            if after.atoms[atom].map in known
        ]
        if not pairs:
            continue
        if len(pairs) == 1:
            (x, y), (tx, ty) = pairs[0]
            for atom in fragment:
                after.atoms[atom].x += tx - x
                after.atoms[atom].y += ty - y
            continue
        transform = _fit(pairs)
        for atom in fragment:
            after.atoms[atom].x, after.atoms[atom].y = transform(
                (after.atoms[atom].x, after.atoms[atom].y)
            )
    _separate(after)


def _fit(pairs: list[tuple[Point, Point]]):
    """The turn (or turn and mirror) and move that best lays the first points of
    ``pairs`` on the second (least squares)."""

    sx = sum(p[0] for p, _ in pairs) / len(pairs)
    sy = sum(p[1] for p, _ in pairs) / len(pairs)
    tx = sum(q[0] for _, q in pairs) / len(pairs)
    ty = sum(q[1] for _, q in pairs) / len(pairs)
    best = None
    for mirror in (1.0, -1.0):
        a = b = 0.0
        for (px, py), (qx, qy) in pairs:
            px, py = (px - sx) * mirror, py - sy
            qx, qy = qx - tx, qy - ty
            a += px * qx + py * qy
            b += px * qy - py * qx
        angle = math.atan2(b, a)
        cos, sin = math.cos(angle), math.sin(angle)
        error = 0.0
        for (px, py), (qx, qy) in pairs:
            px, py = (px - sx) * mirror, py - sy
            error += (px * cos - py * sin + tx - qx) ** 2 + (px * sin + py * cos + ty - qy) ** 2
        if best is None or error < best[0]:
            best = (error, mirror, cos, sin)
    _, mirror, cos, sin = best  # type: ignore[misc]

    def transform(point: Point) -> Point:
        px, py = (point[0] - sx) * mirror, point[1] - sy
        return (px * cos - py * sin + tx, px * sin + py * cos + ty)

    return transform


def _approach(
    molecule: Molecule, fixed: list[int], moved: list[int], anchor: int, mover: int, distance: float
) -> None:
    """Move the atoms ``moved`` (rigidly) so ``mover`` stands ``distance`` from ``anchor``
    on its freest side, its own bonds turned away from it."""

    atoms = molecule.atoms
    ax, ay = atoms[anchor].x, atoms[anchor].y
    own = [other for other in molecule.neighbours(anchor) if other in fixed and other != mover]
    angles = [math.atan2(atoms[o].y - ay, atoms[o].x - ax) for o in own]
    others = [(atoms[atom].x, atoms[atom].y) for atom in fixed if atom != anchor]

    def crowding(angle: float) -> float:
        point = (ax + math.cos(angle) * distance, ay + math.sin(angle) * distance)
        near = sum(1.0 / max(math.dist(point, other), 0.3) ** 2 for other in others)
        clear = min(
            (abs(math.remainder(angle - other, 2 * math.pi)) for other in angles), default=math.pi
        )
        return near - clear * 2.0

    candidates = [math.radians(degrees) for degrees in range(0, 360, 15)]
    angle = min(candidates, key=crowding)
    mx, my = atoms[mover].x, atoms[mover].y
    outward = [0.0, 0.0]
    for other in molecule.neighbours(mover):
        if other in moved:
            ux, uy = _unit(mx - atoms[other].x, my - atoms[other].y)
            outward[0] += ux
            outward[1] += uy
    turn = 0.0
    if abs(outward[0]) + abs(outward[1]) > 1e-9:
        turn = (angle + math.pi) - math.atan2(outward[1], outward[0])
    cos, sin = math.cos(turn), math.sin(turn)
    tx, ty = ax + math.cos(angle) * distance, ay + math.sin(angle) * distance
    for atom in moved:
        dx, dy = atoms[atom].x - mx, atoms[atom].y - my
        atoms[atom].x, atoms[atom].y = tx + dx * cos - dy * sin, ty + dx * sin + dy * cos


def _separate(molecule: Molecule, least: float = 0.9) -> None:
    """Push fragments apart until none comes nearer another than ``least`` bonds, counted
    from the edges of their atoms' labels (a written atom is wider than a vertex)."""

    fragments = molecule.fragments()
    atoms = molecule.atoms

    def room(atom: int) -> float:
        item = atoms[atom]
        if item.element == "C" and molecule.neighbours(atom) and item.isotope is None:
            return 0.15
        return (
            0.35
            + 0.22 * (item.hydrogens > 0)
            + 0.1 * (item.hydrogens > 1)
            + 0.15 * (len(item.element) > 1)
        )

    for _ in range(30):
        moved = False
        for i, first in enumerate(fragments):
            for second in fragments[i + 1 :]:
                closest = min(
                    (
                        math.dist((atoms[a].x, atoms[a].y), (atoms[b].x, atoms[b].y))
                        - room(a)
                        - room(b),
                        a,
                        b,
                    )
                    for a in first
                    for b in second
                )
                if closest[0] >= least:
                    continue
                small = second if len(second) <= len(first) else first
                _, a, b = closest
                if small is first:
                    a, b = b, a
                dx, dy = atoms[b].x - atoms[a].x, atoms[b].y - atoms[a].y
                ux, uy = _unit(dx, dy) if math.hypot(dx, dy) > 1e-6 else (1.0, 0.0)
                push = least - closest[0] + 0.05
                for atom in small:
                    atoms[atom].x += ux * push
                    atoms[atom].y += uy * push
                moved = True
        if not moved:
            return


def gather(molecule: Molecule, meetings: list[tuple[int, int]], gap: float = 2.1) -> None:
    """Bring a fragment an arrow of this step will bond to another near it, if it is far."""

    for first, second in meetings:
        fragments = molecule.fragments()
        where = {atom: number for number, fragment in enumerate(fragments) for atom in fragment}
        if where[first] == where[second]:
            continue
        a, b = molecule.atoms[first], molecule.atoms[second]
        if math.hypot(a.x - b.x, a.y - b.y) <= gap + 0.5:
            continue
        one, two = fragments[where[first]], fragments[where[second]]
        if len(one) >= len(two):
            _approach(molecule, one, two, first, second, gap)
        else:
            _approach(molecule, two, one, second, first, gap)
    _separate(molecule)
