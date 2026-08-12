"""Initial component grammar and intrinsic sizing rules."""

from __future__ import annotations

from dataclasses import dataclass, replace

from flexo.geometry import Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec
from flexo.style import LayoutStyle


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    kind: str
    minimum_size: Size
    ports: tuple[PortSpec, ...]


_INPUT = PortSpec("input", Side.WEST, adaptive=True)
_OUTPUT = PortSpec("output", Side.EAST)
_STANDARD = (_INPUT, _OUTPUT)
_QKV = (
    PortSpec("q", Side.WEST, 0.24, adaptive=True),
    PortSpec("k", Side.WEST, 0.5, adaptive=True),
    PortSpec("v", Side.WEST, 0.76, adaptive=True),
    _OUTPUT,
)
_MULTI_OUTPUT = (
    _INPUT,
    PortSpec("output", Side.EAST, 0.3),
    PortSpec("branch", Side.EAST, 0.7),
    PortSpec("residual", Side.WEST, 0.8),
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
    else:
        natural = Size(
            max(definition.minimum_size.width, label.width + 2.0 * style.padding_x.points),
            max(definition.minimum_size.height, label.height + 2.0 * style.padding_y.points),
        )
    width = node.width.points if node.width is not None else natural.width
    height = node.height.points if node.height is not None else natural.height
    return Size(width, height)
