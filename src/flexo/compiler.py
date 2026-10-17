"""Public compiler facade joining the pure phase functions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from flexo.diagnostics import FlexoError
from flexo.draft import DRAFT, give_up_if_newer, recall, remember
from flexo.emit import emit_svg
from flexo.figure_shapes import Overlay, part_boxes
from flexo.frames import (
    PlacedFrame,
    ended,
    margin,
    place,
    settled,
    split,
    stood_in,
    title_room,
    undrawn,
)
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import MeasuredFigure
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec, FreeShape, GroupSpec
from flexo.layout import fit_figure, measure_figure
from flexo.pages import lettered
from flexo.routing import route_figure
from flexo.routing.room import crossing_room, crossings, room_needed, with_room
from flexo.structure_frames import framed
from flexo.style import LayoutStyle, Palette
from flexo.svg import SVGDocument
from flexo.themes import figure_palette, figure_style
from flexo.units import Length
from flexo.wording import worded


@dataclass(frozen=True, slots=True)
class Compilation:
    measured: MeasuredFigure
    fitted: FittedFigure
    routed: RoutedFigure
    document: SVGDocument
    frames: tuple[PlacedFrame, ...] = ()
    """The figure's frames (``flexo.frames``), round what they name: no part of the layout."""
    shapes: Overlay | None = None
    """The shapes drawn over it (``flexo.figure_shapes``), as they were placed on it: no part
    of the layout either."""


def compile_figure(
    figure: FigureSpec,
    *,
    style: LayoutStyle | None = None,
    palette: Palette | None = None,
) -> Compilation:
    give_up_if_newer()
    # (Shapes drawn over the figure take no room: laid out without them, drawn on it after.)
    shapes = figure.shapes
    if shapes:
        figure = replace(figure, shapes=())
    layout_style = style or figure_style(figure)
    paint_palette = palette or figure_palette(figure)
    # (A frame goes round shapes where the layout puts them: laid out without it, and
    # without the lines that end at it -- routed once it is where it will be drawn.)
    whole = lettered(_resolved_shapes(figure, layout_style))
    figure, frames = split(whole)
    lines = ended(whole) if frames else ((), ())
    held = (frames, lines) if any(lines) else None
    # Each shape's words in the weight and slant it asks for (``flexo.wording``).
    figure = replace(figure, nodes=tuple(worded(node) for node in figure.nodes))
    # Structures that share a frame, each drawn as the frame sees it (flexo.structure_frames).
    unframed = figure
    figure = framed(figure, layout_style)
    figure = _with_margin_for(frames, figure, layout_style)
    figure = _with_room_for_titles(frames, figure, layout_style)
    measured = measure_figure(figure, style=layout_style)
    if style is None and _too_large(measured):
        # Tighten the spacing before growing the page: a figure a little too
        # wide for its column reads better closer together than overflowing.
        # (Too tall for a page with a height, the same; if nothing fits both ways, the
        # first spacing that fits across is kept, as for a page with no height.)
        across = None
        for scale in COMPACT_SCALES:
            tighter = replace(
                layout_style,
                gap=Length(layout_style.gap.points * scale),
                group_padding=Length(layout_style.group_padding.points * scale),
            )
            attempt = measure_figure(figure, style=tighter)
            if not _too_large(attempt):
                across = (tighter, attempt)
                break
            if across is None and _too_wide(measured) and not _too_wide(attempt):
                across = (tighter, attempt)
        if across is not None:
            layout_style, measured = across
        if _too_wide(measured):
            # Still wider than its page: the structures with no size of their own drawn
            # smaller, all alike, until it fits -- a molecule is drawn to fill whatever box
            # it is given; a structure given a size keeps it.
            for scale in STRUCTURE_SCALES:
                smaller = _with_smaller_structures(unframed, layout_style, scale)
                if smaller is unframed:
                    break
                smaller = framed(smaller, layout_style)
                smaller = _with_margin_for(frames, smaller, layout_style)
                figure = _with_room_for_titles(frames, smaller, layout_style)
                measured = measure_figure(figure, style=layout_style)
                if not _too_wide(measured):
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
        routed = _route(fitted, layout_style, held)
        current, measured, fitted, routed = _with_room_rounds(
            figure, measured, fitted, routed, layout_style, slide=slide,
            rounds=DRAFT_ROOM_ROUNDS, held=held,
        )
        # (The next draft starts from this one's room, as its lines are this one's.)
        remember("layout", _layout_key(figure, layout_style), (_room_of(current), slide))
        return _framed(
            frames, measured, fitted, routed, layout_style, paint_palette, held, shapes=shapes
        )
    give_up_if_newer()
    fitted = fit_figure(measured, style=layout_style)
    give_up_if_newer()
    routed = _route(fitted, layout_style, held)
    fitted, routed, slide = _judged_slides(measured, fitted, routed, layout_style, held)
    current, measured, fitted, routed = _with_room_rounds(
        figure, measured, fitted, routed, layout_style, slide=slide, held=held
    )
    current, measured, fitted, routed = _uncrossed(
        current, measured, fitted, routed, layout_style, slide=slide, held=held
    )
    # (For a draft of it to start from.)
    remember("layout", _layout_key(figure, layout_style), (_room_of(current), slide))
    give_up_if_newer()
    return _framed(
        frames, measured, fitted, routed, layout_style, paint_palette, held, shapes=shapes
    )


FRAME_ROUNDS = 1
"""Most times a figure is routed again because a frame its lines end at is drawn elsewhere
than they took it to be: a line through its title's band that was not looked for."""


def _route(fitted: FittedFigure, style: LayoutStyle, held: tuple | None = None) -> RoutedFigure:
    """``fitted`` routed. Where lines end at frames (``held``: the frames, and those
    lines), with each such frame standing in the figure where it will be drawn
    (``flexo.frames.stood_in``) -- routed again should its routes put the frame elsewhere,
    so that the lines meet its outline as it is drawn."""

    if held is None:
        return route_figure(fitted, style=style)
    frames, lines = held
    stood = stood_in(fitted, frames, lines, style)
    routed = route_figure(stood, style=style)
    for _ in range(FRAME_ROUNDS):
        again = stood_in(fitted, frames, lines, style, among=routed)
        if settled(stood, again):
            break
        stood, routed = again, route_figure(again, style=style)
    return routed


def _kept(
    routed: RoutedFigure, fitted: FittedFigure, style: LayoutStyle, held: tuple | None
) -> RoutedFigure:
    """``routed`` as the routes of ``fitted``, a layout that puts everything where the one
    it was routed in did: its frames standing in it where they stood."""

    if held is None:
        return replace(routed, fitted=fitted)
    frames, lines = held
    again = stood_in(fitted, frames, lines, style, among=routed)
    if settled(routed.fitted, again):
        return replace(routed, fitted=again)
    return _route(fitted, style, held)


def _with_margin_for(frames: tuple, figure: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``figure`` with its page's margin wider by what its frames stand out from their
    shapes: a frame round shapes at the page's edge is on the page."""

    out = margin(frames, style)
    if not frames:
        return figure
    groups = []
    for group in figure.groups:
        if group.id == figure.root:
            padding = group.layout.authored_padding(style.group_padding)
            group = replace(
                group,
                layout=replace(
                    group.layout,
                    padding_top=Length(padding.top + out),
                    padding_right=Length(padding.right + out),
                    padding_bottom=Length(padding.bottom + out),
                    padding_left=Length(padding.left + out),
                ),
            )
        groups.append(group)
    return replace(figure, groups=tuple(groups))


TITLE_ROUNDS = 3
"""Most times a figure is laid out to find where its frames' titles want room: making it
over one shape can leave another at the frame's top."""


def _with_room_for_titles(frames: tuple, figure: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``figure`` with room kept for the titles of its frames: laid out, each title's place
    found (over the shape at its frame's top; under the one at its bottom, for a title
    there), and the room it wants there added -- again, should that leave another shape
    at a frame's top."""

    if not any(frame.label for frame in frames):
        return figure
    kept: set[tuple[str, str]] = set()
    for _ in range(TITLE_ROUNDS):
        try:
            fitted = fit_figure(measure_figure(figure, style=style), style=style)
        except FlexoError:
            return figure  # (said by the layout proper, which follows)
        asked = {
            group: {where: amount for where, amount in wanted.items() if (group, where) not in kept}
            for group, wanted in title_room(frames, fitted, style).items()
        }
        asked = {group: wanted for group, wanted in asked.items() if wanted}
        if not asked:
            break
        kept |= {(group, where) for group, wanted in asked.items() for where in wanted}
        figure = with_room(figure, asked, style)
    return figure


def _framed(
    frames: tuple,
    measured: MeasuredFigure,
    fitted: FittedFigure,
    routed: RoutedFigure,
    style: LayoutStyle,
    palette: Palette,
    held: tuple | None = None,
    *,
    shapes: tuple[FreeShape, ...] = (),
) -> Compilation:
    """The figure drawn, its frames round what they name and its shapes over it."""

    placed, said = place(frames, routed, style)
    if held is not None:
        said = (*said, *undrawn(frames, held[1], routed))
    # Its plots drawn (once: kept for the figure's own drawing), and what to say of those
    # that were not.
    if any(node.measured.spec.kind == "plot" for node in fitted.nodes):
        from flexo.plots import said as plots_said

        said = (*said, *plots_said(fitted.nodes, style, palette))
    if said:
        measured, fitted, routed = _with_said(said, measured, fitted, routed)
    overlay = (
        Overlay(
            tuple(shape.spec for shape in shapes),
            style,
            palette,
            boxes=part_boxes(routed.fitted, placed),
            groups=routed.fitted.measured.semantic.groups,
            root=routed.fitted.measured.semantic.root,
        )
        if shapes
        else None
    )
    document = emit_svg(routed, style=style, palette=palette, frames=placed, shapes=overlay)
    if overlay is not None and overlay.diagnostics:
        # (What is said of the shapes -- a part one names that is gone -- is the figure's.)
        said = tuple(overlay.diagnostics)
        measured, fitted, routed = _with_said(said, measured, fitted, routed)
    return Compilation(measured, fitted, routed, document, placed, overlay)


def _with_said(
    said: tuple, measured: MeasuredFigure, fitted: FittedFigure, routed: RoutedFigure
) -> tuple[MeasuredFigure, FittedFigure, RoutedFigure]:
    """The figure as laid out and routed, with more said of it."""

    measured = replace(measured, diagnostics=measured.diagnostics + said)
    fitted = replace(fitted, measured=measured)
    if routed.fitted.nodes == fitted.nodes:
        return measured, fitted, replace(routed, fitted=fitted)
    # (Routed with frames standing in it for their lines: said of that figure too.)
    among = routed.fitted.measured
    among = replace(among, diagnostics=among.diagnostics + said)
    return measured, fitted, replace(routed, fitted=replace(routed.fitted, measured=among))


def _layout_key(figure: FigureSpec, style: LayoutStyle) -> tuple:
    """Which drawing of a figure a draft's layout follows: the figure, on its page and at its
    spacing, its groups running the way they do (turned to fit a slide, another)."""

    kinds = tuple((group.id, group.layout.kind) for group in figure.groups)
    return (figure.id, figure.width, figure.height, style, kinds)


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


def _judged_slides(measured, fitted, routed, style, held=None):
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
    plain_routed = _route(plain, style, held)
    bends, plain_bends = _bends(routed), _bends(plain_routed)
    # (Bending no less, the slid layout is still the better if its lines meet their boxes
    # nearer the middles of their sides: a branch's last step level with the one feeding it.)
    better = bends < plain_bends or (
        bends == plain_bends
        and _off_middles(fitted, routed) < _off_middles(plain, plain_routed) - OFF_MIDDLE
    )
    if better and len(crossings(routed)) <= len(crossings(plain_routed)):
        return fitted, routed, True
    return plain, plain_routed, False


OFF_MIDDLE = 0.5
"""How much nearer the middles of their boxes' sides, in points over all its lines, a
layout's lines must meet them for it to be the better of two that bend as much."""


def _off_middles(fitted, routed: RoutedFigure) -> float:
    """How far, in all, the ends of a figure's lines are from the middles of the sides
    they meet: along each side, from where the line meets it to its middle."""

    boxes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    total = 0.0
    for edge in routed.edges:
        if len(edge.centerline) < 2:
            continue
        ends = (
            (edge.spec.source.node_id, edge.centerline[0]),
            (edge.spec.target.node_id, edge.centerline[-1]),
        )
        for node_id, point in ends:
            box = boxes.get(node_id)
            if box is not None:
                total += min(abs(point.x - box.center.x), abs(point.y - box.center.y))
    return total


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


def _with_room_rounds(
    figure, measured, fitted, routed, style, *, slide=True, rounds=None, held=None
):
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
            routed = _kept(routed, next_fitted, style, held)
        else:
            routed = _route(next_fitted, style, held)
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


def _uncrossed(figure, measured, fitted, routed, style, *, slide=True, held=None):
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
                _route(trial_fitted, style, held),
                style,
                slide=slide,
                held=held,
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


def _too_large(measured: MeasuredFigure) -> bool:
    """Wider than its page, or taller than a page with a height."""

    grown = {"layout.width.grown", "layout.height.grown"}
    return any(item.code in grown for item in measured.diagnostics)


COMPACT_SCALES = (0.8, 0.65, 0.5)
"""Spacing scales tried, in order, when a figure is wider (or taller) than its page."""

STRUCTURE_SCALES = (0.85, 0.7, 0.6, 0.5, 0.4)
"""Sizes tried, in order, for the structures with no size of their own when a figure is still
wider than its page with its spacing tightened: shares of their usual 20 by 15 label sizes."""


def _with_smaller_structures(figure: FigureSpec, style: LayoutStyle, scale: float) -> FigureSpec:
    """``figure`` with each structure that has neither a width nor a height of its own drawn
    ``scale`` times its usual size -- or ``figure`` itself, with none such."""

    from flexo.drawn import units

    u = units(style).u
    nodes, changed = [], False
    for node in figure.nodes:
        sized = node.property("width") is not None or node.property("height") is not None
        if node.kind == "structure" and not sized:
            size = (("width", round(20.0 * u * scale, 3)), ("height", round(15.0 * u * scale, 3)))
            node = replace(node, properties=(*node.properties, *size))
            changed = True
        nodes.append(node)
    return replace(figure, nodes=tuple(nodes)) if changed else figure

CROSSING_ROOM_TRIALS = 2
"""Most layouts tried, per figure, to route a crossing round instead of through."""

ROOM_ROUNDS = 3
"""How many times layout may be asked for more room before routing takes what it has."""

DRAFT_ROOM_ROUNDS = 0
"""How many times a draft's layout may be asked for more room (flexo.draft): none -- it is
given the room its last drawing had, and is drawn in full once the changes stop."""
