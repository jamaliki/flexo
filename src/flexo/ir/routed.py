"""Routed IR: logical centerlines, visible shafts, and edge-label positions."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.geometry import Point
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import EdgeSpec


@dataclass(frozen=True, slots=True)
class RoutedEdge:
    spec: EdgeSpec
    centerline: tuple[Point, ...]
    shaft: tuple[Point, ...]
    label_metrics: TextMetrics | None = None
    label_position: Point | None = None


@dataclass(frozen=True, slots=True)
class RoutedFigure:
    fitted: FittedFigure
    edges: tuple[RoutedEdge, ...]

    def edge(self, edge_id: str) -> RoutedEdge:
        return next(edge for edge in self.edges if edge.spec.id == edge_id)
