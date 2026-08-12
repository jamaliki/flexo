from __future__ import annotations

from flexo.compiler import compile_figure
from flexo.gallery import vertical_slice
from flexo.geometry import Side, segments
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
)
from flexo.layout import fit_figure, measure_figure
from flexo.lint import lint_compilation
from flexo.routing import route_figure
from flexo.style import LayoutStyle
from flexo.units import pt


def routed_fixture(*, obstacle: bool = False, lane: bool = False):
    nodes = [NodeSpec("source", "block"), NodeSpec("target", "block")]
    children = ["source", "target"]
    if obstacle:
        nodes.insert(1, NodeSpec("obstacle", "matrix"))
        children.insert(1, "obstacle")
    figure = FigureSpec(
        "routing",
        width=pt(220),
        nodes=tuple(nodes),
        edges=(
            EdgeSpec(
                "flow",
                PortRef("source", "output"),
                PortRef("target", "input"),
                lane_hint="root-bottom" if lane else None,
            ),
        ),
        groups=(
            GroupSpec(
                "root",
                tuple(children),
                LayoutSpec("row", justify="space-between"),
            ),
        ),
    )
    return route_figure(fit_figure(measure_figure(figure)))


def test_direct_route_reaches_ports_and_shortens_shaft() -> None:
    routed = routed_fixture()
    edge = routed.edge("flow")
    assert edge.centerline[0] == routed.fitted.node("source").port("output").position
    assert edge.centerline[-1] == routed.fitted.node("target").port("input").position
    assert edge.shaft[-1].distance_to(edge.centerline[-1]) == LayoutStyle().arrow_length.points
    assert all(segment.orthogonal for segment in segments(edge.centerline))


def test_visibility_route_avoids_middle_obstacle() -> None:
    routed = routed_fixture(obstacle=True)
    obstacle = routed.fitted.node("obstacle").bounds
    assert not any(
        segment.intersects_rect_interior(obstacle)
        for segment in segments(routed.edge("flow").centerline)
    )
    assert len(routed.edge("flow").centerline) >= 4


def test_bottom_lane_routes_below_nodes() -> None:
    routed = routed_fixture(lane=True)
    edge = routed.edge("flow")
    assert max(point.y for point in edge.centerline) > routed.fitted.node("source").bounds.bottom
    assert edge.centerline[-2].y == edge.centerline[-1].y
    assert routed.fitted.node("target").port("input").side is Side.WEST


def test_routing_is_deterministic() -> None:
    assert routed_fixture(obstacle=True) == routed_fixture(obstacle=True)


def test_marker_orientation_matches_final_approach_after_elbow() -> None:
    figure = FigureSpec(
        "elbow",
        width=pt(180),
        nodes=(
            NodeSpec("source", "matrix"),
            NodeSpec("target", "block"),
        ),
        edges=(
            EdgeSpec("elbow", PortRef("source", "output"), PortRef("target", "input")),
        ),
        groups=(
            GroupSpec(
                "root",
                ("source", "target"),
                LayoutSpec("row", align="start", justify="space-between"),
            ),
        ),
    )
    edge = route_figure(fit_figure(measure_figure(figure))).edge("elbow")
    center_final = segments(edge.centerline)[-1]
    shaft_final = segments(edge.shaft)[-1]
    assert center_final.horizontal
    assert shaft_final.horizontal
    assert center_final.end.x > center_final.start.x
    assert shaft_final.end.x > shaft_final.start.x


def test_gallery_feed_forward_routes_minimize_elbows_globally() -> None:
    compilation = compile_figure(vertical_slice())
    feed_forward = tuple(
        edge for edge in compilation.routed.edges if edge.spec.role == "flow"
    )
    bend_counts = tuple(max(0, len(segments(edge.centerline)) - 1) for edge in feed_forward)
    assert bend_counts == (0,) * 10
    style = LayoutStyle()
    assert all(
        segments(edge.centerline)[-1].length
        >= 2 * style.arrow_length.points + style.elbow_radius.points
        for edge in compilation.routed.edges
    )
    feature = compilation.fitted.node("cryo.branches.feature-path.inputs.nodes")
    distances = compilation.fitted.node("cryo.branches.feature-path.inputs.distances")
    concat = compilation.fitted.node("cryo.branches.feature-path.concat")
    assert feature.port("output").position.y == concat.port("input1").position.y
    assert distances.port("output").position.y == concat.port("input2").position.y
    assert (
        concat.port("input2").position.y - concat.port("input1").position.y
        >= style.port_spacing.points
    )
    assert lint_compilation(compilation).ok


def test_fanout_net_has_one_trunk_and_heads_only_at_three_sinks() -> None:
    compilation = compile_figure(_vertical_net_figure())
    net = compilation.routed.net("shared")
    assert len(net.rail) == 2
    assert len(net.source_stems) == 1
    assert len(net.target_stems) == 3
    assert not any(stem.arrow_end for stem in net.source_stems)
    assert all(stem.arrow_end for stem in net.target_stems)
    assert compilation.document.text.count('marker-end="url(#arrow.flow)"') == 3
    assert all(
        segment.orthogonal
        for route in (
            net.rail,
            *(stem.centerline for stem in net.source_stems),
            *(stem.centerline for stem in net.target_stems),
        )
        for segment in segments(route)
    )


def test_merge_net_has_one_head_and_labeled_combination_rail() -> None:
    compilation = compile_figure(_horizontal_merge_figure())
    net = compilation.routed.net("combined")
    assert len(net.source_stems) == 3
    assert len(net.target_stems) == 1
    assert net.label_position is not None
    assert compilation.document.text.count('marker-end="url(#arrow.flow)"') == 1
    assert "Average" in compilation.document.text


def _vertical_net_figure() -> FigureSpec:
    source = NodeSpec(
        "source",
        "block",
        (TextRun("Source"),),
        ports=(PortSpec("s", Side.SOUTH, adaptive=True),),
    )
    targets = tuple(
        NodeSpec(
            f"target{index}",
            "block",
            (TextRun(f"T{index}"),),
            ports=(PortSpec("n", Side.NORTH, adaptive=True),),
        )
        for index in range(1, 4)
    )
    return FigureSpec(
        "fanout-net",
        width=pt(220),
        nodes=(source, *targets),
        nets=(
            NetSpec(
                "shared",
                "fan-out",
                (PortRef("source", "s"),),
                tuple(PortRef(node.id, "n") for node in targets),
            ),
        ),
        groups=(
            GroupSpec("root", ("source", "targets"), LayoutSpec("column", gap=pt(18))),
            GroupSpec(
                "targets",
                tuple(node.id for node in targets),
                LayoutSpec("row", gap=pt(18), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def _horizontal_merge_figure() -> FigureSpec:
    sources = tuple(
        NodeSpec(
            f"source{index}",
            "block",
            (TextRun(f"S{index}"),),
            ports=(PortSpec("e", Side.EAST, adaptive=True),),
        )
        for index in range(1, 4)
    )
    target = NodeSpec(
        "target",
        "block",
        (TextRun("Average"),),
        ports=(PortSpec("w", Side.WEST, adaptive=True),),
    )
    return FigureSpec(
        "merge-net",
        width=pt(260),
        nodes=(*sources, target),
        nets=(
            NetSpec(
                "combined",
                "merge",
                tuple(PortRef(node.id, "e") for node in sources),
                (PortRef("target", "w"),),
                label=(TextRun("Average"),),
            ),
        ),
        groups=(
            GroupSpec("root", ("sources", "target"), LayoutSpec("row", gap=pt(18))),
            GroupSpec(
                "sources",
                tuple(node.id for node in sources),
                LayoutSpec("column", gap=pt(12), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def test_lint_rejects_parallel_tracks_below_minimum_separation() -> None:
    close_ports = (
        PortSpec("first", Side.EAST, 0.45),
        PortSpec("second", Side.EAST, 0.55),
    )
    targets = (
        PortSpec("first", Side.WEST, 0.45),
        PortSpec("second", Side.WEST, 0.55),
    )
    figure = FigureSpec(
        "close-tracks",
        width=pt(180),
        nodes=(
            NodeSpec("source", "block", ports=close_ports),
            NodeSpec("target", "block", ports=targets),
        ),
        edges=(
            EdgeSpec("first", PortRef("source", "first"), PortRef("target", "first")),
            EdgeSpec("second", PortRef("source", "second"), PortRef("target", "second")),
        ),
        groups=(
            GroupSpec("root", ("source", "target"), LayoutSpec("row", gap=pt(20))),
        ),
    )

    report = lint_compilation(compile_figure(figure))
    assert "routing.track.separation" in {item.code for item in report.errors}
