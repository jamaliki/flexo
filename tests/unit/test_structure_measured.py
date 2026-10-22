"""A molecule is measured once: its extent and what it is framed by are kept, in memory and
on disk beside its drawing, and a figure laid out again -- every way it could be, changed, or
opened another day -- neither draws nor measures it again (flexo.structure_fit)."""

from __future__ import annotations

from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure

DATA = Path(__file__).parent / "data"


def _forget() -> None:
    """Everything kept of the structures drawn so far forgotten in memory, as in a new
    session: only the disk keeps them."""

    from flexo import confine, drawn, structure_fit, structure_frames, structures

    for kept in (
        structures._render_svg,
        structures._render,
        structures._checked,
        structures._own_ids,
        drawn._picture,
        structure_fit._svg_extent,
        structure_fit._png_extent,
        structure_frames._geometry,
    ):
        kept.cache_clear()
    structures._failed.clear()
    structure_fit._EXTENTS.clear()
    confine._SEEN.clear()


def _counting(monkeypatch, module, name: str) -> list[object]:
    called: list[object] = []
    real = getattr(module, name)

    def counted(*args):
        called.append(args)
        return real(*args)

    monkeypatch.setattr(module, name, counted)
    return called


def _figure(words: str, *, framed: bool = False) -> flexo.Figure:
    with flexo.Figure("measured") as figure:
        row = figure.root.row("row", gap=24)
        before = row.block("before", label=words)
        model = row.structure(
            "model",
            DATA / "1a7g.cif",
            look="flat",
            width=200,
            height=120,
            yaw=20,
            colors={"E": "#3f7fc0"},
            **({"frame": "f"} if framed else {}),
        )
        if framed:
            row.structure(
                "part",
                DATA / "1a7g.cif",
                look="flat",
                width=200,
                height=120,
                frame="f",
                cartoon="resi 300-320",
                sticks="none",
            )
        figure.connect(before, model)
    return figure


def test_a_molecule_is_measured_once_however_often_its_figure_is_laid_out() -> None:
    """Laid out every way it could be, and again once its words beside it change, a figure
    measures its molecule's drawing once: never again, and never drawn again."""

    pytest.importorskip("molsketch")
    from flexo import structure_fit, structures
    from flexo.boxfit import fit_in_box

    _forget()
    with pytest.MonkeyPatch.context() as patch:
        measured = _counting(patch, structure_fit, "_svg_extent")
        first = fit_in_box(_figure("Substrate"), 520, 160)
        assert len(measured) == 1, len(measured)
        measured.clear()
        drawn = _counting(patch, structures, "_drawn")
        again = fit_in_box(_figure("Substrate, bound"), 520, 160)
        assert measured == [] and drawn == []
    assert first.layout == again.layout


def test_a_figure_opened_again_neither_draws_nor_measures_its_molecules(
    tmp_path: Path, monkeypatch
) -> None:
    """Opened again another day (nothing in memory), a figure of structures sharing a frame
    is laid out from what was kept beside their drawings -- their extents, what frames them
    -- and drawn the same, mol-sketch never asked, no drawing read to be measured."""

    pytest.importorskip("molsketch")
    from flexo import structure_fit, structures

    kept = tmp_path / "kept"
    monkeypatch.setenv("FLEXO_STRUCTURE_CACHE", str(kept))
    _forget()
    first = compile_figure(_figure("Substrate", framed=True).spec).document.text
    names = [item.name for item in kept.iterdir()]
    assert any(name.endswith(".extent.json") for name in names)
    assert any(name.endswith(".npz") for name in names)

    _forget()
    drawn = _counting(monkeypatch, structures, "_drawn")
    measured = _counting(monkeypatch, structure_fit, "_svg_extent")
    assert compile_figure(_figure("Substrate", framed=True).spec).document.text == first
    assert drawn == [] and measured == []


def test_a_molecule_mol_sketch_fails_to_draw_is_measured_as_its_hatched_panel() -> None:
    """A molecule mol-sketch can't draw at these settings is laid out as the hatched panel it
    is drawn as -- and its extent is not kept: drawn again another time, it may be drawn."""

    pytest.importorskip("molsketch")
    from flexo import structure_fit, structures
    from flexo.style import Palette
    from flexo.themes import figure_style

    _forget()
    spec = _figure("Substrate").spec
    node = next(node for node in spec.nodes if node.id == "row.model")
    style = figure_style(spec)
    ask = structures._ask(node, style, Palette("plain", {}, ()))
    structures._failed[structures._failing(ask)] = "mol-sketch couldn't draw it."
    try:
        found = structure_fit.drawn_extent(ask, 2.0)
        assert found == structure_fit._png_extent(structures._hatched(2.0))
        assert (ask, 2.0) not in structure_fit._EXTENTS
    finally:
        structures._failed.clear()
