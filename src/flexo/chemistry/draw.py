"""A molecule drawn to the ACS proportions, in a figure's words and pen.

Measures follow the ACS 1996 document settings ChemDraw ships with, scaled to the
label size ``u``: a bond 1.44 label heights long, a double bond's lines 18 % of a
bond apart, a wedge as wide at its end as a fifth of a bond, a margin of 0.16 label
heights round every label. Carbon is a vertex; every other atom is its symbol,
centred on its place, with its hydrogens on the side its bonds leave free (``OH``,
``HO``, ``H₂N``). A bond stops short of a label by the margin. A double bond in a
ring lies inside it, its inner line shortened; one to a labelled end atom (``C=O``)
is centred on its bond; one between two carbons lies on the side its substituents
are. Charges are circled, as mechanisms draw them, or written after the symbol.
Lone pairs are pairs of dots in the widest gaps an atom has, a radical one dot.

Everything is in points, y down: shapes and words for ``flexo.drawn``.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from flexo.chemistry.layout import rings
from flexo.chemistry.molecule import Molecule
from flexo.drawn import Shape, Words, path
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import TextRun

type Point = tuple[float, float]
type Box = tuple[float, float, float, float]

MINUS = "\N{MINUS SIGN}"

METALS = frozenset({
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Y", "Zr", "Nb", "Mo", "Tc",
    "Ru", "Rh", "Pd", "Ag", "Cd", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "La",
    "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
})
"""Transition metals and lanthanides: their d and f electrons are not lone pairs."""


@dataclass(frozen=True, slots=True)
class Pen:
    """The measures a molecule is drawn with, from the label size ``u`` (points)."""

    u: float
    measure: Callable[[tuple[TextRun, ...]], TextMetrics]

    @property
    def bond(self) -> float:
        return 1.44 * self.u

    @property
    def line(self) -> float:
        return 0.075 * self.u

    @property
    def gap(self) -> float:
        return 0.18 * self.bond

    @property
    def margin(self) -> float:
        return 0.18 * self.u

    @property
    def wedge(self) -> float:
        return 0.2 * self.bond

    @property
    def dot(self) -> float:
        return 0.075 * self.u


@dataclass(slots=True)
class Atomic:
    """Where an atom is drawn, and what is drawn round it."""

    point: Point
    radius: tuple[float, float] = (0.0, 0.0)
    """The half-width and half-height of the ellipse its symbol keeps clear (0 for a vertex)."""
    taken: list[float] = field(default_factory=list)
    """Directions (radians, y down) its bonds, hydrogens and marks already use."""
    pairs: list[tuple[float, Point]] = field(default_factory=list)
    """Each lone pair drawn: its direction, and the middle of its two dots."""
    radical: tuple[float, Point] | None = None
    """Its radical's dot, if it has one: its direction and place."""
    label: Box | None = None
    """The box of a label written across (``OH``, ``H₂N``), when it is wider than its symbol."""
    label_side: str = ""
    ink: list[Box] = field(default_factory=list)
    """The boxes its letters take: its label, and hydrogens written above or below it."""


@dataclass(slots=True)
class Drawn:
    shapes: list[Shape] = field(default_factory=list)
    words: list[Words] = field(default_factory=list)
    atoms: dict[int, Atomic] = field(default_factory=dict)
    boxes: list[Box] = field(default_factory=list)
    """The ink of every label and mark, to keep arrows clear of."""
    lines: dict[frozenset[int], list[tuple[Point, Point]]] = field(default_factory=dict)
    """Each bond's drawn lines, its main line first (a wedge's middle stands for it)."""
    marks: list[tuple[int, float, float, float]] = field(default_factory=list)
    """What is drawn beside an atom besides its label -- a circled charge -- as the atom
    it belongs to and a circle (x, y, radius), for arrows to keep off."""

    def moved(self, dx: float, dy: float) -> Drawn:
        """The same drawing ``dx``, ``dy`` along: drawn once and put where it goes, rather
        than drawn again there."""

        from dataclasses import replace

        from flexo.render_drawn import _moved

        def point(at: Point) -> Point:
            return (at[0] + dx, at[1] + dy)

        def box(at: Box) -> Box:
            return (at[0] + dx, at[1] + dy, at[2] + dx, at[3] + dy)

        atoms = {
            index: Atomic(
                point(place.point),
                place.radius,
                list(place.taken),
                [(angle, point(middle)) for angle, middle in place.pairs],
                (place.radical[0], point(place.radical[1])) if place.radical else None,
                box(place.label) if place.label is not None else None,
                place.label_side,
                [box(item) for item in place.ink],
            )
            for index, place in self.atoms.items()
        }
        return Drawn(
            [replace(shape, d=_moved(shape.d, dx, dy)) for shape in self.shapes],
            [replace(words, x=words.x + dx, y=words.y + dy) for words in self.words],
            atoms,
            [box(item) for item in self.boxes],
            {key: [(point(a), point(b)) for a, b in items] for key, items in self.lines.items()},
            [(atom, x + dx, y + dy, radius) for atom, x, y, radius in self.marks],
        )

    def bounds(self) -> Box:
        xs, ys = [], []
        for atom in self.atoms.values():
            xs.append(atom.point[0])
            ys.append(atom.point[1])
        for x0, y0, x1, y1 in self.boxes:
            xs += [x0, x1]
            ys += [y0, y1]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


def labelled(molecule: Molecule, atom: int) -> bool:
    """Whether an atom is written: any but carbon, and a carbon with an isotope, on its own
    (``CH₄``), or with one other atom besides hydrogen that is not carbon (``H₃C-Br``,
    ``H₃C-OH``), where a bare line would say less than its formula. Ethene stays a line."""

    item = molecule.atoms[atom]
    if item.element != "C" or item.isotope is not None:
        return True
    heavy = []
    seen, stack = {atom}, [atom]
    while stack:
        here = stack.pop()
        if molecule.atoms[here].element != "H":
            heavy.append(molecule.atoms[here].element)
            if len(heavy) > 2:
                return False
        for other in molecule.neighbours(here):
            if other not in seen:
                seen.add(other)
                stack.append(other)
    return len(heavy) == 1 or any(element != "C" for element in heavy)


def draw_molecule(
    molecule: Molecule,
    pen: Pen,
    *,
    prefix: str,
    origin: Point = (0.0, 0.0),
    pairs: str = "used",
    used: dict[int, list[float]] | None = None,
    lone: dict[int, float] | None = None,
    charges: str = "circled",
    wedges: dict[tuple[int, int], str] | None = None,
    avoid: list[list[Point]] | None = None,
) -> Drawn:
    """Shapes and words for ``molecule``, its layout's unit scaled to a bond.

    The electrons an arrow takes are drawn by the arrow, at its tail, in its ink
    (``flexo.chemistry.curly``): ``used`` gives, for each atom, the directions its arrows
    leave it, which its other marks keep clear of, and ``lone`` the atoms whose radical a
    fishhook takes. ``pairs`` says which other lone pairs are drawn: ``all`` (on every
    atom but carbon, and a carbanion's) or none (``used``, ``none``). ``wedges`` maps a
    bond (from its stereo centre) to ``wedge`` or ``hash``; ``avoid`` gives the arrows'
    strokes, as points, for circled charges to keep off."""

    drawn = Drawn()
    scale = pen.bond
    points = {
        index: (origin[0] + atom.x * scale, origin[1] + atom.y * scale)
        for index, atom in enumerate(molecule.atoms)
    }
    for index in range(len(molecule.atoms)):
        drawn.atoms[index] = Atomic(points[index])
    for bond in molecule.bonds:
        for first, second in ((bond.a, bond.b), (bond.b, bond.a)):
            (x1, y1), (x2, y2) = points[first], points[second]
            drawn.atoms[first].taken.append(math.atan2(y2 - y1, x2 - x1))
    # Where the arrows' own electrons are drawn, kept clear before anything else is put
    # round the atom: the hydrogens written beside it go to the other side (``OH₂``
    # facing what its pair attacks), its charge and other pairs elsewhere.
    for index, leaving in (used or {}).items():
        drawn.atoms[index].taken.extend(leaving)
    for index in range(len(molecule.atoms)):
        if labelled(molecule, index):
            _label(molecule, index, pen, drawn, prefix, charges)
    found = rings(molecule, list(range(len(molecule.atoms))))
    for number, bond in enumerate(molecule.bonds):
        style = (wedges or {}).get((bond.a, bond.b)) or (wedges or {}).get((bond.b, bond.a))
        start = bond.a if (wedges or {}).get((bond.a, bond.b)) else bond.b if style else bond.a
        _bond(molecule, bond, pen, drawn, f"{prefix}.bond{number}", found, style, start)
    strokes = [line for stroke in avoid or [] for line in itertools.pairwise(stroke)]
    for index in range(len(molecule.atoms)):
        if charges == "circled" and molecule.charge_of(index) and (
            abs(molecule.charge_of(index)) == 1 or not labelled(molecule, index)
        ):
            _circled(molecule, index, pen, drawn, prefix, strokes)
        elif charges != "circled" and molecule.charge_of(index) and not labelled(molecule, index):
            _vertex_charge(molecule, index, pen, drawn, prefix)
    for index, atom in enumerate(molecule.atoms):
        if atom.element in METALS:
            continue  # a metal's d electrons are not drawn as lone pairs
        leaving = (used or {}).get(index, [])
        place = drawn.atoms[index]
        show = 0
        if pairs == "all" and (labelled(molecule, index) or atom.lone):
            show = max(0, atom.lone // 2 - len(leaving))
        radical = bool(atom.lone % 2) and index not in (lone or {})
        marks = _spread(place.taken, show + radical, [])
        for number, angle in enumerate(marks[:show]):
            _lone_pair(pen, drawn, index, angle, f"{prefix}.pair{index}.{number}")
        if radical:
            _radical(pen, drawn, index, marks[-1], f"{prefix}.radical{index}")
    return drawn


def _spread(taken: list[float], count: int, wanted: list[float]) -> list[float]:
    """Directions for ``count`` marks round an atom (lone pairs, then a radical): as far
    from its bonds and labels and from each other as they can be, then each settled on
    the nearest of above, below, left and right that leaves it nearly as clear. The
    first marks face ``wanted`` (where their arrows go), if they can."""

    if count <= 0:
        return []
    fixed = list(taken)
    marks: list[float] = []
    for number in range(count):
        prefer = wanted[number] if number < len(wanted) else None
        marks.append(_free_angle(fixed + marks, prefer))
    for _ in range(8):
        for number in range(len(wanted), count):
            others = fixed + marks[:number] + marks[number + 1 :]
            marks[number] = _free_angle(others, None)
    settled = []
    for number, angle in enumerate(marks):
        others = fixed + settled + marks[number + 1 :]
        if number < len(wanted):
            settled.append(angle)
            continue
        own = _clearance(angle, others)
        plain = min(
            (k * math.pi / 2 for k in range(4)),
            key=lambda option: abs(math.remainder(option - angle, 2 * math.pi)),
        )
        near = abs(math.remainder(plain - angle, 2 * math.pi)) <= math.radians(25)
        settled.append(
            plain
            if near and _clearance(plain, others) >= min(own * 0.75, math.radians(70))
            else angle
        )
    return settled


def _clearance(angle: float, taken: list[float]) -> float:
    return min(
        (abs(math.remainder(angle - other, 2 * math.pi)) for other in taken), default=math.pi
    )


def _free_angle(taken: list[float], prefer: float | None) -> float:
    """The direction farthest from everything in ``taken`` -- or, given ``prefer``, the
    one nearest it that keeps a reasonable clearance."""

    candidates = [math.radians(degrees) for degrees in range(0, 360, 3)]
    best = max(_clearance(angle, taken) for angle in candidates)
    if prefer is not None:
        good = [
            angle for angle in candidates if _clearance(angle, taken) >= min(best, math.radians(50))
        ]
        return min(good, key=lambda angle: abs(math.remainder(angle - prefer, 2 * math.pi)))
    return max(
        candidates,
        key=lambda angle: (
            round(_clearance(angle, taken), 4),
            -abs(math.remainder(angle + math.pi / 2, 2 * math.pi)),
        ),
    )


# -- labels --------------------------------------------------------------------------------


def _label(
    molecule: Molecule, index: int, pen: Pen, drawn: Drawn, prefix: str, charges: str
) -> None:
    atom = molecule.atoms[index]
    place = drawn.atoms[index]
    x, y = place.point
    symbol = (TextRun(atom.element),)
    if atom.isotope is not None:
        symbol = (TextRun(str(atom.isotope), baseline_shift="super"), TextRun(atom.element))
    symbol_metrics = pen.measure(symbol)
    element_width = pen.measure((TextRun(atom.element),)).width
    cap = symbol_metrics.cap_height or 0.7 * pen.u
    baseline = y + cap / 2.0
    hydrogens = ()
    if atom.hydrogens:
        hydrogens = (TextRun("H"),) + (
            (TextRun(str(atom.hydrogens), baseline_shift="sub"),) if atom.hydrogens > 1 else ()
        )
    charge = ()
    if molecule.charge_of(index) and (charges != "circled" or abs(molecule.charge_of(index)) > 1):
        # A charge of two or more is written after the label, as Mg²⁺ is, circled or not.
        charge = (TextRun(_charge_text(molecule.charge_of(index)), baseline_shift="super"),)
    side = _hydrogen_side(place.taken) if hydrogens else "right"
    if (
        hydrogens
        and not place.taken
        and atom.element in {"O", "S", "Se", "Te", "F", "Cl", "Br", "I"}
    ):
        side = "left"  # on its own, as it is written: H₂O, HO⁻, HCl
    # The symbol's own letter is centred on the atom; an isotope's number reaches left.
    symbol_left = x - element_width / 2.0 - (symbol_metrics.width - element_width)
    if side == "left":
        runs = hydrogens + symbol + charge
        start = symbol_left - pen.measure(hydrogens).width
    elif side in {"up", "down"}:
        runs = symbol + charge
        start = symbol_left
    else:
        runs = symbol + hydrogens + charge
        start = symbol_left
    metrics = pen.measure(runs)
    drawn.words.append(
        Words(f"{prefix}.atom{index}", runs, metrics, start, baseline, anchor="start")
    )
    place.radius = (element_width / 2.0 + pen.margin, cap / 2.0 + pen.margin)
    drawn.boxes.append(
        (start, baseline - cap, start + metrics.width, baseline + metrics.descent * 0.3)
    )
    place.ink.append(drawn.boxes[-1])
    if side in {"left", "right"} and hydrogens:
        place.label = (start, baseline - cap, start + metrics.width, baseline)
        place.label_side = side
    if side in {"up", "down"}:
        h_metrics = pen.measure(hydrogens)
        h_baseline = (
            baseline - cap - pen.margin * 1.2 if side == "up" else baseline + cap + pen.margin * 1.2
        )
        left = x - pen.measure((TextRun("H"),)).width / 2.0
        drawn.words.append(
            Words(f"{prefix}.atom{index}.h", hydrogens, h_metrics, left, h_baseline, anchor="start")
        )
        drawn.boxes.append((left, h_baseline - cap, left + h_metrics.width, h_baseline))
        place.ink.append(drawn.boxes[-1])
    direction = {"right": 0.0, "left": math.pi, "up": -math.pi / 2, "down": math.pi / 2}[side]
    if hydrogens or charge:
        place.taken.append(direction)


def _hydrogen_side(taken: list[float]) -> str:
    """Where an atom's hydrogens go: right, if no bond comes within a right angle of
    that; else left; else above or below, whichever its bonds leave clearer."""

    def clearance(direction: float) -> float:
        return min(
            (abs(math.remainder(direction - angle, 2 * math.pi)) for angle in taken),
            default=math.pi,
        )

    if clearance(0.0) >= math.pi / 2 - 1e-6:
        return "right"
    if clearance(math.pi) >= math.pi / 2 - 1e-6:
        return "left"
    return "up" if clearance(-math.pi / 2) >= clearance(math.pi / 2) else "down"


def _charge_text(charge: int) -> str:
    sign = "+" if charge > 0 else MINUS
    return sign if abs(charge) == 1 else f"{abs(charge)}{sign}"


# -- bonds ----------------------------------------------------------------------------------


def _ends(
    drawn: Drawn, first: int, second: int, offset: Point = (0.0, 0.0)
) -> tuple[Point, Point] | None:
    """A bond's line from ``first`` to ``second`` (moved by ``offset``), stopped at each
    end's label ellipse."""

    (x1, y1), (x2, y2) = drawn.atoms[first].point, drawn.atoms[second].point
    x1, y1, x2, y2 = x1 + offset[0], y1 + offset[1], x2 + offset[0], y2 + offset[1]
    t1 = _leaving(drawn.atoms[first], (x1, y1), (x2, y2))
    t2 = 1.0 - _leaving(drawn.atoms[second], (x2, y2), (x1, y1))
    if t2 - t1 < 0.05:
        return None
    return ((x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1), (x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2))


def _leaving(atom: Atomic, start: Point, end: Point) -> float:
    """How far along start-to-end the line leaves the atom's label ellipse (0 for a vertex)."""

    rx, ry = atom.radius
    if rx <= 0.0:
        return 0.0
    cx, cy = atom.point
    dx, dy = end[0] - start[0], end[1] - start[1]
    ox, oy = start[0] - cx, start[1] - cy
    a = (dx / rx) ** 2 + (dy / ry) ** 2
    b = 2 * (ox * dx / rx**2 + oy * dy / ry**2)
    c = (ox / rx) ** 2 + (oy / ry) ** 2 - 1.0
    disc = b * b - 4 * a * c
    if a <= 0 or disc < 0:
        return 0.0
    return max(0.0, (-b + math.sqrt(disc)) / (2 * a))


def _line(drawn: Drawn, bond, identifier: str, ends, pen: Pen) -> None:
    if ends is None:
        return
    (x1, y1), (x2, y2) = ends
    drawn.shapes.append(Shape(identifier, path("M", x1, y1, "L", x2, y2), "line", width=pen.line))
    drawn.lines.setdefault(frozenset((bond.a, bond.b)), []).append(ends)


def _bond(
    molecule: Molecule,
    bond,
    pen: Pen,
    drawn: Drawn,
    identifier: str,
    found: list[list[int]],
    style: str | None,
    start: int,
) -> None:
    if style in {"wedge", "hash"}:
        _wedge(drawn, pen, start, bond.other(start), style, identifier)
        return
    (x1, y1), (x2, y2) = drawn.atoms[bond.a].point, drawn.atoms[bond.b].point
    length = math.hypot(x2 - x1, y2 - y1) or 1e-6
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length
    if bond.order == 1:
        _line(drawn, bond, identifier, _ends(drawn, bond.a, bond.b), pen)
        return
    if bond.order >= 3:
        _line(drawn, bond, identifier, _ends(drawn, bond.a, bond.b), pen)
        for sign in (-1, 1):
            offset = (nx * pen.gap * sign, ny * pen.gap * sign)
            _line(
                drawn,
                bond,
                f"{identifier}.{'ab'[sign > 0]}",
                _ends(drawn, bond.a, bond.b, offset),
                pen,
            )
        return
    side = _double_side(molecule, bond, drawn, found)
    if side == 0:
        for sign in (-1, 1):
            offset = (nx * pen.gap * sign / 2, ny * pen.gap * sign / 2)
            _line(
                drawn,
                bond,
                f"{identifier}.{'ab'[sign > 0]}",
                _ends(drawn, bond.a, bond.b, offset),
                pen,
            )
        return
    _line(drawn, bond, identifier, _ends(drawn, bond.a, bond.b), pen)
    offset = (nx * pen.gap * side, ny * pen.gap * side)
    inner = _ends(drawn, bond.a, bond.b, offset)
    if inner is None:
        return
    (ax, ay), (bx, by) = inner
    # The inner line is shortened where it meets a vertex, to keep clear of its neighbours.
    trim = pen.gap * 0.85 / length
    cut_a = trim if not drawn.atoms[bond.a].radius[0] else 0.0
    cut_b = trim if not drawn.atoms[bond.b].radius[0] else 0.0
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy) / length
    a = (ax + dx * cut_a / span, ay + dy * cut_a / span)
    b = (bx - dx * cut_b / span, by - dy * cut_b / span)
    _line(drawn, bond, f"{identifier}.inner", (a, b), pen)


def _double_side(molecule: Molecule, bond, drawn: Drawn, found: list[list[int]]) -> int:
    """Which side of its bond a double bond's second line goes: 1 or -1 (the normal's way
    or not), or 0 for centred on it."""

    (x1, y1), (x2, y2) = drawn.atoms[bond.a].point, drawn.atoms[bond.b].point
    nx, ny = -(y2 - y1), x2 - x1
    for ring in sorted(found, key=len):
        if bond.a in ring and bond.b in ring:
            cx = sum(drawn.atoms[atom].point[0] for atom in ring) / len(ring)
            cy = sum(drawn.atoms[atom].point[1] for atom in ring) / len(ring)
            return 1 if (cx - x1) * nx + (cy - y1) * ny > 0 else -1
    others = [
        other
        for end in (bond.a, bond.b)
        for other in molecule.neighbours(end)
        if other not in (bond.a, bond.b)
    ]
    a_alone = len(molecule.neighbours(bond.a)) == 1
    b_alone = len(molecule.neighbours(bond.b)) == 1
    if (
        (a_alone and labelled(molecule, bond.a))
        or (b_alone and labelled(molecule, bond.b))
        or not others
    ):
        return 0
    if labelled(molecule, bond.a) and labelled(molecule, bond.b):
        return 0
    score = sum(
        (drawn.atoms[other].point[0] - x1) * nx + (drawn.atoms[other].point[1] - y1) * ny
        for other in others
    )
    if abs(score) < 1e-6:
        return 0
    return 1 if score > 0 else -1


def _wedge(drawn: Drawn, pen: Pen, start: int, end: int, style: str, identifier: str) -> None:
    ends = _ends(drawn, start, end)
    if ends is None:
        return
    drawn.lines.setdefault(frozenset((start, end)), []).append(ends)
    (x1, y1), (x2, y2) = ends
    length = math.hypot(x2 - x1, y2 - y1) or 1e-6
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length
    half = pen.wedge / 2.0
    narrow = pen.line / 2.0
    if style == "wedge":
        d = path(
            "M",
            x1 + nx * narrow,
            y1 + ny * narrow,
            "L",
            x2 + nx * half,
            y2 + ny * half,
            "L",
            x2 - nx * half,
            y2 - ny * half,
            "L",
            x1 - nx * narrow,
            y1 - ny * narrow,
            "Z",
        )
        drawn.shapes.append(Shape(identifier, d, "solid", width=pen.line * 0.4))
        return
    count = max(4, round(length / (0.12 * pen.bond)))
    pieces = []
    for step in range(count + 1):
        t = step / count
        width = narrow + (half - narrow) * t
        cx, cy = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        pieces += ["M", cx + nx * width, cy + ny * width, "L", cx - nx * width, cy - ny * width]
    drawn.shapes.append(Shape(identifier, path(*pieces), "line", width=pen.line * 0.85))


# -- marks round an atom ---------------------------------------------------------------------


def _reach(place: Atomic, angle: float, pen: Pen) -> float:
    """How far from an atom's centre, in ``angle``, its label (or vertex) ends."""

    rx, ry = place.radius
    if rx <= 0.0:
        return pen.u * 0.18
    cos, sin = math.cos(angle), math.sin(angle)
    return 1.0 / math.sqrt((cos / rx) ** 2 + (sin / ry) ** 2) - pen.margin * 0.4


def _lone_pair(pen: Pen, drawn: Drawn, index: int, angle: float, identifier: str) -> None:
    place = drawn.atoms[index]
    place.taken.append(angle)
    (cx, cy), dots = _pair_dots(place, angle, pen)
    pieces = [_circle(x, y, pen.dot) for x, y in dots]
    drawn.shapes.append(Shape(identifier, " ".join(pieces), "solid", width=pen.dot * 0.2))
    reach = pen.dot * 1.9 + pen.dot
    drawn.boxes.append((cx - reach, cy - reach, cx + reach, cy + reach))
    place.pairs.append((angle, (cx, cy)))


def _pair_dots(place: Atomic, angle: float, pen: Pen) -> tuple[Point, tuple[Point, Point]]:
    """Where a lone pair in ``angle`` sits by its atom: its middle, and its two dots."""

    distance = _reach(place, angle, pen) + pen.dot * 2.2
    cx = place.point[0] + math.cos(angle) * distance
    cy = place.point[1] + math.sin(angle) * distance
    across = (-math.sin(angle) * pen.dot * 1.9, math.cos(angle) * pen.dot * 1.9)
    return (cx, cy), ((cx - across[0], cy - across[1]), (cx + across[0], cy + across[1]))


def pair_spots(
    molecule: Molecule, drawn: Drawn, pen: Pen, index: int, count: int
) -> list[tuple[Point, Point]]:
    """Where ``count`` more of an atom's lone pairs go, as the two dots of each: where a
    drawing showing every pair puts them -- clear of its bonds, the hydrogens written
    beside it, its charge, and the pairs already drawn there (an arrow's among them)."""

    if count <= 0 or molecule.atoms[index].element in METALS:
        return []
    place = drawn.atoms[index]
    taken = list(place.taken) + [angle for angle, _ in place.pairs]
    return [_pair_dots(place, angle, pen)[1] for angle in _spread(taken, count, [])]


def _radical(pen: Pen, drawn: Drawn, index: int, angle: float, identifier: str) -> None:
    place = drawn.atoms[index]
    place.taken.append(angle)
    distance = _reach(place, angle, pen) + pen.dot * 2.4
    x = place.point[0] + math.cos(angle) * distance
    y = place.point[1] + math.sin(angle) * distance
    drawn.shapes.append(
        Shape(identifier, _circle(x, y, pen.dot * 1.15), "solid", width=pen.dot * 0.2)
    )
    place.radical = (angle, (x, y))
    drawn.boxes.append((x - pen.dot * 2, y - pen.dot * 2, x + pen.dot * 2, y + pen.dot * 2))


def _circled(
    molecule: Molecule, index: int, pen: Pen, drawn: Drawn, prefix: str, avoid=(),
) -> None:
    """A charge in a circle beside its atom: at the upper right if that is clear, else
    wherever round the atom it touches no bond, no other label and no arrow."""

    place = drawn.atoms[index]
    radius = pen.u * 0.3
    u = pen.u
    lines = [line for key, items in drawn.lines.items() for line in items] + list(avoid)

    def clash(x: float, y: float) -> float:
        hits = 0.0
        for line in lines:
            if _to_segment((x, y), line) < radius + pen.line + u * 0.04:
                hits += 1
        for x0, y0, x1, y1 in drawn.boxes:
            if x0 - radius < x < x1 + radius and y0 - radius < y < y1 + radius:
                hits += 1
        return hits

    best = None
    for degrees in range(0, 360, 15):
        angle = math.radians(degrees)
        distance = _edge(place, angle, pen) + radius + u * 0.07
        x = place.point[0] + math.cos(angle) * distance
        y = place.point[1] + math.sin(angle) * distance
        clear = min(
            (abs(math.remainder(angle - other, 2 * math.pi)) for other in place.taken),
            default=math.pi,
        )
        upper_right = abs(math.remainder(angle + math.pi / 4, 2 * math.pi))
        score = (clash(x, y), -min(clear, math.radians(60)), upper_right)
        if best is None or score < best[0]:
            best = (score, x, y, angle)
    _, x, y, angle = best  # type: ignore[misc]
    place.taken.append(angle)
    arm = radius * 0.55
    sign = ["M", x - arm, y, "L", x + arm, y]
    if molecule.charge_of(index) > 0:
        sign += ["M", x, y - arm, "L", x, y + arm]
    d = _circle(x, y, radius) + " " + path(*sign)
    drawn.shapes.append(Shape(f"{prefix}.charge{index}", d, "line", width=pen.line * 0.85))
    drawn.boxes.append((x - radius, y - radius, x + radius, y + radius))
    drawn.marks.append((index, x, y, radius))


def _edge(place: Atomic, angle: float, pen: Pen) -> float:
    """How far from an atom's centre, in ``angle``, its label (all of it: ``H₂N``) ends."""

    if place.label is None:
        return _reach(place, angle, pen)
    left, top, right, bottom = place.label
    cx, cy = place.point
    cos, sin = math.cos(angle), math.sin(angle)
    reach = []
    if abs(cos) > 1e-9:
        reach.append(((right if cos > 0 else left) - cx) / cos)
    if abs(sin) > 1e-9:
        reach.append(((bottom if sin > 0 else top) - cy) / sin)
    return max(0.0, min(value for value in reach if value >= 0)) if reach else 0.0


def _to_segment(point: Point, segment) -> float:
    (x1, y1), (x2, y2) = segment
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    along = ((point[0] - x1) * dx + (point[1] - y1) * dy) / length if length else 0.0
    t = max(0.0, min(1.0, along))
    return math.dist(point, (x1 + t * dx, y1 + t * dy))


def _vertex_charge(molecule: Molecule, index: int, pen: Pen, drawn: Drawn, prefix: str) -> None:
    place = drawn.atoms[index]
    angle = _free_angle(place.taken, -math.pi / 4)
    place.taken.append(angle)
    runs = (TextRun(_charge_text(molecule.charge_of(index))),)
    metrics = pen.measure(runs)
    distance = pen.u * 0.55
    x = place.point[0] + math.cos(angle) * distance
    y = place.point[1] + math.sin(angle) * distance
    cap = metrics.cap_height or pen.u * 0.7
    drawn.words.append(
        Words(f"{prefix}.charge{index}", runs, metrics, x, y + cap / 2, anchor="middle")
    )
    drawn.boxes.append((x - metrics.width / 2, y - cap / 2, x + metrics.width / 2, y + cap / 2))


def _circle(x: float, y: float, r: float) -> str:
    return path("M", x - r, y, "A", r, r, 0, 1, 1, x + r, y, "A", r, r, 0, 1, 1, x - r, y, "Z")
