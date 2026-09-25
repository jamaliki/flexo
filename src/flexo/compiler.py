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
from flexo.routing.room import crossing_room, crossings, room_needed, with_room
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
    current, measured, fitted, routed = _with_room_rounds(
        figure, measured, fitted, routed, layout_style
    )
    current, measured, fitted, routed = _uncrossed(
        current, measured, fitted, routed, layout_style
    )
    document = emit_svg(routed, style=layout_style, palette=paint_palette)
    return Compilation(measured, fitted, routed, document)


def _with_room_rounds(figure, measured, fitted, routed, style):
    """Lay out again, up to ``ROOM_ROUNDS`` times, with the room routing asked for."""

    current = figure
    for _ in range(ROOM_ROUNDS):
        needs = room_needed(routed, style)
        if not needs:
            break
        attempt = with_room(current, needs, style)
        try:
            next_measured = measure_figure(attempt, style=style)
            next_fitted = fit_figure(next_measured, style=style)
        except FlexoError:
            break  # The room does not fit the figure's width: keep what routed.
        current, measured, fitted = attempt, next_measured, next_fitted
        routed = route_figure(fitted, style=style)
    return current, measured, fitted, routed


def _uncrossed(figure, measured, fitted, routed, style):
    """Try a lane of room along a container's edge where it would take a crossing out.

    A route that crosses another often has a clean way round -- over the top
    of its container's contents, say -- that is too narrow to take until the
    container is given a lane more. Each crossing's containers are offered
    one, top or bottom, and the figure is laid out and routed again; room that
    removes crossings is kept, room that does not is thrown away.
    """

    best = len(crossings(routed))
    trials = 0
    while best and trials < CROSSING_ROOM_TRIALS:
        improved = False
        for needs in crossing_room(routed, style):
            if trials >= CROSSING_ROOM_TRIALS:
                break
            trials += 1
            attempt = with_room(figure, needs, style)
            try:
                trial_measured = measure_figure(attempt, style=style)
                trial_fitted = fit_figure(trial_measured, style=style)
            except FlexoError:
                continue
            trial = _with_room_rounds(
                attempt,
                trial_measured,
                trial_fitted,
                route_figure(trial_fitted, style=style),
                style,
            )
            count = len(crossings(trial[3]))
            if count < best:
                best = count
                figure, measured, fitted, routed = trial
                improved = True
                break
        if not improved:
            break
    return figure, measured, fitted, routed


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

CROSSING_ROOM_TRIALS = 2
"""Most layouts tried, per figure, to route a crossing round instead of through."""

ROOM_ROUNDS = 3
"""How many times layout may be asked for more room before routing takes what it has."""
