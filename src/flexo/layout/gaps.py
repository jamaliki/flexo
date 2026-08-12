"""Edge-aware spacing for linear layout groups."""

from __future__ import annotations

from flexo.ir.semantic import FigureSpec, LayoutKind
from flexo.style import LayoutStyle


def routing_gaps_for_group(
    figure: FigureSpec,
    group_id: str,
    style: LayoutStyle,
    *,
    kind: LayoutKind | None = None,
) -> tuple[float, ...]:
    """Return a gap for every sibling boundary, enlarged for crossing routes."""

    groups = {group.id: group for group in figure.groups}
    group = groups[group_id]
    boundary_count = max(0, len(group.children) - 1)
    base = (group.layout.gap or style.gap).points
    if boundary_count == 0:
        return ()
    actual_kind = kind or group.layout.kind
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
    crossings = [0] * boundary_count
    for edge in figure.edges:
        if edge.lane_hint:
            continue
        source = child_for_node.get(edge.source.node_id)
        target = child_for_node.get(edge.target.node_id)
        if source is None or target is None or source == target:
            continue
        for boundary in range(min(source, target), max(source, target)):
            crossings[boundary] += 1

    clearance = style.route_clearance.points
    target_clearance = max(clearance, 2.0 * style.arrow_length.points)
    lane_spacing = style.route_lane_spacing.points
    return tuple(
        max(base, clearance + target_clearance + max(0, count - 1) * lane_spacing)
        if count
        else base
        for count in crossings
    )
