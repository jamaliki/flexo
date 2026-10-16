"""A figure a document holds, edited in a tab of its own (``flexo.studio.embedded``): its words
the figure as the document holds it, each edit made to the document at once and each edit of
the document's coming to it, nothing written but the document. And what a deck kept in one file
needs of the studio: files a document no longer names taken out of a bundle (and put back on an
undo), new bundles made (``flexo.studio.bundles.new_bundle``), and a document's kind writing
into it what a bundle keeps inside it as it is packed (``bundled``)."""

from __future__ import annotations

import copy
import json
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from flexo import bundle as B
from flexo.studio import Drawing, bundles
from flexo.studio.embedded import FigureView, split, words_of
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
FIGURE = {
    "figure": {"id": "pipeline"},
    "nodes": [{"id": "encoder", "label": "Encoder"}, {"id": "decoder", "label": "Two\nlines"}],
    "edges": [{"from": "encoder", "to": "decoder"}],
}


class Holder:
    """A kind of document that holds figures by name (as a deck does, on its slides)."""

    name = "holder"
    title = "Holder"
    static = Path(".")

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and "holds" in document

    def new(self, path: Path) -> dict[str, Any]:
        return {"holds": {}}

    def load(self, path: Path) -> Any:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def save(self, path: Path, document: Any) -> None:
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    def catalog(self) -> dict[str, Any]:
        return {}

    def draw(self, document: Any, base: Path, hints: dict[str, Any] | None = None) -> Drawing:
        return Drawing([])

    def export(self, document: Any, base: Path, stem: str, formats: list[str]) -> list[Path]:
        return []

    def figure_in(self, document: Any, key: str) -> dict[str, Any] | None:
        found = (document.get("holds") or {}).get(key)
        return found if isinstance(found, dict) else None

    def with_figure(self, document: Any, key: str, figure: dict[str, Any]) -> Any:
        if self.figure_in(document, key) is None:
            return None
        changed = copy.deepcopy(document)
        changed["holds"][key] = copy.deepcopy(figure)
        return changed

    def bundled(self, data: Any, base: Path) -> Any:
        return {**data, "bundled": True}


@pytest.fixture(autouse=True)
def _apart(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEXO_BUNDLES", str(tmp_path_factory.mktemp("bundles")))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def workspace(tmp_path: Path) -> Any:
    (tmp_path / "talk.yaml").write_text(
        yaml.safe_dump({"holds": {"pipeline": FIGURE}}, sort_keys=False), encoding="utf-8"
    )
    found = Workspace(tmp_path)
    found.kinds["holder"] = Holder()
    told: list[dict[str, Any]] = []
    tell = found.broadcast
    found.broadcast = lambda event: (told.append(event), tell(event))  # type: ignore[method-assign]
    found.told = told  # type: ignore[attr-defined]
    try:
        yield found
    finally:
        found.close()


def test_a_figure_a_document_holds_opens_as_a_figure_of_its_own(workspace: Any) -> None:
    view = workspace.open("talk.yaml#pipeline")
    assert isinstance(view, FigureView) and view.kind.name == "figure"
    assert workspace.open("talk.yaml#pipeline") is view  # one for every page
    assert yaml.safe_load(view.document["text"]) == FIGURE
    assert "label: |-\n    Two\n    lines" in view.document["text"]  # words as a person writes them
    info = view.info()
    assert info["file"] == "talk.yaml#pipeline" and info["exists"] and not info["held"]
    # Drawn as the figure kind draws it, its files found beside the document.
    drawn = workspace.draw("talk.yaml#pipeline", view.document, 1, {}, {})
    assert drawn["pages"] and "svg" in drawn["pages"][0]
    with pytest.raises(FileNotFoundError, match="no figure “nowhere”"):
        workspace.open("talk.yaml#nowhere")
    assert split("talk.yaml#pipeline") == ("talk.yaml", "pipeline") and split("notes.txt#a") is None


def test_an_edit_in_the_figures_tab_is_the_documents_and_the_documents_comes_back(
    workspace: Any,
) -> None:
    view, deck = workspace.open("talk.yaml#pipeline"), workspace.open("talk.yaml")
    text = view.document["text"].replace("label: Encoder", "label: Backbone")
    version, document = view.update({"text": text}, view.version, PERSON, "page-a")
    assert document["text"] == text and version == view.version
    assert deck.document["holds"]["pipeline"]["nodes"][0]["label"] == "Backbone"
    assert deck.version == 2  # one change of the document's
    # Changed in the document (on its slide, undone there): the figure's tab has it.
    changed = copy.deepcopy(deck.document)
    changed["holds"]["pipeline"]["nodes"][1]["label"] = "Head"
    deck.update(changed, deck.version, PERSON, "page-b")
    assert yaml.safe_load(view.document["text"])["nodes"][1]["label"] == "Head"
    told = [(event["type"], event.get("file")) for event in workspace.told]
    assert ("doc", "talk.yaml#pipeline") in told and ("doc", "talk.yaml") in told
    # Words that do not read yet stay in the tab; the document waits for them to.
    view.update({"text": "figure: {id: pipeline\n"}, view.version, PERSON, "page-a")
    assert deck.document["holds"]["pipeline"]["nodes"][1]["label"] == "Head"


def test_a_figure_gone_from_its_document_takes_no_edits_until_it_is_back(workspace: Any) -> None:
    view, deck = workspace.open("talk.yaml#pipeline"), workspace.open("talk.yaml")
    held = copy.deepcopy(deck.document)
    deck.update({"holds": {}}, deck.version, PERSON, "page-b")
    assert view.gone and "no longer in “talk”" in view.problem
    with pytest.raises(ValueError, match="no longer in"):
        view.update({"text": "figure: {id: x}\nnodes: []\n"}, view.version, PERSON, "page-a")
    deck.update(held, deck.version, PERSON, "page-b")  # undone
    assert not view.gone and view.problem is None


def test_a_figures_tab_writes_nothing_but_its_document_and_is_saved_with_it(
    workspace: Any, tmp_path: Path
) -> None:
    view = workspace.open("talk.yaml#pipeline")
    text = view.document["text"].replace("Encoder", "Saved")
    view.update({"text": text}, view.version, PERSON, "page-a")
    assert view.write() is True
    assert sorted(path.name for path in tmp_path.iterdir()) == ["talk.yaml"]
    assert "Saved" in (tmp_path / "talk.yaml").read_text()
    saved = [event for event in workspace.told if event["type"] == "saved"]
    assert {"type": "saved", "file": "talk.yaml#pipeline", "version": view.version} in saved
    assert view.saved == view.version


def test_files_a_document_no_longer_names_go_from_a_bundle_and_come_back(tmp_path: Path) -> None:
    from flexo.studio.figure_kind import SAMPLE_FIGURE

    (tmp_path / "figures").mkdir()
    file = tmp_path / "figures" / "old.yaml"
    file.write_text(SAMPLE_FIGURE, encoding="utf-8")
    named = "figure: {id: main}\nnodes:\n- {id: a, label: 'figures/old.yaml'}\n"
    (tmp_path / "main.yaml").write_text(named, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("main.yaml")
        workspace.release([file])  # a folder's: its person's, left be
        doc.update({"text": named.replace("figures/old.yaml", "gone")}, doc.version, PERSON)
        assert file.exists()
        workspace.bundle = object()  # a bundle's working folder: the file is the bundle's own
        doc.update({"text": named}, doc.version, PERSON)
        workspace.release([file])
        doc.update({"text": named.replace("figures/old.yaml", "gone")}, doc.version, PERSON)
        assert not file.exists()
        doc.update({"text": named}, doc.version, PERSON)  # undone: it is named again
        assert file.read_text(encoding="utf-8") == SAMPLE_FIGURE
        # Named by a page's document not yet sent (an edit asked of it): back before it is read.
        doc.update({"text": named.replace("figures/old.yaml", "gone")}, doc.version, PERSON)
        assert not file.exists()
        workspace.follow_uploads([(tmp_path, {"text": named})])
        assert file.read_text(encoding="utf-8") == SAMPLE_FIGURE
    finally:
        workspace.close()


def test_a_new_bundle_holds_a_new_document_named_as_it_is(tmp_path: Path) -> None:
    made = bundles.new_bundle(tmp_path / "Untitled", "figure")
    assert made == tmp_path / "Untitled.flexo"
    with B.Bundle(made) as opened:
        assert opened.document == "Untitled.yaml" and opened.kind == "figure"
    with pytest.raises(FileExistsError, match="already exists"):
        bundles.new_bundle(tmp_path / "Untitled.flexo", "figure")
    with pytest.raises(ValueError, match="No kind"):
        bundles.new_bundle(tmp_path / "Other", "nothing")


def test_a_studio_started_on_a_bundle_not_there_yet_makes_it(tmp_path: Path) -> None:
    server, workspace = start(tmp_path / "Lab meeting.flexo", browser=False, kind="figure")
    try:
        assert (tmp_path / "Lab meeting.flexo").is_file() and workspace.trusted
        assert workspace.bundle.document == "Lab meeting.yaml"
    finally:
        workspace.close()
        server.server_close()


def test_new_deck_in_a_page_makes_a_bundle_beside_the_folders_documents(tmp_path: Path) -> None:
    (tmp_path / "notes.yaml").write_text("figure: {id: notes}\nnodes: []\n", encoding="utf-8")
    server, workspace = start(tmp_path, browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = json.dumps({"name": "Group talk", "kind": "figure"}).encode()
        request = urllib.request.Request(
            f"{url}/api/bundle/new",
            data=body,
            headers={"Content-Type": "application/json", "X-Studio-Token": workspace.token},
        )
        with OPENER.open(request) as response:
            made = json.loads(response.read())
        assert made["name"] == "Group talk.flexo" and (tmp_path / "Group talk.flexo").is_file()
        # Served beside this one, for a tab of its own.
        with OPENER.open(made["address"]) as response:
            assert response.status == 200
    finally:
        workspace.close()  # (and the bundle's studio with it)
        server.shutdown()
        server.server_close()


def test_a_documents_kind_writes_into_it_what_a_bundle_keeps_inside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import flexo.studio

    found = flexo.studio.kinds()
    monkeypatch.setattr(flexo.studio, "kinds", lambda: {**found, "holder": Holder()})
    (tmp_path / "talk.yaml").write_text("# kept\nholds: {}\n", encoding="utf-8")
    made = B.pack(tmp_path / "talk.yaml")
    assert yaml.safe_load(zipfile.ZipFile(made.path).read("talk.yaml")) == {
        "holds": {},
        "bundled": True,
    }
    assert (tmp_path / "talk.yaml").read_text() == "# kept\nholds: {}\n"
    kept = B.pack(tmp_path / "talk.yaml", tmp_path / "as-is.flexo", embed=False)
    assert zipfile.ZipFile(kept.path).read("talk.yaml") == b"# kept\nholds: {}\n"


def test_a_figures_words_read_as_the_figure() -> None:
    assert yaml.safe_load(words_of(FIGURE)) == FIGURE
