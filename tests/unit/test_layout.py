from __future__ import annotations

from dataclasses import replace

import pytest

from flexo.builder import Figure
from flexo.components import (
    TRANSPARENT_KINDS,
    attachment_lane_tracks,
    component_port_offsets,
    route_clearance,
)
from flexo.diagnostics import FlexoError, Severity
from flexo.gallery import gallery_figure
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
from flexo.layout.ports import (
    _CENTER_BAND_FRACTION,
    _adapt_endpoint_ports,
    _port_positions,
)
from flexo.routing import route_figure
from flexo.style import STYLES, LayoutStyle, vector_stack_height
from flexo.units import CellSpan, pt


def row_figure(*, label: str = "Short") -> FigureSpec:
    return FigureSpec(
        "rows",
        width=pt(180),
        nodes=(
            NodeSpec("first", "block", (TextRun(label),)),
            NodeSpec("second", "mlp", (TextRun("Projection"),)),
        ),
        groups=(
            GroupSpec(
                "root",
                ("first", "second"),
                LayoutSpec("row", justify="space-between"),
            ),
        ),
    )


def test_row_layout_is_disjoint_and_contained() -> None:
    fitted = fit_figure(measure_figure(row_figure()))
    first = fitted.node("first").bounds
    second = fitted.node("second").bounds
    root = fitted.group("root").content_bounds
    assert not first.intersects(second)
    assert root.contains_rect(first)
    assert root.contains_rect(second)
    assert first.left < second.left


def test_label_change_updates_intrinsic_geometry() -> None:
    short = measure_figure(row_figure(label="Short")).node("first").intrinsic_size.width
    long = measure_figure(
        row_figure(label="A substantially longer processing stage")
    ).node("first").intrinsic_size.width
    assert long > short


def test_fixed_boundary_reports_local_overflow() -> None:
    figure = FigureSpec(
        "overflow",
        width=pt(100),
        nodes=(NodeSpec("wide", "block", (TextRun("Much too wide for this box"),)),),
        groups=(
            GroupSpec(
                "root",
                ("module",),
                LayoutSpec("row"),
            ),
            GroupSpec(
                "module",
                ("wide",),
                LayoutSpec("row", width=pt(30), height=pt(30)),
            ),
        ),
    )
    with pytest.raises(FlexoError, match=r"layout\.overflow"):
        fit_figure(measure_figure(figure))


def test_dense_sibling_routes_reserve_a_lane_gutter() -> None:
    source_ports = tuple(
        PortSpec(f"out{index}", Side.EAST, offset)
        for index, offset in enumerate((0.25, 0.5, 0.75), start=1)
    )
    target_ports = tuple(
        PortSpec(f"in{index}", Side.WEST, offset)
        for index, offset in enumerate((0.25, 0.5, 0.75), start=1)
    )
    figure = FigureSpec(
        "dense-routes",
        width=pt(180),
        nodes=(
            NodeSpec("source", "block", ports=source_ports),
            NodeSpec("target", "block", ports=target_ports),
        ),
        edges=tuple(
            EdgeSpec(
                f"flow{index}",
                PortRef("source", f"out{index}"),
                PortRef("target", f"in{index}"),
            )
            for index in range(1, 4)
        ),
        groups=(
            GroupSpec(
                "root",
                ("source", "target"),
                LayoutSpec("row", gap=pt(10), justify="start"),
            ),
        ),
    )

    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source").bounds
    target = routed.fitted.node("target").bounds
    style = LayoutStyle()
    target_clearance = max(
        style.route_clearance.points,
        2 * style.arrow_length.points + style.elbow_radius.points,
    )
    # Three routes cross this boundary, so it reserves two lanes at the pitch the
    # router enforces between parallel tracks.
    lane_spacing = max(style.route_lane_spacing.points, style.port_spacing.points)
    expected = style.route_clearance.points + target_clearance + 2 * lane_spacing
    assert target.left - source.right == expected
    for edge in routed.edges:
        route_segments = segments(edge.centerline)
        assert route_segments[0].length >= style.route_clearance.points
        assert route_segments[-1].length >= style.route_clearance.points


def test_adaptive_target_port_aligns_but_explicit_offset_stays_fixed() -> None:
    figure = FigureSpec(
        "adaptive-ports",
        width=pt(180),
        nodes=(
            NodeSpec("source", "block"),
            NodeSpec(
                "adaptive",
                "block",
                ports=(PortSpec("input", Side.WEST, adaptive=True),),
            ),
            NodeSpec(
                "fixed",
                "block",
                ports=(PortSpec("input", Side.WEST, 0.2),),
            ),
        ),
        edges=(
            EdgeSpec("to-adaptive", PortRef("source", "output"), PortRef("adaptive", "input")),
            EdgeSpec("to-fixed", PortRef("source", "output"), PortRef("fixed", "input")),
        ),
        groups=(
            GroupSpec(
                "root",
                ("source", "targets"),
                LayoutSpec("row", gap=pt(18)),
            ),
            GroupSpec(
                "targets",
                ("adaptive", "fixed"),
                LayoutSpec("column", gap=pt(10), padding=pt(0)),
                role="layout",
            ),
        ),
    )

    fitted = fit_figure(measure_figure(figure))
    source = fitted.node("source")
    adaptive = fitted.node("adaptive")
    # R18: the adaptive target sits far enough above the source that aligning
    # with it would leave the band, so it keeps its authored centre.
    assert adaptive.port("input").position.y == adaptive.bounds.center.y
    # The source serves both targets and slides toward their mean, because that
    # mean does lie inside its own band.
    drift = abs(source.port("output").position.y - source.bounds.center.y)
    assert 0.0 < drift <= _CENTER_BAND_FRACTION * source.bounds.height
    fixed = fitted.node("fixed")
    assert fixed.port("input").position.y == fixed.bounds.top + fixed.bounds.height * 0.2


def test_near_aligned_adaptive_pair_slides_into_one_straight_run() -> None:
    """R18: in-band sliding still absorbs a few-point mismatch, so no micro-jog."""

    offset = pt(4)
    figure = FigureSpec(
        "near-aligned",
        width=pt(220),
        nodes=(
            NodeSpec("shim", "spacer", height=offset),
            NodeSpec(
                "source",
                "block",
                (TextRun("Source"),),
                ports=(PortSpec("output", Side.EAST, adaptive=True),),
            ),
            NodeSpec(
                "target",
                "block",
                (TextRun("Target"),),
                ports=(PortSpec("input", Side.WEST, adaptive=True),),
            ),
        ),
        edges=(EdgeSpec("flow", PortRef("source", "output"), PortRef("target", "input")),),
        groups=(
            GroupSpec("root", ("left", "target"), LayoutSpec("row", gap=pt(40), align="start")),
            GroupSpec(
                "left",
                ("shim", "source"),
                LayoutSpec("column", gap=pt(0), padding=pt(0)),
                role="layout",
            ),
        ),
    )

    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source").port("output")
    target = routed.fitted.node("target").port("input")
    assert source.position.y == target.position.y
    assert routed.edge("flow").centerline == (source.position, target.position)


def test_adapted_gallery_ports_stay_inside_their_centre_band() -> None:
    """R18: adaptation fine-tunes alignment; it never walks a port off centre."""

    for name in ("vertical-slice", "modelangelo-gnn"):
        figure = gallery_figure(name)
        fitted = fit_figure(measure_figure(figure))
        for node in fitted.nodes:
            for spec in node.measured.spec.ports:
                if not spec.adaptive:
                    continue
                vertical = spec.side in {Side.EAST, Side.WEST}
                bounds = node.bounds
                home = bounds.point_on(spec.side, spec.offset)
                length = bounds.height if vertical else bounds.width
                position = node.port(spec.name).position
                drift = (
                    abs(position.y - home.y) if vertical else abs(position.x - home.x)
                )
                assert drift <= _CENTER_BAND_FRACTION * length + 1e-6


def _pair_figure(
    *,
    source_height: float,
    target_height: float,
    source_ports: tuple[PortSpec, ...],
    target_ports: tuple[PortSpec, ...],
    blocker_height: float | None = None,
) -> FigureSpec:
    """One row of adaptive ports, optionally with a component to pass on the way."""

    blocker = (
        (NodeSpec("blocker", "block", (TextRun("."),), height=pt(blocker_height)),)
        if blocker_height is not None
        else ()
    )
    children = ("source", *(node.id for node in blocker), "target")
    return FigureSpec(
        "adaptive-pair",
        width=pt(360),
        nodes=(
            NodeSpec(
                "source",
                "block",
                (TextRun("Source"),),
                height=pt(source_height),
                ports=source_ports,
            ),
            *blocker,
            NodeSpec(
                "target",
                "block",
                (TextRun("Target"),),
                height=pt(target_height),
                ports=target_ports,
            ),
        ),
        edges=tuple(
            EdgeSpec(
                f"flow{index}",
                PortRef("source", source.name),
                PortRef("target", target.name),
            )
            for index, (source, target) in enumerate(
                zip(source_ports, target_ports, strict=True), start=1
            )
        ),
        groups=(
            GroupSpec("root", children, LayoutSpec("row", gap=pt(40))),
        ),
    )


def test_solitary_adaptive_pair_ends_collinear_on_one_straight_segment() -> None:
    """R10: a one-to-one adaptive pair with room to agree leaves no jog behind."""

    figure = _pair_figure(
        source_height=80.0,
        target_height=28.0,
        source_ports=(PortSpec("output", Side.EAST, 0.25, adaptive=True),),
        target_ports=(PortSpec("input", Side.WEST, 0.5, adaptive=True),),
    )
    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source").port("output").position
    target = routed.fitted.node("target").port("input").position
    assert source.y == target.y
    assert routed.edge("flow1").centerline == (source, target)


def test_multi_output_adaptive_ports_stay_collinear_with_their_targets() -> None:
    """R10: the cryo/sequence/IPA shape -- two outputs, two inputs, no S-jogs."""

    style = LayoutStyle()
    figure = _pair_figure(
        source_height=60.0,
        target_height=60.0,
        source_ports=(
            PortSpec("first", Side.EAST, 1.0 / 3.0, adaptive=True),
            PortSpec("second", Side.EAST, 2.0 / 3.0, adaptive=True),
        ),
        target_ports=(
            PortSpec("first", Side.WEST, 0.24, adaptive=True),
            PortSpec("second", Side.WEST, 0.76, adaptive=True),
        ),
    )
    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source")
    target = routed.fitted.node("target")
    for name, edge_id in (("first", "flow1"), ("second", "flow2")):
        start = source.port(name).position
        end = target.port(name).position
        assert start.y == end.y
        assert routed.edge(edge_id).centerline == (start, end)
    assert (
        source.port("second").position.y - source.port("first").position.y
        >= style.port_spacing.points
    )


def test_collinear_pair_slides_clear_of_the_component_it_passes() -> None:
    """R10: agreeing on a coordinate inside a clearance ring still routes as a jog."""

    style = LayoutStyle()
    figure = _pair_figure(
        source_height=60.0,
        target_height=60.0,
        source_ports=(PortSpec("output", Side.EAST, 0.5, adaptive=True),),
        target_ports=(PortSpec("input", Side.WEST, 0.5, adaptive=True),),
        blocker_height=10.0,
    )
    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source").port("output").position
    target = routed.fitted.node("target").port("input").position
    blocker = routed.fitted.node("blocker").bounds
    assert source.y == target.y
    assert routed.edge("flow1").centerline == (source, target)
    # Both ends slide up together, to exactly one clearance above what they pass.
    assert source.y == blocker.top - style.route_clearance.points


def test_adapted_gallery_ports_reach_a_fixed_point() -> None:
    """R10: another target or source pass moves nothing, so no pair is stranded."""

    figure = gallery_figure("modelangelo-gnn")
    nodes = fit_figure(measure_figure(figure)).nodes
    style = STYLES[figure.style]
    for move_targets in (True, False):
        again = _adapt_endpoint_ports(figure, nodes, style, move_targets=move_targets)
        assert _port_positions(again) == _port_positions(nodes)


def test_unreachable_adaptive_pair_keeps_its_authored_centres() -> None:
    """R18: disjoint port bands settle centred, so the run reads as one Z-bend.

    Supersedes the R10 rule that sent both ports to the nearest reachable limit:
    an attachment hanging off a corner is worse than a centred bend.
    """

    figure = FigureSpec(
        "disjoint-bands",
        width=pt(320),
        nodes=(
            NodeSpec(
                "source",
                "block",
                (TextRun("Source"),),
                ports=(PortSpec("output", Side.EAST, 0.5, adaptive=True),),
            ),
            NodeSpec("above", "spacer", height=pt(60)),
            NodeSpec("below", "spacer", height=pt(60)),
            NodeSpec(
                "target",
                "block",
                (TextRun("Target"),),
                ports=(PortSpec("input", Side.WEST, 0.5, adaptive=True),),
            ),
        ),
        edges=(EdgeSpec("flow", PortRef("source", "output"), PortRef("target", "input")),),
        groups=(
            GroupSpec("root", ("left", "right"), LayoutSpec("row", gap=pt(40), align="start")),
            GroupSpec(
                "left",
                ("source", "below"),
                LayoutSpec("column", gap=pt(10), padding=pt(0)),
                role="layout",
            ),
            GroupSpec(
                "right",
                ("above", "target"),
                LayoutSpec("column", gap=pt(10), padding=pt(0)),
                role="layout",
            ),
        ),
    )
    routed = route_figure(fit_figure(measure_figure(figure)))
    source = routed.fitted.node("source")
    target = routed.fitted.node("target")
    assert source.bounds.bottom < target.bounds.top
    assert source.port("output").position.y == source.bounds.center.y
    assert target.port("input").position.y == target.bounds.center.y
    # One rise between the two boxes: a Z-bend, not two corner attachments.
    assert len(segments(routed.edge("flow").centerline)) == 3


def _spine_figure(*, net: bool) -> FigureSpec:
    """A south hub feeding a north continuation and a module's west input.

    The same two pairings are authored either as one fan-out net or as two
    ordinary edges, so the two link kinds can be compared directly.
    """

    pairs = (
        (PortRef("hub", "output"), PortRef("module", "input")),
        (PortRef("hub", "output"), PortRef("next", "skip")),
    )
    return FigureSpec(
        "spine",
        width=pt(280),
        nodes=(
            NodeSpec(
                "hub",
                "block",
                (TextRun("Hub"),),
                width=pt(72),
                ports=(PortSpec("output", Side.SOUTH, adaptive=True),),
            ),
            NodeSpec(
                "next",
                "block",
                (TextRun("Next"),),
                width=pt(72),
                ports=(PortSpec("skip", Side.NORTH, adaptive=True),),
            ),
            NodeSpec(
                "module",
                "block",
                (TextRun("Module"),),
                ports=(PortSpec("input", Side.WEST, adaptive=True),),
            ),
        ),
        edges=()
        if net
        else tuple(
            EdgeSpec(f"link{index}", source, target)
            for index, (source, target) in enumerate(pairs, start=1)
        ),
        nets=(
            NetSpec(
                "skip",
                "fan-out",
                (PortRef("hub", "output"),),
                tuple(target for _, target in pairs),
            ),
        )
        if net
        else (),
        groups=(
            GroupSpec("root", ("spine", "module"), LayoutSpec("row", gap=pt(40), align="start")),
            GroupSpec(
                "spine",
                ("hub", "next"),
                LayoutSpec("column", gap=pt(40), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def test_perpendicular_net_leg_leaves_the_hub_on_its_own_axis() -> None:
    """R14: the rail junction serves the west branch, so it must not pull the hub."""

    fitted = fit_figure(measure_figure(_spine_figure(net=True)))
    hub = fitted.node("hub")
    module = fitted.node("module")
    assert module.bounds.left > hub.bounds.right
    assert hub.port("output").position.x == hub.bounds.center.x
    assert fitted.node("next").port("skip").position.x == hub.port("output").position.x


def test_perpendicular_edge_leg_cannot_pull_its_port_past_the_band() -> None:
    """R18: an edge leg still pulls, but never further than the centre band.

    R14 left perpendicular *edge* pairs clamping to the band edge, which parked
    this south port on the hub's bottom-right corner. The module's west port is
    far east of the hub, so the pull is refused outright.
    """

    fitted = fit_figure(measure_figure(_spine_figure(net=False)))
    hub = fitted.node("hub")
    module = fitted.node("module")
    assert module.bounds.left > hub.bounds.right
    assert hub.port("output").position.x == hub.bounds.center.x


def _heads_figure() -> FigureSpec:
    """A fan-out from a west hub into heads that begin well east of it."""

    heads = tuple(
        NodeSpec(
            f"head{index}",
            "block",
            (TextRun(f"Head {index}"),),
            ports=(PortSpec("input", Side.NORTH, adaptive=True),),
        )
        for index in range(1, 4)
    )
    return FigureSpec(
        "heads",
        width=pt(400),
        nodes=(
            NodeSpec(
                "hub",
                "block",
                (TextRun("Hub"),),
                width=pt(72),
                ports=(PortSpec("output", Side.SOUTH, adaptive=True),),
            ),
            NodeSpec("lane", "spacer", width=pt(140), height=pt(0)),
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
            GroupSpec("root", ("hub", "row"), LayoutSpec("column", gap=pt(48), align="start")),
            GroupSpec(
                "row",
                ("lane", *(head.id for head in heads)),
                LayoutSpec("row", gap=pt(18), padding=pt(0), align="start"),
                role="layout",
            ),
        ),
    )


def test_unreachable_net_sinks_keep_their_authored_offsets() -> None:
    """R14: all-or-nothing -- an unreachable hub x leaves every tap centred."""

    fitted = fit_figure(measure_figure(_heads_figure()))
    hub = fitted.node("hub")
    assert hub.port("output").position.x == hub.bounds.center.x
    for index in range(1, 4):
        head = fitted.node(f"head{index}")
        assert head.bounds.left > hub.port("output").position.x
        assert head.port("input").position.x == head.bounds.center.x


def labeled_edge_figure(label: str) -> FigureSpec:
    return FigureSpec(
        "labeled-edge",
        width=pt(320),
        nodes=(
            NodeSpec("source", "block", (TextRun("Source"),)),
            NodeSpec("target", "block", (TextRun("Target"),)),
        ),
        edges=(
            EdgeSpec(
                "labeled",
                PortRef("source", "output"),
                PortRef("target", "input"),
                label=(TextRun(label),),
            ),
        ),
        groups=(
            GroupSpec(
                "root",
                ("source", "target"),
                LayoutSpec("row", gap=pt(6), justify="start"),
            ),
        ),
    )


def test_measurement_records_edge_label_metrics() -> None:
    measured = measure_figure(labeled_edge_figure("ESM-1b"))
    assert len(measured.edge_labels) == len(measured.semantic.edges)
    metrics = measured.edge_label("labeled")
    assert metrics is not None
    assert metrics.width > 0.0
    assert measured.edge_label("absent") is None


def test_edge_label_widens_the_boundary_it_crosses() -> None:
    style = LayoutStyle()
    short = measure_figure(labeled_edge_figure("x"))
    long = measure_figure(labeled_edge_figure("A rather long edge label"))
    label_width = long.edge_label("labeled").width
    fitted = fit_figure(long)
    gap = fitted.node("target").bounds.left - fitted.node("source").bounds.right
    assert gap >= label_width + 2.0 * style.padding_x.points
    assert long.group("root").intrinsic_size.width > short.group("root").intrinsic_size.width


def test_edge_label_fits_between_the_components_it_separates() -> None:
    routed = route_figure(fit_figure(measure_figure(labeled_edge_figure("ESM-1b"))))
    edge = routed.edge("labeled")
    assert edge.label_metrics is not None and edge.label_position is not None
    source = routed.fitted.node("source").bounds
    target = routed.fitted.node("target").bounds
    half = edge.label_metrics.width / 2.0
    assert edge.label_position.x - half >= source.right
    assert edge.label_position.x + half <= target.left


def grid_figure(
    *,
    count: int = 4,
    columns: int = 2,
    children: tuple[str, ...] | None = None,
    nodes: tuple[NodeSpec, ...] | None = None,
    **layout_options: object,
) -> FigureSpec:
    """A plain grid of equal blocks, with the root's own spacing zeroed out."""

    node_specs = nodes or tuple(
        NodeSpec(f"cell{index}", "block", (TextRun(f"C{index}"),)) for index in range(count)
    )
    return FigureSpec(
        "grid",
        width=pt(600),
        nodes=node_specs,
        groups=(
            GroupSpec(
                "root",
                children if children is not None else tuple(node.id for node in node_specs),
                LayoutSpec(
                    kind="grid",
                    columns=columns,
                    align="start",
                    **{"padding": pt(0), **layout_options},  # type: ignore[arg-type]
                ),
            ),
        ),
    )


def test_row_and_column_gaps_separate_their_own_axis() -> None:
    fitted = fit_figure(measure_figure(grid_figure(row_gap=pt(30), column_gap=pt(9))))
    first = fitted.node("cell0").bounds
    beside = fitted.node("cell1").bounds
    below = fitted.node("cell2").bounds
    assert beside.left - first.right == pytest.approx(9.0)
    assert below.top - first.bottom == pytest.approx(30.0)


def test_axis_gaps_fall_back_to_gap_then_to_the_style() -> None:
    uniform = fit_figure(measure_figure(grid_figure(gap=pt(12))))
    partial = fit_figure(measure_figure(grid_figure(gap=pt(12), row_gap=pt(40))))
    assert partial.node("cell1").bounds.left == pytest.approx(
        uniform.node("cell1").bounds.left
    )
    assert partial.node("cell2").bounds.top - partial.node("cell0").bounds.bottom == (
        pytest.approx(40.0)
    )


def test_column_gap_spaces_a_row_and_row_gap_spaces_a_column() -> None:
    def linear(kind: str, **options: object) -> FigureSpec:
        return FigureSpec(
            "linear",
            width=pt(400),
            nodes=(
                NodeSpec("first", "block", (TextRun("A"),)),
                NodeSpec("second", "block", (TextRun("B"),)),
            ),
            groups=(
                GroupSpec(
                    "root",
                    ("first", "second"),
                    LayoutSpec(kind=kind, padding=pt(0), align="start", **options),  # type: ignore[arg-type]
                ),
            ),
        )

    row = fit_figure(measure_figure(linear("row", column_gap=pt(21), row_gap=pt(3))))
    assert row.node("second").bounds.left - row.node("first").bounds.right == (
        pytest.approx(21.0)
    )
    column = fit_figure(measure_figure(linear("column", column_gap=pt(3), row_gap=pt(21))))
    assert column.node("second").bounds.top - column.node("first").bounds.bottom == (
        pytest.approx(21.0)
    )


def test_padding_sides_apply_independently() -> None:
    figure = grid_figure(
        padding=None,
        padding_top=pt(20),
        padding_right=pt(3),
        padding_bottom=pt(11),
        padding_left=pt(7),
    )
    fitted = fit_figure(measure_figure(figure))
    root = fitted.group("root")
    assert root.content_bounds.left - root.bounds.left == pytest.approx(7.0)
    assert root.content_bounds.top - root.bounds.top == pytest.approx(20.0)
    assert root.bounds.right - root.content_bounds.right == pytest.approx(3.0)
    assert root.bounds.bottom - root.content_bounds.bottom == pytest.approx(11.0)


def test_one_padding_still_pads_every_side_equally() -> None:
    fitted = fit_figure(measure_figure(grid_figure(padding=pt(9))))
    root = fitted.group("root")
    assert root.content_bounds.left - root.bounds.left == pytest.approx(9.0)
    assert root.bounds.bottom - root.content_bounds.bottom == pytest.approx(9.0)


def test_grid_children_take_the_cell_they_address() -> None:
    figure = grid_figure(
        count=3,
        columns=3,
        gap=pt(10),
        placements=(("cell2", 0, 0), ("cell0", 1, 2)),
    )
    fitted = fit_figure(measure_figure(figure))
    first = fitted.node("cell2").bounds
    # cell1 is unaddressed, so it flows into the first cell left over.
    flowed = fitted.node("cell1").bounds
    last = fitted.node("cell0").bounds
    assert flowed.top == pytest.approx(first.top)
    assert flowed.left > first.left
    assert last.top > first.top
    assert last.left > flowed.left


def test_sparse_grid_needs_no_spacer_children() -> None:
    """A hole costs nothing: the same geometry as filling it with a spacer."""

    filled = grid_figure(
        columns=3,
        gap=pt(10),
        nodes=(
            NodeSpec("cell0", "block", (TextRun("C0"),)),
            NodeSpec("hole", "spacer"),
            NodeSpec("cell1", "block", (TextRun("C1"),)),
            NodeSpec("cell2", "block", (TextRun("C2"),)),
        ),
        children=("cell0", "hole", "cell1", "cell2"),
    )
    sparse = grid_figure(
        count=3,
        columns=3,
        gap=pt(10),
        placements=(("cell1", 0, 2), ("cell2", 1, 0)),
    )
    filled_fit = fit_figure(measure_figure(filled))
    sparse_fit = fit_figure(measure_figure(sparse))
    for node_id in ("cell0", "cell1", "cell2"):
        assert sparse_fit.node(node_id).bounds == filled_fit.node(node_id).bounds


def test_column_widths_reserve_a_lane_no_child_occupies() -> None:
    lane = pt(50)
    reserved = grid_figure(
        count=2,
        columns=3,
        gap=pt(10),
        column_widths=((1, lane),),
        placements=(("cell1", 0, 2),),
    )
    fitted = fit_figure(measure_figure(reserved))
    left = fitted.node("cell0").bounds
    right = fitted.node("cell1").bounds
    # One empty lane wide, with one gap on either side of it.
    assert right.left - left.right == pytest.approx(50.0 + 2.0 * 10.0)


def test_column_widths_only_raise_a_column_that_is_already_narrower() -> None:
    narrow = fit_figure(measure_figure(grid_figure(gap=pt(10), column_widths=((0, pt(4)),))))
    plain = fit_figure(measure_figure(grid_figure(gap=pt(10))))
    assert narrow.node("cell1").bounds.left == pytest.approx(plain.node("cell1").bounds.left)


def test_cells_extent_resolves_against_the_figure_style() -> None:
    style = LayoutStyle()
    figure = grid_figure(
        count=1,
        columns=1,
        nodes=(NodeSpec("cell0", "block", (TextRun("C0"),), height=CellSpan(4)),),
    )
    measured = measure_figure(figure, style=style)
    assert measured.node("cell0").intrinsic_size.height == pytest.approx(
        vector_stack_height(style, 4).points
    )


def test_cells_extent_follows_a_restyled_vector_cell() -> None:
    style = LayoutStyle().with_updates(vector_cell=pt(20), vector_cell_gap=pt(2))
    figure = grid_figure(
        count=1,
        columns=1,
        nodes=(NodeSpec("cell0", "block", (TextRun("C0"),), height=CellSpan(3)),),
    )
    measured = measure_figure(figure, style=style)
    assert measured.node("cell0").intrinsic_size.height == pytest.approx(64.0)


def test_a_box_sized_in_cells_lines_up_with_the_vector_beside_it() -> None:
    style = LayoutStyle()
    with Figure("aligned", width=pt(400)) as figure:  # noqa: SIM117
        with figure.root.row("chain", gap=pt(10), padding=0, align="start") as chain:
            vector = chain.vector("features", ramp="ramp-node", cells=3)
            chain.mlp("projection", input=vector, height="cells:3", width=pt(40))
    fitted = fit_figure(measure_figure(figure.spec, style=style))
    cells = fitted.node("chain.features.cells").bounds
    projection = fitted.node("chain.projection").bounds
    assert projection.top == pytest.approx(cells.top)
    assert projection.bottom == pytest.approx(cells.bottom)


def _wired_pair(
    *,
    stacked: bool,
    ports: tuple[PortSpec, ...] = (),
    lane: str | None = None,
) -> FigureSpec:
    """Two blocks wired source-to-target, side by side or one above the other."""

    return FigureSpec(
        "pair",
        width=pt(240),
        nodes=(
            NodeSpec("first", "block", (TextRun("First"),), ports=ports),
            NodeSpec("second", "block", (TextRun("Second"),)),
        ),
        edges=(
            EdgeSpec(
                "flow",
                PortRef("first", "output"),
                PortRef("second", "input"),
                lane_hint=lane,
            ),
        ),
        groups=(
            GroupSpec(
                "root",
                ("first", "second"),
                LayoutSpec("column" if stacked else "row", gap=pt(40)),
            ),
        ),
    )


def _port_sides(figure: FigureSpec) -> dict[tuple[str, str], Side]:
    fitted = fit_figure(measure_figure(figure))
    return {
        (node.measured.spec.id, port.name): port.side
        for node in fitted.nodes
        for port in node.ports
    }


def test_a_stacked_pair_takes_south_and_north_ports_with_no_port_table() -> None:
    """R21: a defaulted port faces what it is wired to, so a column reads downward."""

    sides = _port_sides(_wired_pair(stacked=True))
    assert sides[("first", "output")] is Side.SOUTH
    assert sides[("second", "input")] is Side.NORTH
    # The ports nothing names are invisible, so they keep the grammar's own side.
    assert sides[("first", "input")] is Side.WEST
    assert sides[("second", "output")] is Side.EAST


def test_a_side_by_side_pair_keeps_the_east_and_west_ports_it_had() -> None:
    sides = _port_sides(_wired_pair(stacked=False))
    assert sides[("first", "output")] is Side.EAST
    assert sides[("second", "input")] is Side.WEST


def test_an_authored_port_side_is_pinned_even_when_it_faces_away() -> None:
    """Writing the side down *is* the choice; nothing may overrule it."""

    pinned = (
        PortSpec("input", Side.WEST, adaptive=True),
        PortSpec("output", Side.NORTH, adaptive=True),
    )
    sides = _port_sides(_wired_pair(stacked=True, ports=pinned))
    assert sides[("first", "output")] is Side.NORTH, "authored, so pinned"
    assert sides[("second", "input")] is Side.NORTH, "defaulted, so re-sided"


def test_a_lane_hinted_edge_leaves_its_ports_where_the_grammar_put_them() -> None:
    """An authored corridor, not the counterpart, says where that ink goes."""

    sides = _port_sides(_wired_pair(stacked=True, lane="root-left"))
    assert sides[("first", "output")] is Side.EAST
    assert sides[("second", "input")] is Side.WEST


def test_a_near_diagonal_relationship_names_no_side() -> None:
    """Below the decisive margin the component grammar's own side stands.

    A port that flipped on a few points of layout drift would be worse than one
    that never moved: the reader sees a different figure, for a fraction of a bend.
    """

    figure = FigureSpec(
        "diagonal",
        width=pt(240),
        nodes=(
            NodeSpec("first", "block", (TextRun("First"),)),
            NodeSpec("filler", "spacer"),
            NodeSpec("second", "block", (TextRun("Second"),)),
        ),
        edges=(EdgeSpec("flow", PortRef("first", "output"), PortRef("second", "input")),),
        groups=(
            GroupSpec("root", ("first", "column"), LayoutSpec("row", gap=pt(30))),
            GroupSpec(
                "column",
                ("filler", "second"),
                LayoutSpec("column", gap=pt(6), padding=pt(0)),
                role="layout",
            ),
        ),
    )
    sides = _port_sides(figure)
    assert sides[("first", "output")] is Side.EAST
    assert sides[("second", "input")] is Side.WEST


def _row_fan_out() -> FigureSpec:
    """One source over a row of three sinks, joined by a fan-out net."""

    return FigureSpec(
        "fan-out",
        width=pt(300),
        nodes=(
            NodeSpec("source", "block", (TextRun("Trunk"),)),
            *(
                NodeSpec(f"head{index}", "mlp", (TextRun("MLP"),))
                for index in range(1, 4)
            ),
        ),
        nets=(
            NetSpec(
                "readout",
                "fan-out",
                (PortRef("source", "output"),),
                tuple(PortRef(f"head{index}", "input") for index in range(1, 4)),
            ),
        ),
        groups=(
            GroupSpec("root", ("source", "heads"), LayoutSpec("column", gap=pt(40), align="start")),
            GroupSpec(
                "heads",
                ("head1", "head2", "head3"),
                LayoutSpec("row", gap=pt(20), padding=pt(0)),
                role="layout",
            ),
        ),
    )


def test_a_net_votes_once_for_its_trunk_not_once_per_spoke() -> None:
    """R21: the rail runs along the spokes' spread, so the trunk leaves across it.

    Voting per spoke would drag the source port east, because a wide readout row
    puts most of its heads to one side. A stem does not run to the far port -- it
    runs to the shared rail -- so the whole net asks for one direction.
    """

    sides = _port_sides(_row_fan_out())
    assert sides[("source", "output")] is Side.SOUTH
    for index in range(1, 4):
        assert sides[(f"head{index}", "input")] is Side.NORTH


def test_a_conflicted_port_picks_a_side_and_says_so() -> None:
    """Two connections facing opposite ways get an answer plus an info diagnostic."""

    figure = FigureSpec(
        "conflict",
        width=pt(300),
        nodes=(
            NodeSpec("left", "block", (TextRun("Left"),)),
            NodeSpec("middle", "block", (TextRun("Middle"),)),
            NodeSpec("right", "block", (TextRun("Right"),)),
        ),
        edges=(
            EdgeSpec("in", PortRef("left", "output"), PortRef("middle", "input")),
            EdgeSpec("also", PortRef("right", "output"), PortRef("middle", "input")),
        ),
        groups=(
            GroupSpec("root", ("left", "middle", "right"), LayoutSpec("row", gap=pt(30))),
        ),
    )
    fitted = fit_figure(measure_figure(figure))
    (diagnostic,) = fitted.diagnostics
    assert diagnostic.code == "layout.port.side.conflicted"
    assert diagnostic.severity is Severity.INFO
    assert diagnostic.entity_id == "middle"
    assert "input" in diagnostic.message
    assert fitted.node("middle").port("input").side in {Side.EAST, Side.WEST}


def test_a_loop_back_leaves_the_spine_the_side_it_needs() -> None:
    """A node wired both onward and back home does not use one side for both.

    Both connections face south, so both defaulted ports would land there and the
    router would draw the return alongside the spine, a hair apart. The short hop
    keeps the straight run; the long return takes the wider margin beside the
    node, which is where its rail was going to travel anyway.
    """

    figure = Figure(
        "loop",
        width=pt(300),
        layout=LayoutSpec("column", gap=pt(30), align="start"),
    )
    root = figure.root
    blocks = []
    for index, name in enumerate(("head", "middle", "tail")):
        with root.row(f"band{index}", gap=pt(24), padding=0, align="start", role="layout") as band:
            band.node("lane", "spacer", width=pt(30), height=0.0)
            blocks.append(band.block(name, label=name.title()))
            band.group(f"panel{index}", width=pt(120), height=pt(30), role="module")
    head, middle, tail = blocks
    root.connect(head, middle)
    root.connect(middle, tail)
    root.connect(tail, head)
    fitted = fit_figure(measure_figure(figure.spec))
    assert fitted.node("band0.head").port("output").side is Side.SOUTH, "the spine goes on"
    assert fitted.node("band0.head").port("input").side is Side.WEST, "the return takes the lane"
    assert fitted.node("band2.tail").port("input").side is Side.NORTH
    assert fitted.node("band2.tail").port("output").side is Side.WEST
    assert fitted.diagnostics == ()


def test_the_authored_figure_still_serializes_with_the_sides_it_declared() -> None:
    """Re-siding is a compiler decision; the semantic figure is untouched."""

    fitted = fit_figure(measure_figure(_wired_pair(stacked=True)))
    assert fitted.node("first").port("output").side is Side.SOUTH
    ports = fitted.measured.semantic.node("first").ports
    authored = next(port for port in ports if port.name == "output")
    assert authored.side is Side.EAST, "the semantic figure keeps the grammar's side"
    assert authored.auto_side, "and says the side was never the author's choice"


def _ports_row(align: str = "ports") -> FigureSpec:
    """A box beside a captioned vector, in a row that aligns one way or the other.

    The caption is a sibling node, so the composite's box is taller than its
    glyph and its glyph sits at the top. Bounding-box alignment lines the two
    boxes up and the arrow between them then runs uphill; ports alignment lines
    up the two port lines instead.
    """

    return FigureSpec(
        "ports",
        width=pt(400),
        nodes=(
            NodeSpec("box", "block", (TextRun("Box"),), height=pt(60)),
            NodeSpec("cells", "vector", properties=(("cells", 3),)),
            NodeSpec("caption", "label", (TextRun("Feature\nupdate"),), role="label"),
        ),
        groups=(
            GroupSpec(
                "root",
                ("box", "glyph"),
                LayoutSpec("row", gap=pt(30), padding=pt(0), align=align),  # type: ignore[arg-type]
            ),
            GroupSpec(
                "glyph",
                ("cells", "caption"),
                LayoutSpec("column", gap=pt(3), padding=pt(0), align="center"),
                role="layout",
            ),
        ),
    )


def test_ports_alignment_puts_one_line_through_a_row() -> None:
    """R24: a chain aligned by port line runs straight, whatever hangs off it."""

    boxed = fit_figure(measure_figure(_ports_row(align="start")))
    aligned = fit_figure(measure_figure(_ports_row()))
    assert boxed.node("box").bounds.center.y != pytest.approx(
        boxed.node("cells").bounds.center.y
    ), "bounding-box alignment lines up the boxes, not the ports"
    assert aligned.node("box").bounds.center.y == pytest.approx(
        aligned.node("cells").bounds.center.y
    )
    assert aligned.node("box").port("output").position.y == pytest.approx(
        aligned.node("cells").port("input").position.y
    )


def test_a_composite_answers_with_its_glyph_and_not_with_its_caption() -> None:
    """The anchor skips label children, so the caption hangs below the line."""

    measured = measure_figure(_ports_row())
    glyph = measured.group("glyph")
    cells = measured.node("cells")
    assert glyph.anchor.y == pytest.approx(cells.intrinsic_size.height / 2.0)
    assert glyph.anchor.y < glyph.intrinsic_size.height / 2.0, "not the middle of the box"


def test_an_explicit_anchor_child_wins_over_the_first_one() -> None:
    figure = _ports_row()
    groups = tuple(
        replace(group, anchor="caption") if group.id == "glyph" else group
        for group in figure.groups
    )
    measured = measure_figure(replace(figure, groups=groups))
    glyph = measured.group("glyph")
    caption = measured.node("caption")
    assert glyph.anchor.y == pytest.approx(
        glyph.intrinsic_size.height - caption.intrinsic_size.height / 2.0
    )


def test_a_ports_row_reserves_the_reach_above_and_below_its_shared_line() -> None:
    """Ascent plus descent, as a line of type: it may exceed the tallest child."""

    measured = measure_figure(_ports_row())
    root = measured.group("root")
    tallest = max(
        measured.node("box").intrinsic_size.height,
        measured.group("glyph").intrinsic_size.height,
    )
    assert root.intrinsic_size.height > tallest


def test_ports_alignment_shares_one_centre_down_a_grid_column() -> None:
    """The user's ask: the input features of a module line up with each other."""

    figure = FigureSpec(
        "column",
        width=pt(400),
        nodes=(
            NodeSpec("wide", "block", (TextRun("Edge rectangles"),)),
            NodeSpec("pad0", "spacer"),
            NodeSpec("narrow", "vector", properties=(("cells", 3),)),
            NodeSpec("pad1", "spacer"),
        ),
        groups=(
            GroupSpec(
                "root",
                ("wide", "pad0", "narrow", "pad1"),
                LayoutSpec("grid", columns=2, padding=pt(0), align="ports"),
            ),
        ),
    )
    fitted = fit_figure(measure_figure(figure))
    assert fitted.node("wide").bounds.center.x == pytest.approx(
        fitted.node("narrow").bounds.center.x
    )


def test_an_anchor_must_name_a_child_of_the_group_it_anchors() -> None:
    with pytest.raises(ValueError, match="not one of its children"):
        GroupSpec("g", ("a", "b"), anchor="c")


def test_a_caption_costs_less_clearance_than_a_body_but_is_not_transparent() -> None:
    """R24: routes used to run through caption text, which reads as a clipped word."""

    style = STYLES["paper"]
    caption = NodeSpec("c", "label", (TextRun("Attended value"),), role="label")
    body = NodeSpec("b", "block", (TextRun("MLP"),))
    assert "label" not in TRANSPARENT_KINDS, "a caption is ink, so a route may not cross it"
    assert route_clearance(caption, style) == pytest.approx(style.caption_clearance.points)
    assert route_clearance(body, style) == pytest.approx(style.route_clearance.points)
    assert route_clearance(caption, style) < route_clearance(body, style)


def test_no_connector_in_the_panel_touches_a_caption() -> None:
    """The acceptance for R24, read off the figure the critique was written about."""

    routed = route_figure(fit_figure(measure_figure(gallery_figure("modelangelo-gnn"))))
    clearance = STYLES["paper"].caption_clearance.points
    captions = tuple(
        node.bounds.inflated(clearance - 0.01)
        for node in routed.fitted.nodes
        if node.measured.spec.kind == "label"
    )
    runs = [edge.centerline for edge in routed.edges]
    for net in routed.nets:
        runs.append(net.rail)
        runs.extend(stem.centerline for stem in net.source_stems + net.target_stems)
    for run in runs:
        for segment in segments(run):
            for caption in captions:
                assert not segment.intersects_rect_interior(caption)


def test_attachment_lane_tracks_put_a_lane_centre_on_every_offset() -> None:
    """R28: the arithmetic a figure used to write as a magic inter-glyph gap."""

    offsets = component_port_offsets("attention", ("q", "k", "v"))
    assert offsets == (0.24, 0.5, 0.76)
    tracks = attachment_lane_tracks(offsets, 120.0)
    assert len(tracks) == 7
    assert sum(tracks) == pytest.approx(120.0)
    lanes = tracks[1::2]
    assert lanes == pytest.approx((31.2, 31.2, 31.2)), "one width, the widest that stays disjoint"
    edges = [0.0]
    for track in tracks:
        edges.append(edges[-1] + track)
    centres = [(edges[index], edges[index + 1]) for index in range(1, len(tracks), 2)]
    for (low, high), offset in zip(centres, offsets, strict=True):
        assert (low + high) / 2.0 == pytest.approx(offset * 120.0)


def test_attachment_lanes_reject_offsets_that_cannot_hold_one() -> None:
    with pytest.raises(ValueError, match="must ascend"):
        attachment_lane_tracks((0.5, 0.24), 120.0)
    with pytest.raises(ValueError, match="leave no room"):
        attachment_lane_tracks((0.0, 0.5), 120.0)
    with pytest.raises(ValueError, match="positive width"):
        attachment_lane_tracks((0.24, 0.76), 0.0)
