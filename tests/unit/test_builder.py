from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import yaml

import flexo
from flexo.builder import Figure, NodeHandle
from flexo.compiler import Compilation, compile_figure
from flexo.components import attachment_lane_tracks
from flexo.diagnostics import FlexoError
from flexo.gallery import modelangelo_gnn, vertical_slice
from flexo.geometry import Side
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec, PortSpec, TextRun
from flexo.lint import lint_compilation
from flexo.serialization import dump_figure, parse_figure
from flexo.style import STYLES, VectorPreset
from flexo.units import CellSpan, pt
from flexo.validate import normalize_and_validate


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


def test_vector_preset_carries_its_shades_instead_of_a_ramp_role() -> None:
    preset = VectorPreset(("#d0568c", "#7fae3f"), "2x3")
    figure = Figure("preset", width=pt(120.0))
    with figure.module("m") as module:
        module.vector("kv", label="K, V", preset=preset)
    assert dict(figure.spec.node("m.kv.cells").properties) == {
        "cells": 3,
        "columns": 2,
        "shades": preset.encode(),
    }


def test_vector_preset_refuses_to_share_the_job_with_ramp_or_topology() -> None:
    figure = Figure("preset", width=pt(120.0))
    with figure.module("m") as module:
        for conflict in ({"ramp": "ramp-q"}, {"cells": 4}, {"columns": 2}):
            with pytest.raises(ValueError, match="already carries colour and topology"):
                module.vector("v", preset=VectorPreset("#4a6cb0", "1x3"), **conflict)


def test_vector_without_a_preset_keeps_its_defaults() -> None:
    figure = Figure("plain", width=pt(120.0))
    with figure.module("m") as module:
        module.vector("v")
    assert dict(figure.spec.node("m.v.cells").properties) == {
        "cells": 3,
        "columns": 1,
        "ramp": "ramp-node",
    }


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


def test_at_places_children_and_leaves_the_rest_flowing() -> None:
    with Figure("placed", width=pt(400)) as figure:  # noqa: SIM117
        with figure.root.grid("panel", columns=4, gap=pt(8)) as panel:
            panel.block("first", label="A")
            panel.block("last", label="D", at=(1, 3))
            panel.block("second", label="B")
    layout = figure.spec.group("panel").layout
    assert layout.placements == (("panel.last", 1, 3),)
    assert layout.placement_map() == {"panel.last": (1, 3)}


def test_vector_addresses_its_whole_composite() -> None:
    with Figure("placed", width=pt(400)) as figure:  # noqa: SIM117
        with figure.root.grid("panel", columns=3) as panel:
            panel.vector("q", label="Q", ramp="ramp-q", at=(1, 2))
    # The grid's child is the column holding cells and caption, not the cells.
    assert figure.spec.group("panel").layout.placements == (("panel.q", 1, 2),)


def test_two_children_in_one_cell_is_rejected_where_it_is_written() -> None:
    with Figure("clash", width=pt(400)) as figure, figure.root.grid("panel", columns=3) as panel:
        panel.block("first", label="A", at=(0, 1))
        with pytest.raises(ValueError, match=r'already taken by "panel\.first"'):
            panel.block("second", label="B", at=(0, 1))


def test_a_column_outside_the_grid_is_rejected() -> None:
    with (
        Figure("range", width=pt(400)) as figure,
        figure.root.grid("panel", columns=3) as panel,
    ):
        with pytest.raises(ValueError, match=r"column 3 .* is out of range"):
            panel.block("first", label="A", at=(0, 3))
        with pytest.raises(ValueError, match="0-indexed"):
            panel.block("second", label="B", at=(-1, 0))


def test_at_needs_a_grid() -> None:
    with (
        Figure("kind", width=pt(400)) as figure,
        figure.root.row("band") as band,
        pytest.raises(ValueError, match="lays out as a row"),
    ):
        band.block("first", label="A", at=(0, 0))


def test_placement_naming_a_stranger_is_a_diagnostic() -> None:
    figure = FigureSpec(
        "stranger",
        width=pt(200),
        nodes=(NodeSpec("only", "block", (TextRun("A"),)),),
        groups=(
            GroupSpec(
                "root",
                ("only",),
                LayoutSpec(kind="grid", columns=2, placements=(("ghost", 0, 1),)),
            ),
        ),
    )
    with pytest.raises(FlexoError, match="not a child of this group"):
        normalize_and_validate(figure)


def test_padding_takes_one_length_a_pair_or_four_sides() -> None:
    with Figure("padding", width=pt(400)) as figure:
        figure.root.group("uniform", padding=pt(6))
        figure.root.group("pair", padding=(pt(4), pt(20)))
        figure.root.group("sides", padding=(pt(1), pt(2), pt(3), pt(4)))
    spec = figure.spec
    uniform = spec.group("uniform").layout
    assert uniform.padding == pt(6) and uniform.padding_top is None
    pair = spec.group("pair").layout
    assert (pair.padding_top, pair.padding_right) == (pt(20), pt(4))
    assert (pair.padding_bottom, pair.padding_left) == (pt(20), pt(4))
    sides = spec.group("sides").layout
    assert (sides.padding_top, sides.padding_right, sides.padding_bottom, sides.padding_left) == (
        pt(1),
        pt(2),
        pt(3),
        pt(4),
    )


def test_padding_rejects_a_three_value_shorthand() -> None:
    with (
        Figure("padding", width=pt(400)) as figure,
        pytest.raises(ValueError, match="not 3 values"),
    ):
        figure.root.group("odd", padding=(pt(1), pt(2), pt(3)))


def test_column_widths_need_a_column_count() -> None:
    with (
        Figure("lane", width=pt(400)) as figure,
        pytest.raises(ValueError, match="need a column count"),
    ):
        figure.root.row("band", column_widths={0: pt(50)})


def test_cells_extent_survives_a_document_round_trip() -> None:
    with Figure("extent", width=pt(400)) as figure:  # noqa: SIM117
        with figure.root.grid("panel", columns=2, row_gap=pt(4), column_gap=pt(18)) as panel:
            panel.mlp("projection", height="cells:3", width=pt(40))
            panel.block("tail", label="T", at=(1, 1))
    original = figure.spec
    assert original.node("panel.projection").height == CellSpan(3)
    parsed = parse_figure(yaml.safe_load(dump_figure(original)))
    assert parsed == original


def test_paint_lowers_into_one_scalar_property_per_part() -> None:
    """A node property holds a scalar, so the three parts travel separately."""

    figure = Figure("paint", width=pt(240.0))
    with figure.module("m") as module:
        module.mlp("mlp", label="MLP", paint={"label": "#9fe1cb", "fill": "#085041"})
    node = figure.spec.node("m.mlp")
    assert dict(node.properties) == {"paint-fill": "#085041", "paint-label": "#9fe1cb"}
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))).node("m.mlp") == node


def test_a_group_takes_the_same_three_paint_parts_a_node_does() -> None:
    """A container has no property bag, so its paint travels as typed pairs."""

    figure = Figure("paint", width=pt(240.0))
    with figure.module("m", label="Module", paint={"label": "#9FE1CB", "fill": "#abc"}) as module:
        module.mlp("mlp", label="MLP")
        module.row("plain", paint=None)
    group = figure.spec.group("m")
    assert group.paint == (("fill", "#aabbcc"), ("label", "#9fe1cb"))
    assert figure.spec.group("m.plain").paint == ()
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))).group("m") == group


def test_a_group_rejects_paint_it_cannot_apply() -> None:
    figure = Figure("paint", width=pt(240.0))
    with pytest.raises(ValueError, match="valid parts: fill, stroke, label"):
        figure.module("bad", paint={"title": "#123456"})
    with pytest.raises(ValueError, match="invalid colour"):
        figure.module("worse", paint={"fill": "teal"})
    with pytest.raises(ValueError, match="valid parts: fill, stroke, label"):
        GroupSpec("direct", (), paint=(("body", "#123456"),))


def test_motif_only_reaches_the_properties_when_it_is_off() -> None:
    figure = Figure("motifs", width=pt(240.0))
    with figure.module("m") as module:
        module.mlp("on", label="On")
        module.mlp("off", label="Off", motif=False)
        module.feature_strip("strip", label="Strip", cells=4, motif=False)
    assert figure.spec.node("m.on").properties == ()
    assert dict(figure.spec.node("m.off").properties) == {"motif": False}
    # A motif switch may not displace the properties a component already sets.
    assert dict(figure.spec.node("m.strip").properties) == {"cells": 4, "motif": False}


def test_an_unknown_title_side_is_rejected_where_it_is_written() -> None:
    figure = Figure("titles", width=pt(240.0))
    with pytest.raises(ValueError, match="valid sides: left, right"):
        figure.module("m", label="Module", title_side="top")
    assert figure.module("m", label="Module", title_side="right")
    assert figure.spec.group("m").title_side == "right"


def _joined_figure(**net_options: object) -> Figure:
    figure = Figure("joins", width=pt(320.0))
    with figure.module("m", gap="40pt") as module:
        first = module.block("first", label="First")
        second = module.block("second", label="Second")
        sink = module.block("sink", label="Sink")
    figure.merge(sinks=[first, second], dst=sink, id="combined", **net_options)  # type: ignore[arg-type]
    return figure


def test_merge_carries_its_rail_placement_and_joint_style_into_the_spec() -> None:
    net = _joined_figure(rail_at=0.55, joint="arrow").spec.nets[0]
    assert (net.rail_at, net.joint) == (0.55, "arrow")
    assert parse_figure(yaml.safe_load(dump_figure(_joined_figure(rail_at=0.55).spec))).nets == (
        _joined_figure(rail_at=0.55).spec.nets
    )


def test_a_net_refuses_a_placement_it_cannot_keep() -> None:
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        _joined_figure(rail_at=1.0)
    with pytest.raises(ValueError, match="places its rail twice"):
        _joined_figure(rail_at=0.5, rail="east")


def test_only_a_merge_may_join_with_an_arrowhead() -> None:
    """A fan-out's branches leave the trunk, so an arrow there would point back."""

    figure = Figure("fan", width=pt(320.0))
    with figure.module("m", gap="40pt") as module:
        source = module.block("source", label="Source")
        first = module.block("first", label="First")
        second = module.block("second", label="Second")
    with pytest.raises(ValueError, match="only a merge has"):
        figure.net(src=source, sinks=[first, second], joint="arrow")
    assert figure.net(src=source, sinks=[first, second], joint="dot", id="shared").joint == "dot"


_WRAPPERS = (
    "block",
    "matrix",
    "sequence",
    "graph",
    "inset",
    "tensor",
    "feature_strip",
    "add_norm",
    "prediction",
    "loss",
    "mlp",
    "cnn",
)


@pytest.mark.parametrize("wrapper", _WRAPPERS)
def test_every_component_factory_takes_input_and_inputs(wrapper: str) -> None:
    """R23: one way to wire a component, whichever factory made it."""

    for keyword in ("input", "inputs"):
        with Figure("uniform", width=pt(240)) as figure, figure.module("m", gap="20pt") as module:
            upstream = module.block("upstream", label="Up")
            value = upstream if keyword == "input" else (upstream,)
            getattr(module, wrapper)("target", **{keyword: value})
        (edge,) = figure.spec.edges
        assert str(edge.source) == "m.upstream.output"
        assert str(edge.target) == "m.target.input"


def test_node_itself_takes_input_and_inputs() -> None:
    """The factories are conveniences over ``node``, so ``node`` accepts them too."""

    with Figure("wired", width=pt(300)) as figure, figure.module("m", gap="20pt") as module:
        first = module.block("first", label="One")
        second = module.block("second", label="Two")
        module.node("concat", "concat", inputs=(first, second))
        module.node("sink", "block", input=first)
    wired = {(str(edge.source), str(edge.target)) for edge in figure.spec.edges}
    assert wired == {
        ("m.first.output", "m.concat.input1"),
        ("m.second.output", "m.concat.input2"),
        ("m.first.output", "m.sink.input"),
    }


def test_several_inputs_share_one_port_when_the_component_has_only_one() -> None:
    with Figure("fan-in", width=pt(300)) as figure, figure.module("m", gap="20pt") as module:
        first = module.block("first", label="One")
        second = module.block("second", label="Two")
        module.add_norm("norm", inputs=(first, second))
    assert [str(edge.target) for edge in figure.spec.edges] == [
        "m.norm.input",
        "m.norm.input",
    ]


def test_wiring_a_component_with_no_input_port_says_which_ports_it_has() -> None:
    figure = Figure("bad", width=pt(240))
    with figure.module("m") as module:
        source = module.block("source", label="Source")
        with pytest.raises(ValueError, match="no \"input\" port"):
            module.attention("attn", q=source, k=source, v=source, input=source)


def test_authored_ports_win_over_the_ones_a_factory_would_compute() -> None:
    """``mlp(ports=...)`` used to raise "multiple values for keyword argument"."""

    ports = (
        PortSpec("input", Side.NORTH, adaptive=True),
        PortSpec("output", Side.SOUTH, adaptive=True),
    )
    with Figure("ports", width=pt(240)) as figure, figure.module("m", gap="20pt") as module:
        source = module.block("source", label="Source")
        head = module.mlp("head", ports=ports, input=source)
        module.cnn("conv", ports=ports, input=source)
    assert isinstance(head, NodeHandle) and head.ports == ("input", "output")
    for node_id in ("m.head", "m.conv"):
        assert figure.spec.node(node_id).ports == ports
    assert [str(edge.target) for edge in figure.spec.edges] == ["m.head.input", "m.conv.input"]


def test_a_factory_computes_its_ports_only_when_the_author_gave_none() -> None:
    with Figure("computed", width=pt(300)) as figure, figure.module("m", gap="20pt") as module:
        first = module.block("first", label="One")
        second = module.block("second", label="Two")
        module.mlp("head", inputs=(first, second))
    names = [port.name for port in figure.spec.node("m.head").ports]
    assert names == ["input1", "input2", "output"]


def test_authored_ports_receive_the_inputs_a_factory_was_given() -> None:
    """Author ports plus several inputs: the numbered ports they declared, if any."""

    ports = (
        PortSpec("input1", Side.NORTH, 0.3, adaptive=True),
        PortSpec("input2", Side.NORTH, 0.7, adaptive=True),
        PortSpec("output", Side.SOUTH, adaptive=True),
    )
    with Figure("authored", width=pt(300)) as figure, figure.module("m", gap="20pt") as module:
        first = module.block("first", label="One")
        second = module.block("second", label="Two")
        module.mlp("head", ports=ports, inputs=(first, second))
    assert [str(edge.target) for edge in figure.spec.edges] == [
        "m.head.input1",
        "m.head.input2",
    ]


def test_a_factory_merges_its_own_properties_under_the_authors() -> None:
    with Figure("props", width=pt(240)) as figure, figure.module("m") as module:
        module.sequence("tokens", tokens=6, properties={"tokens": 9, "extra": "yes"})
    assert dict(figure.spec.node("m.tokens").properties) == {"extra": "yes", "tokens": 9}


def test_a_group_authors_nets_and_merges_like_the_figure_does() -> None:
    """R23: ``root.net(...)`` works wherever ``root.connect(...)`` does."""

    with Figure("nets", width=pt(320)) as figure:
        root = figure.root
        with root.column("stack", gap="20pt") as stack:
            source = stack.block("source", label="Source")
            first = stack.block("first", label="One")
            second = stack.block("second", label="Two")
            net = stack.net(src=source, sinks=[first, second], id="fan", rail_at=0.4)
            merged = stack.merge(sinks=[first, second], dst=source, id="join", joint="dot")
    assert figure.spec.nets == (net, merged)
    assert net.kind == "fan-out" and net.rail_at == 0.4
    assert merged.kind == "merge" and merged.joint == "dot"
    assert [str(ref) for ref in net.targets] == ["stack.first.input", "stack.second.input"]


def test_build_compiles_exports_and_lints_in_one_call(tmp_path) -> None:
    """The three calls every figure script used to make by hand."""

    result = flexo.build(
        vertical_slice(),
        tmp_path,
        stem="slice",
        formats=("editable",),
    )
    assert result.outputs.editable_svg == tmp_path / "slice.editable.svg"
    assert result.outputs.editable_svg.is_file()
    assert result.outputs.existing() == (result.outputs.editable_svg,)
    assert isinstance(result.compilation, Compilation)
    assert result.ok and result.report.ok
    assert "slice.editable.svg" in result.summary()


def test_build_writes_its_outputs_even_when_the_figure_lints_with_errors(tmp_path) -> None:
    figure = FigureSpec(
        "clipped",
        width=pt(120),
        nodes=(
            NodeSpec(
                "tiny",
                "block",
                (TextRun("A label far too long for this block"),),
                width=pt(12),
                height=pt(8),
            ),
        ),
        groups=(GroupSpec("root", ("tiny",), LayoutSpec("row"), role="canvas"),),
    )
    result = flexo.build(figure, tmp_path, formats=("editable",))
    assert result.outputs.editable_svg.is_file()
    assert not result.ok
    assert any(item.code == "layout.text.overflow" for item in result.report.errors)


def test_figure_render_is_build_on_the_builder(tmp_path) -> None:
    with Figure("rendered", width=pt(180)) as figure, figure.module("m") as module:
        module.block("only", label="One")
    result = figure.render(tmp_path, formats=("editable",))
    assert result.outputs.editable_svg == tmp_path / "rendered.editable.svg"
    assert result.outputs.editable_svg.is_file()


def test_figure_compile_takes_the_style_and_palette_it_will_be_drawn_with() -> None:
    with Figure("styled", width=pt(180)) as figure, figure.module("m") as module:
        module.block("only", label="One")
    large = STYLES["paper"].with_updates(typography=flexo.TypographyStyle(size=pt(16.0)))
    dark = flexo.DEFAULT_PALETTE.with_overrides({"container-fill": "#101010"})
    styled = figure.compile(style=large, palette=dark)
    plain = figure.compile()
    assert styled.document.height_mm > plain.document.height_mm
    assert "#101010" in styled.document.text
    assert "#101010" not in plain.document.text


def test_the_authoring_surface_is_reachable_from_the_top_level_package() -> None:
    """One import line has to be enough to write and build a figure."""

    for name in (
        "Figure",
        "VectorPreset",
        "TextRun",
        "LayoutStyle",
        "TypographyStyle",
        "Palette",
        "DEFAULT_PALETTE",
        "STYLES",
        "build",
        "compile_figure",
        "export_outputs",
        "lint_compilation",
        "load_figure",
        "save_figure",
        "retheme_svg",
        "vector_stack_height",
        "shade_ramp",
        "Side",
        "pt",
    ):
        assert name in flexo.__all__, name
        assert getattr(flexo, name) is not None, name


def test_attention_can_be_created_before_its_sources_exist() -> None:
    """R27: q/k/v are optional, so a decoder may be authored before its encoder."""

    with Figure("cross", width=pt(320.0)) as figure:
        with figure.module("decoder") as module:
            block = module.attention("xmha", label="Multi-Head\nAttention")
        with figure.module("encoder") as module:
            top = module.block("top", label="Add & Norm")
        figure.net(src=top, sinks=[block.k, block.v], id="cross-kv")
    semantic = figure.spec
    assert block.ports == ("q", "k", "v", "output")
    assert semantic.edges == (), "an unwired attention block authors no connectors"
    assert tuple(str(target) for target in semantic.nets[0].targets) == (
        "decoder.xmha.k",
        "decoder.xmha.v",
    )


def test_attention_wires_only_the_sources_it_was_given() -> None:
    with Figure("partial", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("m") as module:
            query = module.block("query", label="Q")
            module.attention("mha", q=query)
    assert [str(edge.target) for edge in figure.spec.edges] == ["m.mha.q"]


def test_add_norm_names_both_of_its_arrivals_and_both_of_its_departures() -> None:
    """R27: input/skip on the way in, output/branch on the way out."""

    with Figure("residual", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("m", layout="column") as module:
            sublayer = module.block("sublayer", label="Feed Forward")
            bypassed = module.block("bypassed", label="Embedding")
            block = module.add_norm("an", label="Add & Norm", input=sublayer, skip=bypassed)
    assert block.ports == ("input", "skip", "output", "branch")
    semantic = figure.spec
    assert [str(edge.target) for edge in semantic.edges] == ["m.an.input", "m.an.skip"]
    sides = {port.name: (port.side, port.auto_side) for port in semantic.node("m.an").ports}
    # The spine follows the figure's reading direction; the bypass does not.
    assert sides["input"] == (Side.WEST, True)
    assert sides["output"] == (Side.EAST, True)
    assert sides["skip"] == (Side.EAST, False)
    assert sides["branch"] == (Side.EAST, False)


def test_a_default_residual_always_enters_and_leaves_on_the_east_side() -> None:
    """One convention per figure: a bypass is the wire on the right, in every tower.

    Auto-siding chose per node, so a mirrored pair of towers came out
    mirror-handed and a reader had to learn each one. The pinned pair also takes
    two lanes -- arrival low, departure high -- so neither run starts where the
    other one ends.
    """

    def tower(pair, name: str) -> None:
        with pair.column(name, gap=pt(30.0), padding=pt(24.0), role="module") as column:
            an = column.add_norm(f"{name}-an", label="Add & Norm", width=pt(90.0))
            sublayer = column.block(f"{name}-ff", label="Feed Forward", width=pt(90.0))
            fork = column.node(f"{name}-fork", "junction")
            column.connect(fork, sublayer)
            column.connect(sublayer, an)
            column.connect(fork.branch, an.skip, id=f"{name}-skip")

    with (
        Figure("towers", width=pt(520.0)) as figure,
        figure.root.row("pair", gap=pt(40.0), role="layout") as pair,
    ):
        tower(pair, "left")
        tower(pair, "right")
    compiled = compile_figure(figure.spec)
    for name in ("left", "right"):
        node = compiled.fitted.node(f"pair.{name}.{name}-an")
        ports = {port.name: port for port in node.ports}
        assert ports["skip"].side is Side.EAST
        assert ports["branch"].side is Side.EAST
        assert ports["skip"].position.x == node.bounds.right
        # The arrival sits below the departure, the way the wire travels.
        assert ports["skip"].position.y > ports["branch"].position.y
    assert not lint_compilation(compiled).errors


def test_an_explicit_port_table_still_buys_a_left_handed_residual() -> None:
    left_handed = (
        PortSpec("input", Side.SOUTH, 0.5, adaptive=True),
        PortSpec("skip", Side.WEST, 0.8, adaptive=True),
        PortSpec("output", Side.NORTH, 0.5, adaptive=True),
        PortSpec("branch", Side.WEST, 0.2, adaptive=True),
    )
    with Figure("mirror", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("m", layout="column") as module:
            module.add_norm("an", label="Add & Norm", ports=left_handed)
    sides = {port.name: port.side for port in figure.spec.node("m.an").ports}
    assert sides["skip"] is Side.WEST and sides["branch"] is Side.WEST


def test_a_skip_edge_lands_on_the_skip_port_rather_than_crowding_the_input() -> None:
    """The two arrivals get two ports, so neither route is dragged off its twin.

    The container carries side padding because the pinned bypass routes *outside*
    the block it rejoins: a content-hugging column leaves the corridor no room.
    """

    with Figure("tower", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.root.group(
            "m", role="module", layout="column", gap="30pt", padding=pt(24.0)
        ) as module:
            an = module.add_norm("an", label="Add & Norm", width="90pt")
            sublayer = module.block("sublayer", label="Attention", width="90pt")
            fork = module.node("fork", "junction")
            module.connect(fork, sublayer)
            module.connect(sublayer, an)
            module.connect(fork.branch, an.skip, id="skip")
    compiled = compile_figure(figure.spec)
    node = compiled.fitted.node("m.an")
    entries = {port.name: port.position for port in node.ports}
    assert entries["input"] != entries["skip"]
    report = lint_compilation(compiled)
    assert not report.errors, report.format()


def test_residual_prefers_a_component_s_own_skip_port() -> None:
    with Figure("skip", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("m", layout="column") as module:
            source = module.block("source", label="Source")
            target = module.add_norm("an", label="Add & Norm")
            edge = module.residual(source, target)
    assert str(edge.target) == "m.an.skip"
    assert edge.role == "residual"


def test_via_lowers_onto_an_edge_and_a_net_as_a_side() -> None:
    """R27: one word about the corridor, on both authoring surfaces."""

    with Figure("hints", width=pt(320.0)) as figure:
        with figure.module("m", layout="column") as module:
            first = module.block("first", label="First")
            second = module.block("second", label="Second")
            third = module.block("third", label="Third")
        edge = figure.root.connect(first, second, id="round", via="west")
        net = figure.net(src=first, sinks=[second, third], id="bus", via=Side.NORTH)
        merged = figure.merge(sinks=[second, third], dst=first, id="join", via="south")
    assert edge.via is Side.WEST
    assert (net.via, merged.via) == (Side.NORTH, Side.SOUTH)
    assert figure.spec.edges[0].via is Side.WEST


def test_an_unknown_via_side_is_rejected_where_it_is_written() -> None:
    figure = Figure("bad", width=pt(320.0))
    with figure.module("m") as module:
        first = module.block("first", label="First")
        second = module.block("second", label="Second")
    with pytest.raises(ValueError, match="unknown via side"):
        module.connect(first, second, via="left")


def test_a_net_may_not_place_its_rail_twice() -> None:
    figure = Figure("twice", width=pt(320.0))
    with figure.module("m") as module:
        first = module.block("first", label="First")
        second = module.block("second", label="Second")
        third = module.block("third", label="Third")
    with pytest.raises(ValueError, match="places its rail twice"):
        figure.net(src=first, sinks=[second, third], rail="west", via="west")
    with pytest.raises(ValueError, match="places its rail twice"):
        figure.net(src=first, sinks=[second, third], rail_at=0.4, via="west")


def _attention_figure(**options: object) -> Figure:
    """One attention composite in a column, with nothing wired into it."""

    options.setdefault("width", pt(120.0))
    figure = Figure("grown", width=pt(320.0))
    with figure.root.column("m", role="layout") as column:
        column.attention("mha", label="Attention", **options)
    return figure


def test_attention_without_vectors_is_the_plain_component() -> None:
    """R28: ``vectors=`` is opt-in, so a figure that never asks for it never moves."""

    plain = _attention_figure().spec
    assert [node.id for node in plain.nodes] == ["m.mha"]
    assert plain.groups[1].children == ("m.mha",)
    assert not plain.edges
    assert _attention_figure(vectors=None).spec == plain
    assert _attention_figure(vectors=False).spec == plain


def test_attention_vectors_lower_into_a_block_over_three_glyphs() -> None:
    semantic = _attention_figure(vectors=True).spec
    assert semantic.group("m.mha").children == ("m.mha.block", "m.mha.qkv")
    assert semantic.group("m.mha").anchor == "m.mha.block"
    assert semantic.group("m.mha.qkv").children == (
        "m.mha.qkv.q",
        "m.mha.qkv.k",
        "m.mha.qkv.v",
    )
    assert semantic.node("m.mha.block").kind == "attention"
    for name in ("q", "k", "v"):
        assert semantic.group(f"m.mha.qkv.{name}").children == (
            f"m.mha.qkv.{name}.label",
            f"m.mha.qkv.{name}.cells",
        ), "the caption stands beside the stack, on the side the convention names"
        assert semantic.group(f"m.mha.qkv.{name}").anchor == f"m.mha.qkv.{name}.cells"
        assert semantic.node(f"m.mha.qkv.{name}.cells").kind == "vector"
        caption = semantic.node(f"m.mha.qkv.{name}.label")
        assert (caption.text, caption.role) == (name.upper(), "caption")


def test_attention_vectors_centre_every_glyph_on_its_own_port() -> None:
    """The composite's whole reason to exist: no author arithmetic, exact x."""

    compiled = compile_figure(_attention_figure(vectors=True).spec)
    block = compiled.fitted.node("m.mha.block")
    for name, offset in (("q", 0.24), ("k", 0.5), ("v", 0.76)):
        cells = compiled.fitted.node(f"m.mha.qkv.{name}.cells")
        assert cells.bounds.center.x == pytest.approx(
            block.bounds.left + offset * block.bounds.width
        ), f"{name} is not centred under its port"
        assert cells.bounds.center.x == pytest.approx(block.port(name).position.x)
    row = compiled.fitted.group("m.mha.qkv")
    assert row.bounds.width == pytest.approx(block.bounds.width)


def test_attention_vector_drops_are_plain_verticals() -> None:
    compiled = compile_figure(_attention_figure(vectors=True).spec)
    drops = [
        edge
        for edge in compiled.routed.edges
        if edge.spec.target.node_id == "m.mha.block"
    ]
    assert len(drops) == 3
    for drop in drops:
        start, end = drop.centerline
        assert len(drop.centerline) == 2, "a centred drop needs no bend"
        assert start.x == pytest.approx(end.x)
        assert start.y > end.y, "the glyph feeds the block above it"
    assert not lint_compilation(compiled).errors


def test_attention_vector_glyphs_are_fed_from_below_and_leave_north() -> None:
    cells = _attention_figure(vectors=True).spec.node("m.mha.qkv.k.cells")
    assert [(port.name, port.side.value, port.auto_side) for port in cells.ports] == [
        ("input", "south", False),
        ("output", "north", False),
    ]


def test_attention_handle_answers_q_k_v_from_the_glyphs() -> None:
    with Figure("wired", width=pt(320.0)) as figure:
        with figure.root.column("m", role="layout") as column:
            grown = column.attention("mha", label="Attention", width=pt(120.0), vectors=True)
            source = column.block("src", label="Source")
        figure.root.connect(source, grown.k)
    assert grown.id == "m.mha.block"
    assert str(grown.output) == "m.mha.block.output"
    assert str(grown.q) == "m.mha.qkv.q.cells.input"
    assert str(grown.v) == "m.mha.qkv.v.cells.input"
    authored = figure.spec.edges[-1]
    assert str(authored.target) == "m.mha.qkv.k.cells.input"


def test_attention_wires_its_sources_into_the_glyphs_at_creation() -> None:
    with (
        Figure("wired", width=pt(320.0)) as figure,
        figure.root.column("m", role="layout") as column,
    ):
        source = column.block("src", label="Source")
        column.attention(
            "mha", label="Attention", width=pt(120.0), vectors=True, q=source, v=source
        )
    targets = [str(edge.target) for edge in figure.spec.edges if edge.source.node_id == "m.src"]
    assert targets == ["m.mha.qkv.q.cells.input", "m.mha.qkv.v.cells.input"]


def test_attention_vectors_true_takes_the_palette_ramp_roles() -> None:
    semantic = _attention_figure(vectors=True).spec
    ramps = {
        name: semantic.node(f"m.mha.qkv.{name}.cells").property("ramp")
        for name in ("q", "k", "v")
    }
    assert ramps == {"q": "ramp-q", "k": "ramp-kv", "v": "ramp-kv"}


def test_attention_broadcasts_one_preset_or_one_ramp_to_all_three() -> None:
    preset = VectorPreset("#4a6cb0", "1x4")
    shared = _attention_figure(vectors=preset).spec
    for name in ("q", "k", "v"):
        assert dict(shared.node(f"m.mha.qkv.{name}.cells").properties) == {
            "cells": 4,
            "columns": 1,
            "shades": preset.encode(),
        }
    named = _attention_figure(vectors="ramp-attended").spec
    assert named.node("m.mha.qkv.v.cells").property("ramp") == "ramp-attended"


def test_attention_vectors_take_one_paint_per_name_case_insensitively() -> None:
    presets = {
        "Q": VectorPreset("#9a6fb8", "1x3"),
        "K": VectorPreset("#c9853d", "1x3"),
        "V": VectorPreset("#4f9b8f", "1x3"),
    }
    semantic = _attention_figure(vectors=presets).spec
    assert semantic.node("m.mha.qkv.q.cells").property("shades") == presets["Q"].encode()
    assert semantic.node("m.mha.qkv.v.cells").property("shades") == presets["V"].encode()


def test_attention_vectors_reject_a_partial_or_unknown_mapping() -> None:
    with pytest.raises(ValueError, match="leaves k, v unpainted"):
        _attention_figure(vectors={"q": "ramp-q"})
    with pytest.raises(ValueError, match="does not know the key"):
        _attention_figure(vectors={"q": "ramp-q", "k": "ramp-kv", "v": "ramp-kv", "x": "ramp-q"})
    with pytest.raises(ValueError, match="vectors= takes True"):
        _attention_figure(vectors=[1, 2, 3])


def test_attention_vectors_need_a_width_to_centre_against() -> None:
    figure = Figure("unsized", width=pt(320.0))
    with figure.root.column("m", role="layout") as column:  # noqa: SIM117
        with pytest.raises(ValueError, match="needs a width to grow its vectors"):
            column.attention("mha", label="Attention", vectors=True)


def test_attention_composite_aligns_a_ports_row_on_the_block() -> None:
    """The tower lines up on the attention boxes, not on the captions beneath."""

    with (
        Figure("towers", width=pt(460.0)) as figure,
        figure.root.row("row", align="ports", role="layout") as row,
    ):
        with row.column("left", role="layout") as left:
            left.attention("mha", label="Attention", width=pt(120.0), vectors=True)
        with row.column("right", role="layout") as right:
            right.block("plain", label="Plain", width=pt(120.0), height=pt(58.0))
    compiled = compile_figure(figure.spec)
    block = compiled.fitted.node("row.left.mha.block").bounds
    plain = compiled.fitted.node("row.right.plain").bounds
    assert block.center.y == pytest.approx(plain.center.y)


def test_attention_vector_lanes_follow_an_authored_port_table() -> None:
    """A cross-attention that reads its value on the left puts that glyph there."""

    vaswani = (
        PortSpec("v", Side.SOUTH, 0.24, adaptive=True, auto_side=True),
        PortSpec("k", Side.SOUTH, 0.5, adaptive=True, auto_side=True),
        PortSpec("q", Side.SOUTH, 0.76, adaptive=True, auto_side=True),
        PortSpec("output", Side.NORTH, 0.5, adaptive=True, auto_side=True),
    )
    compiled = compile_figure(_attention_figure(vectors=True, ports=vaswani).spec)
    block = compiled.fitted.node("m.mha.block")
    xs = {
        name: compiled.fitted.node(f"m.mha.qkv.{name}.cells").bounds.center.x
        for name in ("q", "k", "v")
    }
    assert xs["v"] < xs["k"] < xs["q"], "the glyphs read in port order, not in q/k/v order"
    for name, offset in (("v", 0.24), ("k", 0.5), ("q", 0.76)):
        assert xs[name] == pytest.approx(block.bounds.left + offset * block.bounds.width)


def test_attention_vector_captions_stand_beside_their_glyph() -> None:
    """R29: the caption leaves the corridor under the stack empty for the feed.

    Beside, not below: one ``caption_clearance`` of air from the cells, centred on
    the port line the cells' own side ports sit on, and inside the lane the
    composite cut for this glyph.
    """

    style = STYLES["paper"]
    compiled = compile_figure(_attention_figure(vectors=True).spec)
    for name in ("q", "k", "v"):
        cells = compiled.fitted.node(f"m.mha.qkv.{name}.cells").bounds
        caption = compiled.fitted.node(f"m.mha.qkv.{name}.label").bounds
        assert cells.left - caption.right == pytest.approx(style.caption_clearance.points)
        assert caption.center.y == pytest.approx(cells.center.y)
        assert caption.top >= cells.top and caption.bottom <= cells.bottom


def test_attention_vector_captions_leave_the_stacks_where_they_were() -> None:
    """A caption may not move the thing it names off the port that thing feeds.

    The glyph reserves the caption's room on the stack's other side too, so the
    glyph is exactly as wide as its lane and symmetric about its cells -- which is
    what keeps the stack on the port's x whichever side the words take.
    """

    compiled = compile_figure(_attention_figure(vectors=True).spec)
    lanes = attachment_lane_tracks((0.24, 0.5, 0.76), 120.0)
    for name in ("q", "k", "v"):
        cells = compiled.fitted.node(f"m.mha.qkv.{name}.cells").bounds
        glyph = compiled.fitted.group(f"m.mha.qkv.{name}").bounds
        assert glyph.width == pytest.approx(lanes[1])
        assert glyph.center.x == pytest.approx(cells.center.x)
        assert glyph.height == pytest.approx(cells.height), "the caption adds no band"


def test_a_lane_too_narrow_for_a_side_caption_keeps_it_underneath() -> None:
    """The degrade is the old arrangement, not a caption jammed into 3pt of lane."""

    style = STYLES["paper"]
    below = compile_figure(_attention_figure(vectors=True, width=pt(50.0)).spec)
    assert below.measured.semantic.group("m.mha.qkv.q").children == (
        "m.mha.qkv.q.cells",
        "m.mha.qkv.q.label",
    )
    cells = below.fitted.node("m.mha.qkv.q.cells").bounds
    caption = below.fitted.node("m.mha.qkv.q.label").bounds
    assert caption.top - cells.bottom == pytest.approx(
        style.arrival_clearance.points + style.caption_clearance.points
    )
    assert cells.center.x == pytest.approx(below.fitted.node("m.mha.block").port("q").position.x)


def test_attention_vector_feeds_arrive_as_plain_verticals() -> None:
    """The point of the whole arrangement: nothing to hook around under a glyph."""

    with Figure("fed", width=pt(320.0)) as figure:
        with figure.root.column("m", role="layout") as column:
            grown = column.attention("mha", label="Attention", width=pt(120.0), vectors=True)
            source = column.block("src", label="Source", width=pt(120.0))
        figure.net(src=source, sinks=[grown.q, grown.k, grown.v], id="qkv")
    compiled = compile_figure(figure.spec)
    net = compiled.routed.net("qkv")
    for stem in net.target_stems:
        assert len(stem.centerline) == 2, f"{stem.port} hooks around something"
        start, end = stem.centerline
        assert start.x == pytest.approx(end.x)
        assert start.y > end.y, "the feed arrives from below"
    assert not lint_compilation(compiled).errors


# --- R35: module padding, notes, and operator symbols ---------------------


def test_module_takes_the_same_asymmetric_padding_a_group_does() -> None:
    """R35: ``module`` is a group, so the one layout knob it swallowed is back.

    The figure this replaces had to abandon ``module()`` and rebuild it as a raw
    ``group`` to pull a port up to its module's wall.
    """

    with Figure("padded", width=pt(220)) as figure:  # noqa: SIM117
        with figure.module("m", label="Module", padding=(pt(20), pt(3), pt(11), pt(7))) as module:
            module.block("b", label="Body")
    layout = next(group for group in figure.spec.groups if group.id == "m").layout
    assert (layout.padding_top, layout.padding_right) == (pt(20), pt(3))
    assert (layout.padding_bottom, layout.padding_left) == (pt(11), pt(7))
    assert layout.padding is None, "asymmetry is four sides, not one length"
    fitted = compile_figure(figure.spec).fitted
    group = fitted.group("m")
    assert group.bounds.right - group.content_bounds.right == pytest.approx(3.0)
    assert group.bounds.bottom - group.content_bounds.bottom == pytest.approx(11.0)
    assert group.content_bounds.left - group.bounds.left == pytest.approx(7.0)
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))) == figure.spec


def test_module_and_row_take_one_padding_and_an_xy_pair_too() -> None:
    """The whole padding grammar, not a special case of it."""

    with Figure("padded", width=pt(220)) as figure:
        figure.module("uniform", padding=pt(9)).block("a")
        figure.root.row("pair", padding=(pt(4), pt(6))).block("b")
        figure.root.column("none").block("c")
    layouts = {group.id: group.layout for group in figure.spec.groups}
    assert layouts["uniform"].padding == pt(9)
    assert layouts["pair"].padding_left == pt(4) and layouts["pair"].padding_top == pt(6)
    assert layouts["none"].padding is None, "an author who asked for nothing gets the default"


def test_a_note_travels_as_a_node_property_and_round_trips() -> None:
    """R35: a remark about a component belongs to the component, not to a column."""

    with Figure("noted", width=pt(220)) as figure:  # noqa: SIM117
        with figure.module("m") as module:
            module.mlp("ffn", label="GEGLU FFN", note="384 → 768 → 384")
            module.cnn("conv", label="Conv", note="stride 2\nk = 3")
    nodes = {node.id: node for node in figure.spec.nodes}
    assert nodes["m.ffn"].property("note") == "384 → 768 → 384"
    assert nodes["m.conv"].property("note") == "stride 2\nk = 3"
    assert len(figure.spec.groups) == 2, "no wrapper column was grown to hold the words"
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))) == figure.spec


def test_a_note_needs_a_body_to_sit_in() -> None:
    with Figure("noted", width=pt(220)) as figure:
        with pytest.raises(ValueError, match="no body to hold a note"):
            figure.root.node("v", "vector", note="N × 3")  # noqa: RUF001
        figure.root.block("b", label="Body")


def test_operator_spreads_its_inputs_over_the_edges_it_offers() -> None:
    """R2/R35: two arrivals on two edges, never two arrowheads on one point."""

    with Figure("ops", width=pt(220)) as figure:  # noqa: SIM117
        with figure.module("m") as module:
            sublayer = module.block("sublayer", label="Sublayer")
            skip = module.block("skip", label="Skip")
            join = module.operator("join", "+", inputs=(sublayer, skip))
            assert join.ports == ("input", "output", "north", "south")
    targets = [str(edge.target) for edge in figure.spec.edges]
    assert targets == ["m.join.input", "m.join.south"]
    node = next(node for node in figure.spec.nodes if node.id == "m.join")
    assert node.kind == "operator"
    assert node.text == "+"
    assert node.properties == (), "the default shape says nothing"
    assert {port.side for port in node.ports} == set(Side)
    assert all(port.offset == 0.5 and not port.adaptive for port in node.ports)


def test_operator_takes_the_standard_wiring_keywords() -> None:
    with Figure("ops", width=pt(220)) as figure:  # noqa: SIM117
        with figure.module("m") as module:
            source = module.block("source", label="Source")
            module.operator("scale", "×", shape="circle", input=source)  # noqa: RUF001
            module.operator(
                "sum",
                "Σ",
                ports=(PortSpec("input1", Side.WEST, 0.3), PortSpec("input2", Side.WEST, 0.7)),
                inputs=(source, source),
            )
    assert [str(edge.target) for edge in figure.spec.edges] == [
        "m.scale.input",
        "m.sum.input1",
        "m.sum.input2",
    ]
    scale = next(node for node in figure.spec.nodes if node.id == "m.scale")
    assert scale.property("shape") == "circle"


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"glyph": "Add"}, "exactly one glyph"),
        ({"glyph": ""}, "exactly one glyph"),
        ({"shape": "hexagon"}, "unknown operator shape"),
    ],
)
def test_operator_refuses_what_is_not_a_symbol(options: dict[str, str], message: str) -> None:
    glyph = options.pop("glyph", "+")
    with Figure("ops", width=pt(220)) as figure:
        with pytest.raises(ValueError, match=message):
            figure.root.operator("op", glyph, **options)
        figure.root.block("b", label="Body")
