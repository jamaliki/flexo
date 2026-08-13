"""Bottom-up intrinsic measurement with no positional geometry."""

from __future__ import annotations

import math

from flexo.components import intrinsic_node_size
from flexo.geometry import Size
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import FigureSpec, LayoutKind, LayoutSpec, NodeSpec
from flexo.layout.gaps import routing_gaps_for_group
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
        )
        padding = (group.layout.padding or layout_style.group_padding).points
        title_height = label.height + layout_style.compact_gap.points if group.label else 0.0
        measured = MeasuredGroup(
            group,
            label,
            Size(body.width + 2.0 * padding, body.height + 2.0 * padding + title_height),
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
) -> Size:
    if not child_sizes:
        return Size(0.0, 0.0)
    actual_kind = kind or layout.kind
    gap = (layout.gap or style.gap).points
    axis_gaps = gaps if gaps is not None else (gap,) * (len(child_sizes) - 1)
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
    columns = layout.columns or 1
    rows = math.ceil(len(values) / columns)
    column_widths = [0.0] * columns
    row_heights = [0.0] * rows
    for index, size in enumerate(values):
        column = index % columns
        row = index // columns
        column_widths[column] = max(column_widths[column], size.width)
        row_heights[row] = max(row_heights[row], size.height)
    return Size(
        sum(column_widths) + gap * (columns - 1),
        sum(row_heights) + gap * (rows - 1),
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
