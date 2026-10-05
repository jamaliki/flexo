"""Fit measured components into explicit editorial containers."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.geometry import Point, Rect, Size
from flexo.ir.fitted import FittedFigure, FittedGroup, FittedNode, ResolvedPort
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode
from flexo.ir.semantic import LayoutKind, LayoutSpec
from flexo.layout.arrange import arrange, arrangement_size, declared_size
from flexo.layout.gaps import routing_gaps_for_group
from flexo.layout.order import optimized_child_orders
from flexo.layout.ports import adapt_ports
from flexo.layout.sides import choose_port_sides
from flexo.layout.slide import aligned_with, slide_groups
from flexo.layout.widen import widen_boxes
from flexo.style import LayoutStyle
from flexo.themes import figure_style

_EPSILON = 1e-7


def fit_figure(
    measured: MeasuredFigure,
    *,
    style: LayoutStyle | None = None,
    slide: bool = True,
) -> FittedFigure:
    """Place every component; ``slide=False`` leaves groups where their parents
    put them (see ``flexo.layout.slide``)."""

    fitter = _Fitter(measured, style or figure_style(measured.semantic), slide=slide)
    return fitter.fit()


@dataclass(frozen=True, slots=True)
class _Child:
    id: str
    size: Size
    anchor: Point
    node: MeasuredNode | None = None


class _Fitter:
    def __init__(self, measured: MeasuredFigure, style: LayoutStyle, *, slide: bool) -> None:
        self.measured = measured
        self.slide = slide
        self.style = style
        self.nodes = {node.spec.id: node for node in measured.nodes}
        self.groups = {group.spec.id: group for group in measured.groups}
        self.child_orders = optimized_child_orders(measured.semantic)
        self.edge_labels = measured.edge_label_index
        self.fitted_nodes: dict[str, FittedNode] = {}
        self.fitted_groups: dict[str, FittedGroup] = {}
        self.kinds: dict[str, LayoutKind] = {}

    def fit(self) -> FittedFigure:
        canvas = self.measured.canvas_size
        self._fit_group(self.measured.semantic.root, Rect(0.0, 0.0, canvas.width, canvas.height))
        nodes = tuple(self.fitted_nodes[node.spec.id] for node in self.measured.nodes)
        # Sides first, offsets second: adaptation slides a port along the side it
        # is on, so it has to be told which side that is before it starts.
        groups = tuple(self.fitted_groups[group.spec.id] for group in self.measured.groups)
        # A part lined up with another its person chose: centred on it (again once the
        # groups have slid, should the other have moved with them).
        semantic = self.measured.semantic
        nodes = aligned_with(semantic, nodes, groups, self.kinds)
        nodes, diagnostics = choose_port_sides(semantic, nodes, groups)
        # A centred row can leave an input outside the reach of the port it feeds;
        # sliding the row is the one fix that moving ports cannot make.
        if self.slide:
            nodes, groups = slide_groups(semantic, nodes, groups, self.kinds, self.style)
            nodes = aligned_with(semantic, nodes, groups, self.kinds)
        # Then a box several straight arrows share a side of grows until they meet
        # its middle, so the boxes they come from keep their centres.
        nodes = widen_boxes(self.measured.semantic, nodes, groups, self.kinds, self.style)
        nodes = adapt_ports(self.measured.semantic, nodes, self.style)
        return FittedFigure(self.measured, nodes, groups, canvas, diagnostics)

    def _fit_group(self, group_id: str, bounds: Rect) -> None:
        measured_group = self.groups[group_id]
        layout = measured_group.spec.layout
        padding = layout.resolved_padding(self.style.group_padding)
        title_height = (
            measured_group.label.height + self.style.compact_gap.points
            if measured_group.spec.label
            else 0.0
        )
        # A title under the contents (a plate's count) takes its band at the bottom.
        above = 0.0 if measured_group.spec.title_below else title_height
        content = Rect(
            bounds.x + padding.left,
            bounds.y + padding.top + above,
            max(0.0, bounds.width - padding.horizontal),
            max(0.0, bounds.height - padding.vertical - title_height),
        )
        child_ids = self.child_orders.get(group_id, measured_group.spec.children)
        children = tuple(self._child(child_id) for child_id in child_ids)
        kind = self._resolve_kind(measured_group, children, content.size)
        self.kinds[group_id] = kind
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
            return _Child(child_id, node.intrinsic_size, node.anchor, node=node)
        group = self.groups[child_id]
        layout = group.spec.layout
        return _Child(
            child_id,
            declared_size(layout, group.intrinsic_size),
            group.anchor,
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
            anchors=tuple(child.anchor for child in children),
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
                anchors=tuple(child.anchor for child in children),
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
        return arrange(
            tuple(child.size for child in children),
            tuple(child.id for child in children),
            layout,
            kind,
            content,
            gaps=routing_gaps_for_group(
                self.measured.semantic,
                group_id,
                self.style,
                kind=kind,
                edge_labels=self.edge_labels,
            ),
            row_gap=layout.resolved_row_gap(self.style.gap),
            column_gap=layout.resolved_column_gap(self.style.gap),
            anchors=tuple(child.anchor for child in children),
            group_id=group_id,
        )
