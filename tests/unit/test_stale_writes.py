"""A file written whole by something that read it a while ago -- an agent writing back what it
read with its change, a script -- is taken in as a change from what it read: the edits saved
since it read the file are kept, and its own change is taken in (``Doc._made_from``,
``flexo.studio.nearness``). A file put back word for word as it was is taken in as it is."""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import pytest

from flexo.studio import nearness
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.workspace import RECENT, Workspace, _dumps

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
AGENT = {"id": "mcp:claude-code", "name": "Claude Code", "kind": "agent"}
MINE = ("Input $x$", "Input $x_0$")
THEIRS = ("Output $y$", "Output $\\hat{y}$")


@pytest.fixture(autouse=True)
def _apart(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))
    monkeypatch.setenv("FLEXO_ACTS", "0")


@pytest.fixture
def workspace(tmp_path: Path):
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    opened = Workspace(tmp_path)
    opened._stop.set()  # (no clock: each test takes the file in itself)
    try:
        yield opened
    finally:
        opened.close()


def _written(workspace: Workspace, text: str) -> None:
    """The file written by something else, a moment later than the studio last saw it."""

    path = workspace.root / "figure.yaml"
    path.write_text(text, encoding="utf-8")
    later = time.time_ns() + 2_000_000_000
    os.utime(path, ns=(later, later))


def _saved(workspace: Workspace, text: str) -> None:
    doc = workspace.open("figure.yaml")
    doc.update({"text": text}, doc.version, PERSON, "page-a")
    assert doc.write()


def _on_disk(workspace: Workspace) -> str:
    return (workspace.root / "figure.yaml").read_text(encoding="utf-8")


def test_a_writer_that_read_the_file_before_the_last_save_undoes_nothing_saved(
    workspace: Workspace,
) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)  # what the agent read
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))  # the owner's edit, saved
    _written(workspace, stale.replace(*THEIRS))  # the agent writes back the whole of it
    workspace.reread(doc)
    text = doc.document["text"]
    assert "Input $x_0$" in text and "Output $\\hat{y}$" in text
    # The file holds less than the document: written again, with both.
    assert doc.saved < doc.version
    workspace.flush()
    assert _on_disk(workspace) == text


def test_a_writer_that_read_an_older_save_still_keeps_every_save_since(
    workspace: Workspace,
) -> None:
    doc = workspace.open("figure.yaml")
    _saved(workspace, SAMPLE_FIGURE.replace("Encoder", "Encoder, first"))
    stale = _on_disk(workspace)
    words = SAMPLE_FIGURE.replace("Encoder", "Encoder, first")
    for edit in (MINE, ("tone: encoder", "tone: decoder")):
        words = words.replace(*edit)
        _saved(workspace, words)
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    text = doc.document["text"]
    assert all(
        part in text for part in ("Encoder, first", "Input $x_0$", "tone: decoder", "\\hat{y}")
    )


def test_a_writer_that_read_the_latest_is_taken_in_as_before(workspace: Workspace) -> None:
    doc = workspace.open("figure.yaml")
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    latest = _on_disk(workspace)
    # It reads the file as it is now, and changes the owner's own edit, and another thing: as
    # near what the file held before that edit as what it holds now, it is taken from now.
    _written(workspace, latest.replace("Input $x_0$", "Input $x_1$").replace(*THEIRS))
    workspace.reread(doc)
    text = doc.document["text"]
    assert "Input $x_1$" in text and "\\hat{y}" in text and "x_0" not in text
    assert doc.saved == doc.version  # (the file holds the document)


def test_a_file_put_back_word_for_word_is_taken_in(workspace: Workspace) -> None:
    doc = workspace.open("figure.yaml")
    first = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE).replace(*THEIRS))
    # git checkout, Time Machine, an editor's undo: the file as it was before both.
    _written(workspace, first)
    workspace.reread(doc)
    assert doc.document["text"] == SAMPLE_FIGURE
    assert doc.saved == doc.version


def test_a_writers_old_copy_written_again_brings_nothing_new(workspace: Workspace) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    workspace.flush()
    merged = doc.document["text"]
    # The same old copy, written again (a write tried twice): not taken for the file put back.
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    assert doc.document["text"] == merged
    workspace.flush()
    assert _on_disk(workspace) == merged


def test_a_stale_write_is_said_as_what_its_writer_changed_and_by_whom(
    workspace: Workspace,
) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    workspace.set_presence(AGENT, "figure.yaml", None, "Renaming the output")
    listener = workspace.listen("page-a", PERSON)
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    events = []
    while not listener.events.empty():
        events.append(listener.events.get())
    (changed,) = [event for event in events if event["type"] == "doc"]
    assert changed["who"] == AGENT
    said = [event["entry"]["text"] for event in events if event["type"] == "activity"]
    assert said == ["renamed “Output $y$” to “Output $\\hat{y}$”"]
    assert workspace.activity[-1]["who"] == AGENT


def test_a_stale_write_by_no_agent_here_is_another_apps(workspace: Workspace) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    entry = workspace.activity[-1]
    assert entry["who"]["name"] == "Another app"
    assert entry["text"].startswith("renamed “Output")


def test_a_stale_write_is_merged_with_edits_not_yet_saved(workspace: Workspace) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    typing = SAMPLE_FIGURE.replace(*MINE).replace("Encoder", "Encoder, typing")
    doc.update({"text": typing}, doc.version, PERSON, "page-a")  # (not written yet)
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    text = doc.document["text"]
    assert all(part in text for part in ("x_0", "Encoder, typing", "\\hat{y}"))


def test_a_writer_that_read_the_file_before_it_was_opened_undoes_nothing_saved_since(
    tmp_path: Path,
) -> None:
    # Read before the studio opened the file, and an edit made then (in the studio before it
    # was started again): what the file held then is not kept, but what was saved since the
    # file was opened is.
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    stale = SAMPLE_FIGURE
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE.replace(*MINE), encoding="utf-8")
    workspace = Workspace(tmp_path)
    workspace._stop.set()
    try:
        doc = workspace.open("figure.yaml")
        _saved(workspace, SAMPLE_FIGURE.replace(*MINE).replace("Encoder", "Encoder, since"))
        _written(workspace, stale.replace(*THEIRS))
        workspace.reread(doc)
        text = doc.document["text"]
        assert "Encoder, since" in text and "\\hat{y}" in text and "x_0" not in text
    finally:
        workspace.close()


def test_a_file_that_did_not_read_and_reads_again_is_taken_in_from_what_it_was_written_from(
    workspace: Workspace,
) -> None:
    doc = workspace.open("figure.yaml")
    stale = _on_disk(workspace)
    _saved(workspace, SAMPLE_FIGURE.replace(*MINE))
    _written(workspace, "figure: [\n")  # half written
    workspace.reread(doc)
    assert doc.held
    _written(workspace, stale.replace(*THEIRS))
    workspace.reread(doc)
    assert not doc.held
    assert "x_0" in doc.document["text"] and "\\hat{y}" in doc.document["text"]


def test_a_file_that_never_read_is_taken_whole_when_it_does(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text("figure: [\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    workspace._stop.set()
    try:
        doc = workspace.open("figure.yaml")
        assert doc.unread and not doc.recent
        _written(workspace, SAMPLE_FIGURE)
        workspace.reread(doc)
        assert doc.document["text"] == SAMPLE_FIGURE and not doc.unread
        assert doc.saved == doc.version
    finally:
        workspace.close()


# -- how near --


def test_versions_alike_are_near_and_a_part_moved_is_apart() -> None:
    deck = {"slides": [{"title": f"Slide {n}", "body": [{"text": f"Point {n}"}]} for n in range(9)]}
    edited = copy.deepcopy(deck)
    edited["slides"][4]["title"] = "Slide 4, edited"
    moved = copy.deepcopy(deck)
    moved["slides"].insert(7, moved["slides"].pop(2))
    one, other, elsewhere = _dumps(deck), _dumps(edited), _dumps(moved)
    assert nearness.apart(one, one) == 0
    assert nearness.apart(one, other) == nearness.apart(other, one) > 0
    assert nearness.apart(one, elsewhere) > 0
    # Lines of words are pieces too: a figure's words, a line changed.
    lines = "\n".join(f"line {n}" for n in range(40))
    changed = lines.replace("line 7", "seven")
    assert 0 < nearness.apart(_dumps({"text": lines}), _dumps({"text": changed})) < 8


def test_the_nearest_is_the_first_of_those_as_near() -> None:
    versions = [_dumps({"a": n, "b": [1, 2, 3]}) for n in range(5)]
    assert nearness.nearest(versions, _dumps({"a": 3, "b": [1, 2, 3]})) == versions[3]
    aim = _dumps({"a": 9, "b": [1, 2, 3]})  # as near to each
    assert nearness.nearest(versions, aim) == versions[0]
    assert nearness.nearest(list(reversed(versions)), aim) == versions[4]
    assert nearness.nearest([], aim) is None


def test_the_nearest_of_many_versions_is_found_as_each_against_the_aim_would_find_it() -> None:
    document = {
        "slides": [
            {"title": f"Slide {n}", "points": [f"{n}.{m}" for m in range(4)]} for n in range(30)
        ]
    }
    versions = []
    for n in range(RECENT):
        document = copy.deepcopy(document)
        document["slides"][(n * 7) % 30]["title"] = f"Edit {n}"
        if n % 5 == 0:
            document["slides"].insert(n % 30, document["slides"].pop(0))
        versions.append(_dumps(document))
    aim = json.loads(versions[11])
    aim["slides"][3]["points"].append("new")
    aim = _dumps(aim)
    newest_first = list(reversed(versions))
    expected = min(newest_first, key=lambda text: nearness.apart(text, aim))
    assert nearness.nearest(newest_first, aim) == expected == versions[11]
