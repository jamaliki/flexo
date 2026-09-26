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
    with pytest.raises(FlexoError, match="contains"):
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


def test_a_run_keeps_a_space_it_begins_with(measurer: TextMeasurer) -> None:
    """The space is part of the advance, so it has to be part of the ink."""

    merged = measurer.measure((TextRun("QK"), TextRun(" module")))
    assert [run.text for line in merged.lines for run in line.runs] == ["QK module"]
    styled = measurer.measure((TextRun("QK", weight=700), TextRun(" module")))
    assert [run.text for line in styled.lines for run in line.runs] == ["QK", " module"]
    assert styled.width > measurer.measure(
        (TextRun("QK", weight=700), TextRun("module"))
    ).width


def test_a_superscript_and_subscript_on_one_letter_stack(measurer: TextMeasurer) -> None:
    """``x^2_B`` sets both scripts at one place, as wide as the wider of them."""

    from flexo.markup import parse_label

    stacked = measurer.measure(parse_label("$x^2_B$")).width
    letter = measurer.measure(parse_label("$x$")).width
    two = measurer.measure(parse_label("$x^2$")).width - letter
    b = measurer.measure(parse_label("$x_B$")).width - letter
    assert stacked == pytest.approx(letter + max(two, b))


def test_common_tex_symbols_are_known() -> None:
    from flexo.markup import parse_label

    label = r"$r \ll d \Rightarrow \argmax_i \lVert x \rVert \equiv \int$"
    text = "".join(run.text for run in parse_label(label))
    assert "\\" not in text and "≪" in text and "⇒" in text and "arg max" in text


def test_a_maths_family_sets_italic_greek_as_tex_does() -> None:
    from flexo.style import TypographyStyle
    from flexo.text import FontStack

    stack = FontStack(TypographyStyle(family="Latin Modern Roman", math_family="Latin Modern Math"))
    pieces = stack.segments("x\u03b1", 400, True)
    assert pieces[0][1] == "x" and pieces[-1][0].family == "Latin Modern Math"
    assert pieces[-1][1] == "\U0001d6fc"  # mathematical italic small alpha
    # Upright text keeps its Greek as written.
    assert stack.segments("\u03b1", 400, False)[0][1] == "\u03b1"
