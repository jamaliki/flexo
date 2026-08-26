"""Routed IR: logical centerlines, visible shafts, and edge-label positions."""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic
from flexo.geometry import Point
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import EdgeSpec, NetSpec, PortRef


@dataclass(frozen=True, slots=True)
class Hop:
    """One bridge arc: where this shaft crosses ``over``, and hops it (R34).

    ``point`` is the crossing itself, on the hopping shaft's centerline; emit
    turns it into a semicircle of the style's hop radius centred there, inserted
    into that shaft's own path data. Only the hopper records the crossing --
    exactly one of the two shafts is interrupted, so the pair reads as one wire
    passing over the other.
    """

    point: Point
    over: str


@dataclass(frozen=True, slots=True)
class RoutedEdge:
    spec: EdgeSpec
    centerline: tuple[Point, ...]
    shaft: tuple[Point, ...]
    label_metrics: TextMetrics | None = None
    label_position: Point | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    """What the router had to overrule while drawing this edge, for the lint report.

    The net counterpart below carries the same field for the same reason: a hint
    the geometry could not honour is a warning about the figure, not a reason to
    refuse to draw it.
    """
    hops: tuple[Hop, ...] = ()
    """Where this shaft bridges another connector it crosses (R34).

    Nets carry no hops: their ink is a rail and a fan of stems rather than one
    shaft, so where a net and an edge cross it is always the edge that hops --
    it is routed later in every figure -- and a net crossing another net keeps
    the plain crossing warning.
    """


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
