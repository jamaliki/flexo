"""A drawing sent to the page with its SVG as it is (``flexo.studio.framing``), read back by
the page as JSON would have given it (``static/studio/framed.js``)."""

from __future__ import annotations

import copy
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
READER = Path(framing.__file__).parent / "static" / "studio" / "framed.js"


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


ANSWER = {
    "version": 3,
    "pages": [
        {"id": "slide1", "hash": "a", "svg": '<svg id="one">“quoted” \\ é \U0001d465</svg>'},
        {"id": "slide2", "hash": "b"},
        {"id": "slide3", "pending": True},
        {"id": "slide4", "hash": "d", "svg": "<svg/>"},
    ],
    "messages": [{"text": "a line\nand another", "severity": "note"}],
}


def test_a_drawing_is_framed_with_its_svgs_as_they_are_and_read_back_whole() -> None:
    body = framing.framed(ANSWER)
    assert body is not None
    head, _, tail = body.partition(b"\n")
    # The JSON on a line of its own, none of the SVG in it; the SVGs after it, as they are.
    assert b"<svg" not in head and tail == ANSWER["pages"][0]["svg"].encode() + b"<svg/>"
    assert framing.read(body) == ANSWER
    # The answer itself is not changed by being framed.
    assert ANSWER["pages"][0]["svg"].startswith("<svg")


def test_an_edit_and_its_drawing_are_framed_and_what_carries_no_drawing_is_not() -> None:
    edit = {"delta": [], "version": 4, "drawing": copy.deepcopy(ANSWER), "select": ["a"]}
    assert framing.read(framing.framed(edit)) == edit
    for plain in (
        {"version": 3, "stale": True},
        {"pages": [{"id": "s", "hash": "x"}]},
        [1, 2],
        None,
    ):
        assert framing.framed(plain) is None


def test_the_page_reads_a_framed_answer_as_json_would_have_given_it() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    edit = {"delta": [[["a"], 1]], "drawing": copy.deepcopy(ANSWER)}
    for answer in (ANSWER, edit):
        body = framing.framed(answer)
        script = (
            f"const M = await import({json.dumps(READER.as_uri())});\n"
            f"const bytes = Uint8Array.from({json.dumps(list(body))});\n"
            "const kind = { headers: { 'Content-Type': M.ACCEPT } };\n"
            "const response = new Response(bytes, kind);\n"
            "console.log(JSON.stringify(await M.answered(response)));\n"
        )
        result = subprocess.run(
            [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
        )
        assert json.loads(result.stdout.strip().splitlines()[-1]) == answer
    # Any other answer is read as JSON.
    script = (
        f"const M = await import({json.dumps(READER.as_uri())});\n"
        "const kind = { headers: { 'Content-Type': 'application/json' } };\n"
        "const response = new Response('{\"ok\": true}', kind);\n"
        "console.log(JSON.stringify(await M.answered(response)));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"ok": True}


def test_the_studio_frames_a_drawing_for_a_page_that_reads_it_so_and_answers_json_otherwise(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    _, _, opened = call(f"{base}/api/open?file=figure.yaml", workspace.token)
    document = json.loads(opened)["document"]
    asked = {"file": "figure.yaml", "document": document, "version": 1, "hints": {"client": "c"}}
    status, kind, plain = call(f"{base}/api/draw", workspace.token, asked)
    assert status == 200 and kind == "application/json"
    status, kind, framed = call(
        f"{base}/api/draw", workspace.token, {**asked, "version": 2}, framed=True
    )
    assert status == 200 and kind == framing.ACCEPT
    # The same drawing either way.
    assert framing.read(framed) == {
        **json.loads(plain),
        "version": 2,
        "seconds": framing.read(framed)["seconds"],
    }
    # An answer with no SVG in it (every page known) is JSON, framed or not.
    known = {page["id"]: page["hash"] for page in json.loads(plain)["pages"]}
    status, kind, again = call(
        f"{base}/api/draw", workspace.token, {**asked, "version": 3, "known": known}, framed=True
    )
    assert status == 200 and kind == "application/json" and "svg" not in again.decode()
