"""Semantic input IR: meaning and relationships without computed geometry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from flexo.geometry import Insets, Side
from flexo.units import Extent, Length

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
type Scalar = str | int | float | bool
type LayoutKind = Literal["row", "column", "grid", "overlay", "stack"]
type CollisionPolicy = Literal["disjoint", "overlay", "ignore"]
type NetKind = Literal["fan-out", "merge"]
type JointStyle = Literal["dot", "arrow", "auto"]
JOINT_STYLES = ("dot", "arrow", "auto")
"""How a branch is marked where it meets the trunk of its net."""
TITLE_SIDES = ("left", "right")
"""Where a group may anchor its title along its own top edge."""
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
    row_gap: Length | None = None
    """Space between rows; falls back to ``gap``, then to the style token."""
    column_gap: Length | None = None
    """Space between columns; falls back to ``gap``, then to the style token."""
    padding_top: Length | None = None
    padding_right: Length | None = None
    padding_bottom: Length | None = None
    padding_left: Length | None = None
    """One side of the group's padding; each falls back to ``padding``.

    A panel usually wants more air above and below its content than beside it,
    and a single ``padding`` can only buy that by widening the panel too.
    """
    placements: tuple[tuple[str, int, int], ...] = ()
    """``(child id, row, column)`` for grid children placed by address.

    Rows and columns are 0-indexed. Children absent from this tuple keep
    row-major flow order, skipping the cells these claim.
    """
    column_widths: tuple[tuple[int, Length], ...] = ()
    """``(column index, minimum width)`` reserved even when the column is empty."""

    def __post_init__(self) -> None:
        if self.kind == "grid" and (self.columns is None or self.columns < 1):
            raise ValueError("grid layout requires a positive column count")
        if self.columns is not None and self.columns < 1:
            raise ValueError("columns must be positive")
        if self.kind != "grid" and (self.placements or self.column_widths):
            raise ValueError(
                f'cell placements and column widths need a grid layout, not "{self.kind}"'
            )
        columns = self.columns or 1
        occupied: dict[tuple[int, int], str] = {}
        for child_id, row, column in self.placements:
            _validate_id(child_id, "Placed child ID")
            if row < 0 or column < 0:
                raise ValueError(
                    f'cell (row {row}, column {column}) for "{child_id}" is out of range; '
                    "grid rows and columns are 0-indexed"
                )
            if column >= columns:
                raise ValueError(
                    f'column {column} for "{child_id}" is out of range; '
                    f"the grid has {columns} columns (0-{columns - 1})"
                )
            previous = occupied.setdefault((row, column), child_id)
            if previous != child_id:
                raise ValueError(
                    f"cell (row {row}, column {column}) is claimed by both "
                    f'"{previous}" and "{child_id}"'
                )
        placed = [child_id for child_id, _, _ in self.placements]
        if len(placed) != len(set(placed)):
            raise ValueError("a grid child may only be placed in one cell")
        for column, _ in self.column_widths:
            if not 0 <= column < columns:
                raise ValueError(
                    f"reserved width for column {column} is out of range; "
                    f"the grid has {columns} columns (0-{columns - 1})"
                )
        reserved = [column for column, _ in self.column_widths]
        if len(reserved) != len(set(reserved)):
            raise ValueError("a grid column may only reserve one minimum width")

    def placement_map(self) -> dict[str, tuple[int, int]]:
        return {child_id: (row, column) for child_id, row, column in self.placements}

    def resolved_gap(self, default: Length) -> float:
        return (self.gap or default).points

    def resolved_row_gap(self, default: Length) -> float:
        return (self.row_gap or self.gap or default).points

    def resolved_column_gap(self, default: Length) -> float:
        return (self.column_gap or self.gap or default).points

    def axis_gap(self, kind: LayoutKind, default: Length) -> float:
        """The gap between siblings of a linear arrangement of ``kind``.

        A row lays its children out across columns and a column stacks them into
        rows, so each linear axis reads the asymmetric token that names it.
        """

        if kind == "row":
            return self.resolved_column_gap(default)
        if kind in {"column", "stack"}:
            return self.resolved_row_gap(default)
        return self.resolved_gap(default)

    def resolved_padding(self, default: Length) -> Insets:
        base = (self.padding or default).points
        return Insets(
            self.padding_top.points if self.padding_top is not None else base,
            self.padding_right.points if self.padding_right is not None else base,
            self.padding_bottom.points if self.padding_bottom is not None else base,
            self.padding_left.points if self.padding_left is not None else base,
        )


@dataclass(frozen=True, slots=True)
class NodeSpec:
    id: str
    kind: str
    label: tuple[TextRun, ...] = ()
    role: str = "block"
    ports: tuple[PortSpec, ...] = ()
    width: Extent | None = None
    height: Extent | None = None
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
    rail_at: float | None = None
    """Where along the trunk run the shared rail sits, as a fraction in (0, 1).

    The run is measured from the trunk's start toward the destination: for a
    merge from the source port furthest from the sink up to the sink itself, for
    a fan-out from the shared source out to the target furthest from it. The
    fraction is a *request*: the router clamps it to the nearest feasible rail
    when honouring it would cross a component, and says so with a warning.
    ``None`` keeps the default placement, one escape short of the hub.
    """
    joint: JointStyle = "auto"
    """How a branch meeting this net's trunk is marked.

    ``"auto"`` follows ``style.junction_dots``; ``"dot"`` always draws the
    junction dot; ``"arrow"`` ends the joining ink in an arrowhead pointing into
    the trunk, which the trunk itself crosses unbroken.
    """

    def __post_init__(self) -> None:
        _validate_id(self.id, "Net ID")
        if self.joint not in JOINT_STYLES:
            raise ValueError(
                f'unknown joint style "{self.joint}" for net "{self.id}"; '
                f"valid styles: {', '.join(JOINT_STYLES)}"
            )
        if self.joint == "arrow" and self.kind != "merge":
            raise ValueError(
                f'net "{self.id}" cannot join with an arrow: an arrowhead marks a branch '
                "flowing into a trunk, which only a merge has"
            )
        if self.rail_at is not None:
            if not 0.0 < self.rail_at < 1.0:
                raise ValueError(
                    f'net "{self.id}" rail_at must lie strictly between 0 and 1, '
                    f"not {self.rail_at}"
                )
            if self.rail_hint is not None:
                raise ValueError(
                    f'net "{self.id}" places its rail twice: a side hint pins the rail to '
                    "the boundary and rail_at measures along the trunk; choose one"
                )
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
    title_side: Literal["left", "right"] = "left"
    """Which end of the group's top edge its title is anchored to.

    Paint and typography only: the title band is the same height either way, so
    moving it moves no child.
    """

    def __post_init__(self) -> None:
        _validate_id(self.id, "Group ID")
        if len(self.children) != len(set(self.children)):
            raise ValueError(f'group "{self.id}" contains duplicate children')
        if self.title_side not in TITLE_SIDES:
            raise ValueError(
                f'unknown title side "{self.title_side}" for group "{self.id}"; '
                f"valid sides: {', '.join(TITLE_SIDES)}"
            )

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
