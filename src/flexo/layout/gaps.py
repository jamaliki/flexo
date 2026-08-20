"""Edge-aware spacing for linear layout groups."""

from __future__ import annotations

from collections.abc import Mapping

from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import FigureSpec, LayoutKind, layout_connections
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
            extent = metrics.width if actual_kind == "row" else metrics.height
            reserved = extent + 2.0 * along_axis
            for boundary in crossed_boundaries(edge.source.node_id, edge.target.node_id):
                label_reserves[boundary] = max(label_reserves[boundary], reserved)

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
