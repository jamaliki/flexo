"""Measured IR: semantic values plus text metrics and intrinsic sizes."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.geometry import Point, Size
from flexo.ir.semantic import FigureSpec, GroupSpec, NodeSpec, TextRun

_ORIGIN = Point(0.0, 0.0)


@dataclass(frozen=True, slots=True)
class MeasuredLine:
    runs: tuple[TextRun, ...]
    width: float


@dataclass(frozen=True, slots=True)
class TextMetrics:
    width: float
    height: float
    ascent: float
    descent: float
    baseline: float
    line_height: float
    lines: tuple[MeasuredLine, ...]


@dataclass(frozen=True, slots=True)
class MeasuredNode:
    spec: NodeSpec
    label: TextMetrics
    intrinsic_size: Size
    anchor: Point = _ORIGIN
    """Where this component's port lines cross, from its own top-left.

    ``anchor.y`` is the y of its west and east ports, ``anchor.x`` the x of its
    north and south ports -- the two lines an ``align="ports"`` parent lines its
    children up on. A component answers with its own centre, which is where the
    grammar puts a side-centre port.
    """


@dataclass(frozen=True, slots=True)
class MeasuredGroup:
    spec: GroupSpec
    label: TextMetrics
    intrinsic_size: Size
    anchor: Point = _ORIGIN
    """Where this group's port lines cross, from its own top-left.

    A composite answers with its anchor child's line (see ``GroupSpec.anchor``),
    so a captioned vector reports the middle of the cell stack rather than the
    middle of cells-plus-caption. Measured at the size the parent will hand the
    group, which is why it is computed here beside ``intrinsic_size``.
    """


@dataclass(frozen=True, slots=True)
class MeasuredFigure:
    semantic: FigureSpec
    nodes: tuple[MeasuredNode, ...]
    groups: tuple[MeasuredGroup, ...]
    canvas_size: Size
    edge_labels: tuple[TextMetrics, ...] = ()
    """Label metrics, positionally aligned with ``semantic.edges``."""

    def node(self, node_id: str) -> MeasuredNode:
        return next(node for node in self.nodes if node.spec.id == node_id)

    def group(self, group_id: str) -> MeasuredGroup:
        return next(group for group in self.groups if group.spec.id == group_id)

    def edge_label(self, edge_id: str) -> TextMetrics | None:
        return self.edge_label_index.get(edge_id)

    @property
    def edge_label_index(self) -> dict[str, TextMetrics]:
        """Non-empty edge label metrics keyed by edge ID."""

        return {
            edge.id: metrics
            for edge, metrics in zip(self.semantic.edges, self.edge_labels, strict=False)
            if metrics.width > 0.0 or metrics.height > 0.0
        }
