"""Small immutable geometry values and exact-enough intersection predicates."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise


def _require_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("geometry coordinates must be finite")


class Side(StrEnum):
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"

    @property
    def vector(self) -> Point:
        return {
            Side.NORTH: Point(0.0, -1.0),
            Side.EAST: Point(1.0, 0.0),
            Side.SOUTH: Point(0.0, 1.0),
            Side.WEST: Point(-1.0, 0.0),
        }[self]


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def __post_init__(self) -> None:
        _require_finite(self.x, self.y)

    def translated(self, dx: float = 0.0, dy: float = 0.0) -> Point:
        return Point(self.x + dx, self.y + dy)

    def distance_to(self, other: Point) -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True, slots=True)
class Size:
    width: float
    height: float

    def __post_init__(self) -> None:
        _require_finite(self.width, self.height)
        if self.width < 0.0 or self.height < 0.0:
            raise ValueError("size dimensions must be non-negative")


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        _require_finite(self.x, self.y, self.width, self.height)
        if self.width < 0.0 or self.height < 0.0:
            raise ValueError("rectangle dimensions must be non-negative")

    @classmethod
    def from_points(cls, first: Point, second: Point) -> Rect:
        return cls(
            min(first.x, second.x),
            min(first.y, second.y),
            abs(second.x - first.x),
            abs(second.y - first.y),
        )

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    def contains_point(self, point: Point, *, strict: bool = False) -> bool:
        if strict:
            return self.left < point.x < self.right and self.top < point.y < self.bottom
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom

    def contains_rect(self, other: Rect) -> bool:
        return (
            self.left <= other.left
            and self.right >= other.right
            and self.top <= other.top
            and self.bottom >= other.bottom
        )

    def intersects(self, other: Rect, *, strict: bool = True) -> bool:
        if strict:
            return (
                self.left < other.right
                and self.right > other.left
                and self.top < other.bottom
                and self.bottom > other.top
            )
        return (
            self.left <= other.right
            and self.right >= other.left
            and self.top <= other.bottom
            and self.bottom >= other.top
        )

    def inflated(self, amount: float) -> Rect:
        if amount < 0.0 and (-2.0 * amount > min(self.width, self.height)):
            raise ValueError("deflation exceeds rectangle size")
        return Rect(
            self.x - amount,
            self.y - amount,
            self.width + 2.0 * amount,
            self.height + 2.0 * amount,
        )

    def translated(self, dx: float = 0.0, dy: float = 0.0) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def point_on(self, side: Side, offset: float = 0.5) -> Point:
        if not 0.0 <= offset <= 1.0:
            raise ValueError("side offset must lie between 0 and 1")
        if side is Side.NORTH:
            return Point(self.left + self.width * offset, self.top)
        if side is Side.EAST:
            return Point(self.right, self.top + self.height * offset)
        if side is Side.SOUTH:
            return Point(self.left + self.width * offset, self.bottom)
        return Point(self.left, self.top + self.height * offset)

    @classmethod
    def union(cls, rectangles: Iterable[Rect]) -> Rect:
        values = tuple(rectangles)
        if not values:
            raise ValueError("cannot union an empty rectangle collection")
        left = min(rectangle.left for rectangle in values)
        top = min(rectangle.top for rectangle in values)
        right = max(rectangle.right for rectangle in values)
        bottom = max(rectangle.bottom for rectangle in values)
        return cls(left, top, right - left, bottom - top)


@dataclass(frozen=True, slots=True)
class Segment:
    start: Point
    end: Point

    @property
    def horizontal(self) -> bool:
        return math.isclose(self.start.y, self.end.y, abs_tol=1e-9)

    @property
    def vertical(self) -> bool:
        return math.isclose(self.start.x, self.end.x, abs_tol=1e-9)

    @property
    def orthogonal(self) -> bool:
        return self.horizontal or self.vertical

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def bounds(self) -> Rect:
        return Rect.from_points(self.start, self.end)

    def intersects_rect_interior(self, rectangle: Rect) -> bool:
        if not self.orthogonal:
            raise ValueError("rectangle intersection requires an orthogonal segment")
        if self.horizontal:
            low, high = sorted((self.start.x, self.end.x))
            crosses_y = rectangle.top < self.start.y < rectangle.bottom
            return crosses_y and max(low, rectangle.left) < min(high, rectangle.right)
        low, high = sorted((self.start.y, self.end.y))
        return rectangle.left < self.start.x < rectangle.right and max(low, rectangle.top) < min(
            high, rectangle.bottom
        )


def segments(points: tuple[Point, ...]) -> tuple[Segment, ...]:
    return tuple(Segment(start, end) for start, end in pairwise(points))
