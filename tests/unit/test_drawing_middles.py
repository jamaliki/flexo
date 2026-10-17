"""A part drawn over a name or under one -- a named structure, picture or mechanism -- is met
by its lines, and lined up by a row that centres what it holds, at the middle of what it
draws, not of its box with the name in it (``flexo.title_sides``, ``MeasuredNode.drawn``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from flexo.builder import Figure
from flexo.compiler import Compilation, compile_figure
from flexo.title_sides import middle_y
from flexo.units import pt

_ART = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60" viewBox="0 0 80 60">'
    '<rect width="80" height="60" fill="#9cc"/></svg>'
)

OXYGEN = [{"smiles": "O=O", "arrow": "none", "label": "Oxygen"}]
WATER = [{"smiles": "O", "arrow": "none", "label": "Water"}]


def _art(tmp_path: Path) -> Path:
    target = tmp_path / "cell.svg"
    target.write_text(_ART, encoding="utf-8")
    return target


def _middles(compilation: Compilation, *ids: str) -> list[float]:
    return [middle_y(compilation.fitted.node(identifier)) for identifier in ids]


def test_a_named_mechanism_is_met_at_the_middle_of_its_structures_not_of_them_and_names() -> None:
    with Figure("reaction", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.row("row", align="center") as row:
            oxygen = row.mechanism("oxygen", OXYGEN)
            water = row.mechanism("water", WATER)
            row.connect(oxygen.output, water.input)
    compilation = compile_figure(figure.spec)
    node = compilation.fitted.node("row.oxygen")
    top, bottom = node.measured.drawn
    # Its structures, over the name under them.
    assert top == pytest.approx(0.0) and bottom < node.measured.intrinsic_size.height - 5.0
    middle = node.bounds.y + (top + bottom) / 2.0
    assert middle < node.bounds.center.y - 2.0
    assert node.port("output").position.y == pytest.approx(middle)
    assert node.measured.anchor.y == pytest.approx((top + bottom) / 2.0)
    # Its line runs from the middle of one's structure to the middle of the other's.
    line = compilation.routed.edges[0].centerline
    assert middle_y(compilation.fitted.node("row.water")) == pytest.approx(middle)
    assert [point.y for point in line] == pytest.approx([middle] * len(line))


def test_an_unnamed_mechanism_is_met_and_lined_up_by_its_box() -> None:
    with Figure("reaction", width=pt(320.0)) as figure:
        figure.root.mechanism("oxygen", [{"smiles": "O=O", "arrow": "none"}])
    node = compile_figure(figure.spec).fitted.node("oxygen")
    assert node.measured.drawn is None
    assert middle_y(node) == pytest.approx(node.bounds.center.y)


@pytest.mark.parametrize("kind", ["row", "grid"])
def test_a_plus_beside_named_molecules_stands_level_with_them_in_a_centred_row(
    kind: str,
) -> None:
    """The owner's "ACV + O2": the + and the line out of the oxygen at the middle of the
    molecules, not half a name's line under it."""

    with Figure("substrates", width=pt(400.0)) as figure:
        options = {"columns": 4} if kind == "grid" else {}
        with getattr(figure, kind)("row", align="center", **options) as row:
            row.mechanism("water", WATER)
            row.text("plus", label="+")
            row.mechanism("oxygen", OXYGEN)
            row.block("enzyme", label="Enzyme")
            row.connect("oxygen", "enzyme")
    compilation = compile_figure(figure.spec)
    ids = ("row.water", "row.plus", "row.oxygen", "row.enzyme")
    water, plus, oxygen, enzyme = _middles(compilation, *ids)
    assert plus == pytest.approx(water) and oxygen == pytest.approx(water)
    assert enzyme == pytest.approx(water)
    # (Not the middles of their boxes: the names hang under the molecules.)
    assert compilation.fitted.node("row.oxygen").bounds.center.y > oxygen + 2.0
    line = compilation.routed.edges[0].centerline
    assert [point.y for point in line] == pytest.approx([oxygen] * len(line))


def test_a_group_of_named_molecules_is_lined_up_by_its_molecules_in_a_centred_parent(
    tmp_path: Path,
) -> None:
    """A grid of a substrate, a + and another beside a picture with no name: the picture
    centred on the molecules' line, and the line into it level."""

    with Figure("engine", width=pt(500.0)) as figure:  # noqa: SIM117
        with figure.grid("engine", columns=2, align="center") as engine:
            with engine.grid("substrates", columns=3, align="center") as substrates:
                substrates.mechanism("water", WATER)
                substrates.text("plus", label="+")
                oxygen = substrates.mechanism("oxygen", OXYGEN)
            cell = engine.image("cell", _art(tmp_path), height="60pt")
            engine.connect(oxygen.output, cell.input)
    compilation = compile_figure(figure.spec)
    group = compilation.measured.group("engine.substrates")
    assert group.middle is not None
    water, plus, oxygen_middle, picture = _middles(
        compilation,
        "engine.substrates.water",
        "engine.substrates.plus",
        "engine.substrates.oxygen",
        "engine.cell",
    )
    assert plus == pytest.approx(water) and oxygen_middle == pytest.approx(water)
    assert picture == pytest.approx(water)
    line = compilation.routed.edges[0].centerline
    assert [point.y for point in line] == pytest.approx([water] * len(line))


def test_a_named_structure_and_picture_are_centred_on_their_drawings(tmp_path: Path) -> None:
    with Figure("row", width=pt(400.0)) as figure:  # noqa: SIM117
        with figure.row("row", align="center") as row:
            # (A file not there: its panel says so, named all the same.)
            row.structure("model", tmp_path / "missing.cif", label="Protein", width=60,
                          height=60, title_side="bottom")
            row.text("plus", label="+")
            row.image("art", _art(tmp_path), height="50pt", label="Cell")
    compilation = compile_figure(figure.spec)
    model, plus, art = _middles(compilation, "row.model", "row.plus", "row.art")
    assert plus == pytest.approx(model) and art == pytest.approx(model)


def test_rows_lined_up_by_their_ends_or_starts_are_as_they_were() -> None:
    for align, edge in (("end", "bottom"), ("start", "top")):
        with Figure("row", width=pt(400.0)) as figure:  # noqa: SIM117
            with figure.row("row", align=align) as row:
                row.mechanism("water", WATER)
                row.text("plus", label="+")
                row.mechanism("oxygen", OXYGEN)
        compilation = compile_figure(figure.spec)
        edges = {
            getattr(compilation.fitted.node(identifier).bounds, edge)
            for identifier in ("row.water", "row.plus", "row.oxygen")
        }
        assert max(edges) - min(edges) == pytest.approx(0.0), align


def test_a_centred_row_with_nothing_named_is_centred_on_its_boxes_as_ever() -> None:
    with Figure("row", width=pt(400.0)) as figure:  # noqa: SIM117
        with figure.row("row", align="center") as row:
            row.block("a", label="A")
            row.text("plus", label="+")
            row.block("b", label="Tall\nblock\nhere")
    compilation = compile_figure(figure.spec)
    centres = {
        round(compilation.fitted.node(identifier).bounds.center.y, 6)
        for identifier in ("row.a", "row.plus", "row.b")
    }
    assert len(centres) == 1
    assert compilation.measured.group("row").middle is None


def test_a_row_lined_up_by_its_port_lines_meets_a_named_molecule_at_its_molecule(
    tmp_path: Path,
) -> None:
    """A row whose parts are wired to one another lines them up by their port lines: a named
    structure's is its molecule's middle, so the block it feeds stands level with that."""

    with Figure("chain", width=pt(400.0)) as figure:  # noqa: SIM117
        with figure.row("row") as row:
            model = row.structure("model", tmp_path / "missing.cif", label="Protein",
                                  width=60, height=60, title_side="bottom")
            block = row.block("dock", label="Dock")
            row.connect(model.output, block.input)
    compilation = compile_figure(figure.spec)
    assert compilation.measured.semantic.group("row").layout.align == "ports"
    model_middle, block_middle = _middles(compilation, "row.model", "row.dock")
    assert block_middle == pytest.approx(model_middle)
    line = compilation.routed.edges[0].centerline
    assert [point.y for point in line] == pytest.approx([model_middle] * len(line))
