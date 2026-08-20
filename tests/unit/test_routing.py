from __future__ import annotations

import pytest

from flexo.compiler import compile_figure
from flexo.diagnostics import Severity
from flexo.emit import _net_ink
from flexo.gallery import gallery_figure, vertical_slice
from flexo.geometry import Point, Rect, Segment, Side, segments
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
from flexo.routing.nets import _vertical_rail, net_segments
from flexo.routing.nudge import (
    Run,
    caption_reach,
    caption_rise,
    collapse_zigzags,
    edge_shaft,
    nudge_routes,
    rail_label_position,
    shorten_start,
)
from flexo.routing.solve import _routing_order
from flexo.routing.visibility import PathCosts, shortest_orthogonal_path
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer, ink_descent
from flexo.units import pt


def routed_fixture(*, obstacle: bool = False, lane: bool = False, style=None):
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
    return route_figure(fit_figure(measure_figure(figure)), style=style)


def test_direct_route_reaches_ports_and_shortens_shaft() -> None:
    style = LayoutStyle()
    routed = routed_fixture()
    edge = routed.edge("flow")
    assert edge.centerline[0] == routed.fitted.node("source").port("output").position
    assert edge.centerline[-1] == routed.fitted.node("target").port("input").position
    assert edge.shaft[-1].distance_to(edge.centerline[-1]) == (
        style.arrow_length.points + style.connector_standoff.points
    )
    assert all(segment.orthogonal for segment in segments(edge.centerline))


def test_shaft_leaves_a_standoff_at_both_connector_ends() -> None:
    style = LayoutStyle()
    standoff = style.connector_standoff.points
    edge = routed_fixture().edge("flow")
    assert edge.shaft[0].distance_to(edge.centerline[0]) == standoff
    # The marker is anchored at the shaft end and its tip sits an arrow_length
    # beyond, so the tip lands exactly one standoff short of the target port.
    tip = edge.shaft[-1].distance_to(edge.centerline[-1]) - style.arrow_length.points
    assert tip == standoff
    assert all(segment.orthogonal for segment in segments(edge.shaft))


def test_zero_standoff_reproduces_butt_jointed_shafts() -> None:
    style = LayoutStyle().with_updates(connector_standoff=pt(0))
    edge = routed_fixture(style=style).edge("flow")
    assert edge.shaft[0] == edge.centerline[0]
    assert edge.shaft[-1].distance_to(edge.centerline[-1]) == style.arrow_length.points


def test_standoff_never_inverts_a_shaft_shorter_than_its_trims() -> None:
    centerline = (Point(0.0, 0.0), Point(3.0, 0.0))
    # Both trims exceed the run: the shaft collapses to a point rather than
    # reversing, exactly as an over-long arrow trim already degrades.
    assert edge_shaft(centerline, arrow_length=4.0, standoff=2.5) == (Point(0.0, 0.0),)
    assert edge_shaft(centerline, arrow_length=0.0, standoff=1.0) == (
        Point(1.0, 0.0),
        Point(2.0, 0.0),
    )
    assert shorten_start(centerline, 10.0) == (Point(3.0, 0.0),)
    assert shorten_start(centerline, 1.0) == (Point(1.0, 0.0), Point(3.0, 0.0))


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
    style = LayoutStyle()
    # R18: a run is straight whenever its two ports share a coordinate, and a
    # single centred Z-bend -- never more -- when the band refuses the alignment.
    for edge in feed_forward:
        source = compilation.fitted.node(edge.spec.source.node_id).port(
            edge.spec.source.port_name
        )
        target = compilation.fitted.node(edge.spec.target.node_id).port(
            edge.spec.target.port_name
        )
        bends = max(0, len(segments(edge.centerline)) - 1)
        assert bends == (0 if source.position.y == target.position.y else 2)
    assert all(
        segments(edge.centerline)[-1].length
        >= 2 * style.arrow_length.points + style.elbow_radius.points
        for edge in compilation.routed.edges
    )
    distances = compilation.fitted.node("cryo.branches.feature-path.inputs.distances")
    concat = compilation.fitted.node("cryo.branches.feature-path.concat")
    # The lower feed is inside the band and lands straight; the upper one is not,
    # so it keeps the concat's authored first-input offset and bends.
    assert distances.port("output").position.y == concat.port("input2").position.y
    first = next(port for port in concat.measured.spec.ports if port.name == "input1")
    assert (
        concat.port("input1").position.y
        == concat.bounds.point_on(first.side, first.offset).y
    )
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


def test_net_stems_stand_off_at_nodes_while_rail_joints_stay_closed() -> None:
    style = LayoutStyle()
    standoff = style.connector_standoff.points
    net = compile_figure(_vertical_net_figure()).routed.net("shared")
    for stem in net.source_stems:
        assert stem.shaft[0].distance_to(stem.centerline[0]) == standoff
        assert stem.shaft[-1] == stem.centerline[-1]
    for stem in net.target_stems:
        assert stem.shaft[0] == stem.centerline[0]
        assert stem.shaft[-1].distance_to(stem.centerline[-1]) == (
            style.arrow_length.points + standoff
        )
    ink = _net_ink(net, style.elbow_radius.points)
    for _, shaft, arrow_end in ink.stems:
        joint = shaft[0] if arrow_end else shaft[-1]
        assert any(
            Rect.from_points(segment.start, segment.end).contains_point(joint)
            for _, points, _ in ink.rails
            for segment in segments(points)
        )


def test_rail_orientation_follows_the_target_side_majority() -> None:
    """R9: the spokes decide the axis, and a tie runs along the hub port axis."""

    horizontal_spokes = (Side.NORTH, Side.NORTH, Side.WEST)
    vertical_spokes = (Side.WEST, Side.EAST, Side.NORTH)
    assert not _vertical_rail(None, Side.SOUTH, horizontal_spokes)
    assert _vertical_rail(None, Side.SOUTH, vertical_spokes)
    assert _vertical_rail(None, Side.SOUTH, (Side.WEST, Side.NORTH))
    assert not _vertical_rail(None, Side.EAST, (Side.WEST, Side.NORTH))
    assert _vertical_rail(Side.WEST, Side.SOUTH, horizontal_spokes)
    assert not _vertical_rail(Side.NORTH, Side.SOUTH, vertical_spokes)


def test_skip_net_drops_one_straight_trunk_at_the_hub_axis() -> None:
    """R9: a west branch and a north continuation tie, so the trunk stays vertical."""

    compilation = compile_figure(_skip_net_figure())
    net = compilation.routed.net("skip")
    hub = compilation.fitted.node("previous").port("output")
    assert net.rail[0].x == net.rail[-1].x == hub.position.x
    (trunk,) = net.source_stems
    assert tuple(point.x for point in trunk.centerline) == (hub.position.x,) * 2
    branch, continuation = net.target_stems
    assert branch.port.node_id == "module.nodes"
    assert segments(branch.centerline)[-1].horizontal
    assert tuple(point.x for point in continuation.centerline) == (hub.position.x,) * 2
    assert lint_compilation(compilation).ok


def test_reserved_spacer_columns_never_deflect_a_net_rail() -> None:
    """A spacer draws no body, so it must not push the trunk off the hub axis."""

    without = compile_figure(_skip_net_figure())
    with_spacer = compile_figure(_skip_net_figure(spacer=True))
    assert with_spacer.routed.net("skip").rail[0].x == without.routed.net("skip").rail[0].x


def _skip_net_figure(*, spacer: bool = False) -> FigureSpec:
    """A spine block feeding a module's west input and the next spine block."""

    spine_children = ("previous", "strip", "addln") if spacer else ("previous", "addln")
    reserved = (NodeSpec("reserved", "spacer", width=pt(72), height=pt(0)),) if spacer else ()
    strip = (
        (
            GroupSpec(
                "strip",
                ("reserved",),
                LayoutSpec("row", padding=pt(0)),
                role="layout",
            ),
        )
        if spacer
        else ()
    )
    return FigureSpec(
        "skip-net",
        width=pt(260),
        nodes=(
            NodeSpec(
                "previous",
                "block",
                (TextRun("Previous"),),
                width=pt(72),
                ports=(PortSpec("output", Side.SOUTH, adaptive=True),),
            ),
            *reserved,
            NodeSpec(
                "addln",
                "block",
                (TextRun("Add LN"),),
                width=pt(72),
                ports=(PortSpec("skip", Side.NORTH, adaptive=True),),
            ),
            NodeSpec(
                "module.nodes",
                "block",
                (TextRun("Node features"),),
                ports=(PortSpec("input", Side.WEST, adaptive=True),),
            ),
        ),
        nets=(
            NetSpec(
                "skip",
                "fan-out",
                (PortRef("previous", "output"),),
                (PortRef("module.nodes", "input"), PortRef("addln", "skip")),
            ),
        ),
        groups=(
            GroupSpec("root", ("band",), LayoutSpec("column", gap=pt(24))),
            GroupSpec(
                "band",
                ("spine", "module"),
                LayoutSpec("row", gap=pt(24), padding=pt(0), align="start"),
                role="layout",
            ),
            GroupSpec(
                "spine",
                spine_children,
                LayoutSpec("column", gap=pt(24), padding=pt(0)),
                role="layout",
            ),
            *strip,
            GroupSpec(
                "module",
                ("module.nodes",),
                LayoutSpec("row"),
                role="module",
            ),
        ),
    )


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


def test_aligned_ports_route_as_one_straight_segment() -> None:
    """R5: a collinear, unobstructed pair of escape points never gains a jog."""

    figure = FigureSpec(
        "straight",
        width=pt(200),
        nodes=(
            NodeSpec("source", "block", ports=(PortSpec("output", Side.EAST),)),
            NodeSpec("target", "block", ports=(PortSpec("input", Side.WEST),)),
        ),
        edges=(EdgeSpec("flow", PortRef("source", "output"), PortRef("target", "input")),),
        groups=(GroupSpec("root", ("source", "target"), LayoutSpec("row", gap=pt(40))),),
    )
    edge = route_figure(fit_figure(measure_figure(figure))).edge("flow")
    assert len(edge.centerline) == 2
    assert edge.centerline[0].y == edge.centerline[-1].y


def test_direct_segment_is_refused_when_it_would_share_a_lane() -> None:
    start, end = Point(0.0, 0.0), Point(40.0, 0.0)
    costs = PathCosts(14.0, separation=6.0)
    assert shortest_orthogonal_path(start, end, (), costs=costs) == (start, end)
    occupied = (Segment(Point(0.0, 2.0), Point(40.0, 2.0)),)
    detour = shortest_orthogonal_path(start, end, (), costs=costs, occupied=occupied)
    assert detour is not None
    assert len(detour) > 2


def test_zigzag_collapse_straightens_a_short_middle_segment() -> None:
    points = (
        Point(0.0, 0.0),
        Point(10.0, 0.0),
        Point(10.0, 2.0),
        Point(30.0, 2.0),
        Point(30.0, 20.0),
        Point(50.0, 20.0),
    )
    collapsed = collapse_zigzags(points, (), 3.0)
    assert collapsed == (
        Point(0.0, 0.0),
        Point(30.0, 0.0),
        Point(30.0, 20.0),
        Point(50.0, 20.0),
    )


def test_zigzag_collapse_keeps_a_jog_that_would_cross_an_obstacle() -> None:
    points = (
        Point(0.0, 0.0),
        Point(10.0, 0.0),
        Point(10.0, 2.0),
        Point(30.0, 2.0),
        Point(30.0, 20.0),
        Point(50.0, 20.0),
    )
    blocker = Rect(15.0, -2.0, 5.0, 4.0)
    assert collapse_zigzags(points, (blocker,), 3.0) == points


def _container_figure() -> FigureSpec:
    """A spine node, a bordered module, and a spine node below it."""

    return FigureSpec(
        "containers",
        width=pt(260),
        nodes=(
            NodeSpec("top", "block", ports=(PortSpec("output", Side.EAST),)),
            NodeSpec("inner", "block", ports=(PortSpec("input", Side.WEST),)),
            NodeSpec("bottom", "block", ports=(PortSpec("input", Side.NORTH),)),
        ),
        edges=(
            EdgeSpec("into", PortRef("top", "output"), PortRef("inner", "input")),
            EdgeSpec("past", PortRef("top", "output"), PortRef("bottom", "input")),
        ),
        groups=(
            GroupSpec("root", ("top", "module", "bottom"), LayoutSpec("column", gap=pt(30))),
            GroupSpec("module", ("inner",), LayoutSpec("row"), role="module"),
        ),
    )


def test_opaque_container_blocks_routes_that_do_not_own_it() -> None:
    routed = route_figure(fit_figure(measure_figure(_container_figure())))
    module = routed.fitted.group("module").bounds
    past = routed.edge("past")
    assert not any(
        segment.intersects_rect_interior(module) for segment in segments(past.centerline)
    )
    into = routed.edge("into")
    assert any(
        segment.intersects_rect_interior(module) for segment in segments(into.centerline)
    )


def test_nudging_redistributes_a_shared_corridor_around_its_mean() -> None:
    boundary = Rect(-100.0, -100.0, 400.0, 400.0)
    runs = (
        Run("first", "first", boundary),
        Run("second", "second", boundary),
    )
    polylines = (
        (Point(0.0, 0.0), Point(0.0, 50.0), Point(60.0, 50.0), Point(60.0, 100.0)),
        (Point(0.0, 120.0), Point(0.0, 52.0), Point(80.0, 52.0), Point(80.0, 160.0)),
    )
    style = LayoutStyle()
    spacing = style.port_spacing.points
    nudged = nudge_routes(runs, polylines, style=style, obstacles=())
    first = nudged[0][1].y
    second = nudged[1][1].y
    assert abs(second - first) == spacing
    assert (first + second) / 2.0 == (50.0 + 52.0) / 2.0
    assert nudged[0][0] == polylines[0][0]
    assert nudged[1][-1] == polylines[1][-1]


def test_nudging_leaves_a_group_alone_when_the_move_hits_an_obstacle() -> None:
    boundary = Rect(-100.0, -100.0, 400.0, 400.0)
    runs = (
        Run("first", "first", boundary),
        Run("second", "second", boundary),
    )
    polylines = (
        (Point(0.0, 0.0), Point(0.0, 50.0), Point(60.0, 50.0), Point(60.0, 100.0)),
        (Point(0.0, 120.0), Point(0.0, 52.0), Point(80.0, 52.0), Point(80.0, 160.0)),
    )
    blocker = Rect(20.0, 47.0, 10.0, 2.0)
    style = LayoutStyle()
    assert nudge_routes(runs, polylines, style=style, obstacles=(blocker,)) == polylines


def test_gallery_routing_is_deterministic_and_lint_clean() -> None:
    for name in ("vertical-slice", "modelangelo-gnn"):
        first = compile_figure(gallery_figure(name))
        second = compile_figure(gallery_figure(name))
        assert first.routed == second.routed
        assert first.document.text == second.document.text
        assert not lint_compilation(first).errors


def test_long_haul_edges_claim_their_lane_before_short_ones() -> None:
    fitted = fit_figure(measure_figure(_container_figure()))
    order = _routing_order(fitted, fitted.measured.semantic.edges)
    assert tuple(edge.id for edge in order) == ("past", "into")


def test_long_run_prefers_the_middle_of_its_gutter() -> None:
    """R1: given a free corridor, the crossing run centres instead of grazing."""

    obstacles = (Rect(0.0, 40.0, 40.0, 20.0), Rect(60.0, 40.0, 40.0, 20.0))
    costs = PathCosts(14.0, clearance=5.0)
    route = shortest_orthogonal_path(
        Point(10.0, 100.0),
        Point(90.0, 0.0),
        obstacles,
        costs=costs,
    )
    assert route is not None
    crossing = tuple(segment for segment in segments(route) if segment.vertical)
    assert len(crossing) == 1
    # The gutter runs from x=40 to x=60; hugging either wall costs more length.
    assert crossing[0].start.x == 50.0


def test_departure_orientation_is_charged_against_the_port_stub() -> None:
    """R5: turning straight out of a port costs a bend, so straight runs win."""

    obstacles = (Rect(20.0, 20.0, 40.0, 40.0),)
    costs = PathCosts(14.0)
    turning = shortest_orthogonal_path(
        Point(0.0, 0.0),
        Point(100.0, 0.0),
        obstacles,
        costs=costs,
        departure=False,
    )
    assert turning == (Point(0.0, 0.0), Point(100.0, 0.0))


def _transparent_edge_figure() -> FigureSpec:
    """A spacer wide and tall enough to be crossed sits between two blocks."""

    return FigureSpec(
        "transparent-edge",
        width=pt(240),
        nodes=(
            NodeSpec("source", "block", (TextRun("Source"),)),
            NodeSpec("middle", "spacer", width=pt(60), height=pt(40)),
            NodeSpec("target", "block", (TextRun("Target"),)),
        ),
        edges=(EdgeSpec("flow", PortRef("source", "output"), PortRef("target", "input")),),
        groups=(
            GroupSpec(
                "root",
                ("source", "middle", "target"),
                LayoutSpec("row", gap=pt(20)),
            ),
        ),
    )


def _transparent_net_figure() -> FigureSpec:
    """A fan-out whose stems drop straight through a reserved corridor spacer."""

    heads = tuple(
        NodeSpec(
            f"head{index}",
            "block",
            (TextRun(f"Head {index}"),),
            ports=(PortSpec("input", Side.NORTH, adaptive=True),),
        )
        for index in range(1, 3)
    )
    return FigureSpec(
        "transparent-net",
        width=pt(280),
        nodes=(
            NodeSpec(
                "hub",
                "block",
                (TextRun("Hub"),),
                ports=(PortSpec("output", Side.SOUTH, adaptive=True),),
            ),
            NodeSpec("corridor", "spacer", width=pt(200), height=pt(30)),
            *heads,
        ),
        nets=(
            NetSpec(
                "fan",
                "fan-out",
                (PortRef("hub", "output"),),
                tuple(PortRef(head.id, "input") for head in heads),
            ),
        ),
        groups=(
            GroupSpec("root", ("hub", "corridor", "row"), LayoutSpec("column", gap=pt(24))),
            GroupSpec(
                "row",
                tuple(head.id for head in heads),
                LayoutSpec("row", gap=pt(24), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def test_lint_treats_transparent_kinds_as_air_like_the_router_does() -> None:
    """R17: a spacer draws no body, so crossing one is not an obstacle defect."""

    for figure in (_transparent_edge_figure(), _transparent_net_figure()):
        compilation = compile_figure(figure)
        spacer = next(
            node
            for node in compilation.routed.fitted.nodes
            if node.measured.spec.kind == "spacer"
        )
        crossed = tuple(
            segment
            for route in (
                *(edge.centerline for edge in compilation.routed.edges),
                *(
                    stem.centerline
                    for net in compilation.routed.nets
                    for stem in net.source_stems + net.target_stems
                ),
            )
            for segment in segments(route)
            if segment.intersects_rect_interior(spacer.bounds)
        )
        assert crossed, "the fixture must actually route through the spacer"
        assert lint_compilation(compilation).ok


def test_skip_trunk_and_head_taps_run_through_block_centres() -> None:
    """R14: net taps sit on the centre of the block they leave or enter."""

    compilation = compile_figure(gallery_figure("modelangelo-gnn"))
    fitted = compilation.fitted
    for net_id, hub_id in (
        ("skip.previous", "band1.previous"),
        ("skip.cryo", "strip1.addln1"),
        ("skip.sequence", "strip2.addln2"),
        ("heads.fan-out", "strip3.addln3"),
    ):
        net = compilation.routed.net(net_id)
        centre = fitted.node(hub_id).bounds.center.x
        (trunk,) = net.source_stems
        assert trunk.centerline[0].x == centre
        if net_id != "heads.fan-out":
            assert net.rail[0].x == net.rail[-1].x == centre
    for stem in compilation.routed.net("heads.fan-out").target_stems:
        head = fitted.node(stem.port.node_id)
        assert stem.centerline[0].x == head.bounds.center.x
        assert stem.centerline == (
            Point(head.bounds.center.x, stem.centerline[0].y),
            head.port("input").position,
        )


def test_attention_merges_read_as_one_formula_labelled_arrow() -> None:
    """R20: the attention is a merge whose queries run straight into the sink.

    Supersedes the R18 test of the attention *component*: panel-b no longer draws
    the matrix. Each module merges its query vector with a second source into the
    attended value, and the query leg plus the arrival have to read as the single
    horizontal arrow the formula label sits above.
    """

    compilation = compile_figure(gallery_figure("modelangelo-gnn"))
    routed = compilation.routed
    for net_id, query_id in (
        ("band1.cryo.attention", "band1.cryo.q.cells"),
        ("band2.sequence.attention", "band2.sequence.q.cells"),
        ("band3.ipa.attention", "band3.ipa.qv.cells"),
    ):
        net = routed.net(net_id)
        assert net.spec.kind == "merge"
        query = next(
            stem for stem in net.source_stems if stem.port.node_id == query_id
        )
        (arrival,) = net.target_stems
        assert len(query.centerline) == 2, "the query leaves east and does not bend"
        assert query.centerline[0].y == query.centerline[-1].y
        assert arrival.centerline[0].y == query.centerline[0].y, "one straight arrow"
        assert arrival.centerline[-1].y == query.centerline[0].y
        assert net.label_position is not None and net.label_metrics is not None
        assert net.label_position.y < query.centerline[0].y, "formula above the arrow"
        assert query.centerline[0].x <= net.label_position.x <= arrival.centerline[-1].x
        (riser,) = tuple(
            stem for stem in net.source_stems if stem.port.node_id != query_id
        )
        rail = segments(net.rail)
        assert any(_on_segment(riser.centerline[-1], run) for run in rail), (
            "the second source joins the shared rail"
        )
        assert any(_on_segment(arrival.centerline[0], run) for run in rail)


def _on_segment(point: Point, segment: Segment) -> bool:
    if segment.horizontal:
        low, high = sorted((segment.start.x, segment.end.x))
        return point.y == segment.start.y and low <= point.x <= high
    low, high = sorted((segment.start.y, segment.end.y))
    return point.x == segment.start.x and low <= point.y <= high


def test_junction_dots_never_sit_on_a_rail_corner() -> None:
    """R21: a filleted corner cuts across the bend, so a dot there would float.

    Rails are straight today; this pins the invariant that keeps the 6 pt elbow
    radius compatible with junction dots if one ever bends.
    """

    for name in ("vertical-slice", "modelangelo-gnn"):
        compilation = compile_figure(gallery_figure(name))
        for net in compilation.routed.nets:
            corners = set(net.rail[1:-1])
            assert not corners & set(net.junctions)


def test_ipa_graph_output_rises_north_without_doubling_back() -> None:
    """R16/R20: the north output faces the merge rail, so the leg never reverses."""

    compilation = compile_figure(gallery_figure("modelangelo-gnn"))
    routed = compilation.routed
    graph = routed.fitted.node("band3.ipa.graph")
    assert graph.port("output").side is Side.NORTH
    net = routed.net("band3.ipa.attention")
    stem = next(item for item in net.source_stems if item.port.node_id == "band3.ipa.graph")
    assert stem.centerline[0] == graph.port("output").position
    assert len(stem.centerline) == 2, "one straight climb into the rail"
    assert stem.centerline[-1].x == stem.centerline[0].x
    assert stem.centerline[-1].y < stem.centerline[0].y


def test_rail_label_anchors_above_the_longest_horizontal_run() -> None:
    """R20: a net caption belongs to the arrow, not to the rail that feeds it."""

    style = LayoutStyle()
    metrics = TextMeasurer(style.typography).measure((TextRun("softmax(QK"),))
    rail = (Point(40.0, 10.0), Point(40.0, 30.0))
    # The rail drops *below* the run here, so nothing climbs through the caption
    # and the words keep the whole collinear stretch.
    stems = (
        (Point(0.0, 10.0), Point(40.0, 10.0)),
        (Point(40.0, 10.0), Point(90.0, 10.0)),
        (Point(20.0, 30.0), Point(40.0, 30.0)),
    )
    position = rail_label_position(rail, stems, metrics, style)
    assert position.y < 10.0, "above the run"
    assert position.x == 45.0, "centred on the collinear run, not on the rail"
    assert position.y == pytest.approx(10.0 - caption_rise(metrics, style))
    # With no horizontal ink at all the rail midpoint still carries the caption.
    vertical = rail_label_position(
        rail,
        ((Point(40.0, 10.0), Point(40.0, 30.0)),),
        metrics,
        style,
    )
    assert vertical.y == 20.0
    assert vertical.x == pytest.approx(
        40.0 + metrics.width / 2.0 + caption_reach(metrics, style)
    )


def test_a_caption_clears_the_riser_that_climbs_through_its_band() -> None:
    """R24: a riser out of the middle of a run cuts the run the caption may use.

    The words go over the wider of the two stretches the riser leaves, keeping
    ``caption_clearance`` off the vertical ink -- the panel-b defect where
    ``softmax(QK^T)V`` ended flush against the K,V riser.
    """

    style = LayoutStyle()
    metrics = TextMeasurer(style.typography).measure((TextRun("softmax(QK"),))
    rail = (Point(70.0, -20.0), Point(70.0, 10.0))  # climbs into the run's band
    stems = ((Point(0.0, 10.0), Point(70.0, 10.0)), (Point(70.0, 10.0), Point(80.0, 10.0)))
    position = rail_label_position(rail, stems, metrics, style)
    clearance = caption_reach(metrics, style)
    assert position.x + metrics.width / 2.0 <= 70.0 - clearance, "clear of the riser"
    assert position.x == pytest.approx((0.0 + 70.0 - clearance) / 2.0)


def test_the_panel_b_formulas_clear_both_their_run_and_their_riser() -> None:
    """Every merge caption in panel b keeps its clearance from all the net's ink."""

    style = LayoutStyle()
    routed = compile_figure(gallery_figure("modelangelo-gnn")).routed
    for net_id in ("band1.cryo.attention", "band2.sequence.attention", "band3.ipa.attention"):
        net = routed.net(net_id)
        assert net.label_metrics is not None and net.label_position is not None
        descent = ink_descent(net.label_metrics, style.typography)
        bottom = net.label_position.y + descent
        left = net.label_position.x - net.label_metrics.width / 2.0
        right = net.label_position.x + net.label_metrics.width / 2.0
        top = net.label_position.y - net.label_metrics.ascent
        caption = Rect(left, top, right - left, bottom - top)
        half = style.connector_width.points / 2.0
        for segment in net_segments(net):
            ink = Rect(
                min(segment.start.x, segment.end.x) - half,
                min(segment.start.y, segment.end.y) - half,
                abs(segment.end.x - segment.start.x) + 2.0 * half,
                abs(segment.end.y - segment.start.y) + 2.0 * half,
            )
            gap = _rect_gap(caption, ink)
            assert gap >= style.caption_clearance.points - 1e-6, (
                f"{net_id} caption is {gap:.2f} pt from {segment}"
            )


def _rect_gap(first: Rect, second: Rect) -> float:
    """Nearest distance between two axis-aligned rectangles, 0 if they touch."""

    dx = max(first.x - second.right, second.x - first.right, 0.0)
    dy = max(first.y - second.bottom, second.y - first.bottom, 0.0)
    return max(dx, dy) if (dx == 0.0 or dy == 0.0) else (dx * dx + dy * dy) ** 0.5


def _riser_merge_figure(**net_options: object) -> FigureSpec:
    """Panel-b's attention shape: one straight trunk plus one riser into a sink.

    The trunk and the sink share a row, so the merge draws one horizontal run
    from ``trunk`` to ``sink`` with the riser climbing into it -- exactly the
    geometry ``rail_at`` measures along.
    """

    trunk = NodeSpec("trunk", "block", (TextRun("Q"),), ports=(PortSpec("e", Side.EAST),))
    riser = NodeSpec("riser", "block", (TextRun("KV"),), ports=(PortSpec("e", Side.EAST),))
    sink = NodeSpec("sink", "block", (TextRun("A"),), ports=(PortSpec("w", Side.WEST),))
    return FigureSpec(
        "riser-merge",
        width=pt(260),
        nodes=(trunk, riser, sink),
        nets=(
            NetSpec(
                "combined",
                "merge",
                (PortRef("trunk", "e"), PortRef("riser", "e")),
                (PortRef("sink", "w"),),
                **net_options,  # type: ignore[arg-type]
            ),
        ),
        groups=(
            GroupSpec("root", ("sources", "sink"), LayoutSpec("row", gap=pt(40), align="start")),
            GroupSpec(
                "sources",
                ("trunk", "riser"),
                LayoutSpec("column", gap=pt(30), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def test_an_unhinted_rail_sits_in_the_middle_of_its_corridor() -> None:
    """R9: with no hint at all the rail halves the gap its stems leave it.

    The corridor runs from the sources' escapes at x=63 to the sink's at x=84,
    so the rail lands at 73.5 -- trunk and stems each get half the run, instead
    of the rail hugging the sink it feeds.
    """

    compilation = compile_figure(_riser_merge_figure())
    net = compilation.routed.net("combined")
    assert net.spec.rail_at is None and net.spec.joint == "auto"
    assert net.rail == (Point(73.5, 28.0), Point(73.5, 86.0))
    assert tuple(stem.centerline for stem in net.source_stems) == (
        (Point(58.0, 28.0), Point(73.5, 28.0)),
        (Point(58.0, 86.0), Point(73.5, 86.0)),
    )
    assert tuple(stem.centerline for stem in net.target_stems) == (
        (Point(73.5, 28.0), Point(98.0, 28.0)),
    )
    assert net.diagnostics == ()
    assert compilation.document.text.count('id="combined.junction.1"') == 1
    assert lint_compilation(compilation).ok


def test_a_captioned_rail_leaves_its_caption_the_run() -> None:
    """A corridor too narrow to halve keeps the rail at its end, not in the words.

    The caption is written above the run the net reads along, so a rail parked in
    the middle of the corridor would be drawn straight through it.
    """

    labelled = compile_figure(_riser_merge_figure(label=(TextRun("softmax(QK"),)))
    net = labelled.routed.net("combined")
    assert net.rail == (Point(84.0, 28.0), Point(84.0, 86.0)), "one escape short of the sink"
    assert net.label_metrics is not None and net.label_position is not None
    assert net.label_position.x < net.rail[0].x, "and the caption owns the whole run"
    assert lint_compilation(labelled).ok


def test_rail_at_slides_the_rail_along_the_trunk_run() -> None:
    """R20: an authored fraction places the joint, measured from the trunk's start."""

    for fraction, expected in ((0.25, 68.0), (0.5, 78.0), (0.6, 82.0)):
        compilation = compile_figure(_riser_merge_figure(rail_at=fraction))
        net = compilation.routed.net("combined")
        # The run leaves trunk.e at x=58 and ends on sink.w at x=98.
        assert net.rail[0].x == net.rail[-1].x == expected
        assert net.rail[0].x == 58.0 + fraction * 40.0
        assert net.diagnostics == ()
        assert lint_compilation(compilation).ok


def test_a_fan_out_measures_its_run_from_the_shared_source() -> None:
    """R9: the two kinds read the same fraction in opposite directions."""

    figure = _vertical_net_figure()
    net = figure.nets[0]
    routed = compile_figure(
        FigureSpec(
            figure.id,
            width=figure.width,
            nodes=figure.nodes,
            nets=(NetSpec(net.id, net.kind, net.sources, net.targets, rail_at=0.25),),
            groups=figure.groups,
        )
    ).routed.net("shared")
    fitted = compile_figure(figure).fitted
    source = fitted.node("source").port("s").position.y
    far = max(
        fitted.node(f"target{index}").port("n").position.y for index in range(1, 4)
    )
    assert routed.rail[0].y == pytest.approx(source + 0.25 * (far - source))


def test_an_unreachable_rail_at_is_clamped_and_says_so() -> None:
    """A placement hint is a request: the router may overrule it, but not quietly."""

    compilation = compile_figure(_riser_merge_figure(rail_at=0.97))
    net = compilation.routed.net("combined")
    # 0.97 of the run lands inside the sink's arrival clearance, so the rail
    # falls back to the nearest position that still clears it.
    assert net.rail[0].x == 84.0
    (diagnostic,) = net.diagnostics
    assert diagnostic.code == "routing.net.rail-at.clamped"
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.entity_id == "combined"
    assert "0.650" in diagnostic.message
    report = lint_compilation(compilation)
    assert report.ok, "a clamped hint is a warning, never an error"
    assert diagnostic in report.warnings


def test_rail_at_refuses_a_fraction_outside_the_run() -> None:
    for fraction in (0.0, 1.0, -0.5, 1.4):
        with pytest.raises(ValueError, match="strictly between 0 and 1"):
            _riser_merge_figure(rail_at=fraction)


def test_a_rail_side_hint_and_a_fraction_cannot_place_the_same_rail() -> None:
    with pytest.raises(ValueError, match="places its rail twice"):
        _riser_merge_figure(rail_at=0.5, rail_hint=Side.EAST)


def test_an_arrow_joint_stands_off_the_trunk_it_points_into() -> None:
    """R20: the branch ends in an arrowhead; the trunk it meets stays unbroken."""

    style = LayoutStyle()
    compilation = compile_figure(_riser_merge_figure(rail_at=0.5, joint="arrow"))
    net = compilation.routed.net("combined")
    (arrival,) = net.target_stems
    joint = arrival.centerline[0]
    assert joint == Point(78.0, 28.0), "the branch still meets the trunk exactly"
    ink = _net_ink(
        net,
        style.elbow_radius.points,
        arrow_length=style.arrow_length.points,
        standoff=style.connector_standoff.points,
    )
    assert not ink.dots, "the arrowhead stands in for the junction dot"
    (rail_id, points, arrow) = ink.rails[0]
    assert (rail_id, arrow) == ("combined.rail", True)
    # The marker is anchored at the path end and its tip reaches a full arrow
    # further on, so this leaves the tip exactly one standoff short of the trunk.
    tip = points[-1].distance_to(joint) - style.arrow_length.points
    assert tip == pytest.approx(style.connector_standoff.points)
    trunk = next(stem for stem in net.source_stems if stem.port.node_id == "trunk")
    assert trunk.shaft[-1] == joint and arrival.shaft[0] == joint
    assert [stem_id for stem_id, _, arrow in ink.stems if arrow] == ["combined.target.1"], (
        "the rail carries the joint marker, so no stem gains one"
    )
    assert lint_compilation(compilation).ok
