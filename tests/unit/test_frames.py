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
    """A frame with no title takes no room: only the page's margin is wider, for it to be
    on the page."""

    untitled = yaml.safe_load(FRAMED)
    for node in untitled["nodes"]:
        if node.get("kind") == "frame":
            node.pop("label", None)
    framed = compile_figure(parse_figure(untitled))
    plain = compile_figure(_figure(without=("shared", "lined", "tinted")))
    for one, other in (("enc", "dec"), ("x", "y"), ("attn", "mlp"), ("left", "right")):
        assert _box(framed, one).x - _box(framed, other).x == pytest.approx(
            _box(plain, one).x - _box(plain, other).x
        )
        assert _box(framed, one).y - _box(framed, other).y == pytest.approx(
            _box(plain, one).y - _box(plain, other).y
        )
    laid_out = [node.measured.spec.id for node in framed.fitted.nodes]
    assert laid_out == ["x", "enc", "attn", "dec", "mlp", "y"]
    assert [frame.spec.id for frame in framed.frames] == ["shared", "lined", "tinted"]


def test_a_frame_is_round_what_it_names_and_on_the_page() -> None:
    framed = compile_figure(_figure())
    page = framed.fitted.canvas_size
    for frame in framed.frames:
        for name in around(frame.spec):
            inner = _box(framed, name)
            assert frame.bounds.x < inner.x and frame.bounds.right > inner.right
            assert frame.bounds.y < inner.y and frame.bounds.bottom > inner.bottom
        assert frame.bounds.x >= 0 and frame.bounds.y >= 0
        assert frame.bounds.right <= page.width and frame.bounds.bottom <= page.height


def _title(frame: flexo.frames.PlacedFrame) -> flexo.Rect:
    """Where a frame's title is drawn."""

    return flexo.Rect(
        frame.title_x, frame.bounds.y + frame.inset, frame.label.width, frame.label.height
    )


def _words(compilation: flexo.Compilation) -> dict[str, flexo.Rect]:
    """Everything a frame's title could lie on: each shape, and each group's own title."""

    style = flexo.resolve_style(compilation.measured.semantic.style)
    found = {node.measured.spec.id: node.bounds for node in compilation.fitted.nodes}
    for group in compilation.fitted.groups:
        spec, label = group.measured.spec, group.measured.label
        if spec.label and label.lines:
            inset = spec.layout.authored_padding(style.group_padding)
            found[f"{spec.id} (title)"] = flexo.Rect(
                group.bounds.x + inset.left, group.bounds.y + inset.top, label.width, label.height
            )
    return found


def _lies_on(title: flexo.Rect, compilation: flexo.Compilation) -> list[str]:
    return [
        name
        for name, box in _words(compilation).items()
        if title.x < box.right and box.x < title.right
        and title.y < box.bottom and box.y < title.bottom
    ]


TITLED = """
figure: {id: titled, style: paper, width: 183mm}
groups:
- id: root
  role: canvas
  layout: {kind: row, gap: 24}
  children: [stack, module, cells, first, second, third]
- {id: stack, role: layout, layout: {kind: column}, children: [a, b, c]}
- {id: module, role: module, label: A module with a title, layout: {kind: column}, children: [m, n]}
- {id: cells, role: layout, layout: {kind: grid, columns: 2}, children: [p, q, r, s]}
nodes:
- {id: a, label: Above}
- {id: b, label: Framed}
- {id: c, label: Below}
- {id: m, label: First in a module}
- {id: n, label: Second}
- {id: p, label: P}
- {id: q, label: Q}
- {id: r, label: R}
- {id: s, label: S}
- {id: first, kind: frame, label: Under another shape, properties: {around: b}}
- {id: second, kind: frame, label: Under a title, properties: {around: m}}
- {id: third, kind: frame, label: In a grid, properties: {around: "r, s"}}
edges:
- {from: a, to: b}
- {from: b, to: c}
- {from: p, to: r}
"""


def test_a_frames_title_has_room_kept_for_it_and_lies_on_nothing() -> None:
    """Once a frame took no room at all, and its title lay on whatever was over its shapes:
    the shape above in a column, the title of the module they stand in, the row above in a
    grid."""

    titled = compile_figure(parse_figure(yaml.safe_load(TITLED)))
    assert not titled.measured.diagnostics
    for frame in titled.frames:
        assert _lies_on(_title(frame), titled) == [], frame.spec.id
        # (Within the frame, at its top.)
        assert frame.bounds.x <= frame.title_x
        assert frame.title_x + frame.label.width <= frame.bounds.right + 1e-6
    # The room is made where the title is, and nowhere else: only the gap over the framed
    # shape is deeper than the column's others.
    gap_over = _box(titled, "b").y - _box(titled, "a").bottom
    gap_under = _box(titled, "c").y - _box(titled, "b").bottom
    assert gap_over > gap_under + 10
    rows = _box(titled, "r").y - _box(titled, "p").bottom
    columns = _box(titled, "q").x - _box(titled, "p").right
    assert rows > columns + 10


def _struck(title: flexo.Rect, compilation: flexo.Compilation) -> list[str]:
    """The lines that run through ``title``."""

    return [
        edge.spec.id
        for edge in compilation.routed.edges
        for one, other in zip(edge.centerline, edge.centerline[1:], strict=False)
        if min(one.x, other.x) < title.right and title.x < max(one.x, other.x) + 1e-6
        and min(one.y, other.y) < title.bottom and title.y < max(one.y, other.y)
    ]


def test_a_frames_title_stops_short_of_a_line_that_comes_down_into_the_frame() -> None:
    """A title began over the shape at the frame's top, where the arrow from the shape above
    comes down: it was struck through."""

    titled = compile_figure(parse_figure(yaml.safe_load(TITLED)))
    frames = {frame.spec.id: frame for frame in titled.frames}
    for frame in frames.values():
        assert _struck(_title(frame), titled) == [], frame.spec.id
    # The arrow into "Framed" is down its middle, and the title wider than the shape: the
    # title ends before it.
    first = _title(frames["first"])
    assert first.right < _box(titled, "b").center.x
    # Without the line the same title is not held back: the frame is no wider than it.
    document = yaml.safe_load(TITLED)
    document["edges"] = []
    free = next(
        frame for frame in compile_figure(parse_figure(document)).frames if frame.spec.id == "first"
    )
    assert free.bounds.width < frames["first"].bounds.width
    assert free.bounds.width == pytest.approx(free.label.width + 2 * free.inset)


def test_a_frame_is_centred_on_what_it_holds_and_runs_under_nothing() -> None:
    """A title longer than the shapes once widened the frame to the right alone, off the
    middle of them and under whatever stood beside them."""

    titled = compile_figure(parse_figure(yaml.safe_load(TITLED)))
    shapes = {node.measured.spec.id: node.bounds for node in titled.fitted.nodes}
    for frame in titled.frames:
        held = [shapes[name] for name in around(frame.spec)]
        middle = (min(box.x for box in held) + max(box.right for box in held)) / 2
        assert frame.bounds.center.x == pytest.approx(middle), frame.spec.id
        under = [
            name
            for name, box in shapes.items()
            if name not in around(frame.spec)
            and frame.bounds.x < box.right and box.x < frame.bounds.right
            and frame.bounds.y < box.bottom and box.y < frame.bounds.bottom
        ]
        assert under == [], frame.spec.id
    # (The one wider than its shape is: room was made beside it, in its module.)
    second = next(frame for frame in titled.frames if frame.spec.id == "first")
    assert second.bounds.width > shapes["b"].width + 2 * second.inset + 1


def test_a_title_stands_over_the_shape_at_its_frames_top() -> None:
    """Round shapes at different heights, the title is over the higher: its room is there."""

    framed = compile_figure(_figure())
    shared = next(frame for frame in framed.frames if frame.spec.id == "shared")
    assert _box(framed, "dec").y < _box(framed, "enc").y
    assert shared.title_x == pytest.approx(_box(framed, "dec").x)
    assert _lies_on(_title(shared), framed) == []
    tinted = next(frame for frame in framed.frames if frame.spec.id == "tinted")
    assert _lies_on(_title(tinted), framed) == []


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
