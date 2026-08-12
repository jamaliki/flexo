"""Crossing-minimizing order for small adjacent layout columns."""

from __future__ import annotations

from itertools import combinations, pairwise, permutations

from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutConnection, layout_connections

_MAXIMUM_EXHAUSTIVE_CHILDREN = 5


def optimized_child_orders(figure: FigureSpec) -> dict[str, tuple[str, ...]]:
    """Find stable child orders that strictly reduce crossings between columns."""

    groups = {group.id: group for group in figure.groups}
    descendants = _descendant_index(figure, groups)
    result: dict[str, tuple[str, ...]] = {}
    for parent in figure.groups:
        if parent.layout.kind != "row":
            continue
        for left_id, right_id in pairwise(parent.children):
            left = groups.get(left_id)
            right = groups.get(right_id)
            if not _optimizable_pair(left, right, result):
                continue
            assert left is not None and right is not None
            connecting = _connecting_edges(layout_connections(figure), left, right, descendants)
            best_left, best_right = _best_pair_order(left, right, connecting, descendants)
            original_crossings = _crossing_count(
                left.children,
                right.children,
                connecting,
                descendants,
            )
            best_crossings = _crossing_count(
                best_left,
                best_right,
                connecting,
                descendants,
            )
            if best_crossings < original_crossings:
                result[left.id] = best_left
                result[right.id] = best_right
    return result


def _optimizable_pair(
    left: GroupSpec | None,
    right: GroupSpec | None,
    existing: dict[str, tuple[str, ...]],
) -> bool:
    return bool(
        left
        and right
        and left.id not in existing
        and right.id not in existing
        and left.role == right.role == "layout"
        and left.layout.kind in {"column", "stack"}
        and right.layout.kind in {"column", "stack"}
        and 1 < len(left.children) <= _MAXIMUM_EXHAUSTIVE_CHILDREN
        and 1 < len(right.children) <= _MAXIMUM_EXHAUSTIVE_CHILDREN
    )


def _best_pair_order(
    left: GroupSpec,
    right: GroupSpec,
    edges: tuple[LayoutConnection, ...],
    descendants: dict[str, frozenset[str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    best = (left.children, right.children)
    best_score = (_crossing_count(*best, edges, descendants), 0)
    for left_order in permutations(left.children):
        for right_order in permutations(right.children):
            score = (
                _crossing_count(left_order, right_order, edges, descendants),
                _inversions(left_order, left.children) + _inversions(right_order, right.children),
            )
            if score < best_score:
                best = (left_order, right_order)
                best_score = score
    return best


def _connecting_edges(
    edges: tuple[LayoutConnection, ...],
    left: GroupSpec,
    right: GroupSpec,
    descendants: dict[str, frozenset[str]],
) -> tuple[LayoutConnection, ...]:
    left_nodes = frozenset().union(*(descendants[child] for child in left.children))
    right_nodes = frozenset().union(*(descendants[child] for child in right.children))
    return tuple(
        edge
        for edge in edges
        if not edge.externally_routed
        and (
            (edge.source.node_id in left_nodes and edge.target.node_id in right_nodes)
            or (edge.target.node_id in left_nodes and edge.source.node_id in right_nodes)
        )
    )


def _crossing_count(
    left_order: tuple[str, ...],
    right_order: tuple[str, ...],
    edges: tuple[LayoutConnection, ...],
    descendants: dict[str, frozenset[str]],
) -> int:
    left_positions = _node_positions(left_order, descendants)
    right_positions = _node_positions(right_order, descendants)
    endpoint_positions = []
    for edge in edges:
        if edge.source.node_id in left_positions:
            endpoint_positions.append(
                (left_positions[edge.source.node_id], right_positions[edge.target.node_id])
            )
        else:
            endpoint_positions.append(
                (left_positions[edge.target.node_id], right_positions[edge.source.node_id])
            )
    return sum(
        (left_a - left_b) * (right_a - right_b) < 0
        for (left_a, right_a), (left_b, right_b) in combinations(endpoint_positions, 2)
        if left_a != left_b and right_a != right_b
    )


def _node_positions(
    order: tuple[str, ...],
    descendants: dict[str, frozenset[str]],
) -> dict[str, int]:
    return {
        node_id: index
        for index, child_id in enumerate(order)
        for node_id in descendants[child_id]
    }


def _descendant_index(
    figure: FigureSpec,
    groups: dict[str, GroupSpec],
) -> dict[str, frozenset[str]]:
    result = {node.id: frozenset((node.id,)) for node in figure.nodes}

    def descendants(entity_id: str) -> frozenset[str]:
        if entity_id not in result:
            result[entity_id] = frozenset(
                node_id
                for child_id in groups[entity_id].children
                for node_id in descendants(child_id)
            )
        return result[entity_id]

    for group in figure.groups:
        descendants(group.id)
    return result


def _inversions(order: tuple[str, ...], original: tuple[str, ...]) -> int:
    positions = {value: index for index, value in enumerate(original)}
    indices = tuple(positions[value] for value in order)
    return sum(first > second for first, second in combinations(indices, 2))
