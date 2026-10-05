"""What the figure editor offers: the parts of its palette and the fields of each."""

from __future__ import annotations

from flexo.serialization import parse_figure
from flexo.studio.figure_parts import RAMPS, catalogue
from flexo.style import RAMP_ROLES


def test_a_vector_is_a_part_of_the_palette_made_with_its_chips_and_steppers() -> None:
    """A cell stack, as in a model's diagram: three cells to start, coloured with the
    shapes' chips (its tone), its cells and columns set with steppers; the theme's ramps
    under More; its words under it."""

    part = catalogue()["parts"]["vector"]
    assert part["category"] == "Machine Learning"
    assert part["node"] == {"kind": "vector", "label": "Vector", "properties": {"cells": 3}}
    fields = {field["key"]: field for field in part["fields"]}
    assert set(fields) == {
        "label",
        "properties.tone",
        "properties.cells",
        "properties.columns",
        "properties.ramp",
    }
    assert fields["properties.cells"]["type"] == "integer"
    assert fields["properties.columns"]["type"] == "integer"
    assert fields["properties.ramp"]["more"] is True
    assert set(RAMPS) == set(RAMP_ROLES)
    assert set(fields["properties.ramp"]["options"]) == {"", *RAMP_ROLES}
    # Drawn at the size it is added at: taller than its cells, for its words.
    width, height = part["size"]
    assert 0 < width < height
    assert {"cells", "query", "key", "value"} <= set(part["words"])
    parse_figure({"figure": {"id": "f"}, "nodes": [{"id": "v", **part["node"]}]})


def test_a_grid_of_cells_says_how_to_write_its_ramp_and_hides_its_legend_at_once() -> None:
    fields = [field["key"] for field in catalogue()["parts"]["cells"]["fields"]]
    by_key = {field["key"]: field for field in catalogue()["parts"]["cells"]["fields"]}
    # One switch, beside the key it is the legend of.
    assert fields.index("properties.legend") == fields.index("properties.key") + 1
    assert by_key["properties.legend"]["label"] == "Legend"
    hint = by_key["properties.ramp"]["hint"]
    assert "space" in hint and "comma" in hint


def test_a_line_that_branches_has_fields_of_its_own() -> None:
    fields = {field["key"]: field for field in catalogue()["net_fields"]}
    assert set(fields) == {"label", "via", "line", "rail"}
    # The side lines gathered into one shape meet it on: a merge's alone.
    assert fields["via"]["show"] == {"kind": "merge"}
    assert fields["rail"]["labels"] == {
        "": "Automatic",
        "north": "Top",
        "east": "Right",
        "south": "Bottom",
        "west": "Left",
    }
