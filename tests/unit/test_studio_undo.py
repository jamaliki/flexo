"""An undo kept by the studio and drawn in the same request (``/api/update`` with ``draw``),
as the page sends it (``static/studio/session.js``): one request, where it took two."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo.studio import framing
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
SESSION = Path(framing.__file__).parent / "static" / "studio" / "session.js"


def call(
    url: str, token: str, body: object = None, *, framed: bool = False
) -> tuple[int, str, bytes]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-Studio-Token": token}
    if framed:
        headers["Accept"] = f"{framing.ACCEPT}, application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with OPENER.open(request) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace]]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_an_undo_is_kept_and_drawn_in_one_request(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    token = workspace.token
    _, _, opened = call(f"{base}/api/open?file=figure.yaml", token)
    opened = json.loads(opened)
    before = opened["document"]
    after = {**before, "text": before["text"].replace("label: Encoder", "label: Undone")}
    assert after != before
    body = {
        "file": "figure.yaml",
        "kind": "figure",
        "base": opened["version"],
        "instance": opened["instance"],
        "document": after,
        "client": "page-1",
        "who": PERSON,
        "draw": {"version": 7, "known": {}, "hints": {"client": "page-1"}},
    }
    status, kind, answer = call(f"{base}/api/update", token, body, framed=True)
    assert status == 200 and kind == framing.ACCEPT
    answer = framing.read(answer)
    doc = workspace.open("figure.yaml")
    # Kept, as any update is ...
    assert answer["version"] == doc.version == opened["version"] + 1
    assert answer["document"] == doc.document == after
    # ... and drawn as it is kept, in the same request.
    (page,) = answer["drawing"]["pages"]
    assert answer["drawing"]["version"] == 7 and "Undone" in page["svg"]
    # Without ``draw``, an update is answered as ever.
    body = {**body, "base": doc.version, "document": before}
    body.pop("draw")
    status, kind, plain = call(f"{base}/api/update", token, body, framed=True)
    assert status == 200 and kind == "application/json" and "drawing" not in json.loads(plain)


FAKE_PAGE = """
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
}
globalThis.Node = Node;
globalThis.SVGElement = class extends Node {};
globalThis.document = {
  body: new Node("body"), head: new Node("head"), documentElement: new Node("html"),
  addEventListener() {}, querySelector() { return null; },
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new SVGElement(tag),
  createTextNode: (text) => Object.assign(new Node("#text"), { text }),
};
"""


def test_the_page_sends_an_undo_and_has_it_drawn_in_one_request() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = SESSION
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const asked = [];
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async (route, body) => {
    asked.push([route, Boolean(body.draw), body.document?.text]);
    if (route !== "/api/update") return new Promise(() => {});
    const text = body.document.text;
    const page = { id: "p", hash: "h" + text, svg: "<svg>" + text + "</svg>" };
    const drawing = { version: body.draw?.version, pages: [page], messages: [] };
    return { version: body.base + 1, document: body.document, who: null,
             drawing: body.draw ? drawing : undefined };
  },
};
const opened = { file: "a.yaml", version: 1, saved: 1, exists: true, document: { text: "A" } };
const session = new Session(workspace, opened);
const drawn = [];
session.on("drawn", ({ pages }) => drawn.push(pages.map((page) => page.svg)));
const wait = () => new Promise((resolve) => setTimeout(resolve, 30));
session.change((d) => { d.text = "B"; });
session.synced = session.document;  // (sent, and drawn: as the studio has it)
session.version = 2;
asked.length = 0;
session.undo();
await wait();
const { version, drawBusy: busy } = session;
console.log(JSON.stringify({ asked, drawn, text: session.document.text, version, busy }));
process.exit(0);
"""
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    said = json.loads(result.stdout.strip().splitlines()[-1])
    # One request: the document undone, sent with its drawing asked for -- and that drawing shown.
    assert said["asked"] == [["/api/update", True, "A"]]
    assert said["drawn"] == [["<svg>A</svg>"]]
    assert said["text"] == "A" and said["version"] == 3 and said["busy"] == 0
