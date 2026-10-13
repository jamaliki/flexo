"""Frames: a box round shapes wherever they are in the figure.

A group arranges what it holds, so it can only hold what stands together. A frame arranges
nothing: it names the shapes and groups it goes round (``around``, their ids), is drawn
round them where the layout put them -- taking no room of its own -- and lies behind them,
in front of them, or over them as a tint (``layer``).

    - id: stage
      kind: frame
      label: Stage 1
      properties: {around: "encoder, decoder", layer: behind}

It is written as a shape, so it has a shape's words, colours and line style; the layout
never sees it (``split``), and it is placed once everything else has been (``place``),
centred on what it holds. It takes no room, but for its title: that has a band kept clear
for it over the shape at the frame's top, and room beside the frame where a long title
widens it (``title_room``), so it lies on nothing -- a line that comes down there it stops
short of. The title stands at the frame's top left, or at the corner its ``title_side``
names, as a group's does: ``right``, ``bottom-left`` or ``bottom-right`` -- its band under
the shape at the frame's bottom then, and all of this the same, seen in a mirror.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from itertools import pairwise

from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Point, Rect
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import TextMetrics
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import TITLE_SIDES, FigureSpec, GroupSpec, NodeSpec
from flexo.style import LayoutStyle, Palette

FRAME_KIND = "frame"
LAYERS = ("behind", "front", "over")
"""Where a frame lies: behind what it goes round, filled; in front, an outline alone; over
it, a tint the shapes show through."""
TINT = 0.22
"""How much of its colour a frame over its shapes lays on them."""


@dataclass(frozen=True, slots=True)
class PlacedFrame:
    spec: NodeSpec
    bounds: Rect
    label: TextMetrics | None
    layer: str
    inset: float
    """The room between the frame and what it goes round."""
    title_x: float = 0.0
    """Where its title starts: at the frame's left, short of any line that comes down
    there (``_reach``) -- at its right, as far from there as the title is wide."""
    title_side: str = TITLE_SIDES[0]
    """The corner its title stands at (``title_side_of``)."""

    @property
    def title(self) -> Rect | None:
        """Where its title is drawn: in its band, at the frame's top or at its bottom."""

        if self.label is None:
            return None
        top = (
            self.bounds.bottom - self.inset - self.label.height
            if _below(self.title_side)
            else self.bounds.y + self.inset
        )
        return Rect(self.title_x, top, self.label.width, self.label.height)


def around(spec: NodeSpec) -> tuple[str, ...]:
    """The ids a frame goes round, as written: ``"encoder, decoder"``."""

    written = str(spec.property("around", "")).split(",")
    return tuple(part for part in (item.strip() for item in written) if part)


def layer_of(spec: NodeSpec) -> str:
    written = str(spec.property("layer", LAYERS[0])).strip().lower()
    return written if written in LAYERS else LAYERS[0]


def title_side_of(spec: NodeSpec) -> str:
    """The corner a frame's title stands at, in a group's words for it (``title_side``):
    ``left``, the top left, where none is written -- or what is written is none of them
    (said: ``place``)."""

    written = _title_side_written(spec)
    return written if written in TITLE_SIDES else TITLE_SIDES[0]


def _title_side_written(spec: NodeSpec) -> str:
    return str(spec.property("title_side") or TITLE_SIDES[0]).strip().lower()


def _below(side: str) -> bool:
    return side.startswith("bottom")


def _right(side: str) -> bool:
    return side.endswith("right")


def split(figure: FigureSpec) -> tuple[FigureSpec, tuple[NodeSpec, ...]]:
    """``figure`` as the layout sees it -- no frame among its shapes, in its groups or at
    the end of a line -- and its frames."""

    frames = tuple(node for node in figure.nodes if node.kind == FRAME_KIND)
    if not frames:
        return figure, ()
    ids = {frame.id for frame in frames}
    return (
        replace(
            figure,
            nodes=tuple(node for node in figure.nodes if node.id not in ids),
            groups=tuple(
                replace(group, children=tuple(c for c in group.children if c not in ids))
                for group in figure.groups
            ),
            edges=tuple(
                edge
                for edge in figure.edges
                if edge.source.node_id not in ids and edge.target.node_id not in ids
            ),
        ),
        frames,
    )


def place(
    frames: tuple[NodeSpec, ...], routed: RoutedFigure, style: LayoutStyle
) -> tuple[tuple[PlacedFrame, ...], tuple[Diagnostic, ...]]:
    """Each frame round what it names, where the layout put it; and what to say of a frame
    that names nothing there is, or has its title somewhere there is not."""

    if not frames:
        return (), ()
    fitted = routed.fitted
    boxes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    boxes |= {
        group.measured.spec.id: group.bounds
        for group in fitted.groups
        if group.measured.spec.id != fitted.measured.semantic.root
    }
    inset = _inset(style)
    drawn = _strokes(routed)
    placed: list[PlacedFrame] = []
    said: list[Diagnostic] = []
    for spec in frames:
        named = around(spec)
        found = [boxes[item] for item in named if item in boxes]
        missing = [item for item in named if item not in boxes]
        if missing or not found:
            what = ", ".join(f"“{item}”" for item in missing) or "nothing"
            said.append(
                Diagnostic(
                    "frame.around.unknown",
                    f"The frame goes round {what}, which {'is' if len(missing) < 2 else 'are'} "
                    "not in the figure.",
                    Severity.WARNING,
                    entity_id=spec.id,
                    hint="Name the shapes or groups it goes round in its properties.around.",
                )
            )
        side, written = title_side_of(spec), _title_side_written(spec)
        if written != side:
            said.append(
                Diagnostic(
                    "frame.title-side.unknown",
                    f"The frame\u2019s title can\u2019t stand at “{written}”: it is drawn at the "
                    "top left.",
                    Severity.WARNING,
                    entity_id=spec.id,
                    hint="Its properties.title_side is left (the top left), right (the top "
                    "right), bottom-left or bottom-right.",
                )
            )
        if not found:
            continue
        label = _title(spec, style)
        held = _round(found)
        band = label.height + style.compact_gap.points if label is not None else 0.0
        if _below(side):
            # (Under its shapes, the same: the lines that go down through the band there.)
            lines = _crossing(
                drawn, held.bottom + style.compact_gap.points, held.bottom + band
            )
            ends, top = _feet(found), held.y - inset
        else:
            # (The lines that come down where its title is: through the band, clear of its
            # gap.)
            lines = _crossing(drawn, held.y - band, held.y - style.compact_gap.points)
            ends, top = _heads(found), held.y - inset - band
        reach, title_x = _reach(held, ends, label, style, lines, right=_right(side))
        middle = held.x + held.width / 2.0
        bounds = Rect(middle - reach, top, 2.0 * reach, held.height + 2.0 * inset + band)
        placed.append(PlacedFrame(spec, bounds, label, layer_of(spec), inset, title_x, side))
    return tuple(placed), tuple(said)


def _title(spec: NodeSpec, style: LayoutStyle) -> TextMetrics | None:
    from flexo.text import TextMeasurer, title_runs, title_typography

    if not spec.label:
        return None
    typography = style.typography
    return TextMeasurer(title_typography(typography)).measure(
        title_runs(spec.label, typography), weight=typography.title_weight
    )


def _round(boxes: list[Rect]) -> Rect:
    left, top = min(box.x for box in boxes), min(box.y for box in boxes)
    return Rect(
        left, top, max(box.right for box in boxes) - left, max(box.bottom for box in boxes) - top
    )


def _heads(boxes: list[Rect]) -> Rect:
    """Those of ``boxes`` at the top, as one: the frame's top is theirs, and its title's place
    over them."""

    top = min(box.y for box in boxes)
    return _round([box for box in boxes if box.y <= top + 0.5])


def _feet(boxes: list[Rect]) -> Rect:
    """Those of ``boxes`` at the bottom, as one: where a title under the frame's shapes is."""

    bottom = max(box.bottom for box in boxes)
    return _round([box for box in boxes if box.bottom >= bottom - 0.5])


def _reach(
    held: Rect,
    heads: Rect,
    label: TextMetrics | None,
    style: LayoutStyle,
    lines: list[tuple[float, float]],
    *,
    right: bool = False,
) -> tuple[float, float]:
    """How far a frame reaches either side of the middle of what it holds (``held``), and
    where its title starts.

    The frame stays centred on what it holds, so a title longer than that widens it both
    ways alike. The title starts at the frame's left; where a line comes down through its
    band (``lines``, the stretch of the band each crosses) it ends short of the line, the
    frame the wider for it. Over shapes that start further in than the frame does (the top
    of an L) it starts with them: what is beside them is not the frame's.

    At the frame's ``right`` it is the same seen in a mirror: the title ends at the frame's
    right, starts past a line through its band, and ends with shapes that end further in.
    (``heads``: the shapes its band is over -- or under, those at the frame's bottom.)"""

    inset = _inset(style)
    middle = held.x + held.width / 2.0
    reach = held.width / 2.0 + inset
    if label is None:
        return reach, held.x
    if right:
        # (Turned about the middle of what it holds, placed from the left, and turned back.)
        turned = Rect(2.0 * middle - heads.right, heads.y, heads.width, heads.height)
        across = [(2.0 * middle - end, 2.0 * middle - start) for start, end in lines]
        reach, start = _reach(held, turned, label, style, across)
        return reach, 2.0 * middle - start - label.width
    if heads.x > held.x + 0.5:
        return max(reach, heads.x + label.width + inset - middle), heads.x
    clear = style.compact_gap.points
    reach = max(reach, label.width / 2.0 + inset)
    for _ in range(len(lines) + 1):
        start = middle - reach + inset
        met = [
            left
            for left, right in lines
            if right > start - clear and left < start + label.width + clear
        ]
        if not met:
            break
        reach = middle - (min(met) - clear - label.width) + inset
    return reach, middle - reach + inset


def _strokes(routed: RoutedFigure) -> list[tuple[Point, ...]]:
    """Every line of the figure as it was routed, a run of points each."""

    runs = [edge.centerline for edge in routed.edges]
    for net in routed.nets:
        runs += [net.rail, *net.trunks, *net.joins]
        runs += [stem.centerline for stem in (*net.source_stems, *net.target_stems)]
    return [run for run in runs if len(run) > 1]


def _crossing(
    runs: list[tuple[Point, ...]], top: float, bottom: float
) -> list[tuple[float, float]]:
    """Where ``runs`` pass between ``top`` and ``bottom``: the stretch across of each piece
    that does."""

    found: list[tuple[float, float]] = []
    for run in runs:
        for one, other in pairwise(run):
            high, low = sorted((one, other), key=lambda point: point.y)
            if low.y <= top or high.y >= bottom:
                continue
            if low.y - high.y < 1e-6:
                found.append((min(one.x, other.x), max(one.x, other.x)))
                continue

            def across(y: float, high: Point = high, low: Point = low) -> float:
                return high.x + (low.x - high.x) * (y - high.y) / (low.y - high.y)

            ends = across(max(high.y, top)), across(min(low.y, bottom))
            found.append((min(ends), max(ends)))
    return found


def title_room(
    frames: tuple[NodeSpec, ...], fitted: FittedFigure, style: LayoutStyle
) -> dict[str, dict[str, float]]:
    """The room a titled frame's title asks of the layout, as ``routing.room.with_room``
    takes it. Over each shape at the frame's top, a band as deep as the title and the
    frame's own inset; and beside the shapes at its sides, as much as the title makes the
    frame wider than what it holds. Each is kept in the gap before that shape -- in a row,
    a column or a grid -- else at that side of the group that holds it, where there is not
    that much free already. So the title lies on nothing (not the shape above, nor that
    group's own title), and the frame it widens runs under nothing. A title at the frame's
    bottom has its band under each shape there instead: what is below makes way, and
    nothing above does."""

    from flexo.hierarchy import parent_map

    semantic = fitted.measured.semantic
    groups = {group.id: group for group in semantic.groups}
    parents = parent_map(semantic.groups)
    boxes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    boxes |= {group.measured.spec.id: group.bounds for group in fitted.groups}
    inset = _inset(style)
    needs: dict[str, dict[str, float]] = {}
    for spec in frames:
        named = [item for item in around(spec) if item in boxes and item in parents]
        label = _title(spec, style)
        if label is None or not named:
            continue
        held = _round([boxes[item] for item in named])
        band = label.height + style.compact_gap.points + inset
        corner = title_side_of(spec)
        below = _below(corner)
        lines = _expected(named, semantic, groups, boxes, held, below=below)
        ends = (_feet if below else _heads)([boxes[item] for item in named])
        reach, _ = _reach(held, ends, label, style, lines, right=_right(corner))
        wider = reach - (held.width / 2.0 + inset)
        for item in named:
            mine = boxes[item]
            for side, amount, there in (
                ("bottom", band, mine.bottom >= held.bottom - 0.5)
                if below
                else ("top", band, mine.y <= held.y + 0.5),
                ("left", wider, mine.x <= held.x + 0.5),
                ("right", wider, mine.right >= held.right - 0.5),
            ):
                if not there:
                    continue
                holder = groups[parents[item]]
                where, free = _beside(item, holder, boxes, side)
                if where is not None and amount - free > 0.5:
                    asked = needs.setdefault(holder.id, {})
                    asked[where] = max(asked.get(where, 0.0), amount - free)
    return needs


def _expected(
    named: list[str],
    semantic: FigureSpec,
    groups: dict[str, GroupSpec],
    boxes: dict[str, Rect],
    held: Rect,
    *,
    below: bool = False,
) -> list[tuple[float, float]]:
    """Where a line is likely to come down through a frame's title before any is routed:
    at the middle of a shape at the frame's top that is joined to one above the frame.
    (A title at the frame's bottom, ``below``: of a shape there joined to one under it.)"""

    inside: dict[str, str] = {}
    for item in named:
        within = [item]
        while within:
            one = within.pop()
            inside[one] = item
            within += groups[one].children if one in groups else ()
    joined = [(edge.source.node_id, edge.target.node_id) for edge in semantic.edges]
    for net in semantic.nets:
        joined += [(a.node_id, b.node_id) for a in net.sources for b in net.targets]
    found: list[tuple[float, float]] = []
    for pair in joined:
        for mine, other in (pair, pair[::-1]):
            if mine not in inside or other in inside or mine not in boxes or other not in boxes:
                continue
            if below:
                there = boxes[inside[mine]].bottom >= held.bottom - 0.5
                beyond = boxes[other].y >= held.bottom - 0.5
            else:
                there = boxes[inside[mine]].y <= held.y + 0.5
                beyond = boxes[other].bottom <= held.y + 0.5
            if there and beyond:
                middle = boxes[mine].x + boxes[mine].width / 2.0
                found.append((middle, middle))
    return found


def _beside(
    item: str, holder: GroupSpec, boxes: dict[str, Rect], side: str
) -> tuple[str | None, float]:
    """Where in ``holder`` the room on one side of ``item`` is (over it, ``"top"``, under
    it, ``"bottom"``, or to its ``"left"`` or ``"right"``), and how much is free there
    already.

    With nothing of the group's on that side of it, the group's own side -- and free, what
    the group's other parts stand out past it; else the gap before it (``"gap:2"``) in a
    row, a column or a grid. ``None`` in a group laid out some other way with something
    there: no gap is its own."""

    mine = boxes[item]
    # (The side a box starts at going that way, and the one it ends at: smaller is before.)
    lead = {
        "top": lambda b: b.y,
        "bottom": lambda b: -b.bottom,
        "left": lambda b: b.x,
        "right": lambda b: -b.right,
    }[side]
    trail = {
        "top": lambda b: b.bottom,
        "bottom": lambda b: -b.y,
        "left": lambda b: b.right,
        "right": lambda b: -b.x,
    }[side]
    parts = [child for child in holder.children if child in boxes]
    before = [
        child for child in parts if child != item and trail(boxes[child]) <= lead(mine) + 0.5
    ]
    if not before:
        return side, lead(mine) - min(lead(boxes[child]) for child in parts)
    order = list(holder.children)
    if holder.layout.kind == ("column" if side in ("top", "bottom") else "row"):
        nearest = max(before, key=lambda child: trail(boxes[child]))
        return f"gap:{min(order.index(item), order.index(nearest))}", 0.0
    if holder.layout.kind == "grid" and holder.layout.columns:
        columns = holder.layout.columns
        if side == "bottom":
            # (The gap under its row is the one after the gap over it: the first of the
            # rows', with no row over it.)
            over, _ = _beside(item, holder, boxes, "top")
            under = columns - 1 if over == "top" else int(str(over).removeprefix("gap:")) + 1
            return f"gap:{under}", 0.0
        # The rows over it (the columns beside it), counted as they are seen; a grid's row
        # gaps come after its column gaps.
        runs, end = 0, None
        for child in sorted(before, key=lambda child: lead(boxes[child])):
            if end is None or lead(boxes[child]) >= end - 0.5:
                runs += 1
            end = trail(boxes[child]) if end is None else max(end, trail(boxes[child]))
        gap = {"top": columns - 1 + runs - 1, "left": runs - 1, "right": columns - 1 - runs}
        return f"gap:{gap[side]}", 0.0
    return None, 0.0


def margin(frames: tuple[NodeSpec, ...], style: LayoutStyle) -> float:
    """How far a frame stands out from what it goes round. (The page's margin is that much
    wider, so a frame round shapes at the page's edge is on the page; a title's room is
    kept where it is: ``title_room``.)"""

    return _inset(style) if frames else 0.0


def _inset(style: LayoutStyle) -> float:
    return max(4.0, style.group_padding.points * 0.5)


def draw(
    parent: ET.Element,
    frame: PlacedFrame,
    style: LayoutStyle,
    palette: Palette,
    *,
    within: Rect | None = None,
    name: str = "",
) -> None:
    """One frame: its box and its title. ``within``: the part of it inside a container it
    shows through (``name``), drawn there again over the container's own fill -- only that
    part, and to an editor a part of the frame, not a shape of its own."""

    from flexo.components import node_tone
    from flexo.render import toned
    from flexo.render_common import dashes, paint_attributes, paint_override, render_runs
    from flexo.svg import element, inkscape_attr
    from flexo.text import title_typography

    spec, bounds = frame.spec, frame.bounds
    radius = (
        style.container_radius.points
        if style.container_radius is not None
        else style.corner_radius.points * 1.5
    )
    width = (
        style.container_stroke_width.points
        if style.container_stroke_width is not None
        else style.stroke_width.points
    )
    # In its own colour where it was given one; else as a container is.
    mine = toned(palette, spec, style)
    family = "block" if node_tone(spec, False) is not None else "container"
    filled = frame.layer != "front"
    attributes = paint_attributes(
        palette=mine,
        fill_role=f"{family}-fill" if filled else None,
        stroke_role=f"{family}-stroke",
        stroke_width=max(width, 0.75),
        fill=paint_override(spec, "fill") if filled else None,
        stroke=paint_override(spec, "stroke"),
    )
    if not filled:
        attributes["fill"] = "none"
    if frame.layer == "over":
        attributes["fill__opacity"] = TINT
    attributes |= dashes(spec.line, max(width, 0.75))
    if within is None:
        group = element(
            parent,
            "g",
            id=spec.id,
            data__flexo__entity="component",
            data__flexo__kind=FRAME_KIND,
            data__flexo__role=spec.role,
            data__flexo__layer=frame.layer,
            **{inkscape_attr("label"): spec.text or spec.id},
        )
        part = spec.id
    else:
        part = f"{spec.id}.in.{name}"
        clip = element(parent, "clipPath", id=f"{part}.clip")
        element(clip, "rect", x=within.x, y=within.y, width=within.width, height=within.height)
        group = element(parent, "g", clip__path=f"url(#{part}.clip)", data__hit__for=spec.id)
    element(
        group,
        "rect",
        id=f"{part}.body",
        x=bounds.x,
        y=bounds.y,
        width=bounds.width,
        height=bounds.height,
        rx=radius,
        # (In front of its shapes, only its line is its own to press: they are under it.)
        pointer__events="stroke" if frame.layer != "behind" else None,
        **attributes,
    )
    if frame.label is not None:
        # (At the frame's right its lines end together there, as a group's title's do.)
        right = _right(frame.title_side)
        render_runs(
            group,
            f"{part}.label",
            frame.label,
            x=frame.title_x + frame.label.width if right else frame.title_x,
            y=frame.title.y + frame.label.baseline,
            typography=title_typography(style.typography),
            palette=mine,
            fill_role="ink",
            fill=paint_override(spec, "label"),
            anchor="end" if right else None,
            weight=style.typography.title_weight,
        )
