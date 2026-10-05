"""Public compiler facade joining the pure phase functions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from flexo.diagnostics import FlexoError
from flexo.draft import DRAFT, give_up_if_newer, recall, remember
from flexo.emit import emit_svg
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import MeasuredFigure
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec, GroupSpec
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
    give_up_if_newer()
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
    if DRAFT.get():
        # A draft (flexo.draft): laid out with the room, and the slides, the figure's last
        # drawing had; routed from that drawing; no more room asked for, nor a lane tried.
        last = recall("layout", _layout_key(figure, layout_style))
        slide = last[1] if last is not None else True
        if last is not None and last[0]:
            figure = _with_recalled_room(figure, last[0])
            measured = measure_figure(figure, style=layout_style)
        fitted = fit_figure(measured, style=layout_style, slide=slide)
        routed = route_figure(fitted, style=layout_style)
        current, measured, fitted, routed = _with_room_rounds(
            figure, measured, fitted, routed, layout_style, slide=slide, rounds=DRAFT_ROOM_ROUNDS
        )
        # (The next draft starts from this one's room, as its lines are this one's.)
        remember("layout", _layout_key(figure, layout_style), (_room_of(current), slide))
        document = emit_svg(routed, style=layout_style, palette=paint_palette)
        return Compilation(measured, fitted, routed, document)
    fitted = fit_figure(measured, style=layout_style)
    routed = route_figure(fitted, style=layout_style)
    fitted, routed, slide = _judged_slides(measured, fitted, routed, layout_style)
    current, measured, fitted, routed = _with_room_rounds(
        figure, measured, fitted, routed, layout_style, slide=slide
    )
    current, measured, fitted, routed = _uncrossed(
        current, measured, fitted, routed, layout_style, slide=slide
    )
    # (For a draft of it to start from.)
    remember("layout", _layout_key(figure, layout_style), (_room_of(current), slide))
    document = emit_svg(routed, style=layout_style, palette=paint_palette)
    return Compilation(measured, fitted, routed, document)


def _layout_key(figure: FigureSpec, style: LayoutStyle) -> tuple:
    """Which drawing of a figure a draft's layout follows: the figure, at its width and
    spacing, its groups running the way they do (turned to fit a slide, another)."""

    kinds = tuple((group.id, group.layout.kind) for group in figure.groups)
    return (figure.id, figure.width, style, kinds)


def _room_of(figure: FigureSpec) -> dict[str, tuple]:
    """The room routing asked of each group, with how many parts it held then."""

    return {
        group.id: (group.layout.room, group.layout.gap_room, len(group.children))
        for group in figure.groups
        if any(group.layout.room) or any(group.layout.gap_room)
    }


def _with_recalled_room(figure: FigureSpec, room: dict[str, tuple]) -> FigureSpec:
    """``figure`` given the room its last drawing did: round each group, and between its
    parts while it holds as many (the gaps between them are the same gaps)."""

    groups = []
    for group in figure.groups:
        kept = room.get(group.id)
        if kept is None:
            groups.append(group)
            continue
        gaps = kept[1] if kept[2] == len(group.children) else group.layout.gap_room
        groups.append(replace(group, layout=replace(group.layout, room=kept[0], gap_room=gaps)))
    return replace(figure, groups=tuple(groups))


def _judged_slides(measured, fitted, routed, style):
    """The layout with its groups slid to straighten arrows, if the routes agree.

    Fitting slides a group on a prediction of where the router will put each
    arrow; a port several arrows share can prove it wrong. So the figure is also
    fitted with every group where its parent put it, and the slid layout is kept
    only when its routes bend less and cross no more. Returns the chosen fitting,
    its routes, and whether later refits should slide.
    """

    plain = fit_figure(measured, style=style, slide=False)
    if plain.nodes == fitted.nodes:
        return fitted, routed, True
    plain_routed = route_figure(plain, style=style)
    if _bends(routed) < _bends(plain_routed) and len(crossings(routed)) <= len(
        crossings(plain_routed)
    ):
        return fitted, routed, True
    return plain, plain_routed, False


def _bends(routed: RoutedFigure) -> int:
    """Corners in every drawn line: how far a figure's arrows are from straight."""

    lines = [edge.centerline for edge in routed.edges]
    for net in routed.nets:
        lines += [net.rail, *net.trunks, *net.joins]
        lines += [stem.centerline for stem in (*net.source_stems, *net.target_stems)]
    return sum(_corners(line) for line in lines)


def _corners(points) -> int:
    count = 0
    for before, at, after in zip(points, points[1:], points[2:], strict=False):
        cross = (at.x - before.x) * (after.y - at.y) - (at.y - before.y) * (after.x - at.x)
        count += abs(cross) > 1e-6
    return count


def _with_room_rounds(figure, measured, fitted, routed, style, *, slide=True, rounds=None):
    """Lay out again, up to ``ROOM_ROUNDS`` times (or ``rounds``), with the room routing
    asked for."""

    current = figure
    for _ in range(ROOM_ROUNDS if rounds is None else rounds):
        needs = room_needed(routed, style)
        if not needs:
            break
        attempt = with_room(current, needs, style)
        if attempt == current:
            break  # Room for nothing the figure holds: it would be laid out as it is.
        try:
            next_measured = measure_figure(attempt, style=style)
            next_fitted = fit_figure(next_measured, style=style, slide=slide)
        except FlexoError:
            break  # The room does not fit the figure's width: keep what routed.
        # Room the layout had to spare moves nothing, and routing it again would draw
        # every line as it is: they are kept.
        if _placed_alike(next_fitted, fitted):
            routed = replace(routed, fitted=next_fitted)
        else:
            routed = route_figure(next_fitted, style=style)
        current, measured, fitted = attempt, next_measured, next_fitted
    return current, measured, fitted, routed


def _placed_alike(one: FittedFigure, other: FittedFigure) -> bool:
    """Whether two layouts of a figure, its groups given different room, put everything
    in the same place: routing reads where things are, never the room that put them there."""

    if one.canvas_size != other.canvas_size or one.nodes != other.nodes:
        return False
    if len(one.groups) != len(other.groups):
        return False
    for first, second in zip(one.groups, other.groups, strict=True):
        if (first.bounds, first.content_bounds) != (second.bounds, second.content_bounds):
            return False
        if _unroomed(first.measured.spec) != _unroomed(second.measured.spec):
            return False
    return True


def _unroomed(group: GroupSpec) -> GroupSpec:
    return replace(group, layout=replace(group.layout, room=(0.0, 0.0, 0.0, 0.0), gap_room=()))


def _uncrossed(figure, measured, fitted, routed, style, *, slide=True):
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
                trial_fitted = fit_figure(trial_measured, style=style, slide=slide)
            except FlexoError:
                continue
            trial = _with_room_rounds(
                attempt,
                trial_measured,
                trial_fitted,
                route_figure(trial_fitted, style=style),
                style,
                slide=slide,
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

DRAFT_ROOM_ROUNDS = 0
"""How many times a draft's layout may be asked for more room (flexo.draft): none -- it is
given the room its last drawing had, and is drawn in full once the changes stop."""
