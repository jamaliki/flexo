"""Frames: a box round shapes wherever they are in the figure, behind them, in front of them
or over them -- which no group can be, as a group holds only what stands together."""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

import flexo
from flexo import compile_figure
from flexo.frames import LAYERS, around, split, title_side_of
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


SIDES = ("left", "right", "bottom-left", "bottom-right")


def _sided(text: str, side: str | None, **only: str) -> flexo.Compilation:
    """``text`` with the title of each of its frames (or of ``only``, by id) at ``side``."""

    document = yaml.safe_load(text)
    for node in document["nodes"]:
        where = only.get(node["id"], side)
        if node.get("kind") == "frame" and where is not None:
            node["properties"]["title_side"] = where
    return compile_figure(parse_figure(document))


@pytest.mark.parametrize("side", SIDES)
def test_a_frames_title_stands_at_the_corner_its_title_side_names(side: str) -> None:
    """A title stood at the frame's top left alone: over a shape whose line goes up from
    its top, there was nowhere for it clear of the line. It stands at any corner now, with
    all it has at the top left: room of its own, clear of every line, the frame centred."""

    titled = _sided(TITLED, side)
    assert not titled.measured.diagnostics
    shapes = {node.measured.spec.id: node.bounds for node in titled.fitted.nodes}
    below, right = side.startswith("bottom"), side.endswith("right")
    for frame in titled.frames:
        assert frame.title_side == side == title_side_of(frame.spec)
        title, held = frame.title, [shapes[name] for name in around(frame.spec)]
        assert _lies_on(title, titled) == [], frame.spec.id
        assert _struck(title, titled) == [], frame.spec.id
        # In its band, within the frame: under the shapes at the bottom, over them at the top.
        assert frame.bounds.x <= title.x and title.right <= frame.bounds.right + 1e-6
        if below:
            assert title.y > max(box.bottom for box in held)
            assert title.bottom == pytest.approx(frame.bounds.bottom - frame.inset)
            assert frame.bounds.y == pytest.approx(min(box.y for box in held) - frame.inset)
        else:
            assert title.bottom < min(box.y for box in held)
            assert title.y == pytest.approx(frame.bounds.y + frame.inset)
            assert frame.bounds.bottom == pytest.approx(
                max(box.bottom for box in held) + frame.inset
            )
        # Still centred on what it holds, and round it.
        middle = (min(box.x for box in held) + max(box.right for box in held)) / 2
        assert frame.bounds.center.x == pytest.approx(middle), frame.spec.id
        assert all(frame.bounds.x < box.x and box.right < frame.bounds.right for box in held)
    frames = {frame.spec.id: frame for frame in titled.frames}
    # With no line through its band it is at the frame's corner, the frame's inset from it;
    # at the right its lines end together there.
    free = frames["second"]
    if right:
        assert free.title.right == pytest.approx(free.bounds.right - free.inset)
    else:
        assert free.title.x == pytest.approx(free.bounds.x + free.inset)
    svg = titled.document.text
    drawn = re.search(r'<text id="second\.label"[^>]*>', svg)[0]
    assert ('text-anchor="end"' in drawn) is right
    at = float(re.search(r' x="([^"]+)"', drawn)[1])
    assert at == pytest.approx(free.title.right if right else free.title.x, abs=1e-3)
    baseline = float(re.search(r' y="([^"]+)"', drawn)[1])
    assert baseline == pytest.approx(free.title.y + free.label.baseline, abs=1e-3)


def test_a_title_at_the_right_or_the_bottom_stops_short_of_a_line_through_its_band() -> None:
    """The arrow into "Framed" comes down its middle, and the one out of it goes down from
    there: a title wider than the shape keeps to its own side of whichever is in its band,
    the frame the wider for it -- past the line, at the right."""

    middle = {side: _box(_sided(TITLED, side), "b").center.x for side in SIDES}
    first = {
        side: next(f for f in _sided(TITLED, side).frames if f.spec.id == "first")
        for side in SIDES
    }
    assert first["left"].title.right < middle["left"]
    assert first["right"].title.x > middle["right"]
    assert first["bottom-left"].title.right < middle["bottom-left"]
    assert first["bottom-right"].title.x > middle["bottom-right"]
    # Without the lines none is held back: the frame is no wider than its title.
    document = yaml.safe_load(TITLED)
    document["edges"] = []
    for side in SIDES:
        free = next(
            frame
            for frame in _sided(yaml.safe_dump(document), side).frames
            if frame.spec.id == "first"
        )
        assert free.bounds.width < first[side].bounds.width, side
        assert free.bounds.width == pytest.approx(free.label.width + 2 * free.inset), side


def test_a_title_at_the_bottom_has_its_room_under_the_shapes_and_moves_none_above() -> None:
    """Its band is under the shape at the frame's bottom: what is below makes way."""

    # (On a page wide enough for each, so that all are spaced alike.)
    document = yaml.safe_load(TITLED)
    document["figure"]["width"] = "300mm"
    wide = yaml.safe_dump(document, sort_keys=False)
    for node in document["nodes"]:
        node.pop("label", None) if node.get("kind") == "frame" else None
    plain = compile_figure(parse_figure(document))
    top, bottom = _sided(wide, None), _sided(wide, "bottom-left")

    def gap(drawn: flexo.Compilation, over: str, under: str) -> float:
        return _box(drawn, under).y - _box(drawn, over).bottom

    def inside(drawn: flexo.Compilation, group: str, shape: str) -> tuple[float, float]:
        """How far a shape is from its group's top, and from its bottom."""

        return (
            _box(drawn, shape).y - _box(drawn, group).y,
            _box(drawn, group).bottom - _box(drawn, shape).bottom,
        )

    # In a column the gap under the framed shape is the deeper one now; the gap over it is
    # as it is with no title at all.
    assert gap(top, "a", "b") > gap(plain, "a", "b") + 10
    assert gap(top, "b", "c") == pytest.approx(gap(plain, "b", "c"))
    assert gap(bottom, "b", "c") > gap(plain, "b", "c") + 10
    assert gap(bottom, "a", "b") == pytest.approx(gap(plain, "a", "b"))
    # In a module, under its first shape: the second is further down, the first no lower
    # under the module's own title.
    assert gap(bottom, "m", "n") > gap(plain, "m", "n") + 10
    assert inside(bottom, "module", "m")[0] == pytest.approx(inside(plain, "module", "m")[0])
    assert inside(top, "module", "m")[0] > inside(plain, "module", "m")[0] + 10
    # Round a grid's last row, under the grid: its rows are no further apart for it.
    assert gap(bottom, "p", "r") == pytest.approx(gap(plain, "p", "r"))
    assert gap(top, "p", "r") > gap(plain, "p", "r") + 10
    assert inside(bottom, "cells", "r")[1] > inside(plain, "cells", "r")[1] + 10
    # Round its first row, in the gap under that row -- as over its last, for a title on top.
    document = yaml.safe_load(wide)
    document["nodes"][-1]["properties"] = {"around": "p, q", "title_side": "bottom-right"}
    under = compile_figure(parse_figure(document))
    assert gap(under, "p", "r") == pytest.approx(gap(top, "p", "r"))
    assert inside(under, "cells", "p")[0] == pytest.approx(inside(plain, "cells", "p")[0])
    third = next(frame for frame in under.frames if frame.spec.id == "third")
    assert _lies_on(third.title, under) == [] and _struck(third.title, under) == []


def test_a_title_stands_with_the_shape_at_the_corner_it_is_at() -> None:
    """Round shapes at different heights the title is over the higher, or under the lower:
    its room is there. At the right it ends with that shape, as at the left it starts
    with it."""

    for side, shape, edge in (
        ("left", "dec", "x"),
        ("right", "dec", "right"),
        ("bottom-left", "enc", "x"),
        ("bottom-right", "enc", "right"),
    ):
        framed = _sided(FRAMED, None, shared=side)
        shared = next(frame for frame in framed.frames if frame.spec.id == "shared")
        assert _box(framed, "dec").y < _box(framed, "enc").y
        assert _box(framed, "dec").bottom < _box(framed, "enc").bottom
        mine, title = _box(framed, shape), shared.title
        if side.startswith("bottom"):
            assert title.y > mine.bottom
        else:
            assert title.bottom < mine.y
        if side in {"left", "bottom-right"}:
            # (The shape there starts, or ends, further in than the frame does.)
            assert getattr(title, edge) == pytest.approx(getattr(mine, edge)), side
        assert _lies_on(title, framed) == [], side


def test_the_top_left_is_where_a_title_stands_unless_another_corner_is_named() -> None:
    """``left`` written is the frame as it is drawn with nothing written; and a frame with no
    title is the same at every corner."""

    for text in (FRAMED, TITLED):
        assert _sided(text, "left").document.text == _sided(text, None).document.text
    untitled = yaml.safe_load(FRAMED)
    for node in untitled["nodes"]:
        node.pop("label", None) if node.get("kind") == "frame" else None
    bare = yaml.safe_dump(untitled, sort_keys=False)
    for side in SIDES:
        sided = _sided(bare, side)
        assert sided.document.text == _sided(bare, None).document.text, side
        assert all(frame.title is None for frame in sided.frames)


def test_a_title_side_that_is_none_of_the_four_is_said_and_the_title_is_at_the_top_left() -> None:
    plain = _sided(TITLED, None)
    for written in ("top", "bottom", "Centre", 3):
        wrong = _sided(TITLED, None, first=written)
        said = [d for d in wrong.measured.diagnostics if d.code == "frame.title-side.unknown"]
        assert [item.entity_id for item in said] == ["first"]
        assert f"“{str(written).lower()}”" in said[0].message
        assert all(side in said[0].hint for side in SIDES)
        assert wrong.document.text == plain.document.text
    # (As it is written by hand: in any case, with room round it.)
    assert not _sided(TITLED, " Bottom-Right ").measured.diagnostics
    assert _sided(TITLED, " Bottom-Right ").document.text == (
        _sided(TITLED, "bottom-right").document.text
    )


def test_a_title_at_another_corner_keeps_its_frames_layer_colours_and_line() -> None:
    document = yaml.safe_load(FRAMED)
    document["nodes"][6]["line"] = "dashed"
    document["nodes"][6]["properties"] |= {"paint-label": "#aa0000"}
    document["figure"]["dim"] = ["left"]
    text = yaml.safe_dump(document, sort_keys=False)
    top, bottom = _sided(text, None).document.text, _sided(text, "bottom-right").document.text

    def drawn(svg: str, name: str, what: str) -> str:
        found = re.search(rf'<{what} id="{re.escape(name)}"[^>]*>', svg)[0]
        # (All but where it is: its place, and which end of it is there.)
        return re.sub(r' (x|y|width|height|text-anchor)="[^"]*"', "", found)

    for name in ("shared", "lined", "tinted"):
        assert drawn(top, f"{name}.body", "rect") == drawn(bottom, f"{name}.body", "rect")
        assert drawn(top, name, "g") == drawn(bottom, name, "g")
    for name in ("shared.label", "tinted.label", "shared.in.left.label", "shared.in.right.label"):
        assert drawn(top, name, "text") == drawn(bottom, name, "text")
    assert 'fill="#aa0000"' in drawn(bottom, "shared.label", "text")
    assert "stroke-dasharray" in drawn(bottom, "shared.body", "rect")
    # Behind its shapes still, and what is dimmed is dimmed still: the frame round it too.
    order = [bottom.index(f'id="{name}"') for name in ("shared", "enc", "y", "lined", "tinted")]
    assert order == sorted(order)
    for svg in (top, bottom):
        assert re.search(r'<g id="tinted"[^>]*data-flexo-show="dimmed"', svg)


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


def test_the_part_of_a_frame_in_a_group_shows_only_there_in_every_output() -> None:
    """The part drawn again over a module's fill is the whole frame, clipped to the module:
    unclipped, the part over the right module would cover the left one's shapes."""

    import zlib

    from flexo.export import rasterise
    from flexo.pdf import _n, _png_decode, pdf_bytes
    from flexo.portable import portable_svg
    from flexo.svg import number

    compiled = compile_figure(_figure())
    svg = compiled.document.text
    portable = portable_svg(svg)
    streams = re.findall(rb"stream\n(.*?)\nendstream", pdf_bytes(svg), re.S)
    drawn = b"".join(zlib.decompress(found) for found in streams if found[:2] == b"x\x9c")
    for module in ("left", "right"):
        box = _box(compiled, module)
        edges = (box.x, box.y, box.width, box.height)
        rect = 'x="{}" y="{}" width="{}" height="{}"'.format(*(number(v) for v in edges))
        assert re.search(
            rf'<clipPath id="(\w+)">\s*<rect {re.escape(rect)} />\s*</clipPath>\s*'
            rf'<g clip-path="url\(#\1\)">\s*<rect [^>]*id="shared\.in\.{module}\.body"',
            portable,
        )
        assert ("q " + " ".join(_n(v) for v in edges) + " re W n").encode() in drawn
    # Drawn from the portable SVG, the left module is as the SVG draws it: its input, its
    # encoder and its title are not under the frame's part in the right module.
    left = _box(compiled, "left")
    across, _, channels, written = _png_decode(rasterise(svg, dpi=72))
    *_, outlined = _png_decode(rasterise(portable, dpi=72))
    spots = [
        (y * across + x) * channels
        for y in range(int(left.y), int(left.y + left.height))
        for x in range(int(left.x), int(left.x + left.width))
    ]
    unlike = [
        at for at in spots
        if any(abs(written[at + c] - outlined[at + c]) > 40 for c in range(channels))
    ]
    assert len(unlike) < len(spots) // 200


# -- lines that end at a frame --


def _lined(text: str, *edges: dict, **settings: object) -> flexo.Compilation:
    """``text`` with more lines, as a figure file writes them (and settings of the figure)."""

    document = yaml.safe_load(text)
    document["edges"] = [*document.get("edges", []), *edges]
    document["figure"] |= settings
    return compile_figure(parse_figure(document))


def _line(compilation: flexo.Compilation, source: str, target: str) -> flexo.ir.RoutedEdge:
    return next(
        edge
        for edge in compilation.routed.edges
        if (edge.spec.source.node_id, edge.spec.target.node_id) == (source, target)
    )


def _frame(compilation: flexo.Compilation, name: str) -> flexo.frames.PlacedFrame:
    return next(frame for frame in compilation.frames if frame.spec.id == name)


def _side_met(box: flexo.Rect, point: flexo.Point) -> str | None:
    """The side of ``box`` that ``point`` is on, if it is on its outline."""

    across = box.x - 1e-6 <= point.x <= box.right + 1e-6
    down = box.y - 1e-6 <= point.y <= box.bottom + 1e-6
    for side, at, on in (
        ("north", box.y, point.y), ("south", box.bottom, point.y),
        ("west", box.x, point.x), ("east", box.right, point.x),
    ):
        if abs(at - on) < 1e-6 and (across if side in {"north", "south"} else down):
            return side
    return None


def _enters(line: tuple[flexo.Point, ...], box: flexo.Rect) -> bool:
    """Whether a line runs inside ``box`` anywhere along it (not merely to its outline)."""

    inner = box.inflated(-0.5)
    for one, other in pairwise(line):
        for share in (0.0, 0.25, 0.5, 0.75, 1.0):
            at = flexo.Point(one.x + (other.x - one.x) * share, one.y + (other.y - one.y) * share)
            if inner.contains_point(at):
                return True
    return False


def _errors(compilation: flexo.Compilation) -> list[str]:
    from flexo.diagnostics import Severity
    from flexo.lint import lint_compilation

    found = lint_compilation(compilation).diagnostics
    return [item.code for item in found if item.severity is Severity.ERROR]


def test_a_line_ends_at_a_frames_outline_on_the_side_that_faces_its_other_end() -> None:
    """A line to a frame was refused: a frame had no port for it to end at. It meets the
    frame's outline as it meets a box: at the middle of the side that faces its other end,
    or of the side ``depart`` or ``arrive`` names -- and never goes inside the frame."""

    drawn = _lined(
        TITLED,
        {"from": "c", "to": "third"},
        {"from": "a", "to": "third", "arrive": "north"},
        {"from": "second", "to": "q", "depart": "north"},
    )
    assert _errors(drawn) == []
    third, second = _frame(drawn, "third").bounds, _frame(drawn, "second").bounds
    # From a shape to its left: the frame's left side, at its middle, the arrow's last step
    # square to it.
    beside = _line(drawn, "c", "third").centerline
    assert _side_met(third, beside[-1]) == "west"
    assert beside[-1].y == pytest.approx(third.center.y)
    assert beside[-2].y == pytest.approx(beside[-1].y) and beside[-2].x < third.x
    # At the side asked for: the top of one, from a shape far to its left; out of the top
    # of another, to a shape beside it.
    over = _line(drawn, "a", "third").centerline
    assert _side_met(third, over[-1]) == "north" and over[-2].y < third.y
    out = _line(drawn, "second", "q").centerline
    assert _side_met(second, out[0]) == "north" and out[1].y < second.y
    assert out[0].x == pytest.approx(second.center.x)
    for line, box in ((beside, third), (over, third), (out, second)):
        assert not _enters(line, box)
    # Its arrowhead is on the outline: the ink stops there, as at a box.
    svg = drawn.document.text
    for name in ("edge.4.c-to-third", "edge.5.a-to-third", "edge.6.second-to-q"):
        assert f'id="{name}"' in svg
    short = third.x - _line(drawn, "c", "third").shaft[-1].x
    assert short > 0
    assert short == pytest.approx(_box(drawn, "r").y - _line(drawn, "p", "r").shaft[-1].y)


def test_a_line_to_a_frame_keeps_clear_of_its_outline_as_of_a_box() -> None:
    """A frame takes no room: round shapes a gap from another, its outline stands nearer that
    other than the gap. A line from it to the frame's far side ran down that outline, and
    left its box off the middle: that gap grows, for the line to keep a box's clearance."""

    from flexo.style import STYLES

    figure = {
        "figure": {"id": "pipeline"},
        "groups": [
            {"id": "root", "role": "canvas", "layout": {"kind": "row"},
             "children": ["api", "back", "frame"]},
            {"id": "back", "role": "layout", "layout": {"kind": "column"},
             "children": ["queue", "store"]},
        ],
        "nodes": [
            {"id": "api", "label": "API"}, {"id": "queue", "label": "Orders"},
            {"id": "store", "label": "Store"},
            {"id": "frame", "kind": "frame", "label": "Backend",
             "properties": {"around": "queue, store", "title_side": "bottom-left"}},
        ],
        "edges": [
            {"from": "queue", "to": "store"},
            {"from": "api", "to": "frame", "arrive": "south"},
        ],
    }
    drawn = compile_figure(parse_figure(figure))
    line = _line(drawn, "api", "frame").centerline
    frame, api = _frame(drawn, "frame").bounds, _box(drawn, "api")
    clearance = STYLES["paper"].route_clearance.points
    assert line[0].y == pytest.approx(api.center.y)
    assert _side_met(frame, line[-1]) == "south"
    for a, b in pairwise(line[:-1]):
        if a.x == b.x and min(a.y, b.y) < frame.bottom:
            assert frame.left - a.x >= clearance - 1e-6 or a.x - frame.right >= clearance - 1e-6
    assert not _enters(line, frame)


def test_a_line_to_a_frame_moves_no_shape_and_the_other_lines_go_through_the_frame() -> None:
    """A frame takes no room: nor does a line to it. What is laid out is laid out without
    the line, and the lines of the shapes the frame goes round cross its outline as they
    did."""

    plain = _lined(TITLED)
    drawn = _lined(TITLED, {"from": "c", "to": "third"}, {"from": "c", "to": "first"})
    assert drawn.fitted.canvas_size == plain.fitted.canvas_size
    assert [node.bounds for node in drawn.fitted.nodes] == [n.bounds for n in plain.fitted.nodes]
    assert [group.bounds for group in drawn.fitted.groups] == [
        group.bounds for group in plain.fitted.groups
    ]
    assert [frame.bounds for frame in drawn.frames] == [frame.bounds for frame in plain.frames]
    # No frame is among what was laid out, nor a line to one among the layout's lines.
    assert all(node.measured.spec.kind != "frame" for node in drawn.fitted.nodes)
    assert [edge.id for edge in drawn.measured.semantic.edges] == [
        edge.id for edge in plain.measured.semantic.edges
    ]
    # The arrow into "R" comes down through the frame round it still, where it did.
    assert _line(drawn, "p", "r").centerline == _line(plain, "p", "r").centerline
    assert _enters(_line(drawn, "p", "r").centerline, _frame(drawn, "third").bounds)
    # With no line to a frame, nothing is routed that was not: no frame stands in.
    assert all(node.measured.spec.kind != "frame" for node in plain.routed.fitted.nodes)
    assert sorted(n.measured.spec.id for n in drawn.routed.fitted.nodes if (
        n.measured.spec.kind == "frame"
    )) == ["first", "third"]


def test_lines_on_one_side_of_a_frame_spread_along_it_clear_of_a_line_through_it() -> None:
    """Several lines on a side each have a place of their own on it, as on a box's -- none
    where a line of a shape inside the frame goes through that side."""

    drawn = _lined(
        TITLED,
        {"from": "third", "to": "q", "depart": "north"},
        {"from": "q", "to": "third", "arrive": "north"},
        {"from": "a", "to": "third", "arrive": "north"},
    )
    assert _errors(drawn) == []
    third = _frame(drawn, "third").bounds
    met = sorted(
        point.x
        for point in (
            _line(drawn, "third", "q").centerline[0],
            _line(drawn, "q", "third").centerline[-1],
            _line(drawn, "a", "third").centerline[-1],
        )
        if _side_met(third, point) == "north"
    )
    lane = flexo.resolve_style("paper").port_spacing.points
    assert len(met) == 3 and all(b - a >= lane - 1e-6 for a, b in pairwise(met))
    # (The arrow into "R" goes through the frame's top at R's middle.)
    through = _box(drawn, "r").center.x
    assert all(abs(x - through) >= lane - 1e-6 for x in met)
    # Alone on that side, a line would be at its middle, where that arrow is: it keeps off.
    alone = _lined(TITLED, {"from": "q", "to": "third", "arrive": "north"})
    lone = _line(alone, "q", "third").centerline[-1]
    assert _side_met(_frame(alone, "third").bounds, lone) == "north"
    assert abs(lone.x - _box(alone, "r").center.x) >= lane - 1e-6


def test_a_line_between_a_frame_and_what_it_goes_round_is_refused_in_plain_words() -> None:
    from flexo.diagnostics import FlexoError

    for edge, inside in (
        ({"from": "b", "to": "first"}, "“b”"),
        ({"from": "first", "to": "b"}, "“b”"),
        ({"from": "third", "to": "third"}, "starts and ends at it"),
    ):
        with pytest.raises(FlexoError) as refused:
            _lined(TITLED, edge)
        (said,) = refused.value.diagnostics
        assert said.code == "frame.line.inside" and inside in said.message
        assert "from inside it" in said.message and "port" not in said.message
    # A frame round all that another goes round holds it: no line between the two.
    document = yaml.safe_load(TITLED)
    document["nodes"].append(
        {"id": "outer", "kind": "frame", "properties": {"around": "cells", "layer": "front"}}
    )
    document["edges"].append({"from": "third", "to": "outer"})
    with pytest.raises(FlexoError, match="“third”, which it goes round"):
        compile_figure(parse_figure(document))
    # Nor a line that branches, with a shape of the frame's among its other ends.
    document = yaml.safe_load(TITLED)
    document["nets"] = [
        {"id": "fan", "kind": "fan-out", "sources": ["c"], "targets": ["third", "r"]},
    ]
    with pytest.raises(FlexoError) as refused:
        compile_figure(parse_figure(document))
    (said,) = refused.value.diagnostics
    assert (said.code, said.entity_id) == ("frame.line.inside", "fan")
    # (Between frames neither of which holds the other, a line is drawn.)
    apart = _lined(TITLED, {"from": "first", "to": "third"})
    assert _side_met(_frame(apart, "first").bounds, _line(apart, "first", "third").centerline[0])
    assert _side_met(_frame(apart, "third").bounds, _line(apart, "first", "third").centerline[-1])


STAGED = """
figure: {id: staged, style: paper, width: 183mm}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 30}, children: [feed, stack, sink]}
- {id: stack, role: layout, layout: {kind: column}, children: [above, sample, refine]}
nodes:
- {id: feed, label: Restraints}
- {id: above, label: Above}
- {id: sample, label: Pose sampling}
- {id: refine, label: Chemotype substitution}
- {id: sink, label: Assemble}
- id: stage
  kind: frame
  label: "B: Generation"
  properties: {around: "sample, refine", title_side: bottom-left}
  line: dashed
edges:
- {from: refine, to: sample}
- {from: sample, to: sink, depart: north}
"""


def test_a_frames_title_and_a_line_that_meets_the_frame_on_its_side_do_not_touch() -> None:
    """The frame's title at its bottom left, and a line arriving at its bottom: the line
    stops at the outline, the title is inside it, and neither is on the other -- nor is the
    frame any wider for the line. (The frame's lower box is its wider one: its title starts
    at the frame's corner, and the frame is not twice as wide as its title, so the line
    meets its bottom under the title's end.)"""

    plain = _lined(STAGED)
    drawn = _lined(STAGED, {"from": "feed", "to": "stage", "arrive": "south"})
    assert _errors(drawn) == []
    stage, line = _frame(drawn, "stage"), _line(drawn, "feed", "stage")
    assert stage.bounds == _frame(plain, "stage").bounds and stage.title == plain.frames[0].title
    assert _side_met(stage.bounds, line.centerline[-1]) == "south"
    assert line.centerline[-1].x == pytest.approx(stage.bounds.center.x)
    assert not _enters(line.centerline, stage.bounds)
    title = stage.title
    assert _box(drawn, "refine").width > _box(drawn, "sample").width
    assert title.x == pytest.approx(stage.bounds.x + stage.inset)
    assert title.x < line.centerline[-1].x < title.right + 1.0
    assert title.y > _box(drawn, "refine").bottom and title.bottom < stage.bounds.bottom
    assert _struck(title, drawn) == []
    # (The arrow's point is on the outline, under the words by the frame's own inset.)
    assert line.centerline[-1].y - title.bottom == pytest.approx(stage.inset)
    # At the frame's top, where the line out of "Pose sampling" goes up through it at the
    # middle (nothing standing over it): a line to the frame's top keeps a lane from that.
    document = yaml.safe_load(STAGED)
    document["groups"][1]["children"].remove("above")
    document["nodes"] = [node for node in document["nodes"] if node["id"] != "above"]
    bare = yaml.safe_dump(document, sort_keys=False)
    top = _lined(bare, {"from": "feed", "to": "stage", "arrive": "north"})
    at, frame = _line(top, "feed", "stage").centerline[-1], _frame(top, "stage").bounds
    assert _side_met(frame, at) == "north"
    assert _box(top, "sample").center.x == pytest.approx(frame.center.x)
    lane = flexo.resolve_style("paper").port_spacing.points
    assert abs(at.x - frame.center.x) >= lane - 1e-6
    # And a line to its far side goes round it, not through it between its shapes.
    far = _lined(STAGED, {"from": "feed", "to": "stage", "arrive": "east"})
    round_ = _line(far, "feed", "stage").centerline
    assert _side_met(_frame(far, "stage").bounds, round_[-1]) == "east"
    assert not _enters(round_, _frame(far, "stage").bounds)


EXPECTED = """
figure: {id: expected, style: paper, width: 183mm}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 30}, children: [feed, stack, sink]}
- {id: stack, role: layout, layout: {kind: column}, children: [above, top, low]}
nodes:
- {id: feed, label: Feed}
- {id: above, label: Above}
- {id: top, label: Top}
- {id: low, label: Low}
- {id: sink, label: Sink}
- {id: stage, kind: frame, label: A stage of two, properties: {around: "top, low"}}
edges:
- {from: above, to: top, arrive: west}
- {from: top, to: low}
"""


def test_a_line_meets_a_frame_as_it_is_drawn_once_its_title_has_its_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frame is as wide as the lines through its title's band leave its title room for,
    which is known once they are routed -- after its own lines must know where it is. Here
    a line is looked for down into "Top" that comes in by its side instead: the frame is
    drawn narrower than it was taken to be, and its lines meet it there all the same."""

    import flexo.compiler as compiler

    lines = ({"from": "feed", "to": "stage"}, {"from": "stage", "to": "sink"})
    plain, drawn = _lined(EXPECTED), _lined(EXPECTED, *lines)
    stage = _frame(drawn, "stage").bounds
    assert stage == _frame(plain, "stage").bounds
    assert stage.width == pytest.approx(_frame(plain, "stage").label.width + 14.0, abs=0.1)
    into, out = _line(drawn, "feed", "stage").centerline, _line(drawn, "stage", "sink").centerline
    assert _side_met(stage, into[-1]) == "west" and _side_met(stage, out[0]) == "east"
    assert _errors(drawn) == []
    # Routed once only, the frame is drawn where its lines took it to be: wider than its
    # title needs, its title at its corner still, the lines on its outline.
    monkeypatch.setattr(compiler, "FRAME_ROUNDS", 0)
    once = _lined(EXPECTED, *lines)
    wide = _frame(once, "stage")
    assert wide.bounds.width > stage.width + 10
    assert wide.bounds.center.x == pytest.approx(stage.center.x)
    assert wide.title.x == pytest.approx(wide.bounds.x + wide.inset)
    assert _side_met(wide.bounds, _line(once, "feed", "stage").centerline[-1]) == "west"
    assert _side_met(wide.bounds, _line(once, "stage", "sink").centerline[0]) == "east"


LEVEL = """
figure: {id: level, style: paper, width: 183mm}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 40}, children: [feed, stack]}
- {id: stack, role: layout, layout: {kind: column}, children: [one, two, three]}
nodes:
- {id: feed, label: Feed}
- {id: one, label: One}
- {id: two, label: Two}
- {id: three, label: Three}
- {id: stage, kind: frame, label: Stage, properties: {around: "two, three"}}
edges:
- {from: one, to: two}
- {from: two, to: three}
- {from: feed, to: stage}
"""


def test_a_line_alone_on_a_frames_side_meets_its_middle_or_runs_straight_as_to_a_box() -> None:
    """By a box's rules: in a group that centres its parts, at the middle of the side, with
    a bend if its other end is not level with it; between parts lined up by their edges,
    slid along the side to run straight where it can."""

    def drawn(align: str) -> tuple[tuple[flexo.Point, ...], flexo.Rect, flexo.Rect]:
        document = yaml.safe_load(LEVEL)
        document["groups"][0]["layout"]["align"] = align
        found = compile_figure(parse_figure(document))
        line = _line(found, "feed", "stage").centerline
        return line, _frame(found, "stage").bounds, _box(found, "feed")

    line, stage, feed = drawn("center")
    assert _side_met(stage, line[-1]) == "west" and line[-1].y == pytest.approx(stage.center.y)
    assert stage.y < feed.center.y < stage.bottom and len(line) == 4
    line, stage, feed = drawn("end")
    assert _side_met(stage, line[-1]) == "west" and len(line) == 2
    assert line[0].y == pytest.approx(line[-1].y) and feed.y < line[0].y < feed.bottom
    assert abs(line[-1].y - stage.center.y) > 10


SIDED = """
figure: {id: sided, style: paper, width: 183mm}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 60}, children: [feeds, pair]}
- {id: feeds, role: layout, layout: {kind: column}, children: [f1, f2, f3]}
- {id: pair, role: layout, layout: {kind: row}, children: [one, two]}
nodes:
- {id: f1, label: First}
- {id: f2, label: Second}
- {id: f3, label: Third}
- {id: one, label: One}
- {id: two, label: Two}
- {id: stage, kind: frame, label: Stage, properties: {around: "one, two"}}
edges:
- {from: one, to: two, label: passes}
"""


def test_a_frames_own_lines_do_not_widen_it_nor_move_the_words_of_lines_inside_it() -> None:
    """A line that ends at a frame stops at its outline: it is not through its title's
    band, however near the title it arrives (and whatever the theme's spacing), so the
    frame is no wider for it. And the frame is no shape for a caption to keep off: the
    words of a line between the shapes it goes round stay where they were."""

    from dataclasses import replace

    from flexo.units import Length

    lines = [{"from": name, "to": "stage"} for name in ("f1", "f2", "f3")]
    paper = flexo.resolve_style("paper")
    for style in (None, replace(paper, compact_gap=Length(12.0))):
        plain = compile_figure(parse_figure(yaml.safe_load(SIDED)), style=style)
        document = yaml.safe_load(SIDED)
        document["edges"] += lines
        drawn = compile_figure(parse_figure(document), style=style)
        stage = _frame(drawn, "stage")
        assert stage.bounds == _frame(plain, "stage").bounds
        ends = [_line(drawn, name, "stage").centerline[-1] for name in ("f1", "f2", "f3")]
        assert [_side_met(stage.bounds, end) for end in ends] == ["west"] * 3
        # (One of them level with the title, just outside the frame.)
        assert any(stage.title.y < end.y < stage.title.bottom for end in ends)
        assert _struck(stage.title, drawn) == []
        assert stage.title == _frame(plain, "stage").title
        words = _line(drawn, "one", "two")
        assert words.label_position == _line(plain, "one", "two").label_position
        assert stage.bounds.contains_point(words.label_position)
    # The words of a line that comes down into a frame, set beside it inside the frame:
    # there still, with a line to the frame drawn.
    document = yaml.safe_load(TITLED)
    document["edges"][2]["label"] = "a caption of some length"
    said = yaml.safe_dump(document, sort_keys=False)
    plain, drawn = _lined(said), _lined(said, {"from": "c", "to": "third"})
    at = _line(drawn, "p", "r").label_position
    assert at == _line(plain, "p", "r").label_position
    assert _frame(drawn, "third").bounds.contains_point(at)


TIGHT = """
figure: {id: tight, style: paper, width: 120mm}
groups:
- {id: root, role: canvas, layout: {kind: column, padding: 2}, children: [feed, row]}
- {id: row, role: layout, layout: {kind: row, padding: 0}, children: [one, two]}
nodes:
- {id: feed, label: Feed}
- {id: one, label: One}
- {id: two, label: Two}
- {id: stage, kind: frame, properties: {around: "one, two"}}
edges:
- {from: feed, to: one}
"""


def test_a_line_to_a_frame_at_the_pages_edge_is_given_room_on_the_page_as_any_line_is() -> None:
    """Under a frame round the page's last row there is no room for a line to come round to
    the frame's bottom: the page is given a lane there (``routing.room``), as for a line
    round a box -- the one thing a line to a frame asks of the layout, and no shape moves
    for it."""

    plain = _lined(TIGHT)
    drawn = _lined(TIGHT, {"from": "feed", "to": "stage", "arrive": "south"})
    assert _errors(drawn) == [] and not drawn.measured.diagnostics
    line, stage = _line(drawn, "feed", "stage").centerline, _frame(drawn, "stage").bounds
    assert _side_met(stage, line[-1]) == "south"
    page = drawn.fitted.canvas_size
    assert all(0.0 < point.x < page.width and 0.0 < point.y < page.height for point in line)
    assert page.height > plain.fitted.canvas_size.height + 5
    assert page.width == plain.fitted.canvas_size.width
    assert [node.bounds for node in drawn.fitted.nodes] == [n.bounds for n in plain.fitted.nodes]
    assert stage == _frame(plain, "stage").bounds


def test_routes_kept_across_a_layout_that_moves_nothing_keep_their_frames_standing_in() -> None:
    """Room that the layout had to spare moves nothing, and the routes are kept as they
    are (``compiler._kept``): the frames their lines end at with them, where they stood."""

    import flexo.compiler as compiler
    from flexo.frames import ended, split

    # (On a page wide enough that the figure is spaced as its theme spaces it.)
    document = yaml.safe_load(TITLED)
    document["figure"]["width"] = "300mm"
    plain = compile_figure(parse_figure(document))
    document["edges"].append({"from": "c", "to": "third"})
    whole = parse_figure(document)
    drawn = compile_figure(whole)
    _, frames = split(whole)
    style = flexo.resolve_style("paper")
    kept = compiler._kept(drawn.routed, drawn.fitted, style, (frames, ended(whole)))
    stood = [n for n in kept.fitted.nodes if n.measured.spec.kind == "frame"]
    assert [node.measured.spec.id for node in stood] == ["third"]
    assert stood[0].bounds == _frame(drawn, "third").bounds
    # (Not routed again: the same lines, each the object it was.)
    assert all(one is other for one, other in zip(kept.edges, drawn.routed.edges, strict=True))
    assert compiler._kept(plain.routed, plain.fitted, style, None).fitted is plain.fitted


def test_a_line_to_a_frame_is_shown_as_its_frame_is() -> None:
    """Hidden or faint with its frame, as a line to a shape is with its shape."""

    from flexo.showing import DIMMED, HIDDEN, states

    line = {"from": "c", "to": "third"}
    for setting, how in (("hide", HIDDEN), ("dim", DIMMED)):
        # The frame itself; all it goes round; and, of two, one: only then is it not.
        for named, shown in ((["third"], how), (["r", "s"], how), (["r"], None)):
            drawn = _lined(TITLED, line, **{setting: named})
            figure = drawn.routed.fitted.measured.semantic
            found = states(figure, [frame.spec for frame in drawn.frames])
            assert found.get("third") == shown and found.get("edge.4.c-to-third") == shown
            marked = re.search(r'<g id="edge\.4\.c-to-third"[^>]*>', drawn.document.text)[0]
            assert (f'data-flexo-show="{how}"' in marked) is (shown is not None)
    lit = _lined(TITLED, line, highlight=["c", "third"])
    found = states(lit.routed.fitted.measured.semantic, [f.spec for f in lit.frames])
    assert "third" not in found and "edge.4.c-to-third" not in found
    assert found["edge.3.p-to-r"] == DIMMED


def test_a_line_that_branches_and_one_drawn_straight_or_curved_end_at_a_frame_too() -> None:
    document = yaml.safe_load(TITLED)
    document["nets"] = [
        {"id": "fan", "kind": "fan-out", "sources": ["c"], "targets": ["third", "n"]},
    ]
    document["edges"] += [
        {"from": "a", "to": "second", "shape": "curved"},
        {"from": "q", "to": "first", "shape": "straight"},
    ]
    drawn = compile_figure(parse_figure(document))
    third, second, first = (_frame(drawn, name).bounds for name in ("third", "second", "first"))
    (stem,) = [
        stem for stem in drawn.routed.net("fan").target_stems if stem.port.node_id == "third"
    ]
    assert _side_met(third, stem.centerline[-1]) and not _enters(stem.centerline, third)
    curved, straight = _line(drawn, "a", "second"), _line(drawn, "q", "first")
    assert _side_met(second, curved.centerline[-1]) == "west"
    assert first.inflated(1e-6).contains_point(straight.centerline[-1])
    assert not first.inflated(-0.5).contains_point(straight.centerline[-1])
    # (The layout sees neither the branching line nor the others.)
    layout, _ = split(parse_figure(document))
    assert not layout.nets and len(layout.edges) == 3


def test_a_line_to_a_frame_round_nothing_is_not_drawn_and_said() -> None:
    document = yaml.safe_load(TITLED)
    document["nodes"][-1]["properties"]["around"] = "nowhere"
    document["edges"].append({"from": "c", "to": "third"})
    drawn = compile_figure(parse_figure(document))
    said = {item.code: item for item in drawn.measured.diagnostics}
    assert set(said) == {"frame.around.unknown", "frame.line.undrawn"}
    assert said["frame.line.undrawn"].entity_id == "edge.4.c-to-third"
    assert "“third”" in said["frame.line.undrawn"].message
    assert 'id="edge.4.c-to-third"' not in drawn.document.text
    assert 'id="edge.3.p-to-r"' in drawn.document.text


def test_a_line_to_a_frame_is_kept_in_the_file_and_drawn_the_same_as_a_draft() -> None:
    from flexo.draft import drafting
    from flexo.frames import ended

    document = yaml.safe_load(TITLED)
    document["edges"].append({"from": "c", "to": "third", "arrive": "south", "label": "feeds"})
    figure = parse_figure(document)
    written = figure_to_document(figure)["edges"][-1]
    ends = (written["from"], written["to"], written["arrive"])
    assert ends == ("c.output", "third.input", "south")
    assert "ports" not in next(n for n in figure_to_document(figure)["nodes"] if n["id"] == "third")
    edges, nets = ended(figure)
    assert [edge.id for edge in edges] == ["edge.4.c-to-third"] and nets == ()
    assert ended(_figure(TITLED)) == ((), ())
    full = compile_figure(figure)
    with drafting():
        draft = compile_figure(figure)
    assert draft.document.text == full.document.text
    assert ">feeds<" in full.document.text
    assert _side_met(_frame(full, "third").bounds, _line(full, "c", "third").centerline[-1]) == (
        "south"
    )


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


def test_the_editor_offers_where_a_frames_title_stands_as_it_does_a_groups() -> None:
    """A frame's title could stand at its top left alone; a group's at any corner."""

    found = catalogue()
    keys = [field["key"] for field in found["parts"]["frame"]["fields"]]
    assert keys[keys.index("properties.layer") + 1] == "properties.title_side"
    side = found["parts"]["frame"]["fields"][keys.index("properties.title_side")]
    (group,) = (field for field in found["group_fields"] if field["key"] == "title_side")
    # The same control, its choices named and ordered alike -- shown on every frame, as a
    # group's is on every group with a frame drawn.
    same = ("label", "type", "options", "labels", "default")
    assert {name: side[name] for name in same} == {name: group[name] for name in same}
    assert side["label"] == "Title Position" and side["options"] == list(SIDES)
    assert side["labels"]["bottom-left"] == "Bottom Left" and side["default"] == "left"
    assert "show" not in side and "more" not in side

    # Chosen, it is written in the frame's properties and drawn; the top left again, and
    # nothing is written.
    text = yaml.safe_dump(yaml.safe_load(TITLED), sort_keys=False)
    target = {"type": "node", "id": "first"}
    values = {"properties.title_side": "bottom-left"}
    under = apply(text, {"do": "update", "target": target, "values": values})["text"]
    assert _nodes(under)["first"]["properties"] == {"around": "b", "title_side": "bottom-left"}
    drawn = compile_figure(parse_figure(yaml.safe_load(under)))
    first = next(frame for frame in drawn.frames if frame.spec.id == "first")
    assert first.title.y > _box(drawn, "b").bottom
    back = apply(under, {"do": "update", "target": target, "values": {values.popitem()[0]: None}})
    assert _nodes(back["text"])["first"]["properties"] == {"around": "b"}
    # A frame copied keeps where its title stands, as it keeps its layer.
    copied = apply(under, {"do": "duplicate", "ids": ["b", "first"]})["text"]
    sides = [
        node["properties"].get("title_side")
        for node in _nodes(copied).values()
        if node.get("kind") == "frame" and node["label"] == "Under another shape"
    ]
    assert sides == ["bottom-left", "bottom-left"]


def test_the_editor_draws_a_line_to_a_frame_and_keeps_it_right() -> None:
    """A line drawn to a frame was refused as breaking the figure. It is written as a line
    to a shape is, ended at another side or another shape as one is, and goes or is renamed
    with its frame."""

    from flexo.studio.figure_edit import EditError, model

    def edges(text: str) -> list[dict]:
        return yaml.safe_load(text).get("edges", [])

    text = yaml.safe_dump(yaml.safe_load(TITLED), sort_keys=False)
    made = apply(text, {"do": "connect", "source": "c", "target": "third"})
    assert made["select"] == ["edge.4.c-to-third"]
    assert edges(made["text"])[-1] == {"from": "c", "to": "third"}
    both = apply(made["text"], {"do": "connect", "source": "third", "target": "q"})["text"]
    assert edges(both)[-1] == {"from": "third", "to": "q"}
    compile_figure(parse_figure(yaml.safe_load(both)))
    # (The page knows a frame takes a line: it has a box's two ports.)
    (frame,) = (node for node in model(both)["nodes"] if node["id"] == "third")
    assert frame["ports"] == ["input", "output"]

    # From a shape the frame goes round there is no way to it: said by what each is called.
    for source, target in (("b", "first"), ("first", "b")):
        with pytest.raises(EditError) as refused:
            apply(both, {"do": "connect", "source": source, "target": target})
        assert str(refused.value) == (
            "A line can\u2019t end at “Under another shape” from inside it: the frame goes "
            "round “Framed”."
        )

    # Its end at the frame taken to another side, to another frame -- and never to a frame
    # that goes round its other end.
    line = {"type": "edge", "id": "edge.4.c-to-third"}
    sided = apply(both, {"do": "update", "target": line, "values": {"arrive": "south"}})
    assert edges(sided["text"])[3] == {"from": "c", "to": "third", "arrive": "south"}
    there = {"to": "second", "arrive": "west"}
    moved = apply(sided["text"], {"do": "update", "target": line, "values": there})
    assert moved["select"] == ["edge.4.c-to-second"]
    assert edges(moved["text"])[3] == {"from": "c", "to": "second", "arrive": "west"}
    compile_figure(parse_figure(yaml.safe_load(moved["text"])))
    inner = {"type": "edge", "id": "edge.1.a-to-b"}
    with pytest.raises(EditError, match="from inside it"):
        apply(both, {"do": "update", "target": inner, "values": {"from": "first"}})

    # Renamed, its lines name it; deleted, they go with it -- none joined round it, as round
    # a shape taken out of a chain; and gone with the last shape it went round, the same.
    renamed = apply(both, {"do": "rename", "id": "third", "to": "stage"})["text"]
    assert edges(renamed)[3:] == [{"from": "c", "to": "stage"}, {"from": "stage", "to": "q"}]
    for gone in (["third"], ["r", "s"]):
        left = apply(both, {"do": "delete", "ids": gone})["text"]
        assert "third" not in _nodes(left)
        assert not [edge for edge in edges(left) if "third" in edge.values()]
        assert not [edge for edge in edges(left) if (edge["from"], edge["to"]) == ("c", "q")]
        compile_figure(parse_figure(yaml.safe_load(left)))

    # Copied with a shape it is joined to, the copies are joined; alone, it has no line.
    copied = apply(both, {"do": "duplicate", "ids": ["c", "third"]})["text"]
    assert {"from": "c-2", "to": "third-2"} in edges(copied)
    alone = apply(both, {"do": "duplicate", "ids": ["third"]})["text"]
    assert not [edge for edge in edges(alone) if "third-2" in edge.values()]
    # Two lines into it are joined into one that branches, as into a shape.
    third = apply(both, {"do": "connect", "source": "a", "target": "third"})["text"]
    joined = apply(third, {"do": "join", "ids": ["edge.4.c-to-third", "edge.6.a-to-third"]})
    (net,) = yaml.safe_load(joined["text"])["nets"]
    assert (net["kind"], net["sources"], net["targets"]) == ("merge", ["c", "a"], ["third"])
    drawn = compile_figure(parse_figure(yaml.safe_load(joined["text"])))
    assert [stem.port.node_id for stem in drawn.routed.net(net["id"]).target_stems] == ["third"]
