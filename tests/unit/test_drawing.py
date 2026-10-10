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
    # A stretch makes the rectangle a path of its mapped outline.
    stretched, _ = list(read_drawing(svg.replace("scale(2)", "scale(2, 3)")).walk())
    assert stretched.kind == "path" and (stretched.width, stretched.height) == (10.0, 15.0)


PLOT = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
 width="200pt" height="100pt" viewBox="0 0 200 100">
 <defs><style type="text/css">*{stroke-linejoin: round; stroke-linecap: butt}</style>
  <clipPath id="axes"><rect x="20" y="10" width="160" height="80"/></clipPath>
  <path id="tick" d="M 0 0 L 0 3.5" style="stroke: #000000; stroke-width: 0.8"/></defs>
 <g id="line"><path d="M 0 50 L 100 50 L 250 50" clip-path="url(#axes)"
   style="fill: none; stroke: #1f77b4; stroke-width: 1.5"/></g>
 <path d="M 0 0 L 200 0 L 200 100 Z" clip-path="url(#axes)"
   style="fill: #ff7f0e; fill-opacity: 0.3"/>
 <use xlink:href="#tick" x="40" y="90" style="stroke: #000000; stroke-width: 0.8"/>
 <text style="font-size: 10px; font-family: 'No Such Family'; text-anchor: middle"
   x="10" y="50" transform="rotate(-90 10 50)">Loss θ</text>
 <g transform="translate(60 95)"><text><tspan x="0" y="0" style="font-size: 10px">L</tspan>
   <tspan x="6" y="2" style="font-size: 7px; font-style: oblique">t</tspan></text></g>
</svg>"""


def test_a_plotting_library_svg_is_read() -> None:
    items = list(read_drawing(PLOT).walk())
    line, area, tick, label, maths = items
    # Clipped to the axes: the line stops at their edges, the area is cut to them.
    assert [s.points[0] for s in line.segments] == [(20.0, 50.0), (100.0, 50.0), (180.0, 50.0)]
    assert line.paint.stroke == "#1f77b4" and line.paint.linejoin == "round"
    assert area.paint.fill_opacity == 0.3
    assert max(p[0] for s in area.segments for p in s.points) == 180.0
    # A <use> draws its target where it is placed.
    assert [s.points[0] for s in tick.segments] == [(40.0, 90.0), (40.0, 93.5)]
    # A turned label keeps its angle; a family that is not installed falls back.
    assert label.angle == -90.0 and label.pivot == (10.0, 50.0)
    assert all(run.face is not None for run in label.lines[0].runs)
    # Absolutely placed tspans are one line; the lowered one is a script.
    runs = maths.lines[0].runs
    assert [r.text for r in runs] == ["L", "t"] and runs[1].italic and runs[1].baseline == 97.0


def test_a_regulation_head_is_read_by_its_name_whatever_the_page_puts_before_its_id() -> None:
    from flexo.builder import Figure

    with Figure("regulated") as figure:
        repressor = figure.block("a", label="cI")
        figure.connect(repressor, figure.block("b", label="cro"), head="inhibition")
    svg = compile_figure(figure.spec).document.text
    # As a slide sets a figure: every id under the slide's own.
    svg = svg.replace('id="', 'id="slide7.body.0.').replace("url(#", "url(#slide7.body.0.")
    lines = [item for item in read_drawing(svg).walk() if isinstance(item, Shape)]
    heads = [head.shape for line in lines for head in line.arrowheads]
    # A bar (it represses) is not an open arrowhead (it activates) to a writer reading it.
    assert heads == ["inhibition"]


def test_a_shape_filled_with_one_picture_is_that_picture_cropped_to_the_shape() -> None:
    from flexo.drawing import Drawing, ink_bounds

    picture = 'href="data:image/png;base64,AAAA"'
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<pattern id="p" patternUnits="userSpaceOnUse" x="-50" y="0" width="200" height="100">'
        f'<image width="200" height="100" {picture}/></pattern>'
        '<g transform="translate(10,0)">'
        '<rect id="kept" x="0" y="10" width="100" height="80" fill="url(#p)"/>'
        '<ellipse id="round" cx="50" cy="50" rx="40" ry="40" fill="url(#p)"/></g>'
        '<clipPath id="c"><rect x="0" y="0" width="60" height="100"/></clipPath>'
        f'<image id="cut" width="100" height="100" clip-path="url(#c)" {picture}/>'
        f'<image id="whole" width="50" height="50" clip-path="url(#c)" {picture}/>'
        "</svg>"
    )
    kept, round_, cut, whole = read_drawing(svg).walk()
    # The whole picture, where the pattern puts it, showing only within the shape.
    assert (kept.id, kept.x, kept.y, kept.width, kept.height) == ("kept", -40.0, 0.0, 200.0, 100.0)
    assert kept.clip == (10.0, 10.0, 110.0, 90.0) and not kept.oval
    assert round_.oval and round_.clip == (20.0, 10.0, 100.0, 90.0)
    # A picture cut by a clip it is drawn in shows only what the clip keeps -- if it cuts it.
    assert cut.clip == (0.0, 0.0, 60.0, 100.0) and whole.clip is None
    assert ink_bounds(Drawing(200.0, 100.0, Group(None, [kept]))) == (10.0, 10.0, 110.0, 90.0)
