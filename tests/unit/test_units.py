from __future__ import annotations

import math

import pytest

from flexo.diagnostics import FlexoError
from flexo.units import CellSpan, Length, cm, inch, mm, parse_extent, pt, px


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


def test_parse_extent_reads_lengths_and_cell_spans() -> None:
    assert parse_extent("12pt") == Length(12.0)
    assert parse_extent(9) == Length(9.0)
    assert parse_extent("cells:3") == CellSpan(3)
    assert parse_extent(" cells : 12 ") == CellSpan(12)
    assert parse_extent(CellSpan(2)) == CellSpan(2)
    assert str(CellSpan(5)) == "cells:5"


def test_cell_span_needs_at_least_one_cell() -> None:
    with pytest.raises(ValueError, match="at least one cell"):
        CellSpan(0)


def test_a_cell_span_is_not_a_length() -> None:
    with pytest.raises(FlexoError, match="Invalid length"):
        Length.parse("cells:3")
