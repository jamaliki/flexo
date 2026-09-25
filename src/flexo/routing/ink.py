"""A connector's painted parts: its shaft, trimmed for arrowheads, and where its caption sits."""

from __future__ import annotations

from flexo.geometry import Point, Segment, segments
from flexo.ir.measured import TextMetrics
from flexo.style import LayoutStyle
from flexo.text import ink_descent

_EPSILON = 1e-7


def shorten_end(points: tuple[Point, ...], distance: float) -> tuple[Point, ...]:
    """Shorten an orthogonal polyline while preserving its earlier vertices."""
    if not points or distance <= 0.0:
        return points
    remaining = distance
    result = list(points)
    while len(result) >= 2:
        end = result[-1]
        previous = result[-2]
        segment_length = previous.distance_to(end)
        if segment_length > remaining:
            ratio = (segment_length - remaining) / segment_length
            result[-1] = Point(
                previous.x + (end.x - previous.x) * ratio,
                previous.y + (end.y - previous.y) * ratio,
            )
            return tuple(result)
        remaining -= segment_length
        result.pop()
    return (points[0],)


def shorten_start(points: tuple[Point, ...], distance: float) -> tuple[Point, ...]:
    """Shorten an orthogonal polyline from its head, preserving its later vertices."""
    if not points or distance <= 0.0:
        return points
    remaining = distance
    result = list(points)
    while len(result) >= 2:
        start = result[0]
        following = result[1]
        segment_length = following.distance_to(start)
        if segment_length > remaining:
            ratio = (segment_length - remaining) / segment_length
            result[0] = Point(
                following.x + (start.x - following.x) * ratio,
                following.y + (start.y - following.y) * ratio,
            )
            return tuple(result)
        remaining -= segment_length
        result.pop(0)
    return (points[-1],)


def edge_shaft(
    centerline: tuple[Point, ...],
    *,
    arrow_length: float,
    standoff: float,
) -> tuple[Point, ...]:
    """The painted polyline for a port-to-port centerline.

    Both trims are ink-only; the centerline itself stays port-to-port. The arrow
    marker is anchored at the path end with its tip a full ``arrow_length``
    further on, so trimming ``arrow_length + standoff`` leaves the tip
    ``standoff`` short of the target port.
    """

    return shorten_start(shorten_end(centerline, arrow_length + standoff), standoff)


def caption_rise(metrics: TextMetrics, style: LayoutStyle) -> float:
    """How far above a run's centerline a caption's baseline has to sit.

    A connector caption is route geometry, not a node, so the caption-obstacle
    rule that keeps routes off component captions cannot reach it: nothing stops
    a caption of its own from landing on the arrow it labels. This is the same
    clearance measured from the other side -- half the shaft's stroke, then
    ``caption_clearance`` of air, then the depth of the caption's own lowest ink,
    which is what a subscript makes deeper than the font's descender.
    """

    return (
        style.connector_width.points / 2.0
        + style.caption_clearance.points
        + ink_descent(metrics, style.typography)
    )


def caption_reach(metrics: TextMetrics, style: LayoutStyle) -> float:
    """How far beside a run's centerline a caption's near edge has to sit."""

    return style.connector_width.points / 2.0 + style.caption_clearance.points


def edge_label_position(
    points: tuple[Point, ...],
    metrics: TextMetrics,
    style: LayoutStyle,
) -> Point:
    candidates = segments(points)
    horizontal = tuple(segment for segment in candidates if segment.horizontal)
    longest = max(horizontal or candidates, key=lambda segment: segment.length)
    midpoint = Point(
        (longest.start.x + longest.end.x) / 2.0,
        (longest.start.y + longest.end.y) / 2.0,
    )
    if longest.horizontal:
        return midpoint.translated(dy=-caption_rise(metrics, style))
    return midpoint.translated(dx=metrics.width / 2.0 + caption_reach(metrics, style))


def rail_label_position(
    rail: tuple[Point, ...],
    stems: tuple[tuple[Point, ...], ...],
    metrics: TextMetrics,
    style: LayoutStyle,
) -> Point:
    """Anchor a net caption above the horizontal run the net reads along.

    A net's caption belongs to its *arrow*, not to its rail: panel-b writes
    ``softmax(QK^T)V`` above the horizontal run that carries Q into the attended
    value, and that run is a source stem, a stretch of rail and a target stem
    drawn as one line. So the anchor is the midpoint of the longest horizontal
    run the net draws -- collinear pieces counted as one -- and a net whose ink
    is purely vertical keeps its rail midpoint, captioned beside it.

    The run is not all the words have to clear. A riser climbing out of either
    end of it -- in panel-b the one carrying K and V up to the merge -- passes
    straight through the band the caption occupies, so the ends the risers claim
    come off the run before the caption is centred on what is left.
    """

    runs: dict[float, list[Segment]] = {}
    risers: list[Segment] = []
    for polyline in (rail, *stems):
        for segment in segments(polyline):
            if segment.length <= _EPSILON:
                continue
            if segment.horizontal:
                runs.setdefault(segment.start.y, []).append(segment)
            else:
                risers.append(segment)
    if runs:
        coordinate = min(
            runs,
            key=lambda value: (-sum(segment.length for segment in runs[value]), value),
        )
        bounds = tuple(
            value
            for segment in runs[coordinate]
            for value in (segment.start.x, segment.end.x)
        )
        # Only a riser that climbs *above* the run reaches the caption written
        # over it; one arriving from below stops at the run.
        above = [
            riser
            for riser in risers
            if min(riser.start.y, riser.end.y) < coordinate - _EPSILON
        ]
        centre = _captioned_centre(
            min(bounds),
            max(bounds),
            coordinate,
            above,
            metrics.width,
            caption_reach(metrics, style),
        )
        return Point(centre, coordinate - caption_rise(metrics, style))
    first, last = rail[0], rail[-1]
    midpoint = Point((first.x + last.x) / 2.0, (first.y + last.y) / 2.0)
    return midpoint.translated(dx=metrics.width / 2.0 + caption_reach(metrics, style))


def _captioned_centre(
    left: float,
    right: float,
    coordinate: float,
    risers: list[Segment],
    width: float,
    clearance: float,
) -> float:
    """Centre a caption on the stretch of run no riser reaches up through.

    A riser that climbs out of the middle of the run cuts it in two -- panel-b's
    K,V riser leaves the merge run a long stretch on one side and a stub on the
    other -- so the caption takes the widest stretch that is left, not the
    midpoint of a run it would be sitting across.
    """

    free = [(left, right)]
    for riser in risers:
        if min(riser.start.y, riser.end.y) >= coordinate - _EPSILON:
            continue  # Drops away below the run; the caption sits above it.
        blocked = (riser.start.x - clearance, riser.start.x + clearance)
        free = [piece for span in free for piece in _without(span, blocked)]
    if not free:
        return (left + right) / 2.0
    start, end = max(free, key=lambda span: span[1] - span[0])
    if end - start >= width:
        return (start + end) / 2.0
    # More words than the widest stretch holds. Centre them on it anyway -- it is
    # still the best place on the run -- but keep the overflow over the run
    # itself rather than out past its ends.
    return min(max((start + end) / 2.0, left + width / 2.0), right - width / 2.0)


_Span = tuple[float, float]


def _without(span: _Span, blocked: _Span) -> tuple[_Span, ...]:
    """``span`` with ``blocked`` cut out of it: nothing, one piece, or two."""

    pieces = ((span[0], min(span[1], blocked[0])), (max(span[0], blocked[1]), span[1]))
    return tuple(piece for piece in pieces if piece[1] - piece[0] > _EPSILON)


