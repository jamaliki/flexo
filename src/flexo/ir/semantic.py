"""Semantic input IR: meaning and relationships without computed geometry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from flexo.geometry import Side
from flexo.units import Length

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
type Scalar = str | int | float | bool
type LayoutKind = Literal["row", "column", "grid", "overlay", "stack"]
type CollisionPolicy = Literal["disjoint", "overlay", "ignore"]
type NetKind = Literal["fan-out", "merge"]
_ZERO_LENGTH = Length(0.0)


def _validate_id(value: str, label: str = "ID") -> None:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(
            f'{label} "{value}" must start with a letter and contain only letters, digits, '
            "., _, or -"
        )


@dataclass(frozen=True, slots=True)
class TextRun:
    text: str
    weight: int = 400
    italic: bool = False
    baseline_shift: Literal["normal", "super", "sub"] = "normal"


@dataclass(frozen=True, slots=True)
class PortSpec:
    name: str
    side: Side
    offset: float = 0.5
    adaptive: bool = False

    def __post_init__(self) -> None:
        _validate_id(self.name, "Port name")
        if not 0.0 <= self.offset <= 1.0:
            raise ValueError("port offset must lie between 0 and 1")


@dataclass(frozen=True, slots=True)
class PortRef:
    node_id: str
    port_name: str

    def __post_init__(self) -> None:
        _validate_id(self.node_id, "Node ID")
        _validate_id(self.port_name, "Port name")

    @classmethod
    def parse(cls, value: str) -> PortRef:
        try:
            node_id, port_name = value.rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(f'port reference "{value}" must have the form node.port') from exc
        return cls(node_id, port_name)

    def __str__(self) -> str:
        return f"{self.node_id}.{self.port_name}"


@dataclass(frozen=True, slots=True)
class Waypoint:
    reference: str | None = None
    side: Side | None = None
    offset: float = 0.5
    dx: Length = _ZERO_LENGTH
    dy: Length = _ZERO_LENGTH
    x: Length | None = None
    y: Length | None = None

    def __post_init__(self) -> None:
        if self.reference is None and (self.x is None or self.y is None):
            raise ValueError("a waypoint needs a semantic reference or absolute x and y")
        if self.reference is not None:
            _validate_id(self.reference, "Waypoint reference")
        if not 0.0 <= self.offset <= 1.0:
            raise ValueError("waypoint offset must lie between 0 and 1")


@dataclass(frozen=True, slots=True)
class LayoutSpec:
    kind: LayoutKind = "row"
    gap: Length | None = None
    padding: Length | None = None
    align: Literal["start", "center", "end", "stretch"] = "center"
    justify: Literal["start", "center", "end", "space-between"] = "start"
    columns: int | None = None
    width: Length | None = None
    height: Length | None = None
    reflow: LayoutKind | None = None
    equal_size: bool = False

    def __post_init__(self) -> None:
        if self.kind == "grid" and (self.columns is None or self.columns < 1):
            raise ValueError("grid layout requires a positive column count")
        if self.columns is not None and self.columns < 1:
            raise ValueError("columns must be positive")


@dataclass(frozen=True, slots=True)
class NodeSpec:
    id: str
    kind: str
    label: tuple[TextRun, ...] = ()
    role: str = "block"
    ports: tuple[PortSpec, ...] = ()
    width: Length | None = None
    height: Length | None = None
    properties: tuple[tuple[str, Scalar], ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.id, "Node ID")
        _validate_id(self.kind, "Node kind")
        names = [port.name for port in self.ports]
        if len(names) != len(set(names)):
            raise ValueError(f'node "{self.id}" contains duplicate port names')

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.label)

    def property(self, name: str, default: Scalar | None = None) -> Scalar | None:
        return dict(self.properties).get(name, default)


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    id: str
    source: PortRef
    target: PortRef
    role: str = "flow"
    label: tuple[TextRun, ...] = ()
    lane_hint: str | None = None
    waypoints: tuple[Waypoint, ...] = ()
    depart: Side | None = None
    arrive: Side | None = None

    def __post_init__(self) -> None:
        _validate_id(self.id, "Edge ID")
        if self.lane_hint is not None:
            _validate_id(self.lane_hint, "Lane hint")


@dataclass(frozen=True, slots=True)
class NetSpec:
    """A shared-value fan-out or authored many-to-one combination."""

    id: str
    kind: NetKind
    sources: tuple[PortRef, ...]
    targets: tuple[PortRef, ...]
    role: str = "flow"
    label: tuple[TextRun, ...] = ()
    rail_hint: Side | None = None

    def __post_init__(self) -> None:
        _validate_id(self.id, "Net ID")
        if self.kind == "fan-out" and (len(self.sources) != 1 or len(self.targets) < 2):
            raise ValueError("fan-out nets require one source and at least two targets")
        if self.kind == "merge" and (len(self.sources) < 2 or len(self.targets) != 1):
            raise ValueError("merge nets require at least two sources and one target")
        if len(self.sources) != len(set(self.sources)):
            raise ValueError(f'net "{self.id}" contains duplicate sources')
        if len(self.targets) != len(set(self.targets)):
            raise ValueError(f'net "{self.id}" contains duplicate targets')


@dataclass(frozen=True, slots=True)
class LayoutConnection:
    """One endpoint pair used only for layout spacing and port adaptation."""

    source: PortRef
    target: PortRef
    externally_routed: bool = False
    from_net: bool = False
    """True when the pair is one leg of a net rather than a point-to-point edge.

    A net leg is served by a rail junction, not by a direct run between the two
    ports, so port adaptation may only align it along the rail axis.
    """


@dataclass(frozen=True, slots=True)
class GroupSpec:
    id: str
    children: tuple[str, ...]
    layout: LayoutSpec = LayoutSpec()
    collision_policy: CollisionPolicy = "disjoint"
    label: tuple[TextRun, ...] = ()
    role: str = "container"

    def __post_init__(self) -> None:
        _validate_id(self.id, "Group ID")
        if len(self.children) != len(set(self.children)):
            raise ValueError(f'group "{self.id}" contains duplicate children')

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.label)


@dataclass(frozen=True, slots=True)
class FigureSpec:
    id: str
    width: str | Length = "double-column"
    height: Length | None = None
    root: str = "root"
    style: str = "paper"
    palette: str = "default"
    nodes: tuple[NodeSpec, ...] = ()
    edges: tuple[EdgeSpec, ...] = ()
    nets: tuple[NetSpec, ...] = ()
    groups: tuple[GroupSpec, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_id(self.id, "Figure ID")
        _validate_id(self.root, "Root group ID")

    def node(self, node_id: str) -> NodeSpec:
        return next(node for node in self.nodes if node.id == node_id)

    def group(self, group_id: str) -> GroupSpec:
        return next(group for group in self.groups if group.id == group_id)


def layout_connections(figure: FigureSpec) -> tuple[LayoutConnection, ...]:
    """Project authored connections for geometry-aware layout, not routing."""

    edge_connections = tuple(
        LayoutConnection(edge.source, edge.target, edge.lane_hint is not None)
        for edge in figure.edges
    )
    net_connections = tuple(
        LayoutConnection(source, target, net.rail_hint is not None, from_net=True)
        for net in figure.nets
        for source in net.sources
        for target in net.targets
    )
    return edge_connections + net_connections
