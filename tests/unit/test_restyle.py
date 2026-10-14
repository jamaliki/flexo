"""An SVG picture's words and colours restyled where it is placed (``flexo.restyle``): set in
a font Flexo has -- the same in every output -- its texts and colours changed by what the
document keeps beside it, keyed to the drawing's elements, and never written to its file."""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo.artwork import load_artwork
from flexo.diagnostics import FlexoError
from flexo.drawing import Text, read_drawing
from flexo.restyle import (
    AS_DRAWN,
    Restyle,
    colour_key,
    described,
    drawn_family,
    restyle_of,
    restyled,
)
from flexo.serialization import parse_figure
from flexo.svg import local_name

INKSCAPE = """\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="105.83334mm" height="58.208332mm" viewBox="0 0 105.83334 58.208332" version="1.1"
   id="svg1" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
   xmlns="http://www.w3.org/2000/svg">
  <g inkscape:label="Layer 1" inkscape:groupmode="layer" id="layer1"
     transform="translate(-47.625,-62.177083)">
    <rect style="fill:#4a90d9;stroke:#1b1b1b;stroke-width:0.79375" id="rect1" width="42.333332"
       height="21.166666" x="52.916668" y="67.46875" ry="2.6458333" />
    <circle style="fill:#e74c3c" id="path1" cx="124.35417" cy="78.052086" r="10.583333" />
    <text xml:space="preserve" x="55.5625" y="101.86458" id="text1"
       style="font-weight:bold;font-size:7.05556px;line-height:1.25;font-family:'Helvetica Neue';
-inkscape-font-specification:'Helvetica Neue, Bold'"><tspan sodipodi:role="line" id="tspan1"
       x="55.5625" y="101.86458">Encoder block</tspan><tspan sodipodi:role="line" id="tspan2"
       style="font-weight:normal;font-size:4.93889px" x="55.5625" y="108.39367"
       >two lines, the second smaller</tspan></text>
    <text xml:space="preserve" x="55.5625" y="117.21041" id="text2"
       style="font-style:italic;font-size:5.64444px;line-height:1.25;font-family:Georgia;fill:#555555"
       ><tspan sodipodi:role="line" id="tspan3" x="55.5625" y="117.21041"
       >Georgia italic note</tspan></text>
    <text xml:space="preserve" x="113.77084" y="101.86458" id="text3"
       style="font-size:4.58611px;line-height:1.25;font-family:'IBM Plex Mono'"
       ><tspan sodipodi:role="line" id="tspan4" x="113.77084" y="101.86458"
       >mono: 12.5 nm</tspan></text>
  </g>
</svg>
"""


@pytest.fixture
def drawing(tmp_path: Path) -> Path:
    path = tmp_path / "drawing.svg"
    path.write_text(INKSCAPE, encoding="utf-8")
    return path


def texts_of(markup: str) -> dict[str, ET.Element]:
    root = ET.fromstring(markup)
    return {
        item.get("id", "").rsplit(".", 1)[-1]: item
        for item in root.iter()
        if local_name(item.tag) == "text"
    }


def read_texts(markup: str) -> dict[str, Text]:
    found = read_drawing(markup)
    return {item.id.rsplit(".", 1)[-1]: item for item in found.walk() if isinstance(item, Text)}


def faces_of(text: Text) -> set[str]:
    return {run.face.family for line in text.lines for run in line.runs if run.text.strip()}


def test_a_drawings_words_are_set_in_the_figures_font_named_outright(drawing: Path) -> None:
    art = restyled(load_artwork("picture", str(drawing)), Restyle(), "Figtree")
    assert art.width == pytest.approx(300.0, abs=0.01) and art.height == pytest.approx(
        165.0, abs=0.01
    )
    for text in texts_of(art.markup).values():
        style = text.get("style")
        assert "font-family:'Figtree', 'IBM Plex Sans'" in style
        assert "inkscape-font-specification" not in style
    # Every output reads the same face: the one named, found as Flexo finds any.
    assert all(faces_of(text) == {"Figtree"} for text in read_texts(art.markup).values())
    # Its places, sizes and anchors are as drawn.
    one = texts_of(art.markup)["text1"]
    assert one.get("x") == "55.5625" and "font-size:7.05556px" in one.get("style")


def test_as_drawn_keeps_each_family_found_and_flexos_fallback_where_none_is(drawing: Path) -> None:
    art = restyled(load_artwork("picture", str(drawing)), Restyle(AS_DRAWN), "Figtree")
    read = read_texts(art.markup)
    assert faces_of(read["text3"]) == {"IBM Plex Mono"}
    assert faces_of(read["text2"]) == {drawn_family("Georgia")}
    assert drawn_family("'No Such Face', serif") == "Latin Modern Roman"
    assert drawn_family("No Such Face") == "IBM Plex Sans"
    assert drawn_family("monospace") == "IBM Plex Mono"


def test_a_family_named_sets_all_of_its_words(drawing: Path) -> None:
    art = restyled(load_artwork("picture", str(drawing)), Restyle("IBM Plex Mono"), "Figtree")
    assert all(faces_of(text) == {"IBM Plex Mono"} for text in read_texts(art.markup).values())


def test_a_texts_words_size_weight_slant_and_colour_are_changed_by_its_id(drawing: Path) -> None:
    restyle = restyle_of(
        None,
        [
            {"id": "text1", "words": "Decoder block\nthree lines\nnow", "bold": False},
            {"id": "text3", "size": 26, "italic": True, "colour": "#c0392b"},
        ],
    )
    art = restyled(load_artwork("picture", str(drawing)), restyle, "Figtree")
    texts = texts_of(art.markup)
    lines = [piece for piece in texts["text1"] if local_name(piece.tag) == "tspan"]
    assert ["".join(piece.itertext()) for piece in lines] == ["Decoder block", "three lines", "now"]
    # A line more is put a line's step under the last, as its lines stand.
    ys = [float(piece.get("y")) for piece in lines]
    assert ys[2] - ys[1] == pytest.approx(ys[1] - ys[0], abs=1e-4)
    assert len({piece.get("id") for piece in lines if piece.get("id")}) == 2
    read = read_texts(art.markup)
    assert {run.weight for line in read["text1"].lines for run in line.runs} == {400}
    mono = read["text3"]
    # 26 points at the drawing's own size (300pt wide over 105.8 units).
    assert mono.lines[0].runs[0].size * 300.0 / 105.83334 == pytest.approx(26.0, abs=0.01)
    assert mono.lines[0].runs[0].italic and mono.lines[0].runs[0].fill == "#c0392b"


def test_a_text_made_larger_keeps_its_lines_apart_in_step(drawing: Path) -> None:
    art = restyled(
        load_artwork("picture", str(drawing)),
        restyle_of(None, [{"id": "text1", "size": 40}]),
        "Figtree",
    )
    lines = [piece for piece in texts_of(art.markup)["text1"] if local_name(piece.tag) == "tspan"]
    ratio = 40.0 / 20.0
    assert float(lines[1].get("y")) - float(lines[0].get("y")) == pytest.approx(
        (108.39367 - 101.86458) * ratio, abs=1e-3
    )
    assert lines[1].get("style").endswith("px") and float(
        lines[1].get("style").split("font-size:")[1][:-2]
    ) == pytest.approx(4.93889 * ratio, abs=1e-4)


def test_a_text_of_one_line_set_in_itself_is_given_lines(tmp_path: Path) -> None:
    path = tmp_path / "plain.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
        '<text x="10" y="40" font-size="12" font-weight="bold">Hello</text>'
        '<text x="10" y="80" font-size="12">World</text></svg>'
    )
    restyle = restyle_of(
        None, [{"text": 1, "words": "Hello\nthere"}, {"text": 2, "words": "Earth"}]
    )
    art = restyled(load_artwork("picture", str(path)), restyle, "Figtree")
    first, second = (
        item for item in ET.fromstring(art.markup).iter() if local_name(item.tag) == "text"
    )
    assert ["".join(piece.itertext()) for piece in first] == ["Hello", "there"]
    assert [float(piece.get("y")) for piece in first] == [40.0, 55.0]
    assert "".join(second.itertext()) == "Earth"


def test_a_change_to_a_text_the_file_no_longer_has_is_passed_over(drawing: Path) -> None:
    restyle = restyle_of(
        None,
        [
            {"id": "gone", "words": "Lost"},
            {"text": 7, "bold": True},
            {"id": "text2", "words": "Kept"},
        ],
    )
    art = restyled(load_artwork("picture", str(drawing)), restyle, "Figtree")
    words = {key: "".join(text.itertext()) for key, text in texts_of(art.markup).items()}
    assert words["text2"] == "Kept" and "Lost" not in art.markup
    # (A text with an id is never taken for one counted by its place.)
    assert words["text1"] == "Encoder blocktwo lines, the second smaller"


def test_a_colour_is_drawn_in_another_wherever_it_is_used(drawing: Path) -> None:
    restyle = restyle_of(colours={"#4A90D9": "#2e7d32", "black": "#1f4e79"})
    art = restyled(load_artwork("picture", str(drawing)), restyle, "Figtree")
    assert "#4a90d9" not in art.markup.lower() and "fill:#2e7d32" in art.markup
    read = read_texts(art.markup)
    # Words left black by default are drawn in black's swap; words painted are as painted.
    assert read["text1"].lines[0].runs[0].fill == "#1f4e79"
    assert read["text2"].lines[0].runs[0].fill == "#555555"


def test_words_reaching_past_the_page_grow_the_picture_to_hold_them(drawing: Path) -> None:
    artwork = load_artwork("picture", str(drawing))
    grown = restyled(artwork, restyle_of(None, [{"id": "text3", "size": 30}]), "Figtree")
    assert grown.width > artwork.width + 1.0 and grown.height == pytest.approx(artwork.height)
    root = ET.fromstring(grown.markup)
    view = [float(value) for value in root.get("viewBox").split()]
    assert view[2] * artwork.width / 105.83334 == pytest.approx(grown.width, rel=1e-6)
    assert root.get("width").endswith("mm")
    found = read_drawing(grown.markup)
    right = max(
        line.right for item in found.walk() if isinstance(item, Text) for line in item.lines
    )
    assert right <= found.width


def test_a_drawing_without_words_or_colours_changed_is_as_it_was(tmp_path: Path) -> None:
    path = tmp_path / "shapes.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect width="5" height="5" fill="#123456"/></svg>'
    )
    artwork = load_artwork("picture", str(path))
    assert restyled(artwork, Restyle(), "Figtree") is artwork
    swapped = restyled(artwork, restyle_of(colours={"#123456": "#abcdef"}), "Figtree")
    assert 'fill="#abcdef"' in swapped.markup


def test_a_drawing_carried_apart_from_the_page_carries_its_bundled_faces(drawing: Path) -> None:
    artwork = load_artwork("picture", str(drawing))
    carried = restyled(artwork, Restyle(), "Figtree", embed=True)
    sheet = ET.fromstring(carried.markup)[0]
    assert (
        local_name(sheet.tag) == "style"
        and sheet.text.count("@font-face{font-family:'Figtree'") >= 2
    )
    shared = restyled(artwork, Restyle(), "Figtree", embed=True, shared="Figtree")
    assert "@font-face" not in shared.markup


def test_a_panel_is_told_the_texts_in_reading_order_and_the_colours(drawing: Path) -> None:
    said = described(load_artwork("drawing", str(drawing)))
    assert [entry["id"] for entry in said["texts"]] == ["text1", "text3", "text2"]
    first = said["texts"][0]
    assert first["lines"] == ["Encoder block", "two lines, the second smaller"]
    assert first["size"] == pytest.approx(20.0, abs=0.05) and first["bold"] and not first["italic"]
    assert said["texts"][2] == {
        "id": "text2",
        "lines": ["Georgia italic note"],
        "size": 16.0,
        "bold": False,
        "italic": True,
        "colour": "#555555",
        "family": "Georgia",
    }
    colours = {entry["colour"]: entry for entry in said["colours"]}
    assert list(colours) == ["#4a90d9", "#1b1b1b", "#e74c3c", "#555555", "#000000"]
    assert colours["#1b1b1b"]["outline"] and not colours["#1b1b1b"]["fill"]


def test_what_a_document_writes_is_read_and_what_does_not_read_is_said() -> None:
    restyle = restyle_of(
        "drawn",
        [{"id": "text1", "words": "A\nB\n", "size": 12, "bold": True}],
        {"#fff": "rgb(0, 0, 255)"},
    )
    assert restyle.font == AS_DRAWN and restyle.texts[0].words == "A\nB"
    assert restyle.colours == (("#ffffff", "#0000ff"),)
    assert restyle.texts[0].record() == {"id": "text1", "words": "A\nB", "size": 12.0, "bold": True}
    for bad in (
        {"font": 3},
        {"texts": {"id": "x"}},
        {"texts": [{"words": "no key"}]},
        {"texts": [{"id": "a", "size": "big"}]},
        {"texts": [{"id": "a", "shade": 1}]},
        {"colours": {"#fff": "nothing"}},
    ):
        with pytest.raises(ValueError):
            restyle_of(**bad)
    assert (
        colour_key("#ABC") == "#aabbcc"
        and colour_key("none") is None
        and colour_key("url(#g)") is None
    )


def test_a_figures_picture_is_drawn_restyled_in_every_output(tmp_path: Path, drawing: Path) -> None:
    from flexo.compiler import compile_figure
    from flexo.pdf import write_pdf

    spec = parse_figure(
        {
            "figure": {"id": "f", "font": "Figtree"},
            "nodes": [
                {
                    "id": "pic",
                    "kind": "image",
                    "width": "200pt",
                    "properties": {
                        "source": str(drawing),
                        "texts": [{"id": "text2", "words": "Restyled note", "bold": True}],
                        "colours": {"#e74c3c": "#2e7d32"},
                    },
                }
            ],
        }
    )
    compilation = compile_figure(spec)
    text = compilation.document.text
    assert "Restyled note" in text and "#2e7d32" in text and "#e74c3c" not in text
    found = read_drawing(text)
    words = [item for item in found.walk() if isinstance(item, Text)]
    assert {face for item in words for face in faces_of(item)} == {"Figtree"}
    pdf = tmp_path / "f.pdf"
    write_pdf(found, pdf, title="f")
    assert b"Figtree" in pdf.read_bytes() and b"Georgia" not in pdf.read_bytes()
    # The file is never changed.
    assert drawing.read_text(encoding="utf-8") == INKSCAPE


def test_a_figures_picture_whose_changes_do_not_read_says_so(drawing: Path) -> None:
    from flexo.compiler import compile_figure

    spec = parse_figure(
        {
            "figure": {"id": "f"},
            "nodes": [
                {
                    "id": "pic",
                    "kind": "image",
                    "properties": {"source": str(drawing), "texts": [{"words": "x"}]},
                }
            ],
        }
    )
    with pytest.raises(FlexoError) as caught:
        compile_figure(spec)
    assert caught.value.diagnostics[0].code == "image.restyle.invalid"


def test_the_studio_tells_a_pictures_panel_its_words_and_draws_its_thumbnail(
    tmp_path: Path, drawing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    from flexo.studio.server import start

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    (tmp_path / "figure.yaml").write_text("figure: {id: f}\nnodes:\n- id: a\n", encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        query = urllib.parse.urlencode(
            {"file": "figure.yaml", "path": drawing.name, "token": workspace.token}
        )
        with opener.open(f"{url}/api/drawing?{query}") as response:
            said = json.loads(response.read())
        assert [entry["id"] for entry in said["texts"]] == ["text1", "text3", "text2"] and said[
            "stamp"
        ]
        query = urllib.parse.urlencode(
            {
                "file": "figure.yaml",
                "path": drawing.name,
                "token": workspace.token,
                "family": "Figtree",
                "texts": json.dumps([{"id": "text1", "words": "Thumb"}]),
            }
        )
        with opener.open(f"{url}/api/drawn?{query}") as response:
            assert response.headers["Content-Type"] == "image/svg+xml"
            shown = response.read().decode()
        assert "Thumb" in shown and "@font-face{font-family:'Figtree'" in shown
        outside = urllib.parse.urlencode(
            {"file": "figure.yaml", "path": "../elsewhere.svg", "token": workspace.token}
        )
        with pytest.raises(urllib.error.HTTPError):
            opener.open(f"{url}/api/drawing?{outside}")
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


# A figure Flexo wrote, edited in Inkscape: its fonts carried in the file as data, its words
# sized with their unit as attributes (``18px``), a panel of it a nested drawing.
FONT = "data:font/otf;base64,T1RUTwANAIAAAwBQ"
REEDITED = f"""\
<svg xmlns="http://www.w3.org/2000/svg"
   xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   width="350mm" height="100mm" viewBox="0 0 992 283" inkscape:version="1.4.3">
  <defs><style>@font-face{{font-family:'Fira Math';
    src:url({FONT}) format('opentype')}}</style></defs>
  <g id="root">
    <text id="title.label" x="496" y="34" text-anchor="middle" font-family="'DejaVu Sans'"
       font-size="18px" fill="#242126">Annealed SMC</text>
    <svg id="stage" x="15" y="85" width="230" height="160" viewBox="0 0 310 215">
      <rect x="1" y="1" width="308" height="213" rx="8" fill="#ffffff" stroke="#d4d0d8"
         stroke-width="2px" opacity="50%"/>
      <text id="text2" x="155" y="28" font-family="'DejaVu Sans'" font-size="15px"
         font-weight="bold" text-anchor="middle">1. Sample the prior</text>
    </svg>
    <text id="maths" x="300" y="260" font-family="'Fira Math'" font-size="12pt">E<tspan
       font-size="65%" baseline-shift="sub">R1</tspan></text>
    <text id="note" x="600" y="250" font-family="'DejaVu Sans'" font-size="10px"><tspan
       x="600" dy="0">Schematic poses,</tspan><tspan x="600" dy="1.2em">two lines</tspan></text>
  </g>
</svg>
"""


def test_a_flexo_figure_edited_in_inkscape_is_read_listed_and_restyled(tmp_path: Path) -> None:
    """Flexo's own SVG, edited in Inkscape, was refused as a picture -- its fonts, carried in
    the file as data, read as a reference outside it -- and, once read, its words were not:
    a size written with its unit (``18px``) stopped the reading, so its panel listed no words
    and its thumbnail and pictured drawing carried none of the faces they are set in."""

    path = tmp_path / "figure.svg"
    path.write_text(REEDITED, encoding="utf-8")
    art = load_artwork("picture", str(path))
    texts = read_texts(art.markup)
    # A length is in its drawing's user units: a pixel is one, a point four thirds of one,
    # an em and a percentage shares of the font's size.
    assert texts["label"].size == pytest.approx(18.0)
    assert texts["text2"].size == pytest.approx(15.0 * 230 / 310)  # its panel's own scale
    maths = texts["maths"]
    assert maths.size == pytest.approx(16.0)
    runs = [run for line in maths.lines for run in line.runs]
    assert runs[1].size == pytest.approx(16.0 * 0.65)
    assert runs[1].baseline > runs[0].baseline  # lowered, as a subscript is
    note = texts["note"]
    assert note.lines[1].baseline - note.lines[0].baseline == pytest.approx(1.2 * 10.0)
    found = described(art)["texts"]
    assert sorted(text["lines"] for text in found) == sorted(
        [["Annealed SMC"], ["1. Sample the prior"], ["ER1"], ["Schematic poses,", "two lines"]]
    )
    restyled_art = restyled(art, Restyle(), "Figtree", embed=True)
    assert "data:font/otf" in restyled_art.markup or "data:font/" in restyled_art.markup
    for text in texts_of(restyled_art.markup).values():
        assert "Figtree" in (text.get("style") or "")
