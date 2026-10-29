"""An agent reads a document a little at a time, sees its pages as a sheet, outlined or at a build
step, is taught by a short brief and topics with examples that draw, and hears what each edit
did and what to do next -- through the same tools over MCP and in the studio's Assistant."""

from __future__ import annotations

import io
import json
import re
import struct
import time
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from flexo.studio import agent_guides, agent_look, agent_read
from flexo.studio.agent import INSTRUCTIONS, TOOLS, Tools
from flexo.studio.figure_guides import SNIPPETS
from flexo.studio.figure_kind import FigureKind
from flexo.studio.workspace import Workspace

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}

FIGURE = """\
figure:
  id: model
  style: paper
nodes:
- id: x
  kind: text
  label: Input $x$
- id: encoder
  label: Encoder
- id: decoder
  label: Decoder TODO
- id: y
  kind: text
  label: Output $y$
groups:
- id: model
  children: [encoder, decoder]
  layout: {kind: column}
  label: Model
- id: root
  children: [x, model, y]
  layout: {kind: row}
edges:
- from: x
  to: encoder
- from: encoder
  to: decoder
- from: decoder
  to: y
shapes:
- {kind: ring, around: [decoder]}
- {kind: arrow, id: hint, from: {part: x, side: top}, to: {part: encoder, side: top}}
"""


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def figure(tmp_path: Path):
    (tmp_path / "figure.yaml").write_text(FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        yield workspace, Tools(workspace, {"id": "agent", "name": "Claude"})
    finally:
        workspace.close()


def _texts(blocks: list[dict]) -> str:
    return "\n".join(block["text"] for block in blocks if block["type"] == "text")


def _images(blocks: list[dict]) -> list[tuple[int, int]]:
    import base64

    return [
        agent_look.png_size(base64.b64decode(block["source"]["data"]))
        for block in blocks
        if block["type"] == "image"
    ]


def _png(width: int = 16, height: int = 12) -> bytes:
    rows = b"".join(b"\x00" + bytes([200, 80, 80]) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + tag + data + crc

    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows))
    ) + chunk(b"IEND", b"")


# -- look --


def test_a_figure_is_looked_at_as_large_as_a_slide_and_outlined_part_by_part(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call("look", {"file": "figure.yaml", "annotate": True})
    assert not failed, blocks
    (size,) = _images(blocks)
    assert max(size) == agent_look.LOOK_EDGE
    said = _texts(blocks)
    # Each part, group and shape named as the YAML has it, with where it is.
    assert re.search(r"- encoder: nodes\[1\] \(block\) at \[\d+, \d+\], size \[\d+, \d+\]", said)
    assert "- model: groups[0] (group)" in said
    assert "- shapes[1] hint: shapes[1] (arrow)" in said
    assert "- root" not in said  # (the root holds everything: not outlined)


def test_annotating_marks_only_what_is_drawn_and_puts_labels_on_the_page() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200pt" height="100pt" '
        'viewBox="0 -10 200 100"><rect id="a" x="10" y="0" width="50" height="20" fill="#000"/>'
        '<g id="b"><rect x="120" y="40" width="30" height="30" fill="#f00"/></g></svg>'
    )
    marks = [
        agent_look.Mark("a", "nodes[0]", "a"),
        agent_look.Mark("b", "nodes[1]", "b", sort="part"),
        agent_look.Mark("gone", "nodes[2]", "gone"),
    ]
    drawn, placed = agent_look.annotated(svg, marks)
    assert [mark.id for mark, _ in placed] == ["a", "b"]
    # (Boxes from the view box's corner; the outlines are put back where it is.)
    assert placed[0][1] == pytest.approx((10, 10, 60, 30))
    assert 'transform="translate(0 -10)"' in drawn and drawn.endswith("</svg>")
    assert agent_look.listed(placed)[0] == "- a: nodes[0] at [10, 10], size [50, 20]"
    assert agent_look.png_size(agent_look.picture(drawn))[0] == agent_look.LOOK_EDGE


def test_a_sheet_tiles_pages_numbered_in_one_small_picture() -> None:
    page = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="960pt" height="540pt" '
        'viewBox="0 0 960 540"><rect width="960" height="540" fill="#fff"/>'
        '<text x="40" y="80" font-size="40">A slide</text></svg>'
    )
    data = agent_look.sheet([(number, page, number == 3) for number in range(1, 13)])
    width, height = agent_look.png_size(data)
    assert width <= agent_look.SHEET_EDGE and height < width
    # Twelve slides cost less than two pages looked at one by one.
    assert width * height < 2 * 960 * 540


def test_a_sheet_lifts_the_cap_of_pages_and_outlines_are_left_to_single_pages(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call(
        "look", {"file": "figure.yaml", "sheet": True, "annotate": True, "pages": [1, 7]}
    )
    assert not failed
    said = _texts(blocks)
    assert "There is no page 7; figure.yaml has 1." in said
    assert "A sheet of figure.yaml's pages 1, each numbered above" in said
    assert "Outlines are drawn on single pages" in said
    assert len(_images(blocks)) == 1
    assert agent_look.MAX_SHEET > agent_look.MAX_LOOK


def test_a_step_counts_from_one(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call("look", {"file": "figure.yaml", "step": 0})
    assert failed and "step counts from 1" in blocks[0]["text"]
    # A page of one state is drawn whole at any step.
    blocks, failed = tools.call("look", {"file": "figure.yaml", "step": 3})
    assert not failed and len(_images(blocks)) == 1


# -- outline, excerpts and the selection --


def test_the_outline_of_a_figure_says_its_parts_lines_shapes_and_what_is_selected(figure) -> None:
    workspace, tools = figure
    workspace.open("figure.yaml")
    workspace.set_presence(
        PERSON, "figure.yaml", {"label": "Figure · Encoder", "id": "encoder"}, None, "c"
    )
    blocks, failed = tools.call("outline", {"file": "figure.yaml"})
    assert not failed
    said = blocks[0]["text"]
    assert said.splitlines()[:3] == [
        "figure.yaml (figure), version 1.",
        "Ada has selected nodes[1] (encoder).",
        "Figure model: style paper.",
    ]
    assert "- root (group: row)\n  - x: text “Input $x$”" in said
    assert "  - model (group: column) “Model”\n    - encoder: block “Encoder”" in said
    assert "Lines (3): x → encoder; encoder → decoder; decoder → y" in said
    assert "- shapes[1] hint: arrow" in said
    assert "TODOs: 1." in said and "No warnings." in said
    listed, _ = tools.call("list_documents", {})
    assert (
        "Ada is looking at figure.yaml, Figure · Encoder; selected: nodes[1] (encoder)."
        in (listed[0]["text"])
    )


def test_todos_are_the_word_in_capitals_alone() -> None:
    assert agent_read.todos({"a": "TODO: a figure", "b": ["todo", "TODOs", "x TODO y"]}) == 2


def test_an_excerpt_is_the_items_line_for_line_as_the_whole_text_has_them() -> None:
    text = (
        "deck: {id: a}\nslides:\n- title: One\n  body:\n  - text: a\n# a comment\n"
        "- title: Two\n-\n  title: Three\nfigures: {}\n"
    )
    assert agent_read.items(text, "slides") == [(2, 6), (6, 7), (7, 9)]
    cut = agent_read.excerpt(text, "slides", [2, 3, 4])
    assert "── slide 2 ──\n- title: Two\n" in cut
    assert "── slide 3 ──\n-\n  title: Three\n" in cut
    assert "there is no slide 4; there are 3" in cut
    for number in (1, 2, 3):
        piece = agent_read.excerpt(text, "slides", [number]).split("──\n", 1)[1]
        assert piece in text


def test_only_a_deck_is_read_slide_by_slide(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call("read_document", {"file": "figure.yaml", "slides": [1]})
    assert failed and "only a deck is read slide by slide" in blocks[0]["text"]


# -- what an edit did, and what next --


def test_an_edit_says_what_it_changed_what_it_deleted_and_what_to_look_at_next(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call(
        "edit_document", {"file": "figure.yaml", "old": "  label: Encoder", "new": "  label: Coder"}
    )
    assert not failed
    said = blocks[0]["text"]
    assert said.startswith("Changed figure.yaml: now version 2.\n")
    assert "What changed: renamed “Encoder” to “Coder”." in said
    assert "Warning" not in said
    assert "Next: look at page 1 once (look, pages: [1]). Done when" in said
    assert "report it as a Flexo bug; don't nudge places or sizes" in said
    blocks, failed = tools.call(
        "edit_document", {"file": "figure.yaml", "old": "- from: decoder\n  to: y\n", "new": ""}
    )
    said = blocks[0]["text"]
    assert not failed and "Warning -- this deleted: the line from decoder to y. If that is" in said
    blocks, failed = tools.call(
        "edit_document",
        {"file": "figure.yaml", "old": "- id: y\n  kind: text\n  label: Output $y$\n", "new": ""},
    )
    said = blocks[0]["text"]
    # (A part deleted that its group still names: a problem, which blocks.)
    assert not failed and "Warning -- this deleted: the part y \u201cOutput $y$\u201d" in said
    assert said.endswith("Nothing else until they are gone.")
    blocks, _ = tools.call(
        "edit_document",
        {"file": "figure.yaml", "old": "- {kind: ring, around: [decoder]}\n", "new": ""},
    )
    assert "Warning -- this deleted: 1 shape." in blocks[0]["text"]


def test_problems_block_and_an_unchanged_document_says_nothing_more(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call(
        "edit_document", {"file": "figure.yaml", "old": "label: Model", "new": "label: Model"}
    )
    assert not failed and blocks[0]["text"] == "figure.yaml is unchanged (version 1)."
    lines = agent_report_lines(["the figure has no root"])
    assert lines[-1].startswith("Blocking: the problems above. Next: fix them")


def agent_report_lines(problems: list[str]) -> list[str]:
    from flexo.studio import agent_report

    return agent_report.lines(FigureKind(), {"text": FIGURE}, {"text": FIGURE}, problems)


# -- guides --


def test_the_figure_brief_is_short_names_live_tools_and_lists_the_topics(figure) -> None:
    _, tools = figure
    opened, failed = tools.call("open_document", {"file": "figure.yaml"})
    assert not failed
    brief = opened[0]["text"]
    assert brief.startswith("A flexo figure file") and brief == FigureKind().brief()
    lines = brief.splitlines()
    assert len(lines) <= 95 and max(len(line) for line in lines) <= 100
    for tool in ("outline", "read_document", "edit_document", "look", "guide", "status"):
        assert re.search(rf"\b{tool}\b", brief)
    for topic in FigureKind().topics():
        assert f"  {topic}: " in brief
    # Given once; the whole guide is a topic away.
    again, _ = tools.call("open_document", {"file": "figure.yaml"})
    assert len(again) == 1
    whole, failed = tools.call("guide", {"topic": "reference", "kind": "figure"})
    assert not failed and whole[0]["text"] == FigureKind().guide()


def test_a_brief_names_only_tools_and_arguments_there_are() -> None:
    assert agent_guides.written("{tool:look} with {arg:look.sheet}") == "look with sheet"
    with pytest.raises(ValueError, match="none of: peek"):
        agent_guides.written("{tool:peek}")
    with pytest.raises(ValueError, match=r"none of: look\.zoom"):
        agent_guides.written("{arg:look.zoom}")


def test_the_figure_guide_is_cut_into_topics_and_nothing_of_it_is_lost() -> None:
    from flexo.studio.figure_kind import GUIDE

    topics = FigureKind().topics()
    assert agent_guides.MORE not in topics
    # Every word of the guide is in one topic, once.
    words = sorted(re.sub(r"\s", "", "".join(topic.text for topic in topics.values())))
    assert words == sorted(re.sub(r"\s", "", GUIDE))
    assert topics["insets"].text.startswith("A zoom inset, kind: inset")
    assert topics["structures"].text.startswith("A molecule's")
    assert "Genetics:" in topics["biology"].text and "Proteins:" in topics["biology"].text


def test_a_topic_comes_with_its_examples_and_a_shared_name_goes_to_the_kind_in_hand(figure) -> None:
    _, tools = figure
    blocks, failed = tools.call("guide", {"topic": "shapes", "kind": "figure"})
    assert not failed
    said = blocks[0]["text"]
    assert said.startswith("Figure: shapes -- Marks drawn over the figure")
    assert "Examples (each draws as it is):" in said and "kind: ring, around: [decoder]" in said
    listed, _ = tools.call("guide", {})
    assert "Figure topics (guide(topic), kind: figure):" in listed[0]["text"]
    assert (
        "Theme topics (guide(topic), kind: theme):\n  reference: the whole guide"
        in listed[0]["text"]
    )
    _, failed = tools.call("guide", {"topic": "nothing"})
    assert failed
    # An agent briefed on figures alone is given a figure's topic where a deck has one too.
    two = {
        "deck": NS(
            title="Deck", topics=lambda: {"shapes": agent_guides.Topic("shapes", "deck", "D")}
        ),
        "figure": FigureKind(),
    }
    assert agent_guides.answer(two, "shapes", None).startswith("Deck: shapes")
    assert agent_guides.answer(two, "shapes", None, {"figure"}).startswith("Figure: shapes")


@pytest.mark.parametrize(
    ("topic", "snippet"),
    [(topic, snippet) for topic, snippets in SNIPPETS.items() for snippet in snippets],
    ids=lambda value: value if isinstance(value, str) else value.name,
)
def test_every_figure_example_draws_without_a_warning(tmp_path: Path, topic: str, snippet) -> None:
    for name, content in snippet.files.items():
        (tmp_path / name).write_bytes(_png() if content == b"png" else content)
    drawing = FigureKind().draw({"text": snippet.yaml}, tmp_path)
    assert drawing.pages, topic
    assert [m.text for m in drawing.messages if m.severity in ("error", "warning")] == []


# -- the same tools everywhere --


def test_the_instructions_name_the_new_habits() -> None:
    names = {tool["name"] for tool in TOOLS}
    assert {"outline", "guide", "look", "read_document", "edit_document"} <= names
    for word in ("outline", "guide(topic)", "look once", "Flexo bug"):
        assert word in INSTRUCTIONS


def test_mcp_and_the_assistant_are_given_the_same_tools(tmp_path: Path) -> None:
    from flexo.studio.assistant import Assistant
    from flexo.studio.mcp import serve

    out = io.StringIO()
    serve(
        tmp_path,
        io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"),
        out,
    )
    listed = json.loads(out.getvalue())["result"]["tools"]
    assert [tool["name"] for tool in listed] == [tool["name"] for tool in TOOLS]
    look = next(tool for tool in listed if tool["name"] == "look")
    assert {"sheet", "annotate", "step"} <= set(look["inputSchema"]["properties"])

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(())

        def get_final_message(self):
            return NS(content=[], stop_reason="end_turn")

    requests: list[dict] = []

    def stream(**request):
        requests.append(request)
        return Stream()

    workspace = Workspace(tmp_path)
    try:
        assistant = Assistant(workspace, client=NS(beta=NS(messages=NS(stream=stream))))
        assistant.ask("Hello", {}, PERSON)
        deadline = time.monotonic() + 5
        while (assistant.running or not requests) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert [tool["name"] for tool in requests[0]["tools"]] == [tool["name"] for tool in TOOLS]
    finally:
        workspace.close()


def test_the_assistant_is_told_where_the_selection_is_in_the_yaml(figure) -> None:
    from flexo.studio.assistant import _context

    workspace, _ = figure
    workspace.open("figure.yaml")
    said = _context(
        {"file": "figure.yaml", "where": {"label": "Figure · Encoder", "id": "encoder"}}, workspace
    )
    assert said.splitlines()[1:] == [
        "Selected: Figure · Encoder.",
        "Selected, in the YAML: nodes[1] (encoder).",
    ]


def test_a_figure_without_a_root_group_is_outlined_whole(tmp_path) -> None:
    from flexo.studio.figure_agent import outline

    text = (
        "figure: {id: f}\nnodes:\n- {id: a, label: A}\n- {id: b}\n"
        "groups:\n- {id: pair, children: [a], layout: {kind: row}}\n"
    )
    said = outline({"text": text}, NS(pages=[], messages=[]))
    assert said[1:4] == ["Parts:", "- pair (group: row)", "  - a: block “A”"]
    assert said[4] == "- b: block"
