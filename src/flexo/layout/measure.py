"""Bottom-up intrinsic measurement with no positional geometry."""

from __future__ import annotations

from flexo.components import intrinsic_node_size
from flexo.geometry import Size
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import FigureSpec, LayoutKind, LayoutSpec, NodeSpec
from flexo.layout.gaps import routing_gaps_for_group
from flexo.layout.grid import grid_plan, grid_tracks
from flexo.style import STYLES, LayoutStyle
from flexo.text import TextMeasurer
from flexo.validate import normalize_and_validate


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
    node_sizes = {node.spec.id: node.intrinsic_size for node in measured_nodes}
    groups_by_id = {group.id: group for group in semantic.groups}
    measured_groups: dict[str, MeasuredGroup] = {}

    def measure_group(group_id: str) -> MeasuredGroup:
        if group_id in measured_groups:
            return measured_groups[group_id]
        group = groups_by_id[group_id]
        child_sizes = []
        for child_id in group.children:
            if child_id in node_sizes:
                child_sizes.append(node_sizes[child_id])
            else:
                child = measure_group(child_id)
                child_sizes.append(_declared_size(child.spec.layout, child.intrinsic_size))
        label = text_measurer.measure(group.label)
        body = arrangement_size(
            tuple(child_sizes),
            group.layout,
            layout_style,
            gaps=routing_gaps_for_group(
                semantic,
                group_id,
                layout_style,
                edge_labels=edge_labels,
            ),
            child_ids=group.children,
        )
        padding = group.layout.resolved_padding(layout_style.group_padding)
        title_height = label.height + layout_style.compact_gap.points if group.label else 0.0
        measured = MeasuredGroup(
            group,
            label,
            Size(
                body.width + padding.horizontal,
                body.height + padding.vertical + title_height,
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
        else _declared_size(root.spec.layout, root.intrinsic_size).height
    )
    return MeasuredFigure(
        semantic,
        measured_nodes,
        tuple(measured_groups[group.id] for group in semantic.groups),
        Size(canvas_width, canvas_height),
        measured_edge_labels,
    )


def arrangement_size(
    child_sizes: tuple[Size, ...],
    layout: LayoutSpec,
    style: LayoutStyle,
    *,
    kind: LayoutKind | None = None,
    gaps: tuple[float, ...] | None = None,
    child_ids: tuple[str, ...] | None = None,
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
    if actual_kind == "row":
        return Size(
            sum(size.width for size in values) + sum(axis_gaps),
            max(size.height for size in values),
        )
    if actual_kind in {"column", "stack"}:
        return Size(
            max(size.width for size in values),
            sum(size.height for size in values) + sum(axis_gaps),
        )
    if actual_kind == "overlay":
        return Size(
            max(size.width for size in values),
            max(size.height for size in values),
        )
    # Without names no child can be addressed, so every one of them flows.
    plan = grid_plan(layout, child_ids if child_ids is not None else ("",) * len(values))
    column_widths, row_heights = grid_tracks(plan, values, layout)
    return Size(
        sum(column_widths) + layout.resolved_column_gap(style.gap) * (plan.columns - 1),
        sum(row_heights) + layout.resolved_row_gap(style.gap) * (plan.rows - 1),
    )


def _measure_node(
    node: NodeSpec,
    measurer: TextMeasurer,
    style: LayoutStyle,
) -> MeasuredNode:
    label = measurer.measure(node.label)
    return MeasuredNode(node, label, intrinsic_node_size(node, label, style))


def _declared_size(layout: LayoutSpec, intrinsic: Size) -> Size:
    return Size(
        layout.width.points if layout.width is not None else intrinsic.width,
        layout.height.points if layout.height is not None else intrinsic.height,
    )


def _equalized(values: tuple[Size, ...]) -> tuple[Size, ...]:
    width = max(size.width for size in values)
    height = max(size.height for size in values)
    return tuple(Size(width, height) for _ in values)
