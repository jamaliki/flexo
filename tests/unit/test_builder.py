from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import yaml

from flexo.builder import Figure, NodeHandle
from flexo.compiler import Compilation, compile_figure
from flexo.gallery import modelangelo_gnn, vertical_slice
from flexo.geometry import Side
from flexo.ir.semantic import PortSpec, TextRun
from flexo.serialization import dump_figure, parse_figure
from flexo.style import STYLES
from flexo.units import pt


def test_builder_scopes_ids_and_connects_handles() -> None:
    with Figure("builder", width=pt(180)) as figure:  # noqa: SIM117
        with figure.module("encoder") as module:
            source = module.feature_strip("source", label="Features")
            target = module.mlp("target", input=source)
            assert isinstance(target, NodeHandle)
    semantic = figure.spec
    assert {node.id for node in semantic.nodes} == {"encoder.source", "encoder.target"}
    assert str(semantic.edges[0].source) == "encoder.source.output"
    assert str(semantic.edges[0].target) == "encoder.target.input"


def test_builder_round_trips_through_schema_document() -> None:
    original = vertical_slice()
    document = yaml.safe_load(dump_figure(original))
    parsed = parse_figure(document)
    assert parsed == original


def test_vertical_slice_compiles_without_coordinates() -> None:
    compiled = compile_figure(vertical_slice())
    assert len(compiled.routed.edges) == 11
    assert "cryo.residual" in compiled.document.text


def test_builder_authors_shared_fanout_and_merge_nets() -> None:
    with Figure("nets", width=pt(220)) as figure:
        with figure.module("flow") as module:
            source = module.node("source", ports=(PortSpec("out", Side.EAST),))
            first = module.node(
                "first",
                ports=(PortSpec("input", Side.WEST), PortSpec("out", Side.EAST)),
            )
            second = module.node(
                "second",
                ports=(PortSpec("input", Side.WEST), PortSpec("out", Side.EAST)),
            )
            target = module.node("target", ports=(PortSpec("input", Side.WEST),))
        figure.net(src=source.out, sinks=[first.input, second.input], id="shared")
        figure.merge(sinks=[first.out, second.out], dst=target.input, id="combined")
    assert [net.kind for net in figure.spec.nets] == ["fan-out", "merge"]
    assert tuple(map(str, figure.spec.nets[0].targets)) == (
        "flow.first.input",
        "flow.second.input",
    )
    assert tuple(map(str, figure.spec.nets[1].sources)) == (
        "flow.first.out",
        "flow.second.out",
    )
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))) == figure.spec


@pytest.fixture(scope="module")
def panel() -> Compilation:
    return compile_figure(modelangelo_gnn())


def test_panel_alternates_module_bands_with_addln_strips(panel: Compilation) -> None:
    """R11: every Add/LN owns a thin band between the modules it joins."""

    semantic = panel.measured.semantic
    assert semantic.group("root").children == (
        "band1",
        "strip1",
        "band2",
        "strip2",
        "band3",
        "strip3",
        "band4",
    )
    strips = ("strip1", "strip2", "strip3")
    for strip_id in strips:
        children = semantic.group(strip_id).children
        assert [semantic.node(child).kind for child in children] == ["spacer", "add-norm"]
    spines = [
        panel.fitted.node(semantic.group(strip_id).children[1]).bounds
        for strip_id in strips
    ]
    assert {spine.x for spine in spines} == {spines[0].x}
    assert {spine.width for spine in spines} == {spines[0].width}


def test_panel_feedback_rails_run_below_their_module(panel: Compilation) -> None:
    """R11: east out of the module's output vector, south past it, west along the strip."""

    strips = {"cryo": "strip1", "sequence": "strip2", "ipa": "strip3"}
    for module, strip_id in strips.items():
        edge = next(item for item in panel.routed.edges if item.spec.id == f"feedback.{module}")
        east, corner, turn, west = edge.centerline
        assert east.y == corner.y and corner.x > east.x, "leaves the MLP heading east"
        assert turn.x == corner.x and turn.y > corner.y, "drops south, never north"
        assert west.y == turn.y and west.x < turn.x, "runs west along the strip"
        module_bounds = panel.fitted.group(
            next(
                group.id
                for group in panel.measured.semantic.groups
                if group.role == "module" and group.id.endswith(f".{module}")
            )
        ).bounds
        assert corner.x > module_bounds.right, "the descent clears the module container"
        assert turn.y > module_bounds.bottom, "the west run is below the module"
        strip = panel.fitted.group(strip_id).bounds
        assert strip.top <= west.y <= strip.bottom, "the west run lies in the Add/LN strip"


def test_panel_canvas_ends_at_content_plus_one_margin(panel: Compilation) -> None:
    """R12: reserving the heads corridor must not pad the canvas edges."""

    margin = STYLES[panel.measured.semantic.style].group_padding.points
    root = panel.fitted.group("root")
    bands = [panel.fitted.group(child).bounds for child in root.measured.spec.children]
    content_bottom = max(band.bottom for band in bands)
    assert panel.fitted.canvas_size.height == pytest.approx(content_bottom + margin)
    assert min(band.top for band in bands) == pytest.approx(margin)
    assert min(band.left for band in bands) == pytest.approx(margin)


def test_panel_heads_rail_lands_between_the_last_addln_and_the_heads(
    panel: Compilation,
) -> None:
    """R12: the reserved corridor is where the fan-out rail goes."""

    fan_out = panel.routed.net("heads.fan-out")
    start, end = fan_out.rail
    assert start.y == end.y, "one horizontal rail"
    addln = panel.fitted.node("strip3.addln3").bounds
    heads = [panel.fitted.node(stem.port.node_id).bounds for stem in fan_out.target_stems]
    assert addln.bottom < start.y < min(head.top for head in heads)
    for stem in fan_out.target_stems:
        assert {point.x for point in stem.centerline} == {stem.centerline[0].x}


def test_panel_labels_attention_with_a_shifted_run_above_the_arrow(
    panel: Compilation,
) -> None:
    """R13/R20: the formula is a net label in styled runs, drawn with tspans."""

    assert not [node for node in panel.fitted.nodes if node.measured.spec.kind == "attention"]
    formulas = {
        "band1.cryo.attention": (("softmax(QK", "normal"), ("T", "super"), (")V", "normal")),
        "band2.sequence.attention": (
            ("softmax(QK", "normal"),
            ("T", "super"),
            (")V", "normal"),
        ),
        "band3.ipa.attention": (
            ("softmax(−ΣD", "normal"),  # noqa: RUF001
            ("q", "sub"),
            (")V", "normal"),
        ),
    }
    root = ET.fromstring(panel.document.text)
    by_id = {item.get("id"): item for item in root.iter() if item.get("id")}
    for net_id, runs in formulas.items():
        net = panel.routed.net(net_id)
        assert tuple((run.text, run.baseline_shift) for run in net.spec.label) == runs
        label = by_id[f"{net_id}.label"]
        spans = list(label)
        assert [span.text for span in spans] == [text for text, _ in runs]
        assert [span.get("baseline-shift") for span in spans] == [
            None if shift == "normal" else shift for _, shift in runs
        ]
        assert label.get("text-anchor") == "middle"


def test_panel_recycles_node_features_up_a_single_margin_rail(panel: Compilation) -> None:
    """R13: one west run, one climb west of the spine, one arrival."""

    edge = next(item for item in panel.routed.edges if item.spec.id == "recycle.node-features")
    assert edge.spec.role == "residual"
    west, corner, climb, arrival = edge.centerline
    assert west.y == corner.y and corner.x < west.x
    assert climb.x == corner.x and climb.y < corner.y
    assert arrival.y == climb.y and arrival.x > climb.x
    spine = panel.fitted.node("band1.previous").bounds
    assert corner.x < spine.left, "the rail climbs in the margin lane, not over the spine"


def _vector_figure(**options: object) -> Figure:
    figure = Figure("vectors", width=pt(260.0))
    with figure.module("m", gap="24pt") as module:
        cells = module.vector("q", label="Query vector", ramp="ramp-q", **options)
        module.mlp("mlp", label="MLP", input=cells)
    return figure


def test_vector_composite_hangs_its_label_below_the_cells() -> None:
    """R19: the caption is a sibling node, so the ports stay the cells rect."""

    figure = _vector_figure()
    semantic = figure.spec
    assert semantic.group("m.q").children == ("m.q.cells", "m.q.label")
    assert semantic.group("m.q").role == "layout"
    assert semantic.node("m.q.cells").kind == "vector"
    assert semantic.node("m.q.label").kind == "label"
    assert semantic.node("m.q.cells").label == ()
    assert semantic.node("m.q.label").text == "Query vector"
    assert dict(semantic.node("m.q.cells").properties) == {
        "cells": 3,
        "columns": 1,
        "ramp": "ramp-q",
    }
    assert str(semantic.edges[0].source) == "m.q.cells.output"
    compiled = compile_figure(semantic)
    cells = compiled.fitted.node("m.q.cells").bounds
    label = compiled.fitted.node("m.q.label").bounds
    assert label.top == pytest.approx(cells.bottom + STYLES["paper"].vector_label_gap.points)
    assert label.center.x == pytest.approx(cells.center.x), "the column centres both"


def test_vector_returns_the_cells_handle_with_one_port_per_side() -> None:
    """R18: connectors attach to the glyph itself, at side centres."""

    figure = _vector_figure()
    cells = next(
        node for node in figure.spec.nodes if node.id == "m.q.cells"
    )
    assert [(port.name, port.side.value, port.offset) for port in cells.ports] == [
        ("input", "west", 0.5),
        ("output", "east", 0.5),
        ("north", "north", 0.5),
        ("south", "south", 0.5),
    ]
    assert not any(port.adaptive for port in cells.ports)


def test_vector_columns_widen_the_grid_without_touching_its_height() -> None:
    style = STYLES["paper"]
    single = compile_figure(_vector_figure().spec).fitted.node("m.q.cells").bounds
    double = compile_figure(_vector_figure(columns=2).spec).fitted.node("m.q.cells").bounds
    assert double.height == pytest.approx(single.height)
    assert double.width == pytest.approx(
        2.0 * style.vector_cell.points + style.vector_column_gap.points
    )
    assert single.height == pytest.approx(
        3.0 * style.vector_cell.points + 2.0 * style.vector_cell_gap.points
    )


def test_vector_without_a_label_keeps_the_same_cells_id() -> None:
    figure = Figure("plain", width=pt(120.0))
    with figure.module("m") as module:
        handle = module.vector("v")
    assert handle.id == "m.v.cells"
    assert figure.spec.group("m.v").children == ("m.v.cells",)


def test_vector_label_wraps_on_an_authored_line_break() -> None:
    """A long caption may break instead of stretching the column."""

    figure = Figure("wrapped", width=pt(200.0))
    with figure.module("m") as module:
        module.vector("v", label="Sequence\nembedding")
    compiled = compile_figure(figure.spec)
    wrapped = compiled.fitted.node("m.v.label")
    assert len(wrapped.measured.label.lines) == 2
    assert wrapped.bounds.width < 60.0


def test_vector_rejects_a_ramp_no_palette_defines() -> None:
    figure = Figure("bad", width=pt(120.0))
    with figure.module("m") as module:  # noqa: SIM117
        with pytest.raises(ValueError, match="unknown vector ramp"):
            module.vector("v", ramp="ramp-rainbow")


def test_vector_round_trips_through_the_interchange_format() -> None:
    original = _vector_figure(cells=4, columns=2).spec
    assert parse_figure(yaml.safe_load(dump_figure(original))) == original


def test_attention_accepts_styled_label_runs() -> None:
    label = (TextRun("softmax(QK"), TextRun("T", baseline_shift="super"), TextRun(")V"))
    with Figure("styled", width=pt(200)) as figure:  # noqa: SIM117
        with figure.module("block") as module:
            q = module.node("q", ports=(PortSpec("output", Side.EAST),))
            k = module.node("k", ports=(PortSpec("output", Side.EAST),))
            v = module.node("v", ports=(PortSpec("output", Side.EAST),))
            module.attention("attention", q=q, k=k, v=v, label=label)
    assert figure.spec.node("block.attention").label == label


def test_panel_arrows_land_on_vector_side_centres(panel: Compilation) -> None:
    """R18/R20 acceptance: every arrow on a vector meets a side centre.

    A vector's ports are fixed, so this also pins that the re-authored panel
    attaches nothing to a cell stack's corner: the counterpart port is the one
    that adapts.
    """

    semantic = panel.measured.semantic
    vectors = {
        node.id for node in semantic.nodes if node.kind == "vector"
    }
    endpoints = [
        (reference, edge.id)
        for edge in semantic.edges
        for reference in (edge.source, edge.target)
    ] + [
        (reference, net.id)
        for net in semantic.nets
        for reference in net.sources + net.targets
    ]
    touched = set()
    for reference, owner in endpoints:
        if reference.node_id not in vectors:
            continue
        node = panel.fitted.node(reference.node_id)
        spec = next(port for port in node.measured.spec.ports if port.name == reference.port_name)
        assert not spec.adaptive, f"{owner} taps an adaptive vector port"
        assert node.port(spec.name).position == node.bounds.point_on(spec.side, 0.5), (
            f"{owner} does not meet the side centre of {reference.node_id}"
        )
        touched.add(reference.node_id)
    assert len(touched) >= 18, "the whole panel speaks the vector language"
