from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import yaml

import flexo
from flexo.builder import Figure, NodeHandle
from flexo.compiler import Compilation, compile_figure
from flexo.diagnostics import FlexoError
from flexo.gallery import modelangelo_gnn, vertical_slice
from flexo.geometry import Side
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec, PortSpec, TextRun
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
