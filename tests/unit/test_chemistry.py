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
        ("[Xx]", '"Xx" is not an element'),
        ("", "The SMILES is empty"),
    ],
)
def test_smiles_that_cannot_be_read_is_said_in_words(smiles: str, said: str) -> None:
    with pytest.raises(SmilesError, match=re.escape(said)):
        read_smiles(smiles)


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
    from flexo.chemistry.curly import _bends_both_ways, _crossing

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
        assert not _bends_both_ways(curve), shape.id
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
    return draw_molecule(molecule, Pen(measures.u, lambda runs: measures.measure(runs)),
                         prefix="m", pairs="all")


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
