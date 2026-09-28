"""The studio serves one folder to the page that knows its token, and draws figures."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from flexo.studio import kinds
from flexo.studio.figure_kind import NEW_FIGURE, FigureKind
from flexo.studio.server import Handler, Studio


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Studio]]:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    studio = Studio(tmp_path)
    handler = type("TestHandler", (Handler,), {"studio": studio})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.start_file = "figure.yaml"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", studio
    finally:
        server.shutdown()
        server.server_close()


def call(
    url: str, token: str | None, body: object = None, *, host: str | None = None
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Studio-Token"] = token
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_page_carries_the_token_and_calls_need_it(served: tuple[str, Studio]) -> None:
    base, studio = served
    page = urllib.request.urlopen(f"{base}/").read().decode()
    assert re.search(r'"token": "([^"]+)"', page).group(1) == studio.token  # type: ignore[union-attr]
    assert call(f"{base}/api/session?file=figure.yaml", None)[0] == 403
    assert call(f"{base}/api/session?file=figure.yaml", "wrong")[0] == 403
    status, session = call(f"{base}/api/session?file=figure.yaml", studio.token)
    assert status == 200 and session["kind"] == "figure" and "nodes:" in session["document"]["text"]


def test_another_host_name_is_refused(served: tuple[str, Studio]) -> None:
    base, studio = served
    status, _ = call(f"{base}/api/session?file=figure.yaml", studio.token, host="evil.example")
    assert status == 403


def test_files_outside_the_folder_are_refused(served: tuple[str, Studio]) -> None:
    base, studio = served
    status, body = call(
        f"{base}/api/save", studio.token, {"file": "../escape.yaml", "document": {"text": ""}}
    )
    assert status == 403 and "outside" in body["error"]
    assert not (studio.root.parent / "escape.yaml").exists()


def test_a_figure_is_drawn_saved_and_drawn_only_when_changed(served: tuple[str, Studio]) -> None:
    base, studio = served
    document = {"text": NEW_FIGURE.replace("Encoder", "Decoder")}
    request = {"file": "figure.yaml", "document": document, "version": 1, "known": {}, "hints": {}}
    status, drawn = call(f"{base}/api/draw", studio.token, request)
    assert status == 200 and not drawn["unfinished"]
    (page,) = drawn["pages"]
    assert "Decoder" in page["svg"]
    assert page["outline"]["root"]["type"] == "group"
    assert {edge["target"] for edge in page["outline"]["edges"]} == {"encoder", "y"}
    # The page already has this drawing: it is not sent again.
    request.update(version=2, known={page["id"]: page["hash"]})
    _, again = call(f"{base}/api/draw", studio.token, request)
    assert "svg" not in again["pages"][0]
    status, _ = call(
        f"{base}/api/save", studio.token, {"file": "figure.yaml", "document": document}
    )
    assert status == 200
    assert "Decoder" in (studio.root / "figure.yaml").read_text(encoding="utf-8")


def test_an_older_drawing_from_the_same_page_is_dropped(served: tuple[str, Studio]) -> None:
    base, studio = served
    newer = {
        "file": "figure.yaml",
        "document": {"text": NEW_FIGURE},
        "version": 5,
        "known": {},
        "hints": {"client": "a"},
    }
    assert "pages" in call(f"{base}/api/draw", studio.token, newer)[1]
    older = {**newer, "version": 3}
    assert call(f"{base}/api/draw", studio.token, older)[1].get("stale")
    # Another page counts its own drawings.
    other = {**older, "hints": {"client": "b"}}
    assert "pages" in call(f"{base}/api/draw", studio.token, other)[1]


def test_a_new_file_is_made_from_its_kind_or_given_data(served: tuple[str, Studio]) -> None:
    base, studio = served
    status, made = call(
        f"{base}/api/new", studio.token, {"file": "figures/a.yaml", "kind": "figure"}
    )
    assert status == 200 and made["file"] == "figures/a.yaml"
    assert (studio.root / "figures/a.yaml").read_text(encoding="utf-8") == NEW_FIGURE
    data = {"figure": {"id": "given"}, "nodes": [{"id": "n", "label": "N"}]}
    status, _ = call(
        f"{base}/api/new", studio.token, {"file": "figures/a.yaml", "kind": "figure", "data": data}
    )
    assert status == 409
    status, _ = call(
        f"{base}/api/new", studio.token, {"file": "b.yaml", "kind": "figure", "data": data}
    )
    assert status == 200 and "id: given" in (studio.root / "b.yaml").read_text(encoding="utf-8")


def test_pictures_beside_the_document_are_listed_and_uploaded(served: tuple[str, Studio]) -> None:
    base, studio = served
    (studio.root / "pictures").mkdir()
    (studio.root / "pictures" / "a.png").write_bytes(b"png")
    (studio.root / "build").mkdir()
    (studio.root / "build" / "skip.png").write_bytes(b"png")
    _, listed = call(f"{base}/api/files?file=figure.yaml&types=image", studio.token)
    assert listed["files"] == ["pictures/a.png"]
    request = urllib.request.Request(
        f"{base}/api/upload?file=figure.yaml&name=../../photo.png",
        data=b"data",
        headers={"X-Studio-Token": studio.token},
    )
    uploaded = json.loads(urllib.request.urlopen(request).read())
    assert uploaded["path"] == "assets/photo.png"
    assert (studio.root / "assets" / "photo.png").read_bytes() == b"data"


def test_a_figure_that_does_not_read_says_where() -> None:
    kind = FigureKind()
    drawing = kind.draw({"text": "nodes: [\n  - id: x\n"}, Path("."))
    (message,) = drawing.messages
    assert message.severity == "error" and message.where.startswith("line ")
    drawing = kind.draw({"text": "nodes:\n- id: x\n  kind: no-such-kind\n"}, Path("."))
    assert drawing.pages == [] and drawing.messages and drawing.messages[0].severity == "error"


def test_the_figure_kind_is_always_there() -> None:
    assert isinstance(kinds()["figure"], FigureKind)
    assert FigureKind().claims({"nodes": []}) and not FigureKind().claims({"slides": []})
