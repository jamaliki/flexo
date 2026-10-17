"""A structure's colours: rows that are chains, residues, ligands or selections, a later row
over an earlier one, and a molecule coloured by another's secondary structure."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

import flexo
from flexo.structures import structure_problem
from flexo.themes import figure_palette, figure_style


def _molecule(path: Path, *, helix: tuple[int, int] | None = None,
              strand: tuple[int, int] | None = None) -> Path:
    """A small molecule written as PDB: chain A of eight residues (a histidine at 5), chain B
    of three, the ligand 1PE at 401 -- its code starting with a digit, as many do -- and a
    water; with ``helix`` and ``strand``, the residues of A its HELIX and SHEET records say."""

    def line(serial: int, name: str, resn: str, chain: str, resi: int,
             at: tuple[float, float, float], element: str, het: bool = False) -> str:
        x, y, z = at
        return (f"{'HETATM' if het else 'ATOM':<6}{serial:>5} {name:<4} {resn:>3} {chain}{resi:>4}"
                f"    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 10.00          {element:>2}  ")

    lines = []
    if helix:
        lines.append(f"HELIX    1   1 ALA A {helix[0]:>4}  ALA A {helix[1]:>4}  1")
    if strand:
        lines.append(f"SHEET    1   A 2 ALA A{strand[0]:>4}  ALA A{strand[1]:>4}  0")
    serial = 0
    chains = (("A", ("ALA", "GLY", "SER", "LEU", "HIS", "VAL", "ALA", "LYS"), 0.0),
              ("B", ("GLY", "SER", "ALA"), 20.0))
    for chain, names, shift in chains:
        for index, resn in enumerate(names):
            turn = math.radians(100.0 * index)
            middle = (2.3 * math.cos(turn) + shift, 2.3 * math.sin(turn), 1.5 * index)
            for name, (dx, dy, dz) in (("N", (-0.6, 0.6, -0.5)), ("CA", (0.0, 0.0, 0.0)),
                                       ("C", (0.6, -0.6, 0.5)), ("O", (1.2, -0.6, 1.2))):
                serial += 1
                at = (middle[0] + dx, middle[1] + dy, middle[2] + dz)
                lines.append(line(serial, f" {name}", resn, chain, index + 1, at, name[0]))
    for name, at in ((" C1", (6.0, 6.0, 4.0)), (" O1", (7.2, 6.0, 4.0)), (" C2", (8.4, 6.0, 4.0))):
        serial += 1
        lines.append(line(serial, name, "1PE", "A", 401, at, name[1], het=True))
    lines.append(line(serial + 1, " O", "HOH", "A", 501, (-6.0, -6.0, 0.0), "O", het=True))
    path.write_text("\n".join([*lines, "END", ""]), encoding="utf-8")
    return path


def _structure(source: Path, **properties):
    with flexo.Figure("coloured") as figure:
        figure.root.structure("model", source, look="flat", **properties)
    return figure.spec


def _handed(spec) -> dict[str, str]:
    """The colours mol-sketch is handed for the structure, by its names for groups."""

    from flexo import structures

    node = spec.nodes[0]
    ask = structures._ask(node, figure_style(spec), figure_palette(spec))
    figure = structures._one_at_a_time(structures._drawn, ask)
    return dict(figure._colors or {})


def _shown(handed: dict[str, str], key: str) -> str | None:
    """The colour a residue (``SER195.A``) is drawn in, as mol-sketch finds it: its own, else
    its chain's."""

    return handed.get(key) or handed.get(key.partition(".")[2])


def test_a_ligand_whose_code_starts_with_a_digit_is_coloured_not_taken_for_a_chain(
    tmp_path: Path,
) -> None:
    """``6V0401`` -- the ligand 6V0 at 401 -- was read as a chain, as a residue's name had to
    start with letters: said to name no chain, its colour was dropped. A group is looked for
    among the residues and chains the file has."""

    pytest.importorskip("molsketch")
    source = _molecule(tmp_path / "bound.pdb")
    spec = _structure(source, colors={"A": "#86cfc4", "1PE401": "#2f4a5a", "his5": "#d55e00"})
    assert structure_problem(spec.nodes[0], figure_style(spec)) is None
    handed = _handed(spec)
    assert handed["A"] == "#86cfc4"
    assert handed["1PE401.A"] == "#2f4a5a"
    # (A residue's name in any case, as a chain's is not.)
    assert handed["HIS5.A"] == "#d55e00"


def test_a_row_may_be_a_selection_of_residues(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    source = _molecule(tmp_path / "bound.pdb")
    spec = _structure(source, colors={
        "resi 2-3": "#111111",
        "chain B and resi 1+3": "#222222",
        "resn HIS": "#333333",
        "not polymer": "#444444",
    })
    assert structure_problem(spec.nodes[0], figure_style(spec)) is None
    handed = _handed(spec)
    # resi 2-3 is in both chains.
    for key in ("GLY2.A", "SER3.A", "SER2.B"):
        assert _shown(handed, key) == "#111111"
    assert _shown(handed, "GLY1.B") == _shown(handed, "ALA3.B") == "#222222"
    assert _shown(handed, "HIS5.A") == "#333333"
    # A ligand and a water: what is not the polymer.
    assert _shown(handed, "1PE401.A") == _shown(handed, "HOH501.A") == "#444444"
    assert _shown(handed, "LEU4.A") is None and _shown(handed, "ALA1.A") is None


def test_a_later_row_wins_over_an_earlier_one(tmp_path: Path) -> None:
    """As the last colour given in PyMOL is the one drawn: a chain and then a residue in it is
    the chain's colour but for the residue; the residue and then its chain, the chain's
    throughout -- mol-sketch's own rule (the narrowest wins) is not the rows'."""

    pytest.importorskip("molsketch")
    source = _molecule(tmp_path / "bound.pdb")
    first = _handed(_structure(source, colors={"A": "#aa0000", "resi 5": "#0000aa"}))
    assert first["A"] == "#aa0000" and first["HIS5.A"] == "#0000aa"
    second = _handed(_structure(source, colors={"resi 5": "#0000aa", "A": "#aa0000"}))
    assert second == {"A": "#aa0000"}
    # (A chain coloured all but for a few is handed over as one, and the few by theirs.)
    assert len(first) == 2


def test_a_row_that_colours_nothing_is_said_and_the_rest_drawn(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.studio.figure_kind import FigureKind

    source = _molecule(tmp_path / "bound.pdb")
    said = {}
    for group in ("C", "SER99", "resi 40-50", "resn TRP", "resi ten", "entity:3", "spam eggs"):
        spec = _structure(source, colors={"A": "#86cfc4", group: "#2f4a5a"})
        problem = structure_problem(spec.nodes[0], figure_style(spec))
        assert problem is not None and problem.code == "structure.colors"
        said[group] = (problem.message, problem.hint or "")
        assert _handed(spec) == {"A": "#86cfc4"}
    assert said["C"][0] == '"C" names no chain of bound, so its colour would show nowhere.'
    assert "Its chains are A, B" in said["C"][1]
    assert said["SER99"][0].startswith('"SER99" names no residue of bound')
    assert "numbered 1 to 8" in said["SER99"][1] and "1PE401" in said["SER99"][1]
    assert said["resi 40-50"][0] == (
        '"resi 40-50" selects nothing in bound, so its colour would show nowhere.'
    )
    assert "numbered 1 to 8" in said["resi 40-50"][1]
    assert "1PE401" in said["resn TRP"][1]
    assert "isn't a residue number" in said["resi ten"][0]
    assert said["entity:3"][0].startswith('"entity:3" names no entity of bound')
    assert "isn't a word selections use" in said["spam eggs"][0]
    # The studio says each row's: what it colours, or why nothing.
    text = (
        "figure: {id: rows}\nnodes:\n  - id: model\n    kind: structure\n"
        f"    properties: {{source: {source}, colors: [{{group: A, color: '#86cfc4'}},"
        " {group: 'resi 2-4', color: '#2f4a5a'}, {group: 'resi 40', color: '#2f4a5a'}]}\n"
    )
    settings = FigureKind().act(
        {"text": text}, {"do": "structure-settings", "id": "model"}, tmp_path
    )["settings"]
    groups = settings["colours"]["groups"]
    assert groups["A"] == {"residues": 10, "problem": "", "hint": ""}
    assert groups["resi 2-4"]["residues"] == 5 and not groups["resi 2-4"]["problem"]
    assert groups["resi 40"]["residues"] == 0 and "selects nothing" in groups["resi 40"]["problem"]
    assert settings["colours"]["ligands"] == [{"group": "1PE401", "label": "1PE 401"}]


def test_a_structure_is_coloured_by_another_files_secondary_structure(tmp_path: Path) -> None:
    """A diffusion run's frames, each coloured by the structure it ends as: each residue in
    the look's helix, strand or loop colour as the other file has it -- its HELIX and SHEET
    records, here -- the rows over it. A residue the frame draws as the other file has it is
    left to mol-sketch, which colours it so by the element it draws it in; only those drawn
    otherwise are handed a colour."""

    ms = pytest.importorskip("molsketch")
    frame = _molecule(tmp_path / "frame.pdb")
    end = _molecule(tmp_path / "end.pdb", helix=(2, 5), strand=(7, 8))
    flat = ms.load(str(frame)).look("flat").style["palette"]
    # The frame's own secondary structure, worked out from its coordinates: residues 1 to 6
    # a helix, the rest loops -- and it is drawn with that shape.
    from flexo.structure_colours import drawn_as, molecule

    drawn = drawn_as(ms.load(str(frame)).look("flat"))
    assert [drawn[("A", n)] for n in range(1, 9)] == ["H"] * 6 + ["L", "L"]
    residues = molecule(str(frame), frame.stat().st_mtime).residues
    own = {residue.key: residue.ss for residue in residues}
    assert own["ALA1.A"] == own["VAL6.A"] == "H" and own["ALA7.A"] != "E"
    # Drawn in a helix the end has as a loop (1 and 6), or as a loop the end has as a strand
    # (7 and 8): handed the end's colour. The helix it draws where the end has one (2 to 5),
    # and chain B, a loop in both: left to mol-sketch -- in the same colours -- as are the
    # ligand and the water.
    handed = _handed(_structure(frame, ss_from=end))
    assert handed == {"ALA1.A": flat["loop"], "VAL6.A": flat["loop"],
                      "ALA7.A": flat["sheet"], "LYS8.A": flat["sheet"]}
    # A row over it.
    over = _handed(_structure(frame, ss_from=end, colors={"resi 3": "#123456"}))
    assert over["SER3.A"] == "#123456" and over["ALA7.A"] == flat["sheet"]
    assert "GLY2.A" not in over
    # In the figure's colours, its strands are the warm fill.
    from flexo.themes import with_tone_roles

    spec = _structure(frame, ss_from=end, scheme="figure")
    assert _handed(spec)["ALA7.A"] == with_tone_roles(figure_palette(spec)).get("warm-fill")


def test_a_structure_coloured_by_its_own_file_is_drawn_as_its_cartoon_is(tmp_path: Path) -> None:
    """Coloured by its own secondary structure, a structure is handed no colour: drawn as a
    cartoon coloured by secondary structure is, a strand's arrowhead (on the residue after
    it) in the strand's colour, and the loop leaving from that residue in the loop's -- as a
    residue's colour, handed over, would paint both."""

    ms = pytest.importorskip("molsketch")
    # (Named as another test's end.pdb is, as long, with the same ends: read as its own.)
    end = _molecule(tmp_path / "end.pdb", helix=(2, 5), strand=(6, 7))
    assert _handed(_structure(end, ss_from=end)) == {}
    # With its cartoon coloured otherwise (rainbow), each residue is handed its colour.
    rainbow = _handed(_structure(end, ss_from=end, style={"cartoon_color": "rainbow"}))
    flat = ms.load(str(end)).look("flat").style["palette"]
    assert rainbow["GLY2.A"] == flat["helix"] and rainbow["VAL6.A"] == flat["sheet"]


def test_a_file_to_colour_by_that_cant_be_had_is_said(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    frame = _molecule(tmp_path / "frame.pdb")
    spec = _structure(frame, ss_from=tmp_path / "missing.pdb")
    problem = structure_problem(spec.nodes[0], figure_style(spec))
    assert problem is not None and problem.code == "structure.ss_from"
    assert problem.message.startswith("Couldn't find missing.pdb.")
    assert "coloured by its own secondary structure" in problem.message
    assert _handed(spec) == {}
    # One with none of its residues (by chain and number) colours nothing, said so.
    other = tmp_path / "other.pdb"
    other.write_text(frame.read_text().replace(" A   ", " Z   ").replace(" B   ", " Y   "))
    spec = _structure(frame, ss_from=other)
    problem = structure_problem(spec.nodes[0], figure_style(spec))
    assert problem is not None and "has none of frame's residues" in problem.message


def test_the_file_a_structure_is_coloured_by_is_found_beside_and_bundled(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.bundle import figure_references
    from flexo.studio.figure_kind import parse

    _molecule(tmp_path / "frame.pdb")
    _molecule(tmp_path / "end.pdb", helix=(2, 5))
    text = (
        "figure: {id: frames}\nnodes:\n  - id: model\n    kind: structure\n"
        "    properties: {source: frame.pdb, look: flat, ss_from: end.pdb}\n"
    )
    spec = parse(text, tmp_path)
    assert spec.nodes[0].property("ss_from") == str((tmp_path / "end.pdb").resolve())
    import yaml

    named = figure_references(yaml.safe_load(text), tmp_path)
    assert [(reference.name, reference.role) for reference in named] == [
        ("frame.pdb", "structure"), ("end.pdb", "structure")
    ]


def test_many_residues_are_handed_over_at_once(tmp_path: Path) -> None:
    """A large molecule coloured residue by residue (by another's secondary structure, say)
    is handed to mol-sketch all at once: one at a time, each would copy all before it."""

    from flexo.structure_colours import _hand

    class Figure:
        def __init__(self) -> None:
            self._colors = None
            self.calls = 0

        def color(self, group: str, colour: str) -> None:
            self.calls += 1
            self._colors = {**(self._colors or {}), group: colour}

    figure = Figure()
    _hand(figure, {f"ALA{index}.A": "#eeeeee" for index in range(20_000)})
    assert figure.calls == 1 and len(figure._colors) == 20_000
