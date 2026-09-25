"""Public compiler facade joining the pure phase functions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from flexo.diagnostics import FlexoError
from flexo.emit import emit_svg
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import MeasuredFigure
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec
from flexo.layout import fit_figure, measure_figure
from flexo.routing import route_figure
from flexo.routing.room import room_needed, with_room
from flexo.style import LayoutStyle, Palette
from flexo.svg import SVGDocument
from flexo.themes import figure_palette, figure_style
from flexo.units import Length


@dataclass(frozen=True, slots=True)
class Compilation:
    measured: MeasuredFigure
    fitted: FittedFigure
    routed: RoutedFigure
    document: SVGDocument


def compile_figure(
    figure: FigureSpec,
    *,
    style: LayoutStyle | None = None,
    palette: Palette | None = None,
) -> Compilation:
    layout_style = style or figure_style(figure)
    paint_palette = palette or figure_palette(figure)
    figure = _resolved_shapes(figure, layout_style)
    measured = measure_figure(figure, style=layout_style)
    if style is None and _too_wide(measured):
        # Tighten the spacing before growing the page: a figure a little too
        # wide for its column reads better closer together than overflowing.
        for scale in COMPACT_SCALES:
            tighter = replace(
                layout_style,
                gap=Length(layout_style.gap.points * scale),
                group_padding=Length(layout_style.group_padding.points * scale),
            )
            attempt = measure_figure(figure, style=tighter)
            if not _too_wide(attempt):
                layout_style, measured = tighter, attempt
                break
    fitted = fit_figure(measured, style=layout_style)
    routed = route_figure(fitted, style=layout_style)
    # Routing says where the layout left too little room; lay out again with it.
    current = figure
    for _ in range(ROOM_ROUNDS):
        needs = room_needed(routed, layout_style)
        if not needs:
            break
        current = with_room(current, needs, layout_style)
        try:
            next_measured = measure_figure(current, style=layout_style)
            next_fitted = fit_figure(next_measured, style=layout_style)
        except FlexoError:
            break  # The room does not fit the figure's width: keep what routed.
        measured, fitted = next_measured, next_fitted
        routed = route_figure(fitted, style=layout_style)
    document = emit_svg(routed, style=layout_style, palette=paint_palette)
    return Compilation(measured, fitted, routed, document)


def _resolved_shapes(figure: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``figure`` with every ``shape="auto"`` edge given the ``lines`` convention's shape."""

    if not any(edge.shape == "auto" for edge in figure.edges):
        return figure
    shape = style.conventions.lines
    return replace(
        figure,
        edges=tuple(
            replace(edge, shape=shape) if edge.shape == "auto" else edge
            for edge in figure.edges
        ),
    )


def _too_wide(measured: MeasuredFigure) -> bool:
    return any(item.code == "layout.width.grown" for item in measured.diagnostics)


COMPACT_SCALES = (0.8, 0.65, 0.5)
"""Spacing scales tried, in order, when a figure is wider than its page."""

ROOM_ROUNDS = 3
"""How many times layout may be asked for more room before routing takes what it has."""
