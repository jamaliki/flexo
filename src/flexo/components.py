"""Initial component grammar and intrinsic sizing rules."""

from __future__ import annotations

from dataclasses import dataclass, replace

from flexo.geometry import Rect, Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec
from flexo.style import LayoutStyle

TRANSPARENT_KINDS = frozenset({"label", "spacer", "junction"})
"""Node kinds that draw no body, so no connector has to keep clear of them.

Routing, port adaptation, and lint all read this one set: a kind that never
paints a fill cannot be crossed, so treating it as an obstacle in only some of
those passes forces authors to fake zero-size components.
"""


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    kind: str
    minimum_size: Size
    ports: tuple[PortSpec, ...]


_INPUT = PortSpec("input", Side.WEST, adaptive=True)
_OUTPUT = PortSpec("output", Side.EAST, adaptive=True)
_STANDARD = (_INPUT, _OUTPUT)
_QKV = (
    PortSpec("q", Side.WEST, 0.24, adaptive=True),
    PortSpec("k", Side.WEST, 0.5, adaptive=True),
    PortSpec("v", Side.WEST, 0.76, adaptive=True),
    _OUTPUT,
)
_MULTI_OUTPUT = (
    _INPUT,
    PortSpec("output", Side.EAST, 0.3, adaptive=True),
    PortSpec("branch", Side.EAST, 0.7, adaptive=True),
    PortSpec("residual", Side.WEST, 0.8),
)
_CONCAT = (
    PortSpec("input1", Side.WEST, 0.3, adaptive=True),
    PortSpec("input2", Side.WEST, 0.7, adaptive=True),
    _OUTPUT,
)
_VECTOR_PORTS = (
    PortSpec("input", Side.WEST),
    PortSpec("output", Side.EAST),
    PortSpec("north", Side.NORTH),
    PortSpec("south", Side.SOUTH),
)
"""One fixed centre port per side (R18/R19).

A vector is only a couple of cells wide, so an adaptive port would slide off the
middle cell for a gain of a pt or two. Keeping all four ports pinned to the side
centres makes the *counterpart* port adapt instead, which is what puts an arrow
on the middle cell.
"""

_DEFAULT_CELLS = 3
_DEFAULT_COLUMNS = 1


@dataclass(frozen=True, slots=True)
class VectorGrid:
    """The cell layout of one ``vector`` glyph, shared by measurement and paint.

    Measurement asks for the grid a node *wants* (square cells at the style
    token); rendering asks for the grid that fits the bounds the layout handed
    back, so an authored ``width``/``height`` stretches the cells instead of
    letting the ink drift out of the component.
    """

    cells: int
    columns: int
    cell_width: float
    cell_height: float
    row_gap: float
    column_gap: float

    @property
    def size(self) -> Size:
        return Size(
            self.columns * self.cell_width + (self.columns - 1) * self.column_gap,
            self.cells * self.cell_height + (self.cells - 1) * self.row_gap,
        )

    def cell_bounds(self, bounds: Rect, column: int, row: int) -> Rect:
        return Rect(
            bounds.x + column * (self.cell_width + self.column_gap),
            bounds.y + row * (self.cell_height + self.row_gap),
            self.cell_width,
            self.cell_height,
        )


def vector_grid(
    node: NodeSpec,
    style: LayoutStyle,
    *,
    bounds: Rect | None = None,
) -> VectorGrid:
    cells = max(1, int(node.property("cells", _DEFAULT_CELLS) or _DEFAULT_CELLS))
    columns = max(1, int(node.property("columns", _DEFAULT_COLUMNS) or _DEFAULT_COLUMNS))
    row_gap = style.vector_cell_gap.points
    column_gap = style.vector_column_gap.points
    side = style.vector_cell.points
    cell_width = side if bounds is None else (bounds.width - (columns - 1) * column_gap) / columns
    cell_height = side if bounds is None else (bounds.height - (cells - 1) * row_gap) / cells
    return VectorGrid(
        cells,
        columns,
        max(0.0, cell_width),
        max(0.0, cell_height),
        row_gap,
        column_gap,
    )


COMPONENTS: dict[str, ComponentDefinition] = {
    definition.kind: definition
    for definition in (
        ComponentDefinition("block", Size(44.0, 28.0), _STANDARD),
        ComponentDefinition("mlp", Size(48.0, 32.0), _STANDARD),
        ComponentDefinition("cnn", Size(48.0, 32.0), _STANDARD),
        ComponentDefinition(
            "add-norm",
            Size(50.0, 34.0),
            (_INPUT, PortSpec("residual", Side.SOUTH), _OUTPUT),
        ),
        ComponentDefinition("attention", Size(60.0, 58.0), _QKV),
        ComponentDefinition("concat", Size(32.0, 42.0), _CONCAT),
        ComponentDefinition("channels", Size(22.0, 34.0), _STANDARD),
        ComponentDefinition("feature-strip", Size(58.0, 25.0), _MULTI_OUTPUT),
        ComponentDefinition("tensor", Size(54.0, 26.0), _STANDARD),
        ComponentDefinition("matrix", Size(50.0, 48.0), _STANDARD),
        ComponentDefinition("sequence", Size(66.0, 26.0), _STANDARD),
        ComponentDefinition(
            "prediction",
            Size(58.0, 34.0),
            (_INPUT, PortSpec("residual", Side.SOUTH), _OUTPUT),
        ),
        ComponentDefinition("loss", Size(44.0, 32.0), (_INPUT,)),
        ComponentDefinition("junction", Size(8.0, 8.0), _MULTI_OUTPUT),
        ComponentDefinition("graph", Size(70.0, 62.0), _STANDARD),
        ComponentDefinition("inset", Size(82.0, 60.0), _STANDARD),
        # A vector's size is exactly its cell grid, so it comes from the style
        # tokens through vector_grid() rather than from a minimum here.
        ComponentDefinition("vector", Size(0.0, 0.0), _VECTOR_PORTS),
        ComponentDefinition("label", Size(0.0, 0.0), ()),
        ComponentDefinition("spacer", Size(0.0, 0.0), ()),
    )
}


def component_names() -> tuple[str, ...]:
    return tuple(COMPONENTS)


def normalize_node(node: NodeSpec) -> NodeSpec:
    if node.ports or node.kind not in COMPONENTS:
        return node
    return replace(node, ports=COMPONENTS[node.kind].ports)


def intrinsic_node_size(
    node: NodeSpec,
    label: TextMetrics,
    style: LayoutStyle,
) -> Size:
    definition = COMPONENTS[node.kind]
    if node.kind == "label":
        natural = Size(label.width, label.height)
    elif node.kind == "spacer":
        natural = Size(0.0, 0.0)
    elif node.kind == "vector":
        # Exactly the cell grid: a vector carries no inline label, so nothing
        # here may pad it. Its label is a sibling node (see GroupBuilder.vector).
        natural = vector_grid(node, style).size
    else:
        natural = Size(
            max(definition.minimum_size.width, label.width + 2.0 * style.padding_x.points),
            max(definition.minimum_size.height, label.height + 2.0 * style.padding_y.points),
        )
    width = node.width.points if node.width is not None else natural.width
    height = node.height.points if node.height is not None else natural.height
    return Size(width, height)
