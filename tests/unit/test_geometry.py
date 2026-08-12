from __future__ import annotations

from flexo.geometry import Point, Rect, Segment, Side


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
