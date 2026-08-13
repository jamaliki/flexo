"""Fitted IR: immutable rectangles and resolved port positions."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.geometry import Point, Rect, Side, Size
from flexo.ir.measured import MeasuredFigure, MeasuredGroup, MeasuredNode


@dataclass(frozen=True, slots=True)
class ResolvedPort:
    name: str
    side: Side
    position: Point


@dataclass(frozen=True, slots=True)
class FittedNode:
    measured: MeasuredNode
    bounds: Rect
    ports: tuple[ResolvedPort, ...]

    def port(self, name: str) -> ResolvedPort:
        return next(port for port in self.ports if port.name == name)


@dataclass(frozen=True, slots=True)
class FittedGroup:
    measured: MeasuredGroup
    bounds: Rect
    content_bounds: Rect


@dataclass(frozen=True, slots=True)
class FittedFigure:
    measured: MeasuredFigure
    nodes: tuple[FittedNode, ...]
    groups: tuple[FittedGroup, ...]
    canvas_size: Size

    def node(self, node_id: str) -> FittedNode:
        return next(node for node in self.nodes if node.measured.spec.id == node_id)

    def group(self, group_id: str) -> FittedGroup:
        return next(group for group in self.groups if group.measured.spec.id == group_id)
