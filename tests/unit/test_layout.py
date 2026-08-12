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
