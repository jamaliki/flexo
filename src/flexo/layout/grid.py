"""Cell assignment for grid groups, shared by measurement and fitting.

A grid child either names its cell (``LayoutSpec.placements``) or flows into the
next free one. Both passes have to agree on the answer down to the cell, so the
assignment lives here rather than being repeated on either side of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from flexo.geometry import Point, Size
from flexo.ir.semantic import LayoutSpec


@dataclass(frozen=True, slots=True)
class GridPlan:
    """Which cell every grid child occupies, and how large the grid became."""

    columns: int
    rows: int
    cells: tuple[tuple[int, int], ...]
    """The ``(row, column)`` of each child, in the order the children were given."""


def grid_plan(layout: LayoutSpec, child_ids: tuple[str, ...]) -> GridPlan:
    """Assign a cell to every child: addressed ones first, then the flow.

    Addressed children claim their cells outright. The rest keep row-major
    order, skipping any cell already claimed, so a sparse grid needs no filler
    children to hold its holes open. The number of rows is whatever the last
    occupied row is -- an address alone can grow the grid.
    """

    columns = layout.columns or 1
    placements = layout.placement_map()
    cells: list[tuple[int, int] | None] = [placements.get(child_id) for child_id in child_ids]
    taken = {cell for cell in cells if cell is not None}
    cursor = 0
    for index, cell in enumerate(cells):
        if cell is not None:
            continue
        while divmod(cursor, columns) in taken:
            cursor += 1
        cells[index] = divmod(cursor, columns)
        taken.add(cells[index])
        cursor += 1
    resolved = tuple(cell for cell in cells if cell is not None)
    rows = max((row for row, _ in resolved), default=-1) + 1
    return GridPlan(columns, rows, resolved)


def grid_tracks(
    plan: GridPlan,
    sizes: tuple[Size, ...],
    layout: LayoutSpec,
    anchors: tuple[Point, ...] | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The width of every column and the height of every row, in points.

    A column with no content is not dropped: it keeps its slot, and
    ``column_widths`` may reserve a minimum width for it, which is how a lane
    that only holds a connector and its label gets its space.

    Given ``anchors`` -- one anchor offset per child, from its own top-left --
    the tracks are measured the way a line of type is: a row is as tall as the
    furthest reach above its shared anchor line plus the furthest below, which
    can exceed its tallest child. Without them a track is simply as large as its
    largest child.
    """

    column_widths = [0.0] * plan.columns
    row_heights = [0.0] * plan.rows
    if anchors is None:
        for (row, column), size in zip(plan.cells, sizes, strict=True):
            column_widths[column] = max(column_widths[column], size.width)
            row_heights[row] = max(row_heights[row], size.height)
    else:
        lefts, tops = grid_anchor_lines(plan, anchors)
        rights = [0.0] * plan.columns
        bottoms = [0.0] * plan.rows
        for (row, column), size, anchor in zip(plan.cells, sizes, anchors, strict=True):
            rights[column] = max(rights[column], size.width - anchor.x)
            bottoms[row] = max(bottoms[row], size.height - anchor.y)
        column_widths = [left + right for left, right in zip(lefts, rights, strict=True)]
        row_heights = [top + bottom for top, bottom in zip(tops, bottoms, strict=True)]
    for column, reserved in layout.column_widths:
        column_widths[column] = max(column_widths[column], reserved.points)
    return tuple(column_widths), tuple(row_heights)


def grid_anchor_lines(
    plan: GridPlan,
    anchors: tuple[Point, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The shared anchor line of every column and every row, from its own origin.

    A column's line is the furthest left any of its children reaches from its own
    anchor; a row's is the furthest above. Placing each child so its anchor lands
    on that line is what puts one x down a column of glyphs and one y along a
    chain that reads across.
    """

    lefts = [0.0] * plan.columns
    tops = [0.0] * plan.rows
    for (row, column), anchor in zip(plan.cells, anchors, strict=True):
        lefts[column] = max(lefts[column], anchor.x)
        tops[row] = max(tops[row], anchor.y)
    return tuple(lefts), tuple(tops)
