"""Fit measured components into explicit editorial containers."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Rect, Size
from flexo.ir.fitted import FittedFigure, FittedGroup, FittedNode, ResolvedPort
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import LayoutKind, LayoutSpec
from flexo.layout.gaps import routing_gaps_for_group
from flexo.layout.grid import grid_plan, grid_tracks
from flexo.layout.measure import arrangement_size
from flexo.layout.order import optimized_child_orders
from flexo.layout.ports import adapt_ports
from flexo.style import STYLES, LayoutStyle

_EPSILON = 1e-7


def fit_figure(
    measured: MeasuredFigure,
    *,
    style: LayoutStyle | None = None,
) -> FittedFigure:
    fitter = _Fitter(measured, style or STYLES[measured.semantic.style])
    return fitter.fit()


@dataclass(frozen=True, slots=True)
class _Child:
    id: str
    size: Size
    node: MeasuredNode | None = None
    group: MeasuredGroup | None = None


class _Fitter:
    def __init__(self, measured: MeasuredFigure, style: LayoutStyle) -> None:
        self.measured = measured
        self.style = style
        self.nodes = {node.spec.id: node for node in measured.nodes}
        self.groups = {group.spec.id: group for group in measured.groups}
        self.child_orders = optimized_child_orders(measured.semantic)
        self.edge_labels = measured.edge_label_index
        self.fitted_nodes: dict[str, FittedNode] = {}
        self.fitted_groups: dict[str, FittedGroup] = {}

    def fit(self) -> FittedFigure:
        canvas = self.measured.canvas_size
        self._fit_group(self.measured.semantic.root, Rect(0.0, 0.0, canvas.width, canvas.height))
        nodes = tuple(self.fitted_nodes[node.spec.id] for node in self.measured.nodes)
        nodes = adapt_ports(self.measured.semantic, nodes, self.style)
        return FittedFigure(
            self.measured,
            nodes,
            tuple(self.fitted_groups[group.spec.id] for group in self.measured.groups),
            canvas,
        )

    def _fit_group(self, group_id: str, bounds: Rect) -> None:
        measured_group = self.groups[group_id]
        layout = measured_group.spec.layout
        padding = layout.resolved_padding(self.style.group_padding)
        title_height = (
            measured_group.label.height + self.style.compact_gap.points
            if measured_group.spec.label
            else 0.0
        )
        content = Rect(
            bounds.x + padding.left,
            bounds.y + padding.top + title_height,
            max(0.0, bounds.width - padding.horizontal),
            max(0.0, bounds.height - padding.vertical - title_height),
        )
        child_ids = self.child_orders.get(group_id, measured_group.spec.children)
        children = tuple(self._child(child_id) for child_id in child_ids)
        kind = self._resolve_kind(measured_group, children, content.size)
        child_bounds = self._arrange(children, layout, kind, content, group_id)
        self.fitted_groups[group_id] = FittedGroup(measured_group, bounds, content)
        for child, child_bounds_value in zip(children, child_bounds, strict=True):
            if child.node is not None:
                ports = tuple(
                    ResolvedPort(
                        port.name,
                        port.side,
                        child_bounds_value.point_on(port.side, port.offset),
                    )
                    for port in child.node.spec.ports
                )
                self.fitted_nodes[child.id] = FittedNode(
                    child.node,
                    child_bounds_value,
                    ports,
                )
            else:
                self._fit_group(child.id, child_bounds_value)

    def _child(self, child_id: str) -> _Child:
        node = self.nodes.get(child_id)
        if node is not None:
            return _Child(child_id, node.intrinsic_size, node=node)
        group = self.groups[child_id]
        layout = group.spec.layout
        return _Child(
            child_id,
            Size(
                layout.width.points if layout.width is not None else group.intrinsic_size.width,
                layout.height.points if layout.height is not None else group.intrinsic_size.height,
            ),
            group=group,
        )

    def _resolve_kind(
        self,
        group: MeasuredGroup,
        children: tuple[_Child, ...],
        available: Size,
    ) -> LayoutKind:
        layout = group.spec.layout
        requested = arrangement_size(
            tuple(child.size for child in children),
            layout,
            self.style,
            gaps=routing_gaps_for_group(
                self.measured.semantic,
                group.spec.id,
                self.style,
                kind=layout.kind,
                edge_labels=self.edge_labels,
            ),
            child_ids=tuple(child.id for child in children),
        )
        fits = (
            requested.width <= available.width + _EPSILON
            and requested.height <= available.height + _EPSILON
        )
        if fits:
            return layout.kind
        if layout.reflow is not None:
            reflowed = arrangement_size(
                tuple(child.size for child in children),
                layout,
                self.style,
                kind=layout.reflow,
                gaps=routing_gaps_for_group(
                    self.measured.semantic,
                    group.spec.id,
                    self.style,
                    kind=layout.reflow,
                    edge_labels=self.edge_labels,
                ),
                child_ids=tuple(child.id for child in children),
            )
            if (
                reflowed.width <= available.width + _EPSILON
                and reflowed.height <= available.height + _EPSILON
            ):
                return layout.reflow
        contributors = sorted(
            children,
            key=lambda item: item.size.width * item.size.height,
            reverse=True,
        )
        summary = ", ".join(
            f"{child.id} ({child.size.width:.1f} x {child.size.height:.1f} pt)"
            for child in contributors[:3]
        )
        raise FlexoError(
            Diagnostic(
                "layout.overflow",
                f"Needs {requested.width:.1f} x {requested.height:.1f} pt but "
                f"only {available.width:.1f} x {available.height:.1f} pt is available.",
                entity_id=group.spec.id,
                hint=f"Largest contributors: {summary}.",
            )
        )

    def _arrange(
        self,
        children: tuple[_Child, ...],
        layout: LayoutSpec,
        kind: LayoutKind,
        content: Rect,
        group_id: str,
    ) -> tuple[Rect, ...]:
        if not children:
            return ()
        sizes = _equalized(tuple(child.size for child in children)) if layout.equal_size else tuple(
            child.size for child in children
        )
        axis_gaps = routing_gaps_for_group(
            self.measured.semantic,
            group_id,
            self.style,
            kind=kind,
            edge_labels=self.edge_labels,
        )
        if kind == "row":
            total = sum(size.width for size in sizes) + sum(axis_gaps)
            start, actual_gaps = _linear_justification(
                layout.justify, content.width, total, axis_gaps
            )
            x = content.x + start
            result = []
            for index, size in enumerate(sizes):
                height = content.height if layout.align == "stretch" else size.height
                y = _cross_position(layout.align, content.y, content.height, height)
                result.append(Rect(x, y, size.width, height))
                if index < len(actual_gaps):
                    x += size.width + actual_gaps[index]
            return tuple(result)
        if kind in {"column", "stack"}:
            total = sum(size.height for size in sizes) + sum(axis_gaps)
            start, actual_gaps = _linear_justification(
                layout.justify, content.height, total, axis_gaps
            )
            y = content.y + start
            result = []
            for index, size in enumerate(sizes):
                width = content.width if layout.align == "stretch" else size.width
                x = _cross_position(layout.align, content.x, content.width, width)
                result.append(Rect(x, y, width, size.height))
                if index < len(actual_gaps):
                    y += size.height + actual_gaps[index]
            return tuple(result)
        if kind == "overlay":
            return tuple(
                Rect(
                    _cross_position(layout.align, content.x, content.width, size.width),
                    _cross_position(layout.align, content.y, content.height, size.height),
                    size.width,
                    size.height,
                )
                for size in sizes
            )
        return self._arrange_grid(
            sizes,
            tuple(child.id for child in children),
            layout,
            content,
            group_id,
        )

    def _arrange_grid(
        self,
        sizes: tuple[Size, ...],
        child_ids: tuple[str, ...],
        layout: LayoutSpec,
        content: Rect,
        group_id: str,
    ) -> tuple[Rect, ...]:
        row_gap = layout.resolved_row_gap(self.style.gap)
        column_gap = layout.resolved_column_gap(self.style.gap)
        plan = grid_plan(layout, child_ids)
        column_widths, row_heights = grid_tracks(plan, sizes, layout)
        needed = Size(
            sum(column_widths) + column_gap * (plan.columns - 1),
            sum(row_heights) + row_gap * (plan.rows - 1),
        )
        if needed.width > content.width + _EPSILON or needed.height > content.height + _EPSILON:
            raise FlexoError(
                Diagnostic(
                    "layout.grid.overflow",
                    "Grid does not fit content bounds.",
                    entity_id=group_id,
                )
            )
        start_x, actual_x_gap = _justification(
            layout.justify, content.width, needed.width, column_gap, plan.columns
        )
        start_y = _cross_position(layout.align, content.y, content.height, needed.height)
        xs = [content.x + start_x]
        for width in column_widths[:-1]:
            xs.append(xs[-1] + width + actual_x_gap)
        ys = [start_y]
        for height in row_heights[:-1]:
            ys.append(ys[-1] + height + row_gap)
        return tuple(
            Rect(
                _cross_position(layout.align, xs[column], column_widths[column], size.width),
                _cross_position(layout.align, ys[row], row_heights[row], size.height),
                size.width,
                size.height,
            )
            for (row, column), size in zip(plan.cells, sizes, strict=True)
        )


def _equalized(values: tuple[Size, ...]) -> tuple[Size, ...]:
    width = max(size.width for size in values)
    height = max(size.height for size in values)
    return tuple(Size(width, height) for _ in values)


def _justification(
    justify: str,
    available: float,
    natural: float,
    gap: float,
    count: int,
) -> tuple[float, float]:
    extra = max(0.0, available - natural)
    if justify == "center":
        return extra / 2.0, gap
    if justify == "end":
        return extra, gap
    if justify == "space-between" and count > 1:
        return 0.0, gap + extra / (count - 1)
    return 0.0, gap


def _linear_justification(
    justify: str,
    available: float,
    natural: float,
    gaps: tuple[float, ...],
) -> tuple[float, tuple[float, ...]]:
    extra = max(0.0, available - natural)
    if justify == "center":
        return extra / 2.0, gaps
    if justify == "end":
        return extra, gaps
    if justify == "space-between" and gaps:
        addition = extra / len(gaps)
        return 0.0, tuple(gap + addition for gap in gaps)
    return 0.0, gaps


def _cross_position(align: str, start: float, available: float, size: float) -> float:
    if align == "center":
        return start + max(0.0, available - size) / 2.0
    if align == "end":
        return start + max(0.0, available - size)
    return start
