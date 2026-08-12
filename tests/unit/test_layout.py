from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.geometry import Side, segments
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
)
from flexo.layout import fit_figure, measure_figure
from flexo.routing import route_figure
from flexo.style import LayoutStyle
from flexo.units import pt


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
    expected = 2 * style.route_clearance.points + 2 * style.route_lane_spacing.points
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
    source_y = fitted.node("source").port("output").position.y
    adaptive = fitted.node("adaptive")
    expected_y = min(
        adaptive.bounds.bottom - LayoutStyle().corner_radius.points,
        max(adaptive.bounds.top + LayoutStyle().corner_radius.points, source_y),
    )
    assert adaptive.port("input").position.y == expected_y
    fixed = fitted.node("fixed")
    assert fixed.port("input").position.y == fixed.bounds.top + fixed.bounds.height * 0.2
