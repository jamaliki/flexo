"""Behaviour the literature figures rely on: each test is one figure's lesson."""

from __future__ import annotations

from itertools import combinations

import pytest

import flexo
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation
from flexo.routing.labels import label_box


def test_circles_share_the_size_their_longest_label_needs() -> None:
    with Figure("circles") as figure, figure.module("m") as m:
        small = m.circle("a", "$x$")
        long = m.circle("b", "$x_{long}$", shaded=True, input=small)
        m.circle("c", "$y$", width="40pt", input=long)
    compiled = compile_figure(figure.spec)
    a = compiled.fitted.node("m.a").bounds
    b = compiled.fitted.node("m.b").bounds
    c = compiled.fitted.node("m.c").bounds
    assert a.width == pytest.approx(a.height)
    assert a.width == pytest.approx(b.width), "one size for every circle"
    with Figure("alone") as figure, figure.module("m") as m:
        m.circle("a", "$x$")
    alone = compile_figure(figure.spec).fitted.node("m.a").bounds
    assert b.width > alone.width, "the size the longest label needs"
    assert c.width == pytest.approx(40.0), "an authored size is kept"
    assert 'id="m.b.body"' in compiled.document.text
    assert not lint_compilation(compiled).errors


def test_straight_edges_run_outline_to_outline_and_need_no_lanes() -> None:
    with Figure("mlp", conventions={"lines": "straight"}) as figure:
        with figure.module("m", column_gap="30pt") as m:
            with m.column("a", role="layout") as column:
                first = [column.circle(f"a{i}", f"${i}$") for i in range(3)]
            with m.column("b", role="layout") as column:
                second = [column.circle(f"b{i}", f"${i}$") for i in range(3)]
        m.connect_all(first, second)
    compiled = compile_figure(figure.spec)
    assert len(compiled.routed.edges) == 9
    for edge in compiled.routed.edges:
        assert edge.straight and len(edge.centerline) == 2
        for point, node_id in zip(
            edge.centerline, (edge.spec.source.node_id, edge.spec.target.node_id), strict=True
        ):
            bounds = compiled.fitted.node(node_id).bounds
            assert point.distance_to(bounds.center) == pytest.approx(bounds.width / 2.0)
    gap = compiled.fitted.group("m.b").bounds.left - compiled.fitted.group("m.a").bounds.right
    assert gap == pytest.approx(30.0), "a fully connected layer reserves no routing lanes"
    assert not lint_compilation(compiled).errors


def test_two_straight_edges_between_one_pair_run_side_by_side() -> None:
    with Figure("pair", conventions={"lines": "straight"}) as figure:
        with figure.module("m", layout="column") as m:
            z = m.circle("z", "$z$")
            x = m.circle("x", "$x$", shaded=True)
        m.connect(z, x)
        m.connect(x, z)
    down, up = compile_figure(figure.spec).routed.edges
    assert down.centerline[0].x != pytest.approx(up.centerline[-1].x)


def test_attention_input_is_self_attention_and_two_inputs_are_cross_attention() -> None:
    with Figure("attn") as figure, figure.module("m", layout="column") as m:
        x = m.block("x", label="x")
        memory = m.block("mem", label="memory")
        m.attention("self", input=x)
        m.attention("cross", inputs=[x, memory])
    spec = figure.spec
    self_net = next(net for net in spec.nets if net.targets[0].node_id == "m.self")
    assert {target.port_name for target in self_net.targets} == {"q", "k", "v"}
    query = next(edge for edge in spec.edges if edge.target.node_id == "m.cross")
    assert (query.source.node_id, query.target.port_name) == ("m.x", "q")
    kv = next(net for net in spec.nets if net.targets[0].node_id == "m.cross")
    assert kv.sources[0].node_id == "m.mem"


def _loop() -> Figure:
    with Figure("loop", width="single-column") as figure:  # noqa: SIM117
        with figure.module("m", label="Loop", layout="column") as m:
            agent = m.block("agent", label="Agent")
            env = m.block("env", label="Environment")
            m.connect(agent, env, label="action $A_t$", via="east")
            m.connect(env, agent, label="state $S_{t+1}$", via="west")
            m.connect(env, agent, label="reward $R_{t+1}$", via="west")
    return figure


def test_captioned_edges_get_their_own_lines_and_captions_that_do_not_collide() -> None:
    compiled = compile_figure(_loop().spec)
    edges = compiled.routed.edges
    assert len({edge.centerline for edge in edges}) == 3
    boxes = [label_box(edge.label_position, edge.label_metrics) for edge in edges]
    for first, second in combinations(boxes, 2):
        assert not first.intersects(second, strict=True)
    module = compiled.fitted.group("m").bounds
    assert all(module.contains_rect(box) for box in boxes), "captions stay in their module"
    assert not lint_compilation(compiled).diagnostics


def test_via_across_the_line_of_travel_puts_both_ends_on_that_side() -> None:
    compiled = compile_figure(_loop().spec)
    action = compiled.routed.edges[0]
    agent = compiled.fitted.node("m.agent").bounds
    env = compiled.fitted.node("m.env").bounds
    assert action.centerline[0].x == pytest.approx(agent.right)
    assert action.centerline[-1].x == pytest.approx(env.right)


def test_a_row_slightly_too_wide_tightens_before_it_grows() -> None:
    with Figure("row") as figure, figure.module("m") as m:
        previous = m.text("q", "Query $x$")
        for index, label in enumerate(
            ("Query encoder", "MIPS", "Top-k documents", "Generator", "Answer")
        ):
            previous = m.block(f"b{index}", label=label, input=previous)
    compiled = compile_figure(figure.spec)
    assert not any(item.code == "layout.width.grown" for item in compiled.measured.diagnostics)


def _literature() -> dict:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "literature.py"
    spec = importlib.util.spec_from_file_location("literature", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIGURES


@pytest.mark.parametrize("theme", ["paper", "tikz"])
@pytest.mark.parametrize("name", sorted(_literature()))
def test_every_literature_figure_compiles_without_a_diagnostic(name: str, theme: str) -> None:
    """The figures in ``examples/literature.py`` are the promise: clean, as written."""

    compiled = compile_figure(_literature()[name](theme).spec)
    report = lint_compilation(compiled)
    assert not report.diagnostics, report.format()
    assert not compiled.measured.diagnostics


def test_a_decision_meets_each_line_at_a_corner_of_its_own() -> None:
    literature = _literature()
    compiled = compile_figure(literature["training-loop"]("paper").spec)
    diamond = compiled.fitted.node("m.done").bounds
    corners = {
        (round(diamond.center.x, 6), round(diamond.top, 6)),
        (round(diamond.right, 6), round(diamond.center.y, 6)),
        (round(diamond.center.x, 6), round(diamond.bottom, 6)),
        (round(diamond.left, 6), round(diamond.center.y, 6)),
    }
    touching = [
        point
        for edge in compiled.routed.edges
        for point in (edge.centerline[0], edge.centerline[-1])
        if diamond.contains_point(point)
    ]
    assert len(touching) == 3
    assert {(round(point.x, 6), round(point.y, 6)) for point in touching} <= corners
    assert len({(round(point.x, 6), round(point.y, 6)) for point in touching}) == 3


def test_line_styles_and_arrow_ends_change_only_the_ink() -> None:
    import xml.etree.ElementTree as ET

    with Figure("ends") as figure:
        with figure.module("m", layout="column") as m:
            a = m.block("a", label="A")
            b = m.block("b", label="B")
            c = m.block("c", label="C")
        m.connect(a, b, line="dashed", arrow="none")
        m.connect(b, c, line="dotted", arrow="both")
    compiled = compile_figure(figure.spec)
    root = ET.fromstring(compiled.document.text)
    by_id = {item.get("id"): item for item in root.iter() if item.get("id")}
    first, second = compiled.routed.edges
    assert by_id[first.spec.id].get("stroke-dasharray")
    assert by_id[second.spec.id].get("stroke-dasharray", "").startswith("0 ")
    assert by_id[f"{first.spec.id}.shaft"].get("marker-end") is None
    assert first.shaft == first.centerline, "an undirected link meets both components"
    shaft = by_id[f"{second.spec.id}.shaft"]
    assert shaft.get("marker-start") == "url(#arrow.flow.start)"
    assert shaft.get("marker-end") == "url(#arrow.flow)"
    assert by_id["arrow.flow.start"].get("orient") == "auto-start-reverse"
    assert not lint_compilation(compiled).errors


def test_a_volume_grows_with_each_dimension_and_carries_its_caption_below() -> None:
    with Figure("maps") as figure, figure.module("m") as m:
        small = m.volume("small", (8, 16, 16), label="small")
        m.volume("big", (64, 128, 128), label="big", input=small)
    compiled = compile_figure(figure.spec)
    small_box = compiled.fitted.node("m.small.box").bounds
    big_box = compiled.fitted.node("m.big.box").bounds
    assert big_box.width > small_box.width and big_box.height > small_box.height
    caption = compiled.fitted.node("m.big.label").bounds
    assert caption.top >= big_box.bottom
    edge = compiled.routed.edges[0]
    assert (edge.spec.source.node_id, edge.spec.target.node_id) == ("m.small.box", "m.big.box")
    assert not lint_compilation(compiled).errors


def test_a_skip_over_a_row_takes_the_lane_above_rather_than_crossing() -> None:
    """Retrieval-augmented generation: the query skips to the generator."""

    with Figure("rag") as figure:
        with figure.module("m", label="Retrieval-augmented generation") as m:
            query = m.text("q", "Query $x$")
            encoder = m.block("enc", label="Query encoder", input=query)
            with m.column("store", role="layout") as store:
                search = store.block("mips", label="MIPS")
                index = store.block("index", label="Document index")
            documents = m.block("docs", label="Top-k documents")
            generator = m.block("gen", label="Generator")
        m.connect(encoder, search)
        m.connect(index, search)
        m.connect(search, documents)
        m.connect(documents, generator)
        m.connect(query, generator)
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics


def test_rows_wired_one_to_one_share_their_columns() -> None:
    with Figure("table") as figure, figure.module("m", layout="column") as m:
        with m.row("inputs", role="layout") as row:
            words = [row.text(name, name.upper()) for name in ("v", "k", "q")]
        with m.row("projections", role="layout") as row:
            boxes = [
                row.block(f"p{index}", label="Linear projection", input=word)
                for index, word in enumerate(words)
            ]
    compiled = compile_figure(figure.spec)
    for word, box in zip(words, boxes, strict=True):
        above = compiled.fitted.node(word.id).bounds.center.x
        below = compiled.fitted.node(box.id).bounds.center.x
        assert above == pytest.approx(below)
    assert [group.id for group in figure.spec.groups if group.id.startswith("m.")] == [
        "m.inputs",
        "m.projections",
    ], "the authored figure keeps its rows"
    assert not lint_compilation(compiled).diagnostics


def test_a_long_label_wraps_into_balanced_lines_and_an_authored_width_holds() -> None:
    with Figure("wrap") as figure, figure.module("m", layout="column") as m:
        free = m.block("free", label="Multi-head self-attention with rotary position embeddings")
        m.block(
            "fixed", label="Feed-forward network with gated linear units", width="80pt", input=free
        )
    compiled = compile_figure(figure.spec)
    free_node = next(node for node in compiled.measured.nodes if node.spec.id == "m.free")
    lengths = [line.width for line in free_node.label.lines]
    assert len(lengths) == 2 and max(lengths) - min(lengths) < 0.4 * max(lengths)
    assert compiled.fitted.node("m.fixed").bounds.width == pytest.approx(80.0)
    assert not compiled.measured.diagnostics
    assert not lint_compilation(compiled).diagnostics


def test_string_references_resolve_against_the_nodes_that_exist() -> None:
    with Figure("refs") as figure, figure.module("m") as m:
        m.block("b", label="B")
        m.block("c", label="C")
        m.connect("b", "c")  # bare names, scoped ids
        m.connect("m.b", "m.c.input")  # a full id, and a full id with its port
    first, second = figure.spec.edges
    assert (first.source.node_id, first.target.node_id) == ("m.b", "m.c")
    assert (second.source.node_id, second.target.port_name) == ("m.b", "input")


def test_an_unknown_reference_names_what_was_typed_and_what_was_meant() -> None:
    from flexo.diagnostics import FlexoError

    with (
        pytest.raises(FlexoError, match=r'"m\.bb" does not exist') as raised,
        Figure("typo") as figure,
        figure.module("m") as m,
    ):
        m.block("b", label="B")
        m.connect("m.bb", m.block("c", label="C"))
    assert 'Did you mean "m.b"' in str(raised.value)


def test_a_duplicate_id_is_named_where_it_is_written() -> None:
    with Figure("twice") as figure, figure.module("m") as m:
        m.block("b", label="B")
        with pytest.raises(ValueError, match=r'"m\.b" is already used'):
            m.block("b", label="again")
        m.block("c", label="C")


def test_a_legend_keys_every_tone_in_the_colour_it_names() -> None:
    import xml.etree.ElementTree as ET

    with Figure("keyed") as figure, figure.module("m", layout="column") as m:
        m.mlp("mlp", label="MLP", input=m.block("embed", label="Embed", tone="embedding"))
        m.legend()
    compiled = compile_figure(figure.spec)
    names = [
        node.spec.label[0].text
        for node in compiled.measured.nodes
        if node.spec.id.startswith("m.legend.") and node.spec.id.endswith(".name")
    ]
    assert names == ["Embedding", "MLP"]
    root = ET.fromstring(compiled.document.text)
    fills = {
        item.get("id"): item.get("fill")
        for item in root.iter()
        if item.get("id", "").endswith(".body")
    }
    assert fills["m.legend.entry-0.swatch.body"] == fills["m.embed.body"]
    assert fills["m.legend.entry-1.swatch.body"] == fills["m.mlp.body"]


def test_a_loop_back_enters_from_the_side_that_lets_it_go_round() -> None:
    """A decision's "no" back to an earlier step, with a fan-out in between."""

    with Figure("ci") as figure:
        with figure.module("m", label="Continuous integration") as m:
            build = m.block("build", label="Build", input=m.terminal("push", label="Push"))
            with m.column("checks", role="layout") as column:
                checks = [column.block(name, label=name.title()) for name in ("unit", "lint")]
            ok = m.decision("ok", label="All green?")
            deploy = m.terminal("deploy", label="Deploy")
        figure.net(src=build, sinks=checks)
        figure.merge(sinks=checks, dst=ok)
        m.connect(ok, deploy, label="yes")
        m.connect(ok, build, label="no", line="dashed")
    assert not lint_compilation(compile_figure(figure.spec)).diagnostics


def test_a_concat_can_be_made_before_its_inputs() -> None:
    with Figure("late") as figure, figure.module("m") as m:
        joined = m.concat("cat", count=3)
        for index in range(3):
            m.connect(m.block(f"b{index}", label=f"B{index}"), joined.port(f"input{index + 1}"))
    compiled = compile_figure(figure.spec)
    assert {edge.spec.target.port_name for edge in compiled.routed.edges} == {
        "input1",
        "input2",
        "input3",
    }
    assert not lint_compilation(compiled).errors


def test_equal_size_children_share_a_width_and_a_centre_line() -> None:
    with Figure("equal") as figure, figure.module("m", layout="column", equal_size=True) as m:
        first = m.block("a", label="A short one")
        m.block("b", label="A much longer label than the first", input=first)
    compiled = compile_figure(figure.spec)
    a, b = compiled.fitted.node("m.a").bounds, compiled.fitted.node("m.b").bounds
    assert a.width == pytest.approx(b.width)
    assert a.center.x == pytest.approx(b.center.x)


def test_a_reversed_column_reads_from_the_bottom_up() -> None:
    with Figure("up") as figure, figure.root.column("stack", reverse=True) as column:
        first = column.block("first", label="First")
        column.block("second", label="Second", input=first)
    compiled = compile_figure(figure.spec)
    first_box = compiled.fitted.node("stack.first").bounds
    second_box = compiled.fitted.node("stack.second").bounds
    assert second_box.bottom < first_box.top
    assert not lint_compilation(compiled).diagnostics


def test_wired_content_on_the_root_is_centred_on_the_canvas() -> None:
    with Figure("centred") as figure:
        x = figure.root.text("x", "input")
        figure.root.block("a", label="Encoder", input=x)
    compiled = compile_figure(figure.spec)
    box = compiled.fitted.node("a").bounds
    canvas = compiled.fitted.canvas_size.width
    assert box.center.x == pytest.approx(canvas / 2.0)


def test_a_flow_group_lays_its_children_out_in_layers_by_their_wiring() -> None:
    import yaml

    from flexo.serialization import dump_figure, parse_figure

    for kind, axis in (("flow", "y"), ("flow-right", "x")):
        with Figure("flow") as figure, figure.module("m", layout=kind) as m:
            x = m.text("x", "input")
            a = m.block("a", label="A", input=x)
            b = m.block("b", label="B", input=x)
            fused = m.block("fused", label="Fuse", inputs=[a, b])
            m.connect(fused, a, label="loop")
        compiled = compile_figure(figure.spec)
        box = {node.measured.spec.id: node.bounds for node in compiled.fitted.nodes}
        along = (lambda rect: rect.center.y) if axis == "y" else (lambda rect: rect.center.x)
        assert along(box["m.x"]) < along(box["m.a"]) == pytest.approx(along(box["m.b"]))
        assert along(box["m.a"]) < along(box["m.fused"]), "the loop does not reorder layers"
        assert not lint_compilation(compiled).diagnostics
        assert parse_figure(yaml.safe_load(dump_figure(figure.spec))) == figure.spec


def test_a_flow_places_inputs_late_and_ignores_undirected_links_for_layers() -> None:
    with Figure("gan") as figure, figure.module("m", layout="flow") as m:
        generator = m.block("g", label="Generator", input=m.text("z", "noise"))
        judge = m.block("d", label="Discriminator", inputs=[generator, m.text("x", "real")])
        twin = m.block("twin", label="Twin", input=m.text("y", "other"))
        m.connect(generator, twin, arrow="none", line="dashed")
        m.text("verdict", "real or fake?", input=judge)
    compiled = compile_figure(figure.spec)
    top = {node.measured.spec.id: node.bounds.center.y for node in compiled.fitted.nodes}
    assert top["m.x"] == pytest.approx(top["m.g"]), "real data enters beside the generator"
    assert top["m.twin"] == pytest.approx(top["m.g"]), "an undirected link orders no layers"


def test_a_misspelt_layout_or_width_is_named_with_a_guess() -> None:
    with pytest.raises(ValueError, match=r'unknown layout "flwo" \(did you mean "flow"\?\)'):
        Figure("typo").module("m", layout="flwo")
    with Figure("wide", width="one-column") as figure:
        figure.root.block("b", label="B")
    with pytest.raises(flexo.FlexoError, match="single-column"):
        compile_figure(figure.spec)


def test_an_empty_figure_or_flow_compiles_clean() -> None:
    for figure in (Figure("empty"), Figure("empty-flow", layout="flow")):
        assert not lint_compilation(compile_figure(figure.spec)).diagnostics
