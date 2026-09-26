"""Reading a compiled figure back as drawing primitives, for writers of other formats."""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo.compiler import compile_figure
from flexo.drawing import Group, Shape, Text, read_drawing
from flexo.svg import local_name
from flexo.text import TextMeasurer
from flexo.themes import resolve_style


def _literature() -> dict:
    path = Path(__file__).resolve().parents[2] / "examples" / "literature.py"
    spec = importlib.util.spec_from_file_location("literature", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIGURES


FIGURES = _literature()


@pytest.mark.parametrize("theme", ["paper", "sketch", "tikz"])
@pytest.mark.parametrize("name", ["dqn", "gpt-block", "lda", "lstm", "code-review"])
def test_every_text_and_every_arrowhead_is_read(name: str, theme: str) -> None:
    svg = compile_figure(FIGURES[name](theme).spec).document.text
    drawing = read_drawing(svg)
    items = list(drawing.walk())
    root = ET.fromstring(svg)
    texts = [item for item in root.iter() if local_name(item.tag) == "text"]
    assert len([item for item in items if isinstance(item, Text)]) == len(texts)
    marked = [item for item in root.iter() if item.get("marker-end") or item.get("marker-start")]
    heads = sum(len(item.arrowheads) for item in items if isinstance(item, Shape))
    assert heads == sum(bool(m.get("marker-end")) + bool(m.get("marker-start")) for m in marked)


def test_a_centred_label_is_centred_and_measured_as_flexo_measured_it() -> None:
    compiled = compile_figure(FIGURES["dqn"]("paper").spec)
    drawing = read_drawing(compiled.document.text)
    label = next(
        item for item in drawing.walk() if isinstance(item, Text) and item.id == "agent.env.label"
    )
    (line,) = label.lines
    assert (line.left + line.right) / 2.0 == pytest.approx(label.x, abs=1e-6)
    node = compiled.fitted.node("agent.env")
    measured = TextMeasurer(resolve_style("paper").typography).line_width(
        node.measured.label.lines[0].runs, None
    )
    assert line.right - line.left == pytest.approx(measured, rel=1e-3)
    assert label.simple


def test_curves_and_arcs_become_cubics_and_groups_keep_their_ids() -> None:
    drawing = read_drawing(compile_figure(FIGURES["dqn"]("paper").spec).document.text)
    body = next(i for i in drawing.walk() if isinstance(i, Shape) and i.id == "agent.env.body")
    assert body.kind == "rect" and body.radius > 0
    assert {segment.kind for segment in body.segments} >= {"M", "L", "C", "Z"}
    ids = set()

    def collect(group: Group) -> None:
        ids.add(group.id)
        for item in group.items:
            if isinstance(item, Group):
                collect(item)

    collect(drawing.root)
    assert "agent.env" in ids


def test_a_transform_moves_and_scales_everything_under_it() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g transform="translate(10,20) scale(2)">'
        '<rect x="1" y="1" width="5" height="5" rx="1" fill="#f00" stroke="#000" '
        'stroke-width="1" stroke-dasharray="2 1"/>'
        '<text x="3" y="4" font-family="Liberation Sans" font-size="8">Hi</text>'
        "</g></svg>"
    )
    rect, text = list(read_drawing(svg).walk())
    assert (rect.x, rect.y, rect.width, rect.radius) == (12.0, 22.0, 10.0, 2.0)
    assert rect.paint.stroke_width == 2.0 and rect.paint.dash == (4.0, 2.0)
    assert text.size == 16.0 and text.lines[0].baseline == 28.0 and text.lines[0].runs[0].x == 16.0
    with pytest.raises(ValueError, match="uniform scale"):
        read_drawing(svg.replace("scale(2)", "scale(2, 3)"))
