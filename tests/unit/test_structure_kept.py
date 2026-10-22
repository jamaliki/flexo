"""A structure drawn once is kept on disk, and read back until its file changes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure

DATA = Path(__file__).parent / "data"


def _figure(source: Path, look: str = "flat") -> str:
    with flexo.Figure("kept") as figure:
        figure.root.structure(
            "model", source, look=look, width=120, height=90, colors={"E": "#3f7fc0"}
        )
    return compile_figure(figure.spec).document.text


def _forget() -> None:
    """The structures drawn so far forgotten in memory: only the disk keeps them."""

    from flexo import drawn, structures

    for kept in (structures._render_svg, structures._render, structures._checked, drawn._picture):
        kept.cache_clear()
    structures._failed.clear()


def _counting(monkeypatch) -> list[object]:
    from flexo import structures

    drawn: list[object] = []
    real = structures._drawn

    def counted(ask):
        drawn.append(ask)
        return real(ask)

    monkeypatch.setattr(structures, "_drawn", counted)
    return drawn


@pytest.mark.parametrize("look", ["flat", "engraved"])
def test_a_structure_drawn_once_is_read_back_until_its_file_changes(
    tmp_path: Path, monkeypatch, look: str
) -> None:
    pytest.importorskip("molsketch")
    source = tmp_path / "model.cif"
    shutil.copyfile(DATA / "1a7g.cif", source)
    kept = tmp_path / "kept"
    monkeypatch.setenv("FLEXO_STRUCTURE_CACHE", str(kept))
    _forget()
    first = _figure(source, look)
    drawing = ".svg" if look == "flat" else ".png"
    assert {item.suffix for item in kept.iterdir()} == {".json", drawing}

    # Opened again (a new session: nothing in memory): read back, not drawn.
    _forget()
    drawn = _counting(monkeypatch)
    assert _figure(source, look) == first
    assert drawn == []

    # The file saved again: drawn afresh, checked and drawn.
    later = source.stat().st_mtime + 5
    os.utime(source, (later, later))
    _forget()
    assert _figure(source, look) == first  # (the same molecule, drawn again)
    assert len(drawn) >= 2


def test_nothing_is_kept_when_keeping_is_off(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("molsketch")
    monkeypatch.setenv("FLEXO_STRUCTURE_CACHE", "0")
    _forget()
    _figure(DATA / "1a7g.cif")
    _forget()
    drawn = _counting(monkeypatch)
    _figure(DATA / "1a7g.cif")
    assert drawn


def test_an_installed_package_is_told_by_the_hashes_its_installation_recorded() -> None:
    """mol-sketch installed (as in the app) is told by what its installation recorded of its
    files, not by reading every one of them; a copy that is not the one recorded is read."""

    pytest.importorskip("molsketch")
    import importlib.util

    from flexo import structure_kept

    here = Path(importlib.util.find_spec("molsketch").origin).parent
    recorded = structure_kept._recorded("molsketch", here, False, (".py", ".js"))
    if recorded is None:
        pytest.skip("mol-sketch is installed to be worked on in place")
    names = {line.split("=")[0] for line in recorded.decode().splitlines()}
    assert names == {
        f"molsketch/{path.name}" for path in here.iterdir() if path.suffix in (".py", ".js")
    }
    assert structure_kept._recorded("molsketch", here.parent / "elsewhere", False, (".py",)) is None
