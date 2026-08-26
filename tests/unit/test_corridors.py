"""R33: side margins shared by several long runs, reserved and handed out."""

from __future__ import annotations

from itertools import pairwise

import pytest

from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.gallery import GALLERY
from flexo.geometry import Side
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
    Waypoint,
)
from flexo.layout import fit_figure, measure_figure
from flexo.layout.corridors import (
    EMPTY_PLAN,
    corridor_plan,
    margin_clearance,
    track_coordinate,
    track_pitch,
)
from flexo.lint import lint_compilation
from flexo.routing import route_figure
from flexo.style import LayoutStyle
from flexo.units import pt

_PORTS = (
    PortSpec("input", Side.NORTH, 0.5),
    PortSpec("output", Side.SOUTH, 0.5),
    PortSpec("west", Side.WEST, 0.5),
    PortSpec("east", Side.EAST, 0.5),
)


def tower(*runs: EdgeSpec, blocks: int = 6, align: str = "stretch") -> FigureSpec:
    """A column of blocks chained top to bottom, plus whatever long runs are asked for."""

    names = [f"block{index}" for index in range(blocks)]
    chain = tuple(
        EdgeSpec(
            f"chain{index}",
            PortRef(names[index], "output"),
            PortRef(names[index + 1], "input"),
        )
        for index in range(blocks - 1)
    )
    return FigureSpec(
        "corridors",
        width=pt(320),
        nodes=tuple(
            NodeSpec(name, "block", (TextRun(name.title()),), ports=_PORTS) for name in names
        ),
        edges=chain + runs,
        groups=(
            GroupSpec("root", tuple(names), LayoutSpec("column", gap=pt(18), align=align)),
        ),
    )


def bands(*runs: EdgeSpec, blocks: int = 4) -> FigureSpec:
    """Three bands, and a container whose blocks are reached from the side.

    The shape the see-more integration figure is built from: a band of feeds, a
    module holding a boundary strip above a chain of blocks, and a band of
    sinks below. Every long run here attaches to an *east* port of a block deep
    inside the middle module, so it has to travel that module's east margin to
    the height it attaches at -- and the strip, which is nobody's child of that
    module, stands in the same margin.
    """

    names = [f"b{index}" for index in range(blocks)]
    nodes = [
        NodeSpec(name, "block", (TextRun(name.upper()),), width=pt(120), ports=_PORTS)
        for name in names
    ]
    nodes += [
        NodeSpec("feed-a", "block", (TextRun("Feed A"),), ports=_PORTS),
        NodeSpec("feed-b", "block", (TextRun("Feed B"),), ports=_PORTS),
        NodeSpec("strip", "block", (TextRun("Boundary strip"),), width=pt(150), ports=_PORTS),
        NodeSpec("sink", "block", (TextRun("Sink"),), ports=_PORTS),
    ]
    chain = tuple(
        EdgeSpec(
            f"chain{index}",
            PortRef(names[index], "output"),
            PortRef(names[index + 1], "input"),
        )
        for index in range(blocks - 1)
    )
    return FigureSpec(
        "bands",
        width=pt(420),
        nodes=tuple(nodes),
        edges=chain + runs,
        groups=(
            GroupSpec("root", ("band1", "stack", "band3"), LayoutSpec("column", gap=pt(30))),
            GroupSpec("band1", ("feed-a", "feed-b"), LayoutSpec("row", gap=pt(20)), role="module"),
            GroupSpec(
                "stack",
                ("strip", "layer"),
                LayoutSpec("column", gap=pt(24), width=pt(340)),
                role="module",
            ),
            GroupSpec("layer", tuple(names), LayoutSpec("column", gap=pt(18)), role="module"),
            GroupSpec("band3", ("sink",), LayoutSpec("row"), role="module"),
        ),
    )


def traversals() -> FigureSpec:
    """``bands`` with the three runs that contend for the middle module's margin."""

    return bands(
        EdgeSpec("feed-1", PortRef("feed-a", "east"), PortRef("b1", "east")),
        EdgeSpec("feed-3", PortRef("feed-b", "east"), PortRef("b3", "east")),
        EdgeSpec("tap", PortRef("b2", "east"), PortRef("sink", "east")),
    )


def west_run(edge_id: str, source: int, target: int, **extra: object) -> EdgeSpec:
    return EdgeSpec(
        edge_id,
        PortRef(f"block{source}", "west"),
        PortRef(f"block{target}", "west"),
        **extra,  # type: ignore[arg-type]
    )


def corridor_x(routed, edge_id: str) -> float:
    """The coordinate of the longest vertical run this edge travels down."""

    centerline = routed.edge(edge_id).centerline
    return max(
        (abs(end.y - start.y), start.x)
        for start, end in pairwise(centerline)
        if start.x == end.x
    )[1]


def corridor_y(routed, edge_id: str) -> float:
    """The coordinate of the longest horizontal run this edge travels along."""

    centerline = routed.edge(edge_id).centerline
    return max(
        (abs(end.x - start.x), start.y)
        for start, end in pairwise(centerline)
        if start.y == end.y
    )[1]


def test_one_long_run_leaves_the_margin_exactly_as_it_found_it() -> None:
    """The status quo is a corridor: a lone run gets the margin the group already has."""

    figure = tower(west_run("solo", 0, 5))
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.WEST): 1}
    assert plan.corridors == {}
    style = LayoutStyle()
    group = figure.groups[0]
    assert plan.padding(group, style) == group.layout.resolved_padding(style.group_padding)


def test_a_contested_margin_is_widened_to_hold_every_track() -> None:
    """R33 part one: two runs in one margin buy the width of two tracks before fit."""

    figure = tower(west_run("outer", 0, 5), west_run("inner", 1, 4))
    style = LayoutStyle()
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.WEST): 2}
    reserve = plan.reserve("root", style)
    expected = style.route_boundary_clearance.points + margin_clearance(style) + track_pitch(style)
    assert reserve.left == pytest.approx(expected) == pytest.approx(28.0)
    assert (reserve.top, reserve.right, reserve.bottom) == (0.0, 0.0, 0.0)
    # And the fitted figure really carries it: the content edge moved out by the
    # difference between the reservation and the padding the style would give.
    fitted = fit_figure(measure_figure(figure))
    root = fitted.group("root")
    assert root.content_bounds.left - root.bounds.left == pytest.approx(28.0)


def test_the_reservation_is_what_makes_the_second_run_routable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the width bought before fit, the outer track falls outside the boundary."""

    figure = tower(west_run("outer", 0, 5), west_run("inner", 1, 4))
    assert route_figure(fit_figure(measure_figure(figure))) is not None
    assert EMPTY_PLAN.padding(figure.groups[0], LayoutStyle()).left == pytest.approx(14.0)
    for module in ("flexo.layout.fit", "flexo.layout.measure"):
        monkeypatch.setattr(f"{module}.corridor_plan", lambda _figure: EMPTY_PLAN)
    with pytest.raises(FlexoError, match=r"routing\.no-path"):
        route_figure(fit_figure(measure_figure(figure)))


def test_nested_runs_nest_and_the_deeper_reach_takes_the_outer_track() -> None:
    """R33 part two: the planar order, read off the geometry rather than asserted."""

    figure = tower(west_run("outer", 0, 5), west_run("inner", 1, 4))
    plan = corridor_plan(figure)
    assert plan.corridor("outer").track == 1
    assert plan.corridor("inner").track == 0
    style = LayoutStyle()
    fitted = fit_figure(measure_figure(figure))
    outer = track_coordinate(fitted, plan, plan.corridor("outer"), style)
    inner = track_coordinate(fitted, plan, plan.corridor("inner"), style)
    assert outer == pytest.approx(inner - track_pitch(style)), "west: outer is further west"
    routed = route_figure(fitted)
    assert corridor_x(routed, "outer") == pytest.approx(outer)
    assert corridor_x(routed, "inner") == pytest.approx(inner)
    # Planar means exactly this: nobody crosses anybody, and lint agrees.
    report = lint_compilation(compile_figure(figure))
    assert not [
        diagnostic
        for diagnostic in report.diagnostics
        if diagnostic.code == "routing.connector.crossing"
    ]


def test_an_interval_that_only_touches_another_shares_its_track() -> None:
    """Two skips meeting at one block are end to end, not parallel: one track does."""

    figure = tower(west_run("upper", 0, 2), west_run("lower", 2, 4))
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.WEST): 1}
    assert plan.corridors == {}


def test_an_authored_lane_still_outranks_the_engines_arithmetic() -> None:
    """``lane=`` keeps its corridor, and is not counted into anyone else's."""

    figure = tower(
        west_run("outer", 0, 6),
        west_run("authored", 1, 5, lane_hint="root-left"),
        west_run("inner", 2, 4),
        blocks=7,
    )
    plan = corridor_plan(figure)
    assert "authored" not in plan.corridors, "the author already chose this corridor"
    assert plan.margins == {("root", Side.WEST): 2}
    assert plan.corridor("outer").track == 1
    assert plan.corridor("inner").track == 0
    style = LayoutStyle()
    fitted = fit_figure(measure_figure(figure))
    routed = route_figure(fitted)
    lane = fitted.group("root").bounds.left + style.route_boundary_clearance.points
    assert corridor_x(routed, "authored") == pytest.approx(lane)
    assert corridor_x(routed, "outer") == pytest.approx(
        track_coordinate(fitted, plan, plan.corridor("outer"), style)
    )


def test_a_row_hands_out_the_margins_below_it() -> None:
    """The same reading one axis over: a row's long runs travel north or south."""

    names = tuple(f"block{index}" for index in range(5))
    figure = FigureSpec(
        "corridors-row",
        width=pt(420),
        nodes=tuple(
            NodeSpec(name, "block", (TextRun(name.title()),), ports=_PORTS) for name in names
        ),
        edges=(
            EdgeSpec("outer", PortRef("block0", "output"), PortRef("block4", "output")),
            EdgeSpec("inner", PortRef("block1", "output"), PortRef("block3", "output")),
        ),
        groups=(GroupSpec("root", names, LayoutSpec("row", gap=pt(18), align="stretch")),),
    )
    style = LayoutStyle()
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.SOUTH): 2}
    assert (plan.corridor("outer").track, plan.corridor("inner").track) == (1, 0)
    assert plan.reserve("root", style).bottom == pytest.approx(28.0)
    fitted = fit_figure(measure_figure(figure))
    outer = track_coordinate(fitted, plan, plan.corridor("outer"), style)
    inner = track_coordinate(fitted, plan, plan.corridor("inner"), style)
    assert outer == pytest.approx(inner + track_pitch(style)), "south: outer is further down"
    routed = route_figure(fitted)
    assert corridor_y(routed, "outer") == pytest.approx(outer)
    assert corridor_y(routed, "inner") == pytest.approx(inner)
    assert not lint_compilation(compile_figure(figure)).diagnostics


def test_a_run_with_nothing_to_say_about_its_side_takes_the_conventional_one() -> None:
    """Both ports on the layout axis: east for a column, the way a skip bows out."""

    figure = tower(
        EdgeSpec("skip", PortRef("block0", "output"), PortRef("block4", "input")),
        EdgeSpec("shorter", PortRef("block1", "output"), PortRef("block3", "input")),
    )
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.EAST): 2}
    assert (plan.corridor("skip").track, plan.corridor("shorter").track) == (1, 0)


def test_a_run_leaving_east_and_arriving_west_claims_neither_margin() -> None:
    """One margin cannot hold both ends of it, so the router keeps the whole job."""

    figure = tower(
        EdgeSpec("across", PortRef("block0", "east"), PortRef("block5", "west")),
    )
    assert corridor_plan(figure).margins == {}


def test_a_waypointed_run_is_left_to_the_author() -> None:
    figure = tower(
        west_run("solo", 0, 5),
        west_run("aimed", 1, 4, waypoints=(Waypoint(reference="block2", dx=pt(-30)),)),
    )
    plan = corridor_plan(figure)
    assert plan.margins == {("root", Side.WEST): 1}
    assert plan.corridors == {}


def test_a_side_port_deep_inside_a_container_claims_that_containers_margin() -> None:
    """R33 round 14: adjacent bands, and still a run the whole depth of a margin."""

    plan = corridor_plan(traversals())
    assert plan.margins == {("layer", Side.EAST): 2}, "the container threaded, not the root"
    assert plan.claimants[("layer", Side.EAST)] == ("feed-1", "feed-3", "tap")
    # Reach decides: the feed that drops furthest into the stack takes the outer
    # track, and the tap -- which never shares the margin with the short feed --
    # takes the inner one back.
    assert plan.corridor("feed-1").track == 0
    assert plan.corridor("feed-3").track == 1
    assert plan.corridor("tap").track == 0


def test_a_traversal_margin_reserves_its_width_before_fit() -> None:
    figure = traversals()
    style = LayoutStyle()
    reserve = corridor_plan(figure).reserve("layer", style)
    assert reserve.right == pytest.approx(
        style.route_boundary_clearance.points + margin_clearance(style) + track_pitch(style)
    )
    fitted = fit_figure(measure_figure(figure))
    layer = fitted.group("layer")
    assert layer.bounds.right - layer.content_bounds.right == pytest.approx(reserve.right)


def test_a_traversal_corridor_clears_what_intrudes_on_the_margin() -> None:
    """The strip is nobody's child of the layer, and stands in its margin anyway."""

    figure = traversals()
    style = LayoutStyle()
    plan = corridor_plan(figure)
    fitted = fit_figure(measure_figure(figure))
    deepest = max(fitted.node(f"b{index}").bounds.right for index in range(4))
    strip = fitted.node("strip").bounds.right
    assert strip > deepest, "the fixture only tests anything while the strip sticks out"
    inner = track_coordinate(fitted, plan, plan.corridor("feed-1"), style)
    assert inner == pytest.approx(strip + margin_clearance(style))


def test_traversal_runs_route_on_their_own_tracks_one_pitch_apart() -> None:
    figure = traversals()
    style = LayoutStyle()
    plan = corridor_plan(figure)
    fitted = fit_figure(measure_figure(figure))
    routed = route_figure(fitted)
    inner = track_coordinate(fitted, plan, plan.corridor("feed-1"), style)
    outer = track_coordinate(fitted, plan, plan.corridor("feed-3"), style)
    assert outer == pytest.approx(inner + track_pitch(style))
    assert corridor_x(routed, "feed-1") == pytest.approx(inner)
    assert corridor_x(routed, "tap") == pytest.approx(inner), "disjoint runs share a track"
    assert corridor_x(routed, "feed-3") == pytest.approx(outer)
    # Every remaining crossing is one the interval structure forces, and each is
    # bridged rather than warned about.
    report = lint_compilation(compile_figure(figure))
    assert {diagnostic.code for diagnostic in report.diagnostics} <= {"routing.connector.hop"}


def test_an_authored_lane_takes_a_traversal_out_of_the_engines_margin() -> None:
    figure = bands(
        EdgeSpec("feed-1", PortRef("feed-a", "east"), PortRef("b1", "east")),
        EdgeSpec(
            "feed-3",
            PortRef("feed-b", "east"),
            PortRef("b3", "east"),
            lane_hint="stack-right",
        ),
        EdgeSpec("tap", PortRef("b2", "east"), PortRef("sink", "east")),
    )
    plan = corridor_plan(figure)
    assert plan.margins == {("layer", Side.EAST): 1}
    assert plan.corridors == {}
    style = LayoutStyle()
    fitted = fit_figure(measure_figure(figure))
    lane = fitted.group("stack").bounds.right - style.route_boundary_clearance.points
    assert corridor_x(route_figure(fitted), "feed-3") == pytest.approx(lane)


def test_a_grid_row_a_run_never_passes_claims_nothing() -> None:
    """Non-adjacent rows are not the test; an occupied cell in the same lane is.

    A grid whose intervening row sits in another column leaves the straight drop
    open, and a lane holder reserved for the connector itself is not something
    the connector has to go around.
    """

    ports = _PORTS
    figure = FigureSpec(
        "grid",
        width=pt(300),
        nodes=(
            NodeSpec("top", "block", (TextRun("Top"),), ports=ports),
            NodeSpec("aside", "block", (TextRun("Aside"),), ports=ports),
            NodeSpec("lane", "spacer", height=pt(10)),
            NodeSpec("bottom", "block", (TextRun("Bottom"),), ports=ports),
        ),
        edges=(EdgeSpec("drop", PortRef("top", "output"), PortRef("bottom", "input")),),
        groups=(
            GroupSpec(
                "root",
                ("top", "aside", "lane", "bottom"),
                LayoutSpec(
                    "grid",
                    columns=2,
                    placements=(
                        ("top", 0, 0),
                        ("aside", 1, 1),
                        ("lane", 1, 0),
                        ("bottom", 2, 0),
                    ),
                ),
            ),
        ),
    )
    assert corridor_plan(figure).margins == {}


@pytest.mark.parametrize("name", sorted(GALLERY))
def test_every_shipped_figure_leaves_its_margins_uncontested(name: str) -> None:
    """The conservatism bar: nothing in the gallery has a margin to hand out."""

    figure = GALLERY[name]()
    plan = corridor_plan(figure)
    assert plan.corridors == {}
    assert max(plan.margins.values(), default=0) <= 1
    style = LayoutStyle()
    for group in figure.groups:
        assert plan.padding(group, style) == group.layout.resolved_padding(style.group_padding)


@pytest.mark.parametrize("name", sorted(GALLERY))
def test_a_figure_that_routes_clean_today_is_byte_identical(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compile it twice -- corridors armed, corridors disabled -- and diff the SVG."""

    figure = GALLERY[name]()
    armed = compile_figure(figure).document.text
    for module in ("flexo.layout.fit", "flexo.layout.measure", "flexo.routing.solve"):
        monkeypatch.setattr(f"{module}.corridor_plan", lambda _figure: EMPTY_PLAN)
    assert compile_figure(figure).document.text == armed
