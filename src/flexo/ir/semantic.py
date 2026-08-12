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
    groups: tuple[GroupSpec, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_id(self.id, "Figure ID")
        _validate_id(self.root, "Root group ID")

    def node(self, node_id: str) -> NodeSpec:
        return next(node for node in self.nodes if node.id == node_id)

    def group(self, group_id: str) -> GroupSpec:
        return next(group for group in self.groups if group.id == group_id)
