"""What is copied out of Flexo: the parts chosen cut out of their drawing, and each form
another app pastes (``flexo.copied``, the studio's ``copying`` and ``copyout.js``)."""

from __future__ import annotations

import base64
import json
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest

from flexo.copied import HELD, MARGIN, PNG_PIXELS, Copied, cut_out, with_resolution
from flexo.drawing import ink_bounds, read_drawing

FIGURE = """
figure: {id: fig, style: paper}
nodes:
- {id: a, label: Alpha}
- {id: b, label: Beta}
- {id: c, label: Gamma}
groups:
- {id: pair, children: [a, b], layout: {kind: row}, label: Pair}
- {id: root, children: [pair, c], layout: {kind: column}}
edges:
- {from: a, to: b, label: next}
- {from: b, to: c}
shapes:
- {kind: ring, around: [c]}
"""


@pytest.fixture(scope="module")
def drawn() -> str:
    """The figure as the studio draws it for its page: its fonts named, not carried."""

    from flexo.studio.figure_kind import FigureKind
    from flexo.svg_resources import fonts_linked

    with fonts_linked():
        drawing = FigureKind().draw({"text": FIGURE}, Path("."), {})
    assert drawing.pages, [message.text for message in drawing.messages]
    return drawing.pages[0].svg


def _ids(svg: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', svg))


def _page(svg: str) -> tuple[list[float], str, str]:
    root = ET.fromstring(svg)
    return (
        [float(value) for value in root.get("viewBox").split()],
        root.get("width"),
        root.get("height"),
    )


def test_parts_chosen_are_cut_out_alone_on_a_page_just_big_enough(drawn: str) -> None:
    cut = cut_out(drawn, ["a", "b", "edge.1.a-to-b"])
    ids = _ids(cut)
    assert {"a", "b", "edge.1.a-to-b"} <= ids
    # What was not chosen is gone: the other part, its line, the ring round it, the canvas.
    assert not ids & {"c", "edge.2.b-to-c", "shapes.0", "canvas.background"}
    # The groups round them stay, for their places, marked as only holding them.
    assert 'id="pair"' in cut and HELD in cut
    view, width, height = _page(cut)
    left, top, right, bottom = ink_bounds(read_drawing(cut))
    # Its page is what it draws and the margin round it, in points.
    assert left == pytest.approx(MARGIN, abs=0.01) and top == pytest.approx(MARGIN, abs=0.01)
    assert view[2] - right == pytest.approx(MARGIN, abs=0.01)
    assert view[3] - bottom == pytest.approx(MARGIN, abs=0.01)
    assert width.endswith("pt") and float(width.removesuffix("pt")) == pytest.approx(
        view[2], abs=0.01
    )
    assert float(height.removesuffix("pt")) == pytest.approx(view[3], abs=0.01)


def test_a_group_or_a_shape_drawn_over_the_figure_is_cut_out_whole(drawn: str) -> None:
    group = cut_out(drawn, ["pair"])
    assert {"a", "b", "edge.1.a-to-b", "pair"} <= _ids(group)
    assert "c" not in _ids(group)
    ring = cut_out(drawn, ["shapes.0"])
    assert "shapes.0" in _ids(ring) and not {"a", "b", "c"} & _ids(ring)
    # The ring is round Gamma: its page is the ring's size, not the figure's.
    assert _page(ring)[0][2] < _page(drawn)[0][2] / 2


def test_nothing_named_is_the_whole_page(drawn: str) -> None:
    whole = cut_out(drawn)
    assert _page(whole)[0] == _page(drawn)[0]
    assert _ids(drawn) == _ids(whole)


def test_what_is_not_drawn_is_not_copied(drawn: str) -> None:
    with pytest.raises(ValueError):
        cut_out(drawn, ["no-such-part"])
    empty = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g id="g"/></svg>'
    with pytest.raises(ValueError):
        cut_out(empty, ["g"])


SLIDE = """<svg xmlns="http://www.w3.org/2000/svg" id="slide1" width="338.66667mm" height="190.5mm"
  viewBox="0 0 960 540">
  <rect id="canvas.background" width="960" height="540" fill="#ffffff"/>
  <g id="slide1.content" data-flexo-editing="">
    <text id="slide1.title" x="48" y="76" font-family="Figtree" font-size="30"
      data-flexo-placeholder="Title" opacity="0.38">Title</text>
    <g id="slide1.left">
      <rect id="slide1.left.0" x="100" y="100" width="200" height="50" fill="#1a5d9b"/>
    </g>
    <image id="slide1.left.1" x="400" y="100" width="64" height="32"
      href="/api/picture?path=photo.png&amp;v=1&amp;token=t"/>
  </g>
  <g id="presented.slide1.content" display="none" data-flexo-presented="">
    <rect id="presented.slide1.left.0" x="100" y="300" width="200" height="50" fill="#c0504d"/>
  </g>
</svg>"""


def test_a_slide_copied_whole_is_the_slide_as_presented() -> None:
    whole = cut_out(SLIDE)
    # What is there only while editing -- a placeholder's faint words, the slide edited where
    # one presented is kept beside it -- is gone; the slide presented is shown.
    assert "Title" not in whole and "slide1.left.0" not in _ids(whole)
    assert "presented.slide1.left.0" in _ids(whole) and 'display="none"' not in whole
    assert _page(whole)[0] == [0, 0, 960, 540]


def test_an_object_copied_from_a_slide_is_the_one_edited_its_picture_carried() -> None:
    asked = []

    def picture(href: str) -> str | None:
        asked.append(href)
        return "data:image/png;base64," + base64.b64encode(_png(4, 2)).decode()

    cut = cut_out(SLIDE, ["slide1.left.0", "slide1.left.1"], picture=picture)
    assert {"slide1.left.0", "slide1.left.1"} <= _ids(cut)
    assert "presented.slide1.left.0" not in _ids(cut) and "Title" not in cut
    assert asked == ["/api/picture?path=photo.png&v=1&token=t"]
    assert "data:image/png;base64," in cut
    view = _page(cut)[0]
    assert view[0] == pytest.approx(100 - MARGIN) and view[2] == pytest.approx(364 + 2 * MARGIN)
    # A picture the studio cannot carry is left out, not left pointing at the page's address.
    alone = cut_out(SLIDE, ["slide1.left.1", "slide1.left.0"], picture=lambda href: None)
    assert "<image" not in alone and "slide1.left.0" in _ids(alone)


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_each_form_of_a_copy_is_drawn_once_at_its_size(drawn: str) -> None:
    copied = Copied(cut_out(drawn, ["pair"]), title="Pair")
    width, height = copied.size
    pdf = copied.pdf()
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1
    box = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", pdf)
    assert box and float(box.group(1)) == pytest.approx(width, abs=0.01)
    assert float(box.group(2)) == pytest.approx(height, abs=0.01)
    # Words are text in it, in the figure's font, embedded.
    assert b"/FontFile2" in pdf
    svg = copied.svg()
    root = ET.fromstring(svg)
    assert "<text" not in svg and float(root.get("width").removesuffix("pt")) == pytest.approx(
        width, abs=0.01
    )
    png = copied.png()
    assert (
        struct.unpack(">II", png[16:24]) == copied.pixels() == (round(width * 4), round(height * 4))
    )
    # Saying it is 288 pixels to the inch: pasted at its own size.
    at = png.index(b"pHYs")
    per_metre = struct.unpack(">IIB", png[at + 4 : at + 13])
    assert per_metre == (11339, 11339, 1)
    # Asked for again, each is the one made.
    assert copied.pdf() is pdf and copied.png() is png and copied.svg() is svg


def test_a_very_large_copy_is_pictured_smaller() -> None:
    huge = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="4000pt" height="3000pt" '
        'viewBox="0 0 4000 3000"><rect width="10" height="10"/></svg>'
    )
    copied = Copied(huge)
    across, down = copied.pixels()
    assert across * down <= PNG_PIXELS * 1.01 and copied.scale < 4


def test_a_picture_s_resolution_is_said_once() -> None:
    png = _png(3, 2)
    once = with_resolution(png, 288)
    twice = with_resolution(once, 144)
    assert once.count(b"pHYs") == twice.count(b"pHYs") == 1
    at = twice.index(b"pHYs")
    assert struct.unpack(">I", twice[at + 4 : at + 8])[0] == round(144 / 0.0254)
    assert with_resolution(b"not a png", 72) == b"not a png"


def test_the_studio_answers_a_copy_with_its_picture_and_svg(tmp_path: Path, drawn: str) -> None:
    from flexo.studio import copying

    (tmp_path / "photo.png").write_bytes(_png(4, 2))

    class Folder:
        def path(self, name: str) -> Path:
            return tmp_path / name

    made = copying.answer(Folder(), {"svg": drawn, "keep": ["a"], "title": "Alpha"})
    png = base64.b64decode(made["png"])
    assert struct.unpack(">II", png[16:24]) == tuple(made["pixels"])
    assert made["svg"].startswith("<?xml") and made["width"] > 0
    copied = copying.copied(Folder(), SLIDE, ["slide1.left.1"])
    assert "data:image/png;base64," in copied.editable
    with pytest.raises(ValueError):
        copying.answer(Folder(), {"svg": drawn, "keep": ["nothing"]})


COPIES = """
const made = [];
// (Node has a navigator and storage of its own, which a page's stand in for.)
const put = (name, value) =>
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
put("navigator", {});
put("localStorage", { store: {}, getItem(key) { return this.store[key] ?? null; },
  setItem(key, value) { this.store[key] = value; }, removeItem(key) { delete this.store[key]; } });
const studio = { api: async (route, body) => {
  made.push({ route, body });
  return { png: btoa("PNG"), svg: "<svg/>" };
} };
const out = {};
// In a browser that takes no clipboard items: nothing is written, nothing fails.
copyOut(studio, { svg: "<svg/>", keep: ["a"], text: "Alpha", clip: { what: "parts" } });
out.bare = made.length;
// A browser's: words, a picture, and the SVG where it takes one -- asked of the studio.
const written = [];
globalThis.ClipboardItem = class {
  constructor(parts) { this.parts = parts; }
  static supports(type) {
    return type === "web image/svg+xml" || type === "web application/x-flexo-clip";
  }
};
put("navigator", { clipboard: { write: async (items) => { written.push(items); } } });
copyOut(studio, { svg: "<svg/>", keep: ["a", "b"], text: "Alpha\\nBeta",
  clip: { what: "parts", n: 2 }, title: "2 shapes" });
await new Promise((done) => setTimeout(done, 20));
const parts = written[0][0].parts;
out.types = Object.keys(parts);
out.png = await (await parts["image/png"]).text();
out.svg = await (await parts["web image/svg+xml"]).text();
out.text = await parts["text/plain"].text();
out.ownWeb = JSON.parse(await parts["web application/x-flexo-clip"].text());
out.asked = [...made];
// What the browser keeps of the copy -- its words -- brings it back to a paste, here or in
// another tab (kept in the page's storage); other words, nothing.
const paste = (words) => ({ getData: (type) => (type === "text/plain" ? words : "") });
out.here = copiedHere(paste("Alpha\\nBeta"));
out.other = copiedHere(paste("Gamma"));
out.empty = copiedHere(paste(""));
out.kept = JSON.parse(localStorage.getItem("flexo-studio-copied")).clip;
// A browser whose clipboard refuses: quiet.
put("navigator", { clipboard: { write: async () => { throw new Error("NotAllowed"); } } });
copyOut(studio, { svg: "<svg/>", text: "Gamma", clip: { what: "slide" } });
await new Promise((done) => setTimeout(done, 20));
// The Mac app: the app is asked, after the words are written, never the studio.
const calls = [];
globalThis.pywebview = { api: { copy_drawing: async (copy) => { calls.push(copy); return {}; } } };
let wrote = null;
const words = new Promise((done) => { wrote = done; });
made.length = 0;
copyOut(studio, { svg: "<svg id='s'/>", keep: [], text: "Slide", clip: { what: "slide" },
  title: "Slide" }, words);
await new Promise((done) => setTimeout(done, 20));
out.before = calls.length;
wrote();
await new Promise((done) => setTimeout(done, 20));
out.app = calls.slice();
out.studio = made.length;
// No drawing (several slides): Flexo's own copy remembered, and put on the Mac's clipboard
// alone, for a window of another folder -- nothing drawn; nothing at all with no copy of its own.
copyOut(studio, { svg: "", text: "Two", clip: { what: "slides" } });
await new Promise((done) => setTimeout(done, 20));
out.undrawn = calls.slice(1);
copyOut(studio, { svg: "", text: "Words" });
await new Promise((done) => setTimeout(done, 20));
out.unowned = calls.length;
// Pasted in a window of another folder: Flexo's own copy, from the app, when a picture alone
// came -- never asked otherwise.
const owned = [];
globalThis.pywebview = { api: { clipboard_own: () => {
  owned.push(1);
  return JSON.stringify({ what: "parts" });
} } };
const files = (...names) => ({ files: names.map((name) => new File(["x"], name)) });
out.own = await pastedOwn(files("image.png"));
out.notOwn = [pastedOwn(files()), pastedOwn(files("image.png", "notes.txt"))];
out.owned = owned.length;
// Words alone pasted in the app (several slides copied in another folder's window): Flexo's own
// copy asked for, the paste's data kept to be read after; never with files, nor in a browser.
const held = heldData({ types: ["text/plain", "text/html", "Files"], files: [],
  getData: (type) => ({ "text/plain": "A two\\nA three", "text/html": "<p>A</p>" })[type] ?? "" });
out.held = [held.getData("text/plain"), held.getData("text/html"),
  held.getData("image/svg+xml"), held.files.length];
out.words = await pastedOwnWords({ files: [], getData: () => "A two" });
out.wordsWithFiles = pastedOwnWords(files("image.png"));
globalThis.pywebview = { api: { clipboard_own: () => "" } };
out.wordsNotOwn = await pastedOwnWords({ files: [] });
globalThis.pywebview = undefined;
out.wordsInABrowser = pastedOwnWords({ files: [] });
// In a browser, a picture pasted beside a drawing (the studio's copy of another folder): Flexo's
// own copy read from the clipboard's web format; a picture alone (a screenshot), nothing read.
const reads = [];
const kept = { types: ["image/png", "web application/x-flexo-clip"],
  getType: async () => new Blob([JSON.stringify({ what: "block" })]) };
put("navigator", { clipboard: { read: async () => { reads.push(1); return [kept]; } } });
const png = new File(["x"], "image.png", { type: "image/png" });
const picture = (types) => ({ files: [png], types });
out.web = await pastedOwnWeb(picture(["text/plain", "image/svg+xml", "Files"]));
out.screenshot = pastedOwnWeb(picture(["Files"]));
out.webWords = pastedOwnWeb({ files: [], types: ["text/plain"] });
out.reads = reads.length;
globalThis.pywebview = { api: {} };
out.webInTheApp = pastedOwnWeb(picture(["image/svg+xml", "Files"]));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_copies_out_as_the_browser_or_the_app_allows() -> None:
    static = Path(__file__).parents[2] / "src/flexo/studio/static/studio"
    code = (
        f"import {{ copyOut, copiedHere }} from {json.dumps((static / 'copyout.js').as_uri())};\n"
        f"import {{ pastedOwn, pastedOwnWords, pastedOwnWeb, heldData }} from "
        f"{json.dumps((static / 'clipboard.js').as_uri())};\n" + COPIES
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    found = json.loads(done.stdout)
    assert found["bare"] == 0
    assert found["types"] == [
        "text/plain", "image/png", "web image/svg+xml", "web application/x-flexo-clip"
    ]
    assert found["ownWeb"] == {"what": "parts", "n": 2}
    assert (found["png"], found["svg"], found["text"]) == ("PNG", "<svg/>", "Alpha\nBeta")
    assert found["asked"] == [
        {"route": "/api/copy", "body": {"svg": "<svg/>", "keep": ["a", "b"], "title": "2 shapes"}}
    ]
    assert found["here"] == {"what": "parts", "n": 2} == found["kept"]
    assert found["other"] is None and found["empty"] is None
    assert found["before"] == 0 and found["studio"] == 0
    assert found["app"] == [
        {
            "svg": "<svg id='s'/>",
            "keep": [],
            "text": "Slide",
            "clip": '{"what":"slide"}',
            "title": "Slide",
        }
    ]
    assert found["undrawn"] == [
        {"svg": "", "keep": [], "text": "Two", "clip": '{"what":"slides"}', "title": ""}
    ]
    assert found["unowned"] == 2
    assert (
        found["own"] == {"what": "parts"}
        and found["notOwn"] == [None, None]
        and found["owned"] == 1
    )
    assert found["held"] == ["A two\nA three", "<p>A</p>", "", 0]
    assert found["words"] == {"what": "parts"} and found["wordsWithFiles"] is None
    assert found["wordsNotOwn"] is None and found["wordsInABrowser"] is None
    assert found["web"] == {"what": "block"} and found["reads"] == 1
    assert found["screenshot"] is None and found["webWords"] is None
    assert found["webInTheApp"] is None
