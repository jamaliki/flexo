from __future__ import annotations

import pytest
import yaml

from flexo.diagnostics import FlexoError
from flexo.serialization import dump_figure, figure_to_document, parse_figure
from flexo.units import CellSpan, Length


def document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "figure": {"id": "pipeline", "width": "single-column", "root": "root"},
        "nodes": [
            {"id": "input", "kind": "feature-strip", "label": "Features"},
            {"id": "projection", "kind": "mlp", "label": "Projection"},
        ],
        "edges": [
            {"id": "input-to-projection", "from": "input.output", "to": "projection.input"}
        ],
        "groups": [
            {
                "id": "root",
                "children": ["input", "projection"],
                "layout": {"kind": "row", "justify": "center"},
            }
        ],
    }


def test_parse_normalizes_component_ports() -> None:
    figure = parse_figure(document())
    assert {port.name for port in figure.node("projection").ports} == {"input", "output"}


def test_unknown_port_lists_valid_alternatives() -> None:
    value = document()
    value["edges"][0]["to"] = "projection.in"  # type: ignore[index]
    with pytest.raises(
        FlexoError,
        match=r"Valid ports: projection\.input, projection\.output",
    ):
        parse_figure(value)


def test_asymmetric_spacing_and_grid_placement_round_trip() -> None:
    value = document()
    value["groups"][0]["layout"] = {  # type: ignore[index]
        "kind": "grid",
        "columns": 3,
        "gap": "10pt",
        "row_gap": "22pt",
        "column_gap": "6pt",
        "padding_top": "14pt",
        "padding_right": "5pt",
        "padding_bottom": "14pt",
        "padding_left": "5pt",
        "placements": [{"child": "projection", "row": 1, "column": 2}],
        "column_widths": [{"column": 1, "width": "50pt"}],
    }
    value["nodes"][1]["height"] = "cells:3"  # type: ignore[index]
    figure = parse_figure(value)
    layout = figure.group("root").layout
    assert (layout.row_gap, layout.column_gap) == (Length(22.0), Length(6.0))
    assert (layout.padding_top, layout.padding_left) == (Length(14.0), Length(5.0))
    assert layout.placements == (("projection", 1, 2),)
    assert layout.column_widths == ((1, Length(50.0)),)
    assert figure.node("projection").height == CellSpan(3)
    assert parse_figure(yaml.safe_load(dump_figure(figure))) == figure


def test_unset_options_stay_out_of_the_document() -> None:
    figure = parse_figure(document())
    layout = figure_to_document(figure)["groups"][0]["layout"]  # type: ignore[index]
    assert set(layout) == {"kind", "justify"}


def test_title_side_and_node_paint_round_trip() -> None:
    value = document()
    value["groups"][0]["title_side"] = "right"  # type: ignore[index]
    value["groups"][0]["label"] = "Attention module"  # type: ignore[index]
    value["nodes"][1]["properties"] = {  # type: ignore[index]
        "motif": False,
        "paint-fill": "#085041",
        "paint-label": "#9fe1cb",
    }
    figure = parse_figure(value)
    assert figure.group("root").title_side == "right"
    projection = figure.node("projection")
    assert projection.property("paint-label") == "#9fe1cb"
    assert projection.property("motif") is False
    reparsed = parse_figure(yaml.safe_load(dump_figure(figure)))
    assert reparsed == figure
    assert figure_to_document(figure)["groups"][0]["title_side"] == "right"  # type: ignore[index]


def test_a_left_title_stays_out_of_the_document() -> None:
    figure = parse_figure(document())
    assert "title_side" not in figure_to_document(figure)["groups"][0]  # type: ignore[operator]
    with pytest.raises(FlexoError, match="title_side"):
        bad = document()
        bad["groups"][0]["title_side"] = "top"  # type: ignore[index]
        parse_figure(bad)


def _net_document() -> dict[str, object]:
    value = document()
    value["nodes"].append({"id": "residual", "kind": "block", "label": "Residual"})  # type: ignore[attr-defined]
    value["edges"] = []
    value["groups"][0]["children"] = ["input", "projection", "residual"]  # type: ignore[index]
    value["nets"] = [
        {
            "id": "combined",
            "kind": "merge",
            "sources": ["input.output", "residual.output"],
            "targets": ["projection.input"],
            "rail_at": 0.55,
            "joint": "arrow",
        }
    ]
    return value


def test_net_rail_placement_and_joint_round_trip() -> None:
    figure = parse_figure(_net_document())
    (net,) = figure.nets
    assert (net.rail_at, net.joint) == (0.55, "arrow")
    assert parse_figure(yaml.safe_load(dump_figure(figure))) == figure
    assert figure_to_document(figure)["nets"][0]["rail_at"] == 0.55  # type: ignore[index]


def test_default_net_placement_stays_out_of_the_document() -> None:
    value = _net_document()
    del value["nets"][0]["rail_at"]  # type: ignore[index]
    del value["nets"][0]["joint"]  # type: ignore[index]
    figure = parse_figure(value)
    written = figure_to_document(figure)["nets"][0]  # type: ignore[index]
    assert "rail_at" not in written and "joint" not in written  # type: ignore[operator]


def test_a_rail_side_and_a_rail_fraction_cannot_be_written_together() -> None:
    value = _net_document()
    value["nets"][0]["rail"] = "north"  # type: ignore[index]
    with pytest.raises(FlexoError, match="schema"):
        parse_figure(value)


def test_a_fan_out_may_not_ask_for_an_arrow_joint() -> None:
    value = _net_document()
    value["nets"][0]["kind"] = "fan-out"  # type: ignore[index]
    value["nets"][0]["sources"] = ["input.output"]  # type: ignore[index]
    value["nets"][0]["targets"] = ["projection.input", "residual.input"]  # type: ignore[index]
    with pytest.raises(FlexoError, match="schema"):
        parse_figure(value)
