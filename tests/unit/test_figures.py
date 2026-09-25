"""Behaviour the literature figures rely on: each test is one figure's lesson."""

from __future__ import annotations

from itertools import combinations

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation
from flexo.routing.labels import label_box


def test_a_circle_is_sized_to_its_label_and_shaded_on_request() -> None:
    with Figure("circles") as figure, figure.module("m") as m:
        small = m.circle("a", "$x$")
        m.circle("b", "$x_{long}$", shaded=True, input=small)
    compiled = compile_figure(figure.spec)
    a = compiled.fitted.node("m.a").bounds
    b = compiled.fitted.node("m.b").bounds
    assert a.width == pytest.approx(a.height)
    assert b.width > a.width
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
