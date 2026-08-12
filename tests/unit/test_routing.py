from __future__ import annotations

from flexo.geometry import Side, segments
from flexo.ir.semantic import EdgeSpec, FigureSpec, GroupSpec, LayoutSpec, NodeSpec, PortRef
from flexo.layout import fit_figure, measure_figure
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
