"""Text in a figure set to a width of its own: where its words wrap, as an editor's side
handles set it -- and the width it takes of itself, which they snap to."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.themes import figure_style

WORDS = "Checked twice by two people, independently, in the lab"


def _text(**options: object):
    with Figure("t") as figure, figure.row("r") as row:
        row.text("a", WORDS, **options)
    return compile_figure(figure.spec)


def _lines(compiled) -> list[str]:
    label = compiled.fitted.node("r.a").measured.label
    return ["".join(run.text for run in line.runs) for line in label.lines]


def _group(compiled) -> ET.Element:
    root = ET.fromstring(compiled.document.text)
    return next(item for item in root.iter() if item.get("id") == "r.a")


def test_text_given_the_width_it_has_of_itself_wraps_as_it_does_without_one() -> None:
    natural = _text()
    width = natural.fitted.node("r.a").bounds.width
    given = _text(width=f"{width}pt")
    assert _lines(given) == _lines(natural)
    assert given.fitted.node("r.a").bounds.width == pytest.approx(width)


def test_text_given_a_narrower_width_wraps_its_words_inside_it() -> None:
    compiled = _text(width="60pt")
    node = compiled.fitted.node("r.a")
    style = figure_style(compiled.measured.semantic)
    assert len(_lines(compiled)) > len(_lines(_text()))
    assert node.bounds.width == pytest.approx(60.0)
    assert node.measured.label.width <= 60.0 - style.padding_y.points + 1e-6


def test_text_says_where_its_box_is_and_the_width_it_takes_of_itself() -> None:
    natural = _text().fitted.node("r.a").bounds
    compiled = _text(width="60pt")
    group = _group(compiled)
    style = figure_style(compiled.measured.semantic)
    box = [float(value) for value in group.get("data-flexo-box", "").split()]
    bounds = compiled.fitted.node("r.a").bounds
    assert box == pytest.approx([bounds.x, bounds.y, bounds.width, bounds.height], abs=0.01)
    fit = [float(value) for value in group.get("data-flexo-fit", "").split()]
    assert fit == pytest.approx([natural.width, natural.height], abs=0.01)
    assert float(group.get("data-flexo-inset", "nan")) == pytest.approx(style.padding_y.points)
