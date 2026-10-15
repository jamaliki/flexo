"""The studio makes a drawing pasted or dropped into a page its own shapes
(``/api/import-drawing``), writing what no shape draws as pictures beside the document; and the
page's paste and drop of a drawing come to it."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo import freeform
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import CLAIM_LIMIT, Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(url: str, token: str, body: object) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Studio-Token": token},
    )
    try:
        with OPENER.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
PNG = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
    )
).decode()
DRAWING = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="400" height="200">'
    '<defs><clipPath id="c"><circle cx="300" cy="100" r="40"/></clipPath></defs>'
    '<rect x="0" y="0" width="200" height="100" fill="#000000"/>'
    '<text x="20" y="50" font-size="20">Words</text>'
    f'<image x="250" y="50" width="100" height="100" clip-path="url(#c)" '
    f'xlink:href="data:image/png;base64,{PNG}"/>'
    "</svg>"
)

PASTE = """
class Node {
  constructor(tag) {
    Object.assign(this, { tag, children: [], attributes: {}, style: {}, dataset: {} });
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  remove() { this.removed = true; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; }
  get isConnected() { return !this.removed; }
}
globalThis.Node = Node;
globalThis.SVGElement = class extends Node {};
globalThis.document = {
  body: new Node("body"), head: new Node("head"), documentElement: new Node("html"),
  addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new SVGElement(tag),
  createTextNode: (text) => Object.assign(new Node("#text"), { text }),
};
const { drawingPaster } = await import(%s);
const calls = [], pasted = [], pictures = [];
const made = {
  shapes: [{ kind: "group", shapes: [{ kind: "rectangle" }, { kind: "text" }] }],
  count: 3, kept: [], approximated: [], whole: false,
};
const studio = {
  file: "talk.yaml", info: { roles: { ink: "#111111" } }, past: [], future: [],
  api: async (route, body) => {
    calls.push([route, body]);
    if (body.svg?.includes("broken")) throw new Error("The drawing is not SVG");
    if (body.svg?.includes("empty")) return { shapes: [], count: 0, whole: false };
    return body.svg?.includes("many") ? { whole: true, count: 9000 } : made;
  },
  upload: async (file) => `assets/${file.name}`, undo: () => {},
};
const shapes = {
  paste: (clip, options) => { pasted.push([clip, options]); studio.past.push({}); },
};
const paster = drawingPaster({
  studio, shapes, markup: "slide", place: () => ({ centre: [480, 270], fit: [883, 497] }),
  asPicture: async (file) => pictures.push(file.name || file.path),
});
const svg = (words, name) => new File([words], name, { type: "image/svg+xml" });
await paster.shapesOf(svg("<svg></svg>", "image.svg"));
await paster.shapesOf(svg("<svg>many</svg>", "huge.svg"));
await paster.add({ path: "figures/module.svg", name: "figures/module.svg" });
// A PDF's page dropped: a picture, shapes offered.
await paster.add({ path: "figures/plot.pdf", name: "figures/plot.pdf" });
// Not made shapes -- the studio failed, or found nothing to make -- said as a failure, and logged.
const errors = [];
console.error = (...args) => errors.push(args.map(String).join(" "));
await paster.shapesOf(svg("<svg>broken</svg>", "broken.svg"));
await paster.shapesOf(svg("<svg>empty</svg>", "empty.svg"));
const words = (node) => (typeof node === "string" ? node
  : (node?.text ?? "") + (node?.children || []).map(words).join(""));
const toasts = document.body.children.map(words);
const commands = paster.commands().map((c) => [c.label, c.keys || ""]);
console.log(JSON.stringify({ calls, pasted, pictures, commands, errors, toasts }));
"""


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace]]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_a_drawing_pasted_is_made_shapes_placed_as_asked(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    status, made = call(
        f"{base}/api/import-drawing",
        workspace.token,
        {
            "file": "figures/figure.yaml",
            "svg": DRAWING,
            "name": "image.svg",
            "markup": "figure",
            "centre": [480, 270],
            "fit": [150, 150],
        },
    )
    assert status == 200 and not made["whole"]
    group = made["shapes"][0]
    assert group["kind"] == "group" and [s["kind"] for s in group["shapes"]] == [
        "rectangle",
        "text",
        "picture",
    ]
    assert group["shapes"][0]["fill"] == "ink"
    left, _top, width, _height = made["box"]
    assert width <= 150.01 and left + width / 2 == pytest.approx(480, abs=0.05)
    # What no shape draws: a picture beside the document, in its assets, said.
    picture = group["shapes"][2]["source"]
    assert picture.startswith("assets/image-part-") and picture.endswith(".svg")
    assert (workspace.root / "figures" / picture).is_file() and made["pictures"] == [picture]
    assert len(made["kept"]) == 1
    # Its colours as drawn, asked.
    exact = call(
        f"{base}/api/import-drawing",
        workspace.token,
        {"file": "figures/figure.yaml", "svg": DRAWING, "exact": True},
    )[1]
    assert exact["shapes"][0]["shapes"][0]["fill"] == "#000000"


def test_a_file_beside_the_document_is_read_where_it_is(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    (workspace.root / "figures" / "module.svg").write_text(DRAWING, encoding="utf-8")
    made = call(
        f"{base}/api/import-drawing",
        workspace.token,
        {"file": "figures/figure.yaml", "path": "module.svg"},
    )[1]
    assert made["count"] == 4 and made["pictures"][0].startswith("assets/module-part-")
    # Not a drawing, or not there: said.
    (workspace.root / "figures" / "words.txt").write_text("words", encoding="utf-8")
    assert (
        call(
            f"{base}/api/import-drawing",
            workspace.token,
            {"file": "figures/figure.yaml", "path": "words.txt"},
        )[0]
        == 400
    )
    assert call(
        f"{base}/api/import-drawing",
        workspace.token,
        {"file": "figures/figure.yaml", "path": "../../x.svg"},
    )[0] in (403, 404)
    # One that does not read is a picture's to place.
    broken = call(
        f"{base}/api/import-drawing",
        workspace.token,
        {"file": "figures/figure.yaml", "svg": "<svg"},
    )[1]
    assert broken["whole"] and "not SVG" in broken["why"]


def test_a_document_of_pasted_drawings_is_still_a_document() -> None:
    # A deck of a few drawings pasted as shapes runs to megabytes: still found, still opened.
    assert CLAIM_LIMIT >= 10_000_000


def test_the_pages_paste_of_a_drawing_asks_the_studio_and_adds_one_step() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    # The paste module's own logic, without a page: its request and its one step.
    script = PASTE % json.dumps((STATIC / "drawingpaste.js").as_uri())
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    answered = json.loads(result.stdout.strip().splitlines()[-1])
    first, _huge, chosen = (call[1] for call in answered["calls"][:3])
    assert (
        first["svg"] == "<svg></svg>"
        and first["markup"] == "slide"
        and first["centre"] == [480, 270]
    )
    assert first["roles"] == {"ink": "#111111"} and first["exact"] is False
    assert chosen["path"] == "figures/module.svg" and "svg" not in chosen
    clip, options = answered["pasted"][0]
    assert (
        clip["what"] == "shapes"
        and clip["source"] == "drawing"
        and options["label"] == "Paste Drawing"
    )
    assert answered["pasted"][1][1]["label"] == "Add Drawing"
    # Too many pieces to edit one by one: the picture it was. Not made shapes at all: the
    # picture too, but said as the failure it is -- and why -- and logged.
    assert answered["pictures"] == ["huge.svg", "figures/plot.pdf", "broken.svg", "empty.svg"]
    assert len(answered["calls"]) == 5
    said = " ".join(answered["toasts"])
    assert "9,000 pieces are more than are edited one by one" in said
    assert (
        "couldn\u2019t be made shapes (The drawing is not SVG): it is placed as a picture instead"
        in said
    )
    assert "couldn\u2019t be made shapes (nothing in it is drawn as shapes)" in said
    assert (
        len(answered["errors"]) == 2
        and "broken.svg could not be made shapes" in answered["errors"][0]
    )
    assert answered["commands"] == [
        ["Paste as Picture", "⌥⇧⌘V"],
        ["Paste with Original Colours", ""],
    ]


PASTED = """
const { pastedDrawing, pastedOwn } = await import(%s);
const SVG = '<?xml version="1.0"?>\\n<!-- Created with Inkscape -->\\n'
  + '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><circle r="4"/></svg>\\n';
// A paste's clipboardData, as a web view hands it over: its words, its HTML, other types, files.
const transfer = ({ words = "", html = "", types = {}, files = [] } = {}) => ({
  files,
  types: [...(files.length ? ["Files"] : []), ...(words ? ["text/plain"] : []),
          ...Object.keys(types)],
  getData: (type) => (type === "text/plain" ? words : type === "text/html" ? html
    : types[type] ?? ""),
});
const png = new File([new Uint8Array([137, 80, 78, 71])], "image.png", { type: "image/png" });
const tiff = new File([new Uint8Array([73, 73, 42, 0])], "image.tiff", { type: "image/tiff" });
const pdf = new File(["%%PDF-1.4"], "paper.pdf", { type: "application/pdf" });
const asked = [];
// The Mac app, its clipboard holding `answer` (an SVG, "" for none, or an Error: unread).
const app = (answer) => ({ api: {
  clipboard_drawing: async () => {
    asked.push("drawing");
    if (answer instanceof Error) throw answer;
    return answer;
  },
  clipboard_own: async () => { asked.push("own"); return ""; },
} });
async function outcome(data, mac = null) {
  globalThis.pywebview = mac;
  asked.length = 0;
  const found = pastedDrawing(data);
  if (found === null) return { at_once: true, drawing: null, asked: [...asked] };
  const file = await found;
  return { at_once: false, asked: [...asked],
           drawing: file ? { name: file.name, type: file.type,
                             svg: (await file.text()).trim() === SVG.trim() } : null };
}
const named = (name, type = "image/svg+xml", words = SVG) => new File([words], name, { type });
const cases = {
  inkscape_in_the_app: await outcome(transfer({ files: [png] }), app(SVG)),
  inkscape_with_a_texts_words:
    await outcome(transfer({ files: [png], words: "Encoder" }), app(SVG)),
  inkscape_handed_nothing: await outcome(transfer(), app(SVG)),
  a_browsers_copy_image: await outcome(transfer({ files: [tiff] }), app(SVG)),
  svg_file_beside_png_app_first:
    await outcome(transfer({ files: [png, named("image.svg")] }), app(SVG.replace("r=", "r ="))),
  svg_file_in_the_app: await outcome(transfer({ files: [named("module.svg")] }), app("")),
  svg_file_app_unread:
    await outcome(transfer({ files: [png, named("module.svg")] }), app(new Error("gone"))),
  svg_file_by_type: await outcome(transfer({ files: [named("image", "image/svg+xml")] })),
  svg_file_by_name: await outcome(transfer({ files: [named("module.svg", "")] })),
  svg_file_not_svg:
    await outcome(transfer({ files: [named("module.svg", "image/svg+xml", "hello")] })),
  svg_type: await outcome(transfer({ types: { "image/svg+xml": SVG } })),
  inkscape_type: await outcome(transfer({ types: { "image/x-inkscape-svg": SVG } })),
  svg_words: await outcome(transfer({ words: SVG })),
  words: await outcome(transfer({ words: "Hello" }), app(SVG)),
  formatted_words: await outcome(transfer({ words: "", html: "<b>Hello</b>" }), app(SVG)),
  a_photo_in_a_browser: await outcome(transfer({ files: [png] })),
  a_photo_in_the_app: await outcome(transfer({ files: [png] }), app("")),
  a_pdf_in_the_app: await outcome(transfer({ files: [pdf] }), app("")),
};
globalThis.pywebview = app("");
asked.length = 0;
await pastedOwn(transfer({ files: [named("image.svg")] }));
cases.own_asked_beside_an_svg = asked;
console.log(JSON.stringify(cases));
"""


def test_a_paste_brings_the_drawing_however_the_clipboard_holds_it() -> None:
    """A drawing on the clipboard pastes as the drawing, however the web view hands it over:
    its markup as words or under an SVG type, an SVG file, or -- in the Mac app, with a
    picture of any kind or nothing the page reads -- the SVG the app finds on the clipboard,
    asked first, so the PNG of it Inkscape puts beside it never wins. Words, formatted words
    and a photograph paste as they were, nothing waited for."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = PASTED % json.dumps((STATIC / "clipboard.js").as_uri())
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    cases = json.loads(result.stdout.strip().splitlines()[-1])
    pasted = {"name": "image.svg", "type": "image/svg+xml", "svg": True}
    # Inkscape's, in the Mac app: the web view hands a PNG of it (or nothing, or a TIFF beside
    # its words): the app's SVG, asked first.
    for case in (
        "inkscape_in_the_app",
        "inkscape_with_a_texts_words",
        "inkscape_handed_nothing",
        "a_browsers_copy_image",
    ):
        assert cases[case] == {"at_once": False, "asked": ["drawing"], "drawing": pasted}, case
    # An SVG file beside a picture: still the app's drawing first (the same one, as Inkscape
    # wrote it); the file's when the app has none, or can't read its clipboard.
    assert cases["svg_file_beside_png_app_first"]["drawing"] == {**pasted, "svg": False}
    file = {"name": "module.svg", "type": "image/svg+xml", "svg": True}
    assert cases["svg_file_in_the_app"] == {"at_once": False, "asked": ["drawing"], "drawing": file}
    assert cases["svg_file_app_unread"]["drawing"] == file
    # In a browser: an SVG file, by its type or its name, is read; one that holds no drawing is not.
    assert cases["svg_file_by_type"] == {"at_once": False, "asked": [], "drawing": pasted}
    assert cases["svg_file_by_name"]["drawing"] == file
    assert cases["svg_file_not_svg"] == {"at_once": False, "asked": [], "drawing": None}
    # Its SVG under a type of its own, or as words: the drawing, nothing asked.
    for case in ("svg_type", "inkscape_type", "svg_words"):
        assert cases[case] == {"at_once": False, "asked": [], "drawing": pasted}, case
    # Words, formatted words, a photograph in a browser: pasted as they were, at once.
    for case in ("words", "formatted_words", "a_photo_in_a_browser"):
        assert cases[case] == {"at_once": True, "asked": [], "drawing": None}, case
    # A photograph or a PDF in the Mac app: the app asked, and it holds no drawing.
    for case in ("a_photo_in_the_app", "a_pdf_in_the_app"):
        assert cases[case] == {"at_once": False, "asked": ["drawing"], "drawing": None}, case
    # Flexo's own copy is looked for beside an SVG file too (it wins over the drawing).
    assert cases["own_asked_beside_an_svg"] == ["own"]
