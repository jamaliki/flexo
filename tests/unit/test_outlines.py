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
