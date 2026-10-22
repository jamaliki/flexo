"""The studio keeps up with typing: a document is written without holding up the edits made
meanwhile, a deck's YAML is written over from the slides that changed, and answers go to the
page as they are."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.workspace import Workspace

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


def test_edits_are_taken_while_the_document_is_being_written(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        writing, go = threading.Event(), threading.Event()
        save = doc.kind.save

        def slow(path, document, *args, **kwargs):
            writing.set()
            assert go.wait(10)
            return save(path, document, *args, **kwargs)

        doc.kind.save = slow
        first = SAMPLE_FIGURE.replace("Input $x$", "Input $x_0$")
        doc.update({"text": first}, 1, PERSON)
        writer = threading.Thread(target=doc.write)
        writer.start()
        assert writing.wait(10)
        # Taken at once, the file still being written with the edit before it.
        started = time.monotonic()
        second = first.replace("Output $y$", "Output $z$")
        version, _ = doc.update({"text": second}, 2, PERSON)
        assert version == 3 and time.monotonic() - started < 2
        go.set()
        writer.join(10)
        assert doc.saved == 2 or doc.saved == 3
        doc.kind.save = save
        workspace.flush()
        assert doc.saved == 3
        assert "Output $z$" in (tmp_path / "figure.yaml").read_text(encoding="utf-8")
    finally:
        workspace.close()

