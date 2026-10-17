"""A studio started on a figure with a structure in it draws the figure while its page loads:
the page's first drawing finds the molecule drawn."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from flexo.studio.server import start

DATA = Path(__file__).parent / "data"

FIGURE = """figure: {id: warm}
nodes:
  - id: model
    kind: structure
    properties: {source: model.cif, look: flat, width: 120, height: 90}
"""


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


def _warming() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "studio warm-up"]


def test_a_figure_with_a_structure_is_drawn_as_the_studio_starts(
    tmp_path: Path, monkeypatch
) -> None:
    pytest.importorskip("molsketch")
    from flexo import structures

    shutil.copyfile(DATA / "1a7g.cif", tmp_path / "model.cif")
    (tmp_path / "figure.yaml").write_text(FIGURE, encoding="utf-8")
    for kept in (structures._render_svg, structures._render, structures._checked):
        kept.cache_clear()
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    try:
        for thread in _warming():
            thread.join(120)
        drawn: list[object] = []
        real = structures._drawn
        monkeypatch.setattr(structures, "_drawn", lambda ask: drawn.append(ask) or real(ask))
        document = {"text": FIGURE, "suffix": ".yaml"}
        result = workspace.draw("figure.yaml", document, 1, {}, {})
        assert result["pages"] and "model.molecule" in result["pages"][0]["svg"]
        assert drawn == []  # (drawn already, as the studio started)
    finally:
        workspace.close()
        server.server_close()


def test_a_figure_without_a_structure_is_left_for_its_page(tmp_path: Path) -> None:
    from flexo.studio.figure_kind import SAMPLE_FIGURE

    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    before = len(_warming())
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    try:
        assert len(_warming()) == before
    finally:
        workspace.close()
        server.server_close()
