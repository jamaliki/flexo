"""A grid of cells: symbols from text, a key, values on a ramp, and painting by hand."""

from __future__ import annotations

import re

import pytest

import flexo
from flexo.cells import cell_grid, cell_key, cells_drawing
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.themes import figure_style

GRID = """
    K . K
    . Y R
    K R .
"""
KEY = {"Y": {"color": "#f1bf24", "mark": "з", "label": "Yellow"}, "K": "#262422"}


def _figure(**options: object) -> flexo.Figure:
    with flexo.Figure("board") as figure:
        figure.cells("board", GRID, KEY, **options)
    return figure


def _node(figure):
    spec = getattr(figure, "spec", figure)
    return next(node for node in spec.nodes if node.kind == "cells")


def _svg(figure: flexo.Figure) -> str:
    return compile_figure(figure.spec).document.text


def test_the_grid_is_read_row_by_row_and_word_by_word() -> None:
    node = _node(_figure())
    assert cell_grid(node) == (("K", ".", "K"), (".", "Y", "R"), ("K", "R", "."))


def test_every_row_must_name_every_cell() -> None:
    with flexo.Figure("ragged") as figure:
        figure.cells("board", "K K K\nK K")
    with pytest.raises(FlexoError, match="Row 2 has 2 cells, and row 1 has 3"):
        compile_figure(figure.spec)


def test_a_keyed_colour_is_painted_exactly_and_an_unkeyed_symbol_takes_a_tone() -> None:
    node = _node(_figure())
    key = cell_key(node)
    assert key["Y"].color == "#f1bf24" and key["Y"].tone is None
    assert key["R"].color is None and key["R"].tone == "R"
    svg = _svg(_figure())
    yellow = re.search(r'<path[^>]*id="board\.r2c2"[^>]*>', svg).group(0)
    assert 'fill="#f1bf24"' in yellow
    # An exact colour carries no role, so retheming leaves it as written.
    assert "data-flexo-fill" not in yellow
    red = re.search(r'<path[^>]*id="board\.r2c3"[^>]*>', svg).group(0)
    assert 'data-flexo-fill="tone-' in red


def test_empty_cells_draw_nothing_and_marks_are_written_in_their_cells() -> None:
    drawing = cells_drawing(_node(_figure()), figure_style(_figure().spec))
    ids = {shape.id for shape in drawing.shapes}
    assert "board.r1c2" not in ids and "board.r1c1" in ids
    marks = [words for words in drawing.words if words.id.endswith(".mark")]
    assert [words.id for words in marks] == ["board.r2c2.mark"]
    assert "".join(run.text for run in marks[0].runs) == "з"


def test_a_labelled_symbol_has_a_legend_entry() -> None:
    drawing = cells_drawing(_node(_figure()), figure_style(_figure().spec))
    assert any(words.id == "board.legend1.label" for words in drawing.words)
    drawing = cells_drawing(_node(_figure(legend=False)), figure_style(_figure().spec))
    assert not any(".legend" in words.id for words in drawing.words)


def test_numbers_are_shaded_along_the_ramp_and_written_on_request() -> None:
    with flexo.Figure("heat") as figure:
        figure.cells(
            "heat", [[0.0, 0.5, 1.0], [-0.0, None, 1.0]], ramp=("#ffffff", "#000000"), values=True
        )
    node = _node(figure)
    assert cell_grid(node) == (("0", "0.5", "1"), ("-0", ".", "1"))
    drawing = cells_drawing(node, figure_style(figure.spec))
    colours = {shape.id: shape.color for shape in drawing.shapes}
    assert colours["heat.r1c1"] == "#ffffff"
    assert colours["heat.r1c3"] == "#000000"
    assert "heat.r2c2" not in colours
    written = {w.id: "".join(run.text for run in w.runs) for w in drawing.words}
    assert written["heat.r2c1.value"] == "0"  # never "-0"


def test_rows_and_columns_are_numbered_lettered_or_named() -> None:
    style = figure_style(_figure().spec)
    drawing = cells_drawing(
        _node(_figure(row_labels="letters", column_labels="one, two, three")), style
    )
    written = {w.id: "".join(run.text for run in w.runs) for w in drawing.words}
    assert written["board.row3"] == "C"
    assert written["board.column2"] == "two"
    with pytest.raises(FlexoError, match="column_labels names 2, and the grid has 3"):
        cells_drawing(_node(_figure(column_labels="one, two")), style)


def test_a_grid_goes_through_its_document_and_back() -> None:
    figure = _figure(lines="#2b4a9c", row_labels="numbers", row_side="right")
    document = figure_to_document(figure.spec)
    validate_document(document)
    again = parse_figure(document)
    assert _node(again) == _node(figure)
    assert compile_figure(again).document.text == _svg(figure)


def test_gouache_paints_small_cells_with_a_brush() -> None:
    with flexo.Figure("painted", theme="sketch", sketch={"fill": "gouache"}) as figure:
        figure.cells("board", GRID, KEY, cell=12)
    svg = _svg(figure)
    assert "board.r1c1" in svg
    assert re.search(r'id="[^"]*board\.r1c1[^"]*\.brush\d+"', svg)
    assert re.search(r'id="[^"]*board\.r1c1[^"]*\.gouache"', svg)


def test_the_editor_writes_a_new_grid_as_a_block_the_way_it_reads() -> None:
    from flexo.studio.figure_edit import apply

    text = apply("figure: {id: t}\nnodes: []\n", {"do": "add", "kind": "cells"})["text"]
    assert "grid: |\n      A B A B\n      B A B A\n" in text
    # What a file already quoted keeps its quotes.
    kept = 'figure: {id: t}\nnodes:\n- id: a\n  label: "one\\ntwo"\n'
    edited = apply(kept, {"do": "add", "kind": "block"})["text"]
    assert 'label: "one\\ntwo"' in edited
