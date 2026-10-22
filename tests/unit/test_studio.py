"""The studio serves one folder to the page that knows its token, draws figures and
themes, and keeps everyone editing a document -- pages, agents, the file on disk -- in step."""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

from flexo.studio import kinds
from flexo.studio.agent import Tools
from flexo.studio.assistant import Assistant
from flexo.studio.figure_kind import NEW_FIGURE, SAMPLE_FIGURE, FigureKind
from flexo.studio.server import start
from flexo.studio.theme_kind import ThemeKind
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}


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
        with OPENER.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_for(condition, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("waited in vain")


# -- the server --------------------------------------------------------------------------


def test_the_page_carries_the_token_and_calls_need_it(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    page = OPENER.open(f"{base}/").read().decode()
    assert re.search(r'"token": "([^"]+)"', page).group(1) == workspace.token  # type: ignore[union-attr]
    assert call(f"{base}/api/open?file=figure.yaml", None)[0] == 403
    assert call(f"{base}/api/open?file=figure.yaml", "wrong")[0] == 403
    status, opened = call(f"{base}/api/open?file=figure.yaml", workspace.token)
    assert status == 200 and opened["kind"] == "figure" and "nodes:" in opened["document"]["text"]
    status, session = call(f"{base}/api/session", workspace.token)
    assert {item["file"] for item in session["documents"]} == {"figure.yaml"}
    assert session["start"] == "figure.yaml"


def test_another_host_name_is_refused(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    assert call(f"{base}/api/session", workspace.token, host="evil.example")[0] == 403


def test_files_outside_the_folder_are_refused(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    status, body = call(
        f"{base}/api/new", workspace.token, {"file": "../escape.yaml", "kind": "figure"}
    )
    assert status == 403 and "outside" in body["error"]
    assert not (workspace.root.parent / "escape.yaml").exists()


def test_a_figure_is_drawn_and_sent_only_when_changed(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    document = {"text": SAMPLE_FIGURE.replace("Encoder", "Decoder")}
    request = {"file": "figure.yaml", "document": document, "version": 1, "known": {}, "hints": {}}
    status, drawn = call(f"{base}/api/draw", workspace.token, request)
    assert status == 200 and not drawn["unfinished"]
    (page,) = drawn["pages"]
    assert "Decoder" in page["svg"]
    assert page["outline"]["root"]["type"] == "group"
    request.update(version=2, known={page["id"]: page["hash"]})
    assert "svg" not in call(f"{base}/api/draw", workspace.token, request)[1]["pages"][0]


def test_drawings_name_the_fonts_the_page_loads_once(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    document = {"text": SAMPLE_FIGURE}
    request = {"file": "figure.yaml", "document": document, "version": 1, "known": {}}
    (page,) = call(f"{base}/api/draw", workspace.token, {**request, "hints": {}})[1]["pages"]
    assert "@font-face" not in page["svg"] and "font-family" in page["svg"]
    with OPENER.open(f"{base}/") as response:
        assert 'href="/fonts/faces.css"' in response.read().decode()
    with OPENER.open(f"{base}/fonts/faces.css") as response:
        css = response.read().decode()
    assert "font-family:'Figtree'" in css and "url(/fonts/0)" in css
    with OPENER.open(f"{base}/fonts/0") as response:
        assert response.headers["Content-Type"].startswith("font/")
        assert "max-age" in response.headers["Cache-Control"] and len(response.read()) > 10_000
    # Outside the studio a drawing still carries its fonts.
    assert "@font-face" in FigureKind().draw({"text": SAMPLE_FIGURE}, workspace.root).pages[0].svg


def test_an_update_is_saved_and_told_to_everyone(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    listener = workspace.listen("page-b", {"id": "page-b", "name": "Bo", "kind": "person"})
    document = {"text": SAMPLE_FIGURE.replace("Encoder", "Decoder")}
    status, result = call(
        f"{base}/api/update",
        workspace.token,
        {"file": "figure.yaml", "base": 1, "document": document, "client": "page-a", "who": PERSON},
    )
    assert status == 200 and result["version"] == 2
    event = listener.events.get(timeout=2)
    assert event["type"] == "doc" and event["who"]["name"] == "Ada" and event["version"] == 2
    wait_for(lambda: "Decoder" in (workspace.root / "figure.yaml").read_text(encoding="utf-8"))


def test_a_new_file_is_made_from_its_kind_or_given_data(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    status, made = call(
        f"{base}/api/new", workspace.token, {"file": "figures/a.yaml", "kind": "figure"}
    )
    assert status == 200 and made["file"] == "figures/a.yaml"
    # Named for its file, as a deck is.
    made_text = NEW_FIGURE.replace("id: figure\n", "id: a\n", 1)
    assert (workspace.root / "figures/a.yaml").read_text(encoding="utf-8") == made_text
    data = {"figure": {"id": "given"}, "nodes": [{"id": "n", "label": "N"}]}
    assert (
        call(
            f"{base}/api/new",
            workspace.token,
            {"file": "figures/a.yaml", "kind": "figure", "data": data},
        )[0]
        == 409
    )
    assert (
        call(
            f"{base}/api/new", workspace.token, {"file": "b.yaml", "kind": "figure", "data": data}
        )[0]
        == 200
    )
    assert "id: given" in (workspace.root / "b.yaml").read_text(encoding="utf-8")


def test_a_structure_is_chosen_from_structure_files_and_mol_sketch_scenes(
    served: tuple[str, Workspace],
) -> None:
    """A .json is offered as a structure only when it is a mol-sketch scene: a figure or a
    theme written in JSON is not one."""

    base, workspace = served
    (workspace.root / "1abc.pdb").write_text("HEADER\n", encoding="utf-8")
    scene, other = '{"name": "Attack", "keyframes": []}', '{"figure": {"id": "f"}, "nodes": []}'
    (workspace.root / "attack.json").write_text(scene, encoding="utf-8")
    (workspace.root / "other.json").write_text(other, encoding="utf-8")
    found = call(f"{base}/api/files?file=figure.yaml&types=structure", workspace.token)[1]["files"]
    assert "1abc.pdb" in found and "attack.json" in found and "other.json" not in found
    found = call(f"{base}/api/files?file=figure.yaml&types=figure", workspace.token)[1]["files"]
    assert "other.json" in found


def test_pictures_beside_the_document_are_listed_and_uploaded(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    (workspace.root / "pictures").mkdir()
    (workspace.root / "pictures" / "a.png").write_bytes(b"png")
    (workspace.root / "build").mkdir()
    (workspace.root / "build" / "skip.png").write_bytes(b"png")
    assert call(f"{base}/api/files?file=figure.yaml&types=image", workspace.token)[1]["files"] == [
        "pictures/a.png"
    ]
    request = urllib.request.Request(
        f"{base}/api/upload?file=figure.yaml&name=../../photo.png",
        data=b"data",
        headers={"X-Studio-Token": workspace.token},
    )
    assert json.loads(OPENER.open(request).read())["path"] == "assets/photo.png"
    assert (workspace.root / "assets" / "photo.png").read_bytes() == b"data"
    # A file that is already beside the document, the same, is used where it is.
    (workspace.root / "beside.png").write_bytes(b"same")
    request = urllib.request.Request(
        f"{base}/api/upload?file=figure.yaml&name=beside.png",
        data=b"same",
        headers={"X-Studio-Token": workspace.token},
    )
    assert json.loads(OPENER.open(request).read())["path"] == "beside.png"
    assert not (workspace.root / "assets" / "beside.png").exists()


def test_a_picture_pasted_under_the_wrong_name_is_saved_as_what_it_is(
    served: tuple[str, Workspace],
) -> None:
    # (A PNG copied from a web page under a .jpg address -- Steamboat Willie, its background
    # clear -- is a .png in the folder; a name that is right, or no picture's, is kept.)
    base, workspace = served
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
    for name, data, saved in (
        ("steamboat-willie.jpg", png, "assets/steamboat-willie.png"),
        ("photo.jpeg", b"\xff\xd8\xff\xe0 jfif", "assets/photo.jpeg"),
        ("notes.pdf", png, "assets/notes.pdf"),
    ):
        request = urllib.request.Request(
            f"{base}/api/upload?file=figure.yaml&name={name}",
            data=data,
            headers={"X-Studio-Token": workspace.token},
        )
        assert json.loads(OPENER.open(request).read())["path"] == saved


# -- people and agents at once ------------------------------------------------------------


def test_edits_from_two_places_made_at_once_are_both_kept(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        first = SAMPLE_FIGURE.replace("Input $x$", "Input $x_0$")
        second = SAMPLE_FIGURE.replace("Output $y$", "Output $\\hat{y}$")
        doc.update({"text": first}, 1, PERSON)
        version, merged = doc.update(
            {"text": second}, 1, {"id": "agent", "name": "Claude", "kind": "agent"}
        )
        assert version == 3
        assert "$x_0$" in merged["text"] and "\\hat{y}" in merged["text"]
    finally:
        workspace.close()


def test_words_rewritten_while_typed_in_are_both_kept_and_said_to_the_typist(
    tmp_path: Path,
) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        listener = workspace.listen("page-a", PERSON)
        line = "# A figure: its shapes (nodes), then the lines between them (edges)."
        typed = SAMPLE_FIGURE.replace(line, line.replace("figure:", "figure my words:"))
        doc.update({"text": typed}, 1, PERSON, "page-a")
        agent = {"id": "agent", "name": "Claude", "kind": "agent"}
        _, merged = doc.update({"text": SAMPLE_FIGURE.replace(line, "# Not that.")}, 1, agent, "")
        assert merged["text"].startswith("# Not that. my words\nfigure:\n")
        told = []
        while not listener.events.empty():
            event = listener.events.get()
            if event["type"] == "merged":
                told.append(event)
        assert told == [
            {
                "type": "merged",
                "file": "figure.yaml",
                "client": "",
                "notes": [
                    {
                        "rewritten": "# Not that. my words\n",
                        "typed": "my words",
                        "by": agent,
                        "to": None,
                    }
                ],
            }
        ]
    finally:
        workspace.close()


def test_what_a_merge_kept_is_told_to_whoever_it_was_kept_for(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        listener = workspace.listen("page-a", PERSON)
        bob = {"id": "bob", "name": "Bob", "kind": "person"}
        item = {"text": "kept"}
        # Kept against the change's maker: the others' pages, by the maker; kept for the
        # maker: its own window, by the others; kept for the file on disk: no page.
        doc._tell([{"kept": "ours", "item": item}], bob, "window-b", PERSON)
        doc._tell([{"kept": "theirs", "item": item}], bob, "window-b", PERSON)
        doc._tell([{"kept": "theirs", "item": item}], bob, "", None)
        told = []
        while not listener.events.empty():
            told.append(listener.events.get())
        assert [event["notes"] for event in told] == [
            [{"kept": item, "by": bob, "to": None}],
            [{"kept": item, "by": PERSON, "to": "window-b"}],
        ]
    finally:
        workspace.close()


def test_the_file_changed_on_disk_is_taken_in_and_kept_with_unsaved_edits(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        agent = {"id": "mcp:claude-code", "name": "Claude Code", "kind": "agent"}
        workspace.set_presence(agent, "figure.yaml", None, "Renaming things")
        listener = workspace.listen("page", PERSON)
        # An edit here, not yet written, and the agent writes the file with its own tools.
        doc.update({"text": SAMPLE_FIGURE.replace("Encoder", "Encoder, here")}, 1, PERSON)
        time.sleep(0.02)
        (tmp_path / "figure.yaml").write_text(
            SAMPLE_FIGURE.replace("Output $y$", "Output, there"), encoding="utf-8"
        )
        wait_for(lambda: "Output, there" in doc.document["text"])
        assert "Encoder, here" in doc.document["text"]
        events = []
        while not listener.events.empty():
            events.append(listener.events.get())
        assert any(
            event["type"] == "doc" and event["who"]["name"] == "Claude Code" for event in events
        )
        wait_for(lambda: "Encoder, here" in (tmp_path / "figure.yaml").read_text(encoding="utf-8"))
    finally:
        workspace.close()


def test_a_file_on_disk_that_does_not_read_is_reported_and_ours_kept(tmp_path: Path) -> None:
    theme = tmp_path / "lab.yaml"
    theme.write_text("theme: {name: lab, base: paper}\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("lab.yaml")
        theme.write_text("theme: {name: lab, base: [\n", encoding="utf-8")
        wait_for(lambda: doc.problem is not None)
        assert doc.document == {"theme": {"name": "lab", "base": "paper"}}
    finally:
        workspace.close()


def test_a_file_on_disk_that_does_not_read_is_not_written_over(tmp_path: Path) -> None:
    theme = tmp_path / "lab.yaml"
    theme.write_text("theme: {name: lab, base: paper}\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("lab.yaml")
        listener = workspace.listen("page", PERSON)
        broken = "theme: {name: lab, base: [\n"
        theme.write_text(broken, encoding="utf-8")
        wait_for(lambda: doc.held)
        assert (doc.problem or "").startswith("Can\u2019t read lab.yaml: line ")
        assert doc.problem.count("lab.yaml") == 1
        # An edit made meanwhile is kept, and nothing is written over the file.
        mine = {"theme": {"name": "lab", "base": "paper", "description": "mine"}}
        doc.update(mine, doc.version, PERSON)
        time.sleep(0.8)
        workspace.flush()
        assert theme.read_text(encoding="utf-8") == broken
        # Mended on disk: what was written there and the edit made meanwhile, both, saved.
        theme.write_text("theme: {name: lab, base: ink}\n", encoding="utf-8")
        wait_for(lambda: "mine" in theme.read_text(encoding="utf-8"))
        assert doc.document == {"theme": {"name": "lab", "base": "ink", "description": "mine"}}
        assert doc.problem is None and not doc.held
        said = [event["type"] for event in _drained(listener)]
        said = [kind for kind in said if kind in {"problem", "saved"}]
        assert said[0] == "problem" and said[-1] == "saved"  # the page hears the problem is gone
    finally:
        workspace.close()


def test_a_change_on_disk_that_reads_tells_the_pages_the_file_is_saved(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        listener = workspace.listen("page", PERSON)
        changed = SAMPLE_FIGURE.replace("Encoder", "There")
        (tmp_path / "figure.yaml").write_text(changed, encoding="utf-8")
        wait_for(lambda: doc.version == 2)
        wait_for(lambda: any(event["type"] == "saved" for event in _drained(listener)))
        assert doc.saved == doc.version
    finally:
        workspace.close()


def test_a_file_moved_away_is_said_and_written_again_when_saved(tmp_path: Path) -> None:
    figure = tmp_path / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        figure.unlink()
        wait_for(lambda: doc.problem is not None)
        assert doc.problem == "figure.yaml was moved or deleted. Save (⌘S) to put it back."
        assert doc.info()["problem"] == doc.problem  # a page opened now says so too
        time.sleep(0.6)
        assert not figure.exists()  # not put back behind its person's back
        assert doc.write(again=True)
        assert figure.read_text(encoding="utf-8") == SAMPLE_FIGURE and doc.problem is None
    finally:
        workspace.close()


def test_a_file_renamed_while_open_is_followed_and_saved_under_its_new_name(
    tmp_path: Path,
) -> None:
    figure = tmp_path / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    told: list = []
    workspace.broadcast = told.append  # type: ignore[method-assign]
    try:
        doc = workspace.open("figure.yaml")
        figure.rename(tmp_path / "renamed.yaml")
        wait_for(lambda: doc.name == "renamed.yaml")
        assert doc.problem is None and workspace.docs["renamed.yaml"] is doc
        assert {"type": "renamed", "file": "figure.yaml", "to": "renamed.yaml"} in told
        # Edited after, it is saved there, never made again under its old name.
        text = doc.document["text"].replace("Encoder", "Decoder")
        doc.update({**doc.document, "text": text}, doc.version, {"id": "me", "name": "Me"})
        wait_for(lambda: "Decoder" in (tmp_path / "renamed.yaml").read_text(encoding="utf-8"))
        assert not figure.exists()
    finally:
        workspace.close()


def test_only_a_file_that_just_appeared_can_be_one_renamed_or_moved(tmp_path: Path) -> None:
    figure = tmp_path / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    (tmp_path / "figure copy.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    (tmp_path / "old").mkdir()
    workspace = Workspace(tmp_path)
    try:
        # Deleted: the copy that was there already, word for word the same, is another file.
        doc = workspace.open("figure.yaml")
        figure.unlink()
        wait_for(lambda: doc.problem is not None)
        assert doc.problem == "figure.yaml was moved or deleted. Save (⌘S) to put it back."
        assert doc.write(again=True) and doc.problem is None
        # Moved into a folder in its folder: followed there.
        time.sleep(0.6)
        figure.rename(tmp_path / "old" / "figure.yaml")
        wait_for(lambda: doc.name == "old/figure.yaml")
        assert doc.problem is None
    finally:
        workspace.close()


@pytest.mark.parametrize(
    ("name", "text"),
    [("figure.yaml", SAMPLE_FIGURE), ("lab.theme.yaml", "theme:\n  name: lab\n  base: paper\n")],
    ids=["figure", "theme"],
)
def test_a_document_moved_anywhere_in_its_folder_is_followed_and_saved_there(
    tmp_path: Path, name: str, text: str
) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")
    workspace = Workspace(tmp_path)
    me = {"id": "me", "name": "Me"}

    def moved(old: str, new: str) -> None:
        (tmp_path / new).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / old).rename(tmp_path / new)

    # Into a folder made as it is moved (the Finder's New Folder with Selection), up out of it
    # again, into a folder in a folder, and that folder renamed: followed each time, an edit
    # saved where it is, never a second copy where it was.
    steps = [
        (lambda: moved(name, f"New Folder With Items/{name}"), f"New Folder With Items/{name}"),
        (lambda: moved(f"New Folder With Items/{name}", name), name),
        (lambda: moved(name, f"a/b/{name}"), f"a/b/{name}"),
        (lambda: (tmp_path / "a").rename(tmp_path / "talks"), f"talks/b/{name}"),
    ]
    try:
        doc = workspace.open(name)
        for step, (move, now) in enumerate(steps):
            time.sleep(0.3)
            move()
            wait_for(lambda now=now: doc.name == now)
            assert doc.problem is None and not doc.gone and workspace.docs[now] is doc
            edited = json.loads(json.dumps(doc.document))
            if doc.kind.name == "figure":
                edited["text"] = edited["text"].replace("Encoder", f"Encoder {step}")
            else:
                edited["theme"]["description"] = f"Step {step}"
            doc.update(edited, doc.version, me)
            wait_for(lambda now=now, step=step: f" {step}" in (tmp_path / now).read_text("utf-8"))
            copies = [found.relative_to(tmp_path).as_posix() for found in tmp_path.rglob(name)]
            assert copies == [now]
    finally:
        workspace.close()


def test_a_document_gone_from_its_folder_holds_its_edits_until_it_is_found_or_saved(
    tmp_path: Path,
) -> None:
    folder, outside = tmp_path / "talks", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    figure = folder / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(folder)
    told: list = []
    workspace.broadcast = told.append  # type: ignore[method-assign]
    try:
        doc = workspace.open("figure.yaml")
        # Moved out of the studio's folder: nowhere it can find it.
        figure.rename(outside / "figure.yaml")
        wait_for(lambda: doc.gone)
        assert doc.problem == "figure.yaml was moved or deleted. Save (⌘S) to put it back."
        assert doc.info()["gone"] and doc.said()["gone"]
        # Edited meanwhile: the edit is held, never written where the file was.
        text = doc.document["text"].replace("Encoder", "Decoder")
        doc.update({**doc.document, "text": text}, doc.version, {"id": "me", "name": "Me"})
        time.sleep(0.8)
        assert not figure.exists() and doc.saved < doc.version
        # Brought back, into a folder of its own: found, followed, and the edit written there.
        (folder / "back").mkdir()
        (outside / "figure.yaml").rename(folder / "back" / "figure.yaml")
        wait_for(lambda: doc.name == "back/figure.yaml", seconds=10)
        wait_for(lambda: "Decoder" in (folder / "back" / "figure.yaml").read_text("utf-8"))
        assert not figure.exists() and not doc.gone and doc.problem is None
        assert {"type": "renamed", "file": "figure.yaml", "to": "back/figure.yaml"} in told
        # Deleted: written again where it was only as its person chooses, by a save.
        (folder / "back" / "figure.yaml").unlink()
        wait_for(lambda: doc.gone)
        assert doc.write(again=True) and not doc.gone
        assert "Decoder" in (folder / "back" / "figure.yaml").read_text("utf-8")
    finally:
        workspace.close()


def test_a_page_naming_a_followed_document_by_its_old_name_edits_it_where_it_went(
    tmp_path: Path,
) -> None:
    figure = tmp_path / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        (tmp_path / "New Folder").mkdir()
        figure.rename(tmp_path / "New Folder" / "figure.yaml")
        wait_for(lambda: doc.name == "New Folder/figure.yaml")
        # A window not yet told (or an edit on its way) still names it so: it is the document
        # where it went, not a new one made where it was.
        again = workspace.open("figure.yaml")
        assert again is doc and again.info()["file"] == "New Folder/figure.yaml"
        text = doc.document["text"].replace("Encoder", "Decoder")
        again.update({**doc.document, "text": text}, doc.version, {"id": "me", "name": "Me"})
        wait_for(lambda: "Decoder" in (tmp_path / "New Folder" / "figure.yaml").read_text("utf-8"))
        time.sleep(0.6)
        assert not figure.exists()
        # A new file made under the old name is a document of its own.
        figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
        assert workspace.open("figure.yaml") is not doc
    finally:
        workspace.close()


def test_a_refused_call_ends_its_connection(served: tuple[str, Workspace]) -> None:
    import socket

    base, _ = served
    port = int(base.rsplit(":", 1)[1])
    body = json.dumps({"file": "figure.yaml", "base": 1, "document": {"text": "x"}}).encode()
    refused = (
        f"POST /api/update HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Studio-Token: wrong\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    after = f"GET /api/session HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Studio-Token: wrong\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(refused + after.encode())
        answer = b""
        while chunk := connection.recv(65536):
            answer += chunk
    # Its body unread, it is not taken for a request of its own ("400 Bad request syntax").
    assert answer.startswith(b"HTTP/1.1 403") and answer.count(b"HTTP/1.1") == 1


def test_a_page_that_heard_from_an_earlier_studio_is_told_to_take_the_document_in(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    document = {"text": SAMPLE_FIGURE.replace("Encoder", "Decoder")}
    update = {"file": "figure.yaml", "base": 1, "document": document, "who": PERSON}
    status, result = call(f"{base}/api/update", workspace.token, {**update, "instance": "before"})
    assert status == 200 and result == {"restarted": True}
    assert workspace.open("figure.yaml").version == 1
    status, opened = call(f"{base}/api/open?file=figure.yaml", workspace.token)
    assert opened["instance"] == workspace.instance
    update["instance"] = workspace.instance
    status, result = call(f"{base}/api/update", workspace.token, update)
    assert status == 200 and result["version"] == 2


def test_a_file_that_does_not_read_is_not_saved_over(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    theme = workspace.root / "lab.yaml"
    theme.write_text("theme: {name: lab, base: paper}\n", encoding="utf-8")
    doc = workspace.open("lab.yaml")
    theme.write_text("theme: [\n", encoding="utf-8")
    status, answer = call(f"{base}/api/save", workspace.token, {"file": "lab.yaml"})
    assert status == 409 and "Can\u2019t read lab.yaml" in answer["error"] and doc.held
    assert theme.read_text(encoding="utf-8") == "theme: [\n"


class _Deck:
    """A kind of document as flexo-talk's decks are: a mapping with slides."""

    name, title, static = "deck", "Deck", Path(".")

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and "slides" in document and "nodes" not in document

    def new(self, path: Path) -> dict:
        return {"slides": [{"title": "A talk worth giving"}]}

    def load(self, path: Path) -> dict:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"{path.name} is not a deck")
        return document

    def save(self, path: Path, document: dict) -> None:
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


DECK = "deck: {id: talk}\nslides:\n- title: One\n  body: [{text: Hello}]\n- title: Two\n"
TYPO = DECK.replace("[{text: Hello}]", "[unclosed\n  - bullets: [a]")


def test_a_file_with_a_typo_opens_as_the_kind_its_keys_say_and_is_not_written(
    tmp_path: Path,
) -> None:
    talk = tmp_path / "talk.yaml"
    talk.write_text(TYPO, encoding="utf-8")
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    try:
        # Never read in this studio: the keys it still shows say it is a deck, not a figure.
        assert [item["kind"] for item in workspace.documents()] == ["deck"]
        doc = workspace.open("talk.yaml")
        assert doc.kind.name == "deck" and doc.unread and doc.held and doc.document == {}
        assert (doc.problem or "").startswith("Can\u2019t read talk.yaml: line 5")
        info = doc.info()
        assert info["unread"] and info["source"] == TYPO and info["problem"] == doc.problem
        # Nothing it shows is anything to change, and nothing is written over the file.
        with pytest.raises(ValueError, match="Nothing was changed"):
            doc.update({"slides": [{"title": "New"}]}, doc.version, PERSON)
        assert not doc.write(again=True)
        workspace.flush()
        assert talk.read_text(encoding="utf-8") == TYPO
        # Put right on disk: it opens as it reads, and is not written again.
        listener = workspace.listen("page", PERSON)
        talk.write_text(DECK, encoding="utf-8")
        wait_for(lambda: not doc.unread)
        assert doc.document == yaml.safe_load(DECK) and doc.problem is None and not doc.held
        assert doc.saved == doc.version
        said = [event["type"] for event in _drained(listener)]
        assert "doc" in said and said[-1] == "saved"
        assert talk.read_text(encoding="utf-8") == DECK
        assert not workspace.activity  # read at last is no change anyone made
    finally:
        workspace.close()


def test_a_figure_file_with_a_typo_is_one_that_cant_be_read_not_saved(tmp_path: Path) -> None:
    typo = "figure:\n  id: f\nnodes:\n  - {id: a, label: A\n  - {id: b}\n"
    figure = tmp_path / "flow.yaml"
    figure.write_text(typo, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("flow.yaml")
        # Said as a deck's or a theme's is, in its writer's words, its line named.
        assert doc.kind.name == "figure" and doc.unread and doc.held
        assert doc.problem == (
            "Can\u2019t read flow.yaml: line 5: a set of settings in braces isn\u2019t closed, "
            "or a word in it needs quotes"
        )
        assert doc.info()["source"] == typo
        assert not doc.write(again=True)
        assert figure.read_text(encoding="utf-8") == typo
        # Put right: it opens as it reads.
        figure.write_text(typo.replace("label: A\n", "label: A}\n"), encoding="utf-8")
        wait_for(lambda: not doc.unread)
        assert doc.problem is None and "label: A}" in doc.document["text"]
    finally:
        workspace.close()


class _Settling(_Deck):
    """A deck whose drawing, asked to settle, takes as long as it is let: a large figure laid
    out at its best."""

    hold = 20.0

    def draw(self, document: dict, base: Path, hints: dict | None = None):
        from flexo.draft import give_up_if_newer
        from flexo.studio import Drawing, Page

        if (hints or {}).get("settle"):
            deadline = time.monotonic() + self.hold
            while time.monotonic() < deadline:
                give_up_if_newer()
                time.sleep(0.01)
        return Drawing([Page("one", "<svg/>", "One")])


def test_a_drawing_that_yields_is_given_up_for_the_next_asked_for(tmp_path: Path) -> None:
    (tmp_path / "talk.yaml").write_text(DECK, encoding="utf-8")
    workspace = Workspace(tmp_path)
    kind = _Settling()
    workspace.kinds["deck"] = kind  # type: ignore[assignment]
    document = yaml.safe_load(DECK)
    answers: dict[str, dict] = {}

    def settle() -> None:
        hints = {"client": "page", "settle": True, "yields": True}
        answers["settle"] = workspace.draw("talk.yaml", document, 1, {}, hints)

    try:
        settling = threading.Thread(target=settle)
        started = time.monotonic()
        settling.start()
        wait_for(lambda: workspace.drawing.locked())
        # Changed again meanwhile: the next drawing is drawn at once, the settling given up.
        drawn = workspace.draw("talk.yaml", document, 2, {}, {"client": "page"})
        settling.join(5.0)
        assert time.monotonic() - started < 10.0
        assert answers["settle"] == {"version": 1, "stale": True}
        assert drawn["version"] == 2 and [page["id"] for page in drawn["pages"]] == ["one"]
        # One that does not yield is drawn to its end, as ever, the next waiting its turn.
        kind.hold = 1.0
        hints = {"client": "page", "settle": True}

        def late() -> None:
            answers["late"] = workspace.draw("talk.yaml", document, 3, {}, hints)

        waited = threading.Thread(target=late)
        waited.start()
        wait_for(lambda: workspace.drawing.locked())
        assert workspace.draw("talk.yaml", document, 4, {}, {"client": "page"})["version"] == 4
        waited.join(10.0)
        assert answers["late"]["version"] == 3 and not answers["late"].get("stale")
    finally:
        workspace.close()


def test_a_drawing_that_yields_gives_way_to_an_edit_asked_of_its_document(tmp_path: Path) -> None:
    (tmp_path / "talk.yaml").write_text(DECK, encoding="utf-8")
    workspace = Workspace(tmp_path)
    kind = _Settling()
    kind.hold = 3.0
    workspace.kinds["deck"] = kind  # type: ignore[assignment]
    document = yaml.safe_load(DECK)
    answers: list[dict] = []

    def settle() -> None:
        hints = {"client": "page", "settle": True, "yields": True}
        answers.append(workspace.draw("talk.yaml", document, len(answers) + 1, {}, hints))

    try:
        # One that only reads it (a figure's parts read to be shown) does not stop it ...
        settling = threading.Thread(target=settle)
        started = time.monotonic()
        settling.start()
        wait_for(lambda: workspace.drawing.locked())
        workspace.acting("talk.yaml", {"do": "figure", "edit": {"do": "read"}})
        settling.join(10.0)
        assert time.monotonic() - started > 2.5 and not answers[0].get("stale")
        # ... one that changes it does, at once: its drawing is the one worth waiting for.
        settling = threading.Thread(target=settle)
        started = time.monotonic()
        settling.start()
        wait_for(lambda: workspace.drawing.locked())
        workspace.acting("talk.yaml", {"do": "figure", "edit": {"do": "update"}})
        settling.join(10.0)
        assert time.monotonic() - started < 2.0
        assert answers[1] == {"version": 2, "stale": True, "edited": True}
    finally:
        workspace.close()


@pytest.mark.parametrize(
    ("text", "suffix", "kind"),
    [
        ("# a talk\nschema_version: 1\ndeck:\n  id: t\nslides: [unclosed\n", ".yaml", "deck"),
        ('{"deck": {"id": "t"}, "slides": [{"title": "One"}, {"title": ]}', ".json", "deck"),
        ("figure: {id: f}\nnodes:\n  - id: a\n    label: [oops\n", ".yaml", "figure"),
        ("theme:\n  name: lab\n  base: [\n", ".yaml", "theme"),
        ('"slides": [\n', ".yaml", "deck"),
        ("- one\n- two: [\n", ".yaml", None),
        ("words: [\n", ".yaml", None),
    ],
)
def test_the_kind_of_a_file_that_does_not_read_is_told_by_its_keys(
    tmp_path: Path, text: str, suffix: str, kind: str | None
) -> None:
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    try:
        assert workspace.kind_of_text(text, suffix) == kind
        (tmp_path / f"file{suffix}").write_text(text, encoding="utf-8")
        assert workspace.kind_on_disk(tmp_path / f"file{suffix}") == kind
    finally:
        workspace.close()


def test_a_file_put_right_where_the_studio_shows_it_is_written_once_it_reads(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    theme = workspace.root / "lab.yaml"
    theme.write_text("theme:\n  name: lab\n  base: [\n", encoding="utf-8")
    status, opened = call(f"{base}/api/open?file=lab.yaml", workspace.token)
    assert status == 200 and opened["kind"] == "theme" and opened["unread"]
    assert opened["source"] == "theme:\n  name: lab\n  base: [\n"
    # Still wrong: said, and nothing written.
    mend = {"file": "lab.yaml", "text": "theme:\n  name: lab\n  base: [paper\n"}
    status, answer = call(f"{base}/api/mend", workspace.token, mend)
    assert status == 400 and answer["error"].startswith("lab.yaml still can\u2019t be read: line ")
    assert theme.read_text(encoding="utf-8") == "theme:\n  name: lab\n  base: [\n"
    # Another kind's document: not written either.
    mend["text"] = "figure: {id: f}\nnodes: []\n"
    status, answer = call(f"{base}/api/mend", workspace.token, mend)
    assert status == 400 and answer["error"] == "That is a figure, not a theme."
    # Right: written as it is, and taken in.
    mend["text"] = "theme:\n  name: lab\n  base: paper  # ours\n"
    status, answer = call(f"{base}/api/mend", workspace.token, mend)
    assert status == 200
    assert theme.read_text(encoding="utf-8") == mend["text"]
    doc = workspace.open("lab.yaml")
    assert not doc.unread and doc.document == {"theme": {"name": "lab", "base": "paper"}}
    status, answer = call(f"{base}/api/mend", workspace.token, mend)
    assert status == 400 and "reads as it is" in answer["error"]


def test_a_kind_never_writes_over_a_file_another_kind_claims(tmp_path: Path) -> None:
    figure = tmp_path / "talk.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    try:
        doc = workspace.open("talk.yaml")
        assert doc.kind.name == "figure"
        listener = workspace.listen("page", PERSON)
        # The figure's words made a deck's (put right in its Source, say): written, as asked.
        doc.update({"text": DECK}, doc.version, PERSON)
        workspace.flush()
        assert figure.read_text(encoding="utf-8") == DECK
        assert doc.held and doc.foreign == "deck"
        assert doc.problem == "talk.yaml is a deck now, not a figure: it opens again as a deck."
        # It is open as a deck from now on, and the pages are told to open it again.
        again = workspace.open("talk.yaml")
        assert again is not doc and again.kind.name == "deck"
        assert again.document == yaml.safe_load(DECK)
        said = _drained(listener)
        assert {"type": "reopened", "file": "talk.yaml", "kind": "deck"} in said
        assert any(event["type"] == "problem" and event["text"] == doc.problem for event in said)
        # The figure editor making it a figure again (before it heard) writes nothing over it.
        doc.update({"text": DECK + "figure: {id: myfig}\nnodes: []\n"}, doc.version, PERSON)
        assert not doc.write(again=True)
        workspace.flush()
        assert figure.read_text(encoding="utf-8") == DECK
        # A figure again on disk (another app's doing): not taken into the deck, but opened
        # again as a figure.
        figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
        wait_for(lambda: workspace.docs["talk.yaml"].kind.name == "figure")
        assert again.held and again.foreign == "figure" and again.document == yaml.safe_load(DECK)
        assert workspace.open("talk.yaml").document == {"text": SAMPLE_FIGURE}
        assert {"type": "reopened", "file": "talk.yaml", "kind": "figure"} in _drained(listener)
        assert figure.read_text(encoding="utf-8") == SAMPLE_FIGURE
    finally:
        workspace.close()


def test_an_edit_made_in_another_kind_s_editor_is_sent_back_to_open_it_again(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    update = {"file": "figure.yaml", "base": 1, "kind": "deck", "who": PERSON,
              "document": {"slides": []}, "instance": workspace.instance}
    status, answer = call(f"{base}/api/update", workspace.token, update)
    assert status == 200 and answer == {"reopen": True, "kind": "figure"}
    assert (workspace.root / "figure.yaml").read_text(encoding="utf-8") == SAMPLE_FIGURE


def test_a_studio_stopped_by_kill_writes_the_edits_it_has_taken_first(tmp_path: Path) -> None:
    import os
    import signal
    import sys

    from flexo.studio import sessions

    figure = tmp_path / "figure.yaml"
    figure.write_text(SAMPLE_FIGURE, encoding="utf-8")
    studio = subprocess.Popen(
        [sys.executable, "-m", "flexo.studio.server", str(figure), "--no-browser"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        found: list[dict] = []

        def started() -> bool:
            for file in sessions._folder().glob("*.json"):
                with contextlib.suppress(OSError, ValueError):
                    found.append(json.loads(file.read_text(encoding="utf-8")))
            return bool(found)

        wait_for(started, 20)
        base, token = f"http://127.0.0.1:{found[0]['port']}", found[0]["token"]
        changed = {"text": SAMPLE_FIGURE.replace("Encoder", "Taken, then killed")}
        update = {"file": "figure.yaml", "base": 1, "document": changed, "who": PERSON}
        status, answer = call(f"{base}/api/update", token, update)
        assert status == 200 and answer["version"] == 2
        # At once: well before the studio would have written it of its own accord.
        os.kill(studio.pid, signal.SIGTERM)
        assert studio.wait(10) == 0, studio.stderr.read() if studio.stderr else ""
        assert figure.read_text(encoding="utf-8") == changed["text"]
        assert not list(sessions._folder().glob("*.json"))  # and it is off the list
    finally:
        if studio.poll() is None:
            studio.kill()


def test_a_studio_started_again_on_its_port_keeps_its_token(tmp_path: Path) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    tokens = []
    for folder in (tmp_path, tmp_path, tmp_path / "other"):
        folder.mkdir(exist_ok=True)
        server, workspace = start(folder, port=port, browser=False)
        tokens.append(workspace.token)
        workspace.close()
        server.server_close()
    # A page left open on it goes on working; another folder's studio is another matter.
    assert tokens[0] == tokens[1] != tokens[2]


def test_one_person_s_windows_are_one_person(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    ada = {"id": "ada", "name": "Ada", "kind": "person"}
    first, second = workspace.listen("window-1", ada), workspace.listen("window-2", ada)
    document = {"text": SAMPLE_FIGURE.replace("Encoder", "Decoder")}
    update = {"file": "figure.yaml", "base": 1, "document": document, "client": "window-1",
              "who": {"id": "ada", "name": "Ada"}}
    assert call(f"{base}/api/update", workspace.token, update)[0] == 200
    (event,) = [event for event in _drained(second) if event["type"] == "doc"]
    # The person made it, from the window that knows it as its own.
    assert event["who"]["id"] == "ada" and event["client"] == "window-1"
    workspace.set_presence(ada, "figure.yaml", None, None)
    workspace.leave(first)
    assert [entry["who"]["id"] for entry in workspace.present()] == ["ada"]
    workspace.leave(second)
    assert workspace.present() == []


def test_a_window_whose_connection_breaks_is_gone_soon_unless_it_is_back(
    served: tuple[str, Workspace],
) -> None:
    _, workspace = served
    ada = {"id": "ada", "name": "Ada", "kind": "person"}
    workspace.set_presence(ada, "figure.yaml", None, None)
    # A page reconnecting a moment later: its person never left.
    workspace.leave(workspace.listen("ada-1", ada), grace=0.2)
    workspace.listen("ada-2", ada)
    time.sleep(0.4)
    assert [entry["who"]["id"] for entry in workspace.present()] == ["ada"]
    # A window lost for good: its person goes once the grace is over.
    workspace.leave(workspace.listeners["ada-2"], grace=0.2)
    assert [entry["who"]["id"] for entry in workspace.present()] == ["ada"]
    wait_for(lambda: workspace.present() == [])


def test_a_studio_started_again_keeps_a_document_whose_file_went_meanwhile(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    try:
        # The page that held it asks for it as the kind it is open as: nothing is made anew.
        doc = workspace.open("gone.yaml", "theme", held=True)
        assert doc.kind.name == "theme" and not doc.exists
        assert doc.problem == "gone.yaml was moved or deleted. Save (⌘S) to put it back."
        time.sleep(0.6)
        assert not (tmp_path / "gone.yaml").exists()
    finally:
        workspace.close()


def test_a_file_renamed_while_the_studio_was_away_is_named(tmp_path: Path) -> None:
    class Named:
        name = "theme"

        def __init__(self, kind: object) -> None:
            self.kind = kind

        def __getattr__(self, key: str) -> object:
            return getattr(self.kind, key)

        def identity(self, document: object) -> object:
            return (document or {}).get("theme", {}).get("name")

    (tmp_path / "moved.yaml").write_text("theme:\n  name: gone\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        workspace.kinds["theme"] = Named(workspace.kinds["theme"])
        doc = workspace.open("gone.yaml", "theme", held=True)
        assert doc.moved == "moved.yaml" and doc.problem == "gone.yaml is gone: renamed moved.yaml?"
    finally:
        workspace.close()


def test_a_window_closing_is_gone_from_the_others_at_once(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    ada = {"id": "ada", "name": "Ada", "kind": "person"}
    bo = {"id": "bo", "name": "Bo", "kind": "person"}
    workspace.listen("ada-window", ada)
    watching = workspace.listen("bo-window", bo)
    workspace.set_presence(ada, "figure.yaml", None, None)
    _drained(watching)
    # The page's beacon as it closes, not a heartbeat that finds its connection dead.
    assert call(f"{base}/api/leave", workspace.token, {"client": "ada-window"})[0] == 200
    assert workspace.present() == []
    events = _drained(watching)
    assert any(event["type"] == "presence" and event["presence"] == [] for event in events)


def _drained(listener) -> list[dict]:
    events = []
    while not listener.events.empty():
        events.append(listener.events.get())
    return events


def test_the_agent_tools_read_edit_and_look(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        tools = Tools(workspace, {"id": "agent", "name": "Claude"})
        listed, failed = tools.call("list_documents", {})
        assert not failed and "figure.yaml: figure" in listed[0]["text"]
        opened, _ = tools.call("open_document", {"file": "figure.yaml"})
        assert "flexo figure file" in opened[0]["text"] and "version 1" in opened[1]["text"]
        blocks, failed = tools.call(
            "edit_document",
            {"file": "figure.yaml", "old": "label: Encoder", "new": "label: Decoder"},
        )
        assert not failed and "version 2" in blocks[0]["text"]
        blocks, failed = tools.call(
            "edit_document", {"file": "figure.yaml", "old": "label: Nothing", "new": "x"}
        )
        assert failed and "does not occur" in blocks[0]["text"]
        blocks, failed = tools.call(
            "edit_document", {"file": "figure.yaml", "old": "kind: text", "new": "kind: text"}
        )
        assert failed and "occurs 2 times" in blocks[0]["text"]
        looked, failed = tools.call("look", {"file": "figure.yaml"})
        assert not failed
        image = next(block for block in looked if block["type"] == "image")
        assert image["source"]["media_type"] == "image/png" and len(image["source"]["data"]) > 1000
        _, failed = tools.call("open_document", {"file": "themes/new.yaml", "kind": "theme"})
        assert not failed and (tmp_path / "themes/new.yaml").is_file()
        assert tools.call("status", {"doing": "Looking around"})[1] is False
        assert workspace.present()[0]["doing"] == "Looking around"
        notes = [entry["text"] for entry in workspace.activity]
        # (Said as the figure has it, not by the line of its file.)
        assert "renamed \u201cEncoder\u201d to \u201cDecoder\u201d" in notes
    finally:
        workspace.close()


def test_a_shape_renamed_as_it_is_typed_is_one_row_of_activity(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    try:
        me = {"id": "me", "name": "Me", "kind": "person"}
        where = {"page": 4, "label": "Slide 4"}
        said = "renamed \u201c{}\u201d to \u201c{}\u201d in the figure"
        for was, now in [("Customer", "S"), ("S", "Sh"), ("Sh", "Shoppe"), ("Shoppe", "Shopper")]:
            workspace.record(me, "talk.yaml", said.format(was, now), where)
        assert [entry["text"] for entry in workspace.activity] == [
            "renamed \u201cCustomer\u201d to \u201cShopper\u201d in the figure"
        ]
        # Another shape renamed next is a row of its own.
        workspace.record(me, "talk.yaml", said.format("API", "Gateway"), where)
        assert len(workspace.activity) == 2
    finally:
        workspace.close()


def test_an_agent_speaks_mcp_to_the_studio_open_on_its_folder(
    served: tuple[str, Workspace],
) -> None:
    from flexo.studio.mcp import serve

    _, workspace = served
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-code"}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "edit_document",
                "arguments": {"file": "figure.yaml", "old": "Encoder", "new": "Decoder"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "look", "arguments": {"file": "figure.yaml"}},
        },
    ]
    out = io.StringIO()
    serve(workspace.root, io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [answer["id"] for answer in answers] == [1, 2, 3, 4]
    assert answers[0]["result"]["protocolVersion"] == "2025-06-18"
    assert "look" in {tool["name"] for tool in answers[1]["result"]["tools"]}
    assert not answers[2]["result"]["isError"]
    assert any(item["type"] == "image" for item in answers[3]["result"]["content"])
    assert "Decoder" in workspace.open("figure.yaml").document["text"]
    assert workspace.present()[0]["who"]["name"] == "Claude Code"


# -- the assistant, with a stand-in for the API ------------------------------------------


class _Stream:
    def __init__(self, text: str, tools: list[tuple[str, dict]]) -> None:
        self.text, self.tools = text, tools

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield NS(type="text", text=self.text)

    def get_final_message(self):
        content = [_block(type="text", text=self.text)]
        content += [
            _block(type="tool_use", id=f"toolu_{i}", name=name, input=args)
            for i, (name, args) in enumerate(self.tools)
        ]
        return NS(content=content, stop_reason="tool_use" if self.tools else "end_turn")


def _block(**fields):
    return NS(**fields, model_dump=lambda **_: dict(fields))


class _Client:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **request):
        self.requests.append(request)
        return _Stream(*self.script.pop(0))


def test_the_assistant_edits_through_the_tools_and_says_so_to_everyone(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        client = _Client(
            [
                (
                    "I'll rename it.",
                    [
                        (
                            "edit_document",
                            {"file": "figure.yaml", "old": "Encoder", "new": "Decoder"},
                        )
                    ],
                ),
                ("Renamed.", []),
            ]
        )
        assistant = Assistant(workspace, client=client)
        listener = workspace.listen("page", PERSON)
        assistant.ask("Rename the encoder", {"file": "figure.yaml"}, PERSON)
        wait_for(lambda: not assistant.running)
        assert "Decoder" in workspace.open("figure.yaml").document["text"]
        first = client.requests[0]
        assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
        assert all(tool.get("eager_input_streaming") for tool in first["tools"])
        assert "figure.yaml" in first["messages"][0]["content"][0]["text"]
        history = client.requests[1]["messages"]
        results = [
            block
            for message in history
            if message["role"] == "user"
            for block in message["content"]
            if block["type"] == "tool_result"
        ]
        assert len(results) == 1 and "version 2" in results[0]["content"][0]["text"]
        turn = assistant.transcript[-1]
        assert [part["type"] for part in turn["parts"]] == ["text", "tool", "text"]
        assert turn["parts"][1]["state"] == "done"
        events = []
        while not listener.events.empty():
            events.append(listener.events.get())
        assert {"user", "turn", "text", "tool", "idle"} <= {
            e.get("event") for e in events if e["type"] == "assistant"
        }
        assert any(e["type"] == "doc" and e["who"]["name"] == "Claude" for e in events)
    finally:
        workspace.close()


def _chunk(content=None, calls=None, finish=None):
    delta = NS(content=content, refusal=None, tool_calls=calls)
    return NS(choices=[NS(delta=delta, finish_reason=finish)])


def _call(index, *, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


class _OpenAIClient:
    """Chat Completions, streamed: each reply a list of chunks."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))
        self.models = NS(list=lambda: [NS(id="gpt-5-mini"), NS(id="gpt-5.2"), NS(id="tts-1")])

    def _create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return iter(self.script.pop(0))


def test_chatgpt_answers_and_edits_through_the_same_tools(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        edit = '{"file": "figure.yaml", "old": "Encoder", "new": "Decoder"}'
        client = _OpenAIClient(
            [
                [
                    _chunk("I'll rename it."),
                    # Its call arrives in pieces, as a stream sends it.
                    _chunk(calls=[_call(0, id="call_1", name="edit_document", arguments="")]),
                    _chunk(calls=[_call(0, arguments=edit[:20])]),
                    _chunk(calls=[_call(0, arguments=edit[20:])], finish="tool_calls"),
                ],
                [_chunk("Renamed."), _chunk(finish="stop")],
            ]
        )
        assistant = Assistant(workspace)
        chatgpt = assistant.providers["chatgpt"]
        chatgpt.client, chatgpt.given = client, True
        assert assistant.choose("chatgpt") is None
        assert assistant.who["name"] == "ChatGPT"
        listener = workspace.listen("page", PERSON)
        assistant.ask("Rename the encoder", {"file": "figure.yaml"}, PERSON)
        wait_for(lambda: not assistant.running)
        assert "Decoder" in workspace.open("figure.yaml").document["text"]
        first, second = client.requests
        # The newest full GPT its list holds, as no model was set.
        assert first["model"] == "gpt-5.2" and first["stream"] is True
        assert first["messages"][0]["role"] == "system"
        assert "You are ChatGPT" in first["messages"][0]["content"]
        assert {tool["function"]["name"] for tool in first["tools"]} >= {"edit_document", "look"}
        answered = [message for message in second["messages"] if message["role"] == "tool"]
        assert len(answered) == 1 and answered[0]["tool_call_id"] == "call_1"
        assert "version 2" in answered[0]["content"]
        turn = assistant.transcript[-1]
        assert turn["name"] == "ChatGPT" and turn["provider"] == "chatgpt"
        assert [part["type"] for part in turn["parts"]] == ["text", "tool", "text"]
        events = []
        while not listener.events.empty():
            events.append(listener.events.get())
        assert any(e["type"] == "doc" and e["who"]["name"] == "ChatGPT" for e in events)
    finally:
        workspace.close()


def test_who_answers_can_change_and_the_conversation_goes_with_it(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        claude = _Client([("It has two blocks.", [])])
        assistant = Assistant(workspace, client=claude)
        assistant.ask("What is in it?", {"file": "figure.yaml"}, PERSON)
        wait_for(lambda: not assistant.running)
        openai = _OpenAIClient([[_chunk("Yes: Encoder and Decoder."), _chunk(finish="stop")]])
        chatgpt = assistant.providers["chatgpt"]
        chatgpt.client, chatgpt.given = openai, True
        assert assistant.choose("chatgpt", "gpt-5-mini") is None
        assert assistant.transcript[-1]["role"] == "switch"
        assistant.ask("Both of them?", {"file": "figure.yaml"}, PERSON)
        wait_for(lambda: not assistant.running)
        (request,) = openai.requests
        assert request["model"] == "gpt-5-mini"
        # Claude's words, carried over as words.
        roles = [message["role"] for message in request["messages"]]
        assert roles == ["system", "user", "assistant", "user"]
        assert request["messages"][2]["content"] == "It has two blocks."
        state = assistant.state()
        assert state["provider"] == "chatgpt" and state["model"] == "gpt-5-mini"
        assert [item["id"] for item in state["providers"]] == ["claude", "chatgpt", "other"]
        assert assistant.choose("nobody") is not None
        assert assistant.models("chatgpt")["models"] == ["gpt-5-mini", "gpt-5.2"]
    finally:
        workspace.close()


def test_the_newest_full_gpt_is_chosen_when_none_is_set() -> None:
    from flexo.studio.assistant import _newest_gpt

    names = ["gpt-4o", "gpt-5", "gpt-5.1-mini", "gpt-5.1", "gpt-5.1-2026-01-10", "o3"]
    assert _newest_gpt(names) == "gpt-5.1"
    assert _newest_gpt(["o3"]) is None


# -- keeping files safe ----------------------------------------------------------------------


def test_a_save_cut_short_leaves_the_file_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        doc.update({"text": SAMPLE_FIGURE.replace("Encoder", "Changed")}, doc.version, PERSON)

        def full(path: Path, document: dict) -> None:
            path.write_text(document["text"][:20])
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(doc.kind, "save", full)
        workspace.flush()
        assert (tmp_path / "figure.yaml").read_text() == SAMPLE_FIGURE
        assert "could not be saved: no space left on device" in (doc.problem or "")
        assert [path.name for path in tmp_path.iterdir()] == ["figure.yaml"]
    finally:
        monkeypatch.undo()
        workspace.close()
    assert "Changed" in (tmp_path / "figure.yaml").read_text()  # written once it could be


def test_a_file_that_cannot_be_written_does_not_stop_the_others(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(SAMPLE_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        for name in ("a.yaml", "b.yaml"):
            doc = workspace.open(name)
            doc.update({"text": SAMPLE_FIGURE.replace("Encoder", "Changed")}, doc.version, PERSON)
        (tmp_path / "a.yaml").unlink()
        (tmp_path / "a.yaml").mkdir()  # a folder where the file was: it cannot be written
        workspace.flush()
        assert "Changed" in (tmp_path / "b.yaml").read_text()
        assert "could not be saved" in (workspace.open("a.yaml").problem or "")
    finally:
        workspace.close()


def test_odd_files_in_the_folder_do_not_stop_it_opening(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE)
    (tmp_path / "date.yaml").write_text("released: 2024-02-30\n")
    (tmp_path / "deep.json").write_text("[" * 5000 + "]" * 5000)
    (tmp_path / "binary.yaml").write_bytes(bytes(range(256)))
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "other.yaml").write_text(SAMPLE_FIGURE)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    (tmp_path / "loop").mkdir()
    (tmp_path / "loop" / "again").symlink_to(tmp_path, target_is_directory=True)
    workspace = Workspace(tmp_path)
    try:
        assert [entry["file"] for entry in workspace.documents()] == ["figure.yaml"]
    finally:
        workspace.close()


def test_a_document_of_endless_aliases_is_refused(tmp_path: Path) -> None:
    letters = "abcdefghij"
    lines = ["a: &a [x, x, x, x, x, x, x, x, x, x]"]
    for index in range(1, 9):
        refs = ", ".join([f"*{letters[index - 1]}"] * 10)
        lines.append(f"{letters[index]}: &{letters[index]} [{refs}]")
    lines.append("theme: {name: bomb, notes: *i}")
    (tmp_path / "bomb.yaml").write_text("\n".join(lines) + "\n")
    workspace = Workspace(tmp_path)
    try:
        # Opened, but as nothing: why is said, and nothing is written over it.
        doc = workspace.open("bomb.yaml")
        assert doc.unread and doc.document == {} and "too large" in (doc.problem or "")
    finally:
        workspace.close()


def test_one_file_named_two_ways_is_one_document(tmp_path: Path) -> None:
    import unicodedata

    name = unicodedata.normalize("NFD", "résumé.yaml")
    (tmp_path / name).write_text(SAMPLE_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        first = workspace.open(name)
        again = workspace.open(unicodedata.normalize("NFC", "résumé.yaml"))
        assert first is again
    finally:
        workspace.close()


def test_two_studios_on_one_folder_are_both_found_until_each_closes(tmp_path: Path) -> None:
    from flexo.studio import sessions

    first, _ = start(tmp_path, browser=False)
    second, _ = start(tmp_path, browser=False)
    ports = [first.server_address[1], second.server_address[1]]
    try:
        assert sessions.find(tmp_path)["port"] in ports
        sessions.unregister(tmp_path, ports[1])
        assert sessions.find(tmp_path)["port"] == ports[0]
        sessions.unregister(tmp_path, ports[0])
        assert sessions.find(tmp_path) is None
    finally:
        first.server_close()
        second.server_close()


def test_a_folder_is_trusted_to_run_its_code_when_its_person_says(tmp_path: Path) -> None:
    from flexo.studio import code_allowed, folder_root

    server, workspace = start(tmp_path, browser=False, trusted=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        listener = workspace.listen("page", PERSON)
        assert call(f"{url}/api/session", workspace.token)[1]["trusted"] is False
        with workspace.running():
            assert code_allowed.get() is False and folder_root.get() == tmp_path.resolve()
        assert code_allowed.get() is True and folder_root.get() is None
        assert call(f"{url}/api/trust", workspace.token, {})[0] == 200
        assert call(f"{url}/api/session", workspace.token)[1]["trusted"] is True
        events = [listener.events.get(timeout=2) for _ in range(listener.events.qsize())]
        assert {"type": "trusted"} in events
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_the_studio_offers_to_make_only_the_kinds_it_was_started_with(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE)
    server, workspace = start(tmp_path, browser=False, offered=("theme",))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        kinds = call(f"{url}/api/session", workspace.token)[1]["kinds"]
        offered = {kind["name"]: kind["offered"] for kind in kinds}
        assert offered["figure"] is False and offered["theme"] is True
        # A kind not offered still opens.
        assert call(f"{url}/api/open?file=figure.yaml", workspace.token)[0] == 200
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_a_figure_drawn_in_the_studio_reads_no_file_outside_the_folder(tmp_path: Path) -> None:
    import struct
    import zlib

    folder = tmp_path / "sent"
    folder.mkdir()

    def png(path: Path) -> None:
        rows = b"\x00\xff\x00\x00"
        chunk = lambda kind, data: (  # noqa: E731
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )
        header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b"")
        )

    png(tmp_path / "private.png")
    png(folder / "own.png")
    figure = "figure: {id: f}\nnodes:\n- {id: a, kind: image, label: A, properties: {source: %s}}\n"
    workspace = Workspace(folder)
    try:
        for source, allowed in ((folder / "own.png", True), (tmp_path / "private.png", False)):
            name = f"{source.stem}.yaml"
            (folder / name).write_text(figure % source)
            doc = workspace.open(name)
            drawn = workspace.draw(name, doc.document, 1, {}, {})
            refused = any("outside the folder" in m["text"] for m in drawn["messages"])
            assert refused is not allowed, drawn["messages"]
    finally:
        workspace.close()


def test_a_photograph_is_sent_to_the_page_once_by_address_and_exported_whole(
    tmp_path: Path,
) -> None:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    rows = (b"\x00" + b"\x33\x66\xaa" * 600) * 400
    header = struct.pack(">IIBBBBB", 600, 400, 8, 2, 0, 0, 0)
    (tmp_path / "photo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    (tmp_path / "figure.yaml").write_text(
        "figure: {id: f}\nnodes:\n"
        "- {id: a, kind: image, label: A, properties: {source: photo.png}}\n"
    )
    server, workspace = start(tmp_path, browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        doc = workspace.open("figure.yaml")
        svg = workspace.draw("figure.yaml", doc.document, 1, {}, {})["pages"][0]["svg"]
        assert "data:image" not in svg and "/api/picture?" in svg
        found = re.search(r'href="(/api/picture\?[^"]+)"', svg)
        with OPENER.open(url + found.group(1).replace("&amp;", "&")) as response:
            assert response.headers["Cache-Control"].endswith("immutable")
            assert response.read().startswith(b"\x89PNG")
        body = {"file": "figure.yaml", "formats": ["editable"]}
        exported = call(f"{url}/api/export", workspace.token, body)[1]["files"]
        written = (tmp_path / exported[0]).read_text()
        assert "data:image/png;base64," in written and "/api/picture" not in written
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


# -- themes --------------------------------------------------------------------------------


def test_a_theme_is_drawn_on_samples_and_its_changes_named(tmp_path: Path) -> None:
    kind = ThemeKind()
    document = {
        "theme": {"name": "studio-test", "base": "paper", "palette": ["#8b1e3f", "#1d4e89"]}
    }
    drawing = kind.draw(document, tmp_path, {})
    assert [page.id for page in drawing.pages] == ["sample", "system"]
    assert drawing.info["effective"]["palette"][:2] == ["#8b1e3f", "#1d4e89"]
    assert drawing.info["tones"][0]["stroke"].startswith("#")
    assert kind.describe({"theme": {"name": "a"}}, document)[0]["text"] == "changed the name"
    assert kind.check({"theme": {"name": "x", "colours": []}}, tmp_path)
    assert "arrow_shape" in kind.catalog()["choices"]
    # Its full form exported under a plain name of its own, never the theme file's.
    [made] = kind.export(document, tmp_path, "Lab.theme", ["yaml"], into=tmp_path / "out")
    assert made.name == "Lab full theme.yaml" and "studio-test" in made.read_text()


def test_a_theme_is_shown_first_on_what_another_package_leads_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Figures alone showed a theme: a typeface changed for a deck's titles, its text or its
    code changed nothing on the page. A package that shows a theme on more (flexo-talk, on
    slides) now leads with what it has for that, before the figures."""

    from flexo.studio import theme_kind

    class Slides:
        title = "Slides"

        def pages(self, theme: str, base: Path, hints: dict) -> list:
            return []

        def lead(self, theme: str, base: Path, hints: dict) -> list:
            return [("type-slide", "Type on a slide", lambda: f"<svg data-theme='{theme}'/>")]

    class Broken(Slides):
        def lead(self, theme: str, base: Path, hints: dict) -> list:
            raise RuntimeError("nothing to lead with")

    kind = ThemeKind()
    document = {"theme": {"name": "led", "base": "paper"}}
    monkeypatch.setattr(theme_kind, "_specimens", lambda: {"slides": Slides(), "no": Broken()})
    drawing = kind.draw(document, tmp_path, {})
    assert [page.id for page in drawing.pages] == ["type-slide", "sample", "system"]
    # (A slide is shown as wide as its card, a figure at its own size: the page is told.)
    assert [page.extra for page in drawing.pages] == [{"slide": True}, {}, {}]
    assert "data-theme='led" in drawing.pages[0].svg
    assert kind.catalog()["specimens"][0] == {"name": "figures", "title": "Overview"}
    # With no such package there are the figures, called what they are.
    monkeypatch.setattr(theme_kind, "_specimens", lambda: {})
    assert [page.id for page in kind.draw(document, tmp_path, {}).pages] == ["sample", "system"]
    assert kind.catalog()["specimens"][0] == {"name": "figures", "title": "Figures"}


def test_a_theme_file_changed_is_read_again(tmp_path: Path) -> None:
    from flexo.theme_files import register_theme
    from flexo.themes import resolve_palette

    path = tmp_path / "lab.yaml"
    path.write_text(
        yaml.safe_dump({"theme": {"name": "lab-reread", "base": "paper", "palette": ["#111111"]}})
    )
    assert register_theme(path) == "lab-reread"
    first = resolve_palette("lab-reread").get("tone-1-stroke")
    time.sleep(0.01)
    path.write_text(
        yaml.safe_dump({"theme": {"name": "lab-reread", "base": "paper", "palette": ["#ee0000"]}})
    )
    register_theme(path)
    assert resolve_palette("lab-reread").get("tone-1-stroke") != first


def test_the_themes_offered_are_the_folder_s_files_then_flexo_s_own(tmp_path: Path) -> None:
    from flexo.studio import theming

    (tmp_path / "lab.theme.yaml").write_text(
        yaml.safe_dump({"theme": {"name": "lab-offered", "palette": ["#c2410c", "#1d4e89"]}})
    )
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "a.yaml").write_text(SAMPLE_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        found = theming.cards(workspace, "figures/a.yaml")
    finally:
        workspace.close()
    assert found[0]["value"] == "../lab.theme.yaml" and found[0]["source"] == "folder"
    assert found[0]["title"] == "lab-offered" and found[0]["tones"][0]["fill"].startswith("#")
    built_in = [card["value"] for card in found if card["source"] == "built-in"]
    assert {"paper", "classic"} <= set(built_in) and "lab-offered" not in built_in


def test_a_theme_file_is_put_to_use_in_several_figures_at_once(tmp_path: Path) -> None:
    from flexo.studio import theming

    (tmp_path / "lab.theme.yaml").write_text(
        yaml.safe_dump({"theme": {"name": "lab-used", "palette": ["#c2410c"]}})
    )
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(SAMPLE_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        listed = theming.uses(workspace, "lab.theme.yaml")
        before = {entry["file"]: entry["uses"] for entry in listed}
        after = theming.use(workspace, "lab.theme.yaml", ["a.yaml"], PERSON)
    finally:
        workspace.close()
    assert before == {"a.yaml": False, "b.yaml": False}
    assert {entry["file"]: entry["uses"] for entry in after} == {"a.yaml": True, "b.yaml": False}
    written = yaml.safe_load((tmp_path / "a.yaml").read_text())
    assert written["figure"]["style"] == "lab.theme.yaml"
    assert [node["id"] for node in written["nodes"]] == ["x", "encoder", "y"]


def test_a_drawn_figure_says_which_colour_each_tone_takes(tmp_path: Path) -> None:
    drawing = FigureKind().draw({"text": SAMPLE_FIGURE}, tmp_path, {})
    tones = drawing.info["tones"]
    assert tones["used"] == {"encoder": 1} and len(tones["colours"]) == 8
    assert tones["colours"][0]["fill"].startswith("#")
    # Its words' and its marks' colours too, and the grey's: a shape given a tone is painted
    # with them on the page at once (parts.js retoned).
    assert all(set(colour) == {"fill", "stroke", "ink", "motif"} for colour in tones["colours"])
    assert set(tones["neutral"]) == {"fill", "stroke", "ink", "motif"}


def test_the_figures_guide_for_agents_says_how_each_thing_is_written_and_says_it_truly() -> None:
    from flexo.compiler import compile_figure
    from flexo.serialization import parse_figure
    from flexo.studio.figure_kind import GUIDE

    said = (
        "kind: image", "kind: structure", "kind: mechanism", "kind: plot", "kind: frame",
        "title_side", "hide: [ids]", "role: panel", "line: dashed|dotted", "[*Ar]",
    )
    for words in said:
        assert words in GUIDE, words
    # Where a title stands is said of a group, and of a frame: the same four corners.
    corners = "title_side: left|right|bottom-left|bottom-right"
    assert GUIDE.replace("\n ", "").count(corners) == 2
    frame = GUIDE[GUIDE.index("kind: frame") :]
    frame = frame[: frame.index("A plot:")].replace("\n ", "")
    assert "title_side" in frame
    # And a line to a frame is said as one is written: the one it writes out is drawn.
    assert "An edge may start or end at a frame" in frame and "arrive: south" in frame
    written = yaml.safe_load(re.search(r"\{from: block, to: stage, arrive: south\}", frame)[0])
    document = {
        "figure": {"id": "guide"},
        "nodes": [
            {"id": "block"}, {"id": "held"},
            {"id": "stage", "kind": "frame", "properties": {"around": "held"}},
        ],
        "edges": [written],
    }
    drawn = compile_figure(parse_figure(document))
    (line,) = drawn.routed.edges
    assert line.centerline[-1].y == pytest.approx(drawn.frames[0].bounds.bottom)
    # The mechanisms it writes out are ones flexo draws: a real one, and one of placeholders.
    steps = (
        [
            {"smiles": "[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]", "arrows": ["5 -> 2", "2=3 -> 3"]},
            {"arrows": ["3 -> 2", "2-4 -> 4"]},
        ],
        [{"smiles": "[X:1].[Y:2][Z:3]", "arrows": ["1 -> 2", "2-3 -> 3"]}],
    )
    written = GUIDE.replace("\n  ", "")
    assert all(each[0]["smiles"] in written for each in steps)
    for each in steps:
        node = {"id": "r", "kind": "mechanism", "properties": {"steps": each}}
        document = {"figure": {"id": "guide"}, "nodes": [node]}
        assert "<svg" in compile_figure(parse_figure(document)).document.text


def test_the_figure_kind_and_theme_kind_are_always_there() -> None:
    found = kinds()
    assert isinstance(found["figure"], FigureKind) and isinstance(found["theme"], ThemeKind)
    assert FigureKind().claims({"nodes": []}) and not FigureKind().claims({"slides": []})
    assert ThemeKind().claims({"theme": {"name": "x"}})


def test_a_figure_that_does_not_read_says_where() -> None:
    kind = FigureKind()
    drawing = kind.draw({"text": "nodes: [\n  - id: x\n"}, Path("."))
    (message,) = drawing.messages
    assert message.severity == "error" and message.where.startswith("line ")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_merges_as_the_server_does() -> None:
    from flexo.studio.merge import merge3

    cases = [
        [
            {"slides": [{"t": "A"}, {"t": "B"}]},
            {"slides": [{"t": "A!"}, {"t": "B"}]},
            {"slides": [{"t": "N"}, {"t": "A"}, {"t": "B"}]},
        ],
        [{"a": 1, "b": 2}, {"a": 1, "c": 3}, {"a": 5, "b": 2}],
        ["one\ntwo\nthree\n", "ONE\ntwo\nthree\n", "one\ntwo\nTHREE\n"],
        ["The pipeline", "The pipeline by Alice", "Bob: The pipeline"],
        ["one two three", "one TWO three", "one 2 three"],
        ["terminal", "decision", "terminal2"],
        ["one\ntwo words here\n", "one\nfirst words here\n", "one\ntwo words there\n"],
        ["a\n", "b\n", "c\n"],
        ["naïve café", "naïve café au lait", "très naïve café"],
        [
            "First paragraph written by Alice.",
            "First m0 m1 m2 m3paragraph written by Alice.",
            "A completely different sentence.",
        ],
        ["First paragraph written by Alice.", "First m0 paragraph written by Alice.", "New."],
        ["a b c d e f", "a b e f", "a b c x d e f"],
        ["Title", "Title of the talk", "Heading"],
        ["First paragraph w", "First **paragraph** w", "First paraQQgraph w"],
        ["a paragraph", "a page", "a paraQQgraph"],
        ["What we asked \nWhy\n", "What we asked b\nWhy\n", "What we asked a\nWhy\n"],
        ["A m", "A m4", "A mc"],
        ["First m0 mparagraph by Alice.", "Not that. m0 m", "First m0 m3paragraph by Alice."],
        ["one\ntwo words here\nthree\n", "one\nfirst words here\n three\n", "one\nAll new\n"],
        [
            {"s": [{"t": "A"}]},
            {"s": [{"t": "A"}, {"t": "Mine"}]},
            {"s": [{"t": "A"}, {"t": "Theirs"}]},
        ],
        [
            {"body": [{"text": "First."}, {"text": "Second."}]},
            {"body": [{"text": "First."}, {"text": "Second, typed."}]},
            {"layout": "two", "left": [{"text": "First."}], "right": [{"text": "Second."}]},
        ],
        [
            {"left": [{"text": "A"}, {"text": "B"}], "right": [{"text": "R"}]},
            {"left": [{"text": "A"}], "right": [{"text": "R"}, {"text": "B"}]},
            {"left": [{"text": "A"}, {"text": "B, typed"}], "right": [{"text": "R"}]},
        ],
        [
            {"s": [{"t": "0"}, {"t": "1"}, {"t": "Q", "b": [{"x": "P"}]}]},
            {"s": [{"t": "0"}, {"t": "1"}, {"t": "Q", "b": [{"x": "P typed"}]}]},
            {"s": [{"t": "0"}, {"t": "Q moved", "b": [{"x": "P"}]}, {"t": "1"}]},
        ],
        # An object put on another slide while typed in; a shape renamed while typed in; two
        # new slides, alike, added at one place at once.
        [
            {"s": [{"b": [{"x": "A"}, {"x": "P"}]}, {"b": [{"y": 1}]}]},
            {"s": [{"b": [{"x": "A"}, {"x": "P typed"}]}, {"b": [{"y": 1}]}]},
            {"s": [{"b": [{"x": "A"}]}, {"b": [{"y": 1}, {"x": "P"}]}]},
        ],
        [
            {"nodes": [{"id": "a", "label": "Step one"}], "edges": [{"from": "a"}]},
            {"nodes": [{"id": "a", "label": "Step one typed"}], "edges": [{"from": "a"}]},
            {"nodes": [{"id": "z", "label": "Step one"}], "edges": [{"from": "z"}]},
        ],
        [{"s": [{"t": "A"}]}, {"s": [{"t": "A"}, {"t": ""}]}, {"s": [{"t": "A"}, {"t": ""}]}],
        # Two columns made one again while another added to the first: theirs goes with it.
        [
            {"left": [{"x": "A"}, {"x": "B"}], "right": [{"y": 1}]},
            {"body": [{"x": "A"}, {"x": "B"}, {"y": 1}]},
            {"left": [{"x": "A"}, {"x": "B"}, {"x": "New"}], "right": [{"y": 1}]},
        ],
    ]
    pairs = [
        [{"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}],
        [{"a": 1, "b": 2}, {"b": 2, "a": 1}],
        [{"a": 1}, {"a": 1, "b": 2}],
        [[1, 2], [1, 2, 3]],
        [{"a": [1]}, {"a": {"0": 1}}],
        ["1", 1],
        [None, {}],
    ]
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/merge.js"
    code = (
        f"import {{ merge3, same }} from {json.dumps(script.as_uri())};\n"
        f"const cases = {json.dumps(cases)};\n"
        f"const pairs = {json.dumps(pairs)};\n"
        "console.log(JSON.stringify([cases.map(([b, o, t]) => { const notes = [];"
        " return [merge3(b, o, t, notes), notes]; }), pairs.map(([a, b]) => same(a, b))]));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    merged, equal = json.loads(result.stdout)
    noted: list = [[] for _ in cases]
    assert merged == [
        [merge3(*case, notes), notes] for case, notes in zip(cases, noted, strict=True)
    ]
    assert equal == [True, True, False, False, False, False, False]


DRAWING = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Created with Inkscape -->\n'
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><circle r="4"/></svg>\n'
)
PASTES = """
const pasted = (files = [], words = "", html = "") => ({
  files: files.map((name) => new File(["x"], name)),
  getData: (type) => (type === "text/plain" ? words : type === "text/html" ? html : ""),
});
// What a paste brings as a drawing: "now" when nothing is waited for, else the file (or null).
const brought = async (paste) => {
  const drawing = pastedDrawing(paste);
  if (!drawing) return "now";
  const file = await drawing;
  return file && { name: file.name, type: file.type, words: await file.text() };
};
const asked = [];
const app = (answer) => {
  const clipboard_drawing = () => { asked.push(1); return answer(); };
  globalThis.pywebview = { api: { clipboard_drawing } };
};
const cases = [];
for (const paste of [pasted(["image.png"]), pasted([], DRAWING), pasted([], "Words")]) {
  cases.push(await brought(paste));
}
app(async () => DRAWING);
for (const paste of [pasted(["image.png"]), pasted(["image.tiff"]), pasted(), pasted([], "Words"),
  pasted(["figure.pdf"]), pasted(["logo.svg"]), pasted(["image.png", "notes.txt"]),
  pasted([], "", "<b>Words</b>")]) cases.push(await brought(paste));
const many = asked.length;
app(async () => "");
cases.push(await brought(pasted(["image.png"])));
app(async () => { throw new Error("gone"); });
cases.push(await brought(pasted(["image.png"])));
const words = [DRAWING, "  <svg>\\n</svg>  ",
  "<!DOCTYPE svg [ <!ENTITY a 'b'> ]><svg viewBox='0 0 1 1'></svg>",
  "See <svg></svg>", "<svg>", "<svgx></svgx>", "", null].map(svgOfWords);
console.log(JSON.stringify({ cases, many, words }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_drawing_copied_in_another_app_is_pasted_as_its_svg() -> None:
    """Inkscape copies a drawing as SVG and as a PNG of it, and the web view hands the page
    only the PNG: pasted, the drawing was a picture of it. The Mac app reads the SVG for the
    page whenever a picture of any kind came, or nothing it reads as words -- first, so the
    PNG beside it never wins; words, formatted words and a picture in a browser are pasted as
    they were, with nothing waited for."""

    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/clipboard.js"
    code = (
        f"import {{ pastedDrawing, svgOfWords }} from {json.dumps(script.as_uri())};\n"
        f"const DRAWING = {json.dumps(DRAWING)};\n" + PASTES
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    found = json.loads(done.stdout)
    drawing = {"name": "image.svg", "type": "image/svg+xml", "words": DRAWING.strip()}
    from_app = {**drawing, "words": DRAWING}
    # In a browser: only words that are a drawing.
    assert found["cases"][:3] == ["now", drawing, "now"]
    # In the Mac app: the drawing beside a picture of any kind (an SVG file, a picture with
    # another file), alone, or beside a file, or HTML, and no words (Inkscape's canvas) --
    # asked first, so the picture never wins; never for words, and the app asked only then.
    assert found["cases"][3:11] == [
        from_app, from_app, from_app, "now", from_app, from_app, from_app, from_app
    ]
    assert found["many"] == 7
    # (None there, or the app not answering: the picture is pasted.)
    assert found["cases"][11:] == [None, None]
    assert found["words"] == [
        DRAWING.strip(),
        "<svg>\n</svg>",
        "<!DOCTYPE svg [ <!ENTITY a 'b'> ]><svg viewBox='0 0 1 1'></svg>",
        None, None, None, None, None,
    ]


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


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_s_history_and_word_on_saving_are_its_own() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async (route, body) => (route === "/api/update"
    ? { version: 2, document: body.document } : { pages: [], messages: [] }),
};
const info = { file: "a.yaml", version: 1, saved: 1, exists: true, document: { title: "A" } };
const session = new Session(workspace, info);
const wait = () => new Promise((done) => setTimeout(done, 50));
const said = {};
// A letter typed and taken away again did nothing: nothing for the history.
session.change((d) => { d.title = "Ab"; }, { merge: "title" });
session.change((d) => { d.title = "A"; }, { merge: "title" });
said.typedAndDeleted = session.past.length;
// Another person's edit, not yet written, is not this page saving.
session.remote({ client: "other", version: 5, document: { title: "B" } });
said.othersEdit = session.state;
// A change put back elsewhere that cannot be: the history stays where it is.
session.record({ label: "Edit Figure", apply: () => Promise.reject(new Error("changed")) });
session.undo();
await wait();
said.failedUndo = [session.past.length, session.future.length];
session.record({ label: "Edit Figure", apply: () => Promise.resolve() });
session.undo();
await wait();
said.undone = [session.past.length, session.future.length];
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {
        "typedAndDeleted": 0, "othersEdit": "saved", "failedUndo": [1, 0], "undone": [1, 1]
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_change_of_a_figure_s_own_file_and_the_deck_together_is_one_step() -> None:
    """A figure's parts kept in a file of their own deleted with the slide's shapes: the deck's
    change and the file's, joined (mixing.js's joinSteps), are one step -- undone, the file is
    put back and the deck's change taken back, both by one ⌘Z; made again, both again."""
    root = Path(__file__).parents[2] / "src/flexo/studio/static/studio"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps((root / 'session.js').as_uri())});\n"
        f"const M = await import({json.dumps((root / 'mixing.js').as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const info = {
  file: "talk.yaml", version: 1, saved: 1, exists: true, document: { shapes: ["box", "ring"] },
};
const session = new Session(workspace, info);
const wait = () => new Promise((done) => setTimeout(done, 50));
const file = { text: "parts: [a, b]" }, put = [];
const said = {};
session.change((d) => { d.shapes = ["ring"]; }, { label: "Delete Rectangle" });
const from = session.past.length - 1;
session.record({ label: "Delete “a”", place: "Slide 3", where: 2, apply(target) {
  put.push(target);
  file.text = target === "before" ? "parts: [a, b]" : "parts: [b]";
  return Promise.resolve();
} });
file.text = "parts: [b]";
const joined = M.joinSteps(session, from, "Delete 1 Figure Shape and 1 Shape");
said.steps = [session.past.length, session.said(joined).text, session.said(joined).where];
session.undo();
await wait();
said.undone = [session.document.shapes, file.text, [...put], session.past.length,
  session.future.length];
const changes = [];
session.on("change", ({ source, entry }) => changes.push([source, entry?.text]));
session.redo();
await wait();
said.redone = [session.document.shapes, file.text, put, session.past.length,
  session.future.length, changes];
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {
        "steps": [1, "Delete 1 Figure Shape and 1 Shape", 2],
        "undone": [["box", "ring"], "parts: [a, b]", ["before"], 0, 1],
        "redone": [["ring"], "parts: [b]", ["before", "after"], 1, 0,
                   [["history", "Delete 1 Figure Shape and 1 Shape"]]],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_typing_held_in_one_place_undoes_alone_and_what_it_kept_is_said() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const body = (...words) => ({ body: words.map((text) => ({ text })) });
const info = { file: "a.yaml", version: 1, saved: 1, exists: true, document: body("P", "Q") };
const session = new Session(workspace, info);
const said = {};
// Words typed in one place, however long the pauses, with another's change come in
// meanwhile: one step, and undone it takes back the typing, not their change.
session.change((d) => { d.body[0].text = "P typed"; }, { merge: "p", hold: true });
session.remote({ client: "other", version: 2, document: body("P", "Q, theirs") });
session.change((d) => { d.body[0].text = "P typed on"; }, { merge: "p", hold: true });
said.steps = session.past.length;
session.undo();
said.undone = session.document;
// What they deleted while it was typed in here stays, and is said, with who did it.
const told = [];
session.on("merged", ({ notes }) => told.push(...notes));
session.synced = session.document;
session.change((d) => { d.body[0].text = "P again"; });
session.remote({ client: "other", version: 3, who: { name: "Bob" }, document: body("Q, theirs") });
said.kept = [session.document, told];
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    kept = {"text": "P again"}
    assert json.loads(result.stdout) == {
        "steps": 1,
        "undone": {"body": [{"text": "P"}, {"text": "Q, theirs"}]},
        "kept": [{"body": [kept, {"text": "Q, theirs"}]}, [{"kept": kept, "by": {"name": "Bob"}}]],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_undo_takes_back_only_its_own_words_while_another_types_on_after_them() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const opened = { file: "a.yaml", version: 1, saved: 1, exists: true };
const session = new Session(workspace, { ...opened, document: { text: "Second paragraph." } });
const said = { seen: [] };
let version = 1;
const comes = (text) => session.remote({ client: "bob", version: ++version, document: { text } });
// Typed here, a letter at a time, one run however long; then sent.
const type = (letter) => session.change((d) => { d.text += letter; }, { merge: "run", hold: true });
for (const letter of " alicewords") type(letter);
session.synced = session.document;
// Another types on after them, a letter at a time; this run is undone half way through his.
let theirs = session.document.text;
for (const [n, letter] of [..." bobafter"].entries()) {
  theirs += letter;
  comes(theirs);
  if (n === 3) {
    session.undo();
    session.synced = { text: theirs };  // as the studio has it, his letters on ours
  }
  said.seen.push(session.document.text);
}
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    seen = json.loads(result.stdout)["seen"]
    assert seen[3:] == [f"Second paragraph.{' bobafter'[:n + 1]}" for n in range(3, 9)]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_undo_of_notes_written_where_there_were_none_keeps_the_words_another_added() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const opened = { file: "a.yaml", version: 1, saved: 1, exists: true };
const slide = (notes) => ({
  slides: [{ title: "Why" }, { title: "Maturation", ...(notes === undefined ? {} : { notes }) }],
});
const session = new Session(workspace, { ...opened, document: slide() });
const notes = () => session.document.slides[1].notes ?? null;
const seen = [];
// Written here, a letter at a time, where the slide had no notes; then sent.
for (const letter of "Point at sfGFP's row.") {
  const add = (d) => { d.slides[1].notes = (d.slides[1].notes ?? "") + letter; };
  session.change(add, { merge: "notes", hold: true });
}
session.synced = session.document;
// Another adds a sentence to them; this page takes back its own.
const added = "Point at sfGFP's row. Mention mNeonGreen too.";
session.remote({ client: "bob", version: 2, document: slide(added) });
session.undo();
seen.push(notes());
session.redo();
seen.push(notes());
// Taken back again, and another writes on meanwhile: made again, both theirs stay.
session.undo();
session.synced = session.document;
session.remote({ client: "bob", version: 3, document: slide("Mention mNeonGreen too. Soon.") });
session.redo();
seen.push(notes());
// Nobody else wrote in them: taken back, the notes are gone, as they were.
const alone = new Session(workspace, { ...opened, document: slide() });
alone.change((d) => { d.slides[1].notes = "Mine alone."; }, { merge: "notes", hold: true });
alone.undo();
seen.push("notes" in alone.document.slides[1]);
// So in a list: a footnote added empty, written in here, and typed on in by another.
const listed = new Session(workspace, { ...opened, document: { footnotes: ["[1] Old", ""] } });
listed.change((d) => { d.footnotes[1] = "[2] Ours"; }, { merge: "footnote", hold: true });
listed.synced = listed.document;
const footnotes = ["[1] Old", "[2] Ours and theirs"];
listed.remote({ client: "bob", version: 2, document: { footnotes } });
listed.undo();
seen.push(listed.document.footnotes);
console.log(JSON.stringify(seen));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        "Mention mNeonGreen too.",
        "Point at sfGFP's row. Mention mNeonGreen too.",
        "Point at sfGFP's row. Mention mNeonGreen too. Soon.",
        False,
        ["[1] Old", "and theirs"],
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_an_undo_that_can_do_nothing_leaves_the_history_and_is_not_offered_again() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const opened = { file: "a.yaml", version: 1, saved: 1, exists: true, document: { title: "A" } };
const session = new Session(workspace, opened);
session.change((d) => { d.title = "A, typed"; }, { label: "Typing" });
session.change((d) => { d.size = 30; }, { label: "Change Font Size" });
session.synced = session.document;
// Another sets the size since: the undo can do nothing.
const theirs = { title: "A, typed", size: 40 };
session.remote({ client: "bob", who: { name: "Bob" }, version: 2, document: theirs });
session.undo();
const after = [session.document.size, session.past.map((e) => e.label), session.future.length];
// The step before it is the next undone.
session.undo();
console.log(JSON.stringify([after, session.document, session.future.map((e) => e.label)]));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    after, document, future = json.loads(result.stdout)
    assert after == [40, ["Typing"], 0]
    assert document == {"title": "A", "size": 40} and future == ["Typing"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_change_made_again_never_takes_away_what_others_did_since() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/merge.js"
    code = (
        f"import {{ replay }} from {json.dumps(script.as_uri())};\n"
        """
const seen = [];
const see = (...made) => {
  const [document, lost] = replay(...made);
  seen.push([document, lost.length]);
};
// Bold undone: the letters another typed in the word since stay.
see("First **paragraph** w", "First paragraph w", "First **paraQQgraph** w");
// Typing undone a run at a time, its letters among another's typed at the same place.
const runs = [
  ["Second paragraph.", "Second paragraph.  "],
  ["Second paragraph. ", "Second paragraph.  a"],
  ["Second paragraph. b a", "Second paragraph. b al"],
  ["Second paragraph. bo al", "Second paragraph. bo ali"],
];
let now = "Second paragraph. bob types too ali";
for (const [before, after] of [...runs].reverse()) now = replay(after, before, now)[0];
seen.push([now, 0]);
// Words rewritten by another since: nothing of theirs goes.
see("First paragraph. alpha", "First paragraph.", "Bob rewrote it all.");
// A setting another changed since stays theirs, and that is said.
see({ size: 30 }, {}, { size: 40 });
// An object another deleted since is not brought back.
const body = (...texts) => ({ body: texts.map((text) => ({ text })) });
see(body("P", "Second alice"), body("P", "Second"), body("P"));
// A slide another moved and retitled since is still the slide typed in: no copy of it.
const slide = (title, text) => ({ title, body: [{ text }] });
see({ slides: [{ title: "0" }, { title: "1" }, slide("Q", "Typed alice")] },
  { slides: [{ title: "0" }, { title: "1" }, slide("Q", "Typed")] },
  { slides: [{ title: "0" }, slide("Q moved", "Typed alice"), { title: "1" }] });
// A shape put between two, labelled by another since: the figure stays as they have it.
const figure = (nodes, edges) => ({ figure: { nodes: nodes.map((id) => ({ id })), edges } });
const added = figure(["a", "new", "b"], [{ from: "a", to: "new" }, { from: "new", to: "b" }]);
const labelled = structuredClone(added);
labelled.figure.nodes[1].label = "Bob's";
see(added, figure(["a", "b"], [{ from: "a", to: "b" }]), labelled);
// A word retyped here, retyped again by another (or typed onto by them): theirs stands.
const by = (word) => `First paragraph ${word} by Alice.`;
see(by("typed"), by("written"), by("composed"));
see(by("drafted"), by("written"), by("redrafted"));
// A layout undone after another typed in the slide: the slide as it was, with their words.
const two = (words) => ({ layout: "two", left: [{ text: "First." }], right: [{ text: words }] });
see(two("Second."), { body: [{ text: "First." }, { text: "Second." }] }, two("Second. bob"));
// Words typed in a shape just added (named by them), typed on in by another: only the first
// person's go -- the shape stays, with the other's words.
const shape = (id, label) => ({
  nodes: [{ id: "step" }, { id, ...(label ? { label } : {}) }],
  edges: [{ from: "step", to: id }],
});
const typed = shape("alice-shape", "Alice shape");
see(typed, shape("block"), shape("alice-shape", "Alice shape and Bob"));
// So in a figure's file: the line another has typed in keeps its key, with their words; the
// shape's own line is not taken from over it (the shape stays, and that is said); nor are
// lines with no key taken from about their words, leaving a file that no longer reads.
const file = (lines) => ({
  text: ["nodes:", "- id: c", ...lines, "edges:", "- from: c", "  to: b", ""].join("\\n"),
});
const label = (words) => ["- id: s", `  label: ${words}`];
see(file(label("Alice step")), file(["- id: s"]), file(label("Bob Alice step")));
see(file(["- id: s"]), file([]), file(label("Bob")));
const block = (words) => ["- id: s", "  label: |", `    ${words}`];
see(file(block("Alice step")), file(["- id: s"]), file(block("Bob Alice step")));
// Words made a list (or a list words), typed in by another since: undone, their words are
// followed through it, made the other kind again with the change -- not left beside it.
see({ bullets: ["Second."] }, { text: "Second." }, { bullets: ["Second. bob", "bob item"] });
const levels = ["What", "Why", ["and why still"]];
see({ text: "What\\nWhy\\nand why still" }, { bullets: levels, numbered: true },
  { text: "What\\nWhy\\nand why still bob" });
// Words typed, undone after another made them a callout: taken back from the callout.
see({ text: "Second alice" }, { text: "Second" }, { callout: "Second alice" });
console.log(JSON.stringify(seen));
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    seen = json.loads(result.stdout)
    assert seen[0] == ["First paraQQgraph w", 0]
    assert seen[1] == ["Second paragraph. bob types too", 0]
    assert seen[2] == ["Bob rewrote it all.", 0]
    assert seen[3] == [{"size": 40}, 1]
    assert seen[4] == [{"body": [{"text": "P"}]}, 1]
    moved = {"title": "Q moved", "body": [{"text": "Typed"}]}
    assert seen[5] == [{"slides": [{"title": "0"}, moved, {"title": "1"}]}, 0]
    assert seen[6][0]["figure"]["nodes"][1] == {"id": "new", "label": "Bob's"}
    assert len(seen[6][0]["figure"]["edges"]) == 2 and seen[6][1] > 0
    assert seen[7] == ["First paragraph composed by Alice.", 1]
    assert seen[8] == ["First paragraph redrafted by Alice.", 1]
    assert seen[9] == [{"body": [{"text": "First."}, {"text": "Second. bob"}]}, 0]
    kept = {"id": "block", "label": "and Bob"}
    lines = [{"from": "step", "to": "block"}]
    assert seen[10] == [{"nodes": [{"id": "step"}, kept], "edges": lines}, 0]
    assert "\n- id: s\n  label: Bob\nedges:" in seen[11][0]["text"] and seen[11][1] == 0
    assert "\n- id: s\n  label: Bob\nedges:" in seen[12][0]["text"] and seen[12][1] > 0
    assert seen[13][0]["text"].count("    Bob Alice step") == 1 and seen[13][1] > 0
    assert seen[14] == [{"text": "Second. bob\nbob item"}, 0]
    kept = {"bullets": ["What", "Why", ["and why still bob"]], "numbered": True}
    assert seen[15] == [kept, 0]
    assert seen[16] == [{"callout": "Second"}, 0]


def test_a_window_opened_again_leaves_nothing_of_the_last_one_behind(
    served: tuple[str, Workspace],
) -> None:
    _, workspace = served
    ada = {"id": "ada", "name": "Ada", "kind": "person"}
    old = workspace.listen("window-1", ada)
    typing = {"page": 4, "block": "body[1]", "editing": True}
    workspace.set_presence(ada, "figure.yaml", typing, None, "window-1")
    # Reloaded: a new window of the same person, somewhere else; the old one goes.
    workspace.listen("window-2", ada)
    workspace.set_presence(ada, "figure.yaml", {"page": 4}, None, "window-2")
    assert [entry["where"] for entry in workspace.present()] == [{"page": 4}]
    workspace.leave(old)
    assert [entry["where"] for entry in workspace.present()] == [{"page": 4}]


def test_each_person_here_has_a_colour_of_their_own(served: tuple[str, Workspace]) -> None:
    _, workspace = served
    people = [{"id": name, "name": name.title(), "kind": "person"} for name in ("ada", "bo", "cy")]
    for who in people[:2]:
        workspace.set_presence(who, "figure.yaml", None, None)
    assert [entry["colour"] for entry in workspace.present()] == [0, 1]
    # One gone, the next to come has the colour no one here has.
    workspace.absent(people[0])
    workspace.set_presence(people[2], "figure.yaml", None, None)
    colours = {entry["who"]["id"]: entry["colour"] for entry in workspace.present()}
    assert colours == {"bo": 1, "cy": 0}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_says_its_edits_wait_while_the_studio_is_out_of_reach() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
const listeners = {};
let reachable = true, draws = 0;
const opened = {
  file: "a.yaml", kind: "deck", version: 1, saved: 1, exists: true, document: { title: "A" },
};
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), url: (route) => route,
  on(event, listener) { (listeners[event] ||= []).push(listener); },
  async api(route, body) {
    if (!reachable) throw new TypeError("Failed to fetch");
    if (route === "/api/draw") { draws += 1; return { pages: [], messages: [] }; }
    return route === "/api/update" ? { version: 2, document: body.document } : opened;
  },
};
const session = new Session(workspace, opened);
workspace.sessions.set("a.yaml", session);
const wait = (ms = 50) => new Promise((done) => setTimeout(done, ms));
const said = {};
reachable = false;
listeners.online.forEach((listener) => listener(false));
session.change((d) => { d.title = "Typed while the studio is away"; });
await wait(200);
said.atOnce = session.state;  // a moment's break is not worth a word
await wait(1500);
said.later = [session.state, session.pendingLocal];
reachable = true;
listeners.online.forEach((listener) => listener(true));
await wait(300);
said.back = [session.state, session.pendingLocal];
session.saved(2);
said.saved = session.state;
// A file that has never read: nothing to draw until it reads.
const problem = "Can't read a.yaml: line 3";
const unread = new Session(workspace, { ...opened, unread: true, held: true, problem });
draws = 0;
await unread.draw();
said.unreadDraws = [unread.state, draws];
unread.told();
await wait(100);
said.readDraws = [unread.state, draws];
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {
        "atOnce": "saving", "later": ["offline", True], "back": ["saving", False],
        "saved": "saved", "unreadDraws": ["problem", 0], "readDraws": ["saved", 1],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_document_closed_and_opened_again_in_a_page_draws() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
// The studio's rule (Workspace.draw): a drawing older than the last this page asked for,
// of this document, is stale.
const latest = {};
const opened = {
  file: "a.yaml", kind: "deck", version: 1, saved: 1, exists: true, document: { title: "A" },
};
const workspace = {
  client: "page", me: { id: "me" }, sessions: new Map(), url: (route) => route, on() {},
  async api(route, body) {
    if (route !== "/api/draw") return opened;
    const key = `${body.file}\\u0000${body.hints.client}`;
    latest[key] = Math.max(latest[key] || 0, body.version);
    if (body.version < latest[key]) return { version: body.version, stale: true };
    return { pages: [], messages: [] };
  },
};
const drawn = async (session) => {
  let seen = 0;
  session.on("drawn", () => { seen += 1; });
  for (let n = 0; n < 3; n++) await session.draw();
  return seen;
};
const first = new Session(workspace, opened);
const again = new Session(workspace, opened);  // closed, and opened again in the same page
console.log(JSON.stringify([await drawn(first), await drawn(again)]));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [3, 3]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_page_asks_for_its_next_drawing_without_waiting_on_one_that_yields() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(script.as_uri())});\n"
        """
// The studio answers each drawing when told to: the page's asks are counted meanwhile.
const asked = [];
const opened = {
  file: "a.yaml", kind: "deck", version: 1, saved: 1, exists: true, document: { title: "A" },
};
const workspace = {
  client: "page", me: { id: "me" }, sessions: new Map(), url: (route) => route, on() {},
  api(route, body) {
    if (route !== "/api/draw") return Promise.resolve(opened);
    const { hints, version } = body;
    return new Promise((answer) => asked.push({ hints, answer, version }));
  },
};
const session = new Session(workspace, opened);
const tick = () => new Promise((done) => setTimeout(done, 80));
let settling = true;
session.hints = () => ({ settle: settling, yields: settling });
session.requestDraw(0);
await tick();
// Changed while it settles: the next drawing is asked for at once, not after it.
settling = false;
session.requestDraw(0);
await tick();
const overtaken = asked.length;
// While that one (which does not yield) is drawn, a change waits for it, as ever.
session.requestDraw(0);
await tick();
const waited = asked.length;
asked[0].answer({ version: asked[0].version, stale: true });
asked[1].answer({ version: asked[1].version, pages: [], messages: [] });
await tick();
asked[2].answer({ version: asked[2].version, pages: [], messages: [] });
await tick();
// Settling, given up for an edit that changed nothing (nothing newer asked for): asked again.
settling = true;
session.requestDraw(0);
await tick();
const before = asked.length;
asked[before - 1].answer({ version: asked[before - 1].version, stale: true });
await tick();
const again = asked.length - before;
// Given up for an edit asked of the studio: that edit's drawing is the next, not this again.
const then = asked.length;
asked[then - 1].answer({ version: asked[then - 1].version, stale: true, edited: true });
await tick();
const notAgain = asked.length - then;
const yielding = asked.map((one) => Boolean(one.hints.yields));
console.log(JSON.stringify([overtaken, waited, again, notAgain, yielding]));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [2, 2, 1, 0, [True, False, False, True, True]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_quotation_within_a_quotation_alternates_its_marks() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/ui.js"
    # (The marks spelled out: double opening and closing, single opening and closing.)
    dq, dc, sq, sc = "\u201c", "\u201d", "\u2018", "\u2019"
    code = FAKE_PAGE + (
        f"const {{ inQuotes }} = await import({json.dumps(script.as_uri())});\n"
        """
const [dq, dc, sq, sc] = ["\\u201c", "\\u201d", "\\u2018", "\\u2019"];
const label = `Typing in ${inQuotes(`Hello ${dq}world${dc} again`)}`;
const big = inQuotes(`Alice${sc}s ${sq}big${sc} day`);
// Straight marks typed in a name, made typographic at their depth; apostrophes left be.
const straight = inQuotes(`Typing in ${inQuotes(`Take the "fast" path, it's 'quick'`)}`);
const undo = inQuotes(`Undo ${inQuotes(label)}`);
console.log(JSON.stringify([label, inQuotes(label), undo, big, straight]));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        f"Typing in {dq}Hello {sq}world{sc} again{dc}",
        f"{dq}Typing in {sq}Hello {dq}world{dc} again{sc}{dc}",
        f"{dq}Undo {sq}Typing in {dq}Hello {sq}world{sc} again{dc}{sc}{dc}",
        f"{dq}Alice{sc}s {sq}big{sc} day{dc}",
        f"{dq}Typing in {sq}Take the {dq}fast{dc} path, it's {dq}quick{dc}{sc}{dc}",
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_edits_that_reached_the_studio_unanswered_are_not_entered_twice() -> None:
    session_js = Path(__file__).parents[2] / "src/flexo/studio/static/studio/session.js"
    merge_js = Path(__file__).parents[2] / "src/flexo/studio/static/studio/merge.js"
    code = FAKE_PAGE + (
        f"const {{ Session }} = await import({json.dumps(session_js.as_uri())});\n"
        f"const {{ merge3 }} = await import({json.dumps(merge_js.as_uri())});\n"
        """
const listeners = {};
const deck = (words, ...more) => ({ slides: [{ title: "Q", body: [{ text: words }] }, ...more] });
// The studio: each version kept, an update merged from the version it was made from.
let studio, lose = false, reachable = true;
const start = (document, instance, unread = false) => {
  studio = { instance, versions: { 1: document }, version: 1, unread };
};
start(deck("Second paragraph."), "one");
const info = () => ({
  file: "a.yaml", kind: "deck", version: studio.version, saved: studio.version, exists: true,
  document: studio.unread ? {} : studio.versions[studio.version], instance: studio.instance,
  unread: studio.unread, held: studio.unread,
});
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), url: (route) => route,
  on(event, listener) { (listeners[event] ||= []).push(listener); },
  async api(route, body) {
    if (route === "/api/draw") return { pages: [], messages: [] };
    if (!reachable) throw new TypeError("Failed to fetch");
    if (route !== "/api/update") return info();
    if (body.instance !== studio.instance) return { restarted: true };
    const now = studio.versions[studio.version];
    studio.version += 1;
    studio.versions[studio.version] = merge3(studio.versions[body.base], now, body.document);
    // Taken in, but its answer lost on the way back.
    if (lose) { lose = false; reachable = false; throw new TypeError("Failed to fetch"); }
    return { version: studio.version, document: studio.versions[studio.version] };
  },
};
const wait = (ms = 50) => new Promise((done) => setTimeout(done, ms));
const words = (document) => document.slides?.map((slide) => slide.body[0].text).join(" | ");
const said = {};
const session = new Session(workspace, info());
workspace.sessions.set("a.yaml", session);
const type = (letters) => session.change((d) => { d.slides[0].body[0].text += letters; });
const away = () => { reachable = false; listeners.online.forEach((listener) => listener(false)); };
const back = () => { reachable = true; listeners.online.forEach((listener) => listener(true)); };
type(" abc");
await wait(150);
// The studio takes in "d", but its answer never comes; "ef" is typed meanwhile.
lose = true;
type("d");
await wait(150);
type("ef");
back();
await wait(400);
said.unanswered = [words(session.document), words(studio.versions[studio.version])];
// So too when it stops as the answer comes, and starts again on the file it wrote ("g" in).
lose = true;
type("g");
await wait(150);
start(studio.versions[studio.version], "two");
type("hi");
back();
await wait(400);
said.restarted = [words(session.document), words(studio.versions[studio.version])];
// Started again on a file that does not read while "jk" is typed: once it reads (as it was
// last written), the words are in their slide once, and no slide is a copy.
const written = studio.versions[studio.version];
session.saved(studio.version);
away();
type("jk");
await wait(100);
start(written, "three", true);
back();
await wait(400);
said.unread = [words(session.document), words(studio.versions[studio.version])];
studio.unread = false;
studio.version += 1;
studio.versions[studio.version] = written;
session.told();
session.remote({ type: "change", version: studio.version, document: written, client: "disk" });
await wait(400);
said.read = [words(session.document), words(studio.versions[studio.version])];
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    words = "Second paragraph. abc"
    assert json.loads(result.stdout) == {
        "unanswered": [f"{words}def"] * 2,
        "restarted": [f"{words}defghi"] * 2,
        "unread": [f"{words}defghijk", f"{words}defghi"],
        "read": [f"{words}defghijk"] * 2,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_dragged_on_the_drawing_goes_where_it_is_let_go() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    model = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "column"}, "children": ["bench", "analysis"]},
            {"id": "bench", "layout": {"kind": "row"}, "children": ["a", "b", "c"]},
            {"id": "analysis", "layout": {"kind": "row"}, "children": ["d", "e"]},
        ],
    }
    boxes = {
        "root": [0, 0, 300, 130],
        "bench": [0, 0, 300, 50],
        "a": [10, 10, 60, 40],
        "b": [110, 10, 160, 40],
        "c": [210, 10, 260, 40],
        "analysis": [0, 80, 200, 130],
        "d": [10, 90, 60, 120],
        "e": [110, 90, 160, 120],
    }
    drags = [
        ["c", 5, 25],  # before the first of its row
        ["c", 85, 25],  # between a and b
        ["d", 290, 25],  # into the row above, at its end
        ["a", 150, -20],  # out of its row, above it
        ["e", 500, 500],  # far from the figure: nowhere
        ["bench", 100, 25],  # a group over itself: where it is
        ["e", 350, 60],  # past the end of a column: a column of its own, right of it
    ]
    code = (
        f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(model)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  if (!place) return null;\n"
        "  const kept = stays(model, place, id);\n"
        "  if (place.kind === 'line') return { line: place.side, of: place.of, stays: kept };\n"
        "  return { parent: place.parent, index: place.index, stays: stays(model, place, id) };\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        {"parent": "bench", "index": 0, "stays": False},
        {"parent": "bench", "index": 1, "stays": False},
        {"parent": "bench", "index": 3, "stays": False},
        {"parent": "root", "index": 0, "stays": False},
        None,
        {"parent": "root", "index": 0, "stays": True},
        {"line": "right", "of": "root", "stays": False},
    ]
    # Under a figure laid out in a row: a line of its own; just under it, still in the row.
    row = {
        "root": "root",
        "groups": [{"id": "root", "layout": {"kind": "row"}, "children": ["a", "b", "c"]}],
    }
    boxes = {
        "root": [0, 0, 300, 50],
        "a": [10, 10, 60, 40],
        "b": [110, 10, 160, 40],
        "c": [210, 10, 260, 40],
    }
    drags = [["c", 150, 120], ["c", 150, 55], ["c", 150, -60], ["c", 150, 400]]
    code = (
        f"import {{ dropPlace }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(row)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  return place && (place.kind === 'line' ? place.side : place.parent);\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == ["below", "root", "above", None]
    # Well under one part, in line with it: under that part; between parts, a row of its own.
    drags = [["c", 135, 90], ["c", 85, 90], ["a", 235, 95]]
    code = code.replace(
        "return place && (place.kind === 'line' ? place.side : place.parent);",
        "return place && (place.kind === 'line' ? `${place.side} of ${place.of}` : place.parent);",
    ).replace(json.dumps([["c", 150, 120], ["c", 150, 55], ["c", 150, -60], ["c", 150, 400]]),
              json.dumps(drags))
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == ["below of b", "below of root", "below of c"]
    # A row folded onto two lines: under its first line is its second, the row's own; and
    # a part let go over where it was drawn (a nudge) stays where it is.
    folded = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "row"}, "children": ["a", "b", "c", "d", "e", "f"]},
    ]}
    boxes = {
        "root": [0, 0, 300, 130],
        "a": [10, 10, 60, 40], "b": [110, 10, 160, 40], "c": [210, 10, 260, 40],
        "d": [10, 90, 60, 120], "e": [110, 90, 160, 120], "f": [210, 90, 260, 120],
    }
    drags = [["e", 140, 100], ["f", 135, 80], ["a", 85, 105]]
    code = (
        f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(folded)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  if (place.kind === 'line') return `${place.side} of ${place.of}`;\n"
        "  return stays(model, place, id) ? 'stays' : place.index;\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == ["stays", 4, 3]
    # In a row as tall as the column beside its part: under that part, where there is room.
    tall = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "column"}, "children": ["row", "s"]},
        {"id": "row", "layout": {"kind": "row"}, "children": ["u", "col"]},
        {"id": "col", "layout": {"kind": "column"}, "children": ["t", "st"]},
    ]}
    boxes = {
        "root": [0, 0, 300, 260], "row": [0, 0, 300, 170], "col": [150, 0, 290, 170],
        "u": [10, 10, 90, 50], "t": [160, 10, 280, 50], "st": [160, 120, 280, 160],
        "s": [100, 200, 200, 240],
    }
    code = (
        f"import {{ dropPlace }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(tall)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        "const place = dropPlace(model, boxes, { x: 50, y: 110 }, 's');\n"
        "console.log(JSON.stringify(`${place.side} of ${place.of}`));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == "below of u"
    # Level with a part in a column and off to its side: beside it; over it, still in line.
    column = {
        "root": "root",
        "groups": [{"id": "root", "layout": {"kind": "column"}, "children": ["a", "b", "c"]}],
    }
    boxes = {
        "root": [0, 0, 300, 160],
        "a": [100, 10, 200, 40],
        "b": [130, 60, 170, 90],
        "c": [100, 110, 200, 140],
    }
    drags = [["c", 230, 75], ["c", 100, 75], ["c", 175, 75], ["a", 150, 100]]
    code = (
        f"import {{ dropPlace }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(column)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  if (!place) return null;\n"
        "  return place.kind === 'line' ? `${place.side} of ${place.of}` : place.index;\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == ["right of b", "left of b", 1, 1]
    # Anywhere in the free space under a column's last part, in line with it: under it, in
    # its column -- not only just under it, nor a new row under the whole figure.
    beside = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "row"}, "children": ["a", "col"]},
            {"id": "col", "layout": {"kind": "column"}, "children": ["b", "c"]},
        ],
    }
    boxes = {
        "root": [0, 0, 300, 150], "a": [10, 60, 60, 90], "col": [100, 0, 200, 150],
        "b": [110, 10, 190, 40], "c": [110, 110, 190, 140],
    }
    drags = [["a", 150, 146], ["a", 150, 200], ["a", 150, 270], ["a", 150, 75]]
    code = (
        f"import {{ dropPlace }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(beside)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  return place.kind === 'line' ? `${place.side} of ${place.of}` : place.index;\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == ["below of c", "below of c", "below of c", 1]


def test_an_agent_reads_a_file_that_does_not_read_as_written_and_puts_it_right(
    tmp_path: Path,
) -> None:
    from flexo.studio.agent import Tools

    talk = tmp_path / "talk.yaml"
    talk.write_text(TYPO, encoding="utf-8")
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    try:
        tools = Tools(workspace, {"id": "agent", "name": "Claude"})
        said, failed = tools.call("read_document", {"file": "talk.yaml"})
        assert not failed and TYPO in said[0]["text"]
        assert "Can\u2019t read talk.yaml" in said[0]["text"]
        said, failed = tools.call("write_document", {"file": "talk.yaml", "text": DECK})
        assert not failed, said
        doc = workspace.open("talk.yaml")
        assert not doc.unread and doc.document == yaml.safe_load(DECK)
        assert talk.read_text(encoding="utf-8") == DECK
    finally:
        workspace.close()


def test_a_copy_the_studio_made_that_no_document_uses_goes_when_it_closes(tmp_path: Path) -> None:
    (tmp_path / "talk.yaml").write_text(DECK.replace("Hello", "assets/kept.png"), encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    kept, undone, theirs = assets / "kept.png", assets / "undone.png", assets / "theirs.png"
    for file in (kept, undone, theirs):
        file.write_bytes(b"png")
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    workspace.open("talk.yaml")
    workspace.uploads.update({kept, undone})  # copies it made; theirs was there before
    workspace.close()
    assert kept.is_file() and theirs.is_file() and not undone.exists()


def test_a_copy_the_studio_made_goes_when_undone_and_comes_back_when_redone(tmp_path: Path) -> None:
    (tmp_path / "talk.yaml").write_text(DECK, encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    picture, named = assets / "picture.png", assets / "named.png"
    for file in (picture, named):
        file.write_bytes(b"png")
    # Another document, not open here, names one of them.
    (tmp_path / "other.yaml").write_text("slides:\n- body: [{image: assets/named.png}]\n", "utf-8")
    workspace = Workspace(tmp_path)
    workspace.kinds["deck"] = _Deck()  # type: ignore[assignment]
    try:
        doc = workspace.open("talk.yaml")
        plain = doc.document
        workspace.uploads.update({picture, named})  # copies it made, not yet used
        doc.update({**plain, "slides": [{"title": "Typed"}]}, doc.version, PERSON)
        assert picture.is_file() and named.is_file()  # its document has yet to use it
        pictures = [{"image": "assets/picture.png"}, {"image": "assets/named.png"}]
        shown = {**plain, "slides": [{"body": pictures}]}
        doc.update(shown, doc.version, PERSON)
        doc.update(plain, doc.version, PERSON)  # undone: gone at once, but not one named elsewhere
        assert not picture.exists() and named.is_file()
        doc.update(shown, doc.version, PERSON)  # redone: back, as it was
        assert picture.read_bytes() == b"png"
    finally:
        workspace.close()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_under_a_row_is_dragged_to_centre_under_one_of_its_parts_or_the_row() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    model = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "column"}, "children": ["row", "e"]},
            {"id": "row", "layout": {"kind": "row"}, "children": ["a", "b", "c", "d"]},
        ],
    }
    boxes = {
        "root": [0, 0, 370, 130],
        "row": [10, 10, 360, 40],
        "a": [10, 10, 60, 40],
        "b": [110, 10, 160, 40],
        "c": [210, 10, 260, 40],
        "d": [310, 10, 360, 40],
        "e": [145, 100, 225, 130],
    }
    # (Each: the pointer, and where the part's middle is as it is dragged.)
    drags = [[140, 115, 136], [190, 115, 186], [330, 110, 338], [60, 118, 30], [190, 400, 186]]
    code = (
        f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(model)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([x, y, middle]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, 'e', { x: middle, y });\n"
        "  if (!place || place.kind !== 'align') return place && place.kind;\n"
        "  return { with: place.with, centred: place.centred, stays: stays(model, place, 'e') };\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        # Along its own line, under "b", under the row as it is (where it stays), under "d",
        # and past the row's left end, under "a" -- its middle judged, not the pointer.
        {"with": "b", "centred": False, "stays": False},
        {"with": "row", "centred": True, "stays": True},
        {"with": "d", "centred": False, "stays": False},
        {"with": "a", "centred": False, "stays": False},
        # Well under its own line, it is placed in the column as before.
        None,
    ]


def _places(model: dict, boxes: dict, drags: list, shown: str) -> list:
    """Where each of ``drags`` (the part, the pointer's x and y, and where the part's middle
    then is) would go, by drop.js alone: ``shown``, an expression of ``place`` and ``kept``
    (whether the part stays where it is)."""

    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    code = (
        f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(model)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)}).map(([id, box]) => "
        "[id, box && { left: box[0], top: box[1], right: box[2], bottom: box[3] }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y, middle]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id, { x: middle ?? x, y });\n"
        "  const kept = stays(model, place, id);\n"
        f"  return {shown};\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_alone_on_the_last_line_of_a_folded_row_goes_under_a_part_of_the_line_over() -> None:
    # A row seen folded onto two lines, its last part alone on the second: each line a group
    # that only arranges its parts, as the page sees them and as the server writes them.
    model = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "column"}, "children": ["root~line1", "root~line2"]},
        {"id": "root~line1", "role": "layout", "layout": {"kind": "row"},
         "children": ["a", "b", "c", "d"]},
        {"id": "root~line2", "role": "layout", "layout": {"kind": "row"}, "children": ["e"]},
    ]}
    boxes = {
        "root": [0, 0, 370, 130], "root~line1": [10, 10, 360, 40],
        "root~line2": [145, 100, 225, 130],
        "a": [10, 10, 60, 40], "b": [110, 10, 160, 40], "c": [210, 10, 260, 40],
        "d": [310, 10, 360, 40], "e": [145, 100, 225, 130],
    }
    shown = ("place && (place.kind === 'align' ? [place.with, place.centred, kept, place.line, "
             "place.parent, place.index] : place.kind)")
    drags = [["e", 140, 115, 136], ["e", 240, 46, 236], ["e", 190, 115, 186], ["e", 190, 400, 186]]
    assert _places(model, boxes, drags, shown) == [
        # Along its own line -- and just under the line over it -- under the part its middle
        # is nearest: its own line named, to take that line's place in the column.
        ["b", False, False, "root~line2", "root", 1],
        ["c", False, False, "root~line2", "root", 1],
        # Under the line as a whole, where it is drawn already: it stays.
        ["root~line1", True, True, "root~line2", "root", 1],
        None,
    ]
    # Not alone on its line, nor in a group with a title (or a frame) of its own: placed as ever.
    for change in ({"children": ["e", "f"]}, {"label": "Result"}, {"role": "module"}):
        other = {**model, "groups": [*model["groups"][:2], {**model["groups"][2], **change}]}
        more = {**boxes, "e": [145, 100, 180, 130], "f": [190, 100, 225, 130]}
        assert _places(other, more, [["e", 140, 115, 136]], "place && place.kind") != ["align"]
    # A part under a row seen folded: under a part of that row's last line, never a line.
    under = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "column"}, "children": ["flow", "e"]},
        {"id": "flow", "layout": {"kind": "column"}, "children": ["flow~line1", "flow~line2"]},
        {"id": "flow~line1", "role": "layout", "layout": {"kind": "row"}, "children": ["a", "b"]},
        {"id": "flow~line2", "role": "layout", "layout": {"kind": "row"}, "children": ["d", "c"]},
    ]}
    boxes = {
        "root": [0, 0, 100, 120], "flow": [0, 0, 100, 60], "e": [30, 100, 70, 120],
        "flow~line1": [0, 0, 100, 20], "flow~line2": [0, 40, 100, 60],
        "a": [0, 0, 40, 20], "b": [60, 0, 100, 20], "d": [0, 40, 40, 60], "c": [60, 40, 100, 60],
    }
    drags = [["e", 80, 110, 80], ["e", 20, 110, 20], ["e", 50, 110, 50]]
    assert _places(under, boxes, drags, "[place.with, place.of, kept]") == [
        ["c", "flow", False], ["d", "flow", False], ["flow", "flow", True]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_let_go_where_it_already_is_stays_however_the_place_is_said() -> None:
    model = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "row"}, "children": ["a", "col"]},
        {"id": "col", "layout": {"kind": "column"}, "children": ["b", "c"]},
    ]}
    boxes = {
        "root": [0, 0, 300, 150], "a": [10, 60, 60, 90], "col": [100, 0, 200, 150],
        "b": [110, 10, 190, 40], "c": [110, 110, 190, 140],
    }
    shown = "place.kind === 'line' ? [`${place.side} of ${place.of}`, kept] : [place.index, kept]"
    # Under the part over it in its column -- in the gap between them, or past its own foot,
    # where it is said as a line of its own under that part -- is where it is: it stays.
    # Another part let go there goes under it.
    drags = [["c", 150, 100], ["c", 150, 170], ["a", 150, 170], ["b", 150, 170]]
    assert _places(model, boxes, drags, shown) == [
        [1, True], ["below of b", True], ["below of c", False], ["below of c", False]]
    # Lined up under a part already, and drawn as near it as its line has room for (short of
    # it): let go under that part again, it stays.
    lined = {"root": "root", "nodes": [{"id": "e", "align_with": "d"}], "groups": [
        {"id": "root", "layout": {"kind": "column"}, "children": ["row", "e"]},
        {"id": "row", "layout": {"kind": "row"}, "children": ["a", "b", "c", "d"]},
    ]}
    boxes = {
        "root": [0, 0, 370, 130], "row": [10, 10, 360, 40], "a": [10, 10, 60, 40],
        "b": [110, 10, 160, 40], "c": [210, 10, 260, 40], "d": [310, 10, 360, 40],
        "e": [260, 100, 360, 130],
    }
    drags = [["e", 335, 115, 335], ["e", 235, 115, 235]]
    assert _places(lined, boxes, drags, "[place.with, kept]") == [["d", True], ["c", False]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_let_go_just_under_a_part_of_a_row_takes_a_line_of_its_own_under_that_part() -> None:
    model = {"root": "root", "nodes": [{"id": "g", "align_with": "d"}], "groups": [
        {"id": "root", "layout": {"kind": "column"}, "children": ["one", "two", "g"]},
        {"id": "one", "layout": {"kind": "row"}, "children": ["a", "b", "c"]},
        {"id": "two", "layout": {"kind": "row"}, "children": ["d", "e", "pair"]},
        {"id": "pair", "layout": {"kind": "column"}, "children": ["f"]},
    ]}
    boxes = {
        "root": [0, 0, 260, 190], "one": [0, 0, 260, 30], "two": [0, 60, 260, 90],
        "a": [0, 0, 60, 30], "b": [100, 0, 160, 30], "c": [200, 0, 260, 30],
        "d": [0, 60, 60, 90], "e": [100, 60, 160, 90], "pair": [200, 60, 260, 90],
        "f": [200, 60, 260, 90], "g": [20, 150, 60, 180],
    }
    shown = ("place.kind === 'align' ? [place.with, place.of, place.move, place.parent, "
             "place.index, kept] : [place.parent, place.index, kept]")
    drags = [["e", 30, 108], ["a", 130, 108], ["e", 80, 108], [None, 30, 108], ["pair", 30, 108],
             ["g", 30, 100, 400]]
    assert _places(model, boxes, drags, shown) == [
        # Just under the row, under one of its parts -- one of its own, or another row's: a line
        # of its own there (its place in the column), lined up under that part.
        ["d", "two", True, "root", 2, False], ["e", "two", True, "root", 2, False],
        # Under the gap between two parts, a line of its own as its column places it; and so
        # a shape from the palette, and a group, which are lined up with nothing.
        ["root", 2, False], ["root", 2, False], ["root", 2, False],
        # There already, lined up with it (picked up by its far end, say): it stays.
        ["d", "two", True, "root", 2, True],
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_not_drawn_has_no_place_beside_it_and_stops_no_other_from_going_to_its() -> None:
    # A group left holding nothing, and a shape the drawing lacks: neither has a box.
    model = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "row"}, "children": ["a", "gone", "b", "c", "late"]},
        {"id": "gone", "role": "layout", "layout": {"kind": "row"}, "children": []},
    ]}
    boxes = {"root": [0, 0, 160, 20], "a": [0, 0, 40, 20], "b": [60, 0, 100, 20],
             "c": [120, 0, 160, 20], "gone": None, "late": None}
    shown = ("place.kind === 'line' ? `${place.side} of ${place.of}` "
             ": [place.parent, place.index, place.siblings]")
    drags = [["c", 48, 10], ["c", 112, 10], ["c", 20, 60]]
    assert _places(model, boxes, drags, shown) == [
        # Beside a part of the row: its place among all the row holds; shown between those drawn.
        ["root", 1, ["a", "b"]], ["root", 3, ["a", "b"]], "below of a"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_shape_let_go_on_a_lines_body_goes_into_the_line() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    # A line down from a to b (100 pixels), and one across from b to c, with a bend.
    lines = [
        {"id": "edge.1.a-to-b", "from": "a", "to": "b",
         "points": [{"x": 50, "y": 40}, {"x": 50, "y": 140}]},
        {"id": "edge.2.b-to-c", "from": "b", "to": "c",
         "points": [{"x": 50, "y": 180}, {"x": 50, "y": 220}, {"x": 250, "y": 220}]},
    ]
    model = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "column"}, "children": ["top", "c"]},
            {"id": "top", "layout": {"kind": "column"}, "children": ["a", "b"]},
        ],
    }
    boxes = {"root": [0, 0, 300, 260], "top": [10, 10, 90, 170]}
    # (Each: the part dragged, and the pointer.)
    drags = [
        ["d", 54, 90],  # on the first line's middle, a little to its side
        ["d", 50, 45],  # by its start, where it leaves "a": not its body
        ["d", 50, 136],  # by its end, where it meets "b": not its body
        ["d", 66, 90],  # too far to its side
        ["d", 150, 224],  # on the second line, along its bend
        ["a", 54, 90],  # a line of its own: not into it
        ["d", 120, 300],  # nowhere near a line
    ]
    code = (
        f"import {{ lineAt, groupAt }} from {json.dumps(script.as_uri())};\n"
        f"const lines = {json.dumps(lines)};\n"
        f"const model = {json.dumps(model)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const line = lineAt(lines, { x, y }, id);\n"
        "  const group = groupAt(model, boxes, { x, y }, id);\n"
        "  return line && { id: line.id, at: [line.at.x, line.at.y], group };\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        # Lit where the pointer is nearest it, and let go in the group it is in.
        {"id": "edge.1.a-to-b", "at": [50, 90], "group": "top"},
        None,
        None,
        None,
        {"id": "edge.2.b-to-c", "at": [150, 220], "group": "root"},
        None,
        None,
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_shape_carried_near_a_lines_end_goes_beside_the_part_there() -> None:
    # A line down into "b" (100 pixels): a shape 60 pixels high carried 25 pixels from its
    # end would stand over "b" -- it goes beside it, the slot there, not into the line; on
    # the line's middle it goes in. (A small one, or none told, goes in there as before.)
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    down = [{"x": 50, "y": 40}, {"x": 50, "y": 140}]
    lines = [{"id": "edge.1.a-to-b", "from": "a", "to": "b", "points": down}]
    drags = [[115, {"width": 120, "height": 60}], [90, {"width": 120, "height": 60}],
             [115, {"width": 30, "height": 20}], [115, None]]
    code = (
        f"import {{ lineAt }} from {json.dumps(script.as_uri())};\n"
        f"const lines = {json.dumps(lines)};\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([y, carried]) =>"
        " lineAt(lines, { x: 52, y }, 'd', undefined, carried)?.id ?? null)));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [None, "edge.1.a-to-b", "edge.1.a-to-b", "edge.1.a-to-b"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_lines_end_dragged_meets_the_side_of_the_shape_it_is_let_go_by() -> None:
    # A wide box (0..120 across, 0..40 down) and a diamond beside it: let go near the box's
    # top -- even near its corner, the top runs its whole width -- the end meets the middle
    # of its top; by its right, the middle of its right; over its middle, wherever the
    # figure puts it; just outside it, still the box; well away, nothing.
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    shapes = [
        {"id": "box", "left": 0, "top": 0, "right": 120, "bottom": 40},
        {"id": "rmsd", "left": 200, "top": 0, "right": 260, "bottom": 30},
    ]
    points = [[100, 3], [118, 20], [60, 22], [60, 46], [-5, 20], [160, 20], [230, 28]]
    code = (
        f"import {{ endAt }} from {json.dumps(script.as_uri())};\n"
        f"const shapes = {json.dumps(shapes)};\n"
        f"console.log(JSON.stringify({json.dumps(points)}.map(([x, y]) => {{\n"
        "  const at = endAt(shapes, { x, y });\n"
        "  return at && [at.id, at.side, at.at.x, at.at.y];\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        ["box", "north", 60, 0],
        ["box", "east", 120, 20],
        ["box", "", 60, 20],
        ["box", "south", 60, 40],
        ["box", "west", 0, 20],
        None,
        ["rmsd", "south", 230, 30],
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_lines_end_dragged_to_a_frame_meets_its_outline_or_its_title_not_what_it_holds() -> None:
    # A frame (0..200 across, 0..160 down) round a box, its title at its top left. What is
    # inside a frame is the shapes', or nobody's: an end let go there, on nothing, goes
    # nowhere -- near the frame's outline, on either side of it, it meets that side at its
    # middle; on its title, the frame, wherever the figure puts it; on the box, the box.
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    shapes = [
        {"id": "stage", "left": 0, "top": 0, "right": 200, "bottom": 160, "hollow": True,
         "title": {"left": 8, "top": 8, "right": 60, "bottom": 20}},
        {"id": "box", "left": 60, "top": 60, "right": 140, "bottom": 100},
    ]
    points = [
        [100, 150], [100, 168], [4, 80], [196, 30], [30, 14], [100, 40], [170, 130],
        [100, 80], [100, 104], [100, 190],
    ]
    code = (
        f"import {{ endAt, endOff }} from {json.dumps(script.as_uri())};\n"
        f"const shapes = {json.dumps(shapes)};\n"
        f"console.log(JSON.stringify([{json.dumps(points)}.map(([x, y]) => {{\n"
        "  const at = endAt(shapes, { x, y });\n"
        "  return at && [at.id, at.side, at.at.x, at.at.y];\n"
        "}), [[100, 150], [100, 168], [30, 14], [100, 40]].map(([x, y]) =>"
        " endOff(shapes[0], { x, y }))]));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    met, off = json.loads(result.stdout)
    assert met == [
        ["stage", "south", 100, 160],
        ["stage", "south", 100, 160],
        ["stage", "west", 0, 80],
        ["stage", "east", 200, 80],
        ["stage", "", 100, 80],
        None,
        None,
        ["box", "", 100, 80],
        ["box", "south", 100, 100],
        None,
    ]
    # (How far from where a line may end at it: from its outline, inside it or out.)
    assert off == [10, 8, 0, 40]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_lines_drawn_ends_are_told_apart_by_the_shapes_they_meet() -> None:
    # A joined line's pieces: two stems into one shape's two ports, side by side, and a
    # rail whose end stops short of a shape -- each end given its own nearest point.
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    points = [
        {"x": 40, "y": 0, "n": 1}, {"x": 60, "y": 0, "n": 2},
        {"x": 50, "y": -30, "n": 3}, {"x": 50, "y": -80, "n": 4},
    ]
    ends = [
        {"key": "att.q", "left": 0, "top": 0, "right": 100, "bottom": 20},
        {"key": "att.k", "left": 0, "top": 0, "right": 100, "bottom": 20},
        {"key": "q", "left": 30, "top": -120, "right": 70, "bottom": -90},
    ]
    code = (
        f"import {{ endsOf }} from {json.dumps(script.as_uri())};\n"
        f"const found = endsOf({json.dumps(points)}, {json.dumps(ends)});\n"
        "console.log(JSON.stringify(Object.fromEntries([...found].map(([key, point]) =>"
        " [key, point.n]))));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    found = json.loads(result.stdout)
    assert sorted([found["att.q"], found["att.k"]]) == [1, 2] and found["q"] == 4


def test_a_part_dragged_in_a_flow_takes_its_place_among_its_own_layer() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"

    def dropped(model: dict, boxes: dict, drags: list) -> list:
        code = (
            f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
            f"const model = {json.dumps(model)};\n"
            f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
            ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
            f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
            "  const place = dropPlace(model, boxes, { x, y }, id);\n"
            "  if (place.kind === 'line') return `${place.side} of ${place.of}`;\n"
            "  return stays(model, place, id) ? 'stays' : `${place.parent} ${place.index}`;\n"
            "})));\n"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)

    # A module laid out as a flow right, two of its parts in its first layer (one over the
    # other), a third in its second; beside the module, outside it, another part.
    model = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "column"}, "children": ["ln", "m"]},
            {"id": "m", "role": "module", "layout": {"kind": "flow-right"},
             "children": ["nf", "seq", "mlp", "q"]},
        ],
    }
    boxes = {
        "root": [0, 0, 400, 200], "ln": [0, 20, 40, 40], "m": [50, 0, 400, 200],
        "nf": [60, 50, 90, 80], "seq": [60, 120, 90, 150], "mlp": [150, 50, 190, 80],
        "q": [250, 50, 270, 80],
    }
    drags = [
        ["seq", 75, 30],  # over the part above it, in its own layer: before it
        ["seq", 170, 30],  # over a part of the next layer: before the one of its own
        ["seq", 75, 100],  # between the two: after the one above, where it is
        ["seq", 46, 45],  # just past the module's edge: still in it
        ["seq", 55, 30],  # in the module, level with the part outside it: not beside that
        ["seq", 20, 100],  # well out of the module: out of it
    ]
    assert dropped(model, boxes, drags) == ["m 0", "m 0", "stays", "m 0", "m 0", "root 1"]
    # Let go beside a part of a flow: next to it in the flow's order -- never a row of the two.
    flow = {"root": "root", "groups": [
        {"id": "root", "layout": {"kind": "flow-right"}, "children": ["a", "b", "c"]},
    ]}
    boxes = {"root": [0, 0, 240, 30], "a": [0, 0, 40, 30], "b": [100, 0, 140, 30],
             "c": [200, 0, 240, 30]}
    assert dropped(flow, boxes, [["c", 52, 15], ["a", 188, 15]]) == ["root 1", "root 1"]


# The figure's parts (figure/parts.js) as a page imports them: from the studio's addresses.
STATIC_ADDRESSES = """
import { register } from "node:module";
const STATIC = %s;
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  const at = (path) => ({ url: STATIC + path, shortCircuit: true });
  if (specifier.startsWith("/static/kinds/figure/")) return at("figure/" + specifier.slice(21));
  if (specifier === "/static/studio/studio.js") return at("studio/ui.js");
  if (specifier.startsWith("/static/studio/")) return at("studio/" + specifier.slice(15));
  return next(specifier, context);
}`.replace("STATIC", JSON.stringify(STATIC))));
"""


def _markup_of(labels: list) -> list[str]:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/parts.js"
    code = FAKE_PAGE + STATIC_ADDRESSES % json.dumps(script.parents[1].as_uri() + "/") + (
        f"const {{ markupOf }} = await import({json.dumps(script.as_uri())});\n"
        f"const labels = {json.dumps(labels)};\n"
        "console.log(JSON.stringify(labels.map((label) => markupOf(label))));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_label_kept_as_runs_is_typed_as_the_markup_that_writes_them() -> None:
    import dataclasses

    from flexo.ir.semantic import TextRun
    from flexo.markup import parse_label

    # A deck's labels as its figures write them (talk.yaml's), and labels as typed.
    maths = {"maths": True}
    kept = [
        [
            {"text": "Denoiser ", "weight": 400, "italic": False, "baseline_shift": "normal"},
            {"text": "\U0001d716", "weight": 400, "baseline_shift": "normal", **maths},
            {"text": "\U0001d703", "weight": 400, "baseline_shift": "sub", **maths},
        ],
        [
            {"text": "x", "italic": True, **maths},
            {"text": "t", "italic": True, "baseline_shift": "sub", **maths},
            {"text": "\u22121", "baseline_shift": "sub", **maths},
        ],
    ]
    typed = [
        r"$p_\theta(x_{t-1} | x_t)$", r"$q(x_t | x_{t-1})$", "Structure $x_0$",
        r"$\alpha + \beta$", r"$\frac{a}{b}$", r"$\mathbf{h}$", r"$\vec{h}$", "$e^{-x}$",
        r"$\sum_i x_i$", r"Loss $\mathcal{L}$", "MLP `relu`", "[red]{accent} words",
        "price \\$5", r"$\hat{y}$", r"$W_{q}^{T}$", r"$\sqrt{d_k}$", r"$\mathrm{softmax}(x)$",
        r"$10^{-3}$", r"$RT \ln K$", r"$\arg\max_i f$", r"$f(x, y)$", r"$\text{out of} x$",
        r"$\mathrm{H_2O}$", r"$\ell_2$", r"$\vec{\alpha}$", r"$\texttt{relu}(x)$", r"$a\,b$",
        r"$\nabla_\theta L$", r"[$x_t$]{accent} next", "Two\nlines $x$", r"$\sigma^2_B$",
        r"$\Delta G^\circ$", "$x$2",
    ]
    labels = kept + [[dataclasses.asdict(run) for run in parse_label(text)] for text in typed]
    written = _markup_of(labels)
    # Each reads back as the runs it was, look and all: a letter typed keeps the rest so.
    for label, markup in zip(labels, written, strict=True):
        assert parse_label(markup) == tuple(TextRun(**run) for run in label), markup
    # As a person would type them: maths by its commands, its spaces as TeX sets them.
    assert written[:3] == [r"Denoiser $\epsilon_\theta$", "$x_{t-1}$", r"$p_\theta(x_{t-1} | x_t)$"]
    assert written[len(kept) + typed.index(r"$\alpha + \beta$")] == r"$\alpha + \beta$"
    # Words written as words are themselves.
    assert _markup_of(["Plain *words*", None]) == ["Plain *words*", ""]


# -- shapes aligned in a row, grouped and ungrouped: the figure's parts on a page --------

# The figure's parts with a stand-in for the page that hosts them: a figure (``model``), where
# each of its shapes is drawn (``boxes``: left, top, right, bottom), every edit kept
# (``sent``, with the name the history gives it) instead of made, and a menu's items kept
# (``opened``) instead of shown.
FIGURE_PAGE = """
Node.prototype.getContext = () => null;
globalThis.opened = [];
const SHELL = "data:text/javascript," + encodeURIComponent(
  "export * from " + JSON.stringify(STATIC + "studio/ui.js") + ";"
  + "export const menu = (anchor, items) => {"
  + " globalThis.opened.push(items.map((item) => item.label)); };");
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier === "/static/studio/studio.js") return { url: SHELL, shortCircuit: true };
  return next(specifier, context);
}`.replace("SHELL", JSON.stringify(SHELL))));
const { figureParts } = await import(STATIC + "figure/parts.js");
const sent = [];
function figurePage(model, boxes) {
  const drawn = (id) => {
    const [left, top, right, bottom] = boxes[id] || [];
    if (!boxes[id]) return null;
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  };
  const figure = figureParts({
    catalog: { parts: {}, groups: [{ kind: "row", title: "Row", layout: "row" }] },
    overlay: new Node("div"), idOf: (id) => id, changed() {}, groupAnchor: () => ({ x: 0, y: 0 }),
    element: (id) => (drawn(id) ? { getBoundingClientRect: () => drawn(id) } : null), box: drawn,
    run: async (action, { label }) => {
      sent.push([action, label]);
      return { select: action.ids || [] };
    },
  });
  figure.setModel({ figure: { id: "f" }, root: "root", edges: [], nets: [], ...model });
  return figure;
}
// A key pressed with nothing typed in: whether the figure took it, and stopped the
// browser's own.
function press(figure, keys) {
  let stopped = false;
  const preventDefault = () => { stopped = true; };
  const event = { key: "g", code: "KeyG", metaKey: true, target: document.body, ...keys };
  return [figure.key({ ...event, preventDefault }), stopped];
}
"""


def _figure_page(code: str) -> dict:
    static = Path(__file__).parents[2] / "src/flexo/studio/static"
    program = FAKE_PAGE + STATIC_ADDRESSES % json.dumps(static.as_uri() + "/") + FIGURE_PAGE + code
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def _shapes(*names: str) -> str:
    return json.dumps([{"id": name, "kind": "block", "label": name.title()} for name in names])


# A flow chart whose boxes have ended up in two columns side by side, in the figure's row.
FLOW_PAGE = (
    "const figure = figurePage({ nodes: "
    + _shapes("mech", "smiles", "geo", "pose", "crystal", "b", "a")
    + """,
  edges: [{ id: "line", from: "geo", to: "pose" }],
  groups: [
    { id: "root", layout: { kind: "row" }, children: ["mech", "smiles", "col1", "col2", "a"] },
    { id: "col1", role: "layout", layout: { kind: "column" }, children: ["geo", "pose"] },
    { id: "col2", role: "layout", layout: { kind: "column" }, children: ["crystal", "b"] }] },
  { mech: [0, 0, 40, 20], smiles: [60, 0, 100, 20], geo: [120, 0, 160, 20],
    pose: [120, 40, 160, 60], crystal: [180, 0, 220, 20], b: [180, 40, 220, 60],
    a: [240, 0, 280, 20] });
"""
)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_shapes_chosen_are_ordered_as_they_are_seen_along_a_row_or_down_a_column() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    boxes = {"geo": [120, 0, 160, 20], "pose": [118, 40, 162, 60], "crystal": [180, 2, 220, 26],
             "a": [240, 0, 280, 20]}
    code = (
        f"import {{ seenOrder }} from {json.dumps(script.as_uri())};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        "const chosen = ['a', 'unseen', 'pose', 'crystal', 'geo'];\n"
        "const seen = ['row', 'column'].map((kind) => seenOrder(chosen, boxes, kind));\n"
        "console.log(JSON.stringify(seen));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    across, down = json.loads(result.stdout)
    # Left to right, a shape under another after it; one not drawn after those that are.
    assert across == ["geo", "pose", "crystal", "a", "unseen"]
    # Top to bottom, those side by side (one a little lower, or taller) left to right.
    assert down == ["geo", "crystal", "a", "pose", "unseen"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_align_in_a_row_sends_the_shapes_chosen_anywhere_in_the_order_they_are_seen() -> None:
    out = _figure_page(FLOW_PAGE + """
const out = {};
// The top box of each column and one of the figure's own row, chosen in any order.
figure.select(["a", "geo", "crystal"]);
out.offered = figure.canAlign();
out.menu = figure.menuOf("geo", { x: 0, y: 0 }).map((item) => [item.label, item.keys || ""]);
figure.alignChosen("row");
figure.select(["b", "pose"]);
figure.alignChosen("row");
// A group goes as a shape does.
figure.select(["col1", "mech"]);
figure.alignChosen("column");
// In one row (one column) already: nothing is sent.
figure.select(["a", "mech"]);
out.inRow = figure.alignChosen("row");
figure.select(["pose", "geo"]);
out.inColumn = figure.alignChosen("column");
// Not lines, nor one shape alone.
figure.select(["geo", "line"]);
out.withLine = [figure.canAlign(), figure.alignChosen("row")];
figure.select(["geo"]);
out.alone = figure.canAlign();
await figure.idle();
console.log(JSON.stringify({ ...out, sent }));
""")
    assert out["sent"] == [
        [{"do": "line_up", "ids": ["geo", "crystal", "a"], "kind": "row"},
         "Align 3 Shapes in a Row"],
        [{"do": "line_up", "ids": ["pose", "b"], "kind": "row"}, "Align 2 Shapes in a Row"],
        [{"do": "line_up", "ids": ["mech", "col1"], "kind": "column"},
         "Align 2 Shapes in a Column"],
    ]
    assert out["offered"] is True and out["alone"] is False
    assert (out["inRow"], out["inColumn"], out["withLine"]) == (False, False, [False, False])
    # Several chosen, right-clicked: grouped (⌘G), aligned, or shown another way (Show ▸).
    assert out["menu"] == [["Group…", "⌘G"], ["Align in a Row", ""], ["Align in a Column", ""],
                           ["Show", "▸"], ["Duplicate", "⌘D"], ["Delete", "⌫"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_shapes_aligned_in_a_figure_turned_or_folded_to_fit_go_the_way_they_are_seen() -> None:
    # A column drawn as a row, to fit a slide: its shapes are in a row as they are seen, and
    # put in a column the figure is first written the way it is drawn -- one step.
    turned = _figure_page(
        "const figure = figurePage({ nodes: " + _shapes("p", "q", "r") + """,
  groups: [{ id: "root", layout: { kind: "column" }, children: ["p", "q", "r"] }] },
  { p: [0, 0, 40, 20], q: [60, 0, 100, 20], r: [120, 0, 160, 20] });
figure.select(["q", "p"]);
const inRow = figure.alignChosen("row");
figure.alignChosen("column");
await figure.idle();
console.log(JSON.stringify({ inRow, sent }));
""")
    assert turned["inRow"] is False
    assert turned["sent"] == [
        [{"do": "update", "targets": [{"type": "group", "id": "root"}],
          "values": {"layout.kind": "row"}}, "Align 2 Shapes in a Column"],
        [{"do": "line_up", "ids": ["p", "q"], "kind": "column"}, "Align 2 Shapes in a Column"],
    ]
    # A row folded onto two lines: one shape of each line put in a row, the lines are first
    # written as they are seen, so that the rest keep theirs.
    folded = _figure_page(
        "const figure = figurePage({ nodes: " + _shapes("p", "q", "r", "s") + """,
  groups: [{ id: "root", layout: { kind: "row" }, children: ["p", "q", "r", "s"] }] },
  { p: [0, 0, 40, 20], q: [60, 0, 100, 20], r: [0, 40, 40, 60], s: [60, 40, 100, 60] });
figure.select(["p", "q"]);
const inRow = figure.alignChosen("row");
figure.select(["s", "q"]);
figure.alignChosen("row");
await figure.idle();
console.log(JSON.stringify({ inRow, sent }));
""")
    assert folded["inRow"] is False
    assert folded["sent"] == [
        [{"do": "arrange", "id": "root", "kind": "row", "lines": [["p", "q"], ["r", "s"]],
          "align": "start"}, "Align 2 Shapes in a Row"],
        [{"do": "line_up", "ids": ["q", "s"], "kind": "row"}, "Align 2 Shapes in a Row"],
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_command_g_groups_the_shapes_chosen_and_shift_command_g_ungroups() -> None:
    out = _figure_page(FLOW_PAGE + """
const out = {};
// Shapes chosen: ⌘G opens Group…, as ⌥⌘G (Keynote's, which types another letter) does.
figure.select(["geo", "crystal"]);
out.group = [press(figure, {}), press(figure, { altKey: true, key: "©" })];
out.cannotUngroup = press(figure, { shiftKey: true, key: "G" });
// A group chosen: ⇧⌘G takes it apart, as ⇧⌥⌘G does.
figure.select(["col1"]);
out.ungroup = [press(figure, { shiftKey: true, key: "G" }),
  press(figure, { shiftKey: true, altKey: true, key: "˝" })];
// A line cannot be grouped: the key is left to the browser.
figure.select(["line"]);
out.line = press(figure, {});
await figure.idle();
console.log(JSON.stringify({ ...out, sent, opened: globalThis.opened }));
""")
    assert out["group"] == [[True, True], [True, True]] and out["opened"] == [["Row"], ["Row"]]
    assert out["ungroup"] == [[True, True], [True, True]]
    assert [action for action, _ in out["sent"]] == [{"do": "ungroup", "id": "col1"}] * 2
    assert out["cannotUngroup"] == [False, False] and out["line"] == [False, False]


# -- a shape dragged on the drawing: the edits the page sends --------------------------

# The stand-in page with a drawing to drag on: each shape an element that says where it is
# drawn (``boxes``) and how far it has been carried, the window's listeners kept to be
# fired, a frame run when asked. ``answer(action)`` is what the studio answers an edit with
# (the lines an "arrange" made, the copy a "duplicate" made), beside ``sent``.
DRAG_PAGE = r"""
class Names {
  constructor() { this.names = new Set(); }
  add(...names) { for (const name of names) this.names.add(name); }
  remove(...names) { for (const name of names) this.names.delete(name); }
  toggle(name, on = !this.names.has(name)) { if (on) this.add(name); else this.remove(name); }
  contains(name) { return this.names.has(name); }
}
Object.defineProperty(Node.prototype, "classList", {
  get() { return (this.named ??= new Names()); },
});
const PAGE = { left: 0, top: 0, right: 1000, bottom: 800, width: 1000, height: 800 };
Object.assign(Node.prototype, {
  removeAttribute(key) { delete this.attributes[key]; },
  contains(other) { return other === this; },
  matches: () => false, closest: () => null, querySelectorAll: () => [],
  animate() {}, before() {}, cloneNode() { return new Node(this.tag); },
  getBoundingClientRect: () => PAGE,
});
const created = document.createElement;
document.createElement = (tag) => Object.assign(created(tag), { style: { setProperty() {} } });
document.querySelectorAll = () => [];
const listeners = new Map();
globalThis.window = {
  addEventListener(type, run) { listeners.set(type, [...(listeners.get(type) || []), run]); },
  removeEventListener(type, run) {
    listeners.set(type, (listeners.get(type) || []).filter((each) => each !== run));
  },
  getSelection: () => null,
};
const fire = (type, event) => { for (const run of listeners.get(type) || []) run(event); };
let frames = [];
globalThis.requestAnimationFrame = (run) => frames.push(run);
globalThis.cancelAnimationFrame = () => {};
const frame = () => { const due = frames; frames = []; for (const run of due) run(); };
// (A part let go waits a while for the drawing it makes: not what this waits for.)
const later = setTimeout;
globalThis.setTimeout = (run, ms, ...rest) => {
  const timer = later(run, ms, ...rest);
  if (ms >= 1000) timer.unref();
  return timer;
};

function dragPage(model, boxes, answer = () => ({}), parts = {}) {
  const elements = new Map(), gliding = new Map();
  const carried = (node) => {
    const moved = /translate\(([-\d.e]+) ([-\d.e]+)\)/.exec(node.getAttribute("transform") || "");
    return moved ? [Number(moved[1]), Number(moved[2])] : [0, 0];
  };
  const element = (id) => {
    if (!boxes[id]) return null;
    if (!elements.has(id)) {
      const node = Object.assign(new Node("g"), { id, matches: () => true });
      // (Where it is drawn, as far as it has been carried -- and, landing there from where
      // it was, as far short of it as it still is.)
      node.getBoundingClientRect = () => {
        const [left, top, right, bottom] = boxes[id], [cx, cy] = carried(node);
        const [dx, dy] = [cx + (gliding.get(id)?.[0] || 0), cy + (gliding.get(id)?.[1] || 0)];
        return { left: left + dx, top: top + dy, right: right + dx, bottom: bottom + dy,
          width: right - left, height: bottom - top };
      };
      node.getAnimations = () => (gliding.has(id) ? [{ finish: () => gliding.delete(id) }] : []);
      elements.set(id, node);
    }
    return elements.get(id);
  };
  const page = new Node("div");
  const figure = figureParts({
    catalog: { parts, groups: [] }, overlay: page, idOf: (id) => id, changed() {},
    element, box: (id) => element(id)?.getBoundingClientRect() || null,
    // (`breaks`: what goes wrong as an edit is asked for, to see what becomes of the shape.)
    edited: () => { if (figure.breaks) throw new Error(figure.breaks); },
    // (How many times it was told a shape carried had been let go.)
    dragged: () => { figure.told = (figure.told || 0) + 1; },
    run: async (action, { label }) => {
      sent.push([action, label]);
      return { select: [], ...answer(action) };
    },
  });
  figure.setModel({ figure: { id: "f" }, root: "root", edges: [], nets: [], ...model });
  // A shape pressed at its middle, carried to `to` and let go there -- or at `up` (`keys`:
  // ⌥ held, say). The drawing is as it was, whatever was dragged before (`redrawn`: its
  // elements new) -- unless the drawing an earlier drag's edits make has not yet come.
  // Answers the edits sent, whether a place was shown for it as it was let go (a slot, a
  // line between two parts), whether it is still carried (its drawing yet to come), whether
  // the drag is over, and what failed on the way, if anything (as in a browser, where a
  // frame or a listener that fails stops nothing else).
  figure.drag = async (id, to, { keys = {}, up = to, redrawn = true } = {}) => {
    if (redrawn) elements.clear();
    const box = element(id).getBoundingClientRect(), from = sent.length;
    const at = (x, y) => ({ button: 0, target: element(id), clientX: x, clientY: y,
      preventDefault() {}, ...keys });
    const [x, y] = [(box.left + box.right) / 2, (box.top + box.bottom) / 2];
    let failed = null;
    const tried = (run) => { try { run(); } catch (error) { failed = error.message; } };
    figure.pointerdown(at(x, y));
    for (const part of [0.5, 1]) {
      fire("pointermove", at(x + (to[0] - x) * part, y + (to[1] - y) * part));
      tried(frame);
    }
    const marks = page.children.filter((node) => !node.removed);
    const shown = marks.some((node) => node.classList.contains("on"));
    tried(() => fire("pointerup", at(...up)));
    await figure.idle();
    return { sent: sent.slice(from), shown, over: !figure.dragging,
      carried: Boolean(element(id).getAttribute("transform")), ...(failed ? { failed } : {}) };
  };
  return Object.assign(figure, { page, gliding });
}
"""


def _drag_page(code: str) -> dict:
    return _figure_page(DRAG_PAGE + code)


# Two boxes in a column with a frame round them, "Stage", a box to its left and one to its
# right -- each element hearing what it listens for, so a + can be pressed and clicked.
FRAMED_PAGE = (
    "Node.prototype.addEventListener = function (type, run) { (this.heard ??= {})[type] = run; };\n"
    "const TITLE = { left: 196, top: 14, right: 240, bottom: 26, width: 44, height: 12 };\n"
    "Node.prototype.querySelector = function (selector) {\n"
    "  return this.id === 'stage' && selector.includes('.label')"
    " ? { getBoundingClientRect: () => TITLE } : null;\n"
    "};\n"
    "globalThis.getComputedStyle = () => ({});\n"
    "const boxes = { a: [20, 100, 80, 130], b: [200, 40, 260, 70], c: [200, 100, 260, 130],\n"
    "  d: [400, 60, 460, 90], stage: [190, 10, 270, 140], root: [0, 0, 600, 300] };\n"
    "const figure = dragPage({ nodes: [...SHAPES,\n"
    "    { id: 'stage', kind: 'frame', label: 'Stage', properties: { around: 'b, c' } }],\n"
    "  groups: [{ id: 'root', layout: { kind: 'row' }, children: ['a', 'col', 'd', 'stage'] },\n"
    "    { id: 'col', role: 'layout', layout: { kind: 'column' }, children: ['b', 'c'] }] },\n"
    "  boxes, () => ({}), PARTS);\n"
    "const plus = () => figure.markViews()"
    ".filter((node) => (node.attributes.class || '').includes('fig-next'));\n"
    "const at = (x, y) => ({ button: 0, clientX: x, clientY: y,"
    " preventDefault() {}, stopPropagation() {} });\n"
    "// The + beside `from` pressed, dragged to a point and let go there: the edits sent.\n"
    "const drawn = async (from, to) => {\n"
    "  figure.select([from]);\n"
    "  const [button] = plus(), before = sent.length;\n"
    "  button.heard.pointerdown(at(0, 0));\n"
    "  fire('pointermove', at(...to)); frame();\n"
    "  fire('pointerup', at(...to));\n"
    "  await figure.idle();\n"
    "  return sent.slice(before).map(([action]) => action);\n"
    "};\n"
).replace("SHAPES", _shapes("a", "b", "c", "d"))


def _framed_page(code: str) -> dict:
    from flexo.studio.figure_parts import catalogue

    parts = {kind: catalogue()["parts"][kind] for kind in ("block", "frame")}
    return _drag_page(f"const PARTS = {json.dumps(parts)};\n" + FRAMED_PAGE + code)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_line_is_drawn_from_a_plus_to_a_frame_and_from_a_frames_own_plus() -> None:
    """A frame had no + (it took no line), and a line let go anywhere over one was sent to
    it and refused."""

    out = _framed_page("""
const out = {};
figure.select(["stage"]);
out.plus = plus().map((node) => node.attributes.title);
// Its + dragged to a shape outside it: a line from the frame; to one it goes round: none.
out.toShape = await drawn("stage", [430, 75]);
out.toHeld = await drawn("stage", [230, 55]);
// A shape's + let go at the frame's outline, just inside it or just outside; on its title;
// inside it on nothing; on a shape inside it; far from everything.
out.outline = [await drawn("a", [192, 85]), await drawn("a", [185, 85])];
out.outline.push(await drawn("d", [230, 138]));
out.title = await drawn("a", [220, 20]);
out.inside = await drawn("a", [230, 85]);
out.held = await drawn("a", [230, 115]);
out.far = await drawn("a", [300, 200]);
// From a shape the frame goes round, the frame is no place to let go.
out.fromHeld = await drawn("b", [230, 12]);
// Clicked, the frame's + asks for the shape its line goes to: clicked on next. (Once the
// click that ends a drag has had its turn to be swallowed.)
await new Promise((done) => setTimeout(done, 5));
figure.select(["stage"]);
plus()[0].heard.click(at(0, 0));
out.asking = figure.connecting;
const before = sent.length;
figure.click({ target: { id: "d", matches: () => true, closest: () => null } });
await figure.idle();
out.clicked = sent.slice(before).map(([action]) => action);
out.asked = figure.connecting;
console.log(JSON.stringify(out));
""")
    assert len(out["plus"]) == 1 and "Draw a line from “Stage”" in out["plus"][0]
    assert out["toShape"] == [{"do": "connect", "source": "stage", "target": "d"}]
    assert out["toHeld"] == []
    to_frame = {"do": "connect", "target": "stage"}
    assert out["outline"] == [
        [{**to_frame, "source": "a"}], [{**to_frame, "source": "a"}], [{**to_frame, "source": "d"}]
    ]
    assert out["title"] == [{**to_frame, "source": "a"}]
    assert out["inside"] == [] and out["far"] == [] and out["fromHeld"] == []
    assert out["held"] == [{"do": "connect", "source": "a", "target": "c"}]
    assert out["asking"] == {"source": "stage"} and out["asked"] is None
    assert out["clicked"] == [{"do": "connect", "source": "stage", "target": "d"}]


# A flow of seven written with no groups (a column), seen on a slide as a row: six on one
# line and the seventh, "new2", alone on a second, under "geo".
SEVEN = ["mech", "smiles", "geo", "new1", "new2", "crystal", "a"]
SEVEN_PAGE = (
    "const names = " + json.dumps(SEVEN) + ";\n"
    "const boxes = { new2: [240, 90, 330, 120] };\n"
    "names.filter((name) => name !== 'new2').forEach((name, at) => "
    "{ boxes[name] = [20 + at * 110, 20, 110 + at * 110, 50]; });\n"
    "const figure = dragPage({ nodes: " + _shapes(*SEVEN) + ",\n"
    "  edges: names.slice(1).map((name, at) => ({ id: `line${at}`, from: names[at], to: name })),\n"
    "  groups: [{ id: 'root', implied: true, layout: { kind: 'column' }, children: names }] },\n"
    "  boxes, (action) => (action.do === 'arrange' ? { select: ['row', 'row-2'] }\n"
    "    : action.do === 'duplicate' ? { select: ['new2-2'] } : {}));\n"
)
SEVEN_SEEN = {"do": "arrange", "id": "root", "kind": "row", "align": "center",
              "lines": [[name for name in SEVEN if name != "new2"], ["new2"]]}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_alone_on_a_folded_line_let_go_under_a_box_goes_under_that_box_in_one_step() -> None:
    out = _drag_page(SEVEN_PAGE + """
const out = {};
// Just under "crystal"; under the middle of the row; and where it is, under "geo".
out.under = await figure.drag("new2", [505, 60]);
out.centred = await figure.drag("new2", [340, 105]);
out.stays = await figure.drag("new2", [290, 110]);
console.log(JSON.stringify(out));
""")
    # The figure written as it is seen, then the box lined up: one step, named for the box it
    # goes under -- not put under the row as a whole, in the row's middle.
    under = "Place “New2” Under “Crystal”"
    assert out["under"]["sent"] == [
        [SEVEN_SEEN, under], [{"do": "align", "id": "new2", "with": "crystal"}, under]]
    # (The line it goes with, by the name it was written under.)
    assert out["centred"]["sent"] == [
        [SEVEN_SEEN, "Centre “New2”"],
        [{"do": "align", "id": "new2", "with": "row"}, "Centre “New2”"]]
    assert out["under"]["shown"] and out["under"]["carried"] and out["under"]["over"]
    # Let go where it is, no place is shown and nothing sent -- nor the figure written as
    # seen -- and it is home.
    assert out["stays"] == {"sent": [], "shown": False, "carried": False, "over": True}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_under_a_row_seen_folded_is_lined_up_once_the_row_is_written_as_seen() -> None:
    out = _drag_page(
        "const figure = dragPage({ nodes: " + _shapes("a", "b", "c", "d", "f", "g", "e") + """,
  groups: [{ id: "root", layout: { kind: "column" }, children: ["flow", "e"] },
    { id: "flow", layout: { kind: "row" }, children: ["a", "b", "c", "d", "f", "g"] }] },
  { a: [0, 0, 40, 20], b: [60, 0, 100, 20], c: [120, 0, 160, 20], d: [120, 40, 160, 60],
    f: [60, 40, 100, 60], g: [0, 40, 40, 60], e: [60, 100, 100, 120] },
  (action) => (action.do === "arrange" ? { select: ["row", "row-2"] } : {}));
console.log(JSON.stringify(await figure.drag("e", [140, 110])));
""")
    said = "Place “E” Under “D”"
    assert out["sent"] == [
        [{"do": "arrange", "id": "flow", "kind": "row", "align": "start",
          "lines": [["a", "b", "c"], ["g", "f", "d"]]}, said],
        [{"do": "align", "id": "e", "with": "d"}, said]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_let_go_where_it_is_or_where_no_place_can_be_told_is_home_at_once() -> None:
    out = _drag_page(
        "const boxes = { mech: [105, 28, 149, 56], smiles: [169, 28, 213, 56],"
        " geo: [233, 28, 277, 56], pose: [233, 84, 277, 112], b: [233, 126, 277, 154] };\n"
        "const figure = dragPage({ nodes: " + _shapes("mech", "smiles", "geo", "pose", "b", "late")
        + """,
  groups: [{ id: "root", layout: { kind: "column" }, children: ["row", "pose", "b"] },
    { id: "row", role: "layout", layout: { kind: "row" },
      children: ["mech", "gone", "smiles", "geo", "late"] },
    { id: "gone", role: "layout", layout: { kind: "row" }, children: [] }] }, boxes);
const out = {};
// Under the box over it in its column, past its own foot: where it is.
out.under = await figure.drag("b", [255, 185]);
// Beside a box of a row that holds a group left empty and a shape not drawn yet: its place.
out.beside = await figure.drag("b", [157, 42]);
console.log(JSON.stringify(out));
""")
    assert out["under"] == {"sent": [], "shown": False, "carried": False, "over": True}
    assert [action for action, _ in out["beside"]["sent"]] == [
        {"do": "move", "id": "b", "parent": "row", "index": 1}]
    assert out["beside"]["shown"] and out["beside"]["over"]
    # Should where it goes not be worked out as it is let go, the drag ends all the same:
    # the box is home, nothing sent, and the pointer carries it no further.
    failed = _drag_page(
        "const figure = dragPage({ nodes: " + _shapes("a", "b") + """,
  groups: [{ id: "root", layout: { kind: "row" }, children: ["a", "b"] }] },
  { a: [0, 0, 40, 20], b: [60, 0, 100, 20] });
// (Let go a little further on than the pointer was last seen: its place is told afresh.)
figure.page.getBoundingClientRect = () => { throw new Error("no place"); };
console.log(JSON.stringify(await figure.drag("b", [20, 60], { up: [130, 10] })));
""")
    assert failed == {
        "sent": [], "shown": False, "carried": False, "over": True, "failed": "no place"}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_copy_let_go_goes_where_the_box_itself_would_on_a_figure_turned_or_folded() -> None:
    # A column drawn as a row, to fit a slide: a copy let go under the row is put there once
    # the figure is written the way it is drawn, as the box itself is -- one step.
    turned = _drag_page(
        "const figure = dragPage({ nodes: " + _shapes("p", "q", "r") + """,
  groups: [{ id: "root", layout: { kind: "column" }, children: ["p", "q", "r"] }] },
  { p: [0, 0, 40, 20], q: [60, 0, 100, 20], r: [120, 0, 160, 20] },
  (action) => (action.do === "duplicate" ? { select: ["r-2"] } : {}));
console.log(JSON.stringify(await figure.drag("r", [50, 70], { keys: { altKey: true } })));
""")
    said = "Duplicate “R”"
    assert turned["sent"] == [
        [{"do": "duplicate", "ids": ["r"]}, said],
        [{"do": "update", "targets": [{"type": "group", "id": "root"}],
          "values": {"layout.kind": "row"}}, said],
        [{"do": "move", "id": "r-2", "line": "below", "of": "root"}, said]]
    assert not turned["carried"]  # (the box itself never left)
    # A copy of the box alone on a folded line, let go under a box of the line over it: on a
    # line of its own after the box's, then lined up there.
    folded = _drag_page(SEVEN_PAGE + """
console.log(JSON.stringify(await figure.drag("new2", [505, 60], { keys: { altKey: true } })));
""")
    said = "Duplicate “New2”"
    assert folded["sent"] == [
        [SEVEN_SEEN, said], [{"do": "duplicate", "ids": ["new2"]}, said],
        [{"do": "move", "id": "new2-2", "parent": "root", "index": 2}, said],
        [{"do": "align", "id": "new2-2", "with": "crystal"}, said]]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_dragged_while_the_figure_lands_is_read_where_the_figure_is_drawn() -> None:
    # Seven folded onto two lines, the second run back -- just drawn so: "crystal" and "a"
    # still gliding down from the one line they were on, "new2" alone under it for a moment.
    out = _drag_page(
        "const names = " + json.dumps(SEVEN) + ";\n"
        "const boxes = { a: [130, 90, 220, 120], crystal: [240, 90, 330, 120],"
        " new2: [350, 90, 440, 120] };\n"
        "names.slice(0, 4).forEach((name, at) => "
        "{ boxes[name] = [20 + at * 110, 20, 110 + at * 110, 50]; });\n"
        "const figure = dragPage({ nodes: " + _shapes(*SEVEN) + """,
  groups: [{ id: "root", implied: true, layout: { kind: "column" }, children: names }] },
  boxes, (action) => (action.do === "arrange" ? { select: ["row", "row-2"] } : {}));
const out = {};
figure.gliding.set("crystal", [220, -70]).set("a", [440, -70]);
// Let go just right of "new1", at the end of the first line.
out.landing = await figure.drag("new2", [452, 35]);
// Let go there, its drawing still on its way, it is not picked up again from where it was
// let go: the press is no drag.
out.again = await figure.drag("new2", [200, 105], { redrawn: false });
console.log(JSON.stringify(out));
""")
    # Written as it is drawn, four and three -- not as it looked on the way, six and one.
    assert [action for action, _ in out["landing"]["sent"]] == [
        {"do": "arrange", "id": "root", "kind": "row", "align": "end",
         "lines": [["mech", "smiles", "geo", "new1"], ["a", "crystal", "new2"]]},
        {"do": "move", "id": "new2", "parent": "row", "index": 4}]
    assert out["again"] == {"sent": [], "shown": False, "carried": True, "over": True}


# A chain of seven on a slide, written with no groups and drawn folded four and three as a
# snake: the second line under the first, their right ends level, and running back. Each
# box's width in units of its height; a box 28 pixels tall.
SNAKE_WIDTHS = {"mech": 3.43, "smiles": 2.35, "geo": 1.89, "pose": 3.09, "b": 1.57,
                "crystal": 1.67, "a": 1.59}


def _snake(first: list[str], second: list[str], height: float = 28.0) -> dict[str, list[float]]:
    """Where each box of a chain folded onto two lines is drawn, in pixels: ``first`` left
    to right, ``second`` (as the chain runs) back from under the first line's end."""

    gap, boxes, x = 0.72, {}, 4.325
    for name in first:
        boxes[name] = [x, -0.5, x + SNAKE_WIDTHS[name], 0.5]
        x += SNAKE_WIDTHS[name] + gap
    x -= gap
    for name in second:
        boxes[name] = [x - SNAKE_WIDTHS[name], 1.44, x, 2.44]
        x -= SNAKE_WIDTHS[name] + gap
    return {
        name: [round(left * height, 1), round(top * height + 60, 1),
               round(right * height, 1), round(bottom * height + 60, 1)]
        for name, (left, top, right, bottom) in boxes.items()
    }


def _snake_page(first: list[str], second: list[str], groups: list | None = None) -> str:
    """The page with that chain on it: as the file has it (no groups), or as ``groups``."""

    order = [*first, *second]
    lines = [{"id": f"line{at}", "from": one, "to": two}
             for at, (one, two) in enumerate(itertools.pairwise(order))]
    groups = groups or [
        {"id": "root", "implied": True, "layout": {"kind": "column"}, "children": order}]
    return (
        "const boxes = " + json.dumps(_snake(first, second)) + ";\n"
        "const figure = dragPage({ nodes: " + _shapes(*order) + ",\n"
        "  edges: " + json.dumps(lines) + ",\n  groups: " + json.dumps(groups) + " }, boxes,\n"
        "  (action) => (action.do === 'arrange' ? { select: ['row', 'row-2'] }\n"
        "    : action.do === 'duplicate' ? { select: ['b-2'] } : {}));\n"
        # (Just past a side of a box, level with its middle: 18 pixels right of it, or under it.)
        "const right = (id) => [boxes[id][2] + 18, (boxes[id][1] + boxes[id][3]) / 2];\n"
        "const under = (id) => [(boxes[id][0] + boxes[id][2]) / 2, boxes[id][3] + 18];\n"
    )


def _seen(first: list[str], second: list[str]) -> dict:
    """That fold written as it is seen: its second line in the order it is seen, left to right."""

    return {"do": "arrange", "id": "root", "kind": "row", "align": "end",
            "lines": [first, second[::-1]]}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_let_go_just_right_of_the_last_box_of_a_folded_line_goes_after_that_box() -> None:
    first, second = ["mech", "smiles", "geo", "pose"], ["b", "crystal", "a"]
    out = _drag_page(_snake_page(first, second) + """
console.log(JSON.stringify(await figure.drag("b", right("pose"))));
""")
    # Up from under "pose" to just past its right side: after it, at the end of its line --
    # its place among that line's own four, whichever way the line it came from runs.
    assert [action for action, _ in out["sent"]] == [
        _seen(first, second), {"do": "move", "id": "b", "parent": "row", "index": 4}]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_let_go_just_under_a_box_of_the_last_line_takes_a_line_of_its_own_under_it() -> None:
    said = "Place “B” Under “Crystal”"
    placed = [[{"do": "move", "id": "b", "parent": "root", "index": 2}, said],
              [{"do": "align", "id": "b", "with": "crystal"}, said]]
    # From the end of the last line, the figure not yet written as it is seen: written so,
    # then the box put on a line of its own under the last and lined up under "crystal" --
    # one step, and a slot shown for it there.
    first, second = ["mech", "smiles", "geo", "pose"], ["b", "crystal", "a"]
    out = _drag_page(_snake_page(first, second) + """
console.log(JSON.stringify(await figure.drag("b", under("crystal"))));
""")
    assert out == {"sent": [[_seen(first, second), said], *placed], "shown": True, "over": True,
                   "carried": True}
    # From the first line (spliced in before "pose"), the same: never the end of that line.
    first, second = ["mech", "smiles", "geo", "b"], ["pose", "crystal", "a"]
    out = _drag_page(_snake_page(first, second) + """
console.log(JSON.stringify(await figure.drag("b", under("crystal"))));
""")
    assert out["sent"] == [[_seen(first, second), said], *placed]
    # And once the figure is written as its lines, with nothing to write first -- a copy
    # too, put on that line then lined up.
    first, second = ["mech", "smiles", "geo", "pose"], ["b", "crystal", "a"]
    written = [
        {"id": "root", "layout": {"kind": "column", "align": "end"}, "children": ["row", "row-2"]},
        {"id": "row", "role": "layout", "layout": {"kind": "row"}, "children": first},
        {"id": "row-2", "role": "layout", "layout": {"kind": "row"}, "children": second[::-1]},
    ]
    out = _drag_page(_snake_page(first, second, written) + """
const out = { moved: await figure.drag("b", under("crystal")) };
out.copied = await figure.drag("b", under("crystal"), { keys: { altKey: true } });
console.log(JSON.stringify(out));
""")
    assert out["moved"]["sent"] == placed
    assert [action for action, _ in out["copied"]["sent"]] == [
        {"do": "duplicate", "ids": ["b"]},
        {"do": "move", "id": "b-2", "parent": "root", "index": 2},
        {"do": "align", "id": "b-2", "with": "crystal"}]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_box_whose_move_cannot_be_asked_for_is_home_at_once() -> None:
    first, second = ["mech", "smiles", "geo", "pose"], ["b", "crystal", "a"]
    out = _drag_page(_snake_page(first, second) + """
figure.breaks = "no edit";
console.log(JSON.stringify(await figure.drag("b", right("pose"))));
""")
    # Whatever fails once it is let go, it is not left where it was let go to wait for a
    # drawing that will not come.
    assert out == {"sent": [], "shown": True, "over": True, "carried": False, "failed": "no edit"}


def test_a_box_let_go_tells_its_host_which_keeps_drawings_back_while_one_is_carried() -> None:
    """A drawing put in while a box is carried takes the figure from under it and ends the
    drag with nothing done. A host keeps one back while ``dragging`` says a box is carried,
    and is told when it is let go, once; a box pressed and not carried was never one."""

    first, second = ["mech", "smiles", "geo", "pose"], ["b", "crystal", "a"]
    out = _drag_page(_snake_page(first, second) + """
const before = figure.told || 0;
const went = await figure.drag("b", right("pose"));
const once = figure.told;
const pressed = await figure.drag("mech", [169, 60], { redrawn: false });
console.log(JSON.stringify({ before, once, after: figure.told, moved: went.sent.length > 0,
  stayed: pressed.sent.length === 0, over: went.over && pressed.over }));
""")
    assert out == {
        "before": 0, "once": 1, "after": 1, "moved": True, "stayed": True, "over": True,
    }


# -- the File menu's Rename and Duplicate --------------------------------------------


def test_a_document_renamed_follows_its_file_with_its_edits(served) -> None:
    url, workspace = served
    doc = workspace.open("figure.yaml")
    listener = workspace.listen("page-b", PERSON)
    typed = SAMPLE_FIGURE.replace("Encoder", "Coder")
    doc.update({"text": typed}, doc.version, PERSON, "page-a")
    asked = {"file": "figure.yaml", "to": "Pipeline.yaml", "who": PERSON}
    status, answer = call(f"{url}/api/rename", workspace.token, asked)
    assert (status, answer) == (200, {"file": "Pipeline.yaml"})
    folder = workspace.root
    assert not (folder / "figure.yaml").exists()
    # What was typed and not yet written is in the renamed file, not left under the old name.
    assert "Coder" in (folder / "Pipeline.yaml").read_text(encoding="utf-8")
    assert workspace.docs["Pipeline.yaml"] is doc and "figure.yaml" not in workspace.docs
    events = []
    while not listener.events.empty():
        events.append(listener.events.get())
    assert {"type": "renamed", "file": "figure.yaml", "to": "Pipeline.yaml"} in events
    assert any(entry["text"] == "renamed “figure” to “Pipeline”" for entry in workspace.activity)
    # Never over another file, and only as a document's name.
    (folder / "other.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    asked = {"file": "Pipeline.yaml", "to": "other.yaml"}
    status, answer = call(f"{url}/api/rename", workspace.token, asked)
    assert status == 409 and "already used" in answer["error"]
    asked = {"file": "Pipeline.yaml", "to": "notes.txt"}
    status, _ = call(f"{url}/api/rename", workspace.token, asked)
    assert status == 400
    assert (folder / "Pipeline.yaml").exists()


def test_a_document_duplicated_is_a_copy_beside_it_opened(served) -> None:
    url, workspace = served
    doc = workspace.open("figure.yaml")
    typed = SAMPLE_FIGURE.replace("Encoder", "Coder")
    doc.update({"text": typed}, doc.version, PERSON, "page-a")
    asked = {"file": "figure.yaml", "to": "figure copy.yaml"}
    status, answer = call(f"{url}/api/duplicate", workspace.token, asked)
    assert (status, answer) == (200, {"file": "figure copy.yaml"})
    folder = workspace.root
    assert "Coder" in (folder / "figure copy.yaml").read_text(encoding="utf-8")
    assert "Coder" in (folder / "figure.yaml").read_text(encoding="utf-8")
    assert "figure copy.yaml" in workspace.docs and workspace.docs["figure.yaml"] is doc
    status, _ = call(f"{url}/api/duplicate", workspace.token, asked)
    assert status == 409


# -- the assistant's words when it can't answer ----------------------------------------


def _stand_in_sdk(name: str) -> NS:
    """An SDK's errors, as the assistant tells them apart (the SDK itself not needed)."""

    class APIStatusError(Exception):
        status_code, message = 400, ""

    errors = {
        "APIStatusError": APIStatusError,
        "AuthenticationError": type("AuthenticationError", (APIStatusError,), {}),
        "RateLimitError": type("RateLimitError", (APIStatusError,), {}),
        "NotFoundError": type("NotFoundError", (APIStatusError,), {}),
        "APIConnectionError": type("APIConnectionError", (Exception,), {}),
    }
    return NS(__name__=name, **errors)


def test_a_refused_key_and_a_server_not_running_are_said_as_they_are(monkeypatch) -> None:
    import sys

    from flexo.studio import assistant

    openai, anthropic = _stand_in_sdk("openai"), _stand_in_sdk("anthropic")
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    monkeypatch.setenv("FLEXO_STUDIO_OTHER_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("FLEXO_STUDIO_OTHER_NAME", "Ollama")
    monkeypatch.delenv("FLEXO_STUDIO_OTHER_MODEL", raising=False)
    monkeypatch.delenv("FLEXO_STUDIO_SETTINGS", raising=False)
    found = assistant.providers()
    other, chatgpt, claude = found["other"], found["chatgpt"], found["claude"]
    # A key there, refused: never "add a key".
    assert claude.explain(anthropic.AuthenticationError()).startswith(
        "Claude didn\u2019t accept the API key: it may be mistyped, expired or revoked. "
        "Set ANTHROPIC_API_KEY"
    )
    assert chatgpt.explain(openai.APIConnectionError()) == (
        "Couldn\u2019t reach ChatGPT: check your internet connection."
    )
    assert other.explain(openai.APIConnectionError()) == (
        "Couldn\u2019t reach Ollama at http://localhost:11434/v1. Check that it\u2019s running, "
        "and its address (FLEXO_STUDIO_OTHER_URL)."
    )
    # In the Mac app, where its Settings put it right.
    monkeypatch.setenv("FLEXO_STUDIO_SETTINGS", "the app's Settings")
    assert chatgpt.explain(openai.AuthenticationError()).endswith(
        "Put in a new one in the app's Settings."
    )
    assert other.explain(openai.APIConnectionError()).endswith(
        "and its address in the app's Settings."
    )

    # Asked with its server not running, it says so -- not "choose a model" from a list that
    # couldn't be read.
    def unreachable() -> list[str]:
        raise openai.APIConnectionError()

    other.client = NS()
    monkeypatch.setattr(other, "list_models", unreachable)
    with pytest.raises(openai.APIConnectionError):
        other.converse(None, {})
