"""Physical units. Internal geometry is always expressed in points."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError

POINTS_PER_INCH = 72.0
MILLIMETRES_PER_INCH = 25.4
CSS_PIXELS_PER_INCH = 96.0

_UNIT_FACTORS = {
    "pt": 1.0,
    "mm": POINTS_PER_INCH / MILLIMETRES_PER_INCH,
    "cm": 10.0 * POINTS_PER_INCH / MILLIMETRES_PER_INCH,
    "in": POINTS_PER_INCH,
    "px": POINTS_PER_INCH / CSS_PIXELS_PER_INCH,
}
_LENGTH_PATTERN = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(pt|mm|cm|in|px)\s*$"
)


@dataclass(frozen=True, slots=True, order=True)
class Length:
    """A finite physical length stored in PostScript points."""

    points: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.points):
            raise ValueError("length must be finite")

    @classmethod
    def parse(cls, value: Length | str | int | float) -> Length:
        if isinstance(value, cls):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return cls(float(value))
        if not isinstance(value, str):
            raise FlexoError(
                Diagnostic("length.type", f"Expected a length, received {type(value).__name__}.")
            )
        match = _LENGTH_PATTERN.match(value)
        if match is None:
            raise FlexoError(
                Diagnostic(
                    "length.syntax",
                    f'Invalid length "{value}".',
                    hint='Use a number followed by pt, mm, cm, in, or px, such as "12mm".',
                )
            )
        amount, unit = match.groups()
        return cls(float(amount) * _UNIT_FACTORS[unit])

    def to(self, unit: str) -> float:
        try:
            factor = _UNIT_FACTORS[unit]
        except KeyError as exc:
            raise ValueError(f"unknown unit: {unit}") from exc
        return self.points / factor

    def __add__(self, other: Length) -> Length:
        return Length(self.points + other.points)

    def __sub__(self, other: Length) -> Length:
        return Length(self.points - other.points)

    def __mul__(self, scalar: float) -> Length:
        return Length(self.points * scalar)

    def __truediv__(self, scalar: float) -> Length:
        return Length(self.points / scalar)


def pt(value: float) -> Length:
    return Length(float(value))


def mm(value: float) -> Length:
    return Length(float(value) * _UNIT_FACTORS["mm"])


def cm(value: float) -> Length:
    return Length(float(value) * _UNIT_FACTORS["cm"])


def inch(value: float) -> Length:
    return Length(float(value) * _UNIT_FACTORS["in"])


def px(value: float) -> Length:
    return Length(float(value) * _UNIT_FACTORS["px"])
