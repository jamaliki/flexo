"""Ergonomic Python authoring that lowers into the versioned semantic IR."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Self

from flexo.components import normalize_node
from flexo.geometry import Side
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutKind,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    Scalar,
    TextRun,
)
from flexo.style import RAMP_ROLES, STYLES, LayoutStyle
from flexo.units import Length
from flexo.validate import normalize_and_validate


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
    children: list[str] = field(default_factory=list)


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
        )

    @property
    def spec(self) -> FigureSpec:
        groups = tuple(
            GroupSpec(
                draft.id,
                tuple(draft.children),
                draft.layout,
                draft.collision_policy,  # type: ignore[arg-type]
                draft.label,
                draft.role,
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
        padding: Length | str | float | None = None,
        align: str = "center",
        justify: str = "start",
        columns: int | None = None,
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        reflow: LayoutKind | None = None,
        equal_size: bool = False,
        collision_policy: str = "disjoint",
        role: str = "container",
    ) -> GroupBuilder:
        scoped_id = self._scoped(id)
        layout_spec = (
            layout
            if isinstance(layout, LayoutSpec)
            else LayoutSpec(
                layout,
                _length(gap),
                _length(padding),
                align,  # type: ignore[arg-type]
                justify,  # type: ignore[arg-type]
                columns,
                _length(width),
                _length(height),
                reflow,
                equal_size,
            )
        )
        draft = _GroupDraft(
            scoped_id,
            layout_spec,
            collision_policy,
            _label(label),
            role,
        )
        self._draft.children.append(scoped_id)
        self.figure._groups.append(draft)
        return GroupBuilder(self.figure, draft)

    def row(self, id: str, **options: object) -> GroupBuilder:
        return self.group(id, layout="row", **options)

    def column(self, id: str, **options: object) -> GroupBuilder:
        return self.group(id, layout="column", **options)

    def grid(self, id: str, *, columns: int, **options: object) -> GroupBuilder:
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
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        properties: dict[str, Scalar] | None = None,
    ) -> NodeHandle:
        node = normalize_node(
            NodeSpec(
                self._scoped(id),
                kind,
                _label(label),
                role,
                ports,
                _length(width),
                _length(height),
                tuple(sorted((properties or {}).items())),
            )
        )
        self.figure._nodes.append(node)
        self._draft.children.append(node.id)
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
        ramp: str = "ramp-node",
        cells: int = 3,
        columns: int = 1,
        input: NodeHandle | PortRef | str | None = None,
        gap: Length | str | float | None = None,
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
        """

        if cells < 1:
            raise ValueError("a vector needs at least one cell")
        if columns < 1:
            raise ValueError("a vector needs at least one column")
        if ramp not in RAMP_ROLES:
            valid = ", ".join(RAMP_ROLES)
            raise ValueError(f'unknown vector ramp "{ramp}"; valid ramps: {valid}')
        stack = self.column(
            id,
            gap=_vector_label_gap(self.figure.style) if gap is None else gap,
            padding=0,
            align="center",
            role="layout",
        )
        result = stack.node(
            "cells",
            "vector",
            properties={"cells": cells, "columns": columns, "ramp": ramp},
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


def _port_name(value: str | None) -> str:
    if value is None:
        return "output"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return normalized if normalized and normalized[0].isalpha() else f"p-{normalized or 'output'}"
