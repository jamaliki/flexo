"""Bottom-up intrinsic measurement with no positional geometry."""

from __future__ import annotations

from collections.abc import Callable

from flexo.components import intrinsic_node_size
from flexo.geometry import Point, Rect, Size
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import FigureSpec, GroupSpec, NodeSpec
from flexo.layout.arrange import NON_ANCHOR_KINDS, arrange, arrangement_size, declared_size
from flexo.layout.gaps import routing_gaps_for_group
from flexo.layout.order import optimized_child_orders
from flexo.style import STYLES, LayoutStyle
from flexo.text import TextMeasurer
from flexo.validate import normalize_and_validate

__all__ = ["arrangement_size", "measure_figure"]


def measure_figure(
    figure: FigureSpec,
    *,
    style: LayoutStyle | None = None,
    measurer: TextMeasurer | None = None,
) -> MeasuredFigure:
    semantic = normalize_and_validate(figure)
    layout_style = style or STYLES[semantic.style]
    text_measurer = measurer or TextMeasurer(layout_style.typography)
    measured_nodes = tuple(
        _measure_node(node, text_measurer, layout_style) for node in semantic.nodes
    )
    measured_edge_labels = tuple(text_measurer.measure(edge.label) for edge in semantic.edges)
    edge_labels = {
        edge.id: metrics
        for edge, metrics in zip(semantic.edges, measured_edge_labels, strict=True)
        if metrics.width > 0.0 or metrics.height > 0.0
    }
    node_kinds = {node.spec.id: node.spec.kind for node in measured_nodes}
    node_sizes = {node.spec.id: node.intrinsic_size for node in measured_nodes}
    node_anchors = {node.spec.id: node.anchor for node in measured_nodes}
    groups_by_id = {group.id: group for group in semantic.groups}
    child_orders = optimized_child_orders(semantic)
    measured_groups: dict[str, MeasuredGroup] = {}

    def child_geometry(child_ids: tuple[str, ...]) -> tuple[tuple[Size, ...], tuple[Point, ...]]:
        sizes = []
        anchors = []
        for child_id in child_ids:
            if child_id in node_sizes:
                sizes.append(node_sizes[child_id])
                anchors.append(node_anchors[child_id])
            else:
                child = measure_group(child_id)
                sizes.append(declared_size(child.spec.layout, child.intrinsic_size))
                anchors.append(child.anchor)
        return tuple(sizes), tuple(anchors)

    def measure_group(group_id: str) -> MeasuredGroup:
        if group_id in measured_groups:
            return measured_groups[group_id]
        group = groups_by_id[group_id]
        child_sizes, child_anchors = child_geometry(group.children)
        label = text_measurer.measure(group.label)
        gaps = routing_gaps_for_group(
            semantic,
            group_id,
            layout_style,
            edge_labels=edge_labels,
        )
        body = arrangement_size(
            child_sizes,
            group.layout,
            layout_style,
            gaps=gaps,
            child_ids=group.children,
            anchors=child_anchors,
        )
        padding = group.layout.resolved_padding(layout_style.group_padding)
        title_height = label.height + layout_style.compact_gap.points if group.label else 0.0
        intrinsic = Size(
            body.width + padding.horizontal,
            body.height + padding.vertical + title_height,
        )
        measured = MeasuredGroup(
            group,
            label,
            intrinsic,
            _group_anchor(
                group,
                declared_size(group.layout, intrinsic),
                title_height,
                layout_style,
                node_kinds,
                child_orders.get(group_id, group.children),
                child_geometry,
                gaps,
            ),
        )
        measured_groups[group_id] = measured
        return measured

    root = measure_group(semantic.root)
    for group in semantic.groups:
        measure_group(group.id)
    canvas_width = layout_style.resolve_width(semantic.width).points
    canvas_height = (
        semantic.height.points
        if semantic.height is not None
        else declared_size(root.spec.layout, root.intrinsic_size).height
    )
    return MeasuredFigure(
        semantic,
        measured_nodes,
        tuple(measured_groups[group.id] for group in semantic.groups),
        Size(canvas_width, canvas_height),
        measured_edge_labels,
    )


def _measure_node(
    node: NodeSpec,
    measurer: TextMeasurer,
    style: LayoutStyle,
) -> MeasuredNode:
    label = measurer.measure(node.label)
    size = intrinsic_node_size(node, label, style)
    # A component's ports sit on its side centres, so its own centre is where
    # both port lines cross -- including a vector's, whose bounds are exactly its
    # cell grid because the caption is a sibling node rather than padding.
    return MeasuredNode(node, label, size, Point(size.width / 2.0, size.height / 2.0))


def _group_anchor(
    group: GroupSpec,
    size: Size,
    title_height: float,
    style: LayoutStyle,
    node_kinds: dict[str, str],
    child_ids: tuple[str, ...],
    child_geometry: Callable[[tuple[str, ...]], tuple[tuple[Size, ...], tuple[Point, ...]]],
    gaps: tuple[float, ...],
) -> Point:
    """A group's port line: its anchor child's, carried up into group coordinates.

    The group is laid out once at the size its parent will give it, which is the
    only way to learn where inside itself the anchor child lands -- a caption
    below a stack, a title band above a chain, and padding all move it. With no
    child to speak for it (an empty group, or one holding nothing but captions
    and spacers) the group falls back to its own centre.
    """

    primary = _anchor_child(group, node_kinds)
    centre = Point(size.width / 2.0, size.height / 2.0)
    if primary is None or primary not in child_ids:
        return centre
    layout = group.layout
    padding = layout.resolved_padding(style.group_padding)
    content = Rect(
        padding.left,
        padding.top + title_height,
        max(0.0, size.width - padding.horizontal),
        max(0.0, size.height - padding.vertical - title_height),
    )
    sizes, anchors = child_geometry(child_ids)
    bounds = arrange(
        sizes,
        child_ids,
        layout,
        layout.kind,
        content,
        gaps=gaps,
        row_gap=layout.resolved_row_gap(style.gap),
        column_gap=layout.resolved_column_gap(style.gap),
        anchors=anchors,
        group_id=group.id,
    )
    index = child_ids.index(primary)
    return Point(
        bounds[index].x + anchors[index].x,
        bounds[index].y + anchors[index].y,
    )


def _anchor_child(group: GroupSpec, node_kinds: dict[str, str]) -> str | None:
    """The child a group takes its port line from: the author's, or the first real one."""

    if group.anchor is not None:
        return group.anchor
    return next(
        (
            child_id
            for child_id in group.children
            if node_kinds.get(child_id, "") not in NON_ANCHOR_KINDS
        ),
        None,
    )


