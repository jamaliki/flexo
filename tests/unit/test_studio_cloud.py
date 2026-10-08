"""A folder kept in step by a cloud service (Dropbox, Google Drive, iCloud Drive…) is edited
from several computers at once: the copy the service keeps of a file two of them wrote at
once is merged back in, and its documents are written less often while typed in."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from flexo.studio import workspace as studio
from flexo.studio.workspace import (
    Workspace,
    cloud_service,
    conflict_copies,
    is_conflict_copy,
)

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
THEME = "theme: {name: lab, base: paper}\n"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return home


def wait_for(condition, seconds: float = 8.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("waited in vain")


def _folder(home: Path, *parts: str) -> Path:
    folder = home.joinpath(*parts)
    folder.mkdir(parents=True)
    return folder


def test_a_folder_is_known_by_the_service_keeping_it(_home: Path) -> None:
    storage = ("Library", "CloudStorage")
    drive = _folder(_home, *storage, "GoogleDrive-ada@lab.org", "My Drive", "talk")
    assert cloud_service(drive) == "Google Drive"
    assert cloud_service(_folder(_home, *storage, "Dropbox", "talks")) == "Dropbox"
    assert cloud_service(_folder(_home, *storage, "OneDrive-Lab", "talks")) == "OneDrive"
    assert cloud_service(_folder(_home, "Dropbox (Lab)", "talks")) == "Dropbox"
    assert cloud_service(_folder(_home, "Library", "Mobile Documents", "talks")) == "iCloud Drive"
    assert cloud_service(_folder(_home, "Documents", "talks")) is None
    assert cloud_service(_folder(_home, "Dropboxes")) is None
    assert cloud_service(_home.parent) is None  # outside the home folder


def test_the_copies_services_keep_are_known_by_name(tmp_path: Path) -> None:
    talk = tmp_path / "talk.yaml"
    for name in (
        "talk (Ben's conflicted copy 2026-10-08).yaml",
        "talk [Conflict].yaml",
        "talk.sync-conflict-20261008-101500-ABCDEFG.yaml",
        "talk-Conflict-Ben.yaml",
    ):
        assert is_conflict_copy(talk, tmp_path / name), name
    for name in ("talk.yaml", "talks.yaml", "talk copy.yaml", "talk 2.yaml", "talk.yml"):
        assert not is_conflict_copy(talk, tmp_path / name), name
    assert not is_conflict_copy(talk, tmp_path / "in" / "talk [Conflict].yaml")
    # iCloud Drive numbers its own; anywhere else, "talk 2" is someone's.
    assert is_conflict_copy(talk, tmp_path / "talk 2.yaml", "iCloud Drive")
    assert not is_conflict_copy(talk, tmp_path / "talk two.yaml", "iCloud Drive")


def test_only_copies_made_since_the_document_opened_are_taken(tmp_path: Path) -> None:
    talk = tmp_path / "talk.yaml"
    talk.write_text(THEME, encoding="utf-8")
    old = tmp_path / "talk (Ben's conflicted copy 2025-01-01).yaml"
    new = tmp_path / "talk [Conflict].yaml"
    for path in (old, new):
        path.write_text(THEME, encoding="utf-8")
    long_ago = time.time() - 86400
    os.utime(old, (long_ago, long_ago))
    assert conflict_copies(talk, "Dropbox", since=time.time() - 60) == [new]
    assert conflict_copies(talk, "Dropbox") == [old, new]


def _theme(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["theme"]


def test_documents_in_a_shared_folder_are_written_less_often(_home: Path) -> None:
    shared = _folder(_home, "Dropbox", "talks")
    here = _folder(_home, "talks")
    for folder in (shared, here):
        workspace = Workspace(folder)
        try:
            pace = (workspace.quiet, workspace.patience)
            assert pace == ((studio.SHARED_QUIET, studio.SHARED_PATIENCE) if folder == shared
                            else (studio.QUIET, studio.PATIENCE))
        finally:
            workspace.close()


def test_a_copy_of_this_computers_write_is_merged_with_the_other_kept_in_its_place(
    _home: Path, tmp_path: Path,
) -> None:
    folder = _folder(_home, "Library", "CloudStorage", "Dropbox", "talks")
    theme = folder / "lab.yaml"
    theme.write_text(THEME, encoding="utf-8")
    workspace = Workspace(folder)
    told: list = []
    workspace.broadcast = told.append  # type: ignore[method-assign]
    try:
        doc = workspace.open("lab.yaml")
        doc.update({"theme": {"name": "lab", "base": "paper", "description": "mine"}}, 1, PERSON)
        workspace.flush()
        assert _theme(theme)["description"] == "mine"
        # Another computer wrote it at once, from the file as it was: the service keeps its
        # in the file, and this one's beside it -- first the copy, then the other's.
        copy = folder / "lab (Ada's conflicted copy 2026-10-08).yaml"
        theme.rename(copy)
        time.sleep(0.6)
        assert doc.name == "lab.yaml"  # not followed: the copy is no rename
        theirs = "theme: {name: lab, base: ink}\n"
        partial = folder / ".lab.yaml.download"
        partial.write_text(theirs, encoding="utf-8")
        partial.replace(theme)
        wait_for(lambda: not copy.exists())
        assert doc.document == {"theme": {"name": "lab", "base": "ink", "description": "mine"}}
        wait_for(lambda: _theme(theme) == doc.document["theme"])
        kept = list((tmp_path / "data" / "flexo" / "merged").glob("*/*"))
        assert [path.name for path in kept] == [copy.name]
        assert {"type": "conflict", "file": "lab.yaml", "copy": copy.name,
                "service": "Dropbox"} in told
    finally:
        workspace.close()


def test_the_copy_waits_while_the_file_still_holds_what_it_does(_home: Path) -> None:
    folder = _folder(_home, "Dropbox", "talks")
    theme = folder / "lab.yaml"
    theme.write_text(THEME, encoding="utf-8")
    workspace = Workspace(folder)
    try:
        doc = workspace.open("lab.yaml")
        doc.update({"theme": {"name": "lab", "base": "paper", "description": "mine"}}, 1, PERSON)
        workspace.flush()
        # The copy made beside it, and the other's not yet downloaded over it.
        copy = folder / "lab (Ada's conflicted copy 2026-10-08).yaml"
        copy.write_text(theme.read_text(encoding="utf-8"), encoding="utf-8")
        time.sleep(2.6)
        assert copy.exists()
        theme.write_text("theme: {name: lab, base: ink}\n", encoding="utf-8")
        wait_for(lambda: not copy.exists())
        assert doc.document == {"theme": {"name": "lab", "base": "ink", "description": "mine"}}
    finally:
        workspace.close()


def test_another_computers_copy_beside_this_ones_write_is_merged_in(_home: Path) -> None:
    folder = _folder(_home, "Google Drive", "talks")
    theme = folder / "lab.yaml"
    theme.write_text(THEME, encoding="utf-8")
    workspace = Workspace(folder)
    try:
        doc = workspace.open("lab.yaml")
        doc.update({"theme": {"name": "lab", "base": "ink"}}, 1, PERSON)
        workspace.flush()
        doc.update({"theme": {"name": "lab", "base": "ink", "fonts": {"body": "Inter"}}},
                   doc.version, PERSON)
        workspace.flush()
        # Its write lost to this one's, from the file as it first was.
        copy = folder / "lab [Conflict].yaml"
        copy.write_text("theme: {name: lab, base: paper, description: theirs}\n",
                        encoding="utf-8")
        wait_for(lambda: not copy.exists())
        assert doc.document == {
            "theme": {"name": "lab", "base": "ink", "fonts": {"body": "Inter"},
                      "description": "theirs"}
        }
        wait_for(lambda: _theme(theme).get("description") == "theirs")
    finally:
        workspace.close()


def test_a_copy_of_another_deck_is_left_as_it_is() -> None:
    one = {"deck": {"id": "talk", "title": "Talk"}, "slides": []}
    other = {"deck": {"id": "seminar", "title": "Talk"}, "slides": []}
    assert studio._same_document(one, {**one, "slides": [{"title": "New"}]})
    assert not studio._same_document(one, other)
    assert studio._same_document({"theme": {"name": "lab"}}, {"theme": {"name": "lab"}})


def test_conflict_copies_in_a_folder_of_this_computers_alone_are_left(_home: Path) -> None:
    folder = _folder(_home, "talks")
    theme = folder / "lab.yaml"
    theme.write_text(THEME, encoding="utf-8")
    workspace = Workspace(folder)
    try:
        doc = workspace.open("lab.yaml")
        copy = folder / "lab [Conflict].yaml"
        copy.write_text("theme: {name: lab, base: ink}\n", encoding="utf-8")
        time.sleep(2.4)
        assert copy.exists() and doc.document == {"theme": {"name": "lab", "base": "paper"}}
    finally:
        workspace.close()


def test_a_copy_merged_in_is_never_merged_again(
    _home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(_home, "Dropbox", "talks")
    theme = folder / "lab.yaml"
    theme.write_text(THEME, encoding="utf-8")
    monkeypatch.setattr(studio, "set_aside", lambda path: False)  # it can't be moved
    workspace = Workspace(folder)
    try:
        doc = workspace.open("lab.yaml")
        copy = folder / "lab [Conflict].yaml"
        copy.write_text("theme: {name: lab, base: paper, description: theirs}\n",
                        encoding="utf-8")
        wait_for(lambda: doc.document["theme"].get("description") == "theirs")
        # Edited after, and saved: the copy, still there, does not take that back.
        doc.update({"theme": {"name": "lab", "base": "ink"}}, doc.version, PERSON)
        workspace.flush()
        time.sleep(4.5)
        assert doc.document == {"theme": {"name": "lab", "base": "ink"}}
        assert copy.exists()
    finally:
        workspace.close()
