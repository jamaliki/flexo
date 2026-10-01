"""Molecules from SMILES: atoms, bonds, hydrogens, charges, and the electrons each atom keeps.

The reader takes SMILES as chemists and databases write it -- the organic subset
(``CC(=O)O``), bracket atoms with charges, hydrogens, isotopes and atom maps
(``[NH3+:1]``, ``[13CH4]``), aromatic rings in lower case (``c1ccccc1``), ring
closures, branches, stereo (``@``, ``@@``, ``/``, ``\\``) and separate molecules
(``.``) -- and gives the Kekulé structure a mechanism needs: arrows move the
electrons of one double bond, not of a ring's delocalised six.

Each atom keeps the electrons it does not share (``lone``): an oxygen of water
four, a carbanion two, a radical one. They are what lone pairs and radicals are
drawn from, and what an arrow from an atom takes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VALENCE_ELECTRONS = {
    "H": 1,
    "He": 2,
    "Li": 1,
    "Be": 2,
    "B": 3,
    "C": 4,
    "N": 5,
    "O": 6,
    "F": 7,
    "Ne": 8,
    "Na": 1,
    "Mg": 2,
    "Al": 3,
    "Si": 4,
    "P": 5,
    "S": 6,
    "Cl": 7,
    "Ar": 8,
    "K": 1,
    "Ca": 2,
    "Ti": 4,
    "Cr": 6,
    "Mn": 7,
    "Fe": 8,
    "Co": 9,
    "Ni": 10,
    "Cu": 11,
    "Zn": 12,
    "Ga": 3,
    "Ge": 4,
    "As": 5,
    "Se": 6,
    "Br": 7,
    "Kr": 8,
    "Rb": 1,
    "Sr": 2,
    "Pd": 10,
    "Ag": 11,
    "Cd": 12,
    "In": 3,
    "Sn": 4,
    "Sb": 5,
    "Te": 6,
    "I": 7,
    "Xe": 8,
    "Cs": 1,
    "Ba": 2,
    "Pt": 10,
    "Au": 11,
    "Hg": 12,
    "Tl": 3,
    "Pb": 4,
    "Bi": 5,
    "Os": 8,
    "Ru": 8,
    "Rh": 9,
    "Ir": 9,
    "W": 6,
    "Mo": 6,
    "V": 5,
    "Sc": 3,
    "Zr": 4,
}
"""The electrons in each element's outer shell (its group): what it has to share or keep."""

_NORMAL_VALENCES = {
    "B": (3,),
    "C": (4,),
    "N": (3, 5),
    "O": (2,),
    "P": (3, 5),
    "S": (2, 4, 6),
    "F": (1,),
    "Cl": (1,),
    "Br": (1,),
    "I": (1,),
}
"""The bonds an atom written without brackets makes, hydrogens included (SMILES' rule)."""

_ORGANIC = ("Cl", "Br", "B", "C", "N", "O", "P", "S", "F", "I")
_AROMATIC = ("se", "as", "b", "c", "n", "o", "p", "s")
_ELEMENT = re.compile(r"[A-Z][a-z]?")
_BONDS = {"-": 1, "=": 2, "#": 3, "$": 4, ":": 1, "/": 1, "\\": 1}


class SmilesError(ValueError):
    """SMILES that cannot be read, said in words, with where in the SMILES it went wrong."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(slots=True)
class Atom:
    element: str
    charge: int = 0
    hydrogens: int = 0
    """Hydrogens the atom carries that are not atoms of their own (written in its label)."""
    isotope: int | None = None
    map: int | None = None
    """Its atom-map number (``[C:3]``): what arrows and later steps call it."""
    aromatic: bool = False
    chirality: str = ""
    """``@`` or ``@@`` as written: its neighbours anticlockwise or clockwise, seen from
    the first."""
    bracket: bool = False
    order: list[int] = field(default_factory=list)
    """Its neighbours in the order the SMILES writes them, -1 for its own hydrogen (for
    chirality)."""
    lone: int = 0
    """The electrons it does not share: two for each lone pair, one for a radical."""
    x: float = 0.0
    y: float = 0.0


@dataclass(slots=True)
class Bond:
    a: int
    b: int
    order: int = 1
    aromatic: bool = False
    stereo: str = ""
    """``/`` or ``\\`` as written from ``a`` to ``b``: which side of a double bond it lies."""

    def other(self, atom: int) -> int:
        return self.b if atom == self.a else self.a


@dataclass(slots=True)
class Molecule:
    atoms: list[Atom] = field(default_factory=list)
    bonds: list[Bond] = field(default_factory=list)

    def bond(self, a: int, b: int) -> Bond | None:
        for bond in self.bonds:
            if {bond.a, bond.b} == {a, b}:
                return bond
        return None

    def neighbours(self, atom: int) -> list[int]:
        return [bond.other(atom) for bond in self.bonds if atom in (bond.a, bond.b)]

    def bonds_of(self, atom: int) -> list[Bond]:
        return [bond for bond in self.bonds if atom in (bond.a, bond.b)]

    def bonded(self, atom: int) -> int:
        """The bonds an atom makes, counted by order, its hydrogens included."""

        return sum(bond.order for bond in self.bonds_of(atom)) + self.atoms[atom].hydrogens

    def charge_of(self, atom: int) -> int:
        """Its formal charge, from its electrons: those of its group, less those it keeps,
        less one for each bond."""

        item = self.atoms[atom]
        return VALENCE_ELECTRONS.get(item.element, 4) - item.lone - self.bonded(atom)

    def fragments(self) -> list[list[int]]:
        """The separate molecules, each its atoms in order."""

        seen: set[int] = set()
        found = []
        for start in range(len(self.atoms)):
            if start in seen:
                continue
            group, stack = [], [start]
            seen.add(start)
            while stack:
                atom = stack.pop()
                group.append(atom)
                for other in self.neighbours(atom):
                    if other not in seen:
                        seen.add(other)
                        stack.append(other)
            found.append(sorted(group))
        return found

    def copy(self) -> Molecule:
        atoms = [
            Atom(
                a.element,
                a.charge,
                a.hydrogens,
                a.isotope,
                a.map,
                a.aromatic,
                a.chirality,
                a.bracket,
                list(a.order),
                a.lone,
                a.x,
                a.y,
            )
            for a in self.atoms
        ]
        bonds = [Bond(b.a, b.b, b.order, b.aromatic, b.stereo) for b in self.bonds]
        return Molecule(atoms, bonds)

    def index_of(self, number: int) -> int | None:
        """The atom an arrow or a step calls ``number``: its map number, or -- in a
        molecule with no maps -- its place in the SMILES, from 1."""

        if any(atom.map is not None for atom in self.atoms):
            for index, atom in enumerate(self.atoms):
                if atom.map == number:
                    return index
            return None
        return number - 1 if 1 <= number <= len(self.atoms) else None

    def name(self, atom: int) -> str:
        """How words name an atom: its element and number, ``C2``, ``O5``."""

        item = self.atoms[atom]
        if item.map is not None:
            return f"{item.element}{item.map}"
        if any(other.map is not None for other in self.atoms):
            return f"an unnumbered {item.element}"
        return f"{item.element}{atom + 1}"


def read_smiles(smiles: str) -> Molecule:
    """The molecule ``smiles`` writes, kekulized, every atom's hydrogens and electrons known."""

    molecule = _Reader(smiles).read()
    _kekulize(molecule, smiles)
    for index, atom in enumerate(molecule.atoms):
        bonded = sum(bond.order for bond in molecule.bonds_of(index))
        if not atom.bracket:
            valences = _NORMAL_VALENCES.get(atom.element, (bonded,))
            target = next((value for value in valences if value >= bonded), bonded)
            atom.hydrogens = target - bonded
        if atom.element not in VALENCE_ELECTRONS:
            raise SmilesError(f'"{atom.element}" is not an element flexo knows.')
        atom.lone = VALENCE_ELECTRONS[atom.element] - atom.charge - bonded - atom.hydrogens
        if atom.lone < 0:
            raise SmilesError(
                f"{molecule.name(index)} makes {bonded + atom.hydrogens} bonds, more than "
                f"{atom.element} can with a charge of {atom.charge:+d}.",
                "Check its bonds and hydrogens, or give it the charge it has.",
            )
    return molecule


def mapped_smiles(smiles: str, atom: int, number: int) -> str:
    """``smiles`` with its atom ``atom`` (from 0, in the order it is written) given the
    map ``number`` -- written in brackets with the hydrogens it has, as ``C`` becomes
    ``[CH3:7]`` -- and everything else as it was."""

    molecule = read_smiles(smiles)
    reader = _Spans(smiles)
    reader.read()
    lead = len(smiles) - len(smiles.lstrip())
    start, end = reader.spans[atom]
    token = smiles[lead + start : lead + end]
    if token.startswith("["):
        inside = re.sub(r":\d+$", "", token[1:-1])
        written = f"[{inside}:{number}]"
    else:
        count = molecule.atoms[atom].hydrogens
        hydrogens = "" if not count else "H" if count == 1 else f"H{count}"
        written = f"[{token}{hydrogens}:{number}]"
    return smiles[: lead + start] + written + smiles[lead + end :]


class _Reader:
    def __init__(self, smiles: str) -> None:
        self.text = smiles.strip()
        self.at = 0
        self.molecule = Molecule()

    def fail(self, message: str) -> SmilesError:
        shown = self.text[: self.at] + " ‸ " + self.text[self.at :]
        return SmilesError(f"{message} (at {self.at + 1}: {shown}).")

    def read(self) -> Molecule:
        if not self.text:
            raise SmilesError("The SMILES is empty.", 'Write a molecule, such as "CC(=O)O".')
        previous: int | None = None
        branches: list[int | None] = []
        rings: dict[int, tuple[int, str]] = {}
        bond = ""
        text = self.text
        while self.at < len(text):
            char = text[self.at]
            if char.isspace():
                self.at += 1
                continue
            if char == "(":
                if previous is None:
                    raise self.fail("A branch opens before any atom")
                branches.append(previous)
                self.at += 1
            elif char == ")":
                if not branches:
                    raise self.fail("A branch closes that was never opened")
                previous = branches.pop()
                self.at += 1
            elif char in _BONDS:
                bond = char
                self.at += 1
            elif char == ".":
                previous, bond = None, ""
                self.at += 1
            elif char.isdigit() or char == "%":
                if previous is None:
                    raise self.fail("A ring closes before any atom")
                if char == "%":
                    number_text = text[self.at + 1 : self.at + 3]
                    if not number_text.isdigit() or len(number_text) != 2:
                        raise self.fail("A ring number after % needs two digits")
                    number, self.at = int(number_text), self.at + 3
                else:
                    number, self.at = int(char), self.at + 1
                if number in rings:
                    other, first = rings.pop(number)
                    written = bond or first
                    if bond and first and _BONDS[bond] != _BONDS[first]:
                        raise self.fail(f"Ring {number} is opened and closed with different bonds")
                    self.join(other, previous, written, closing=True)
                    self.molecule.atoms[previous].order.append(other)
                    self.molecule.atoms[other].order[
                        self.molecule.atoms[other].order.index(-2 - number)
                    ] = previous
                else:
                    rings[number] = (previous, bond)
                    self.molecule.atoms[previous].order.append(-2 - number)  # its place, kept
                bond = ""
            else:
                atom = self.atom()
                if previous is not None:
                    self.join(previous, atom, bond)
                    self.molecule.atoms[previous].order.append(atom)
                    self.molecule.atoms[atom].order.insert(0, previous)
                previous, bond = atom, ""
        if branches:
            raise SmilesError("A branch is opened and never closed.", "Close each ( with a ).")
        if rings:
            numbers = ", ".join(str(number) for number in sorted(rings))
            raise SmilesError(
                f"Ring {numbers} is opened and never closed.",
                "Each ring number is written twice: where the ring opens, and where it closes.",
            )
        if bond:
            raise SmilesError("The SMILES ends with a bond to nothing.")
        return self.molecule

    def join(self, a: int, b: int, written: str, *, closing: bool = False) -> None:
        if a == b or self.molecule.bond(a, b) is not None:
            raise self.fail("Two atoms are bonded twice")
        atoms = self.molecule.atoms
        aromatic = (not written and atoms[a].aromatic and atoms[b].aromatic) or written == ":"
        order = _BONDS.get(written, 1)
        stereo = written if written in "/\\" and written else ""
        if closing and stereo:
            # A ring bond's direction is written from the atom that closes it.
            stereo = {"/": "\\", "\\": "/"}[stereo]
        self.molecule.bonds.append(Bond(a, b, order, aromatic, stereo))

    def atom(self) -> int:
        text = self.text
        if text[self.at] == "[":
            return self.bracket()
        for symbol in _ORGANIC:
            if text.startswith(symbol, self.at):
                self.at += len(symbol)
                return self.add(Atom(symbol))
        for symbol in _AROMATIC[2:]:
            if text.startswith(symbol, self.at):
                self.at += len(symbol)
                return self.add(Atom(symbol.upper(), aromatic=True))
        if text[self.at] == "*":
            raise self.fail("A * (any atom) cannot be drawn")
        raise self.fail(f'"{text[self.at]}" is not an atom SMILES writes')

    def bracket(self) -> int:
        text = self.text
        end = text.find("]", self.at)
        if end < 0:
            raise self.fail("A [ is never closed")
        inside = text[self.at + 1 : end]
        match = re.fullmatch(
            r"(\d+)?([A-Z][a-z]?|se|as|[bcnops])(@@|@)?(H\d*)?(\+\d*|\++|-\d*|-+)?(?::(\d+))?",
            inside,
        )
        if match is None:
            raise self.fail(f'"[{inside}]" is not a bracket atom SMILES writes')
        isotope, symbol, chirality, hydrogens, charge, mapped = match.groups()
        aromatic = symbol[0].islower()
        element = symbol.capitalize()
        count = 0
        if hydrogens:
            count = int(hydrogens[1:]) if len(hydrogens) > 1 else 1
        signed = 0
        if charge:
            sign = 1 if charge[0] == "+" else -1
            rest = charge[1:]
            signed = sign * (int(rest) if rest.isdigit() else len(charge))
        atom = Atom(
            element,
            signed,
            count,
            int(isotope) if isotope else None,
            int(mapped) if mapped else None,
            aromatic,
            chirality or "",
            bracket=True,
        )
        if count:
            atom.order.append(-1)
        self.at = end + 1
        return self.add(atom)

    def add(self, atom: Atom) -> int:
        self.molecule.atoms.append(atom)
        return len(self.molecule.atoms) - 1


class _Spans(_Reader):
    """A reader that keeps where in the words each atom is written."""

    def __init__(self, smiles: str) -> None:
        super().__init__(smiles)
        self.spans: list[tuple[int, int]] = []

    def atom(self) -> int:
        start = self.at
        index = super().atom()
        self.spans.append((start, self.at))
        return index


def _kekulize(molecule: Molecule, smiles: str) -> None:
    """Give an aromatic ring alternating single and double bonds (a Kekulé structure)."""

    aromatic = [bond for bond in molecule.bonds if bond.aromatic]
    if not aromatic:
        return
    wanting: set[int] = set()
    for index, atom in enumerate(molecule.atoms):
        if not atom.aromatic:
            continue
        explicit_double = any(
            bond.order >= 2 and not bond.aromatic for bond in molecule.bonds_of(index)
        )
        degree = len(molecule.neighbours(index)) + (atom.hydrogens if atom.bracket else 0)
        if atom.element == "C":
            needs = atom.charge == 0 and not explicit_double
        elif atom.element in {"N", "P", "As"}:
            # Pyridine's nitrogen takes a double bond; pyrrole's ([nH], or bonded thrice) does not.
            needs = not explicit_double and (
                (atom.charge == 0 and degree == 2) or (atom.charge == 1 and degree == 3)
            )
        elif atom.element in {"O", "S", "Se"}:
            needs = atom.charge == 1 and degree == 2
        else:
            needs = False
        if needs:
            wanting.add(index)
    choices = {index: [] for index in wanting}
    for bond in aromatic:
        if bond.a in wanting and bond.b in wanting:
            choices[bond.a].append(bond)
            choices[bond.b].append(bond)
    matched: dict[int, Bond] = {}

    def match(remaining: set[int]) -> bool:
        if not remaining:
            return True
        atom = min(
            remaining,
            key=lambda item: len([b for b in choices[item] if b.other(item) in remaining]),
        )
        for bond in choices[atom]:
            other = bond.other(atom)
            if other in remaining:
                matched[atom] = matched[other] = bond
                if match(remaining - {atom, other}):
                    return True
                del matched[atom], matched[other]
        return False

    if not match(set(wanting)):
        raise SmilesError(
            f"The aromatic ring in {smiles!r} cannot be drawn as alternating single and "
            "double bonds.",
            "A pyrrole-like nitrogen carries its hydrogen: write [nH], as in c1cc[nH]c1.",
        )
    for bond in aromatic:
        bond.order = 2 if matched.get(bond.a) is bond else 1
        bond.aromatic = False
    for atom in molecule.atoms:
        atom.aromatic = False
