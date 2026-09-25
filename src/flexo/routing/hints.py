"""What the author said about a route: lanes, waypoints, and ``via`` sides.

``lane=`` and waypoints fix points a route must pass through
(``forced_points``); ``via=`` names the side a route should keep to, and
``via_diagnostics`` reports when the geometry made it take the other one.
"""

from __future__ import annotations

from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Side, segments
from flexo.ir.fitted import FittedFigure
from flexo.ir.semantic import EdgeSpec, Waypoint


@dataclass(frozen=True, slots=True)
class SideBias:
    """The side of its own region a route was asked to favour, and that region.

    The region is the box the two endpoints span, measured on the hint's own
    axis: a west or east hint reads ``low``/``high`` as left and right, a north
    or south one as top and bottom. Inside the region nothing is priced -- every
    route has to cross it -- and neither is a detour on the hinted side. What
    costs is length spent beyond the region on the *other* side, which is exactly
    the connector that wrapped the far face of a module and came back through it.
    """

    side: Side
    low: float
    high: float

    @classmethod
    def of(cls, side: Side, region: Rect) -> SideBias:
        if side.horizontal:
            return cls(side, region.left, region.right)
        return cls(side, region.top, region.bottom)

    @property
    def vertical(self) -> bool:
        """Whether the biased coordinate is an x: the hint names east or west."""

        return self.side.horizontal

    def rejected(self, coordinate: float, tolerance: float = 0.0) -> bool:
        """Whether ``coordinate`` lies beyond the region on the refused side."""

        if self.side in {Side.WEST, Side.NORTH}:
            return coordinate > self.high + tolerance
        return coordinate < self.low - tolerance


_VIA_TOLERANCE = 0.5
"""How far past its region a run may stray before it counts as taking that side.

Half a point: a stub that ends exactly on the region edge, or a lane nudged off
an obstacle by a fraction, has not chosen a corridor.
"""

_OPPOSITE = {
    Side.NORTH: Side.SOUTH,
    Side.SOUTH: Side.NORTH,
    Side.EAST: Side.WEST,
    Side.WEST: Side.EAST,
}


def via_diagnostics(
    edge: EdgeSpec,
    centerline: tuple[Point, ...],
    bias: SideBias | None,
) -> tuple[Diagnostic, ...]:
    """Say out loud that an authored ``via`` had to give way to the geometry.

    The hint is honoured whenever the route keeps out of the corridor it refused
    -- including the ordinary case of a route that never leaves the region
    between its endpoints at all, which needed no corridor. It is clamped only
    when every point of detour ended up on the wrong side, and then the warning
    names the side the route actually took, the way a clamped ``rail_at`` names
    the fraction it reached.
    """

    if bias is None or edge.via is None:
        return ()
    favoured = 0.0
    refused = 0.0
    mirror = SideBias(_OPPOSITE[bias.side], bias.low, bias.high)
    for segment in segments(centerline):
        coordinate = (
            (segment.start.x + segment.end.x) / 2.0
            if bias.vertical
            else (segment.start.y + segment.end.y) / 2.0
        )
        if bias.rejected(coordinate, _VIA_TOLERANCE):
            refused += segment.length
        elif mirror.rejected(coordinate, _VIA_TOLERANCE):
            favoured += segment.length
    # Clamped when the detour went mostly the way the author refused: a route
    # that crosses back to arrive on the hinted side still took the far corridor.
    if refused <= _VIA_TOLERANCE or favoured >= refused:
        return ()
    achieved = _OPPOSITE[edge.via]
    return (
        Diagnostic(
            "routing.via.clamped",
            f"Requested via {edge.via.value} leaves no corridor; the route runs "
            f"{achieved.value} of its endpoints instead.",
            Severity.WARNING,
            entity_id=edge.id,
            hint=f"Open a corridor {edge.via.value} of the endpoints, or drop the hint.",
        ),
    )


def forced_points(
    fitted: FittedFigure,
    edge: EdgeSpec,
    source_escape: Point,
    target_escape: Point,
    boundary_clearance: float,
) -> tuple[Point, ...]:
    result: list[Point] = []
    if edge.lane_hint:
        result.extend(
            _lane_points(
                fitted,
                edge.lane_hint,
                source_escape,
                target_escape,
                boundary_clearance,
                edge.id,
            )
        )
    result.extend(_waypoint(fitted, waypoint, edge.id) for waypoint in edge.waypoints)
    return tuple(result)


def _lane_points(
    fitted: FittedFigure,
    lane: str,
    source: Point,
    target: Point,
    boundary_clearance: float,
    edge_id: str,
) -> tuple[Point, Point]:
    if "-" not in lane:
        raise FlexoError(
            Diagnostic(
                "routing.lane.syntax",
                f'Lane "{lane}" must end in -top, -bottom, -left, or -right.',
                entity_id=edge_id,
            )
        )
    reference, suffix = lane.rsplit("-", 1)
    try:
        bounds = fitted.group(reference).bounds
    except StopIteration as exc:
        raise FlexoError(
            Diagnostic(
                "routing.lane.unknown",
                f'Lane group "{reference}" does not exist.',
                entity_id=edge_id,
            )
        ) from exc
    if suffix == "bottom":
        y = bounds.bottom - boundary_clearance
        return Point(source.x, y), Point(target.x, y)
    if suffix == "top":
        y = bounds.top + boundary_clearance
        return Point(source.x, y), Point(target.x, y)
    if suffix == "left":
        x = bounds.left + boundary_clearance
        return Point(x, source.y), Point(x, target.y)
    if suffix == "right":
        x = bounds.right - boundary_clearance
        return Point(x, source.y), Point(x, target.y)
    raise FlexoError(
        Diagnostic(
            "routing.lane.syntax",
            f'Unknown lane side "{suffix}".',
            entity_id=edge_id,
            hint="Use top, bottom, left, or right.",
        )
    )


def _waypoint(fitted: FittedFigure, waypoint: Waypoint, edge_id: str) -> Point:
    if waypoint.reference is None:
        assert waypoint.x is not None and waypoint.y is not None
        return Point(waypoint.x.points, waypoint.y.points)
    bounds: Rect
    try:
        bounds = fitted.node(waypoint.reference).bounds
    except StopIteration:
        try:
            bounds = fitted.group(waypoint.reference).bounds
        except StopIteration as exc:
            raise FlexoError(
                Diagnostic(
                    "routing.waypoint.unknown",
                    f'Waypoint reference "{waypoint.reference}" does not exist.',
                    entity_id=edge_id,
                )
            ) from exc
    origin = (
        bounds.center
        if waypoint.side is None
        else bounds.point_on(waypoint.side, waypoint.offset)
    )
    return origin.translated(waypoint.dx.points, waypoint.dy.points)



