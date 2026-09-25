"""Bottom-up intrinsic measurement with no positional geometry."""

from __future__ import annotations

import itertools
from collections.abc import Callable

from flexo.components import intrinsic_node_size
from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Point, Rect, Size
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import FigureSpec, GroupSpec, NodeSpec, layout_connections
from flexo.layout.arrange import NON_ANCHOR_KINDS, arrange, arrangement_size, declared_size
from flexo.layout.gaps import routing_gaps_for_group
from flexo.layout.order import optimized_child_orders
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer, title_runs, title_typography
from flexo.themes import figure_style
from flexo.units import CellSpan
from flexo.validate import merge_matched_stacks, normalize_and_validate, resolve_alignment

__all__ = ["arrangement_size", "measure_figure"]


def measure_figure(
    figure: FigureSpec,
    *,
    style: LayoutStyle | None = None,
    measurer: TextMeasurer | None = None,
) -> MeasuredFigure:
    # Layout reads concrete alignments; the authored figure keeps its "auto".
    semantic = resolve_alignment(merge_matched_stacks(normalize_and_validate(figure)))
    layout_style = style or figure_style(semantic)
    text_measurer = measurer or TextMeasurer(layout_style.typography)
    title_measurer = (
        text_measurer
        if layout_style.typography.title_size == 1.0
        else TextMeasurer(title_typography(layout_style.typography))
    )
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
    outward = _outward_connections(semantic)
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
        # A title is drawn at the style's title weight, so it is measured there
        # too: a semibold "Sequence module" is wider than the same words at 400,
        # and the band this reserves is the band those glyphs land in.
        label = title_measurer.measure(
            title_runs(group.label, layout_style.typography),
            weight=layout_style.typography.title_weight,
        )
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
            max(body.width, label.width) + padding.horizontal,
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
                outward.get(group_id, {}),
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
    diagnostics: tuple[Diagnostic, ...] = tuple(
        Diagnostic(
            "layout.size.grown",
            "The label does not fit the authored size; the component grew to hold it.",
            Severity.WARNING,
            entity_id=node.spec.id,
            hint="Give it a larger width or height, or a shorter label.",
        )
        for node in measured_nodes
        if (
            node.spec.width is not None
            and node.intrinsic_size.width
            > layout_style.resolve_extent(node.spec.width).points + 1e-6
        )
        or (
            node.spec.height is not None
            and node.intrinsic_size.height
            > layout_style.resolve_extent(node.spec.height).points + 1e-6
        )
    )
    needed = declared_size(root.spec.layout, root.intrinsic_size).width
    if needed > canvas_width + 1e-6:
        # Wider than the page it was given: draw it anyway and say so, rather
        # than refusing to compile a figure that is merely too big.
        diagnostics += (
            Diagnostic(
                "layout.width.grown",
                f"The figure needs {needed:.1f} pt but its width is {canvas_width:.1f} pt; "
                "the canvas grew to fit.",
                Severity.WARNING,
                entity_id=semantic.id,
                hint="Give the figure a wider width, a smaller theme, or fewer columns.",
            ),
        )
        canvas_width = needed
    return MeasuredFigure(
        semantic,
        measured_nodes,
        tuple(measured_groups[group.id] for group in semantic.groups),
        Size(canvas_width, canvas_height),
        measured_edge_labels,
        diagnostics,
    )


def _measure_node(
    node: NodeSpec,
    measurer: TextMeasurer,
    style: LayoutStyle,
) -> MeasuredNode:
    label = measurer.measure(node.label, max_width=_label_width(node, style))
    size = intrinsic_node_size(node, label, style)
    # A component's ports sit on its side centres, so its own centre is where
    # both port lines cross -- including a vector's, whose bounds are exactly its
    # cell grid because the caption is a sibling node rather than padding.
    return MeasuredNode(node, label, size, Point(size.width / 2.0, size.height / 2.0))


WRAPPED_KINDS = frozenset(
    {"block", "mlp", "cnn", "add-norm", "prediction", "loss", "tensor", "terminal", "text"}
)
"""Kinds whose box is sized round their label, so a long label wraps instead."""


def _label_width(node: NodeSpec, style: LayoutStyle) -> float | None:
    """The width a component's label wraps at, or ``None`` for one that never wraps."""

    if node.kind not in WRAPPED_KINDS:
        return None
    if node.width is not None and not isinstance(node.width, CellSpan):
        return max(1.0, style.resolve_extent(node.width).points - 2.0 * style.padding_x.points)
    return style.label_measure * style.typography.size.points


def _group_anchor(
    group: GroupSpec,
    size: Size,
    title_height: float,
    style: LayoutStyle,
    node_kinds: dict[str, str],
    child_ids: tuple[str, ...],
    child_geometry: Callable[[tuple[str, ...]], tuple[tuple[Size, ...], tuple[Point, ...]]],
    gaps: tuple[float, ...],
    outward: dict[str, int] | None = None,
) -> Point:
    """A group's port line: its anchor child's, carried up into group coordinates.

    The group is laid out once at the size its parent will give it, which is the
    only way to learn where inside itself the anchor child lands -- a caption
    below a stack, a title band above a chain, and padding all move it. With no
    child to speak for it (an empty group, or one holding nothing but captions
    and spacers) the group falls back to its own centre.
    """

    primary = _anchor_child(group, node_kinds, outward or {})
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


def _anchor_child(
    group: GroupSpec,
    node_kinds: dict[str, str],
    outward: dict[str, int],
) -> str | None:
    """The child a group takes its port line from.

    The author's, when named. Otherwise the child that carries the group's
    connections to the rest of the figure -- the encoder at the bottom of a
    tower, not the input at its top -- because that is the line a sibling wired
    to this group wants to share. Ties, and groups wired to nothing outside,
    fall back to the first real child.
    """

    if group.anchor is not None:
        return group.anchor
    candidates = [
        child_id
        for child_id in group.children
        if node_kinds.get(child_id, "") not in NON_ANCHOR_KINDS
    ]
    if not candidates:
        return None
    best = max(outward.get(child_id, 0) for child_id in candidates)
    leaders = [child_id for child_id in candidates if outward.get(child_id, 0) == best]
    if best > 0 and len(leaders) > 1:
        # Several children carry the group's connections equally -- a column of
        # experts fed by one router: the group speaks from its middle.
        return None
    return leaders[0]


def _outward_connections(figure: FigureSpec) -> dict[str, dict[str, int]]:
    """For every group, how many connections each child carries out of the group."""

    groups = {group.id: group for group in figure.groups}
    parents = {child: group.id for group in figure.groups for child in group.children}

    def chain(entity_id: str) -> list[str]:
        result = [entity_id]
        while result[-1] in parents:
            result.append(parents[result[-1]])
        return result

    counts: dict[str, dict[str, int]] = {}
    for connection in layout_connections(figure):
        source = chain(connection.source.node_id)
        target = chain(connection.target.node_id)
        for path, other in ((source, set(target)), (target, set(source))):
            for child, group_id in itertools.pairwise(path):
                if group_id in other:
                    break
                if group_id in groups:
                    bucket = counts.setdefault(group_id, {})
                    bucket[child] = bucket.get(child, 0) + 1
    return counts


