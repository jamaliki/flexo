"""Cell assignment for grid groups, shared by measurement and fitting.

A grid child either names its cell (``LayoutSpec.placements``) or flows into the
next free one. Both passes have to agree on the answer down to the cell, so the
assignment lives here rather than being repeated on either side of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from flexo.geometry import Size
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
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The width of every column and the height of every row, in points.

    A column with no content is not dropped: it keeps its slot, and
    ``column_widths`` may reserve a minimum width for it, which is how a lane
    that only holds a connector and its label gets its space.
    """

    column_widths = [0.0] * plan.columns
    row_heights = [0.0] * plan.rows
    for (row, column), size in zip(plan.cells, sizes, strict=True):
        column_widths[column] = max(column_widths[column], size.width)
        row_heights[row] = max(row_heights[row], size.height)
    for column, reserved in layout.column_widths:
        column_widths[column] = max(column_widths[column], reserved.points)
    return tuple(column_widths), tuple(row_heights)
