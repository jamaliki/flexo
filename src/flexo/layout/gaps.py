"""Edge-aware spacing for linear layout groups."""

from __future__ import annotations

from collections.abc import Mapping

from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutKind, layout_connections
from flexo.layout.grid import grid_plan
from flexo.style import LayoutStyle


def routing_gaps_for_group(
    figure: FigureSpec,
    group_id: str,
    style: LayoutStyle,
    *,
    kind: LayoutKind | None = None,
    edge_labels: Mapping[str, TextMetrics] | None = None,
) -> tuple[float, ...]:
    """Return a gap for every sibling boundary, enlarged for crossing routes.

    ``edge_labels`` carries measured label metrics keyed by edge ID. A boundary
    crossed by a labeled connection is widened to hold the label plus one
    padding on either side, so the label never overlaps the components it sits
    between.
    """

    groups = {group.id: group for group in figure.groups}
    group = groups[group_id]
    boundary_count = max(0, len(group.children) - 1)
    actual_kind = kind or group.layout.kind
    base = group.layout.axis_gap(actual_kind, style.gap)
    if boundary_count == 0:
        return ()
    if actual_kind == "grid":
        return _grid_gaps(figure, group_id, style)
    if actual_kind not in {"row", "column", "stack"}:
        return (base,) * boundary_count

    node_ids = {node.id for node in figure.nodes}
    descendants: dict[str, frozenset[str]] = {}

    def descendant_nodes(entity_id: str) -> frozenset[str]:
        if entity_id in descendants:
            return descendants[entity_id]
        if entity_id in node_ids:
            result = frozenset((entity_id,))
        else:
            result = frozenset(
                node_id
                for child_id in groups[entity_id].children
                for node_id in descendant_nodes(child_id)
            )
        descendants[entity_id] = result
        return result

    child_for_node = {
        node_id: index
        for index, child_id in enumerate(group.children)
        for node_id in descendant_nodes(child_id)
    }

    def crossed_boundaries(source_id: str, target_id: str) -> range:
        source = child_for_node.get(source_id)
        target = child_for_node.get(target_id)
        if source is None or target is None or source == target:
            return range(0)
        return range(min(source, target), max(source, target))

    crossings = [0] * boundary_count
    for connection in layout_connections(figure):
        if connection.externally_routed:
            continue
        for boundary in crossed_boundaries(
            connection.source.node_id, connection.target.node_id
        ):
            crossings[boundary] += 1

    label_reserves = [0.0] * boundary_count
    if edge_labels:
        along_axis = (
            style.padding_x.points if actual_kind == "row" else style.padding_y.points
        )
        for edge in figure.edges:
            if edge.lane_hint is not None:
                continue
            metrics = edge_labels.get(edge.id)
            if metrics is None:
                continue
            for boundary in crossed_boundaries(edge.source.node_id, edge.target.node_id):
                if actual_kind == "row":
                    # Captions over parallel horizontal runs stack across the
                    # gap, so the gap need only be as wide as the widest one.
                    reserved = metrics.width + 2.0 * along_axis
                    label_reserves[boundary] = max(label_reserves[boundary], reserved)
                else:
                    # Captions beside parallel vertical runs have to take turns
                    # along the gap, so their heights add up.
                    if label_reserves[boundary] == 0.0:
                        label_reserves[boundary] = along_axis
                    label_reserves[boundary] += metrics.height + along_axis

    clearance = style.route_clearance.points
    target_clearance = style.arrival_clearance.points
    # Routing separates parallel tracks by ``port_spacing`` and lint reports an
    # error below it, so a crossed boundary has to reserve its lanes at that
    # pitch: reserving less hands the router a gutter it is not allowed to fill.
    lane_spacing = max(style.route_lane_spacing.points, style.port_spacing.points)
    return tuple(
        max(
            base,
            reserved,
            clearance + target_clearance + max(0, count - 1) * lane_spacing if count else 0.0,
        )
        for count, reserved in zip(crossings, label_reserves, strict=True)
    )


def _descendant_map(figure: FigureSpec, group: GroupSpec) -> dict[str, int]:
    """Every node under ``group``, keyed to the index of the child it sits in."""

    groups = {item.id: item for item in figure.groups}
    node_ids = {node.id for node in figure.nodes}

    def walk(entity_id: str) -> tuple[str, ...]:
        if entity_id in node_ids:
            return (entity_id,)
        if entity_id not in groups:
            return ()
        return tuple(node for child in groups[entity_id].children for node in walk(child))

    return {
        node_id: index
        for index, child_id in enumerate(group.children)
        for node_id in walk(child_id)
    }


def _grid_gaps(
    figure: FigureSpec,
    group_id: str,
    style: LayoutStyle,
) -> tuple[float, ...]:
    """Column gaps then row gaps of a grid, each widened for the routes crossing it.

    A grid spaces its tracks uniformly by default, but a connection between two
    cells needs the same room a row or a column gives it: one route clearance at
    the end it leaves and one arrival clearance at the end it points into, plus a
    lane per extra run through the same gutter. Without it a figure authored
    against one arrowhead stopped routing the moment a theme drew a longer one.
    The authored ``column_gap``/``row_gap`` stays the floor, so a grid that
    already left room keeps its exact geometry.

    Runs are counted per gutter *and per track*: two connections crossing the
    same column gap in different rows need one lane each, not two side by side.
    """

    group = next(item for item in figure.groups if item.id == group_id)
    layout = group.layout
    plan = grid_plan(layout, group.children)
    column_base = layout.resolved_column_gap(style.gap)
    row_base = layout.resolved_row_gap(style.gap)
    columns = [column_base] * max(0, plan.columns - 1)
    rows = [row_base] * max(0, plan.rows - 1)
    owner = _descendant_map(figure, group)
    clearance = style.route_clearance.points
    arrival = style.arrival_clearance.points
    lane = max(style.route_lane_spacing.points, style.port_spacing.points)
    column_runs: dict[tuple[int, int], int] = {}
    row_runs: dict[tuple[int, int], int] = {}
    for connection in layout_connections(figure):
        if connection.externally_routed:
            continue
        source = owner.get(connection.source.node_id)
        target = owner.get(connection.target.node_id)
        if source is None or target is None or source == target:
            continue
        (source_row, source_column), (target_row, target_column) = (
            plan.cells[source],
            plan.cells[target],
        )
        if source_row == target_row:
            low, high = sorted((source_column, target_column))
            for boundary in range(low, high):
                key = (source_row, boundary)
                column_runs[key] = column_runs.get(key, 0) + 1
        elif source_column == target_column:
            for boundary in range(min(source_row, target_row), max(source_row, target_row)):
                key = (source_column, boundary)
                row_runs[key] = row_runs.get(key, 0) + 1
    for (_, boundary), count in column_runs.items():
        columns[boundary] = max(columns[boundary], clearance + arrival + (count - 1) * lane)
    for (_, boundary), count in row_runs.items():
        rows[boundary] = max(rows[boundary], clearance + arrival + (count - 1) * lane)
    return tuple(columns) + tuple(rows)


def split_grid_gaps(
    gaps: tuple[float, ...] | None,
    columns: int,
    rows: int,
    column_gap: float,
    row_gap: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The column and row gutters of a grid from ``routing_gaps_for_group``'s answer."""

    column_count, row_count = max(0, columns - 1), max(0, rows - 1)
    if gaps is not None and len(gaps) == column_count + row_count:
        return tuple(gaps[:column_count]), tuple(gaps[column_count:])
    return (column_gap,) * column_count, (row_gap,) * row_count
