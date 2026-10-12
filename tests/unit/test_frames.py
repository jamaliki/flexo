"""Frames: a box round shapes wherever they are in the figure, behind them, in front of them
or over them -- which no group can be, as a group holds only what stands together."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import flexo
from flexo import compile_figure
from flexo.frames import LAYERS, around, split
from flexo.serialization import figure_to_document, parse_figure
from flexo.studio.figure_edit import apply
from flexo.studio.figure_parts import catalogue

FRAMED = """
figure: {id: framed, style: paper, width: 183mm}
groups:
- id: root
  role: canvas
  layout: {kind: row, gap: 24}
  children: [left, right, shared, lined, tinted]
- {id: left, role: module, label: Encoder side, layout: {kind: column}, children: [x, enc, attn]}
- {id: right, role: module, label: Decoder side, layout: {kind: column}, children: [dec, mlp, y]}
nodes:
- {id: x, kind: text, label: Input}
- {id: enc, label: Encoder}
- {id: attn, label: Attention}
- {id: dec, label: Decoder}
- {id: mlp, label: MLP}
- {id: y, kind: text, label: Output}
- {id: shared, kind: frame, label: Shared weights, properties: {around: "enc, dec", tone: 2}}
- {id: lined, kind: frame, properties: {around: "attn, mlp", layer: front}}
- {id: tinted, kind: frame, label: Frozen, properties: {around: left, layer: over, tone: 4}}
edges:
- {from: x, to: enc}
- {from: enc, to: attn}
- {from: dec, to: mlp}
- {from: mlp, to: y}
"""


def _figure(text: str = FRAMED, without: tuple[str, ...] = ()) -> flexo.FigureSpec:
    document = yaml.safe_load(text)
    document["nodes"] = [node for node in document["nodes"] if node["id"] not in without]
    for group in document["groups"]:
        group["children"] = [child for child in group["children"] if child not in without]
    return parse_figure(document)


def _box(compilation: flexo.Compilation, name: str) -> flexo.Rect:
    found = [node.bounds for node in compilation.fitted.nodes if node.measured.spec.id == name]
    found += [g.bounds for g in compilation.fitted.groups if g.measured.spec.id == name]
    return found[0]


def test_a_frame_goes_round_shapes_in_different_groups_and_moves_none_of_them() -> None:
    framed = compile_figure(_figure())
    plain = compile_figure(_figure(without=("shared", "lined", "tinted")))
    # Laid out as without its frames: only the page's margin is wider, for them to be on it.
    for one, other in (("enc", "dec"), ("x", "y"), ("attn", "mlp"), ("left", "right")):
        assert _box(framed, one).x - _box(framed, other).x == pytest.approx(
            _box(plain, one).x - _box(plain, other).x
        )
        assert _box(framed, one).y - _box(framed, other).y == pytest.approx(
            _box(plain, one).y - _box(plain, other).y
        )
    laid_out = [node.measured.spec.id for node in framed.fitted.nodes]
    assert laid_out == ["x", "enc", "attn", "dec", "mlp", "y"]
    placed = {frame.spec.id: frame for frame in framed.frames}
    assert list(placed) == ["shared", "lined", "tinted"]
    page = framed.fitted.canvas_size
    for frame in placed.values():
        for name in around(frame.spec):
            inner = _box(framed, name)
            assert frame.bounds.x < inner.x and frame.bounds.right > inner.right
            assert frame.bounds.y < inner.y and frame.bounds.bottom > inner.bottom
        assert frame.bounds.x >= 0 and frame.bounds.y >= 0
        assert frame.bounds.right <= page.width and frame.bounds.bottom <= page.height
    # A title has a band of its own over what the frame goes round.
    assert placed["shared"].bounds.y < placed["lined"].bounds.y - 1 or placed["shared"].label


def test_each_layer_is_drawn_where_it_lies() -> None:
    svg = compile_figure(_figure()).document.text
    drawn = ("shared", "lined", "tinted", "enc", "dec", "y")
    at = {name: svg.index(f'id="{name}"') for name in drawn}
    # Behind its shapes: before the first of them; in front and over: after the last.
    assert at["shared"] < at["enc"] < at["y"] < at["lined"] < at["tinted"]
    # And the part of it inside each module it reaches into, over that module's own fill.
    for module in ("left", "right"):
        piece = svg.index(f'id="shared.in.{module}.body"')
        holder, held = f'id="{module}.container"', f'id="{module}.components"'
        assert svg.index(holder) < piece < svg.index(held)
        assert f'clip-path="url(#shared.in.{module}.clip)"' in svg
    assert 'data-hit-for="shared"' in svg
    body = {
        name: re.search(rf'<rect id="{name}\.body"[^>]*>', svg)[0]
        for name in ("shared", "lined", "tinted")
    }
    assert 'fill="none"' in body["lined"] and 'pointer-events="stroke"' in body["lined"]
    assert 'fill-opacity="0.22"' in body["tinted"] and 'pointer-events="stroke"' in body["tinted"]
    assert "fill-opacity" not in body["shared"] and "pointer-events" not in body["shared"]
    assert ">Shared weights<" in svg and ">Frozen<" in svg
    assert 'data-flexo-kind="frame"' in svg and 'data-flexo-layer="over"' in svg


def test_a_frame_is_kept_in_the_file_as_the_shape_it_is_written_as() -> None:
    figure = _figure()
    layout, frames = split(figure)
    assert [frame.id for frame in frames] == ["shared", "lined", "tinted"]
    assert all(node.kind != "frame" for node in layout.nodes)
    assert "shared" not in layout.group("root").children
    written = {node["id"]: node for node in figure_to_document(figure)["nodes"]}
    assert written["tinted"]["properties"] == {"around": "left", "layer": "over", "tone": 4}
    assert set(LAYERS) == {"behind", "front", "over"}


def test_a_frame_round_what_is_not_there_is_said_and_one_round_nothing_is_not_drawn() -> None:
    document = yaml.safe_load(FRAMED)
    document["nodes"][6]["properties"]["around"] = "enc, gone"
    document["nodes"][7]["properties"]["around"] = "nowhere"
    compiled = compile_figure(parse_figure(document))
    said = [item for item in compiled.measured.diagnostics if item.code == "frame.around.unknown"]
    assert [item.entity_id for item in said] == ["shared", "lined"]
    assert "“gone”" in said[0].message
    assert [frame.spec.id for frame in compiled.frames] == ["shared", "tinted"]
    assert 'id="lined"' not in compiled.document.text


def test_a_framed_figure_is_exported(tmp_path: Path) -> None:
    built = flexo.build(_figure(), tmp_path, stem="framed", formats=("pdf", "png", "portable"))
    assert built is not None
    assert (tmp_path / "framed.pdf").stat().st_size > 1000
    assert any(path.suffix == ".png" for path in tmp_path.iterdir())


# -- the editor's side --


def _nodes(text: str) -> dict[str, dict]:
    return {node["id"]: node for node in yaml.safe_load(text)["nodes"]}


def test_the_editor_puts_a_frame_round_what_is_chosen_and_keeps_it_round_it() -> None:
    text = yaml.safe_dump(yaml.safe_load(FRAMED), sort_keys=False)
    made = apply(text, {"do": "frame", "ids": ["x", "right", "tinted"], "layer": "front"})
    assert made["select"] == ["frame"]
    frame = _nodes(made["text"])["frame"]
    # (Round shapes and groups, in whatever groups: never round another frame.)
    assert frame["kind"] == "frame"
    assert frame["properties"] == {"around": "x, right", "layer": "front"}
    assert yaml.safe_load(made["text"])["groups"][0]["children"][-1] == "frame"
    compile_figure(parse_figure(yaml.safe_load(made["text"])))
    with pytest.raises(Exception, match="frame to go round"):
        apply(text, {"do": "frame", "ids": ["tinted"]})

    # A shape renamed is still in its frames; one deleted leaves them; the last, and they go.
    renamed = apply(text, {"do": "rename", "id": "enc", "to": "encoder"})["text"]
    assert _nodes(renamed)["shared"]["properties"]["around"] == "encoder, dec"
    less = apply(text, {"do": "delete", "ids": ["attn"]})["text"]
    assert _nodes(less)["lined"]["properties"]["around"] == "mlp"
    none = apply(less, {"do": "delete", "ids": ["mlp"]})["text"]
    assert "lined" not in _nodes(none)
    assert "lined" not in yaml.safe_load(none)["groups"][0]["children"]
    # A group ungrouped, its frame goes round what it held.
    apart = apply(text, {"do": "ungroup", "id": "left"})["text"]
    assert _nodes(apart)["tinted"]["properties"]["around"] == "x, enc, attn"


def test_the_editor_offers_a_frame_with_the_groups_and_not_among_the_shapes_to_add() -> None:
    found = catalogue()
    entry = found["groups"][-1]
    assert entry["kind"] == "frame" and entry["frame"] is True and "layout" not in entry
    part = found["parts"]["frame"]
    assert part["wraps"] is True and part["category"] not in found["categories"]
    fields = {field["key"]: field for field in part["fields"]}
    assert fields["properties.layer"]["options"] == ["behind", "front", "over"]
    assert fields["properties.layer"]["labels"]["over"] == "Over (See-Through)"
    assert fields["properties.around"]["more"] is True
