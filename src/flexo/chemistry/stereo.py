"""Wedges and hashes: a stereocentre's handedness, drawn on its flat structure.

SMILES says a centre's handedness by the order of its neighbours (``@``: seen from
the first, the rest go anticlockwise). A flat drawing says it with one bond drawn as
a wedge (toward the reader) or a hash (away). One bond of each centre is chosen -- to
an atom that is not itself a centre, out of a ring, at the end of a chain if it can
be -- the drawing is lifted into three dimensions with that bond raised, and the
handedness read off it: if it is the one the SMILES gives, the bond is a wedge, if
not, a hash.
"""

from __future__ import annotations

import math

from flexo.chemistry.layout import rings
from flexo.chemistry.molecule import Molecule


def wedges(molecule: Molecule) -> dict[tuple[int, int], str]:
    """For each stereocentre, its drawn bond: (centre, neighbour) to ``wedge`` or ``hash``."""

    found = rings(molecule, list(range(len(molecule.atoms))))
    in_ring = {
        frozenset(pair) for ring in found for pair in zip(ring, [*ring[1:], ring[0]], strict=True)
    }
    centres = {index for index, atom in enumerate(molecule.atoms) if atom.chirality}
    drawn: dict[tuple[int, int], str] = {}
    used: set[int] = set()
    for centre in sorted(centres):
        atom = molecule.atoms[centre]
        neighbours = molecule.neighbours(centre)
        order = [item for item in atom.order if item == -1 or item in neighbours]
        if len(neighbours) < 3 or (len(order) < 4 and -1 not in order and len(order) != 3):
            continue

        def preference(other: int, centre: int = centre) -> tuple:
            return (
                other in used,
                other in centres,
                frozenset((centre, other)) in in_ring,
                len(molecule.neighbours(other)) > 1,
                molecule.atoms[other].element == "H",
                other,
            )

        chosen = min(neighbours, key=preference)
        used.add(chosen)
        handed = _handedness(molecule, centre, order, chosen)
        if handed is None:
            continue
        drawn[(centre, chosen)] = "wedge" if handed == atom.chirality else "hash"
    return drawn


def _handedness(molecule: Molecule, centre: int, order: list[int], raised: int) -> str | None:
    """``@`` or ``@@``: how ``order`` turns round ``centre`` with ``raised`` toward the reader."""

    atoms = molecule.atoms
    cx, cy = atoms[centre].x, -atoms[centre].y  # y up: a right-handed frame, z toward the reader
    points: dict[int, tuple[float, float, float]] = {}
    drawn = [item for item in order if item != -1]
    for item in drawn:
        dx, dy = atoms[item].x - cx, -atoms[item].y - cy
        length = math.hypot(dx, dy) or 1.0
        points[item] = (dx / length, dy / length, 1.0 if item == raised else 0.0)
    if -1 in order:
        # The hydrogen not drawn points away from the drawn bonds, and away from the raised one.
        sx = -sum(points[item][0] for item in drawn)
        sy = -sum(points[item][1] for item in drawn)
        length = math.hypot(sx, sy) or 1.0
        points[-1] = (sx / length * 0.5, sy / length * 0.5, -1.0)
    elif len(drawn) == 3:
        # Three drawn bonds and a lone pair (a chiral nitrogen, sulfur): the pair as the fourth.
        sx = -sum(points[item][0] for item in drawn)
        sy = -sum(points[item][1] for item in drawn)
        length = math.hypot(sx, sy) or 1.0
        points[-2] = (sx / length * 0.5, sy / length * 0.5, -1.0)
        order = [*order, -2]
    if len(order) != 4:
        return None
    a, b, c, d = (points[item] for item in order)
    volume = _dot(_minus(b, a), _cross(_minus(c, a), _minus(d, a)))
    if abs(volume) < 1e-9:
        return None
    # Seen from a, b-c-d anticlockwise is a negative volume in this frame.
    return "@" if volume < 0 else "@@"


def _minus(p, q):
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2])


def _cross(p, q):
    return (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])


def _dot(p, q) -> float:
    return p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
