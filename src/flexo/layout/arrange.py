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
from flexo.layout.grid import grid_anchor_lines, grid_plan, grid_tracks
from flexo.style import LayoutStyle

_EPSILON = 1e-7

PORT_ALIGN = "ports"
"""``align`` value that lines children up by their port line, not their box.

Text sits on a baseline; a component sits on the line its side ports live on.
Aligning boxes lines up whatever the boxes happen to contain -- a caption under
a vector, an inset's illustration -- while aligning port lines is what makes an
arrow run straight from one component through the next.
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
    lines = resolved_anchors(values, anchors)
    if actual_kind == "row":
        height = (
            sum(cross_extent(values, lines, vertical=True))
            if ports
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
    return Size(
        sum(column_widths) + layout.resolved_column_gap(style.gap) * (plan.columns - 1),
        sum(row_heights) + layout.resolved_row_gap(style.gap) * (plan.rows - 1),
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
) -> tuple[Rect, ...]:
    """One rectangle per child, in the order the children were given."""

    if not child_sizes:
        return ()
    sizes = _equalized(child_sizes) if layout.equal_size else child_sizes
    ports = layout.align == PORT_ALIGN
    lines = resolved_anchors(sizes, anchors)
    if kind == "row":
        total = sum(size.width for size in sizes) + sum(gaps)
        start, actual_gaps = linear_justification(layout.justify, content.width, total, gaps)
        x = content.x + start
        ascent = cross_extent(sizes, lines, vertical=True)[0] if ports else 0.0
        result = []
        for index, size in enumerate(sizes):
            height = content.height if layout.align == "stretch" else size.height
            y = (
                content.y + ascent - lines[index].y
                if ports
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
        line = cross_extent(sizes, lines, vertical=False)[0] if ports else 0.0
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
        anchors=lines if ports else None,
        group_id=group_id,
    )


def _arrange_grid(
    sizes: tuple[Size, ...],
    child_ids: tuple[str, ...],
    layout: LayoutSpec,
    content: Rect,
    *,
    row_gap: float,
    column_gap: float,
    anchors: tuple[Point, ...] | None,
    group_id: str,
) -> tuple[Rect, ...]:
    plan = grid_plan(layout, child_ids)
    column_widths, row_heights = grid_tracks(plan, sizes, layout, anchors)
    needed = Size(
        sum(column_widths) + column_gap * (plan.columns - 1),
        sum(row_heights) + row_gap * (plan.rows - 1),
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
        layout.justify, content.width, needed.width, column_gap, plan.columns
    )
    start_y = (
        content.y
        if anchors is not None
        else cross_position(layout.align, content.y, content.height, needed.height)
    )
    xs = [content.x + start_x]
    for width in column_widths[:-1]:
        xs.append(xs[-1] + width + actual_x_gap)
    ys = [start_y]
    for height in row_heights[:-1]:
        ys.append(ys[-1] + height + row_gap)
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
