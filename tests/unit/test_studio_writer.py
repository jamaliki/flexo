"""A studio's documents written by a process of their own (``flexo.studio.writer``): the same
words as written here, what each writing remembers of the file kept there from one writing
to the next, and every writing it cannot do done here, as before."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo.studio import writer
from flexo.studio.theme_kind import ThemeKind
from flexo.studio.workspace import Workspace

THEME = """\
# A theme with words of its own, kept as they are.
theme:
  name: look   # its name
  base: paper
  palette:
    ink: '#222222'
    # the accent, warm
    accent: '#c0392b'
roles:
- name: first   # the first
  ink: ink
- name: second
  ink: accent
- name: third
  ink: ink
"""


@pytest.fixture
def started() -> Iterator[None]:
    writer.start()
    try:
        yield
    finally:
        writer.stop()


def _theme(folder: Path) -> Path:
    path = folder / "look.yaml"
    path.write_text(THEME, encoding="utf-8")
    return path


def _edited(workspace: Workspace, change) -> str:
    doc = workspace.open("look.yaml")
    document = copy.deepcopy(doc.document)
    change(document)
    doc.update(document, doc.version, {"id": "a", "kind": "person"}, "a")
    assert doc.write()
    return doc.path.read_text(encoding="utf-8")


def _session(folder: Path) -> list[str]:
    """A theme written over its words three times: a colour changed, a role taken out, and
    that undone -- what is written each time."""

    workspace = Workspace(folder)
    workspace.quiet = workspace.patience = 1e9
    try:
        doc = workspace.open("look.yaml")
        assert isinstance(doc.kind, ThemeKind)
        whole = copy.deepcopy(doc.document)
        written = [_edited(workspace, lambda d: d["theme"]["palette"].update(accent="#1a5d9b"))]
        written.append(_edited(workspace, lambda d: d["roles"].pop(1)))
        roles = copy.deepcopy(whole["roles"])
        written.append(_edited(workspace, lambda d: d.update(roles=roles)))
        return written
    finally:
        workspace.close()


def test_a_document_is_written_by_the_process_as_it_is_written_here(
    tmp_path: Path, started: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    here, apart = tmp_path / "here", tmp_path / "apart"
    for folder in (here, apart):
        folder.mkdir()
        _theme(folder)
    asked: list[str] = []
    real = writer.save
    monkeypatch.setattr(writer, "save", lambda *a, **k: asked.append(a[4]) or real(*a, **k))
    by_process = _session(apart)
    # (Each writing was the process's.)
    assert len(asked) == 3 and all(name.endswith("look.yaml") for name in asked)
    writer.stop()
    by_here = _session(here)
    assert by_process == by_here
    # Its words kept where the document did not change -- and a role taken out and put back
    # is put back as it was written, the process remembering it from the writing before.
    assert all("# the accent, warm" in text and "# its name" in text for text in by_process)
    assert "name: second" not in by_process[1]
    assert by_process[2] == THEME.replace("#c0392b", "#1a5d9b")


def test_a_writing_the_process_cannot_do_is_done_here(tmp_path: Path, started: None) -> None:
    _theme(tmp_path)

    class Other(ThemeKind):
        """A kind the process does not know as the studio has it."""

    target = tmp_path / ".look.saving.yaml"
    document = {"base": "paper"}
    assert writer.save(Other(), target, document, THEME, str(tmp_path / "look.yaml")) is None
    assert not target.exists()
    # A kind it knows is written there -- and what kind of document it wrote is said.
    document = {"theme": {"name": "look", "base": "paper"}}
    done = writer.save(ThemeKind(), target, document, THEME, str(tmp_path / "look.yaml"))
    assert done is not None and done["claim"] == ["theme", False]
    assert "base: paper" in target.read_text(encoding="utf-8")


def test_without_the_process_writings_are_done_here(tmp_path: Path) -> None:
    writer.stop()
    _theme(tmp_path)
    assert writer.save(ThemeKind(), tmp_path / "x.yaml", {"base": "paper"}, THEME, "x") is None
    assert writer.prime(THEME) is False
    # A process that cannot be started is not asked again and again.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(writer, "COMMAND", ["/nonexistent/flexo-writer"])
    try:
        writer.start()
        for _ in range(writer.FAILURES + 2):
            assert (
                writer.save(ThemeKind(), tmp_path / "y.yaml", {"base": "paper"}, THEME, "y") is None
            )
        assert writer._FAILED >= writer.FAILURES and writer._process() is None
    finally:
        monkey.undo()
        writer.stop()
        writer._FAILED = 0
