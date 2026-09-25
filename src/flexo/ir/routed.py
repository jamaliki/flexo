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
    diagnostics: tuple[Diagnostic, ...] = ()
    """What the router had to overrule while drawing this edge, for the lint report.

    The net counterpart below carries the same field for the same reason: a hint
    the geometry could not honour is a warning about the figure, not a reason to
    refuse to draw it.
    """
    dots: tuple[Point, ...] = ()
    """Branch points to mark, when this edge shares its ink with others (a bundle)."""
    joints: tuple[Point, ...] = ()
    """Every branch point of this edge's bundle: corners there are drawn sharp.

    Two edges of one bundle share ink up to a junction and part there. Drawn
    with a fillet, the one that turns would round the corner of the T the other
    draws straight through, which reads as a smudge at the joint.
    """
    straight: bool = False
    """Whether this edge is one straight segment rather than a routed path."""
    joined_at: Point | None = None
    """Where this edge merges into another of its bundle and its ink stops, arrow first."""
    bundle: str | None = None
    """The tree this edge was routed in with others: one value, several ends.

    Edges of one bundle share ink on purpose, so lint does not read their common
    trunk as two routes too close together.
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
    trunks: tuple[tuple[Point, ...], ...] = ()
    """Pieces of the net's tree between junctions, beyond ``rail`` (the longest)."""
    bundle: str | None = None
    """The tree this net was routed in, when it shares it with edges."""
    joins: tuple[tuple[Point, ...], ...] = ()
    """Pieces between junctions that end in an arrowhead where they merge (drawn shafts)."""
    dots: tuple[Point, ...] | None = None
    """Where three or more pieces of the tree meet: its branch points.

    ``None`` means the router did not decide, and emission falls back to working
    them out from the rail.
    """

    @property
    def pieces(self) -> tuple[tuple[Point, ...], ...]:
        """Every polyline of the net: rail, trunks, and stems."""

        return (
            self.rail,
            *self.trunks,
            *self.joins,
            *(stem.centerline for stem in self.source_stems + self.target_stems),
        )

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
