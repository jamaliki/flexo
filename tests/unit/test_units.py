from __future__ import annotations

import math

import pytest

from flexo.diagnostics import FlexoError
from flexo.units import Length, cm, inch, mm, pt, px


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (inch(1), 72.0),
        (mm(25.4), 72.0),
        (cm(2.54), 72.0),
        (px(96), 72.0),
        (pt(72), 72.0),
        (Length.parse("25.4mm"), 72.0),
    ],
)
def test_unit_conversions(length: Length, expected: float) -> None:
    assert math.isclose(length.points, expected)


def test_round_trip() -> None:
    original = mm(180)
    assert math.isclose(mm(original.to("mm")).points, original.points, rel_tol=1e-12)


def test_invalid_length_has_actionable_diagnostic() -> None:
    with pytest.raises(FlexoError, match="Use a number followed by"):
        Length.parse("wide")
