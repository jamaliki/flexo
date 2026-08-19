"""Routed IR: logical centerlines, visible shafts, and edge-label positions."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic
from flexo.geometry import Point
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import EdgeSpec, NetSpec, PortRef


@dataclass(frozen=True, slots=True)
class RoutedEdge:
    spec: EdgeSpec
    centerline: tuple[Point, ...]
    shaft: tuple[Point, ...]
    label_metrics: TextMetrics | None = None
    label_position: Point | None = None


@dataclass(frozen=True, slots=True)
class RoutedStem:
    port: PortRef
    centerline: tuple[Point, ...]
    shaft: tuple[Point, ...]
    arrow_end: bool = False


@dataclass(frozen=True, slots=True)
class RoutedNet:
    spec: NetSpec
    rail: tuple[Point, ...]
    source_stems: tuple[RoutedStem, ...]
    target_stems: tuple[RoutedStem, ...]
    label_metrics: TextMetrics | None = None
    label_position: Point | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    """What the router had to overrule while placing this net, for the lint report."""

    @property
    def junctions(self) -> tuple[Point, ...]:
        return tuple(
            stem.centerline[-1] for stem in self.source_stems
        ) + tuple(stem.centerline[0] for stem in self.target_stems)


@dataclass(frozen=True, slots=True)
class RoutedFigure:
    fitted: FittedFigure
    edges: tuple[RoutedEdge, ...]
    nets: tuple[RoutedNet, ...] = ()

    def edge(self, edge_id: str) -> RoutedEdge:
        return next(edge for edge in self.edges if edge.spec.id == edge_id)

    def net(self, net_id: str) -> RoutedNet:
        return next(net for net in self.nets if net.spec.id == net_id)
