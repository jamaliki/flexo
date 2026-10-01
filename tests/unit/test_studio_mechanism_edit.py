"""Drawing a mechanism's arrows by pointing: what two clicks write, and the sheet drawn on."""

from __future__ import annotations

import math

import pytest

from flexo.studio.figure_edit import EditError
from flexo.studio.mechanism_edit import add_arrow, remove_arrow, sheet

SN2 = "[OH-:1].[CH3:2][Br:3]"


def test_a_half_drawn_step_is_drawn_on_and_what_is_wrong_said() -> None:
    drawn = sheet([{"smiles": SN2, "arrows": ["1 -> 2"]}], step=0)
    assert drawn["svg"].startswith("<?xml") and "viewBox" in drawn["svg"]
    assert drawn["problem"]["code"] == "mechanism.arrows"
    assert "C2 would have 10 electrons" in drawn["problem"]["message"]
    assert drawn["arrows"] == [{"text": "1 -> 2", "said": "lone pair on O1 → C2"}]
    assert drawn["named"] == [0, 1] and drawn["states"] == 1
    oxygen = next(atom for atom in drawn["atoms"] if atom["name"] == "O1")
    assert oxygen["number"] == 1 and len(oxygen["pairs"]) == 3  # hydroxide's three lone pairs
    x, y, width, height = drawn["view"]
    assert all(
        x <= atom["x"] <= x + width and y <= atom["y"] <= y + height for atom in drawn["atoms"]
    )
    assert {tuple(bond["atoms"]) for bond in drawn["bonds"]} == {(1, 2)}


def test_two_clicks_write_an_arrow_and_a_bond_to_a_far_atom_asks_which_end() -> None:
    steps = [{"smiles": SN2}]
    made = add_arrow(steps, step=0, tail={"atom": 0}, head={"atom": 1})
    assert made["arrow"] == "1 -> 2" and made["steps"][0]["arrows"] == ["1 -> 2"]
    made = add_arrow(made["steps"], step=0, tail={"bond": [1, 2]}, head={"atom": 2})
    assert made["arrow"] == "2-3 -> 3"
    assert add_arrow(steps, step=0, tail={"bond": [1, 2]}, head={"atom": 0}) == {
        "ends": [{"index": 1, "name": "C2"}, {"index": 2, "name": "Br3"}]
    }
    asked = add_arrow(steps, step=0, tail={"bond": [1, 2]}, head={"bond": [1, 0]})
    assert asked["arrow"] == "2-3 -> 2-1"
    half = add_arrow(
        [{"smiles": "[Br:1][Br:2]"}], step=0, tail={"bond": [0, 1]}, head={"atom": 0}, half=True
    )
    assert half["arrow"] == "1-2 ~> 1"
    with pytest.raises(EditError, match="drawn already"):
        add_arrow([{"smiles": SN2, "arrows": "1 -> 2"}], step=0, tail={"atom": 0}, head={"atom": 1})
    with pytest.raises(EditError, match="makes a bond to an atom"):
        add_arrow(steps, step=0, tail={"atom": 0}, head={"bond": [1, 2]})
    left = remove_arrow([{"smiles": SN2, "arrows": "1 -> 2; 2-3 -> 3"}], step=0, index=0)
    assert left["steps"][0]["arrows"] == ["2-3 -> 3"]


def test_an_atom_without_a_number_is_given_one_where_its_smiles_is_written() -> None:
    made = add_arrow([{"smiles": "[OH-:1].CBr"}], step=0, tail={"atom": 0}, head={"atom": 1})
    assert made["steps"][0]["smiles"] == "[OH-:1].[CH3:2]Br" and made["arrow"] == "1 -> 2"
    # A molecule with no numbers at all calls its atoms by their places: nothing is written.
    plain = add_arrow([{"smiles": "CBr.[OH-]"}], step=0, tail={"atom": 2}, head={"atom": 0})
    assert plain["steps"][0]["smiles"] == "CBr.[OH-]" and plain["arrow"] == "3 -> 1"
    # The structure the last step makes takes arrows as a new step.
    after = add_arrow(
        [{"smiles": SN2, "arrows": "1 -> 2; 2-3 -> 3"}], step=1, tail={"atom": 2}, head={"atom": 1}
    )
    assert after["steps"][1] == {"arrows": ["3 -> 2"]}


def test_a_step_drawn_on_holds_still() -> None:
    def shape(drawn):
        first = drawn["atoms"][0]
        return [
            (round(atom["x"] - first["x"], 1), round(atom["y"] - first["y"], 1))
            for atom in drawn["atoms"]
        ]

    before = sheet([{"smiles": SN2}], step=0, holding=[])
    held = sheet([{"smiles": SN2, "arrows": "1 -> 2; 2-3 -> 3"}], step=0, holding=[])
    tidied = sheet([{"smiles": SN2, "arrows": "1 -> 2; 2-3 -> 3"}], step=0)
    assert shape(held) == shape(before)
    assert shape(tidied) != shape(before)  # laid out for its arrows: the hydroxide faces the carbon
    oxygen, carbon = (
        next(a for a in tidied["atoms"] if a["name"] == name) for name in ("O1", "C2")
    )
    assert math.dist((oxygen["x"], oxygen["y"]), (carbon["x"], carbon["y"])) < 3 * tidied["bond"]


def test_a_molecule_is_moved_turned_flipped_and_put_back_where_it_is_seen() -> None:
    from flexo.studio.mechanism_edit import place_molecule

    steps = [{"smiles": SN2, "arrows": ["1 -> 2", "2-3 -> 3"]}]
    moved = place_molecule(steps, step=0, atom=0, move=[-1, 0.5])["steps"]
    moved = place_molecule(moved, step=0, atom=0, move=[0.25, 0])["steps"]
    assert moved[0]["place"] == {"1": {"move": [-0.75, 0.5]}}
    turned = place_molecule(moved, step=0, atom=2, turn=30)["steps"]  # the C2-Br3 molecule, by C2
    assert turned[0]["place"]["2"] == {"turn": 30.0}
    # Flipped as it is seen: the turn it had now turns the other way.
    flipped = place_molecule(turned, step=0, atom=1, flip=True)["steps"]
    assert flipped[0]["place"]["2"] == {"turn": -30.0, "flip": True}
    back = place_molecule(flipped, step=0, atom=1, reset=True)["steps"]
    assert back[0]["place"] == {"1": {"move": [-0.75, 0.5]}}
    # What the last step makes is placed as a step of its own, with no arrows.
    after = place_molecule(steps, step=1, atom=2, move=[1, 0])["steps"]
    assert after[1] == {"arrows": [], "place": {"3": {"move": [1.0, 0.0]}}}
    drawn = sheet(back, step=0)
    assert drawn["paper"].startswith("#")
    assert [molecule["placed"] for molecule in drawn["molecules"]] == [True, False]
    assert "m.step1.bond0" in drawn["molecules"][1]["ids"]
