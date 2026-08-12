"""Route cleanup and utilities for separated parallel paths."""

from __future__ import annotations

from flexo.geometry import Point


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
