"""A decision's diamond round its words: of itself, as it always was; given a width or a
height, that, and the other way as small as its words let it be; and the size that hugs
its words, which an editor's handles snap to."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation

QUESTION = "Structure comparison"


def _decision(label: str = QUESTION, **options):
    figure = Figure("d")
    with figure, figure.row("r") as row:
        row.decision("d", label=label, **options)
    compiled = compile_figure(figure.spec)
    return compiled, compiled.fitted.node("r.d")


def _fit(compiled) -> tuple[float, float]:
    root = ET.fromstring(compiled.document.text)
    group = next(item for item in root.iter() if item.get("id") == "r.d")
    width, height = (float(value) for value in group.get("data-flexo-fit").split())
    return width, height


def _holds(node) -> bool:
    """Whether every line's corners lie inside the diamond (|x|/a + |y|/b <= 1)."""

    bounds, label = node.bounds, node.measured.label
    step, top = label.height / len(label.lines), -label.height / 2
    for index, line in enumerate(label.lines):
        far = max(abs(top + index * step), abs(top + (index + 1) * step))
        reach = (line.width / 2) / (bounds.width / 2) + (far - 2.0) / (bounds.height / 2)
        if reach > 1.0 + 1e-6:
            return False
    return True


def test_a_decision_given_a_width_is_that_wide_and_as_short_as_its_words_let_it_be() -> None:
    _, own = _decision()
    compiled, wide = _decision(width="200pt")
    assert wide.bounds.width == pytest.approx(200.0)
    assert len(wide.measured.label.lines) == 1, "room for its words on one line"
    assert wide.bounds.height < own.bounds.height
    assert _holds(wide)
    assert not lint_compilation(compiled).errors


def test_a_decision_given_a_height_is_that_tall_and_as_narrow_as_its_words_let_it_be() -> None:
    _, own = _decision()
    _, tall = _decision(height="90pt")
    assert tall.bounds.height == pytest.approx(90.0)
    assert tall.bounds.width < own.bounds.width
    assert _holds(tall)


def test_a_decision_too_small_for_its_words_grows_to_hold_them() -> None:
    _, small = _decision(width="70pt", height="10pt")
    assert small.bounds.width == pytest.approx(70.0)
    assert small.bounds.height > 10.0
    assert _holds(small)


def test_the_size_that_hugs_its_words_is_smaller_and_draws_as_it_says() -> None:
    compiled, own = _decision()
    width, height = _fit(compiled)
    assert width < own.bounds.width and height < own.bounds.height
    # Set to it (as an editor's handle snapped there writes it), it is drawn at it, its
    # words on as few lines as before.
    _, hugging = _decision(width=f"{width:.2f}pt", height=f"{height:.2f}pt")
    assert hugging.bounds.width == pytest.approx(width, abs=0.01)
    assert hugging.bounds.height == pytest.approx(height, abs=0.5)
    assert len(hugging.measured.label.lines) <= len(own.measured.label.lines)
    assert _holds(hugging)


def test_one_line_hugged_is_no_flatter_than_the_snug_aspect() -> None:
    from flexo.components import SNUG_ASPECT

    compiled, _ = _decision("Tubes formed?")
    width, height = _fit(compiled)
    assert width / height <= SNUG_ASPECT + 1e-6


def test_a_box_given_a_size_says_the_size_that_fits_its_words() -> None:
    def block(**options):
        figure = Figure("b")
        with figure, figure.row("r") as row:
            row.block("d", label="Sequence design model", **options)
        return compile_figure(figure.spec)

    natural = block().fitted.node("r.d").bounds
    width, height = _fit(block(width="260pt", height="90pt"))
    assert (width, height) == pytest.approx((natural.width, natural.height))
