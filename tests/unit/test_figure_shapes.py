"""Shapes drawn over a figure (flexo.figure_shapes): read, checked, placed on its parts as it
is laid out, drawn over it, shown as its hide and dim say, and edited round trip."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from flexo import Figure, compile_figure, freeform
from flexo.diagnostics import FlexoError
from flexo.figure_shapes import around_box, checked, margin_of, placed_round, read
from flexo.serialization import dump_figure, parse_figure
from flexo.studio.figure_edit import apply, model
from flexo.studio.figure_kind import FigureKind

SVG = "{http://www.w3.org/2000/svg}"
AROUND = Path(__file__).parents[2] / "src/flexo/studio/static/figure/around.js"
FREEFORM = Path(__file__).parents[2] / "src/flexo/studio/static/studio/freeform.js"


def figure(*, shapes: list | None = None, first: tuple[str, ...] = ()) -> dict:
    """A row of three -- x, encoder, decoder -- after any of ``first``."""

    nodes = [{"id": name, "label": name.title()} for name in (*first, "x", "encoder", "decoder")]
    document = {
        "figure": {"id": "f"},
        "nodes": nodes,
        "groups": [
            {"id": "root", "children": [node["id"] for node in nodes], "layout": {"kind": "row"}}
        ],
        "edges": [{"from": "x", "to": "encoder"}, {"from": "encoder", "to": "decoder"}],
    }
    if shapes is not None:
        document["shapes"] = shapes
    return document


def drawn(document: dict):
    return compile_figure(parse_figure(document))


def element(svg: str, ident: str) -> ET.Element:
    root = ET.fromstring(svg)
    found = next((item for item in root.iter() if item.get("id") == ident), None)
    assert found is not None, ident
    return found


def numbers(value: str) -> list[float]:
    return [float(item) for item in value.split()]


def node_box(compilation, ident: str) -> tuple[float, float, float, float]:
    node = next(item for item in compilation.fitted.nodes if item.measured.spec.id == ident)
    return (node.bounds.x, node.bounds.y, node.bounds.width, node.bounds.height)


# -- reading -------------------------------------------------------------------------------


def test_shapes_are_read_and_written_back_as_written() -> None:
    shapes = [
        {"kind": "arrow", "from": [10, 10], "to": {"part": "encoder", "side": "top", "at": [5, 5]}},
        {"kind": "ring", "id": "ring1", "around": ["decoder"], "margin": 4},
        {"kind": "text", "on": "encoder", "at": [0, -16], "text": "here"},
    ]
    spec = parse_figure(figure(shapes=shapes))
    assert [shape.spec["kind"] for shape in spec.shapes] == ["arrow", "ring", "text"]
    again = parse_figure(yaml.safe_load(dump_figure(spec)))
    assert again == spec and hash(again) == hash(spec)
    assert yaml.safe_load(dump_figure(spec))["shapes"][2]["on"] == "encoder"
    # A figure with none writes none.
    assert "shapes" not in yaml.safe_load(dump_figure(parse_figure(figure())))


def test_on_read_by_a_yaml_1_1_reader_is_on() -> None:
    written = yaml.safe_load("kind: text\non: encoder\nat: [0, 0]\n")
    assert True in written
    assert checked(written)["on"] == "encoder"


@pytest.mark.parametrize(
    ("shape", "words"),
    [
        (
            {"kind": "arrow", "from": [0, 0], "to": [1, 1], "fill": "bogus"},
            "shapes[0].fill: fill must be",
        ),
        (
            {"kind": "ring", "on": "x", "around": ["x"]},
            "shapes[0].on: A shape is on a part or drawn round",
        ),
        (
            {"kind": "ring", "at": [0, 0], "size": [1, 1], "margin": 3},
            "shapes[0].margin: margin is for",
        ),
        ({"kind": "brace", "around": ["x"], "side": "middle"}, "shapes[0].side: side must be"),
        (
            {"kind": "group", "around": ["x"], "shapes": []},
            "shapes[0].around: A group is not drawn",
        ),
        ({"kind": "line", "from": [0, 0], "to": {"node": "x"}}, "shapes[0].to: to must be a point"),
    ],
)
def test_a_shape_written_wrong_is_said_under_its_place(shape: dict, words: str) -> None:
    with pytest.raises(FlexoError) as caught:
        parse_figure(figure(shapes=[shape]))
    assert words in str(caught.value)


def test_a_shape_round_parts_needs_no_places_of_its_own() -> None:
    assert checked({"kind": "ring", "around": "encoder, decoder"}) == {
        "kind": "ring",
        "around": ["encoder", "decoder"],
    }
    assert "from" not in checked({"kind": "brace", "around": ["x"]})


def test_shapes_named_alike_or_as_parts_are_refused() -> None:
    _, said = read([{"kind": "ring", "id": "a", "at": [0, 0], "size": [1, 1]}] * 2)
    assert [item.code for item in said] == ["shape.id.duplicate"]
    with pytest.raises(FlexoError, match="as a part of the figure is"):
        parse_figure(figure(shapes=[{"kind": "ring", "id": "encoder", "around": ["x"]}]))


# -- placing -------------------------------------------------------------------------------


def test_shapes_take_no_room_in_the_layout() -> None:
    plain = drawn(figure())
    shaped = drawn(
        figure(
            shapes=[
                {"kind": "ring", "around": ["encoder"]},
                {"kind": "arrow", "from": [-40, -40], "to": [900, 300]},
            ]
        )
    )
    assert [node.bounds for node in plain.fitted.nodes] == [
        node.bounds for node in shaped.fitted.nodes
    ]


def test_attached_shapes_follow_their_parts_as_the_figure_is_laid_out_again() -> None:
    shapes = [
        {"kind": "arrow", "from": [0, -30], "to": {"part": "encoder", "side": "top"}},
        {"kind": "text", "on": "encoder", "at": [2, -14], "text": "here"},
        {"kind": "ring", "id": "ring", "around": ["decoder"]},
    ]
    for first in ((), ("extra", "more")):
        compilation = drawn(figure(shapes=shapes, first=first))
        svg = compilation.document.text
        x, y, w, _ = node_box(compilation, "encoder")
        # The arrow's end is at the middle of the encoder's top, wherever the encoder is.
        ends = numbers(element(svg, "shapes.0").get("data-flexo-ends"))
        assert ends[2:] == pytest.approx([x + w / 2, y])
        # The words are on it, where they were put from its top left.
        assert numbers(element(svg, "shapes.1").get("data-flexo-box"))[:2] == pytest.approx(
            [x + 2, y - 14]
        )
        # The ring is round the decoder, through its box's corners and its margin out.
        box = around_box([node_box(compilation, "decoder")], margin_of({"kind": "ring"}), "ring")
        assert numbers(element(svg, "ring").get("data-flexo-box")) == pytest.approx(list(box))
        placed = compilation.shapes.placed
        assert placed[2].spec["size"] == pytest.approx(list(box[2:]))


def test_a_brace_round_parts_runs_down_their_right_pointing_away() -> None:
    compilation = drawn(figure(shapes=[{"kind": "brace", "around": ["encoder"]}]))
    x, y, w, h = node_box(compilation, "encoder")
    margin = margin_of({"kind": "brace"})
    ends = numbers(element(compilation.document.text, "shapes.0").get("data-flexo-ends"))
    assert ends == pytest.approx([x + w + margin, y - margin, x + w + margin, y + h + margin])
    made = freeform.geometry({"kind": "brace", "from": ends[:2], "to": ends[2:]})
    assert made.label is not None and made.label.x > x + w + margin


def test_a_line_may_be_glued_to_a_piece_of_a_part() -> None:
    document = {
        "figure": {"id": "f"},
        "nodes": [
            {
                "id": "p",
                "kind": "protein",
                "properties": {
                    "length": 200,
                    "features": [{"type": "domain", "label": "SH3", "start": 20, "end": 80}],
                },
            }
        ],
        "shapes": [{"kind": "arrow", "from": [0, 0], "to": {"part": "p.feature1", "side": "top"}}],
    }
    compilation = drawn(document)
    assert not [
        item for item in compilation.measured.diagnostics if item.code == "shape.part.unknown"
    ]
    piece = compilation.shapes.named["p.feature1"]
    ends = numbers(element(compilation.document.text, "shapes.0").get("data-flexo-ends"))
    assert ends[2:] == pytest.approx([piece[0] + piece[2] / 2, piece[1]])


def test_a_part_that_is_gone_is_a_warning_and_an_end_stays_where_it_was() -> None:
    compilation = drawn(
        figure(
            shapes=[
                {"kind": "arrow", "from": [0, 0], "to": {"part": "gone", "at": [30, 40]}},
                {"kind": "ring", "around": ["gone"]},
                {"kind": "text", "on": "gone", "at": [5, 6], "text": "words"},
            ]
        )
    )
    said = [item for item in compilation.measured.diagnostics if item.code == "shape.part.unknown"]
    assert len(said) == 3 and all(item.severity.value == "warning" for item in said)
    svg = compilation.document.text
    assert numbers(element(svg, "shapes.0").get("data-flexo-ends"))[2:] == [30, 40]
    assert 'id="shapes.1"' not in svg
    assert numbers(element(svg, "shapes.2").get("data-flexo-box"))[:2] == [5, 6]


# -- drawing -------------------------------------------------------------------------------


def test_shapes_are_drawn_over_everything_and_behind_under_the_parts() -> None:
    svg = drawn(
        figure(
            shapes=[
                {"kind": "highlight", "around": ["x"], "behind": True},
                {
                    "kind": "arrow",
                    "id": "pointer",
                    "from": [0, 0],
                    "to": [20, 20],
                    "line": "accent2",
                },
            ]
        )
    ).document.text
    root = ET.fromstring(svg)
    layers = [item.get("id") for item in root]
    assert layers.index("layer.shapes") > layers.index("root")
    order = [item.get("id") for item in root.iter() if item.get("id")]
    assert order.index("root.shapes-behind") < order.index("root.components") < order.index("x")
    arrow = element(svg, "pointer")
    assert arrow.get("data-flexo-shape") == "arrow"
    assert arrow.get("{http://www.inkscape.org/namespaces/inkscape}label") == "Arrow"
    # Painted by the figure's palette, by role, so a change of theme repaints it.
    assert element(svg, "pointer.outline").get("data-flexo-stroke") == "tone-2-stroke"


def test_a_shapes_words_are_set_in_the_figures_font() -> None:
    compilation = drawn(
        figure(shapes=[{"kind": "rectangle", "at": [0, 0], "size": [80, 30], "text": "Words"}])
    )
    from flexo.themes import figure_style

    text = element(compilation.document.text, "shapes.0.text")
    assert text.get("font-family") == figure_style(parse_figure(figure())).typography.family


def test_the_page_grows_to_hold_shapes_past_it_on_any_side_nothing_moved() -> None:
    plain = drawn(figure()).document.text
    width, height = numbers(ET.fromstring(plain).get("viewBox"))[2:]
    svg = drawn(
        figure(
            shapes=[
                {
                    "kind": "line",
                    "from": [-50, -30],
                    "to": [width + 40, height + 20],
                    "line_width": 2,
                }
            ]
        )
    ).document.text
    root = ET.fromstring(svg)
    x, y, w, h = numbers(root.get("viewBox"))
    assert x < -50 and y < -30 and x + w > width + 40 and y + h > height + 20
    page = element(svg, "canvas.background")
    assert [float(page.get(key)) for key in ("x", "y", "width", "height")] == pytest.approx(
        [x, y, w, h]
    )
    # The figure's own parts are where they were.
    assert element(svg, "encoder").attrib == element(plain, "encoder").attrib


def test_hide_dim_and_highlight_name_shapes_and_attached_ones_follow_their_parts() -> None:
    shapes = [
        {"kind": "ring", "id": "ring", "around": ["decoder"]},
        {"kind": "arrow", "from": [0, 0], "to": {"part": "encoder"}},
        {"kind": "text", "at": [0, 0], "text": "loose"},
    ]
    hidden = figure(shapes=shapes)
    hidden["figure"]["hide"] = ["ring"]
    hidden["figure"]["dim"] = ["encoder"]
    svg = drawn(hidden).document.text
    assert element(svg, "ring").get("visibility") == "hidden"
    assert element(svg, "shapes.1").get("data-flexo-show") == "dimmed"
    assert element(svg, "shapes.2").get("data-flexo-show") is None
    lit = figure(shapes=shapes)
    lit["figure"]["highlight"] = ["decoder"]
    svg = drawn(lit).document.text
    assert element(svg, "ring").get("data-flexo-show") is None
    assert element(svg, "shapes.1").get("data-flexo-show") == "dimmed"
    assert element(svg, "shapes.2").get("data-flexo-show") == "dimmed"


def test_every_output_has_the_shapes(tmp_path: Path) -> None:
    from flexo.export import build

    spec = parse_figure(figure(shapes=[{"kind": "ring", "around": ["encoder"], "text": "ring"}]))
    result = build(spec, tmp_path, stem="f", formats=("editable", "portable", "pdf", "png"))
    outputs = result.outputs
    assert all(path.stat().st_size for path in outputs.existing())
    assert "Highlight Ring" in outputs.editable_svg.read_text()
    # (The portable SVG is drawn from the editable one, words as outlines: the ring is in it.)
    assert outputs.portable_svg.read_text().count("<path") > 5


def test_a_figure_with_free_shapes_is_not_turned_to_fit_a_box() -> None:
    from flexo.boxfit import fit_in_box

    tall = figure(shapes=[{"kind": "text", "at": [0, 0], "text": "where it is"}])
    tall["groups"][0]["layout"] = {"kind": "column"}
    fit = fit_in_box(parse_figure(tall), 600, 80)
    assert not fit.layout.startswith("turned")


def test_the_builder_draws_shapes() -> None:
    made = Figure("f")
    made.block("a", label="A")
    made.shape("ring", around=["a"])
    made.shape("arrow", from_=[0, 0], to={"part": "a"})
    assert [shape.spec for shape in made.spec.shapes] == [
        {"kind": "ring", "around": ["a"]},
        {"kind": "arrow", "from": [0.0, 0.0], "to": {"part": "a"}},
    ]
    with pytest.raises(FlexoError, match=r"shapes\[2\]\.line_width"):
        made.shape("line", from_=[0, 0], to=[1, 1], line_width=-1)


def test_the_studios_placing_round_parts_is_the_figures() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    boxes = [[10.0, 20.0, 60.0, 30.0], [90.0, 15.0, 40.0, 50.0]]
    kinds = [
        "ring",
        "highlight",
        "rectangle",
        "text",
        "brace",
        "bracket",
        "dimension",
        "arrow",
        "polyline",
    ]
    cases = [
        {
            "kind": kind,
            **({"points": [[0, 0], [5, 9], [10, 2]]} if kind == "polyline" else {}),
            **({"side": side} if side else {}),
        }
        for kind in kinds
        for side in (None, "left", "top", "bottom")
    ]
    script = (
        f"import * as f from {json.dumps(FREEFORM.as_uri())};\n"
        f"import * as a from {json.dumps(AROUND.as_uri())};\n"
        f"const cases = {json.dumps(cases)}, boxes = {json.dumps(boxes)};\n"
        "console.log(JSON.stringify(cases.map((spec) =>\n"
        "  a.placedRound(spec, a.aroundBox(boxes, 3, spec.kind), f.family))));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    theirs = json.loads(result.stdout)
    for spec, other in zip(cases, theirs, strict=True):
        ours = placed_round(spec, around_box([tuple(box) for box in boxes], 3, spec["kind"]))
        for key in ("at", "size", "width", "from", "to", "points"):
            assert (key in ours) == (key in other), (spec, key)
            if key in ours:
                flat = json.loads(json.dumps(ours[key]))
                if key == "points":
                    flat = [value for point in flat for value in point]
                    other[key] = [value for point in other[key] for value in point]
                assert flat == pytest.approx(other[key]), (spec, key)


# -- edited in the studio --------------------------------------------------------------------

TEXT = """\
# A figure
figure:
  id: f
nodes:
- id: x
  label: X
- id: encoder
  label: Encoder
edges:
- from: x
  to: encoder
shapes:
# the ring
- kind: ring
  around: [encoder]   # round the encoder
- kind: arrow
  from: [10, 10]
  to: {part: encoder, side: top, at: [50, 50]}
"""


def test_shapes_edited_keep_the_file_as_written() -> None:
    shapes = model(TEXT)["shapes"]
    result = apply(
        TEXT,
        {
            "do": "shapes",
            "shapes": [
                shapes[0],
                {**shapes[1], "line": "accent2"},
                {"kind": "text", "on": "x", "at": [0, -10], "text": "hi"},
            ],
        },
    )
    text = result["text"]
    assert "# the ring\n- kind: ring\n  around: [encoder]   # round the encoder\n" in text
    assert "  to: {part: encoder, side: top, at: [50, 50]}\n  line: accent2\n" in text
    assert "- kind: text\n  'on': x\n  at: [0, -10]\n  text: hi\n" in text
    assert parse_figure(yaml.safe_load(text)).shapes[2].spec["on"] == "x"
    # The same list again changes nothing, to the letter.
    assert apply(text, {"do": "shapes", "shapes": model(text)["shapes"]})["text"] == text
    # The last one taken away, the list goes.
    assert "shapes:" not in apply(TEXT, {"do": "shapes", "shapes": []})["text"]


def test_a_shape_written_wrong_is_refused_by_the_edit() -> None:
    from flexo.studio.figure_edit import EditError

    with pytest.raises(EditError, match=r"shapes\[0\]\.fill"):
        apply(
            TEXT,
            {
                "do": "shapes",
                "shapes": [{"kind": "ring", "at": [0, 0], "size": [1, 1], "fill": "bogus"}],
            },
        )


def test_a_part_renamed_is_renamed_in_the_shapes() -> None:
    text = apply(TEXT, {"do": "rename", "id": "encoder", "to": "enc"})["text"]
    shapes = model(text)["shapes"]
    assert shapes[0]["around"] == ["enc"] and shapes[1]["to"]["part"] == "enc"


def test_a_part_deleted_leaves_its_shapes_where_they_were() -> None:
    text = apply(
        TEXT + "- {kind: text, 'on': encoder, at: [1, 2], text: hi}\n",
        {"do": "delete", "ids": ["encoder"], "origins": {"encoder": [100, 40]}},
    )["text"]
    shapes = model(text)["shapes"]
    # The ring round it alone goes; the arrow's end is where it was; the words where they were.
    assert shapes == [
        {"kind": "arrow", "from": [10, 10], "to": [50, 50]},
        {"kind": "text", "at": [101, 42], "text": "hi"},
    ]


def test_a_shape_hidden_by_its_id_stays_hidden_as_the_figure_is_edited() -> None:
    text = TEXT.replace("- kind: ring\n", "- kind: ring\n  id: ring\n").replace(
        "  id: f\n", "  id: f\n  hide: [ring]\n"
    )
    edited = apply(
        text, {"do": "update", "target": {"type": "node", "id": "x"}, "values": {"label": "Y"}}
    )["text"]
    assert model(edited)["figure"]["hide"] == ["ring"]


def test_the_studio_draws_the_rest_when_a_shape_is_written_wrong() -> None:
    kind = FigureKind()
    bad = (
        TEXT
        + "- kind: arrow\n  from: [1, 2]\n  to: [3, 4]\n  fill: bogus\n"
        + "- {kind: text, at: [0, 0], text: after}\n"
    )
    drawing = kind.draw({"text": bad}, Path("."))
    said = [message for message in drawing.messages if message.severity == "error"]
    assert [message.where for message in said] == ["shapes.2"]
    svg = drawing.pages[0].svg
    # Each keeps its place in the list: the one after it is still shapes.3.
    assert 'id="shapes.3"' in svg and 'id="shapes.2"' not in svg
    info = drawing.info
    assert len(info["shapes"]) == 4 and info["shapes"][2] is None
    assert info["shapes"][0]["around"] == ["encoder"] and "size" in info["shapes"][0]
    assert set(info["boxes"]) >= {"x", "encoder", "root"}
    assert info["roles"]["tone-1-stroke"]


def test_the_activity_says_what_was_drawn() -> None:
    kind = FigureKind()
    without = {"text": TEXT.split("shapes:")[0]}
    assert kind.describe(without, {"text": TEXT})[0]["text"] == "edited the shapes drawn over it"
    one = {"text": TEXT.split("- kind: arrow")[0]}
    assert kind.describe(one, {"text": TEXT})[0]["text"] == "added an arrow"
    assert kind.describe({"text": TEXT}, one)[0]["text"] == "deleted an arrow"


def test_the_catalogue_offers_the_shapes() -> None:
    shapes = FigureKind().catalog()["shapes"]
    assert shapes["labels"]["ring"] == "Highlight Ring"
    assert "around" in shapes["keys"] and shapes["margins"]["highlight"] == 2.0


def test_a_shapes_text_markup_is_the_figures() -> None:
    svg = drawn(
        figure(shapes=[{"kind": "text", "at": [0, 0], "text": "$x^2$ and `code`"}])
    ).document.text
    assert re.search(r'id="shapes\.0\.text"', svg)


def test_a_shape_named_and_hidden_in_one_step() -> None:
    shapes = model(TEXT)["shapes"]
    named = [{**shapes[0], "id": "ring"}, shapes[1]]
    text = apply(
        TEXT, {"do": "shapes", "shapes": named, "show": {"ids": ["ring"], "as": "dimmed"}}
    )["text"]
    assert model(text)["figure"]["dim"] == ["ring"] and model(text)["shapes"][0]["id"] == "ring"


def test_a_shape_behind_its_parts_is_over_their_groups_box_and_under_them() -> None:
    document = {
        "figure": {"id": "f"},
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
        "groups": [
            {"id": "root", "children": ["m", "c"], "layout": {"kind": "row"}},
            {"id": "m", "role": "module", "children": ["a", "b"], "layout": {"kind": "row"}},
        ],
        "shapes": [
            {"kind": "ellipse", "around": ["a"], "behind": True},
            {"kind": "rounded-rectangle", "around": ["m"], "behind": True},
            {"kind": "star", "at": [300, 10], "size": [40, 40], "behind": True},
        ],
    }
    root = ET.fromstring(drawn(document).document.text)
    order = [item.get("id") for item in root.iter() if item.get("id")]
    # Round a part in a module: over the module's own box, under the part -- never hiding it.
    assert order.index("m.container") < order.index("shapes.0") < order.index("a")
    # Round the module, and free: over the figure's own box (filled), under the module.
    assert order.index("root.container") < order.index("shapes.1") < order.index("m.container")
    assert order.index("root.container") < order.index("shapes.2") < order.index("c")
    assert element(drawn(document).document.text, "m.shapes-behind") is not None
