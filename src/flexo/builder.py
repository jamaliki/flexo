"""Ergonomic Python authoring that lowers into the versioned semantic IR."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Self

from flexo.components import normalize_node
from flexo.geometry import Side
from flexo.ir.semantic import (
    TITLE_SIDES,
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    JointStyle,
    LayoutKind,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    Scalar,
    TextRun,
)
from flexo.style import (
    PAINT_PARTS,
    PAINT_PROPERTY_PREFIX,
    RAMP_ROLES,
    STYLES,
    LayoutStyle,
    VectorPreset,
    normalize_colour,
)
from flexo.units import Extent, Length, parse_extent
from flexo.validate import normalize_and_validate

type Padding = Length | str | float | Sequence[Length | str | float]
"""One length for all four sides, an ``(x, y)`` pair, or ``(top, right, bottom, left)``."""

type Cell = tuple[int, int]
"""A 0-indexed ``(row, column)`` grid address."""


@dataclass(frozen=True, slots=True)
class NodeHandle:
    id: str
    ports: tuple[str, ...]

    def port(self, name: str) -> PortRef:
        if name not in self.ports:
            raise AttributeError(
                f'node "{self.id}" has no port "{name}"; valid ports: {", ".join(self.ports)}'
            )
        return PortRef(self.id, name)

    @property
    def input(self) -> PortRef:
        return self.port("input")

    @property
    def output(self) -> PortRef:
        return self.port("output")

    def __getattr__(self, name: str) -> PortRef:
        return self.port(name)


@dataclass(slots=True)
class _GroupDraft:
    id: str
    layout: LayoutSpec
    collision_policy: str
    label: tuple[TextRun, ...]
    role: str
    title_side: str = "left"
    children: list[str] = field(default_factory=list)
    placements: dict[str, Cell] = field(default_factory=dict)
    """Grid cells claimed by ``at=``, collected as children are authored."""


class Figure:
    """Context-managed semantic figure builder."""

    def __init__(
        self,
        id: str = "figure",
        *,
        width: str | Length = "double-column",
        height: Length | str | float | None = None,
        style: str = "paper",
        palette: str = "default",
        layout: LayoutSpec | None = None,
    ) -> None:
        self.id = id
        self.width = width
        self.height = Length.parse(height) if height is not None else None
        self.style = style
        self.palette = palette
        root = _GroupDraft(
            "root",
            layout or LayoutSpec("column", align="center", justify="center"),
            "disjoint",
            (),
            "canvas",
        )
        self._groups: list[_GroupDraft] = [root]
        self._nodes: list[NodeSpec] = []
        self._edges: list[EdgeSpec] = []
        self._nets: list[NetSpec] = []
        self._edge_counter = 0
        self._net_counter = 0
        self.root = GroupBuilder(self, root)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if exception_type is None:
            _ = self.spec

    def module(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        layout: LayoutKind | LayoutSpec = "row",
        gap: Length | str | float | None = None,
        align: str = "center",
        justify: str = "center",
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        role: str = "module",
        title_side: str = "left",
    ) -> GroupBuilder:
        return self.root.group(
            id,
            label=label,
            layout=layout,
            gap=gap,
            align=align,
            justify=justify,
            width=width,
            height=height,
            role=role,
            title_side=title_side,
        )

    @property
    def spec(self) -> FigureSpec:
        groups = tuple(
            GroupSpec(
                draft.id,
                tuple(draft.children),
                _with_placements(draft),
                draft.collision_policy,  # type: ignore[arg-type]
                draft.label,
                draft.role,
                draft.title_side,  # type: ignore[arg-type]
            )
            for draft in self._groups
        )
        return normalize_and_validate(
            FigureSpec(
                id=self.id,
                width=self.width,
                height=self.height,
                root="root",
                style=self.style,
                palette=self.palette,
                nodes=tuple(self._nodes),
                edges=tuple(self._edges),
                nets=tuple(self._nets),
                groups=groups,
            )
        )

    def net(
        self,
        *,
        src: NodeHandle | PortRef | str,
        sinks: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author one shared value read by multiple downstream ports."""

        return self._add_net(
            "fan-out",
            (_reference(src, "output"),),
            tuple(_reference(sink, "input") for sink in sinks),
            id=id,
            rail=rail,
            rail_at=rail_at,
            joint=joint,
            label=label,
            role=role,
        )

    def merge(
        self,
        *,
        sinks: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        dst: NodeHandle | PortRef | str,
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author a true many-to-one combination before one destination."""

        return self._add_net(
            "merge",
            tuple(_reference(source, "output") for source in sinks),
            (_reference(dst, "input"),),
            id=id,
            rail=rail,
            rail_at=rail_at,
            joint=joint,
            label=label,
            role=role,
        )

    def _add_net(
        self,
        kind: str,
        sources: tuple[PortRef, ...],
        targets: tuple[PortRef, ...],
        *,
        id: str | None,
        rail: Side | str | None,
        rail_at: float | None,
        joint: JointStyle,
        label: str | tuple[TextRun, ...],
        role: str,
    ) -> NetSpec:
        self._net_counter += 1
        net = NetSpec(
            id or f"net.{self._net_counter}",
            kind,  # type: ignore[arg-type]
            sources,
            targets,
            role,
            _label(label),
            Side(rail) if isinstance(rail, str) else rail,
            rail_at,
            joint,
        )
        self._nets.append(net)
        return net

    def compile(self):
        from flexo.compiler import compile_figure

        return compile_figure(self.spec)


class GroupBuilder:
    """A scoped editorial group and component factory."""

    def __init__(self, figure: Figure, draft: _GroupDraft) -> None:
        self.figure = figure
        self._draft = draft

    @property
    def id(self) -> str:
        return self._draft.id

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        return None

    def group(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        layout: LayoutKind | LayoutSpec = "row",
        gap: Length | str | float | None = None,
        row_gap: Length | str | float | None = None,
        column_gap: Length | str | float | None = None,
        padding: Padding | None = None,
        align: str = "center",
        justify: str = "start",
        columns: int | None = None,
        column_widths: Mapping[int, Length | str | float] | None = None,
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        reflow: LayoutKind | None = None,
        equal_size: bool = False,
        collision_policy: str = "disjoint",
        role: str = "container",
        title_side: str = "left",
        at: Cell | None = None,
    ) -> GroupBuilder:
        """Open a nested layout group.

        ``gap`` spaces siblings on both axes; ``row_gap`` and ``column_gap``
        override it for one axis each, so a grid can breathe vertically without
        also spreading sideways. ``padding`` is one length for all four sides, an
        ``(x, y)`` pair, or ``(top, right, bottom, left)``.

        ``at=(row, column)`` places this group in one cell of the enclosing grid
        (see ``grid`` for the rules), and ``column_widths`` reserves minimum
        widths in this group's own grid.

        ``title_side="right"`` anchors the group's title to the right end of its
        top edge instead of the left. The title band is the same height either
        way, so nothing else in the figure moves.
        """

        scoped_id = self._scoped(id)
        if title_side not in TITLE_SIDES:
            raise ValueError(
                f'unknown title side "{title_side}" for group "{scoped_id}"; '
                f"valid sides: {', '.join(TITLE_SIDES)}"
            )
        uniform, top, right, bottom, left = _padding(padding)
        layout_spec = (
            layout
            if isinstance(layout, LayoutSpec)
            else LayoutSpec(
                kind=layout,
                gap=_length(gap),
                padding=uniform,
                align=align,  # type: ignore[arg-type]
                justify=justify,  # type: ignore[arg-type]
                columns=columns,
                width=_length(width),
                height=_length(height),
                reflow=reflow,
                equal_size=equal_size,
                row_gap=_length(row_gap),
                column_gap=_length(column_gap),
                padding_top=top,
                padding_right=right,
                padding_bottom=bottom,
                padding_left=left,
                column_widths=_column_widths(column_widths, columns),
            )
        )
        draft = _GroupDraft(
            scoped_id,
            layout_spec,
            collision_policy,
            _label(label),
            role,
            title_side,
        )
        self._draft.children.append(scoped_id)
        self._place(scoped_id, at)
        self.figure._groups.append(draft)
        return GroupBuilder(self.figure, draft)

    def row(self, id: str, **options: object) -> GroupBuilder:
        return self.group(id, layout="row", **options)

    def column(self, id: str, **options: object) -> GroupBuilder:
        return self.group(id, layout="column", **options)

    def grid(self, id: str, *, columns: int, **options: object) -> GroupBuilder:
        """Open a grid of ``columns`` columns whose children fill it by cell.

        A child may name its cell with ``at=(row, column)``, 0-indexed from the
        top-left. Mixed mode is deterministic: **addressed children claim their
        cells first, then the unaddressed ones keep author order and flow
        row-major into whatever cells are left.** So a child addressed at (0, 4)
        pushes no sibling sideways -- the flow simply steps over that cell when
        it reaches it.

        Nothing has to fill the holes. A short last row, an empty column, or a
        gap in the middle of a row all cost zero children; the grid pads them
        internally. Rows grow to hold the highest row any child addresses.

        An empty column still occupies its slot, and ``column_widths={index:
        length}`` reserves a minimum width for one -- that is how a lane that
        carries only a connector and its caption gets its space, with no node in
        it at all.

        Two children addressed to the same cell, or a column outside the grid,
        is an error at the point of authoring.
        """

        return self.group(id, layout="grid", columns=columns, **options)

    def overlay(self, id: str, **options: object) -> GroupBuilder:
        return self.group(id, layout="overlay", collision_policy="overlay", **options)

    def node(
        self,
        id: str,
        kind: str = "block",
        *,
        label: str | tuple[TextRun, ...] = "",
        role: str = "block",
        ports: tuple[PortSpec, ...] = (),
        width: Extent | str | float | None = None,
        height: Extent | str | float | None = None,
        properties: dict[str, Scalar] | None = None,
        paint: Mapping[str, str] | None = None,
        motif: bool = True,
        at: Cell | None = None,
    ) -> NodeHandle:
        """Author one component.

        ``width`` and ``height`` take any length, or the string ``"cells:N"`` --
        the height of an N-cell vector stack under the figure's style, so a box
        lines its side ports up with a vector without the author computing the
        stack. ``at=(row, column)`` places the node in one cell of an enclosing
        grid.

        ``paint={"fill": ..., "stroke": ..., "label": ...}`` overrides the
        palette role for this node's body fill, body stroke, and label text with
        literal hex colours. An overridden part carries no paint role into the
        SVG, so ``flexo retheme`` leaves it as authored -- reach for it when one
        component has to differ from its palette, and change the palette when
        every component of a kind does.

        ``motif=False`` drops the component's decorative motif -- an MLP's three
        dots, a matrix's cell grid -- and changes nothing else.
        """

        resolved = dict(properties or {})
        resolved.update(_paint_properties(paint))
        if not motif:
            resolved["motif"] = False
        node = normalize_node(
            NodeSpec(
                self._scoped(id),
                kind,
                _label(label),
                role,
                ports,
                _extent(width),
                _extent(height),
                tuple(sorted(resolved.items())),
            )
        )
        self.figure._nodes.append(node)
        self._draft.children.append(node.id)
        self._place(node.id, at)
        return NodeHandle(node.id, tuple(port.name for port in node.ports))

    def block(self, id: str, *, label: str = "", **options: object) -> NodeHandle:
        return self.node(id, "block", label=label, **options)

    def feature_strip(
        self,
        id: str,
        *,
        label: str = "",
        cells: int = 6,
        **options: object,
    ) -> NodeHandle:
        return self.node(
            id,
            "feature-strip",
            label=label,
            properties={"cells": cells},
            **options,
        )

    def vector(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        preset: VectorPreset | None = None,
        ramp: str | None = None,
        cells: int | None = None,
        columns: int | None = None,
        input: NodeHandle | PortRef | str | None = None,
        gap: Length | str | float | None = None,
        at: Cell | None = None,
        **options: object,
    ) -> NodeHandle:
        """A labelled vertical vector glyph: a cell stack with its label below it.

        The composite lowers into a small layout column holding two children --
        ``<id>.cells`` (kind ``vector``) and, when a label is given,
        ``<id>.label`` (kind ``label``). Keeping the caption in its own node is
        what lets the glyph's ports stay the trivial centres of the cell rect:
        no port arithmetic has to know that a caption hangs underneath, and an
        arrow arrives on the middle cell rather than on the middle of
        cells-plus-caption. The returned handle is always the cells node, so
        edges and nets attach to the glyph itself.

        A caption wider than the stack is fine -- the column centres both -- and
        a ``\\n`` in the label breaks it across lines instead of widening it.

        A ``preset`` replaces ``ramp``, ``cells``, and ``columns``: it carries
        the author's own base colour and topology, and the cells paint the
        shades it derives rather than a palette role.

        ``at=(row, column)`` addresses the composite -- caption and all -- in an
        enclosing grid, because the column holding both is the grid's child.
        """

        if preset is not None:
            if ramp is not None or cells is not None or columns is not None:
                raise ValueError(
                    "a vector preset already carries colour and topology; "
                    "drop ramp, cells, and columns"
                )
            properties: dict[str, Scalar] = {
                "cells": preset.cells,
                "columns": preset.columns,
                "shades": preset.encode(),
            }
        else:
            ramp = "ramp-node" if ramp is None else ramp
            cells = 3 if cells is None else cells
            columns = 1 if columns is None else columns
            if cells < 1:
                raise ValueError("a vector needs at least one cell")
            if columns < 1:
                raise ValueError("a vector needs at least one column")
            if ramp not in RAMP_ROLES:
                valid = ", ".join(RAMP_ROLES)
                raise ValueError(f'unknown vector ramp "{ramp}"; valid ramps: {valid}')
            properties = {"cells": cells, "columns": columns, "ramp": ramp}
        stack = self.column(
            id,
            gap=_vector_label_gap(self.figure.style) if gap is None else gap,
            padding=0,
            align="center",
            role="layout",
            at=at,
        )
        result = stack.node(
            "cells",
            "vector",
            properties=properties,
            **{"role": "vector", **options},
        )
        if _label(label):
            stack.node("label", "label", label=label, role="label")
        if input is not None:
            self.connect(input, result.input)
        return result

    def matrix(self, id: str, *, label: str = "", **options: object) -> NodeHandle:
        return self.node(id, "matrix", label=label, **options)

    def sequence(
        self,
        id: str,
        *,
        label: str = "",
        tokens: int = 7,
        **options: object,
    ) -> NodeHandle:
        return self.node(
            id,
            "sequence",
            label=label,
            properties={"tokens": tokens},
            **options,
        )

    def graph(self, id: str, *, label: str = "", **options: object) -> NodeHandle:
        return self.node(id, "graph", label=label, **options)

    def inset(self, id: str, *, label: str = "", **options: object) -> NodeHandle:
        return self.node(id, "inset", label=label, **options)

    def tensor(self, id: str, *, label: str = "", **options: object) -> NodeHandle:
        return self.node(id, "tensor", label=label, **options)

    def concat(
        self,
        id: str,
        *,
        inputs: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        label: str = "Concat",
        **options: object,
    ) -> NodeHandle:
        sources = tuple(inputs)
        if len(sources) < 2:
            raise ValueError("concat requires at least two inputs")
        ports = (
            *(
                PortSpec(
                    f"input{index + 1}",
                    Side.WEST,
                    (index + 1) / (len(sources) + 1),
                    adaptive=True,
                )
                for index in range(len(sources))
            ),
            PortSpec("output", Side.EAST, adaptive=True),
        )
        result = self.node(id, "concat", label=label, ports=ports, **options)
        for index, source in enumerate(sources):
            self.connect(source, result.port(f"input{index + 1}"))
        return result

    def channels(
        self,
        id: str,
        *,
        labels: tuple[str, ...] | list[str],
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> tuple[PortRef, ...]:
        names = tuple(labels)
        if not names:
            raise ValueError("channels requires at least one label")
        ports = (
            PortSpec("input", Side.WEST, adaptive=True),
            *(
                PortSpec(
                    _port_name(name),
                    Side.EAST,
                    (index + 1) / (len(names) + 1),
                    adaptive=True,
                )
                for index, name in enumerate(names)
            ),
        )
        result = self.node(
            id,
            "channels",
            ports=ports,
            properties={"count": len(names), "labels": ",".join(names)},
            **options,
        )
        if input is not None:
            self.connect(input, result.input)
        return tuple(result.port(_port_name(name)) for name in names)

    def add_norm(
        self,
        id: str,
        *,
        label: str = "Add + norm",
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        result = self.node(id, "add-norm", label=label, **options)
        if input is not None:
            self.connect(input, result)
        return result

    def mlp(
        self,
        id: str,
        *,
        label: str = "MLP",
        input: NodeHandle | PortRef | str | None = None,
        inputs: tuple[NodeHandle | PortRef | str, ...] | list[NodeHandle | PortRef | str] = (),
        outputs: tuple[str, ...] | list[str] = (),
        **options: object,
    ) -> NodeHandle | tuple[PortRef, ...]:
        sources = ((input,) if input is not None else ()) + tuple(inputs)
        ports = _processing_ports(len(sources), tuple(outputs)) if sources or outputs else ()
        result = self.node(id, "mlp", label=label, ports=ports, **options)
        for index, source in enumerate(sources):
            target_name = "input" if len(sources) == 1 else f"input{index + 1}"
            self.connect(source, result.port(target_name))
        if outputs:
            return tuple(result.port(_port_name(name)) for name in outputs)
        return result

    def cnn(
        self,
        id: str,
        *,
        label: str = "CNN",
        input: NodeHandle | PortRef | str | None = None,
        output: str | None = None,
        **options: object,
    ) -> NodeHandle | PortRef:
        ports = (
            (
                PortSpec("input", Side.WEST, adaptive=True),
                PortSpec(_port_name(output), Side.EAST, adaptive=True),
            )
            if output
            else ()
        )
        result = self.node(id, "cnn", label=label, ports=ports, **options)
        if input is not None:
            self.connect(input, result.input)
        return result.port(_port_name(output)) if output else result

    def attention(
        self,
        id: str,
        *,
        q: NodeHandle | PortRef | str,
        k: NodeHandle | PortRef | str,
        v: NodeHandle | PortRef | str,
        label: str | tuple[TextRun, ...] = "Attention",
        **options: object,
    ) -> NodeHandle:
        result = self.node(id, "attention", label=label, **options)
        self.connect(q, result.q)
        self.connect(k, result.k)
        self.connect(v, result.v)
        return result

    def prediction(
        self,
        id: str,
        *,
        label: str = "Prediction",
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        result = self.node(id, "prediction", label=label, **options)
        if input is not None:
            self.connect(input, result)
        return result

    def loss(
        self,
        id: str,
        *,
        label: str = "Loss",
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        result = self.node(id, "loss", label=label, **options)
        if input is not None:
            self.connect(input, result)
        return result

    def connect(
        self,
        source: NodeHandle | PortRef | str,
        target: NodeHandle | PortRef | str,
        *,
        id: str | None = None,
        source_port: str = "output",
        target_port: str = "input",
        role: str = "flow",
        label: str | tuple[TextRun, ...] = "",
        lane: str | None = None,
    ) -> EdgeSpec:
        source_ref = _reference(source, source_port)
        target_ref = _reference(target, target_port)
        self.figure._edge_counter += 1
        edge = EdgeSpec(
            id or f"edge.{self.figure._edge_counter}.{source_ref.node_id}-to-{target_ref.node_id}",
            source_ref,
            target_ref,
            role,
            _label(label),
            lane,
        )
        self.figure._edges.append(edge)
        return edge

    def residual(
        self,
        source: NodeHandle | PortRef | str,
        target: NodeHandle | PortRef | str,
        *,
        id: str | None = None,
        lane: str | None = None,
        source_port: str | None = None,
        target_port: str | None = None,
    ) -> EdgeSpec:
        if source_port is None and isinstance(source, NodeHandle):
            source_port = "residual" if "residual" in source.ports else "output"
        if target_port is None and isinstance(target, NodeHandle):
            target_port = "residual" if "residual" in target.ports else "input"
        return self.connect(
            source,
            target,
            id=id,
            source_port=source_port or "output",
            target_port=target_port or "input",
            role="residual",
            lane=lane,
        )

    def _scoped(self, id: str) -> str:
        if self.id == "root" or id.startswith(f"{self.id}."):
            return id
        return f"{self.id}.{id}"

    def _place(self, child_id: str, at: Cell | None) -> None:
        """Claim one grid cell for a child, rejecting a clash where it is made."""

        if at is None:
            return
        layout = self._draft.layout
        if layout.kind != "grid":
            raise ValueError(
                f'"at" addresses a grid cell, but group "{self.id}" lays out as a {layout.kind}'
            )
        if len(tuple(at)) != 2:
            raise ValueError('"at" takes a (row, column) pair')
        row, column = (int(value) for value in at)
        columns = layout.columns or 1
        if row < 0 or column < 0:
            raise ValueError(
                f'cell (row {row}, column {column}) for "{child_id}" is out of range; '
                "grid rows and columns are 0-indexed"
            )
        if column >= columns:
            raise ValueError(
                f'column {column} for "{child_id}" is out of range; '
                f'group "{self.id}" has {columns} columns (0-{columns - 1})'
            )
        for other_id, cell in self._draft.placements.items():
            if cell == (row, column):
                raise ValueError(
                    f'cell (row {row}, column {column}) of group "{self.id}" is already '
                    f'taken by "{other_id}"'
                )
        self._draft.placements[child_id] = (row, column)


def _with_placements(draft: _GroupDraft) -> LayoutSpec:
    if not draft.placements:
        return draft.layout
    return replace(
        draft.layout,
        placements=tuple(
            (child_id, row, column) for child_id, (row, column) in draft.placements.items()
        ),
    )


def _paint_properties(paint: Mapping[str, str] | None) -> dict[str, Scalar]:
    """Lower an authored ``paint`` mapping into one scalar property per part.

    A node property holds a scalar, never a mapping, so the three parts travel
    separately as ``paint-fill``, ``paint-stroke``, and ``paint-label``. Colours
    are normalized to ``#rrggbb`` here, which is both the validation and what
    keeps ``#abc`` and ``#aabbcc`` from serializing as two different figures.
    """

    if not paint:
        return {}
    unknown = sorted(set(paint) - set(PAINT_PARTS))
    if unknown:
        raise ValueError(
            f"unknown paint part(s) {', '.join(unknown)}; "
            f"valid parts: {', '.join(PAINT_PARTS)}"
        )
    return {
        f"{PAINT_PROPERTY_PREFIX}{part}": normalize_colour(paint[part])
        for part in PAINT_PARTS
        if part in paint
    }


def _padding(value: Padding | None) -> tuple[Length | None, ...]:
    """Normalize an authored padding into (uniform, top, right, bottom, left).

    One length stays uniform, so a figure that never asks for asymmetry keeps
    exactly the spec it had before the four sides existed.
    """

    if value is None or isinstance(value, (Length, str, int, float)):
        return (_length(value), None, None, None, None)
    sides = tuple(Length.parse(item) for item in value)
    if len(sides) == 2:
        x, y = sides
        return (None, y, x, y, x)
    if len(sides) == 4:
        return (None, *sides)
    raise ValueError(
        "padding takes one length, an (x, y) pair, or a (top, right, bottom, left) 4-tuple, "
        f"not {len(sides)} values"
    )


def _column_widths(
    value: Mapping[int, Length | str | float] | None,
    columns: int | None,
) -> tuple[tuple[int, Length], ...]:
    if not value:
        return ()
    if columns is None:
        raise ValueError("column widths need a column count; give the group columns=")
    return tuple(sorted((int(column), Length.parse(width)) for column, width in value.items()))


def _processing_ports(input_count: int, outputs: tuple[str, ...]) -> tuple[PortSpec, ...]:
    inputs = tuple(
        PortSpec(
            "input" if input_count == 1 else f"input{index + 1}",
            Side.WEST,
            (index + 1) / (input_count + 1),
            adaptive=True,
        )
        for index in range(input_count)
    )
    output_names = outputs or ("output",)
    result_outputs = tuple(
        PortSpec(
            _port_name(name),
            Side.EAST,
            (index + 1) / (len(output_names) + 1),
            adaptive=True,
        )
        for index, name in enumerate(output_names)
    )
    return inputs + result_outputs


def _vector_label_gap(style_name: str) -> Length:
    """The authored gap between a vector's cells and its caption.

    Composites lower to geometry-free semantics, so the token is resolved here,
    against the style the figure names; an unknown name is left to validation.
    """

    return (STYLES.get(style_name) or LayoutStyle()).vector_label_gap


def _reference(value: NodeHandle | PortRef | str, default_port: str) -> PortRef:
    if isinstance(value, PortRef):
        return value
    if isinstance(value, NodeHandle):
        return value.port(default_port)
    return PortRef.parse(value) if "." in value else PortRef(value, default_port)


def _label(value: str | tuple[TextRun, ...]) -> tuple[TextRun, ...]:
    if isinstance(value, str):
        return (TextRun(value),) if value else ()
    return value


def _length(value: Length | str | float | None) -> Length | None:
    return None if value is None else Length.parse(value)


def _extent(value: Extent | str | float | None) -> Extent | None:
    return None if value is None else parse_extent(value)


def _port_name(value: str | None) -> str:
    if value is None:
        return "output"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return normalized if normalized and normalized[0].isalpha() else f"p-{normalized or 'output'}"
