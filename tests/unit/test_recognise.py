"""A diagram drawn as shapes -- as pasted from Inkscape -- read as a figure's own parts
(``flexo.recognise``): boxes with words become shapes of the nearest kind, arrows between them
lines, frames with titles modules, the arrangement a row, a column or a grid; what is no part of
it stays a shape, attached to the parts. And Convert to Figure Parts, which does so in a figure
file's own words (``flexo.studio.figure_convert``), the command line's ``to-parts``, and the
agents' tool."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from flexo.cli import main
from flexo.compiler import compile_figure
from flexo.recognise import figure_document, figure_of, recognise
from flexo.serialization import parse_figure
from flexo.studio.figure_edit import EditError, apply
from flexo.studio.figure_kind import parse
from flexo.themes import resolve_palette, with_tone_roles

PAPER = with_tone_roles(resolve_palette("paper", "default"))


def box(x, y, w=100, h=50, text=None, fill="#cfe2f3", kind="rectangle", id=None, **more):
    spec = {"kind": kind, **({"id": id} if id else {}), "at": [x, y], "size": [w, h]}
    spec |= {"fill": fill, "line": "#3d85c6", "line_width": 1.5, **more}
    if text:
        spec["text"] = text
    return spec


def words(x, y, text, size=12, **more):
    return {"kind": "text", "at": [x, y], "text": text, "font_size": size, **more}


def arrow(a, b, **more):
    return {"kind": "arrow", "from": a, "to": b, "line": "#444444", "line_width": 1.5, **more}


def pipeline():
    names = ["Raw reads", "Quality filter", "Align to reference", "Call variants", "Report"]
    shapes = [
        box(40 + i * 150, 100, 110, 50, name, fill="#fce5cd" if i == 4 else "#cfe2f3")
        for i, name in enumerate(names)
    ]
    # Arrows ending a little short of each box, as drawn by hand.
    shapes += [arrow([152 + i * 150, 125], [187 + i * 150, 126]) for i in range(4)]
    return shapes


def grid():
    rows = [
        ["Sample prep", "Vitrification", "Data collection"],
        ["Motion correction", "CTF estimation", "Particle picking"],
    ]
    shapes = []
    for r, row in enumerate(rows):
        for c, name in enumerate(row):
            x, y = 60 + c * 170, 60 + r * 110
            shapes.append(box(x, y, 140, 70, fill="#d9ead3", id=f"rect{r * 3 + c}"))
            shapes.append(words(x + 20, y + 26, name, id=f"text{r * 3 + c}"))
    return shapes


def modules():
    shapes = []
    for m, (title, names) in enumerate(
        [
            ("Encoder", ["Embed tokens", "Self-attention", "Feed-forward"]),
            ("Decoder", ["Masked attention", "Cross-attention", "Softmax"]),
        ]
    ):
        x0 = 40 + m * 300
        shapes.append(box(x0, 60, 200, 260, fill="#f3f3f3", id=f"frame{m}"))
        shapes.append(words(x0 + 10, 66, title, size=13, bold=True))
        shapes += [
            box(x0 + 30, 100 + i * 70, 140, 45, name, kind="rounded-rectangle", corner=6)
            for i, name in enumerate(names)
        ]
    shapes.append(arrow([240, 190], [340, 190]))
    return shapes


def flowchart():
    return [
        box(
            170,
            20,
            120,
            40,
            "Start",
            kind="rounded-rectangle",
            corner=20,
            fill="#d9ead3",
            id="start",
        ),
        box(160, 100, 140, 50, "Refine model", id="refine"),
        box(170, 190, 120, 80, "Converged?", kind="diamond", fill="#fff2cc", id="check"),
        box(160, 310, 140, 50, "Write map", kind="parallelogram", id="write"),
        box(
            170, 400, 120, 40, "End", kind="rounded-rectangle", corner=20, fill="#d9ead3", id="end"
        ),
        arrow({"shape": "start", "side": "bottom"}, {"shape": "refine", "side": "top"}),
        arrow({"shape": "refine"}, {"shape": "check"}),
        arrow([230, 271], [230, 308]),
        words(236, 278, "yes", size=11),
        {
            "kind": "elbow",
            "from": {"shape": "check", "side": "right"},
            "to": {"shape": "refine", "side": "right"},
            "elbow": 1.6,
        },
        words(300, 212, "no", size=11),
        arrow({"shape": "write"}, {"shape": "end"}),
    ]


def mix():
    return [
        box(60, 120, 110, 50, "Input $x$", fill="none", id="in"),
        box(230, 120, 110, 50, "Encoder", id="enc"),
        box(400, 120, 110, 50, "Latent $z$", fill="#fce5cd", id="lat"),
        arrow({"shape": "in"}, {"shape": "enc"}),
        arrow({"shape": "enc"}, {"shape": "lat"}),
        {
            "kind": "highlight",
            "at": [220, 110],
            "size": [300, 70],
            "fill": "#ffd966",
            "fill_opacity": 0.35,
            "behind": True,
        },
        {
            "kind": "pen",
            "points": [[90, 60], [140, 40], [200, 70], [260, 45], [320, 70]],
            "line": "#cc0000",
        },
        {"kind": "brace", "from": [520, 190], "to": [220, 190], "text": "learned"},
        {
            "kind": "arrow",
            "from": [580, 60],
            "to": [470, 115],
            "line": "#cc0000",
            "text": "the bottleneck",
        },
    ]


def branches():
    def poly(*points):
        return {"kind": "polyline", "points": [list(point) for point in points], "end": "triangle"}

    return [
        box(200, 30, 120, 40, kind="rounded-rectangle", corner=20, fill="#eeeeee"),
        words(240, 42, "Load"),
        box(200, 110, 120, 80, kind="diamond", fill="#fff2cc"),
        words(228, 142, "Resolution\n< 3 Å?", size=11),
        box(80, 240, 130, 50, fill="#d9ead3"),
        words(95, 256, "Build atoms"),
        box(310, 240, 130, 50, fill="#f4cccc"),
        words(325, 256, "Fit domains"),
        box(200, 350, 120, 40, kind="rounded-rectangle", corner=20, fill="#eeeeee"),
        words(235, 362, "Deposit"),
        poly((260, 70), (260, 108)),
        poly((200, 150), (145, 150), (145, 238)),
        words(160, 132, "yes", size=10),
        poly((320, 150), (375, 150), (375, 238)),
        words(340, 132, "no", size=10),
        poly((145, 290), (145, 370), (198, 370)),
        poly((375, 290), (375, 370), (322, 370)),
    ]


def nodes_of(found):
    return {node["id"]: node for node in found.nodes}


def lines_of(found):
    return [(edge["from"], edge["to"]) for edge in found.edges]


@pytest.mark.parametrize("make", [pipeline, grid, modules, flowchart, mix, branches])
def test_every_diagram_drawn_reads_as_a_figure_that_draws(make) -> None:
    document = figure_document(make(), id="drawn")
    # As a figure file: it reads back as written, and draws.
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    compile_figure(parse_figure(yaml.safe_load(text)))
    compile_figure(figure_of(make()))


def test_a_pipeline_of_boxes_and_arrows_is_a_row_of_shapes_joined_in_turn() -> None:
    found = recognise(pipeline(), palette=PAPER, holder="diagram")
    assert [node["id"] for node in found.nodes] == [
        "raw-reads",
        "quality-filter",
        "align-to-reference",
        "call-variants",
        "report",
    ]
    # Arrows ending short of the boxes still join them, in the way they point.
    assert lines_of(found) == [
        ("raw-reads", "quality-filter"),
        ("quality-filter", "align-to-reference"),
        ("align-to-reference", "call-variants"),
        ("call-variants", "report"),
    ]
    assert found.top == [node["id"] for node in found.nodes]
    # Drawn the same size, they are made so; blue the theme's first tone, orange its second.
    assert found.layout == {"kind": "row", "equal_size": True}
    tones = [node["properties"]["tone"] for node in found.nodes]
    assert tones == [1, 1, 1, 1, 2]
    # A plain block is written as a person writes one: no kind, its words its label.
    assert found.nodes[0] == {"id": "raw-reads", "label": "Raw reads", "properties": {"tone": 1}}
    assert not found.shapes and found.taken == list(range(9))
    assert found.said == "5 shapes and 4 lines"


def test_boxes_in_rows_and_columns_are_a_grid_their_words_laid_on_them_their_labels() -> None:
    found = recognise(grid(), palette=PAPER)
    assert found.layout == {"kind": "grid", "columns": 3, "equal_size": True}
    assert [node["label"] for node in found.nodes] == [
        "Sample prep",
        "Vitrification",
        "Data collection",
        "Motion correction",
        "CTF estimation",
        "Particle picking",
    ]
    # The text boxes laid on the boxes are their words: no part of their own.
    assert len(found.nodes) == 6 and not found.shapes
    assert {node["properties"]["tone"] for node in found.nodes} == {3}
    # A shape glued to one of them is glued to its part.
    assert found.parts["rect0"] == "sample-prep" and found.parts["text0"] == "sample-prep"


def test_frames_with_titles_over_them_are_modules_and_a_line_between_them_joins_their_parts() -> (
    None
):
    found = recognise(modules(), palette=PAPER)
    groups = {group["id"]: group for group in found.groups}
    assert found.top == ["encoder", "decoder"] and found.layout == {"kind": "row"}
    encoder = groups["encoder"]
    assert encoder["label"] == "Encoder" and encoder["role"] == "module"
    assert encoder["children"] == ["embed-tokens", "self-attention", "feed-forward"]
    assert encoder["layout"]["kind"] == "column"
    # The arrow from one frame's edge to the other's joins the parts in them nearest its ends.
    assert lines_of(found) == [("self-attention", "cross-attention")]
    # The frames' grey is the theme's: no colour of their own.
    assert "paint" not in encoder and "fill" not in encoder


def test_a_flow_chart_reads_as_its_kinds_its_branches_words_and_its_way_back() -> None:
    found = recognise(flowchart(), palette=PAPER)
    nodes = nodes_of(found)
    assert {key: node.get("kind", "block") for key, node in nodes.items()} == {
        "start": "terminal",
        "refine-model": "block",
        "converged": "decision",
        "write-map": "io",
        "end": "terminal",
    }
    edges = {(edge["from"], edge["to"]): edge for edge in found.edges}
    assert edges[("converged", "write-map")]["label"] == "yes"
    back = edges[("converged", "refine-model")]
    # Round the side, as drawn; the lines glued to the sides that face are left to the figure.
    assert back["label"] == "no" and (back["depart"], back["arrive"]) == ("east", "east")
    assert "depart" not in edges[("start", "refine-model")]
    assert found.layout == {"kind": "column"}


def test_branches_side_by_side_are_a_row_in_the_column() -> None:
    found = recognise(branches(), palette=PAPER)
    assert found.top == ["load", "resolution", "row", "deposit"]
    row = found.groups[0]
    assert row["children"] == ["build-atoms", "fit-domains"] and row["role"] == "layout"
    nodes = nodes_of(found)
    assert nodes["resolution"]["label"] == "Resolution\n< 3 Å?"
    # Green and red are told apart: two tones.
    assert nodes["build-atoms"]["properties"]["tone"] != nodes["fit-domains"]["properties"]["tone"]
    labels = {(edge["from"], edge["to"]): edge.get("label") for edge in found.edges}
    assert labels[("resolution", "build-atoms")] == "yes"
    assert labels[("resolution", "fit-domains")] == "no"
    assert labels[("build-atoms", "deposit")] is None


def test_what_is_no_part_of_the_diagram_stays_a_shape_attached_to_the_parts() -> None:
    found = recognise(mix(), palette=PAPER, holder="diagram")
    assert len(found.nodes) == 3 and len(found.edges) == 2
    assert found.kept == [5, 6, 7, 8]
    highlight, curve, brace, pointer = found.shapes
    assert highlight["around"] == ["encoder", "latent-z"] and "at" not in highlight
    assert highlight["behind"] is True and highlight["fill_opacity"] == 0.35
    assert (brace["around"], brace["side"]) == (["encoder", "latent-z"], "bottom")
    # A free curve stays one, on the diagram, drawn as large as its parts are now.
    assert curve["kind"] == "pen" and curve["on"] == "diagram"
    # An arrow at a part: glued to it, on the side it was drawn to, and moved with it.
    assert pointer["on"] == "latent-z"
    assert pointer["to"]["part"] == "latent-z" and pointer["to"]["side"] == "top"


def test_fills_take_the_nearest_tone_or_keep_their_own_colour() -> None:
    shapes = [
        box(0, 0, text="Blue", fill="#9fc5e8"),
        box(150, 0, text="Light blue", fill="#cfe2f3"),
        box(300, 0, text="Grey", fill="#eeeeee"),
        box(450, 0, text="Named", fill="accent4-fill"),
        box(600, 0, text="None", fill="none"),
    ]
    found = recognise(shapes, palette=PAPER)
    tones = {node["label"]: node.get("properties", {}) for node in found.nodes}
    assert tones["Blue"] == {"tone": 1} and tones["Light blue"] == {"tone": 1}
    assert tones["Grey"] == {} and tones["None"] == {}
    assert tones["Named"] == {"tone": 4}
    # A colour near no tone of a palette without it is kept: paper's has no cyan... a palette
    # of one blue keeps a green its own.
    one = with_tone_roles(resolve_palette("paper", "#1a5d9b"))
    found = recognise([box(0, 0, text="Green", fill="#93c47d")], palette=one)
    assert found.nodes[0]["properties"] == {"paint-fill": "#93c47d"}
    assert found.notes and "#93c47d" in found.notes[0]


def test_a_circle_with_a_symbol_is_an_operator_and_a_dashed_line_stays_dashed() -> None:
    shapes = [
        box(0, 0, 40, 40, "+", kind="ellipse", fill="none"),
        box(100, 0, 40, 40, "$z$", kind="ellipse", fill="none"),
        box(200, 0, 120, 40, "Done", kind="ellipse", fill="none"),
        arrow([40, 20], [100, 20], dash="dashed", start="triangle"),
        {"kind": "line", "from": [140, 20], "to": [200, 20], "end": "bar"},
    ]
    found = recognise(shapes, palette=PAPER)
    kinds = [(node.get("kind"), node.get("label"), node.get("properties")) for node in found.nodes]
    assert kinds == [
        ("op", None, {"symbol": "+"}),
        ("circle", "$z$", None),
        ("terminal", "Done", None),
    ]
    first, second = found.edges
    assert (first["arrow"], first["line"]) == ("both", "dashed")
    # A bar at its end: inhibition's.
    assert (second["from"], second["to"], second["head"]) == ("z", "done", "inhibition")


def test_a_dark_grey_box_stays_dark_its_words_light_and_dashes_as_lengths_are_dashed() -> None:
    """As an Inkscape drawing imports: a box filled dark grey (a loss, a heading's band) keeps
    its colour, its words drawn light; outlines and lines dashed by their lengths (an SVG's
    dash array) are dashed, or dotted where the dashes are no longer than the line is wide."""

    shapes = [
        box(0, 0, text="Loss", fill="#595959"),
        box(200, 0, text="Light", fill="#f2f2f2", dash=[6.8, 3.4]),
        box(400, 0, text="Dotted", fill="#cfe2f3", dash=[1.5, 3.0]),
        arrow([100, 25], [200, 25], dash=[4.25, 2.83]),
        arrow([300, 25], [400, 25], dash=[1.0, 2.0]),
    ]
    found = recognise(shapes, palette=PAPER)
    nodes = {node["label"]: node for node in found.nodes}
    assert nodes["Loss"]["properties"] == {"paint-fill": "#595959", "paint-label": "#ffffff"}
    assert nodes["Light"].get("properties") is None and nodes["Light"]["line"] == "dashed"
    assert nodes["Dotted"]["line"] == "dotted"
    assert [edge.get("line") for edge in found.edges] == ["dashed", "dotted"]


def test_a_line_whose_head_is_at_its_start_runs_the_other_way() -> None:
    shapes = [
        box(0, 0, text="A"),
        box(200, 0, text="B"),
        arrow([102, 25], [198, 25], start="triangle", end="none"),
    ]
    found = recognise(shapes, palette=PAPER)
    assert lines_of(found) == [("b", "a")] and "arrow" not in found.edges[0]


def test_shapes_with_nothing_of_a_diagram_say_so() -> None:
    with pytest.raises(ValueError, match="reads as a diagram"):
        recognise([{"kind": "highlight", "at": [0, 0], "size": [10, 10]}], palette=PAPER)


# -- in a figure file's own words ---------------------------------------------------------------

FIGURE = """\
# The model, drawn before.
figure:
  id: model
  style: paper
nodes:
- id: x
  kind: text
  label: Input $x$
- id: encoder
  label: Encoder
edges:
- from: x
  to: encoder
"""


def drawn_over(text: str, shapes: list, hide: list | None = None) -> str:
    """``text``, a figure file, with ``shapes`` drawn over it (and some hidden): its words kept."""

    if hide:
        text = text.replace("  style: paper\n", f"  style: paper\n  hide: {hide}\n")
    return text + yaml.safe_dump({"shapes": shapes}, sort_keys=False, allow_unicode=True)


def test_convert_puts_the_parts_in_a_group_where_the_shapes_were_and_they_go() -> None:
    from flexo.freeform import moved

    shapes = [moved(shape, 0, 120) for shape in pipeline()]
    text = drawn_over(FIGURE, shapes)
    result = apply(text, {"do": "convert", "shapes": list(range(len(shapes)))})
    data = yaml.safe_load(result["text"])
    assert result["select"] == ["diagram"] and result["said"] == "5 shapes and 4 lines"
    assert "shapes" not in data and result["text"].startswith("# The model, drawn before.")
    root = next(group for group in data["groups"] if group["id"] == "root")
    # Drawn under the figure's column: after what it holds.
    assert root["children"] == ["x", "encoder", "diagram"]
    diagram = next(group for group in data["groups"] if group["id"] == "diagram")
    assert diagram["role"] == "layout" and diagram["layout"]["kind"] == "row"
    assert len(data["edges"]) == 5
    compile_figure(parse(result["text"], Path.cwd()))


def test_convert_makes_a_new_figure_the_diagram_its_root_laid_out_as_drawn() -> None:
    text = drawn_over("figure:\n  id: drawing\nnodes:\n- id: shape\n  label: ''\n", modules())
    result = apply(text, {"do": "convert", "shapes": list(range(len(modules())))})
    data = yaml.safe_load(result["text"])
    # The new figure's empty shape went: the diagram is the figure.
    assert "shape" not in {node["id"] for node in data["nodes"]}
    root = data["groups"][0]
    assert root == {
        "id": "root",
        "children": ["encoder", "decoder"],
        "layout": {"kind": "row"},
        "role": "canvas",
    }
    assert result["select"] == ["encoder", "decoder"]


def test_convert_keeps_the_rest_attached_and_glues_what_was_glued_to_a_shape_made_a_part() -> None:
    shapes = [*mix(), {"kind": "arrow", "id": "note", "from": [700, 10], "to": {"shape": "enc"}}]
    text = drawn_over(FIGURE, shapes, hide=["lat"])
    assert "hide: ['lat']" in text
    result = apply(text, {"do": "convert", "shapes": list(range(9))})
    data = yaml.safe_load(result["text"])
    kinds = [shape["kind"] for shape in data["shapes"]]
    assert kinds == ["highlight", "pen", "brace", "arrow", "arrow"]
    # Not chosen, the arrow glued to a box made a part is glued to the part.
    assert data["shapes"][-1]["to"]["part"] == "encoder-2"
    # Hidden as the shape, hidden as its part.
    assert data["figure"]["hide"] == ["latent-z"]
    # Written as a person writes shapes: points on one line.
    assert "points: [[" in result["text"]
    compile_figure(parse(result["text"], Path.cwd()))


def test_a_line_drawn_to_a_part_of_the_figure_joins_it() -> None:
    shapes = [box(0, 200, text="Decoder", id="dec"), arrow({"part": "encoder"}, {"shape": "dec"})]
    text = drawn_over(FIGURE, shapes)
    result = apply(text, {"do": "convert", "shapes": [0, 1]})
    data = yaml.safe_load(result["text"])
    assert {"from": "encoder", "to": "decoder"} in data["edges"]


def test_convert_says_what_it_cannot_do() -> None:
    text = drawn_over(FIGURE, [{"kind": "ring", "at": [0, 0], "size": [20, 20]}])
    with pytest.raises(EditError, match="reads as a diagram"):
        apply(text, {"do": "convert", "shapes": [0]})
    with pytest.raises(EditError, match="Choose the shapes"):
        apply(text, {"do": "convert", "shapes": [4]})


def test_the_command_line_makes_shapes_a_figure(tmp_path: Path, capsys) -> None:
    listed = tmp_path / "drawing.yaml"
    listed.write_text(yaml.safe_dump(branches(), allow_unicode=True), encoding="utf-8")
    out = tmp_path / "figure.yaml"
    assert main(["to-parts", str(listed), "-o", str(out)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["figure"]["id"] == "drawing" and len(data["nodes"]) == 5
    assert "5 shapes and 5 lines" in capsys.readouterr().err
    # A figure file's own, by id.
    over = tmp_path / "model.yaml"
    over.write_text(drawn_over(FIGURE, flowchart()), encoding="utf-8")
    assert main(["to-parts", str(over), "--shapes", "start,refine,5"]) == 0
    printed = yaml.safe_load(capsys.readouterr().out)
    assert {"from": "start", "to": "refine-model"} in printed["edges"]


def test_the_agents_tool_makes_a_figures_shapes_its_parts(tmp_path: Path) -> None:
    from flexo.studio.agent import Tools
    from flexo.studio.workspace import Workspace

    (tmp_path / "model.yaml").write_text(drawn_over(FIGURE, flowchart()), encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        tools = Tools(workspace, {"id": "agent", "name": "Claude"})
        said, failed = tools.call("convert_to_figure_parts", {"file": "model.yaml"})
        assert not failed and said[0]["text"].startswith("5 shapes and 5 lines, in model.yaml")
        text = (tmp_path / "model.yaml").read_text(encoding="utf-8")
        doc = workspace.open("model.yaml")
        assert "converged" in doc.document["text"] or "converged" in text
        said, failed = tools.call(
            "convert_to_figure_parts", {"file": "model.yaml", "shapes": ["nothing"]}
        )
        assert failed and "no shape" in said[0]["text"]
    finally:
        workspace.close()
