"""Frames: a box round shapes wherever they are in the figure, behind them, in front of them
or over them -- which no group can be, as a group holds only what stands together."""

from __future__ import annotations

import re
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
