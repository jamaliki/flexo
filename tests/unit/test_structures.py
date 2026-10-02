"""A molecule drawn by mol-sketch, as a component in the figure's colours."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation
from flexo.structures import _png, _without_paper

DATA = Path(__file__).parent / "data"


def test_the_paper_is_taken_out_and_the_ink_kept() -> None:
    np = pytest.importorskip("numpy")
    pixels = np.zeros((1, 3, 4), dtype=np.uint8)
    pixels[0, 0] = (251, 250, 246, 255)  # the paper
    pixels[0, 1] = (0, 0, 0, 255)  # ink
    pixels[0, 2] = (253, 252, 250, 255)  # halfway to white from the paper
    out = _without_paper(pixels, "#fbfaf6")
    assert out[0, 0, 3] == 0
    assert tuple(out[0, 1]) == (0, 0, 0, 255)
    assert 0 < out[0, 2, 3] < 255
    assert _png(out).startswith(b"\x89PNG")


def test_a_structure_is_a_panel_with_the_molecule_in_the_figures_colours() -> None:
    pytest.importorskip("molsketch")
    with flexo.Figure("e2") as figure:
        row = figure.root.row("row", gap=20)
        row.structure(
            "model", DATA / "1a7g.cif", label="E2", width=120, height=90, colors={"E": "Viral"}
        )
        row.block("tag", label="E2 protein", tone="Viral")
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    svg = compiled.document.text
    found = re.search(r'id="row.model.molecule"[^>]*href="data:image/png;base64,([^"]+)"', svg)
    assert found
    png = base64.b64decode(found.group(1))
    assert png.startswith(b"\x89PNG") and len(png) > 1000
    model = compiled.routed.fitted.node("row.model").bounds
    assert model.width >= 120 and model.height >= 90


def test_without_mol_sketch_a_structure_says_how_to_get_it(monkeypatch) -> None:
    import builtins

    real = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object):
        if name == "molsketch":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    from flexo import structures

    structures._render.cache_clear()
    monkeypatch.setattr(builtins, "__import__", refuse)
    with flexo.Figure("none") as figure:
        figure.root.structure("m", DATA / "1a7g.cif")
    with pytest.raises(flexo.FlexoError, match="needs mol-sketch"):
        compile_figure(figure.spec)


def test_a_colour_for_a_chain_the_structure_lacks_is_said_with_the_chains_it_has() -> None:
    from flexo.structures import _check_chains, _NoSuchChain

    class Loaded:
        def _info(self) -> dict:
            return {"structure": {"name": "1a7g", "chains": ["E"]}}

    _check_chains(Loaded(), (("E", "#d55e00"), ("SER195", "#000000"), ("SER195.E", "#111111"),
                             ("entity:1", "#222222")))
    with pytest.raises(_NoSuchChain, match='"A" names no chain of 1a7g') as caught:
        _check_chains(Loaded(), (("A", "#d55e00"),))
    assert "Its chains are E" in caught.value.hint


def test_a_structure_dragged_round_is_turned_from_its_trace(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.studio.figure_edit import EditError
    from flexo.studio.figure_kind import FigureKind

    source = DATA / "1a7g.cif"
    text = (
        "figure: {id: turned}\n"
        "nodes:\n"
        "  - id: model\n    kind: structure\n"
        f"    properties: {{source: {source}, yaw: 40, pitch: -10}}\n"
        "  - {id: tag, label: E2}\n"
    )
    out = FigureKind().act({"text": text}, {"do": "structure-view", "id": "model"}, tmp_path)
    assert out["document"]["text"] == text
    view = out["view"]
    assert view["camera"]["yaw"] == 40 and view["camera"]["pitch"] == -10
    points = [point for chain in view["chains"] for point in chain]
    assert len(points) > 50 and all(len(point) == 3 for point in points)
    # Centred, so the page turns it about its middle.
    for k in range(3):
        values = [point[k] for point in points]
        assert abs(max(values) + min(values)) < 0.1
    with pytest.raises(EditError, match="not a structure"):
        FigureKind().act({"text": text}, {"do": "structure-view", "id": "tag"}, tmp_path)


def test_a_structure_takes_mol_sketch_settings_over_its_look(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.serialization import figure_to_document
    from flexo.studio.figure_kind import FigureKind

    with flexo.Figure("styled") as figure:
        figure.root.structure(
            "model",
            DATA / "1a7g.cif",
            palette="Okabe–Ito",  # noqa: RUF001
            style={"fill": "ink colour", "line": {"width": 2.5}},
        )
    compiled = compile_figure(figure.spec)
    assert 'id="model.molecule"' in compiled.document.text
    written = figure_to_document(figure.spec)["nodes"][0]["properties"]
    assert written["style"] == {"fill": "ink colour", "line": {"width": 2.5}}
    # What the studio shows beside each setting: what it is drawn with.
    text = (
        "figure: {id: styled}\n"
        "nodes:\n"
        "  - id: model\n    kind: structure\n"
        f"    properties: {{source: {DATA / '1a7g.cif'}, style: {{fill: ink colour}}}}\n"
    )
    settings = FigureKind().act(
        {"text": text}, {"do": "structure-settings", "id": "model"}, tmp_path
    )["settings"]
    assert settings["style"]["fill"] == "ink colour"
    assert settings["style"]["line.width"] > 0 and "Okabe–Ito" in settings["palettes"]  # noqa: RUF001
    assert settings["look"] == "engraved-colour"


def test_a_setting_mol_sketch_lacks_is_said_with_what_was_meant() -> None:
    pytest.importorskip("molsketch")
    for settings, said, hint in (
        ({"style": {"fil": "ink"}}, '"fil" is not a field', "Did you mean fill?"),
        ({"style": {"fill": "crayon"}}, 'fill "crayon" is not one', "watercolour"),
        ({"palette": "Plaid"}, '"Plaid" is not one of mol-sketch', "Tableau 10"),
    ):
        with flexo.Figure("wrong") as figure:
            figure.root.structure("model", DATA / "1a7g.cif", **settings)  # type: ignore[arg-type]
        with pytest.raises(flexo.FlexoError, match=said) as caught:
            compile_figure(figure.spec)
        assert hint in (caught.value.diagnostics[0].hint or "")
