from __future__ import annotations

import pytest

from flexo.geometry import Point, Rect, Segment, Side
from flexo.style import STYLES
from flexo.svg import polyline_path, rounded_polyline_path


def test_rect_side_points() -> None:
    rectangle = Rect(10, 20, 40, 30)
    assert rectangle.point_on(Side.NORTH) == Point(30, 20)
    assert rectangle.point_on(Side.EAST, 0.25) == Point(50, 27.5)


def test_touching_rectangles_do_not_strictly_intersect() -> None:
    first = Rect(0, 0, 10, 10)
    second = Rect(10, 0, 10, 10)
    assert not first.intersects(second)
    assert first.intersects(second, strict=False)


def test_segment_intersects_only_rectangle_interior() -> None:
    rectangle = Rect(10, 10, 20, 20)
    assert Segment(Point(0, 20), Point(40, 20)).intersects_rect_interior(rectangle)
    assert not Segment(Point(0, 10), Point(40, 10)).intersects_rect_interior(rectangle)


@pytest.mark.parametrize(
    ("radius", "expected"),
    [
        (0.0, "M 0 0 H 10 V 10 H 20"),
        (4.0, "M 0 0 L 6 0 Q 10 0 10 4 L 10 6 Q 10 10 14 10 L 20 10"),
    ],
)
def test_rounded_polyline_radius_goldens(radius: float, expected: str) -> None:
    points = (Point(0, 0), Point(10, 0), Point(10, 10), Point(20, 10))
    assert rounded_polyline_path(points, radius) == expected
    if radius == 0.0:
        assert rounded_polyline_path(points, radius) == polyline_path(points)


def test_rounded_polyline_halves_the_fillet_on_a_short_middle_segment() -> None:
    """R21: a 6 pt elbow on a 7 pt jog shrinks to 3.5 pt rather than overshooting.

    The two fillets meet exactly at the middle of the short segment -- no
    straight remainder between them, and no arc reaching past a corner.
    """

    radius = STYLES["paper"].elbow_radius.points
    points = (Point(0, 0), Point(20, 0), Point(20, 7), Point(40, 7))
    assert radius == 6.0
    assert rounded_polyline_path(points, radius) == (
        "M 0 0 L 16.5 0 Q 20 0 20 3.5 Q 20 7 23.5 7 L 40 7"
    )


def test_rounded_polyline_keeps_endpoints_when_every_segment_is_short() -> None:
    """R21: a stair of 4 pt treads still starts and ends exactly on its ports."""

    points = (Point(0, 0), Point(4, 0), Point(4, 4), Point(8, 4), Point(8, 8))
    # Every fillet is half a tread, so consecutive arcs join without a straight
    # remainder and neither end of the polyline moves.
    assert rounded_polyline_path(points, STYLES["paper"].elbow_radius.points) == (
        "M 0 0 L 2 0 Q 4 0 4 2 Q 4 4 6 4 Q 8 4 8 6 L 8 8"
    )


def test_rounded_polyline_clamps_large_radius_without_self_intersection() -> None:
    points = (Point(0, 0), Point(8, 0), Point(8, 4), Point(16, 4))
    assert rounded_polyline_path(points, 100.0) == (
        "M 0 0 L 6 0 Q 8 0 8 2 Q 8 4 10 4 L 16 4"
    )
