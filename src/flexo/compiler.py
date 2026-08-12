"""Public compiler facade joining the pure phase functions."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.emit import emit_svg
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import MeasuredFigure
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec
from flexo.layout import fit_figure, measure_figure
from flexo.routing import route_figure
from flexo.style import PALETTES, STYLES, LayoutStyle, Palette
from flexo.svg import SVGDocument


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
    layout_style = style or STYLES[figure.style]
    paint_palette = palette or PALETTES[figure.palette]
    measured = measure_figure(figure, style=layout_style)
    fitted = fit_figure(measured, style=layout_style)
    routed = route_figure(fitted, style=layout_style)
    document = emit_svg(routed, style=layout_style, palette=paint_palette)
    return Compilation(measured, fitted, routed, document)
