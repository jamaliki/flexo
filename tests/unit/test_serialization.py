from __future__ import annotations

import pytest
import yaml

from flexo.diagnostics import FlexoError
from flexo.geometry import Side
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec, PortSpec, TextRun
from flexo.serialization import dump_figure, figure_to_document, parse_figure
from flexo.units import CellSpan, Length
from flexo.validate import normalize_and_validate


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


def test_group_paint_round_trips_and_stays_out_when_unset() -> None:
    value = document()
    value["groups"][0]["label"] = "Attention module"  # type: ignore[index]
    value["groups"][0]["paint"] = {  # type: ignore[index]
        "label": "#9fe1cb",
        "fill": "#085041",
    }
    figure = parse_figure(value)
    assert figure.group("root").paint == (("fill", "#085041"), ("label", "#9fe1cb"))
    assert parse_figure(yaml.safe_load(dump_figure(figure))) == figure
    assert figure_to_document(figure)["groups"][0]["paint"] == {  # type: ignore[index]
        "fill": "#085041",
        "label": "#9fe1cb",
    }
    assert "paint" not in figure_to_document(parse_figure(document()))["groups"][0]  # type: ignore[operator]


def test_a_group_may_only_paint_the_parts_it_has() -> None:
    for paint in ({"title": "#9fe1cb"}, {"fill": "teal"}):
        bad = document()
        bad["groups"][0]["paint"] = paint  # type: ignore[index]
        with pytest.raises(FlexoError, match="paint"):
            parse_figure(bad)


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


def test_a_documents_ports_round_trip_as_pinned_or_defaulted() -> None:
    """Whether a side was the author's choice survives the document.

    Default ports are omitted from the document and restored from the component
    grammar, so they come back free to pick a side. An authored table is written
    out in full and comes back pinned -- the same figure, and the same picture.
    """

    figure = FigureSpec(
        "ports",
        nodes=(
            NodeSpec("defaulted", "block"),
            NodeSpec(
                "authored",
                "block",
                ports=(PortSpec("input", Side.WEST, adaptive=True),),
            ),
        ),
        groups=(GroupSpec("root", ("defaulted", "authored")),),
    )
    document = yaml.safe_load(dump_figure(normalize_and_validate(figure)))
    assert "ports" not in document["nodes"][0]
    restored = parse_figure(document)
    assert all(port.auto_side for port in restored.node("defaulted").ports)
    assert not any(port.auto_side for port in restored.node("authored").ports)


def test_ports_alignment_anchor_and_shadow_survive_a_round_trip() -> None:
    """R24's three new fields are interchange, not just Python."""

    figure = FigureSpec(
        "aligned",
        nodes=(
            NodeSpec("cells", "vector"),
            NodeSpec("caption", "label", role="label"),
            NodeSpec("lit", "block", shadow=True),
        ),
        groups=(
            GroupSpec("root", ("glyph", "lit"), LayoutSpec("row", align="ports"), shadow=True),
            GroupSpec(
                "glyph",
                ("cells", "caption"),
                LayoutSpec("column"),
                role="layout",
                anchor="cells",
            ),
        ),
    )
    document = figure_to_document(figure)
    layout = document["groups"][0]["layout"]  # type: ignore[index]
    assert layout["align"] == "ports"
    assert document["groups"][0]["shadow"] is True  # type: ignore[index]
    assert document["groups"][1]["anchor"] == "cells"  # type: ignore[index]
    assert document["nodes"][2]["shadow"] is True  # type: ignore[index]
    restored = parse_figure(document)
    assert restored.group("root").layout.align == "ports"
    assert restored.group("root").shadow is True
    assert restored.group("glyph").anchor == "cells"
    assert restored.node("lit").shadow is True


def test_the_defaults_of_the_new_fields_stay_out_of_the_document() -> None:
    """A figure that asks for none of them serializes exactly as it did before."""

    document = figure_to_document(
        FigureSpec(
            "plain",
            nodes=(NodeSpec("only", "block"),),
            groups=(GroupSpec("root", ("only",), LayoutSpec("row")),),
        )
    )
    assert "shadow" not in document["nodes"][0]  # type: ignore[operator]
    assert "shadow" not in document["groups"][0]  # type: ignore[operator]
    assert "anchor" not in document["groups"][0]  # type: ignore[operator]


def test_a_via_hint_round_trips_on_an_edge_and_on_a_net() -> None:
    """R27: one word about a corridor, written down and read back."""

    value = _net_document()
    del value["nets"][0]["rail_at"]  # type: ignore[index]
    del value["nets"][0]["joint"]  # type: ignore[index]
    value["nets"][0]["via"] = "west"  # type: ignore[index]
    value["edges"] = [
        {
            "id": "input-to-projection",
            "from": "input.output",
            "to": "projection.input",
            "via": "south",
        }
    ]
    figure = parse_figure(value)
    assert figure.nets[0].via is Side.WEST
    assert figure.edges[0].via is Side.SOUTH
    assert parse_figure(yaml.safe_load(dump_figure(figure))) == figure
    written = figure_to_document(figure)
    assert written["nets"][0]["via"] == "west"  # type: ignore[index]
    assert written["edges"][0]["via"] == "south"  # type: ignore[index]


def test_no_via_hint_stays_out_of_the_document() -> None:
    figure = parse_figure(document())
    assert "via" not in figure_to_document(figure)["edges"][0]  # type: ignore[operator]


def test_a_via_side_cannot_be_written_beside_a_rail_or_a_fraction() -> None:
    for placement in ({"rail": "north"}, {"rail_at": 0.4}):
        value = _net_document()
        del value["nets"][0]["rail_at"]  # type: ignore[index]
        value["nets"][0].update({"via": "west", **placement})  # type: ignore[index]
        with pytest.raises(FlexoError, match="schema"):
            parse_figure(value)


def test_a_typed_superscript_stays_the_string_its_author_wrote() -> None:
    """R36: the translation is downstream of the spec, so YAML never sees it.

    ``softmax(QKᵀ)V`` becomes three baseline-shifted runs when it is measured
    and painted, and *only* then. Canonicalizing it into the ``FigureSpec``
    would rewrite a one-line ``label:`` into a three-entry run list the author
    never wrote, and would make the document depend on which characters the
    bundled face happens to carry -- so the spec keeps the characters, the
    document keeps the plain scalar, and a round trip is a no-op.
    """

    value = document()
    value["nodes"][1]["label"] = "softmax(QKᵀ)V"  # type: ignore[index]
    value["edges"][0]["label"] = "xₖ"  # type: ignore[index]
    value["groups"][0]["label"] = "QKᵀ-attention"  # type: ignore[index]
    figure = parse_figure(value)
    assert figure.node("projection").label == (TextRun("softmax(QKᵀ)V"),)
    assert figure.node("projection").text == "softmax(QKᵀ)V"
    emitted = figure_to_document(figure)
    assert emitted["nodes"][1]["label"] == "softmax(QKᵀ)V"  # type: ignore[index]
    assert emitted["edges"][0]["label"] == "xₖ"  # type: ignore[index]
    assert emitted["groups"][0]["label"] == "QKᵀ-attention"  # type: ignore[index]
    rendered = dump_figure(figure)
    assert "softmax(QKᵀ)V" in rendered, "written out as typed, not escaped"
    reparsed = parse_figure(yaml.safe_load(rendered))
    assert reparsed == figure
    assert dump_figure(reparsed) == rendered


def test_a_hand_built_superscript_still_round_trips_as_runs() -> None:
    """Typing ``ᵀ`` is a second spelling, not a replacement for the first."""

    value = document()
    value["nodes"][1]["label"] = [  # type: ignore[index]
        {"text": "softmax(QK"},
        {"text": "T", "baseline_shift": "super"},
        {"text": ")V"},
    ]
    figure = parse_figure(value)
    assert figure.node("projection").label == (
        TextRun("softmax(QK"),
        TextRun("T", baseline_shift="super"),
        TextRun(")V"),
    )
    assert parse_figure(yaml.safe_load(dump_figure(figure))) == figure
