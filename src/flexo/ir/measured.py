"""Measured IR: semantic values plus text metrics and intrinsic sizes."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic
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
    cap_height: float = 0.0
    """Height of a capital above the baseline: what the eye centres a word on."""
    rise: float = 0.0
    fall: float = 0.0
    """How much a formula taller than the words opened each line, above and below its
    words' own room (``line_height`` and ``baseline`` include them)."""


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
    fit: Size | None = None
    """The size it would be round its words, without a width or height of its own (unset,
    ``intrinsic_size``) -- a decision's, the diamond that hugs them: what an editor's
    handles snap to."""
    room: float | None = None
    """How wide a line of its words may run before they wrap, in points (``None``: they
    never wrap): what an editor's box for typing them wraps them at, as they will be drawn."""
    drawn: tuple[float, float] | None = None
    """The top and bottom of what it draws, its name aside, down from its own top: a named
    structure's molecule, a named picture's artwork, a mechanism's structures over their
    names (``flexo.title_sides``). A line meets it from either side within it, at its middle
    when alone there; a row that centres what it holds lines it up by that middle, and so
    does one lined up by its port line (``anchor``). ``None``: its whole box."""

    @property
    def middle(self) -> float | None:
        """The middle of what it draws (``drawn``), down from its top; ``None``: its box's."""

        return None if self.drawn is None else (self.drawn[0] + self.drawn[1]) / 2.0


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
    middle: float | None = None
    """The line its children's middles stand on, down from its own top, for a parent that
    centres what it holds: a row of named molecules lined up by their molecules (see
    ``MeasuredNode.drawn``), which a ``+`` and an arrow beside the row meet level. ``None``:
    its box's middle -- as it is for any group nothing drawn under a name is lined up in."""


@dataclass(frozen=True, slots=True)
class MeasuredFigure:
    semantic: FigureSpec
    nodes: tuple[MeasuredNode, ...]
    groups: tuple[MeasuredGroup, ...]
    canvas_size: Size
    edge_labels: tuple[TextMetrics, ...] = ()
    """Label metrics, positionally aligned with ``semantic.edges``."""
    diagnostics: tuple[Diagnostic, ...] = ()
    """What measurement had to overrule -- a canvas too narrow for its content."""
    net_labels: tuple[TextMetrics, ...] = ()
    """Caption metrics, positionally aligned with ``semantic.nets``."""

    def node(self, node_id: str) -> MeasuredNode:
        return next(node for node in self.nodes if node.spec.id == node_id)

    def group(self, group_id: str) -> MeasuredGroup:
        return next(group for group in self.groups if group.spec.id == group_id)

    def edge_label(self, edge_id: str) -> TextMetrics | None:
        return self.edge_label_index.get(edge_id)

    @property
    def edge_label_index(self) -> dict[str, TextMetrics]:
        """Non-empty caption metrics keyed by edge ID, and by net ID (the two never share one)."""

        return {
            connection.id: metrics
            for connection, metrics in (
                *zip(self.semantic.edges, self.edge_labels, strict=False),
                *zip(self.semantic.nets, self.net_labels, strict=False),
            )
            if metrics.width > 0.0 or metrics.height > 0.0
        }
