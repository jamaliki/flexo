"""A line style of its own -- solid, dashed or dotted -- for the outline of every shape, group
and frame, as a line has had one."""

from __future__ import annotations

import re

import pytest
import yaml

import flexo
from flexo import FlexoError, compile_figure
from flexo.components import OUTLINED_NEVER
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.studio.figure_edit import apply
from flexo.studio.figure_parts import catalogue

LINED = """
figure: {id: lined, style: paper}
groups:
- {id: root, role: canvas, layout: {kind: row}, children: [later, store, paper, note, plain]}
- {id: later, label: Later, line: dashed, layout: {kind: column}, children: [a, b]}
nodes:
- {id: a, label: Dashed, line: dashed, properties: {badge: frozen}}
- {id: b, label: Dotted, line: dotted}
- {id: store, kind: database, label: Store, line: dashed}
- {id: paper, kind: document, label: Paper, line: dotted}
- {id: note, kind: text, label: Words alone, line: dashed}
- {id: plain, label: Plain}
- {id: round, kind: frame, label: Optional, line: dotted, properties: {around: "store, paper"}}
"""


def _svg(text: str = LINED, **figure: object) -> str:
    document = yaml.safe_load(text)
    document["figure"].update(figure)
    return compile_figure(parse_figure(document)).document.text


def _tag(svg: str, element_id: str) -> str:
    return re.search(rf'<\w+ id="{re.escape(element_id)}"[^>]*>', svg)[0]


def test_a_shapes_outline_is_dashed_or_dotted_and_its_words_are_not() -> None:
    svg = _svg()
    dashed, dotted = _tag(svg, "a.outline"), _tag(svg, "b.outline")
    assert re.search(r'stroke-dasharray="[\d.]+ [\d.]+"', dashed)
    assert "stroke-linecap" not in dashed
    # Dots: dashes of no length, with round caps.
    assert re.search(r'stroke-dasharray="0 [\d.]+"', dotted) and 'stroke-linecap="round"' in dotted
    # The body is in the dashed group; the words and the badge come after it, not in it.
    body, words, close = (svg.index(mark, svg.index('id="a.outline"')) for mark in (
        'id="a.body"', 'id="a.label"', "</g>"
    ))
    assert body < close < words
    assert svg.index('id="a.badge', close) > close
    # Every piece of a shape drawn in several is: a cylinder's lid with its can.
    assert "stroke-dasharray" in _tag(svg, "store.outline")
    assert 'id="plain.outline"' not in svg


def test_a_kind_with_no_outline_has_nothing_to_dash() -> None:
    svg = _svg()
    assert "text" in OUTLINED_NEVER and 'id="note.outline"' not in svg
    assert "stroke-dasharray" not in _tag(svg, "note")


def test_a_groups_and_a_frames_outline_is_dashed_or_dotted() -> None:
    svg = _svg()
    assert re.search(r'stroke-dasharray="[\d.]+ [\d.]+"', _tag(svg, "later.container"))
    frame = _tag(svg, "round.body")
    assert re.search(r'stroke-dasharray="0 [\d.]+"', frame) and 'stroke-linecap="round"' in frame


@pytest.mark.parametrize("container", ["rule", "band"])
def test_a_group_with_a_line_style_has_an_outline_in_a_theme_that_draws_none(
    container: str,
) -> None:
    theme = next(
        name for name in flexo.THEMES if flexo.resolve_style(name).container_style == container
    )
    box = _tag(_svg(style=theme), "later.container")
    assert "stroke-dasharray" in box and 'stroke="' in box and 'fill="none"' in box


def test_the_line_style_is_kept_in_the_file_only_when_chosen() -> None:
    written = figure_to_document(parse_figure(yaml.safe_load(LINED)))
    lines = {item["id"]: item.get("line") for item in written["nodes"] + written["groups"]}
    assert lines["a"] == "dashed" and lines["later"] == "dashed" and lines["round"] == "dotted"
    assert lines["plain"] is None and lines["root"] is None
    assert parse_figure(written) == parse_figure(yaml.safe_load(LINED))
    wrong = yaml.safe_load(LINED)
    wrong["nodes"][0]["line"] = "wavy"
    with pytest.raises(FlexoError, match="schema"):
        validate_document(wrong)
    with pytest.raises(ValueError, match="unknown line"):
        flexo.NodeSpec("a", "block", line="wavy")  # type: ignore[arg-type]


def test_the_builder_takes_a_line_style_for_a_shape_and_a_group() -> None:
    with (
        flexo.Figure("built") as figure,
        figure.root.group("later", label="Later", line="dotted") as later,
    ):
        later.block("a", label="A", line="dashed")
    spec = figure.spec
    assert spec.node("later.a").line == "dashed" and spec.group("later").line == "dotted"
    svg = compile_figure(spec).document.text
    assert 'id="later.a.outline"' in svg and "stroke-dasharray" in _tag(svg, "later.container")


def test_the_studio_offers_it_on_every_kind_with_an_outline_and_sets_it() -> None:
    offered = catalogue()
    for kind, part in offered["parts"].items():
        has = any(field["key"] == "line" for field in part["fields"])
        assert has == (kind not in OUTLINED_NEVER), kind
    assert {"frame", "block", "database", "cloud"} <= {
        kind for kind in offered["parts"] if kind not in OUTLINED_NEVER
    }
    (of_group,) = (field for field in offered["group_fields"] if field["key"] == "line")
    assert of_group["options"] == ["solid", "dashed", "dotted"]
    # (Where the group draws a frame for it to be the line of.)
    assert of_group["show"] == {"role": ["container", "module"]}
    text = LINED
    for kind, target in (("node", "plain"), ("group", "later"), ("node", "round")):
        action = {"do": "update", "target": {"type": kind, "id": target}}
        text = apply(text, {**action, "values": {"line": "dotted"}})["text"]
    document = yaml.safe_load(text)
    lines = {item["id"]: item.get("line") for item in document["nodes"] + document["groups"]}
    assert lines["plain"] == lines["later"] == lines["round"] == "dotted"


# -- a shape's words: bold, italic, their size, where their lines stand --

WORDED = """
figure: {id: worded, style: paper}
groups:
- {id: root, role: canvas, layout: {kind: row}, children: [head, note, gene, wide, plain]}
nodes:
- {id: head, label: Encoder, properties: {bold: true}}
- {id: note, kind: text, label: "Trained once,\nthen frozen", properties: {align: left, size: 6pt}}
- {id: gene, kind: text, label: lacZ, properties: {italic: true}}
- {id: wide, label: "Right\nside", width: 30mm, properties: {align: right, size: 10}}
- {id: plain, label: Plain}
"""


def test_a_shapes_words_take_a_weight_a_slant_a_size_and_a_side_of_their_own() -> None:
    """A figure's words were all set alike; a heading in bold, a gene's name in italic, a
    note set small against its left edge had no way to be said."""

    compiled = compile_figure(parse_figure(yaml.safe_load(WORDED)))
    svg = compiled.document.text
    assert 'font-weight="700"' in _tag(svg, "head.label") or re.search(
        r'<text id="head.label"[^>]*>\s*<tspan[^>]*font-weight="700"', svg
    )
    assert re.search(r'<text id="gene.label"[^>]*>.*?font-style="italic"', svg, re.DOTALL)
    plain = _tag(svg, "plain.label")
    assert "font-weight" not in plain and "italic" not in plain
    # A size of its own is what it is measured at, so its shape is the size for it.
    assert 'font-size="6"' in _tag(svg, "note.label")
    assert 'font-size="10"' in _tag(svg, "wide.label") and 'font-size="8"' in plain
    sizes = {
        node.measured.spec.id: node.measured.label.line_height for node in compiled.fitted.nodes
    }
    assert sizes["note"] < sizes["plain"] < sizes["wide"]
    # Its lines at the side it asks for, in from the shape's edge; else in its middle.
    boxes = {node.measured.spec.id: node.bounds for node in compiled.fitted.nodes}
    left, right, middle = (_tag(svg, f"{name}.label") for name in ("note", "wide", "plain"))
    assert 'text-anchor="start"' in left and 'text-anchor="end"' in right
    assert 'text-anchor="middle"' in middle
    at = lambda tag: float(re.search(r'\bx="([\d.]+)"', tag)[1])  # noqa: E731
    assert boxes["note"].x < at(left) < boxes["note"].center.x
    assert boxes["wide"].center.x < at(right) < boxes["wide"].right
    assert at(middle) == pytest.approx(boxes["plain"].center.x, abs=0.01)


def test_the_studio_says_which_kinds_take_text_styling() -> None:
    parts = catalogue()["parts"]
    assert parts["block"]["styled"] and parts["text"]["styled"] and parts["database"]["styled"]
    assert not parts["structure"]["styled"] and not parts["frame"]["styled"]
    text = apply(WORDED, {"do": "update", "targets": [{"type": "node", "id": "plain"},
                                                      {"type": "node", "id": "head"}],
                          "values": {"properties.italic": True, "properties.bold": None}})["text"]
    nodes = {node["id"]: node for node in yaml.safe_load(text)["nodes"]}
    assert nodes["plain"]["properties"] == {"italic": True}
    assert nodes["head"].get("properties") == {"italic": True}
