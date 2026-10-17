"""Chemistry as chemists draw it: SMILES read, molecules laid out flat, wedges that say
what the SMILES says, and curly arrows that move electrons -- checked."""

from __future__ import annotations

import math
import re

import pytest

import flexo
from flexo.chemistry.curly import INK
from flexo.chemistry.electrons import MechanismError, compare, push, read_arrow
from flexo.chemistry.layout import lay_out, rings
from flexo.chemistry.molecule import SmilesError, read_smiles
from flexo.chemistry.stereo import _handedness, wedges
from flexo.diagnostics import FlexoError
from flexo.drawn import picture
from flexo.style import STYLES


def _atoms(smiles: str) -> list[tuple[str, int, int, int]]:
    molecule = read_smiles(smiles)
    return [
        (atom.element, atom.hydrogens, molecule.charge_of(index), atom.lone)
        for index, atom in enumerate(molecule.atoms)
    ]


@pytest.mark.parametrize(
    ("smiles", "atoms"),
    [
        ("CC(=O)O", [("C", 3, 0, 0), ("C", 0, 0, 0), ("O", 0, 0, 4), ("O", 1, 0, 4)]),
        ("[OH-]", [("O", 1, -1, 6)]),
        (
            "C[N+](C)(C)C",
            [("C", 3, 0, 0), ("N", 0, 1, 0), ("C", 3, 0, 0), ("C", 3, 0, 0), ("C", 3, 0, 0)],
        ),
        ("[CH3]", [("C", 3, 0, 1)]),  # a methyl radical
        ("[CH2-]C", [("C", 2, -1, 2), ("C", 3, 0, 0)]),  # a carbanion's lone pair
        ("[CH3+]", [("C", 3, 1, 0)]),
        (
            "c1cc[nH]c1",
            [("C", 1, 0, 0), ("C", 1, 0, 0), ("C", 1, 0, 0), ("N", 1, 0, 2), ("C", 1, 0, 0)],
        ),
        (
            "O=S(=O)(O)O",
            [("O", 0, 0, 4), ("S", 0, 0, 0), ("O", 0, 0, 4), ("O", 1, 0, 4), ("O", 1, 0, 4)],
        ),
    ],
)
def test_smiles_gives_each_atom_its_hydrogens_charge_and_electrons(
    smiles: str, atoms: list
) -> None:
    assert _atoms(smiles) == atoms


def test_an_aromatic_ring_is_drawn_as_alternating_bonds() -> None:
    benzene = read_smiles("c1ccccc1")
    assert sorted(bond.order for bond in benzene.bonds) == [1, 1, 1, 2, 2, 2]
    for index in range(6):
        assert sum(bond.order for bond in benzene.bonds_of(index)) == 3
    pyridine = read_smiles("c1ccncc1")
    nitrogen = next(i for i, atom in enumerate(pyridine.atoms) if atom.element == "N")
    assert sum(bond.order for bond in pyridine.bonds_of(nitrogen)) == 3


@pytest.mark.parametrize(
    ("smiles", "said"),
    [
        ("C1CC", "Ring 1 is opened and never closed"),
        ("C((C)", "A branch is opened and never closed"),
        ("CC(C)(C)(C)C", "makes 5 bonds"),
        ("c1cccc1", "cannot be drawn as alternating single and double bonds"),
        ("[CL]", '"CL" is not an element'),
        ("", "The SMILES is empty"),
    ],
)
def test_smiles_that_cannot_be_read_is_said_in_words(smiles: str, said: str) -> None:
    with pytest.raises(SmilesError, match=re.escape(said)):
        read_smiles(smiles)


def _placeholders(smiles: str) -> list[tuple[str, int, int | None]]:
    return [(atom.placeholder, atom.charge, atom.map) for atom in read_smiles(smiles).atoms]


def test_a_bracket_atom_that_is_no_element_is_a_placeholder_drawn_as_it_is_written() -> None:
    assert _placeholders("[X:1].[Y:2][Z:3]") == [("X", 0, 1), ("Y", 0, 2), ("Z", 0, 3)]
    assert _placeholders("[Nu-:1].[E:2]=[Z:3]") == [("Nu", -1, 1), ("E", 0, 2), ("Z", 0, 3)]
    symbols = ["X", "Nu", "E", "LG", "R", "R1", "R'", "R1''", "EWG", "M", "L", "Ph", "NHC"]
    for symbol in symbols:
        assert _placeholders(f"[{symbol}]") == [(symbol, 0, None)], symbol
    assert _placeholders("[Nu+]") == [("Nu", 1, None)]
    assert _placeholders("[LG-2:7]") == [("LG", -2, 7)]
    # Its valence is unknown: any bonds, no hydrogens of its own, no electrons known to be its.
    crowded = read_smiles("[M](=O)(=O)(=O)(Cl)(Cl)(Cl)C")
    assert crowded.bonded(0) == 10 and crowded.charge_of(0) == 0
    assert [(atom.hydrogens, atom.lone) for atom in read_smiles("[X][Y-]").atoms] == [(0, 0)] * 2
    # The atoms beside it are read as ever.
    assert _atoms("C[X]")[0] == ("C", 3, 0, 0)
    assert [read_smiles("[R1:4]C[X]").name(index) for index in range(3)] == [
        "R1:4",
        "an unnumbered C",
        "an unnumbered X",
    ]
    assert [read_smiles("[R'][Nu]").name(index) for index in range(2)] == ["R':1", "Nu2"]


def test_a_symbol_that_is_an_element_means_the_element_unless_a_star_comes_before_it() -> None:
    argon, boron = read_smiles("[Ar]").atoms[0], read_smiles("[B:4]").atoms[0]
    assert (argon.element, argon.placeholder, argon.lone) == ("Ar", "", 8)
    assert (boron.element, boron.placeholder, boron.map) == ("B", "", 4)
    assert _placeholders("[*Ar]") == [("Ar", 0, None)]
    assert _placeholders("[*B:4]") == [("B", 0, 4)]
    assert _placeholders("[*CL-]") == [("CL", -1, None)]
    forced = read_smiles("[*C](C)(C)(C)(C)C")  # no carbon: five bonds are not counted against it
    assert forced.atoms[0].element == "*" and forced.name(0) == "C1"


@pytest.mark.parametrize(
    ("smiles", "said", "hint"),
    [
        ("*", "A * (any atom) cannot be drawn without a name", "[X], [Nu], [R1]; or [*Ar]"),
        ("C[*]", "A * (any atom) cannot be drawn without a name", "[X], [Nu], [R1]; or [*Ar]"),
        ("[*-:1]", "A * (any atom) cannot be drawn without a name", "Name it, in brackets"),
        ("[XH2]", "gives the placeholder X hydrogens", "[X][H]"),
        ("[NuH+:2]", "a placeholder carries none of its own", "[Nu][H]"),
        ("[R1H]", "gives the placeholder R1 hydrogens", "[R1][H]"),
        ("[*OH]", "gives the placeholder O hydrogens", "[*O][H]"),
        ("[13X]", "gives the placeholder X an isotope", ""),
        ("[X@@]", "gives the placeholder X a handedness", ""),
        # A mistyped element is not taken for a placeholder.
        ("[CL]", '"CL" is not an element flexo knows', "Did you mean [Cl]?"),
        ("C[BR-:3]", '"BR" is not an element flexo knows', "Did you mean [Br-:3]?"),
        ("[NA+]", '"NA" is not an element flexo knows', "write [*NA+]"),
        ("[RH]", '"RH" is not an element flexo knows', "Did you mean [Rh]?"),
        ("[cl]", '"[cl]" is not a bracket atom SMILES writes', "Did you mean [Cl]?"),
        ("[x]", '"[x]" is not a bracket atom SMILES writes', ""),
        ("[Xyz1a?]", '"[Xyz1a?]" is not a bracket atom SMILES writes', ""),
        ("[R1a]", '"[R1a]" is not a bracket atom SMILES writes', ""),
        ("[*c]", '"[*c]" is not a bracket atom SMILES writes', ""),
        ("[Cl2]", '"[Cl2]" is not a bracket atom SMILES writes', "write [*Cl2]"),
        ("CX", '"X" is not an atom SMILES writes', "goes in them: [X]"),
    ],
)
def test_a_placeholder_written_wrongly_and_an_element_mistyped_are_said_in_words(
    smiles: str, said: str, hint: str
) -> None:
    with pytest.raises(SmilesError, match=re.escape(said)) as caught:
        read_smiles(smiles)
    assert hint in caught.value.hint and bool(hint) == bool(caught.value.hint)


def _angles(molecule) -> set[int]:
    return {
        round(
            math.degrees(
                math.atan2(
                    molecule.atoms[b.b].y - molecule.atoms[b.a].y,
                    molecule.atoms[b.b].x - molecule.atoms[b.a].x,
                )
            )
        )
        % 180
        for b in molecule.bonds
    }


@pytest.mark.parametrize("smiles", ["CCCCCC", "c1ccccc1CC(=O)O", "c1ccc2ccccc2c1", "C/C=C/C(=O)Cl"])
def test_a_molecule_is_laid_out_on_the_30_degree_grid_with_every_bond_one_long(smiles: str) -> None:
    molecule = read_smiles(smiles)
    lay_out(molecule)
    for bond in molecule.bonds:
        a, b = molecule.atoms[bond.a], molecule.atoms[bond.b]
        assert math.hypot(a.x - b.x, a.y - b.y) == pytest.approx(1.0, abs=1e-6)
    assert _angles(molecule) <= {30, 90, 150}  # a horizontal zigzag; rings point up
    for i, a in enumerate(molecule.atoms):
        for j, b in enumerate(molecule.atoms):
            if i < j and molecule.bond(i, j) is None:
                assert math.hypot(a.x - b.x, a.y - b.y) > 0.9


def test_a_five_membered_ring_stands_on_its_heteroatom() -> None:
    furan = read_smiles("c1ccoc1")
    lay_out(furan)
    oxygen = next(atom for atom in furan.atoms if atom.element == "O")
    assert oxygen.y == pytest.approx(max(atom.y for atom in furan.atoms))  # at the bottom
    assert oxygen.x == pytest.approx(sum(atom.x for atom in furan.atoms) / 5, abs=1e-6)


def test_a_double_bond_keeps_its_substituents_on_the_sides_its_smiles_gives() -> None:
    for smiles, same_side in (("F/C=C/F", False), ("F/C=C\\F", True)):
        molecule = read_smiles(smiles)
        lay_out(molecule)
        f1, c1, c2, f2 = molecule.atoms

        def side(point, c1=c1, c2=c2) -> bool:
            return (c2.x - c1.x) * (point.y - c1.y) - (c2.y - c1.y) * (point.x - c1.x) > 0

        assert (side(f1) == side(f2)) is same_side, smiles


def test_rings_are_the_smallest_set() -> None:
    naphthalene = read_smiles("c1ccc2ccccc2c1")
    assert sorted(len(ring) for ring in rings(naphthalene, list(range(10)))) == [6, 6]


def test_a_wedge_says_the_handedness_its_smiles_gives() -> None:
    # The two alanines, drawn alike, differ only in their wedge.
    drawn = {}
    for smiles in ("N[C@@H](C)C(=O)O", "N[C@H](C)C(=O)O"):
        molecule = read_smiles(smiles)
        lay_out(molecule)
        (((centre, raised), style),) = wedges(molecule).items()
        assert centre == 1
        order = [item for item in molecule.atoms[1].order]
        handed = _handedness(molecule, 1, order, raised)
        assert (handed == molecule.atoms[1].chirality) == (style == "wedge")
        drawn[smiles] = style
    assert set(drawn.values()) == {"wedge", "hash"}


ACYL = "[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]"


def _pushed(smiles: str, *steps: list[str]):
    molecule = read_smiles(smiles)
    for number, arrows in enumerate(steps, start=1):
        molecule = push(
            molecule, [read_arrow(text, molecule) for text in arrows], step=f"step {number}"
        )
    return molecule


def _bonds(molecule) -> set[str]:
    return {f"{molecule.name(b.a)}{'-=#'[b.order - 1]}{molecule.name(b.b)}" for b in molecule.bonds}


def test_arrows_move_electrons_and_the_structure_follows() -> None:
    middle = _pushed(ACYL, ["5 -> 2", "2=3 -> 3"])
    assert _bonds(middle) == {"C1-C2", "C2-O3", "C2-Cl4", "O5-C2"}
    assert [middle.charge_of(i) for i in range(5)] == [0, 0, 0, -1, 0]  # O3 takes the charge
    end = _pushed(ACYL, ["5 -> 2", "2=3 -> 3"], ["3 -> 2", "2-4 -> 4"])
    assert _bonds(end) == {"C1-C2", "C2=O3", "O5-C2"}
    assert end.charge_of(end.index_of(4)) == -1  # chloride
    radicals = _pushed("[Br:1][Br:2]", ["1-2 ~> 1", "1-2 ~> 2"])
    assert not radicals.bonds and [atom.lone % 2 for atom in radicals.atoms] == [1, 1]


def _charges(molecule) -> dict[str, int]:
    return {molecule.name(index): molecule.charge_of(index) for index in range(len(molecule.atoms))}


def test_a_placeholder_gives_the_pair_an_arrow_takes_and_its_charge_is_kept() -> None:
    # Backside attack: X gives a pair into a bond, Z takes the pair of the bond that breaks.
    sigma = _pushed("[X:1].[Y:2][Z:3]", ["1 -> 2", "2-3 -> 3"])
    assert _bonds(sigma) == {"X1-Y2"}
    assert _charges(sigma) == {"X1": 1, "Y2": 0, "Z3": -1}
    assert _charges(_pushed("[X-:1].[Y:2][Z:3]", ["1 -> 2", "2-3 -> 3"])) == {
        "X1": 0,
        "Y2": 0,
        "Z3": -1,
    }
    pi = _pushed("[Nu-:1].[E:2]=[Z:3]", ["1 -> 2", "2=3 -> 3"])
    assert _bonds(pi) == {"Nu1-E2", "E2-Z3"}
    assert _charges(pi) == {"Nu1": 0, "E2": 0, "Z3": -1}
    # The pair Z took is its own now, to give back: the step undone leaves all as it was.
    back = _pushed("[Nu-:1].[E:2]=[Z:3]", ["1 -> 2", "2=3 -> 3"], ["3 -> 2-3", "2-1 -> 1"])
    assert _bonds(back) == {"E2=Z3"} and _charges(back) == {"Nu1": -1, "E2": 0, "Z3": 0}
    assert [atom.lone for atom in back.atoms] == [2, 0, 0]
    # A bond moved through a placeholder leaves it as it was, however many bonds it has.
    moved = _pushed("[X:1]=[Y:2][Z+:3]", ["1=2 -> 2-3"])
    assert _bonds(moved) == {"X1-Y2", "Y2=Z3"} and _charges(moved) == {"X1": 1, "Y2": 0, "Z3": 0}
    many = _pushed("[L-:1].[M:2]([L])([L])([L])([L])[L]", ["1 -> 2"])
    assert many.bonded(many.index_of(2)) == 6 and many.charge_of(many.index_of(2)) == -1
    # Fishhooks, a half each: a bond broken into two radicals, and a radical adding to an alkene.
    halves = _pushed("[R:1][R:2]", ["1-2 ~> 1", "1-2 ~> 2"])
    assert not halves.bonds and _charges(halves) == {"R1": 0, "R2": 0}
    assert [atom.lone for atom in halves.atoms] == [1, 1]
    added = _pushed("[R:1].[CH2:3]=[CH2:4]", ["1 ~> 1-3", "3=4 ~> 3-1", "3=4 ~> 4"])
    assert _bonds(added) == {"R1-C3", "C3-C4"} and set(_charges(added).values()) == {0}
    assert [atom.lone for atom in added.atoms] == [0, 0, 1]
    # What is asked of a placeholder is not written on the molecule it was asked of.
    before = read_smiles("[X:1].[Y:2][Z:3]")
    push(before, [read_arrow("1 -> 2", before), read_arrow("2-3 -> 3", before)])
    assert [atom.lone for atom in before.atoms] == [0, 0, 0]


def test_the_real_atoms_beside_a_placeholder_are_checked_as_ever() -> None:
    mixed = "[Nu-:1].[CH3:2][Br:3]"
    made = _pushed(mixed, ["1 -> 2", "2-3 -> 3"])
    assert _bonds(made) == {"Nu1-C2"} and _charges(made) == {"Nu1": 0, "C2": 0, "Br3": -1}
    with pytest.raises(MechanismError, match="C2 would have 10 electrons round it"):
        _pushed(mixed, ["1 -> 2"])
    with pytest.raises(MechanismError, match="C2, which has no lone pair to give"):
        _pushed(mixed, ["2 -> 1"])
    with pytest.raises(MechanismError, match="H3 would make 2 bonds"):
        _pushed("[X:1].[Y:2][H:3]", ["1 -> 3"])
    with pytest.raises(MechanismError, match="is left with 1 electron"):
        _pushed("[R:1][R:2]", ["1-2 ~> 1"])
    # A step drawn by hand: a placeholder's charge and symbol are what the arrows leave.
    made = _pushed("[X:1].[Y:2][Z:3]", ["1 -> 2", "2-3 -> 3"])
    agreed = compare(made, read_smiles("[X+:1][Y:2].[Z-:3]"), step="step 2", before="step 1")
    assert agreed == []
    said = compare(made, read_smiles("[X:1][Y:2].[Nu-:3]"), step="step 2", before="step 1")
    assert said == [
        "step 1's arrows leave X1 positively charged, but step 2 draws it neutral.",
        "step 2 draws atom 3 as Nu; step 1 has it as Z.",
    ]
    # Its electrons cannot be written, so a radical the arrows leave on it is not asked for.
    halves = _pushed("[R:1][R:2]", ["1-2 ~> 1", "1-2 ~> 2"])
    assert compare(halves, read_smiles("[R:1].[R:2]"), step="step 2", before="step 1") == []


@pytest.mark.parametrize(
    ("smiles", "arrows", "said"),
    [
        (ACYL, ["5 -> 2"], "C2 would have 10 electrons round it"),
        ("[Br:1][Br:2]", ["1-2 ~> 1"], "is left with 1 electron"),
        ("[CH3:1][CH3:2]", ["1 -> 2"], "which has no lone pair to give"),
        ("[OH-:1].[CH3:2][C:3](=O)[CH2:4][H:5]", ["1 -> 5"], "H5 would make 2 bonds"),
        (ACYL, ["5 -> 9"], "there is no atom 9"),
        (ACYL, ["2-4 -> 1"], "without saying which of its atoms bonds to it"),
        (ACYL, ["1-3 -> 3"], "are not bonded"),
        (ACYL, ["hello"], "is not an arrow flexo reads"),
    ],
)
def test_an_arrow_that_cannot_be_is_said_with_how_to_mend_it(
    smiles: str, arrows: list[str], said: str
) -> None:
    with pytest.raises(MechanismError, match=re.escape(said)) as caught:
        _pushed(smiles, arrows)
    assert caught.value.hint or "no atom" in str(caught.value)


def test_a_step_drawn_by_hand_is_checked_against_the_arrows_before_it() -> None:
    made = _pushed(ACYL, ["5 -> 2", "2=3 -> 3"], ["3 -> 2", "2-4 -> 4"])
    assert (
        compare(
            made, read_smiles("[CH3:1][C:2](=[O:3])[OH:5].[Cl-:4]"), step="step 3", before="step 2"
        )
        == []
    )
    said = compare(
        made, read_smiles("[CH3:1][C:2](=[O:3])[O-:5].[Cl-:4]"), step="step 3", before="step 2"
    )
    assert "step 2's arrows leave O5 neutral, but step 3 draws it negatively charged." in said


def _mechanism(steps, **options):
    with flexo.Figure("mechanism", width="double-column") as figure:
        figure.root.mechanism("m", steps, **options)
    node = figure.spec.nodes[0]
    return figure, picture(node, STYLES["paper"])


def test_a_mechanism_draws_its_steps_arrows_and_what_they_make() -> None:
    _, drawing = _mechanism(
        [
            {
                "smiles": ACYL,
                "arrows": ["5 -> 2", "2=3 -> 3"],
                "label": "acid chloride",
                "reagents": "NaOH",
            },
            {"arrows": "3 -> 2; 2-4 -> 4"},
        ]
    )
    ids = {shape.id for shape in drawing.shapes}
    curly = [
        shape for shape in drawing.shapes if ".arrow" in shape.id and shape.id.startswith("m.step")
    ]
    strokes = [shape for shape in curly if not shape.id.endswith(".electrons")]
    assert len(strokes) == 4
    assert all(" C " in shape.d for shape in strokes)
    # The lone pairs two arrows take are drawn at their tails, all in the arrows' one ink.
    assert len(curly) - len(strokes) == 2
    assert {shape.color for shape in curly} == {INK}
    assert {"m.arrow1", "m.arrow2"} <= ids  # a reaction arrow into each step after the first
    words = {"".join(run.text for run in words.runs) for words in drawing.words}
    assert {"acid chloride", "NaOH", "Cl"} <= words
    assert any(shape.id.startswith("m.step3.") for shape in drawing.shapes)  # what the arrows make


def test_a_mechanism_that_cannot_be_is_refused_in_words() -> None:
    with pytest.raises(FlexoError) as caught:
        _mechanism([{"smiles": ACYL, "arrows": "5 -> 2"}])
    (said,) = caught.value.diagnostics
    assert said.code == "mechanism.arrows" and "10 electrons" in said.message
    with pytest.raises(FlexoError) as caught:
        # The tetrahedral intermediate, drawn with O3 neutral: the arrows leave it charged.
        _mechanism(
            [
                {"smiles": ACYL, "arrows": "5 -> 2; 2=3 -> 3"},
                {"smiles": "[CH3:1][C:2]([OH:3])([OH:5])[Cl:4]"},
            ]
        )
    (said,) = caught.value.diagnostics
    assert said.code == "mechanism.check" and "leave O3 negatively charged" in said.message


def test_a_later_step_may_bring_in_a_new_molecule_and_leave_out_a_spectator() -> None:
    _, drawing = _mechanism(
        [
            {"smiles": "[Br:1][Br:2]", "arrows": ["1-2 ~> 1", "1-2 ~> 2"]},
            {"smiles": "[Br:1].[CH2:3]=[CH:4]C", "arrows": ["1 ~> 1-3", "3=4 ~> 3-1", "3=4 ~> 4"]},
        ]
    )
    assert any(".radical" in shape.id for shape in drawing.shapes)
    # Br's electron and one of the pi bond's meet in the gap where Br-C3 is made, from
    # either side of it.
    ends = {}
    for shape in drawing.shapes:
        if shape.id in {"m.step2.arrow0", "m.step2.arrow1"}:
            numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
            ends[shape.id] = (numbers[8], numbers[9])  # the tip: after M and the curve, "L"
    first, second = ends["m.step2.arrow0"], ends["m.step2.arrow1"]
    (bond,) = [shape for shape in drawing.shapes if shape.id == "m.step2.bond1"]
    length = math.dist(*_ends_of(bond.d))
    assert 0.25 < math.dist(first, second) / length < 0.6


@pytest.mark.parametrize(
    "steps",
    [
        [{"smiles": ACYL, "arrows": "5 -> 2; 2=3 -> 3"}, {"arrows": "3 -> 2; 2-4 -> 4"}],
        [{"smiles": "[CH3:1][C:2](=[O:3])[CH3:4].[OH2+:5][H:6]", "arrows": "3 -> 6; 6-5 -> 5"}],
        [{"smiles": "[Br:1].[CH2:3]=[CH:4]C", "arrows": "1 ~> 1-3; 3=4 ~> 3-1; 3=4 ~> 4"}],
        [{"smiles": "[OH-:1].[H:2][CH2:3][CH2:4][Br:5]", "arrows": "1 -> 2; 2-3 -> 3-4; 4-5 -> 5"}],
    ],
)
def test_each_curly_arrow_is_one_curve_crossing_no_bond_and_no_charge(steps) -> None:
    from flexo.chemistry.curly import _crossing, _shape

    _, drawing = _mechanism(steps)
    bonds = [
        (*first, *second)
        for shape in drawing.shapes
        if ".bond" in shape.id
        for first, second in [_ends_of(shape.d)]
    ]
    charges = [_circle_of(shape.d) for shape in drawing.shapes if ".charge" in shape.id]
    for shape in drawing.shapes:
        if not re.fullmatch(r"m\.step\d+\.arrow\d+", shape.id):
            continue
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
        start, first, second, end = (tuple(numbers[i : i + 2]) for i in (0, 2, 4, 6))
        curve = [_cubic(start, first, second, end, step / 24) for step in range(25)]
        assert _shape(curve) is not None, shape.id  # a C, or an S: never a wave
        assert not _crossing(curve, bonds), shape.id
        for x, y, radius in charges:
            assert all(math.dist(point, (x, y)) > radius for point in curve), shape.id


def _ends_of(d: str):
    numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return (numbers[0], numbers[1]), (numbers[-2], numbers[-1])


def _circle_of(d: str):
    left, y, radius = (float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", d)[:3])
    return left + radius, y, radius


def _cubic(a, b, c, d, t):
    u = 1 - t
    return tuple(
        u**3 * a[i] + 3 * u * u * t * b[i] + 3 * u * t * t * c[i] + t**3 * d[i] for i in (0, 1)
    )


def test_a_mechanism_draws_its_arrows_in_the_colour_asked_and_the_lone_pairs_they_leave() -> None:
    _, drawing = _mechanism(
        [{"smiles": ACYL, "arrows": "5 -> 2; 2=3 -> 3"}], arrow_colour="#1f77b4", lone_pairs="all"
    )
    arrows = [shape for shape in drawing.shapes if shape.id.startswith("m.step1.arrow")]
    assert arrows and {shape.color for shape in arrows} == {"#1f77b4"}
    # O5 of hydroxide has three lone pairs: the arrow draws the one it takes, the rest stay.
    assert len([shape for shape in drawing.shapes if shape.id.startswith("m.step1.pair")]) >= 2
    with pytest.raises(FlexoError, match="arrow_colour"):
        _mechanism([{"smiles": ACYL}], arrow_colour="magenta")


def _numbers(d: str) -> list[float]:
    return [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", d)]


def test_a_placeholder_is_lettered_as_an_atom_is_where_its_bond_and_its_charge_meet_it() -> None:
    from flexo.compiler import compile_figure
    from flexo.mechanism import mechanism_composed

    steps = [{"smiles": "[X:1].[Y:2][Z:3]", "arrows": ["1 -> 2", "2-3 -> 3"]}]
    figure, drawing = _mechanism(steps)
    lettered = {words.id: "".join(run.text for run in words.runs) for words in drawing.words}
    assert [lettered[f"m.step1.atom{index}"] for index in range(3)] == ["X", "Y", "Z"]
    assert [lettered[f"m.step2.atom{index}"] for index in range(3)] == ["X", "Y", "Z"]
    ids = {shape.id for shape in drawing.shapes}
    # The pair X gives is drawn at its arrow's tail, as any atom's is; the charges the
    # arrows leave are circled beside X and Z.
    assert {"m.step1.arrow0", "m.step1.arrow0.electrons", "m.step1.arrow1"} <= ids
    assert "m.step1.arrow1.electrons" not in ids
    assert {"m.step2.charge0", "m.step2.charge2"} <= ids and "m.step2.charge1" not in ids
    marks = (".pair", ".radical", ".charge")
    assert not any(mark in name for name in ids if name.startswith("m.step1.") for mark in marks)
    composed = mechanism_composed(figure.spec.nodes[0], STYLES["paper"])
    drawn, _, _ = composed.drawn[1]
    u = composed.pen.u
    # The bond X-Y runs between the two letters and stops short of each, as at any label.
    (bond,) = [shape for shape in drawn.shapes if shape.id == "m.step2.bond0"]
    x1, y1, x2, y2 = _numbers(bond.d)
    for end, atom in (((x1, y1), 0), ((x2, y2), 1)):
        assert 0.3 * u < math.dist(end, drawn.atoms[atom].point) < 0.7 * u
    assert math.dist((x1, y1), (x2, y2)) < composed.pen.bond - 0.6 * u
    for atom, charge, positive in ((0, "m.step2.charge0", True), (2, "m.step2.charge2", False)):
        (shape,) = [item for item in drawn.shapes if item.id == charge]
        left, y, radius = _numbers(shape.d)[:3]
        assert 0.3 * u < math.dist((left + radius, y), drawn.atoms[atom].point) < 1.2 * u
        assert (shape.d.count(" M ") == 2) is positive  # a plus has two strokes, a minus one
    # In the file they are words, in the face and size of the other atoms' letters.
    svg = compile_figure(figure.spec).document.text
    found = dict(re.findall(r'<text id="(m\.step2\.atom\d)"[^>]*>(?:<tspan[^>]*>)?([^<]+)<', svg))
    assert found == {"m.step2.atom0": "X", "m.step2.atom1": "Y", "m.step2.atom2": "Z"}
    assert 'id="m.step2.charge0"' in svg and 'id="m.step2.bond0"' in svg
    mixed, _ = _mechanism([{"smiles": "[Nu-:1].[CH3:2][Br:3]", "arrows": "1 -> 2; 2-3 -> 3"}])
    faces = set(
        re.findall(
            r'<text id="m\.step1\.atom\d"[^>]*(font-family="[^"]+" font-size="[^"]+")',
            compile_figure(mixed.spec).document.text,
        )
    )
    assert len(faces) == 1


def test_a_placeholders_digits_are_raised_and_its_primes_kept() -> None:
    drawn = _drawn("[R1][C](=O)[R2'].[EWG-][*Ar]")
    runs = {
        words.id: [(run.text, run.baseline_shift) for run in words.runs] for words in drawn.words
    }
    assert runs["m.atom0"] == [("R", "normal"), ("1", "super")]
    assert runs["m.atom3"] == [("R", "normal"), ("2", "super"), ("'", "normal")]
    assert runs["m.atom4"] == [("EWG", "normal")] and runs["m.atom5"] == [("Ar", "normal")]
    assert "m.charge4" in {shape.id for shape in drawn.shapes}
    # Its letters are centred on its place, and keep its bond off all of them.
    (label,) = [words for words in drawn.words if words.id == "m.atom4"]
    x = drawn.atoms[4].point[0]
    assert label.x + label.metrics.width / 2 == pytest.approx(x)
    assert drawn.atoms[4].radius[0] > label.metrics.width / 2
    # A charge beside a raised number keeps off the number, which stands above the capitals.
    numbered = _drawn("[R1-]")
    ((_, cx, cy, radius),) = numbered.marks
    _, (left, top, right, bottom) = numbered.atoms[0].ink
    assert top < numbered.atoms[0].ink[0][1]
    assert math.hypot(max(left - cx, 0, cx - right), max(top - cy, 0, cy - bottom)) > radius
    # A hydrogen bonded to it that no arrow moves is written in its label, as H2O's are.
    _, drawing = _mechanism("[Nu:1][H:2]")
    (label,) = drawing.words
    assert "".join(run.text for run in label.runs) in {"NuH", "HNu"}


def test_the_lone_pairs_of_a_placeholder_are_those_arrows_leave_on_it() -> None:
    steps = [{"smiles": "[X:1].[Y:2][Z:3]", "arrows": ["1 -> 2", "2-3 -> 3"]}]
    _, drawing = _mechanism(steps, lone_pairs="all")
    pairs = sorted(shape.id for shape in drawing.shapes if ".pair" in shape.id)
    # As written it shows none; X's is at its arrow's tail; Z keeps the pair it took.
    assert pairs == ["m.step2.pair2.0"]
    _, drawing = _mechanism([{"smiles": "[R:1][R:2]", "arrows": ["1-2 ~> 1", "1-2 ~> 2"]}])
    assert {shape.id for shape in drawing.shapes if ".radical" in shape.id} == {
        "m.step2.radical0",
        "m.step2.radical1",
    }
    # A fishhook from a placeholder draws the one electron it takes, not a pair.
    _, drawing = _mechanism(
        [{"smiles": "[R:1].[CH2:3]=[CH2:4]", "arrows": ["1 ~> 1-3", "3=4 ~> 3-1", "3=4 ~> 4"]}]
    )
    (dots,) = [shape for shape in drawing.shapes if shape.id == "m.step1.arrow0.electrons"]
    assert dots.d.count("M") == 1
    assert not any(shape.id == "m.step1.radical0" for shape in drawing.shapes)


def test_a_cycloaddition_is_drawn_ready_to_close_its_ring() -> None:
    _, drawing = _mechanism(
        [
            {
                "smiles": "[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH2:6]",
                "arrows": "1=2 -> 1-6; 3=4 -> 2-3; 5=6 -> 4-5",
            }
        ]
    )
    product = [shape for shape in drawing.shapes if shape.id.startswith("m.step2.bond")]
    ends = []
    for shape in product:
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
        ends.append(math.hypot(numbers[2] - numbers[0], numbers[3] - numbers[1]))
    # The product is a ring of six bonds of one length (its inner double line shorter).
    main = [
        length
        for shape, length in zip(product, ends, strict=True)
        if not shape.id.endswith(".inner")
    ]
    assert len(main) == 6 and max(main) - min(main) < 1e-6 * max(main) + 0.05


def _drawn(smiles: str):
    from flexo.chemistry.draw import Pen, draw_molecule
    from flexo.drawn import units

    measures = units(STYLES["paper"])
    molecule = read_smiles(smiles)
    lay_out(molecule)
    return draw_molecule(
        molecule, Pen(measures.u, lambda runs: measures.measure(runs)), prefix="m", pairs="all"
    )


def test_a_metal_keeps_its_d_electrons_and_a_double_charge_is_written_after_it() -> None:
    iron = _drawn("[Fe-](Br)(Br)(Br)Br")
    assert not any(".radical" in shape.id or ".pair0." in shape.id for shape in iron.shapes)
    magnesium = _drawn("[Mg+2]")
    (label,) = magnesium.words
    assert "".join(run.text for run in label.runs) == "Mg2+"
    assert label.runs[-1].baseline_shift == "super"
    assert not any(".charge" in shape.id for shape in magnesium.shapes)


def test_a_circled_charge_keeps_off_the_bonds_round_its_atom() -> None:
    drawn = _drawn("C[NH2+]C(C)(C)[O-]")
    (charge,) = [shape for shape in drawn.shapes if shape.id == "m.charge1"]
    # The circle is "M x-r y A r r ...": its centre and radius.
    left, y, radius = (float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", charge.d)[:3])
    centre = (left + radius, y)
    for lines in drawn.lines.values():
        for (x1, y1), (x2, y2) in lines:
            for step in range(21):
                t = step / 20
                point = (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
                assert math.dist(point, centre) > radius


def test_an_atom_is_given_a_map_in_its_smiles_and_nothing_else_changes() -> None:
    from flexo.chemistry.molecule import mapped_smiles

    for smiles, atom, written in [
        ("CC(=O)Cl", 1, "C[C:9](=O)Cl"),
        ("CC(=O)Cl", 0, "[CH3:9]C(=O)Cl"),
        ("c1ccccc1", 2, "c1c[cH:9]ccc1"),
        ("C[NH3+]", 1, "C[NH3+:9]"),
    ]:
        assert mapped_smiles(smiles, atom, 9) == written
        before, after = read_smiles(smiles), read_smiles(written)
        assert [(a.element, a.hydrogens, a.charge, a.lone) for a in before.atoms] == [
            (a.element, a.hydrogens, a.charge, a.lone) for a in after.atoms
        ]


def test_a_step_that_cannot_be_is_drawn_as_far_as_it_goes_when_asked() -> None:
    from flexo.mechanism import mechanism_states

    half = [{"smiles": "[OH-:1].[CH3:2][Br:3]", "arrows": "1 -> 2"}, {"label": "after"}]
    with pytest.raises(FlexoError, match="10 electrons"):
        _mechanism(half)
    figure, drawing = _mechanism(half, partial=True)
    panels, problem = mechanism_states(figure.spec.nodes[0])
    assert len(panels) == 1 and problem is not None and problem.code == "mechanism.arrows"
    assert any(shape.id.startswith("m.step1.arrow") for shape in drawing.shapes)
    assert not any(shape.id.startswith("m.step2.") for shape in drawing.shapes)


def test_a_step_puts_its_molecules_where_the_author_places_them() -> None:
    from flexo.mechanism import mechanism_states, place_record, place_words

    steps = [{"smiles": "[OH-:1].[CH3:2][Br:3]", "arrows": "1 -> 2; 2-3 -> 3"}]
    plain, _ = mechanism_states(_mechanism(steps)[0].spec.nodes[0])
    placed = [{**steps[0], "place": {1: {"move": [-1, 0.5]}, 2: {"turn": 90}}}]
    moved, problem = mechanism_states(_mechanism(placed)[0].spec.nodes[0])
    assert problem is None
    before, after = plain[0].molecule.atoms, moved[0].molecule.atoms
    assert (after[0].x - before[0].x, after[0].y - before[0].y) == pytest.approx((-1, 0.5))
    # C2-Br3 turned a quarter about its middle: its bond now runs across where it ran.
    run = (before[2].x - before[1].x, before[2].y - before[1].y)
    turned = (after[2].x - after[1].x, after[2].y - after[1].y)
    assert run[0] * turned[0] + run[1] * turned[1] == pytest.approx(0, abs=1e-9)
    mirror = [{**steps[0], "place": {2: {"flip": True}}}]
    flipped, _ = mechanism_states(_mechanism(mirror)[0].spec.nodes[0])
    atoms = flipped[0].molecule.atoms
    assert (atoms[2].x - atoms[1].x, atoms[2].y - atoms[1].y) == pytest.approx((-run[0], run[1]))
    assert place_words({5: [1, 2], 6: {"turn": 30, "flip": True}}) == "5 move 1 2; 6 turn 30 flip"
    assert place_record("5 move 1 2; 6 turn 30 flip") == {
        "5": {"move": [1.0, 2.0]},
        "6": {"turn": 30.0, "flip": True},
    }
    stale = [{**steps[0], "place": {9: [1, 0]}}]
    with pytest.raises(FlexoError, match="atom 9, which it does not have"):
        _mechanism(stale)
    with pytest.raises(FlexoError, match="does not say where a molecule goes"):
        _mechanism([{**steps[0], "place": "1 sideways"}])


def test_a_mechanisms_arrows_may_take_the_themes_colours() -> None:
    from flexo.compiler import compile_figure

    steps = [{"smiles": ACYL, "arrows": "5 -> 2; 2=3 -> 3"}]
    figure, drawing = _mechanism(steps, arrow_colour="accent2")
    arrows = [shape for shape in drawing.shapes if shape.id.startswith("m.step1.arrow")]
    assert {shape.color for shape in arrows} == {"tone-2-stroke"}
    svg = compile_figure(figure.spec).document.text
    assert re.search(r'id="m\.step1\.arrow0"[^>]*data-flexo-stroke="tone-2-stroke"', svg)
    _, inked = _mechanism(steps, arrow_colour="muted")
    arrows = [shape for shape in inked.shapes if shape.id.startswith("m.step1.arrow")]
    assert {shape.color for shape in arrows} == {"muted-ink"}


def test_a_figure_file_writes_a_mechanisms_arrows_and_places_as_python_does() -> None:
    from flexo.serialization import figure_to_document, parse_figure

    written = {
        "figure": {"id": "file"},
        "nodes": [
            {
                "id": "m",
                "kind": "mechanism",
                "properties": {
                    "steps": [
                        {
                            "smiles": "[OH-:1].[CH3:2][Br:3]",
                            "arrows": ["1 -> 2", "2-3 -> 3"],
                            "place": {1: {"move": [-1, 0]}},
                        },
                        "[CH3:2][OH:1].[Br-:3]",
                    ]
                },
            }
        ],
    }
    figure = parse_figure(written)
    (step, made) = figure.nodes[0].property("steps")
    assert step.get("arrows") == "1 -> 2; 2-3 -> 3" and step.get("place") == "1 move -1 0"
    assert made.get("smiles") == "[CH3:2][OH:1].[Br-:3]"
    assert written["nodes"][0]["properties"]["steps"][0]["arrows"] == ["1 -> 2", "2-3 -> 3"]
    # Drawn as the same mechanism written in Python is, and written back as words.
    steps = [
        {
            "smiles": "[OH-:1].[CH3:2][Br:3]",
            "arrows": ["1 -> 2", "2-3 -> 3"],
            "place": {1: [-1, 0]},
        },
        "[CH3:2][OH:1].[Br-:3]",
    ]
    with flexo.Figure("file") as same:
        same.root.mechanism("m", steps)
    assert picture(figure.nodes[0], STYLES["paper"]) == picture(same.spec.nodes[0], STYLES["paper"])
    back = figure_to_document(figure)["nodes"][0]["properties"]["steps"][0]
    assert back["arrows"] == "1 -> 2; 2-3 -> 3"


def test_a_figure_file_writes_placeholders_as_python_does() -> None:
    from flexo.serialization import figure_to_document, parse_figure

    steps = [
        {"smiles": "[X:1].[Y:2][Z:3]", "arrows": ["1 -> 2", "2-3 -> 3"]},
        {"smiles": "[X+:1][Y:2].[Z-:3]", "label": "X\u2013Y"},
    ]
    written = {
        "figure": {"id": "file"},
        "nodes": [{"id": "m", "kind": "mechanism", "properties": {"steps": steps}}],
    }
    figure = parse_figure(written)
    with flexo.Figure("file") as same:
        same.root.mechanism("m", steps)
    drawing = picture(figure.nodes[0], STYLES["paper"])
    assert drawing == picture(same.spec.nodes[0], STYLES["paper"])
    assert {"X", "Y", "Z"} <= {"".join(run.text for run in words.runs) for words in drawing.words}
    back = figure_to_document(figure)["nodes"][0]["properties"]["steps"]
    assert [step.get("smiles") for step in back] == [step["smiles"] for step in steps]
    # A step written out is held to the charges the arrows leave, on a placeholder too.
    steps[1]["smiles"] = "[X:1][Y:2].[Z-:3]"
    with pytest.raises(FlexoError, match="leave X1 positively charged, but step 2 draws it"):
        picture(parse_figure(written).nodes[0], STYLES["paper"])


@pytest.mark.parametrize(
    "smiles, arrow",
    [
        ("C[C+:1](C)C.[OH2:3]", "3 -> 1"),  # water onto a cation: written OH2, facing it
        ("[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]", "5 -> 2"),
        ("[CH3:1][C:2](=[O:3])[CH3:4].[OH2+:5][H:6]", "3 -> 6"),
    ],
)
def test_a_lone_pair_an_arrow_takes_faces_what_it_attacks(smiles, arrow) -> None:
    from flexo.mechanism import mechanism_composed

    figure, _ = _mechanism([{"smiles": smiles, "arrows": arrow}], partial=True)
    composed = mechanism_composed(figure.spec.nodes[0], STYLES["paper"])
    drawn, molecule, renumber = composed.drawn[0]
    giver, taker = (renumber[molecule.index_of(int(n))] for n in arrow.split(" -> "))
    (dots,) = [shape for shape in drawn.shapes if shape.id.endswith("arrow0.electrons")]
    numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", dots.d)]
    # Each dot is "M x-r y A r r 0 1 1 x+r y A ...": its centre is between its first two points.
    centres = [
        ((numbers[i] + numbers[i + 7]) / 2, numbers[i + 1]) for i in range(0, len(numbers), 16)
    ]
    middle = (sum(x for x, _ in centres) / len(centres), sum(y for _, y in centres) / len(centres))
    here, there = drawn.atoms[giver].point, drawn.atoms[taker].point
    pair = (middle[0] - here[0], middle[1] - here[1])
    toward = (there[0] - here[0], there[1] - here[1])
    cosine = (pair[0] * toward[0] + pair[1] * toward[1]) / (math.hypot(*pair) * math.hypot(*toward))
    assert cosine > 0.5  # within 60 degrees of the way to what it attacks


@pytest.mark.parametrize(
    "smiles, arrows",
    [
        ("[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]", "5 -> 2; 2=3 -> 3"),  # a carbonyl's bare carbon
        ("C[C+:1](C)C.[OH2:3]", "3 -> 1"),  # a cation's vertex, beside its charge
        ("[CH3:1][C:2](=[O:3])[CH3:4].[OH2+:5][H:6]", "3 -> 6; 6-5 -> 5"),  # letters
        ("[NH2:1]C.[CH3:2][C:3](=[O:4])[CH3:5]", "1 -> 3; 3=4 -> 4"),
        ("[OH-:1].[O:2]=[C:3]=[O:4]", "1 -> 3; 3=4 -> 4"),  # CO2's carbon, written
    ],
)
def test_an_arrow_off_a_lone_pair_is_an_s_and_every_head_stops_short_of_its_atom(
    smiles, arrows
) -> None:
    from flexo.chemistry.curly import HEAD_GAP, _Frame, _shape, _to_segment
    from flexo.mechanism import mechanism_composed

    figure, _ = _mechanism([{"smiles": smiles, "arrows": arrows}], partial=True)
    composed = mechanism_composed(figure.spec.nodes[0], STYLES["paper"])
    drawn, molecule, _ = composed.drawn[0]
    frame = _Frame(molecule, drawn, composed.pen)
    for number, text in enumerate(arrows.split("; ")):
        tail, head = text.split(" -> ")
        target = molecule.index_of(int(head.split("-")[-1]))
        (shape,) = [item for item in drawn.shapes if item.id == f"m.step1.arrow{number}"]
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
        start, first, second, end, tip = (tuple(numbers[i : i + 2]) for i in (0, 2, 4, 6, 8))
        curve = [_cubic(start, first, second, end, step / 24) for step in range(25)] + [tip]
        if "-" not in tail and math.dist(start, tip) > frame.bond:
            assert _shape(curve) == "S", text  # leaves its pair and arrives the same way
        elif "-" in tail:
            assert _shape(curve) == "C", text  # a hook
        # Its tip keeps the same gap off whatever the atom is drawn with.
        boxes, lines, circles = frame.ink(target)
        x, y = tip
        nearest = min(
            [math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)) for x0, y0, x1, y1 in boxes]
            + [_to_segment(tip, a, b) - composed.pen.line / 2 for a, b in lines]
            + [math.dist(tip, (cx, cy)) - radius for cx, cy, radius in circles]
        )
        assert HEAD_GAP * frame.bond <= nearest <= 2.5 * HEAD_GAP * frame.bond, text


def _written(drawn) -> dict[int, str]:
    """Each atom a drawing writes, by its number, as it is lettered."""

    found = {}
    for words in drawn.words:
        matched = re.fullmatch(r"m\.atom(\d+)", words.id)
        if matched:
            found[int(matched.group(1))] = "".join(run.text for run in words.runs)
    return found


def _flat(drawn) -> bool:
    return max(place.point[1] for place in drawn.atoms.values()) - min(
        place.point[1] for place in drawn.atoms.values()
    ) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    ("smiles", "written"),
    [
        ("O=C=O", {0: "O", 1: "C", 2: "O"}),  # carbon dioxide: not O=O
        ("O=[*C]=O", {0: "O", 1: "C", 2: "O"}),  # as a placeholder too, straight through
        ("C=C=C", {1: "C"}),  # an allene's middle
        ("C=C=O", {1: "C", 2: "O"}),  # a ketene's
        ("C=C=C=C", {1: "C", 2: "C"}),  # a cumulene's
    ],
)
def test_a_carbon_two_alike_bonds_run_straight_through_is_written_and_lies_flat(
    smiles: str, written: dict[int, str]
) -> None:
    from flexo.drawn import units

    u = units(STYLES["paper"]).u
    drawn = _drawn(smiles)
    assert _written(drawn) == written
    assert _flat(drawn)  # across the page, not on a slant
    assert [place.point[0] for place in drawn.atoms.values()] == sorted(
        place.point[0] for place in drawn.atoms.values()
    )
    for pair, lines in drawn.lines.items():
        # Each double bond is centred on its bond, its two lines a double bond's gap apart.
        first, second = sorted(pair)
        axis = drawn.atoms[first].point[1]
        (_, y1), _ = lines[0]
        (_, y2), _ = lines[1]
        assert (y1 + y2) / 2 == pytest.approx(axis, abs=1e-6)
        assert abs(y1 - y2) == pytest.approx(0.18 * 1.44 * u, rel=1e-6)
        # ... and stops short of a written atom's letter by as much as it does of an O's.
        for (x_start, _), (x_end, _) in lines:
            for atom, end in ((first, x_start), (second, x_end)):
                if atom not in written:
                    continue
                left, _, right, _ = drawn.atoms[atom].ink[0]
                apart = left - end if end < left else end - right
                assert 0.1 * u < apart < 0.25 * u, (smiles, atom)


def test_a_carbon_straight_through_a_substituted_allene_is_written_its_chain_still_zigzags():
    drawn = _drawn("CC=C=CC")  # penta-2,3-diene
    assert _written(drawn) == {2: "C"}
    molecule = read_smiles("CC=C=CC")
    lay_out(molecule)
    assert _angles(molecule) == {30, 150}


@pytest.mark.parametrize(
    ("smiles", "written", "angles"),
    [
        ("C=C", {}, {30}),  # ethene: a line on a slant, never an equals sign
        ("CC", {}, {30}),
        ("CC#CC", {}, {30}),  # but-2-yne: an alkyne's carbons a line, as IUPAC has them
        ("CCC#CCC", {}, {30, 150}),
        ("CC(C)=O", {3: "O"}, {30, 90, 150}),  # acetone
        ("CCCC#N", {4: "N"}, {30, 150}),  # a nitrile's carbon, between single and triple
    ],
)
def test_a_line_of_carbons_and_an_alkyne_are_drawn_as_ever(
    smiles: str, written: dict[int, str], angles: set[int]
) -> None:
    assert _written(_drawn(smiles)) == written
    molecule = read_smiles(smiles)
    lay_out(molecule)
    assert _angles(molecule) == angles


@pytest.mark.parametrize(
    ("smiles", "written"),
    [
        ("O=O", {0: "O", 1: "O"}),
        ("[H][H]", {0: "H", 1: "H"}),
        ("ClCl", {0: "Cl", 1: "Cl"}),
        ("C#N", {0: "HC", 1: "N"}),  # HC≡N, its hydrogen on the left
        ("CBr", {0: "H3C", 1: "Br"}),
    ],
)
def test_a_lone_two_atom_molecule_lies_flat_first_atom_on_the_left(
    smiles: str, written: dict[int, str]
) -> None:
    drawn = _drawn(smiles)
    assert _written(drawn) == written
    assert _flat(drawn)
    assert drawn.atoms[0].point[0] < drawn.atoms[1].point[0]


def test_a_lone_straight_molecule_is_turned_as_its_place_says() -> None:
    from flexo.mechanism import mechanism_states

    for smiles, number in (("O=O", 1), ("O=C=O", 2)):
        steps = [{"smiles": smiles, "arrow": "none", "place": {number: {"turn": 30}}}]
        panels, problem = mechanism_states(_mechanism(steps)[0].spec.nodes[0])
        assert problem is None
        first, last = panels[0].molecule.atoms[0], panels[0].molecule.atoms[-1]
        angle = math.degrees(math.atan2(last.y - first.y, last.x - first.x))
        assert angle == pytest.approx(30.0)  # turned clockwise from flat, y down


def test_a_straight_molecule_beside_others_in_its_step_keeps_the_grid() -> None:
    from flexo.mechanism import mechanism_states

    # X- comes in along Y-Z's line: laid flat, the three would stand in a row, the arrow
    # squeezed between their letters. Alone, Y-Z lies flat.
    for smiles, flat in (("[X-:1].[Y:2][Z:3]", False), ("[Y:2][Z:3]", True)):
        steps = [{"smiles": smiles, "arrow": "none"}]
        panels, _ = mechanism_states(_mechanism(steps)[0].spec.nodes[0])
        molecule = panels[0].molecule
        y, z = (molecule.atoms[molecule.index_of(number)] for number in (2, 3))
        assert (abs(y.y - z.y) < 1e-6) is flat, smiles


def test_hydroxide_adding_to_carbon_dioxide_points_at_its_written_carbon() -> None:
    from flexo.chemistry.curly import HEAD_GAP
    from flexo.mechanism import mechanism_composed

    steps = [{"smiles": "[OH-:1].[O:2]=[C:3]=[O:4]", "arrows": "1 -> 3; 3=4 -> 4"}]
    figure, _ = _mechanism(steps)
    composed = mechanism_composed(figure.spec.nodes[0], STYLES["paper"])
    drawn, molecule, _ = composed.drawn[0]
    o2, c3, o4 = (molecule.index_of(number) for number in (2, 3, 4))
    lettered = {words.id: "".join(run.text for run in words.runs) for words in drawn.words}
    assert lettered[f"m.step1.atom{c3}"] == "C"
    # Beside the hydroxide CO2 keeps the grid, still straight through its written carbon.
    (x2, y2), (x3, y3), (x4, y4) = (drawn.atoms[atom].point for atom in (o2, c3, o4))
    assert (x3 - x2) * (y4 - y3) - (y3 - y2) * (x4 - x3) == pytest.approx(0.0, abs=1e-6)
    for number, target in ((0, c3), (1, o4)):
        (arrow,) = [shape for shape in drawn.shapes if shape.id == f"m.step1.arrow{number}"]
        tip = tuple(_numbers(arrow.d)[8:10])
        nearest = min(drawn.atoms, key=lambda atom: math.dist(tip, drawn.atoms[atom].point))
        assert nearest == target
        x, y = tip
        x0, y0, x1, y1 = drawn.atoms[target].ink[0]
        off = math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
        assert HEAD_GAP * composed.pen.bond <= off <= 2.5 * HEAD_GAP * composed.pen.bond
    # What the arrows make is bicarbonate, its carbon a vertex again.
    made, after, _ = composed.drawn[1]
    assert not any(words.id == f"m.step2.atom{after.index_of(3)}" for words in made.words)
