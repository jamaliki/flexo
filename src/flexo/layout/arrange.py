"""Where a group's children sit, and how much room they need to sit there.

Measurement and fitting have to give the same answer -- one asks how big a group
must be, the other where inside it each child goes -- so the arrangement lives
here once and both passes call it. ``align="ports"`` is why that mattered enough
to move: a ports-aligned row is *taller* than its tallest child, so the size and
the placement can no longer be derived from each other's assumptions.
"""

from __future__ import annotations

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Point, Rect, Size
from flexo.ir.semantic import LayoutKind, LayoutSpec
from flexo.layout.gaps import split_grid_gaps
from flexo.layout.grid import GridPlan, grid_anchor_lines, grid_plan, grid_tracks
from flexo.style import LayoutStyle

_EPSILON = 1e-7

PORT_ALIGN = "ports"
"""``align`` value that lines children up by their port line, not their box.

Text sits on a baseline; a component sits on the line its side ports live on.
Aligning boxes lines up whatever the boxes happen to contain -- a caption under
a vector, an inset's illustration -- while aligning port lines is what makes an
arrow run straight from one component through the next.
"""

CENTRE_ALIGN = "center"
"""``align`` value that centres children across the way a group runs.

A row centres each child on one line -- its box's middle, but for a part drawn over a
name or under one (a named structure, picture or mechanism: ``MeasuredNode.drawn``), whose
drawing's middle it is, and for a group of such parts, the line they stand on
(``MeasuredGroup.middle``). So a ``+`` between two named molecules stands level with them,
not with them and their names.
"""

NON_ANCHOR_KINDS = frozenset({"label", "spacer"})
"""Node kinds that never speak for a group's anchor.

A caption and a lane spacer are furniture around the thing being aligned, so a
composite takes its anchor from the first child that is neither.
"""


def anchor_offsets(sizes: tuple[Size, ...]) -> tuple[Point, ...]:
    """The fallback anchor of each child: the centre of its own box."""

    return tuple(Point(size.width / 2.0, size.height / 2.0) for size in sizes)


def declared_size(layout: LayoutSpec, intrinsic: Size) -> Size:
    """A group's size: whatever its layout asked for, else what it measured."""

    return Size(
        layout.width.points if layout.width is not None else intrinsic.width,
        layout.height.points if layout.height is not None else intrinsic.height,
    )


def resolved_anchors(
    sizes: tuple[Size, ...],
    anchors: tuple[Point, ...] | None,
) -> tuple[Point, ...]:
    return anchor_offsets(sizes) if anchors is None else anchors


def middle_lines(
    layout: LayoutSpec,
    sizes: tuple[Size, ...],
    middles: tuple[float | None, ...] | None,
) -> tuple[float, ...] | None:
    """Where each child's middle is, down from its top, for a row (or a grid's row) that
    centres what it holds (``CENTRE_ALIGN``) -- or ``None`` when every one's is its box's, so
    the row centres its boxes exactly as it always has. Equal sizes centre their boxes."""

    if middles is None or layout.align != CENTRE_ALIGN or layout.equal_size:
        return None
    lines = tuple(
        size.height / 2.0 if middle is None else middle
        for size, middle in zip(sizes, middles, strict=True)
    )
    if all(abs(line - size.height / 2.0) <= 1e-6 for line, size in zip(lines, sizes, strict=True)):
        return None
    return lines


def _middle_reach(sizes: tuple[Size, ...], lines: tuple[float, ...]) -> tuple[float, float]:
    """How far above their shared middle line some of ``sizes`` reach, and how far below."""

    return (
        max(lines),
        max(size.height - line for size, line in zip(sizes, lines, strict=True)),
    )


def cross_extent(
    sizes: tuple[Size, ...],
    anchors: tuple[Point, ...],
    *,
    vertical: bool,
) -> tuple[float, float]:
    """``(ascent, descent)`` of a ports-aligned line of children.

    Read exactly as a text baseline reads: the ascent is the furthest any child
    reaches above the shared line, the descent the furthest below, and the line
    needs both. That is why a ports-aligned row can be taller than its tallest
    child -- two children may hang off the line in opposite directions.
    """

    if vertical:
        ascents = tuple(anchor.y for anchor in anchors)
        descents = tuple(
            size.height - anchor.y for size, anchor in zip(sizes, anchors, strict=True)
        )
    else:
        ascents = tuple(anchor.x for anchor in anchors)
        descents = tuple(
            size.width - anchor.x for size, anchor in zip(sizes, anchors, strict=True)
        )
    return max(ascents), max(descents)


def arrangement_size(
    child_sizes: tuple[Size, ...],
    layout: LayoutSpec,
    style: LayoutStyle,
    *,
    kind: LayoutKind | None = None,
    gaps: tuple[float, ...] | None = None,
    child_ids: tuple[str, ...] | None = None,
    anchors: tuple[Point, ...] | None = None,
    middles: tuple[float | None, ...] | None = None,
) -> Size:
    if not child_sizes:
        return Size(0.0, 0.0)
    actual_kind = kind or layout.kind
    axis_gaps = (
        gaps
        if gaps is not None
        else (layout.axis_gap(actual_kind, style.gap),) * (len(child_sizes) - 1)
    )
    values = _equalized(child_sizes) if layout.equal_size else child_sizes
    ports = layout.align == PORT_ALIGN
    # Equal sizes line up by their centres: an anchor measured on a child's own
    # size would set each resized box off by a different amount.
    lines = resolved_anchors(values, None if layout.equal_size else anchors)
    # (Centred on their drawings' middles, a row may be taller than its tallest part.)
    middle = middle_lines(layout, values, middles)
    if actual_kind == "row":
        height = (
            sum(cross_extent(values, lines, vertical=True))
            if ports
            else sum(_middle_reach(values, middle))
            if middle is not None
            else max(size.height for size in values)
        )
        return Size(sum(size.width for size in values) + sum(axis_gaps), height)
    if actual_kind in {"column", "stack"}:
        width = (
            sum(cross_extent(values, lines, vertical=False))
            if ports
            else max(size.width for size in values)
        )
        return Size(width, sum(size.height for size in values) + sum(axis_gaps))
    if actual_kind == "overlay":
        if ports:
            return Size(
                sum(cross_extent(values, lines, vertical=False)),
                sum(cross_extent(values, lines, vertical=True)),
            )
        return Size(
            max(size.width for size in values),
            max(size.height for size in values),
        )
    # Without names no child can be addressed, so every one of them flows.
    plan = grid_plan(layout, child_ids if child_ids is not None else ("",) * len(values))
    column_widths, row_heights = grid_tracks(plan, values, layout, lines if ports else None)
    if middle is not None and not ports:
        row_heights = _middle_rows(plan, values, middle)[2]
    column_gaps, row_gaps = split_grid_gaps(
        gaps,
        plan.columns,
        plan.rows,
        layout.resolved_column_gap(style.gap),
        layout.resolved_row_gap(style.gap),
    )
    return Size(
        sum(column_widths) + sum(column_gaps),
        sum(row_heights) + sum(row_gaps),
    )


def arrange(
    child_sizes: tuple[Size, ...],
    child_ids: tuple[str, ...],
    layout: LayoutSpec,
    kind: LayoutKind,
    content: Rect,
    *,
    gaps: tuple[float, ...],
    row_gap: float,
    column_gap: float,
    anchors: tuple[Point, ...] | None = None,
    group_id: str = "",
    middles: tuple[float | None, ...] | None = None,
) -> tuple[Rect, ...]:
    """One rectangle per child, in the order the children were given."""

    if not child_sizes:
        return ()
    sizes = _equalized(child_sizes) if layout.equal_size else child_sizes
    ports = layout.align == PORT_ALIGN
    lines = resolved_anchors(sizes, None if layout.equal_size else anchors)
    middle = None if ports else middle_lines(layout, sizes, middles)
    if kind == "row":
        total = sum(size.width for size in sizes) + sum(gaps)
        start, actual_gaps = linear_justification(layout.justify, content.width, total, gaps)
        x = content.x + start
        ascent = 0.0
        if ports:
            # The aligned line sits in the middle of any room to spare, as a
            # centred row would: the canvas is wider than what it holds.
            ascent, descent = cross_extent(sizes, lines, vertical=True)
            ascent += max(0.0, content.height - ascent - descent) / 2.0
        elif middle is not None:
            # (Centred on one line through the middles of what they draw: CENTRE_ALIGN.)
            ascent, descent = _middle_reach(sizes, middle)
            ascent += max(0.0, content.height - ascent - descent) / 2.0
        result = []
        for index, size in enumerate(sizes):
            height = content.height if layout.align == "stretch" else size.height
            y = (
                content.y + ascent - lines[index].y
                if ports
                else content.y + ascent - middle[index]
                if middle is not None
                else cross_position(layout.align, content.y, content.height, height)
            )
            result.append(Rect(x, y, size.width, height))
            if index < len(actual_gaps):
                x += size.width + actual_gaps[index]
        return tuple(result)
    if kind in {"column", "stack"}:
        total = sum(size.height for size in sizes) + sum(gaps)
        start, actual_gaps = linear_justification(layout.justify, content.height, total, gaps)
        y = content.y + start
        line = 0.0
        if ports:
            line, reach = cross_extent(sizes, lines, vertical=False)
            line += max(0.0, content.width - line - reach) / 2.0
        result = []
        for index, size in enumerate(sizes):
            width = content.width if layout.align == "stretch" else size.width
            x = (
                content.x + line - lines[index].x
                if ports
                else cross_position(layout.align, content.x, content.width, width)
            )
            result.append(Rect(x, y, width, size.height))
            if index < len(actual_gaps):
                y += size.height + actual_gaps[index]
        return tuple(result)
    if kind == "overlay":
        if ports:
            left = cross_extent(sizes, lines, vertical=False)[0]
            top = cross_extent(sizes, lines, vertical=True)[0]
            return tuple(
                Rect(
                    content.x + left - anchor.x,
                    content.y + top - anchor.y,
                    size.width,
                    size.height,
                )
                for size, anchor in zip(sizes, lines, strict=True)
            )
        return tuple(
            Rect(
                cross_position(layout.align, content.x, content.width, size.width),
                cross_position(layout.align, content.y, content.height, size.height),
                size.width,
                size.height,
            )
            for size in sizes
        )
    return _arrange_grid(
        sizes,
        child_ids,
        layout,
        content,
        row_gap=row_gap,
        column_gap=column_gap,
        gaps=gaps,
        anchors=lines if ports else None,
        group_id=group_id,
        middles=middle,
    )


def _middle_rows(
    plan: GridPlan, sizes: tuple[Size, ...], lines: tuple[float, ...]
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """For a grid that centres its rows' parts on their middles (``middle_lines``): how far
    above its line each row's parts reach, how far below, and so how tall each row is."""

    tops = [0.0] * plan.rows
    bottoms = [0.0] * plan.rows
    for (row, _), size, line in zip(plan.cells, sizes, lines, strict=True):
        tops[row] = max(tops[row], line)
        bottoms[row] = max(bottoms[row], size.height - line)
    heights = tuple(top + bottom for top, bottom in zip(tops, bottoms, strict=True))
    return tuple(tops), tuple(bottoms), heights


def _arrange_grid(
    sizes: tuple[Size, ...],
    child_ids: tuple[str, ...],
    layout: LayoutSpec,
    content: Rect,
    *,
    row_gap: float,
    column_gap: float,
    gaps: tuple[float, ...] | None = None,
    anchors: tuple[Point, ...] | None,
    group_id: str,
    middles: tuple[float, ...] | None = None,
) -> tuple[Rect, ...]:
    plan = grid_plan(layout, child_ids)
    column_widths, row_heights = grid_tracks(plan, sizes, layout, anchors)
    tops: tuple[float, ...] = ()
    if middles is not None and anchors is None:
        # (Each row's parts centred on one line through the middles of what they draw.)
        tops, _, row_heights = _middle_rows(plan, sizes, middles)
    column_gaps, row_gaps = split_grid_gaps(gaps, plan.columns, plan.rows, column_gap, row_gap)
    needed = Size(
        sum(column_widths) + sum(column_gaps),
        sum(row_heights) + sum(row_gaps),
    )
    if needed.width > content.width + _EPSILON or needed.height > content.height + _EPSILON:
        raise FlexoError(
            Diagnostic(
                "layout.grid.overflow",
                "Grid does not fit content bounds.",
                entity_id=group_id,
            )
        )
    start_x, actual_x_gap = justification(
        layout.justify, content.width, needed.width, 0.0, plan.columns
    )
    start_y = (
        content.y
        if anchors is not None
        else cross_position(layout.align, content.y, content.height, needed.height)
    )
    xs = [content.x + start_x]
    for width, gap in zip(column_widths[:-1], column_gaps, strict=True):
        xs.append(xs[-1] + width + gap + actual_x_gap)
    ys = [start_y]
    for height, gap in zip(row_heights[:-1], row_gaps, strict=True):
        ys.append(ys[-1] + height + gap)
    if anchors is None and tops:
        assert middles is not None
        return tuple(
            Rect(
                cross_position(layout.align, xs[column], column_widths[column], size.width),
                ys[row] + tops[row] - line,
                size.width,
                size.height,
            )
            for (row, column), size, line in zip(plan.cells, sizes, middles, strict=True)
        )
    if anchors is None:
        return tuple(
            Rect(
                cross_position(layout.align, xs[column], column_widths[column], size.width),
                cross_position(layout.align, ys[row], row_heights[row], size.height),
                size.width,
                size.height,
            )
            for (row, column), size in zip(plan.cells, sizes, strict=True)
        )
    lefts, tops = grid_anchor_lines(plan, anchors)
    return tuple(
        Rect(
            xs[column] + lefts[column] - anchor.x,
            ys[row] + tops[row] - anchor.y,
            size.width,
            size.height,
        )
        for (row, column), size, anchor in zip(plan.cells, sizes, anchors, strict=True)
    )


def _equalized(values: tuple[Size, ...]) -> tuple[Size, ...]:
    width = max(size.width for size in values)
    height = max(size.height for size in values)
    return tuple(Size(width, height) for _ in values)


def justification(
    justify: str,
    available: float,
    natural: float,
    gap: float,
    count: int,
) -> tuple[float, float]:
    extra = max(0.0, available - natural)
    if justify == "center":
        return extra / 2.0, gap
    if justify == "end":
        return extra, gap
    if justify == "space-between" and count > 1:
        return 0.0, gap + extra / (count - 1)
    return 0.0, gap


def linear_justification(
    justify: str,
    available: float,
    natural: float,
    gaps: tuple[float, ...],
) -> tuple[float, tuple[float, ...]]:
    extra = max(0.0, available - natural)
    if justify == "center":
        return extra / 2.0, gaps
    if justify == "end":
        return extra, gaps
    if justify == "space-between" and gaps:
        addition = extra / len(gaps)
        return 0.0, tuple(gap + addition for gap in gaps)
    return 0.0, gaps


def cross_position(align: str, start: float, available: float, size: float) -> float:
    if align == "center":
        return start + max(0.0, available - size) / 2.0
    if align == "end":
        return start + max(0.0, available - size)
    return start
