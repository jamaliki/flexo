"""Curly arrows as what they mean: electrons moved, and the structure that follows.

An arrow is written ``from -> to``, a fishhook (one electron) ``from ~> to``. Atoms
are their map numbers (``[O-:5]`` is 5), or their places in the SMILES when it has
no maps. ``from`` is an atom -- a lone pair on it, or its radical -- or a bond,
``2=3``; ``to`` is an atom (the electrons become a lone pair on it, or a bond to it
from the atom they leave) or a pair of atoms, ``2-6`` (a bond made, or made
stronger, between them). The bond sign between two numbers (``-``, ``=``, ``#``) is
for the reader; the molecule says what the bond is.

An arrow from a lone pair on 5 to atom 2 makes a bond 5-2; from bond 2=3 to atom 3,
it leaves a lone pair on 3; from bond 1=2 to 2-6, it moves the bond to 2-6. Two
fishhooks from one bond, one to each atom, break it into two radicals.

The arrows of a step move their electrons together, and the step is then checked:
every bond keeps an even number of electrons, no second-row atom holds more than
eight, no hydrogen more than two. A step drawn by hand is compared, atom by atom,
with what the arrows before it make.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from flexo.chemistry.molecule import VALENCE_ELECTRONS, Bond, Molecule

_ARROW = re.compile(
    r"^\s*(\d+)\s*(?:([-=#~:.])?\s*(\d+))?\s*(->|~>|→|⇀)\s*(\d+)\s*(?:([-=#~:.])?\s*(\d+))?\s*$"
)
_OCTET = frozenset({"B", "C", "N", "O", "F"})


class MechanismError(ValueError):
    """An arrow or a step that cannot be, said in words, with how to put it right."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True, slots=True)
class Arrow:
    """One curly arrow, its atoms as indexes into its step's molecule."""

    source: tuple[int, ...]
    """One atom (a lone pair or a radical on it) or two (the bond between them)."""
    target: tuple[int, ...]
    """One atom, or two (the bond made or strengthened between them)."""
    electrons: int
    """2 for a pair, 1 for a fishhook."""
    written: str


def read_arrow(text: str, molecule: Molecule) -> Arrow:
    """The arrow ``text`` writes, its atoms found in ``molecule``."""

    match = _ARROW.match(str(text))
    if match is None:
        raise MechanismError(
            f'"{text}" is not an arrow flexo reads.',
            'Write "from -> to": a lone pair "5 -> 2", a bond "2=3 -> 3", a bond moved '
            '"1=2 -> 2-6"; "~>" for a fishhook.',
        )
    first, _, second, kind, third, _, fourth = match.groups()

    def atom(number: str) -> int:
        index = molecule.index_of(int(number))
        if index is None:
            maps = sorted(a.map for a in molecule.atoms if a.map is not None)
            known = (
                f"its atoms are mapped {', '.join(str(m) for m in maps)}"
                if maps
                else f"its atoms are 1 to {len(molecule.atoms)}, in the SMILES' order"
            )
            raise MechanismError(f'Arrow "{text}": there is no atom {number}; {known}.')
        return index

    source = (atom(first),) if second is None else (atom(first), atom(second))
    target = (atom(third),) if fourth is None else (atom(third), atom(fourth))
    electrons = 1 if kind in {"~>", "⇀"} else 2
    if len(source) == 2 and molecule.bond(*source) is None:
        raise MechanismError(
            f'Arrow "{text}": atoms {first} and {second} are not bonded, '
            "so no bond's electrons can move.",
            "An arrow starts at a lone pair (one number) or at a bond (two bonded atoms).",
        )
    if len(source) == 2 and len(target) == 1 and target[0] not in source:
        raise MechanismError(
            f'Arrow "{text}": the bond {first}-{second} cannot give its electrons to atom {third} '
            "without saying which of its atoms bonds to it.",
            f'Write "{first}-{second} -> {second}-{third}" (or "-> {first}-{third}").',
        )
    if len(source) == 1 and len(target) == 2 and source[0] not in target:
        raise MechanismError(
            f'Arrow "{text}": a lone pair on {first} can only make a bond to {first}.',
            f'Write "{first} -> {third}" for a bond from {first} to {third}.',
        )
    if source == target or (len(source) == 1 and len(target) == 1 and source[0] == target[0]):
        raise MechanismError(f'Arrow "{text}" moves electrons to where they are already.')
    if len(source) == 2 and len(target) == 2 and set(source) == set(target):
        raise MechanismError(f'Arrow "{text}" moves a bond\'s electrons into the same bond.')
    return Arrow(source, target, electrons, str(text).strip())


def target_bond(arrow: Arrow) -> tuple[int, int] | None:
    """The two atoms an arrow bonds (or bonds again), or None when it ends in a lone pair."""

    if len(arrow.target) == 2:
        return arrow.target[0], arrow.target[1]
    if len(arrow.source) == 1:
        return arrow.source[0], arrow.target[0]
    return None


def push(molecule: Molecule, arrows: list[Arrow], *, step: str = "") -> Molecule:
    """The molecule after ``arrows`` move their electrons, all together; a step that
    cannot be raises a ``MechanismError`` saying why."""

    after = molecule.copy()
    lone = [atom.lone for atom in molecule.atoms]
    shared: dict[frozenset[int], int] = {
        frozenset((bond.a, bond.b)): 2 * bond.order for bond in molecule.bonds
    }
    taken_lone = [0] * len(lone)
    taken_shared: dict[frozenset[int], int] = {}
    where = f"{step}: " if step else ""
    for arrow in arrows:
        moved = arrow.electrons
        if len(arrow.source) == 1:
            (atom,) = arrow.source
            taken_lone[atom] += moved
            if taken_lone[atom] > molecule.atoms[atom].lone:
                what = "lone pair" if moved == 2 else "electron of its own"
                more = "no" if taken_lone[atom] == moved else "no more"
                raise MechanismError(
                    f'{where}arrow "{arrow.written}" starts at {molecule.name(atom)}, which has '
                    f"{more} {what} to give.",
                    "Start it at a bond of that atom instead, or give the atom its charge.",
                )
            lone[atom] -= moved
        else:
            key = frozenset(arrow.source)
            taken_shared[key] = taken_shared.get(key, 0) + moved
            if taken_shared[key] > 2 * molecule.bond(*arrow.source).order:  # type: ignore[union-attr]
                raise MechanismError(
                    f"{where}arrows take more electrons from the bond "
                    f"{_pair(molecule, arrow.source)} than it has."
                )
            shared[key] -= moved
        if len(arrow.target) == 1 and len(arrow.source) == 2:
            lone[arrow.target[0]] += moved
        else:
            bonded = target_bond(arrow)
            key = frozenset(bonded)  # type: ignore[arg-type]
            shared[key] = shared.get(key, 0) + moved
    for key, count in shared.items():
        if count % 2:
            a, b = sorted(key)
            raise MechanismError(
                f"{where}the bond between {molecule.name(a)} and {molecule.name(b)} is left with "
                f"{count} electron{'s' if count != 1 else ''}.",
                "A fishhook moves one electron; a bond is made of two, so fishhooks come in pairs.",
            )
    bonds: list[Bond] = []
    for key, count in shared.items():
        if count <= 0:
            continue
        a, b = sorted(key)
        old = molecule.bond(a, b)
        if old is not None:
            bond = Bond(
                old.a, old.b, count // 2, False, old.stereo if count // 2 == old.order else ""
            )
        else:
            bond = Bond(a, b, count // 2)
        bonds.append(bond)
    after.bonds = bonds
    for index, atom in enumerate(after.atoms):
        atom.lone = lone[index]
    changed = {atom for arrow in arrows for atom in (*arrow.source, *arrow.target)}
    for index in changed:
        after.atoms[index].chirality = ""
        after.atoms[index].charge = after.charge_of(index)
    _check(after, changed, where)
    return after


def _check(molecule: Molecule, changed: set[int], where: str) -> None:
    for index in sorted(changed):
        atom = molecule.atoms[index]
        bonded = molecule.bonded(index)
        around = atom.lone + 2 * bonded
        name = molecule.name(index)
        if atom.element == "H" and bonded > 1:
            raise MechanismError(
                f"{where}{name} would make {bonded} bonds; a hydrogen makes one.",
                "When a hydrogen is taken by a new bond, its old bond breaks: "
                "add an arrow from it to the atom it leaves.",
            )
        if atom.element in _OCTET and around > 8:
            raise MechanismError(
                f"{where}{name} would have {around} electrons round it; "
                f"{atom.element} keeps no more than eight.",
                "As a bond to it forms, another must break: add an arrow from one of its bonds "
                "(to the atom that takes the electrons).",
            )
        if atom.element not in VALENCE_ELECTRONS:
            raise MechanismError(f"{where}{name} is not an element flexo knows.")


def _pair(molecule: Molecule, atoms: tuple[int, ...]) -> str:
    return "-".join(molecule.name(atom) for atom in atoms)


def compare(made: Molecule, drawn: Molecule, *, step: str, before: str) -> list[str]:
    """How a structure drawn by hand (``drawn``) differs from the one the arrows before it
    make (``made``), atom by atom through their maps -- in words; empty when they agree."""

    def mapped(molecule: Molecule) -> dict[int, int]:
        return {
            atom.map: index for index, atom in enumerate(molecule.atoms) if atom.map is not None
        }

    ours, theirs = mapped(made), mapped(drawn)
    if not theirs:
        return [f"{step} has no atom maps, so it cannot be checked against {before}'s arrows."]
    said: list[str] = []
    for number in sorted(set(ours) | set(theirs)):
        if number not in theirs:
            said.append(f"{step} does not draw atom {number}, which {before}'s arrows keep.")
            continue
        if number not in ours:
            said.append(f"{step} draws an atom {number} that {before} does not have.")
            continue
        a, b = ours[number], theirs[number]
        one, two = made.atoms[a], drawn.atoms[b]
        name = made.name(a)
        if one.element != two.element:
            said.append(
                f"{step} draws atom {number} as {two.element}; {before} has it as {one.element}."
            )
            continue
        q1, q2 = made.charge_of(a), drawn.charge_of(b)
        if q1 != q2:
            said.append(
                f"{before}'s arrows leave {name} {_charge_words(q1)}, "
                f"but {step} draws it {_charge_words(q2)}."
            )
        h1 = one.hydrogens + _bonded_hydrogens(made, a)
        h2 = two.hydrogens + _bonded_hydrogens(drawn, b)
        if h1 != h2:
            said.append(
                f"{before}'s arrows leave {name} with {h1} hydrogen{'s' * (h1 != 1)}; "
                f"{step} draws {h2}."
            )
        if one.lone % 2 != two.lone % 2:
            left = "a radical" if one.lone % 2 else "with no radical"
            drawn_as = "as one" if two.lone % 2 else "without one"
            said.append(f"{before}'s arrows leave {name} {left}; {step} draws it {drawn_as}.")
    for number in sorted(ours):
        for other in sorted(ours):
            if other <= number or number not in theirs or other not in theirs:
                continue
            if "H" in {made.atoms[ours[number]].element, made.atoms[ours[other]].element}:
                continue  # a hydrogen's bond is counted with its atom's hydrogens
            first = made.bond(ours[number], ours[other])
            second = drawn.bond(theirs[number], theirs[other])
            o1 = first.order if first else 0
            o2 = second.order if second else 0
            if o1 != o2:
                pair = f"{made.name(ours[number])} and {made.name(ours[other])}"
                said.append(
                    f"{before}'s arrows leave {_order_words(o1)} between {pair}; "
                    f"{step} draws {_order_words(o2)}."
                )
    return said


def _bonded_hydrogens(molecule: Molecule, index: int) -> int:
    """Hydrogens drawn as atoms of their own on an atom: written so an arrow can move one,
    they are its hydrogens all the same."""

    return sum(1 for other in molecule.neighbours(index) if molecule.atoms[other].element == "H")


def _charge_words(charge: int) -> str:
    if charge == 0:
        return "neutral"
    if abs(charge) == 1:
        return "positively charged" if charge > 0 else "negatively charged"
    return f"with a charge of {charge:+d}"


def _order_words(order: int) -> str:
    return {0: "no bond", 1: "a single bond", 2: "a double bond", 3: "a triple bond"}.get(
        order, f"a bond of {order}"
    )
