"""A molecule drawn by mol-sketch, as a component in the figure's colours."""

from __future__ import annotations

import base64
import json
import re
import shutil
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


def _flat_figure(style: str = "paper") -> str:
    with flexo.Figure("flat", style=style) as figure:
        row = figure.root.row("row", gap=20)
        row.structure(
            "model", DATA / "1a7g.cif", label="E2", look="flat", width=120, height=90,
            colors={"E": "Viral"}, sticks="(sidechain or name CA) and resi 300-305",
        )
        row.block("tag", label="E2 protein", tone="Viral")
    return compile_figure(figure.spec).document.text


def _molecule(svg: str):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg)
    return next(item for item in root.iter() if item.get("id") == "row.model.molecule")


def test_a_flat_structure_is_shapes_painted_by_the_figures_roles() -> None:
    pytest.importorskip("molsketch")
    from flexo.colour import srgb_mix
    from flexo.themes import resolve_palette, with_tone_roles

    svg = _flat_figure()
    group = _molecule(svg)
    assert group.get("data-flexo-drawn") == "mol-sketch"
    tags = [item.tag.rsplit("}", 1)[-1] for item in group.iter()]
    assert "svg" in tags and "image" not in tags  # shapes, not a picture
    # The chain in its tone's fill, its far side a shade of it, its lines in ink.
    palette = with_tone_roles(resolve_palette("paper"))
    fills = {
        (item.get("data-flexo-fill"), item.get("data-flexo-fill-shade"), item.get("fill"))
        for item in group.iter() if item.get("data-flexo-fill")
    }
    tone = next(role for role, _, _ in fills if role.startswith("tone-") and role.endswith("-fill"))
    assert (tone, None, palette.get(tone)) in fills
    shaded = {(colour, shade) for role, shade, colour in fills if role == tone and shade}
    assert shaded and all(
        colour == srgb_mix(palette.get(tone), palette.get("ink"), float(shade))
        for colour, shade in shaded
    )
    assert any(item.get("data-flexo-stroke") == "ink" for item in group.iter())


def test_a_flat_structure_is_recoloured_with_the_figure() -> None:
    pytest.importorskip("molsketch")
    from flexo.colour import srgb_mix
    from flexo.theme import retheme_svg
    from flexo.themes import resolve_palette, with_tone_roles

    dark = with_tone_roles(resolve_palette("dark"))
    group = _molecule(retheme_svg(_flat_figure(), dark))
    for item in group.iter():
        for part in ("fill", "stroke"):
            role = item.get(f"data-flexo-{part}")
            if not role:
                continue
            shade = item.get(f"data-flexo-{part}-shade")
            wanted = dark.get(role)
            if shade:
                wanted = srgb_mix(wanted, dark.get("ink"), float(shade))
            assert item.get(part) == wanted


def test_a_flat_structure_keeps_its_line_in_a_sketched_theme() -> None:
    pytest.importorskip("molsketch")
    plain, sketched = _molecule(_flat_figure("paper")), _molecule(_flat_figure("sketch"))
    shapes = lambda group: sum(1 for item in group.iter() if item.tag.endswith("path"))  # noqa: E731
    assert shapes(sketched) == shapes(plain)  # each shape as mol-sketch drew it


def test_a_flat_structure_is_vectors_in_the_pdf() -> None:
    pytest.importorskip("molsketch")
    from flexo.pdf import pdf_bytes

    data = pdf_bytes(_flat_figure())
    assert b"/Subtype /Image" not in data  # no picture: the molecule is paths


def test_the_settings_of_a_structure_coloured_by_a_tone_are_shown(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind
    from flexo.themes import resolve_palette, with_tone_roles

    with flexo.Figure("toned", style="paper") as figure:
        row = figure.root.row("row", gap=20)
        row.structure(
            "model", DATA / "1a7g.cif", look="flat", colors={"E": "Viral"}, scheme="figure"
        )
        row.block("tag", label="E2 protein", tone="Viral")
    action = {"do": "structure-settings", "id": "row.model"}
    settings = FigureKind().act({"text": dump_figure(figure.spec)}, action, tmp_path)["settings"]
    assert settings["look"] == "flat"
    # Drawn in the figure's colours: its helices in the accent's fill.
    assert settings["style"]["palette.helix"] == with_tone_roles(resolve_palette("paper")).get(
        "accent-fill"
    )


def test_a_flat_structure_is_in_the_looks_own_colours_unless_it_asks_for_the_figures(
    tmp_path: Path,
) -> None:
    """mol-sketch's Flat: coral helices, amber strands, near-white loops, teal hydrogen
    bonds -- left as they are, the ink and a chain's own colour apart. ``scheme: figure``
    paints it in the figure's tones; a scheme it lacks is said."""

    ms = pytest.importorskip("molsketch")
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind

    flat = ms.load(str(DATA / "1a7g.cif")).look("flat").style
    found = {}
    for scheme in (None, "figure"):
        with flexo.Figure("flat", style="paper") as figure:
            figure.root.structure("model", DATA / "1a7g.cif", look="flat", scheme=scheme)
        action = {"do": "structure-settings", "id": "model"}
        text = dump_figure(figure.spec)
        found[scheme] = FigureKind().act({"text": text}, action, tmp_path)["settings"]["style"]
    for key in ("helix", "sheet", "loop", "hbond"):
        assert found[None][f"palette.{key}"] == flat["palette"][key]
    assert found["figure"]["palette.helix"] != flat["palette"]["helix"]
    with flexo.Figure("odd") as figure:
        figure.root.structure("model", DATA / "1a7g.cif", look="flat", scheme="pastel")
    problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
    assert problem is not None and problem.code == "structure.scheme"
    assert "look, figure" in (problem.hint or "")


def _scene(name: str = "pi_star.json") -> Path:
    return DATA / name


def test_a_scene_is_drawn_at_the_end_of_its_step_with_its_arrows_in() -> None:
    """A mol-sketch scene (a reaction, in steps) is a structure's source: drawn where its
    step's hold ends -- its curly arrows grow over the end of the hold, and at its start are
    not there yet -- and its next step, the product, at the end of that one's."""

    ms = pytest.importorskip("molsketch")
    from flexo.structures import _ask, _frame, _loaded

    with flexo.Figure("steps") as figure:
        row = figure.root.row("row", gap=20)
        for step in (1, 2):
            row.structure(f"s{step}", _scene(), label=f"Step {step}", look="textbook", step=step)
    style = figure_style(figure.spec)
    scene = ms.load(str(_scene()))
    starts = scene.frames("keyframes")
    holds = [step.get("hold", 24) for step in scene.scene()["keyframes"]]
    for index, node in enumerate(figure.spec.nodes):
        ask = _ask(node, style, flexo.themes.figure_palette(figure.spec))
        assert _frame(_loaded(ask.source, ask.stamp), ask) == starts[index] + holds[index] - 2
    compiled = compile_figure(figure.spec)
    assert not [d for d in lint_compilation(compiled).diagnostics if d.severity is Severity.ERROR]
    assert all(structure_problem(node, style) is None for node in figure.spec.nodes)
    # Drawn there, its arrows are in it: the first step's picture is not the one at its start.
    at = {}
    for frame in (0, starts[0] + holds[0] - 2):
        at[frame] = scene.copy().look("textbook").render((400, 300), frame=frame).png()
    assert at[0] != at[starts[0] + holds[0] - 2]


def test_a_step_a_scene_lacks_is_said_with_the_steps_it_has() -> None:
    pytest.importorskip("molsketch")
    for step, said in ((3, "This scene has 2 steps: step 3 is not one of them."),
                       (1.5, "A scene's step is a whole number")):
        with flexo.Figure("steps") as figure:
            figure.root.structure("model", _scene(), look="textbook", step=step)
        problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert problem is not None and problem.code == "structure.step"
        assert said in problem.message
        assert 'id="model.problem"' in compile_figure(figure.spec).document.text


def test_a_scene_is_named_for_itself_and_only_a_scene_is_one(tmp_path: Path) -> None:
    from flexo.structures import is_scene, structure_caption

    assert is_scene(_scene())
    assert structure_caption(_scene()) == "π* attack (carbonyl addition)"
    figure = tmp_path / "figure.json"
    figure.write_text('{"figure": {"id": "f"}, "nodes": []}', encoding="utf-8")
    assert not is_scene(figure) and not is_scene(DATA / "1a7g.cif")


def test_a_scenes_orbitals_and_measures_take_colours_of_ones_own(tmp_path: Path) -> None:
    """Colours mol-sketch leaves out until given -- a scene's filled and empty orbitals, its
    measures and their windows, hydrogen bonds -- are settings a structure may set."""

    pytest.importorskip("molsketch")
    with flexo.Figure("coloured") as figure:
        figure.root.structure(
            "model", _scene(), look="textbook",
            style={"palette": {"filled": "#1a9e3a", "empty": "#7a3db8", "window": "#dddddd"},
                   "lone_pair_style": "lobes"},
        )
    assert structure_problem(figure.spec.nodes[0], figure_style(figure.spec)) is None
    assert 'id="model.problem"' not in compile_figure(figure.spec).document.text


def test_shades_are_mixed_as_mol_sketch_mixes_them() -> None:
    from flexo.colour import srgb_mix

    # Half of one step rounds up, as JavaScript's Math.round does (not to even).
    assert srgb_mix("#000000", "#020202", 0.25) == "#010101"
    assert srgb_mix("#e8796b", "#000000", 0.165) == "#c26559"


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
    pytest.importorskip("molsketch")

    def problem(colors: dict[str, str]):
        with flexo.Figure("odd") as figure:
            figure.root.structure("model", DATA / "1a7g.cif", colors=colors)
        return structure_problem(figure.spec.nodes[0], figure_style(figure.spec))

    assert problem({"E": "#d55e00", "ALA291": "#000000", "THR292.E": "#111111",
                    "entity:1": "#222222", "SO41": "#333333"}) is None
    said = problem({"A": "#d55e00"})
    assert said is not None and said.message.startswith('"A" names no chain of 1A7G')
    assert "Its chains are E" in (said.hint or "")


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
    assert view["camera"]["zoom"] == 1 and view["camera"]["pan_x"] == 0
    points = [point for chain in view["chains"] for point in chain]
    assert len(points) > 50 and all(len(point) == 3 for point in points)
    # Turned about the middle of what it draws, as mol-sketch turns it: the fit's outermost
    # points hold the box round all of it.
    fit = view["fit"]
    assert 6 <= len(fit) < 300
    for k in range(3):
        assert abs((max(p[k] for p in fit) + min(p[k] for p in fit)) / 2 - view["centre"][k]) < 0.01
    assert view["frame"] == {"long_side": 1200, "foot": 0.0, "head": 0.0}
    with pytest.raises(EditError, match="isn't a structure"):
        FigureKind().act({"text": text}, {"do": "structure-view", "id": "tag"}, tmp_path)


def test_a_site_zoomed_into_turns_as_it_is_framed(tmp_path: Path) -> None:
    """Dragged round, a molecule zoomed into its active site shows the site where the drawing
    has it -- its atoms, as sticks, framed and zoomed as mol-sketch frames them -- not the
    whole protein fitted to the box."""

    pytest.importorskip("molsketch")
    from flexo.studio.figure_kind import FigureKind

    source = DATA / "1a7g.cif"
    text = (
        "figure: {id: site}\n"
        "nodes:\n"
        "  - id: model\n    kind: structure\n"
        f"    properties: {{source: {source}, look: flat, site: resi 327+335, zoom: 3, "
        "pan_x: 0.1, pan_y: -0.05}\n"
    )
    view = FigureKind().act({"text": text}, {"do": "structure-view", "id": "model"}, tmp_path)[
        "view"
    ]
    assert view["camera"]["zoom"] == 3
    assert (view["camera"]["pan_x"], view["camera"]["pan_y"]) == (0.1, -0.05)
    site = [atom for atom in view["atoms"] if atom[4]]
    # The two histidines' side chains, from their alpha carbons (the ribbon has the rest of
    # their backbone), with their bonds.
    assert len(site) == 2 * 7 and {atom[3] for atom in site} == {"C", "N"}
    assert view["bonds"] and all(
        0 <= a < len(view["atoms"]) and 0 <= b < len(view["atoms"]) for a, b in view["bonds"]
    )
    assert view["sticks"]["radius"] > 0 and view["sticks"]["site"] >= 1


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


def test_waters_and_lone_ions_are_left_out_unless_asked_for(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.studio.figure_kind import FigureKind

    # A few residues of a chain, a calcium beside them and a water: the ion and the water
    # would float free of the ribbon as dots.
    residues = []
    for index, name in enumerate(("ALA", "GLY", "SER", "LEU", "VAL", "ALA")):
        places = (("N", (0.0, 0.0)), ("CA", (1.2, 0.8)), ("C", (2.4, 0.0)), ("O", (2.4, -1.2)))
        for atom, (dx, dy) in places:
            serial = len(residues) + 1
            x, y, z = 3.6 * index + dx, dy, 0.0
            residues.append(
                f"ATOM  {serial:5d}  {atom:<3} {name} A{index + 1:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 10.00           {atom[0]}  "
            )
    residues += [
        "HETATM  100 CA    CA A 101       6.000   5.000   0.000  1.00 10.00          CA  ",
        "HETATM  101  O   HOH A 201       9.000  -5.000   0.000  1.00 10.00           O  ",
    ]
    source = tmp_path / "bound.pdb"
    source.write_text("\n".join([*residues, "END", ""]), encoding="utf-8")

    def sticks(extra: str = "") -> str:
        text = (
            "figure: {id: ions}\n"
            "nodes:\n"
            "  - id: model\n    kind: structure\n"
            f"    properties: {{source: {source}{extra}}}\n"
        )
        settings = FigureKind().act(
            {"text": text}, {"do": "structure-settings", "id": "model"}, tmp_path
        )["settings"]
        return settings["style"]["reps.sticks"]

    hidden = sticks()
    assert "not water" in hidden and "not resn CA" in hidden
    # Asked for, they are drawn where they lie.
    shown = sticks(", solvent: true")
    assert "or water" in shown and "resn CA" not in shown


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


def test_a_numbers_note_never_says_its_unit_again() -> None:
    """A field's unit is in it ("30°", "2 px"): its note says only what the unit does not."""

    from flexo.structure_style import SECTIONS

    words = {"°": "degree", "px": "pixel"}
    for field in (field for section in SECTIONS for field in section["fields"]):
        if field.get("unit") in words:
            assert words[field["unit"]] not in field["hint"].lower(), field["label"]


def test_every_field_of_mol_sketchs_style_is_offered_or_said_why_not() -> None:
    """The studio's panes offer every field of mol-sketch's style -- once each -- but those
    it says why it leaves out: the figure's own (its paper, set on every structure it draws),
    those the structure's own fields set, and those that change nothing a figure draws. A
    field mol-sketch adds is offered, or said why not, before this passes."""

    ms = pytest.importorskip("molsketch")
    from flexo.structure_style import NOT_OFFERED, PANES, SECTIONS, THE_FIGURES
    from flexo.structures import UNSET, _fields

    def walk(value: dict, prefix: str = "") -> set[str]:
        names: set[str] = set()
        for key, item in value.items():
            names |= walk(item, f"{prefix}{key}.") if isinstance(item, dict) else {prefix + key}
        return names

    every = walk(ms.default_style()) | UNSET
    assert every == _fields()
    offered = [field["key"] for section in SECTIONS for field in section["fields"]]
    assert len(offered) == len(set(offered)), "a setting offered twice"
    assert not set(offered) - every, "a setting mol-sketch lacks"
    assert not set(offered) & set(NOT_OFFERED), "a setting offered and left out"
    assert not set(NOT_OFFERED) - every, "a setting left out that mol-sketch lacks"
    missing = every - set(offered) - set(NOT_OFFERED)
    assert not missing, f"mol-sketch's {sorted(missing)} neither offered nor said why not"
    assert set(THE_FIGURES) <= set(NOT_OFFERED) and all(NOT_OFFERED.values())
    # Each pane is of sections, and every section of the panes is in one.
    assert [pane["key"] for pane in PANES] == [
        "look", "molecule", "scene", "site", "map", "labels", "camera"
    ]
    assert {section["pane"] for section in SECTIONS} == {pane["key"] for pane in PANES}


def test_a_structures_own_fields_are_each_in_one_of_its_panes() -> None:
    """A structure's panel is its words (and where they stand), then its panes: each of its
    own fields (its file, what it draws, its site, its map, its view, its frame) is in one of
    them, where it belongs."""

    from flexo.structure_style import PANES
    from flexo.studio.figure_parts import catalogue

    part = catalogue({"themes": [], "palettes": {}, "fonts": [], "components": []})["parts"][
        "structure"
    ]
    placed = [
        field["key"]
        for pane in PANES
        for section in pane["sections"]
        for field in section["fields"]
        if field.get("own")
    ]
    fields = [field["key"] for field in part["fields"] if field["type"] != "molsketch"]
    assert sorted(placed) == sorted(
        key for key in fields if key not in {"label", "properties.title_side"}
    )
    assert not [field for field in part["fields"] if field.get("more")]
    # What is drawn as a cartoon, sticks or a surface, a click away: the look's, none, or one
    # of those most reached for.
    sticks = next(field for field in part["fields"] if field["key"] == "properties.sticks")
    assert [chip["value"] for chip in sticks["chips"]][:3] == [None, "none", "hetatm and not water"]


def test_the_studio_is_told_a_scenes_steps_and_what_a_setting_is_without_its_own(
    tmp_path: Path,
) -> None:
    """A scene's steps, by the names it gives them, for the studio to choose one by; and each
    setting as the look (and the figure) give it, beside what the structure is drawn with --
    what a setting goes back to when it is no longer the structure's own."""

    pytest.importorskip("molsketch")
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind

    def settings(**options: object) -> dict:
        with flexo.Figure("asked") as figure:
            figure.root.structure("model", _scene(), look="textbook", **options)  # type: ignore[arg-type]
        action = {"do": "structure-settings", "id": "model"}
        return FigureKind().act({"text": dump_figure(figure.spec)}, action, tmp_path)["settings"]

    plain = settings()
    assert plain["steps"] == ["\u03c0* attack: precursor", "Tetrahedral alkoxide"]
    assert plain["inherited"] == plain["style"]
    own = settings(style={"show": {"orbitals": False}, "line": {"width": 3}}, step=3)
    # (A step it lacks is said, and its steps still named.)
    assert own["steps"] == plain["steps"] and "problem" in own
    own = settings(style={"show": {"orbitals": False}, "line": {"width": 3}})
    assert own["style"]["show.orbitals"] is False and own["style"]["line.width"] == 3
    assert own["inherited"]["show.orbitals"] is True
    assert own["inherited"]["line.width"] == plain["style"]["line.width"] != 3


def test_none_drawn_as_sticks_is_meant_and_not_said_to_select_nothing(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind

    with flexo.Figure("bare") as figure:
        figure.root.structure("model", DATA / "1a7g.cif", sticks="none", surface="chain Q")
    action = {"do": "structure-settings", "id": "model"}
    found = FigureKind().act({"text": dump_figure(figure.spec)}, action, tmp_path)["settings"]
    assert found["style"]["reps.sticks"].startswith("none")
    assert list(found["selections"]) == ["properties.surface"]


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
    # (Without mol-sketch the panel says that first: nothing is downloaded to draw.)
    pytest.importorskip("molsketch")
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


def test_a_structure_is_named_for_what_its_file_holds_and_a_long_name_wraps(tmp_path: Path) -> None:
    from flexo.structures import structure_caption

    # Its molecule, as a person writes it (the PDB's capitals kept for acronyms), and its ID.
    assert structure_caption(DATA / "1a7g.cif") == "E2 DNA-binding domain (1A7G)"
    entry = tmp_path / "capsid.pdb"
    entry.write_text(
        f"{'HEADER    VIRAL PROTEIN':<62}1A8O\n"
        "COMPND    MOL_ID: 1;\nCOMPND   2 MOLECULE: HIV CAPSID;\n"
    )
    assert structure_caption(entry) == "HIV capsid (1A8O)"
    # A complex with DNA is named for its protein, never "DNA".
    entry.write_text(
        f"{'HEADER    TRANSCRIPTION/DNA':<62}1LCD\nCOMPND   2 MOLECULE: DNA (5'-D(*TP*GP)-3');\n"
        "COMPND   5 MOLECULE: LAC REPRESSOR;\n"
    )
    assert structure_caption(entry) == "Lac repressor (1LCD)"
    # A title in capitals is set in sentence case, its acronyms kept.
    entry.write_text(
        f"{'HEADER    TRANSCRIPTION/DNA':<62}1LCD\n"
        "TITLE     LAC REPRESSOR HIV GFP II DNA\n"
    )
    assert structure_caption(entry) == "Lac repressor HIV GFP II DNA (1LCD)"
    # A long title is cut before the phrase the cut falls in: no "during" left hanging.
    entry.write_text(
        f"{'HEADER    HYDROLASE':<62}1GBT\n"
        "TITLE     ACYL-ENZYME INTERMEDIATE DURING THE HYDROLYSIS OF A SUBSTRATE\n"
    )
    assert structure_caption(entry) == "Acyl-enzyme intermediate (1GBT)"
    assert structure_caption(tmp_path / "none.cif") is None
    # A name wider than its panel is set on two lines over it, not across its edges.
    with flexo.Figure("named") as figure:
        figure.root.row("row").structure(
            "model", tmp_path / "missing.cif", width=120, height=90,
            label="β-barrel fold (E2 DNA-binding domain, 1A7G)",
        )
    compiled = compile_figure(figure.spec)
    codes = [item.code for item in lint_compilation(compiled).diagnostics]
    assert "layout.text.overflow" not in codes
    assert len(compiled.routed.fitted.node("row.model").measured.label.lines) == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_editor_frames_a_turning_molecule_as_mol_sketch_does() -> None:
    """The page's projector is mol-sketch's (computeFit, makeProjector): the box round what is
    drawn, turned, fitted to the render -- 90% of its width, its height less 24 pixels, an
    atom's room kept round it -- then zoomed and panned, shrunk to the canvas."""

    from test_pages import _studio

    corners = [[x, y, z] for x in (-10, 10) for y in (-5, 5) for z in (-2, 2)]
    view = {
        "centre": [0, 0, 0],
        "fit": corners,
        "frame": {"long_side": 1200, "foot": 0.0, "head": 0.0},
        "camera": {"zoom": 1, "pan_x": 0, "pan_y": 0, "fov": 0},
    }

    def placed(points, camera=None, turn=(0, 0, 0), size=(1200, 600)):
        shown = {**view, "camera": {**view["camera"], **(camera or {})}}
        angles = dict(zip(("yaw", "pitch", "roll"), turn, strict=True))
        code = (
            f"(() => {{ const p = parts.moleculeProjector({json.dumps(shown)}, "
            f"{json.dumps(angles)}, {size[0]}, {size[1]}); "
            f"return {{ per: p.perAngstrom, at: {json.dumps(points)}.map((q) => p.at(q)) }}; }})()"
        )
        return _studio(code)

    base = min(1200 * 0.9 / (20 + 2.6), (600 - 24) / (10 + 2.4))
    seen = placed([[0, 0, 0], [10, 0, 0], [0, 5, 0]])
    assert seen["per"] == pytest.approx(base)
    (x0, y0, *_), (x1, y1, *_), (x2, y2, *_) = seen["at"]
    assert (x0, y0) == pytest.approx((600, 300))
    assert (x1 - x0, y1 - y0) == pytest.approx((10 * base, 0))
    assert (x2 - x0, y2 - y0) == pytest.approx((0, -5 * base))  # y up, the page's y down
    # Zoomed and panned as mol-sketch does: about the middle, then moved by shares of it.
    moved = {"zoom": 3, "pan_x": 0.1, "pan_y": -0.05}
    (x0, y0, *_), (x1, *_) = placed([[0, 0, 0], [10, 0, 0]], moved)["at"]
    assert (x0, y0) == pytest.approx((600 + 120, 300 - 30))
    assert x1 - x0 == pytest.approx(30 * base)
    # A canvas half the size: everything half as far.
    (x0, y0, *_), (x1, *_) = placed([[0, 0, 0], [10, 0, 0]], size=(600, 300))["at"]
    assert (x0, y0, x1 - x0) == pytest.approx((300, 150, 5 * base))
    # Turned a quarter about y: x goes into the page, z comes to the right -- and the box
    # round it, turned, is framed again.
    turned = placed([[0, 0, 0], [10, 0, 0], [0, 0, 2]], turn=(90, 0, 0))["at"]
    (x0, *_), (x1, *_), (x2, *_) = turned
    assert x1 == pytest.approx(x0, abs=1e-6) and x2 > x0


def test_a_row_of_structures_too_wide_for_its_page_draws_them_smaller_to_fit() -> None:
    """A diffusion run's five frames at their usual size are wider than a double column: they
    are drawn smaller, alike, until the row fits its page -- with no warning that it grew. A
    structure given a size of its own keeps it."""

    def figure(sized: bool = False):
        with flexo.Figure("run", width="double-column") as made:
            row = made.root.row("row")
            for k in range(5):
                own = {"width": 150, "height": 110} if sized and k == 0 else {}
                row.structure(f"t{k}", DATA / "1a7g.cif", label=f"t = {k}", look="flat",
                              frame="run", **own)
        return made.spec

    compiled = compile_figure(figure())
    said = [d.code for d in compiled.measured.diagnostics]
    assert "layout.width.grown" not in said
    widths = {round(compiled.routed.fitted.node(f"row.t{k}").bounds.width, 1) for k in range(5)}
    assert len(widths) == 1 and widths.pop() < 20.0 * flexo.drawn.units(figure_style(figure())).u
    # One given a size keeps it; the others are drawn smaller.
    sized = compile_figure(figure(sized=True))
    assert round(sized.routed.fitted.node("row.t0").bounds.width) >= 150
    assert sized.routed.fitted.node("row.t1").bounds.width < 150
