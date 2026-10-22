"""An edit sent as no more than what it is (``flexo.studio.acting``): from the version the page
has, kept by the studio and drawn as it is made -- one request, answered with what changed --
and a drawing asked for the same way."""

from __future__ import annotations

import copy
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo.studio.acting import changed, changes
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
ADD = {"do": "add", "kind": "protein", "after": "encoder", "source": "encoder"}


def call(url: str, token: str, body: object = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", "X-Studio-Token": token}
    )
    try:
        with OPENER.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


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


def test_what_changed_is_said_by_where_and_made_again_from_it() -> None:
    before = {
        "slides": [{"title": "A", "body": [{"text": "x"}, {"figure": {"nodes": [{"id": "a"}]}}]}],
        "deck": {"id": "d", "theme": "t"},
    }
    after = copy.deepcopy(before)
    after["slides"][0]["body"][1]["figure"]["nodes"][0]["label"] = "Alpha"  # a key added
    after["slides"][0]["title"] = "B"
    after["slides"][0]["body"].append({"text": "y"})  # a list grown
    del after["deck"]["theme"]
    made = changes(before, after)
    # Only what changed, the least that holds each change: a mapping whose keys changed and a
    # list whose length did, whole -- so that its order is the one made.
    assert [path for path, *_ in made] == [["slides", 0, "title"], ["slides", 0, "body"], ["deck"]]
    assert changed(copy.deepcopy(before), made) == after
    assert list(changed(copy.deepcopy(before), made)["deck"]) == list(after["deck"])
    assert changes(before, copy.deepcopy(before)) == []
    # A key taken away alone, a list's item, and the whole.
    assert changed({"a": [1, 2]}, [[["a", 1], 3]]) == {"a": [1, 3]}
    assert changed({"a": 1, "b": 2}, [[["b"]]]) == {"a": 1}
    assert changed({"a": 1}, [[[], [1, 2]]]) == [1, 2]


def test_an_edit_sent_as_the_version_the_page_has_is_kept_and_drawn_in_one_request(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    token = workspace.token
    _, opened = call(f"{base}/api/open?file=figure.yaml", token)
    version = opened["version"]
    body = {
        "file": "figure.yaml",
        "kind": "figure",
        "base": version,
        "instance": opened["instance"],
        "client": "page-1",
        "who": PERSON,
        "action": ADD,
        "commit": True,
        "draw": {"version": 1, "known": {}, "hints": {"client": "page-1"}},
    }
    # (What is sent is the edit, not the document.)
    assert len(json.dumps(body)) < len(json.dumps(opened["document"]))
    status, result = call(f"{base}/api/act", token, body)
    assert status == 200 and result["select"] == ["protein"]
    # Kept at once, as an update from that version would be: the version it became, and what
    # changed -- never the whole document.
    doc = workspace.open("figure.yaml")
    assert "document" not in result and result["version"] == doc.version == version + 1
    assert changed(copy.deepcopy(opened["document"]), result["delta"]) == doc.document
    # Drawn in the same request, as the page would have asked it to be.
    (page,) = result["drawing"]["pages"]
    assert "protein" in page["svg"] and result["drawing"]["version"] == 1
    # Drawn again with the page knowing that drawing: nothing sent again.
    again = {
        **body,
        "base": doc.version,
        "action": {"do": "read"},
        "commit": False,
        "draw": {"version": 2, "known": {page["id"]: page["hash"]}, "hints": {"client": "page-1"}},
    }
    status, read = call(f"{base}/api/act", token, again)
    assert status == 200 and read["delta"] == [] and "svg" not in read["drawing"]["pages"][0]
    assert workspace.open("figure.yaml").version == doc.version


def test_an_edit_made_on_a_version_since_changed_is_answered_for_the_page_to_send(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    token = workspace.token
    _, opened = call(f"{base}/api/open?file=figure.yaml", token)
    version = opened["version"]
    # Another's change comes in first.
    other = {**opened["document"], "text": opened["document"]["text"].replace("Encoder", "Coder")}
    status, _ = call(
        f"{base}/api/update",
        token,
        {"file": "figure.yaml", "base": version, "document": other, "client": "page-2"},
    )
    assert status == 200 and workspace.open("figure.yaml").version == version + 1
    body = {
        "file": "figure.yaml",
        "base": version,
        "instance": opened["instance"],
        "client": "page-1",
        "action": ADD,
        "commit": True,
    }
    status, result = call(f"{base}/api/act", token, body)
    # Made on the page's version, not kept: what it changed there, for the page to send as it
    # sends any edit of its own, merged with the other's.
    assert status == 200 and "version" not in result
    made = changed(copy.deepcopy(opened["document"]), result["delta"])
    assert "protein" in made["text"] and "Coder" not in made["text"]
    assert workspace.open("figure.yaml").version == version + 1


def test_a_version_the_studio_does_not_have_is_sent_whole(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    token = workspace.token
    _, opened = call(f"{base}/api/open?file=figure.yaml", token)
    body = {
        "file": "figure.yaml",
        "base": opened["version"],
        "instance": opened["instance"],
        "action": ADD,
    }
    # From a studio since stopped, the page takes in the document first.
    assert call(f"{base}/api/act", token, {**body, "instance": "gone"})[1] == {"restarted": True}
    # A version let go, or never had: sent whole.
    assert call(f"{base}/api/act", token, {**body, "base": 9999})[1] == {"resend": True}
    drawn = {
        "file": "figure.yaml",
        "base": 9999,
        "instance": opened["instance"],
        "version": 3,
        "known": {},
        "hints": {},
    }
    status, answer = call(f"{base}/api/draw", token, drawn)
    assert status == 200 and answer["stale"] and answer["resend"]


def test_a_drawing_asked_for_by_the_version_the_page_has_is_the_document_s(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    token = workspace.token
    _, opened = call(f"{base}/api/open?file=figure.yaml", token)
    whole = {
        "file": "figure.yaml",
        "document": opened["document"],
        "version": 1,
        "known": {},
        "hints": {},
    }
    kept = {
        "file": "figure.yaml",
        "base": opened["version"],
        "instance": opened["instance"],
        "version": 2,
        "known": {},
        "hints": {},
    }
    status, first = call(f"{base}/api/draw", token, whole)
    status, second = call(f"{base}/api/draw", token, kept)
    assert status == 200 and second["pages"][0]["svg"] == first["pages"][0]["svg"]
    assert second["pages"][0]["hash"] == first["pages"][0]["hash"]


def test_an_edit_sent_again_after_the_studio_restarted_between_its_save_and_answer_is_made_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flexo.studio import acting

    monkeypatch.setenv("FLEXO_ACTS", str(tmp_path / "acts"))
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")

    def studio():
        server, workspace = start(folder / "figure.yaml", browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, workspace, f"http://127.0.0.1:{server.server_address[1]}"

    def stop(server, workspace):
        workspace.close()
        server.shutdown()
        server.server_close()

    server, workspace, base = studio()
    _, opened = call(f"{base}/api/open?file=figure.yaml", workspace.token)
    body = {
        "file": "figure.yaml",
        "base": opened["version"],
        "instance": opened["instance"],
        "client": "page-1",
        "action": ADD,
        "commit": True,
        "once": "page-1:add-protein",
    }
    status, made = call(f"{base}/api/act", workspace.token, body)
    assert status == 200 and made["version"] == opened["version"] + 1
    # Written to its file -- and the studio gone before its answer reached the page.
    workspace.flush()
    stop(server, workspace)
    acting._MADE.clear()  # (a new studio knows only what was written)
    server, workspace, base = studio()
    try:
        # Sent again as it was, and with the document whole as the page falls back to: made
        # already, so made no more -- the page takes in the studio's document instead.
        status, again = call(f"{base}/api/act", workspace.token, body)
        assert status == 200 and again["repeat"] and again["instance"] == workspace.instance
        whole = {
            "file": "figure.yaml",
            "document": opened["document"],
            "action": ADD,
            "once": body["once"],
        }
        assert call(f"{base}/api/act", workspace.token, whole)[1]["repeat"]
        text = workspace.open("figure.yaml").document["text"]
        assert text.count("id: protein") == 1
        # Another edit is made as ever.
        _, now = call(f"{base}/api/open?file=figure.yaml", workspace.token)
        other = {
            **body,
            "base": now["version"],
            "instance": now["instance"],
            "once": "page-1:other",
            "action": {**ADD, "kind": "text"},
        }
        status, made = call(f"{base}/api/act", workspace.token, other)
        assert status == 200 and made["version"] == now["version"] + 1
    finally:
        stop(server, workspace)


def test_an_edit_whose_save_never_reached_its_file_is_made_again(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from flexo.studio import acting

    monkeypatch.setenv("FLEXO_ACTS", str(tmp_path / "acts"))
    path = tmp_path / "figure.yaml"
    path.write_text("before", encoding="utf-8")
    workspace = SimpleNamespace(root=tmp_path, instance="one")
    doc = SimpleNamespace(name="figure.yaml", path=path, version=1, workspace=workspace)
    acting._keep(workspace, doc, "kept", 1)
    acting.saving(workspace, doc, path)  # (the words "before", holding "kept")
    acting._keep(workspace, doc, "lost", 2)
    acting._keep(workspace, doc, "later", 3)  # (made after the words written were taken)
    doc.version = 3
    written = tmp_path / ".figure.saving.yaml"
    written.write_text("after", encoding="utf-8")
    acting.saving(workspace, doc, written, 2)  # (kept beside, and the studio gone before the move)
    acting._MADE.clear()
    assert acting.made_already(workspace, doc, "kept") and not acting.made_already(
        workspace, doc, "lost"
    )
    # The move made after all: both held.
    acting._MADE.clear()
    written.replace(path)
    assert acting.made_already(workspace, doc, "kept") and acting.made_already(
        workspace, doc, "lost"
    )
    # (Not one made after the words written were taken.)
    assert not acting.made_already(workspace, doc, "later")
