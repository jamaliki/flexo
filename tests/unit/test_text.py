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


def test_code_is_set_in_a_monospace_face_even_when_wrapped() -> None:
    from flexo.markup import parse_label
    from flexo.style import TypographyStyle
    from flexo.text import TextMeasurer, font_stack

    runs = parse_label("Call `fit_in_box(figure)` to fit a figure to its box")
    assert [run.code for run in runs] == [False, True, False]
    metrics = TextMeasurer(TypographyStyle()).measure(runs, max_width=60.0)
    code = [run for line in metrics.lines for run in line.runs if run.code]
    assert code and "fit_in_box" in "".join(run.text for run in code)
    stack = font_stack(TypographyStyle())
    if stack.mono() is not None:
        face, _ = stack.segments("fit", 400, False, code=True)[0]
        assert face.family != stack.families[0][0].family


def test_a_word_wider_than_the_line_breaks_only_when_asked() -> None:
    from flexo.ir.semantic import TextRun
    from flexo.style import TypographyStyle
    from flexo.text import TextMeasurer

    measurer = TextMeasurer(TypographyStyle())
    url = (TextRun("https://github.com/jamaliki/flexo-talk/blob/main/src/compose.py"),)
    kept = measurer.measure(url, max_width=100)
    assert len(kept.lines) == 1 and kept.width > 100
    broken = measurer.measure(url, max_width=100, balance=False, break_words=True)
    assert len(broken.lines) > 1 and broken.width <= 100
    assert "".join(run.text for line in broken.lines for run in line.runs) == url[0].text


def test_coloured_words_are_painted_in_their_colour() -> None:
    from flexo.builder import Figure
    from flexo.compiler import compile_figure
    from flexo.markup import parse_label

    runs = parse_label("Thanks to [Ada]{accent} and [Bob]{#c0392b}")
    assert [(run.text, run.color) for run in runs] == [
        ("Thanks to ", ""), ("Ada", "accent"), (" and ", ""), ("Bob", "#c0392b"),
    ]
    with Figure("coloured") as figure:
        figure.block("b", label="Thanks to [Ada]{accent} and [Bob]{#c0392b}")
    svg = compile_figure(figure.spec).document.text
    assert 'fill="#c0392b"' in svg and 'data-flexo-fill="tone-1-stroke"' in svg


def test_a_word_longer_than_any_line_breaks_quickly_into_pieces_that_fit() -> None:
    import time

    from flexo.units import pt

    measurer = TextMeasurer(TypographyStyle(family="Figtree", size=pt(20)))
    start = time.monotonic()
    word = (TextRun("W" * 20_000),)
    metrics = measurer.measure(word, max_width=400.0, break_words=True, balance=False)
    assert time.monotonic() - start < 10
    assert all(line.width <= 400.0 + 1e-6 for line in metrics.lines)
    assert sum(len(run.text) for line in metrics.lines for run in line.runs) == 20_000


def test_invisible_format_characters_are_never_missing() -> None:
    from flexo.text import font_stack
    from flexo.units import pt

    stack = font_stack(TypographyStyle(family="Figtree", size=pt(20)))
    assert stack.missing("a️ b‍ c⁠", False) == set()


def test_a_placed_svg_may_name_its_weights() -> None:
    from flexo.svg_resources import _css_weight

    weights = [_css_weight(value, 400) for value in ("700", "bold", "normal", "lighter", None, "x")]
    assert weights == [700, 700, 400, 300, 400, 400]


def test_balanced_lines_never_break_a_word_that_fits_whole() -> None:
    from flexo.units import pt

    measurer = TextMeasurer(TypographyStyle(family="Figtree", size=pt(20)))
    words = (TextRun("Column 1 has a longer heading than the rest"),)
    metrics = measurer.measure(words, max_width=120, balance=True, break_words=True)
    lines = ["".join(run.text for run in line.runs) for line in metrics.lines]
    assert "Column" in lines[0] and all("Colum" not in line or "Column" in line for line in lines)


def test_a_tab_is_a_space_and_control_characters_draw_nothing() -> None:
    from flexo.markup import parse_label

    assert parse_label("a\tb\r\nc") == (TextRun("a b\nc"),)


def test_a_fallback_face_serves_its_script_and_a_word_is_set_in_one_face() -> None:
    from flexo.text import font_stack
    from flexo.units import pt

    stack = font_stack(TypographyStyle(family="Figtree", size=pt(20)))
    words = stack.segments("Tiếng Việt", 400, False)
    # Whole words, not letter by letter.
    assert [face.family for face, _ in words] == ["IBM Plex Sans"]
    after = stack.segments("日本語 ✓", 400, False)
    assert after[-1] == (after[-1][0], "✓") and after[-1][0].family == "IBM Plex Sans"
