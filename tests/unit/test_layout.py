from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec, TextRun
from flexo.layout import fit_figure, measure_figure
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
