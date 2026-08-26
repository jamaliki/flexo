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


def test_an_inherited_weight_measures_the_run_it_will_actually_draw(
    measurer: TextMeasurer,
) -> None:
    """R27: a title is drawn at ``title_weight``, so it is measured there too.

    A run that names no weight inherits whatever its ``<text>`` element declares,
    which is the whole reason it emits no ``font-weight`` of its own -- so the
    weight that band was reserved at has to be that same inherited one.
    """

    runs = (TextRun("Sequence module"),)
    plain = measurer.measure(runs)
    inherited = measurer.measure(runs, weight=600)
    explicit = measurer.measure((TextRun("Sequence module", weight=600),))
    assert inherited.width == pytest.approx(explicit.width)
    assert inherited.width > plain.width
    # A run that named its own weight keeps it: inheritance fills a gap, it does
    # not overrule an author.
    named = (TextRun("Sequence module", weight=300),)
    assert measurer.measure(named, weight=600).width == pytest.approx(
        measurer.measure(named).width
    )
    assert measurer.measure(runs, weight=None).width == pytest.approx(plain.width)


def test_an_inherited_weight_reaches_a_wrapped_line_too(measurer: TextMeasurer) -> None:
    wide = measurer.measure((TextRun("A longer node label"),), max_width=40.0, weight=700)
    assert len(wide.lines) >= 2
    assert all(line.width <= 40.0 for line in wide.lines)
    assert wide.width > measurer.measure((TextRun("A longer node label"),), max_width=40.0).width


def test_a_typed_superscript_measures_as_a_hand_built_one(measurer: TextMeasurer) -> None:
    """R36: ``softmax(QKᵀ)V`` is the label, not an error and not three runs.

    The face has no ``ᵀ``, so the typed spelling used to be a
    ``font.glyph.missing`` diagnostic and the formula could only be written as
    the tuple this compares against. Both spellings now measure to the same
    number, because they become the same runs before anything is shaped -- and
    those are the runs the SVG is painted from.
    """

    typed = measurer.measure((TextRun("softmax(QKᵀ)V"),))
    built = measurer.measure(
        (TextRun("softmax(QK"), TextRun("T", baseline_shift="super"), TextRun(")V"))
    )
    assert typed.width == pytest.approx(built.width)
    assert [(run.text, run.baseline_shift) for run in typed.lines[0].runs] == [
        ("softmax(QK", "normal"),
        ("T", "super"),
        (")V", "normal"),
    ]
    # The raised T is set small, so the formula is narrower than a flat one.
    assert typed.width < measurer.measure((TextRun("softmax(QKT)V"),)).width


def test_a_typed_subscript_measures_as_a_dropped_run(measurer: TextMeasurer) -> None:
    metrics = measurer.measure((TextRun("Dₖ"),))
    assert [(run.text, run.baseline_shift) for run in metrics.lines[0].runs] == [
        ("D", "normal"),
        ("k", "sub"),
    ]
    assert metrics.width == pytest.approx(
        measurer.measure((TextRun("D"), TextRun("k", baseline_shift="sub"))).width
    )


def test_a_subscript_digit_measures_exactly_as_it_always_did(measurer: TextMeasurer) -> None:
    """R36 may not touch ``x₀``: IBM Plex draws that inferior itself.

    The rule is "translate what the face cannot draw", so a label made only of
    characters it can draw comes out of measurement as the single run it went
    in as -- which is what keeps every shipped figure byte-identical.
    """

    metrics = measurer.measure((TextRun("x₀"),))
    assert [(run.text, run.baseline_shift) for run in metrics.lines[0].runs] == [("x₀", "normal")]
    assert metrics.width == pytest.approx(7.08, abs=0.001)


def test_a_typed_shift_survives_wrapping(measurer: TextMeasurer) -> None:
    """Translation happens before the lines are cut, so wrapping keeps it."""

    metrics = measurer.measure((TextRun("Attention scores softmax(QKᵀ)V"),), max_width=60.0)
    runs = [(run.text, run.baseline_shift) for line in metrics.lines for run in line.runs]
    assert len(metrics.lines) >= 2
    assert ("T", "super") in runs
    assert "".join(text for text, _ in runs).replace(" ", "") == "Attentionscoressoftmax(QKT)V"


def test_a_run_keeps_a_space_it_begins_with(measurer: TextMeasurer) -> None:
    """The space is part of the advance, so it has to be part of the ink."""

    merged = measurer.measure((TextRun("QK"), TextRun(" module")))
    assert [run.text for line in merged.lines for run in line.runs] == ["QK module"]
    styled = measurer.measure((TextRun("QK", weight=700), TextRun(" module")))
    assert [run.text for line in styled.lines for run in line.runs] == ["QK", " module"]
    assert styled.width > measurer.measure(
        (TextRun("QK", weight=700), TextRun("module"))
    ).width
