from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.ir.semantic import TextRun
from flexo.style import TypographyStyle
from flexo.text import TextMeasurer


@pytest.fixture
def measurer() -> TextMeasurer:
    return TextMeasurer(TypographyStyle())


def test_known_text_metrics_are_stable(measurer: TextMeasurer) -> None:
    metrics = measurer.measure((TextRun("Attention"),))
    assert metrics.width == pytest.approx(33.376, abs=0.001)
    assert metrics.height == pytest.approx(9.76)
    assert metrics.baseline == pytest.approx(metrics.ascent)


def test_weight_changes_advance(measurer: TextMeasurer) -> None:
    regular = measurer.measure((TextRun("Projection", weight=400),))
    semibold = measurer.measure((TextRun("Projection", weight=600),))
    assert regular.width != semibold.width


def test_wrapping_preserves_words(measurer: TextMeasurer) -> None:
    metrics = measurer.measure((TextRun("A longer node label"),), max_width=40.0)
    assert len(metrics.lines) >= 2
    assert all(line.width <= 40.0 for line in metrics.lines)


def test_missing_glyph_is_diagnostic(measurer: TextMeasurer) -> None:
    with pytest.raises(FlexoError, match="does not contain"):
        measurer.measure((TextRun("\U0001f9ec"),))
