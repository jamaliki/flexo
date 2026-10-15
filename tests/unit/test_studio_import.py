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
const commands = paster.commands().map((c) => [c.label, c.keys || ""]);
console.log(JSON.stringify({ calls, pasted, pictures, commands }));
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
    first, _huge, chosen = (call[1] for call in answered["calls"])
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
    # Too many pieces to edit one by one: the picture it was.
    assert answered["pictures"] == ["huge.svg", "figures/plot.pdf"]
    assert len(answered["calls"]) == 3
    assert answered["commands"] == [
        ["Paste as Picture", "⌥⇧⌘V"],
        ["Paste with Original Colours", ""],
    ]
