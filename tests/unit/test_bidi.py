"""Right-to-left text: Unicode's bidirectional algorithm, and lines drawn in visual order."""

from __future__ import annotations

from flexo.bidi import base_level, levels, visual_order
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.drawing import Text, read_drawing


def _seen(text: str) -> list[str]:
    level_of = levels(text)
    pieces: list[list] = []
    for character, level in zip(text, level_of, strict=True):
        if pieces and pieces[-1][1] == level:
            pieces[-1][0] += character
        else:
            pieces.append([character, level])
    return [pieces[index][0] for index in visual_order([level for _, level in pieces])]


def test_a_persian_line_with_english_and_numbers_is_ordered_as_read() -> None:
    assert base_level("سلام world") == 1 and base_level("Hello سلام") == 0
    seen = _seen("ترکیب با English words در وسط")
    assert seen[1] == "English words" and seen[0].strip().startswith("در")
    # Persian digits keep their order; they are a left-to-right island.
    assert "۱۲۳" in _seen("اعداد ۱۲۳ و")


def test_a_formula_keeps_its_brackets_in_a_right_to_left_line() -> None:
    text = "مدل f(x) را"
    level_of = levels(text)
    assert level_of[text.index("(")] == level_of[text.index(")")] == level_of[text.index("x")]


def test_a_drawing_sets_a_right_to_left_label_in_visual_pieces() -> None:
    with Figure("fa") as figure:
        figure.block("b", label="ترکیب با English در وسط")
    drawing = read_drawing(compile_figure(figure.spec).document.text)
    line = next(item for item in drawing.walk() if isinstance(item, Text)).lines[0]
    assert line.logical and any(run.rtl for run in line.runs)
    assert not all(run.rtl for run in line.runs)
    xs = [run.x for run in line.runs]
    assert xs == sorted(xs)
