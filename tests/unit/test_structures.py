"""A molecule drawn by mol-sketch, as a component in the figure's colours."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.diagnostics import Severity
from flexo.lint import lint_compilation
from flexo.structures import _png, _without_paper, structure_problem
from flexo.themes import figure_style

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
    from flexo.drawn import _picture

    def forget() -> None:
        for cache in (structures._render, structures._checked, structures._loaded, _picture):
            cache.cache_clear()

    forget()
    monkeypatch.setattr(builtins, "__import__", refuse)
    with flexo.Figure("none") as figure:
        figure.root.structure("m", DATA / "1a7g.cif")
    try:
        # The figure is drawn all the same, the structure a panel saying what it needs.
        svg = compile_figure(figure.spec).document.text
        assert 'id="m.problem"' in svg and "mol-sketch" in svg
        said = structures.structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert said is not None and "needs mol-sketch" in said.message
        assert said.severity is Severity.WARNING
    finally:
        monkeypatch.undo()
        forget()


def test_a_colour_for_a_chain_the_structure_lacks_is_said_with_the_chains_it_has() -> None:
    from flexo.structures import _check_chains, _NoSuchChain

    class Loaded:
        def _info(self) -> dict:
            return {"structure": {"name": "1a7g", "chains": ["E"]}}

    _check_chains(Loaded(), (("E", "#d55e00"), ("SER195", "#000000"), ("SER195.E", "#111111"),
                             ("entity:1", "#222222")))
    with pytest.raises(_NoSuchChain, match='"A" names no chain of 1A7G') as caught:
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
    with pytest.raises(EditError, match="isn't a structure"):
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
        # Said on the structure, which is drawn as a panel saying it; the figure is drawn.
        assert 'id="model.problem"' in compile_figure(figure.spec).document.text
        problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert problem is not None and said in problem.message
        assert hint in (problem.hint or "")


def test_every_choice_the_studio_offers_is_shown_by_a_name_of_its_own() -> None:
    from flexo.structure_style import CHOICES, SECTIONS
    from flexo.studio.figure_parts import catalogue

    fields = [field for section in SECTIONS for field in section["fields"]]
    for field in fields:
        if field["type"] == "choice":
            # What is written stays mol-sketch's value; what is shown is named for each.
            assert list(field["labels"]) == list(CHOICES[field["key"]]) == field["options"]
            assert all(field["labels"].values())
    cartoon = next(field for field in fields if field["key"] == "cartoon_color")
    assert cartoon["labels"] == {
        "ss": "Secondary Structure",
        "carbon": "Carbon",
        "rainbow": "Rainbow",
    }
    editor = catalogue()
    for part in [*editor["parts"].values(), {"fields": editor["group_fields"]}]:
        for field in [*part["fields"], *(c for f in part["fields"] for c in f.get("columns", []))]:
            if field["type"] == "choice":
                assert [str(option) for option in field["options"]] == list(field["labels"])


def test_structures_drawn_at_once_make_one_engine_between_them() -> None:
    """The studio draws on a thread per request: two structures drawn at once once made two
    engines, and a molecule read into the one let go was asked of the other ("unknown input
    in1") until the studio was started again."""

    pytest.importorskip("molsketch")
    import threading

    import molsketch._engine as engine_module

    from flexo import structures
    from flexo.themes import figure_palette

    made: list[str] = []
    real = engine_module.Engine.__init__

    def counted(self, *args, **kwargs) -> None:
        made.append(threading.current_thread().name)
        real(self, *args, **kwargs)

    with flexo.Figure("race") as figure:
        for index in range(3):
            figure.root.structure(f"m{index}", DATA / "1a7g.cif", width=100 + index, height=80)
    style, palette = figure_style(figure.spec), figure_palette(figure.spec)
    was = engine_module._engine
    engine_module.Engine.__init__ = counted  # type: ignore[method-assign]
    engine_module._engine = None
    structures._loaded.cache_clear()
    structures._render.cache_clear()
    start = threading.Barrier(3)
    drawn: dict[str, object] = {}

    def draw(node) -> None:
        start.wait()
        try:
            drawn[node.id] = structures.structure_png(node, style, palette, 100.0, 80.0)
        except Exception as error:  # what the race broke, said by the assertion below
            drawn[node.id] = error

    try:
        threads = [threading.Thread(target=draw, args=(node,)) for node in figure.spec.nodes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(made) == 1
        assert all(isinstance(png, bytes) and png.startswith(b"\x89PNG") for png in drawn.values())
    finally:
        engine_module.Engine.__init__ = real  # type: ignore[method-assign]
        ours = engine_module._engine
        engine_module._engine = was if was is not None else ours
        if was is not None and ours is not None and ours is not was:
            ours.v8.close()
        structures._loaded.cache_clear()
        structures._render.cache_clear()


def test_a_molecule_kept_from_an_engine_let_go_is_read_again() -> None:
    pytest.importorskip("molsketch")
    import molsketch._engine as engine_module

    from flexo import structures
    from flexo.themes import figure_palette

    with flexo.Figure("stale") as figure:
        figure.root.structure("m", DATA / "1a7g.cif", width=90, height=70)
    node = figure.spec.nodes[0]
    style, palette = figure_style(figure.spec), figure_palette(figure.spec)
    structures._render.cache_clear()
    structures.structure_png(node, style, palette, 90.0, 70.0)
    # Another engine in the first one's place: the molecule kept is unknown to it.
    old = engine_module.engine()
    engine_module._engine = engine_module.Engine()
    old.v8.close()
    structures._render.cache_clear()
    png = structures.structure_png(node, style, palette, 90.0, 70.0)
    assert png.startswith(b"\x89PNG")


def test_a_structure_that_cant_be_downloaded_is_a_panel_saying_so(monkeypatch) -> None:
    from flexo import structures
    from flexo.drawn import _picture

    def offline(source: str, stamp: float):
        raise ConnectionError(f"could not download https://files.rcsb.org/download/{source}.cif")

    monkeypatch.setattr(structures, "_loaded", offline)
    structures._checked.cache_clear()
    _picture.cache_clear()
    with flexo.Figure("offline") as figure:
        row = figure.root.row("row", gap=20)
        row.structure("model", "9ZZZ", label="Ubiquitin", width=160, height=120)
        row.block("next", label="Next step")
        figure.connect("row.model", "row.next")
    try:
        svg = compile_figure(figure.spec).document.text
        assert "Couldn't download 9ZZZ" in svg and 'id="row.next"' in svg
        assert 'id="row.model.molecule"' not in svg
        problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert problem is not None and problem.code == "structure.fetch"
        assert problem.entity_id == "row.model" and problem.severity is Severity.WARNING
    finally:
        monkeypatch.undo()
        structures._checked.cache_clear()
        _picture.cache_clear()


def test_a_colour_row_starts_on_a_chain_the_structure_has() -> None:
    """A new row of a structure's colours once said chain A whatever the molecule's chains:
    for one without an A, the whole slide was an error. It starts on a chain the molecule has
    (the studio offers them), and a row naming a chain it lacks is a warning on that row,
    the molecule drawn without it."""

    pytest.importorskip("molsketch")
    from flexo.studio.figure_kind import FigureKind
    from flexo.studio.figure_parts import catalogue

    parts = catalogue({"themes": [], "palettes": {}, "fonts": [], "components": []})["parts"]
    colours = next(f for f in parts["structure"]["fields"] if f["key"] == "properties.colors")
    assert colours["row"]["group"] == "@chain"
    assert [column["type"] for column in colours["columns"]] == ["chain", "colour"]
    text = (
        "figure: {id: coloured}\n"
        "nodes:\n"
        "  - id: model\n    kind: structure\n"
        f"    properties: {{source: {DATA / '1a7g.cif'}, colors: [{{group: A, color: '#e69f00'}},"
        " {group: E, color: '#0072b2'}, {group: E}]}\n"
    )
    settings = FigureKind().act(
        {"text": text}, {"do": "structure-settings", "id": "model"}, DATA
    )["settings"]
    assert settings["chains"] == ["E"]
    drawing = FigureKind().draw({"text": text}, DATA)
    assert drawing.pages and 'id="model.molecule"' in drawing.pages[0].svg
    warned = [m for m in drawing.messages if m.where == "model"]
    assert warned and warned[0].severity == "warning" and '"A" names no chain' in warned[0].text


def test_a_structure_mol_sketch_fails_to_draw_leaves_the_figure_drawn(monkeypatch) -> None:
    pytest.importorskip("molsketch")
    from flexo import structures

    def broken(ask, aspect):
        raise RuntimeError("<anonymous>:48: ReferenceError: cm is not defined")

    monkeypatch.setattr(structures, "_render", broken)
    with flexo.Figure("broken") as figure:
        row = figure.root.row("row", gap=20)
        row.structure("model", DATA / "1a7g.cif", width=100, height=80, style={"fill": "chalk"})
        row.block("next", label="Next")
    try:
        svg = compile_figure(figure.spec).document.text
        assert 'id="row.model.molecule"' in svg and 'id="row.next"' in svg
        problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert problem is not None and problem.code == "structure.draw"
        assert "(cm is not defined)" in problem.message and "anonymous" not in problem.message
    finally:
        monkeypatch.undo()
        structures._failed.clear()
