"""Themes and palettes of one's own, written as files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import flexo
from flexo import theme_files
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.lint import lint_compilation
from flexo.themes import THEMES, theme

LAB = """
theme:
  name: lab-test
  base: paper
  description: A test lab.
  font: Liberation Sans
  type: {size: 7.5pt, label_weight: 400}
  palette: ["#1d4e89", "#f26419", "#2a9d8f"]
  page: {ink: "#1b1b1b"}
  tones: {rule: tinted, fill_lightness: 0.92}
  style: {corner_radius: 1.5pt, arrow_shape: latex, widths: {single-column: 3.5in}}
  conventions: {branch: dot}
palettes:
  Lab warm test: ["#9b2226", "#ca6702", "#ee9b00"]
"""


def _figure(**options: object) -> Figure:
    with Figure("t", **options) as figure:
        x = figure.root.text("x", "x")
        a = figure.root.block("a", label="Encoder", input=x, tone="encoder")
        figure.root.block("b", label="Head", input=a, tone="head")
    return figure


def test_a_theme_file_is_a_theme_by_its_path_and_by_its_name(tmp_path: Path) -> None:
    path = tmp_path / "lab.yaml"
    path.write_text(LAB)
    compiled = compile_figure(_figure(theme=str(path)).spec)
    assert not lint_compilation(compiled).diagnostics
    lab = theme("lab-test")
    assert lab.style.typography.family == "Liberation Sans"
    assert lab.style.typography.size.points == pytest.approx(7.5)
    assert lab.style.corner_radius.points == pytest.approx(1.5)
    assert lab.style.arrow_shape == "latex"
    assert lab.style.conventions.branch == "dot"
    assert dict(lab.style.widths)["single-column"].points == pytest.approx(252.0)
    assert lab.page.ink == "#1b1b1b" and lab.palette[0] == "#1d4e89"
    assert lab.tones.settings["fill_lightness"] == 0.92  # type: ignore[attr-defined]
    # The file's palettes came with it.
    assert not lint_compilation(
        compile_figure(_figure(theme="lab-test", palette="Lab warm test").spec)
    ).diagnostics


def test_every_theme_writes_out_as_a_file_that_reads_back_the_same() -> None:
    for name in ("paper", "sketch", "tikz"):
        document = yaml.safe_load(flexo.dump_theme(name))
        document["theme"]["name"] = f"{name}-copy"
        copy = theme(flexo.register_theme(document))
        original = THEMES[name]
        written = yaml.safe_load(flexo.dump_theme(copy.name))["theme"]
        assert written | {"name": name} == yaml.safe_load(flexo.dump_theme(name))["theme"]
        assert copy.style.corner_radius == original.style.corner_radius
        assert copy.page == original.page and copy.palette == original.palette


def test_a_mistake_in_a_theme_names_the_setting_and_what_it_may_be() -> None:
    with pytest.raises(FlexoError, match="corner_radiuss"):
        flexo.register_theme({"theme": {"name": "bad", "style": {"corner_radiuss": "2pt"}}})
    with pytest.raises(FlexoError, match="Use one of"):
        flexo.register_theme({"theme": {"name": "bad", "style": {"arrow_shape": "fishhook"}}})
    with pytest.raises(FlexoError, match="Unknown tone rule"):
        flexo.register_theme({"theme": {"name": "bad", "tones": {"rule": "rainbow"}}})


def test_palettes_register_by_name_or_from_a_file(tmp_path: Path) -> None:
    flexo.register_palette("Test Pair", ["#112233", "#445566"])
    assert not lint_compilation(compile_figure(_figure(palette="test pair").spec)).diagnostics
    path = tmp_path / "colours.yaml"
    path.write_text("colours: ['#aa0000', '#00aa00', '#0000aa']\n")
    assert flexo.register_palette(path) == ("colours",)
    assert not lint_compilation(compile_figure(_figure(palette=str(path)).spec)).diagnostics


def test_a_theme_path_in_a_figure_file_is_found_beside_it(tmp_path: Path) -> None:
    (tmp_path / "lab.yaml").write_text(LAB)
    (tmp_path / "figure.yaml").write_text(
        "figure: {id: f, theme: lab.yaml}\nnodes: [{id: a, label: A}, {id: b, label: B}]\n"
        "edges: [{from: a, to: b}]\n"
    )
    spec = flexo.load_figure(tmp_path / "figure.yaml")
    assert theme(spec.style).name.split("@")[0] == "lab-test"
    assert theme(spec.style).description == "A test lab."


def test_a_theme_file_never_takes_the_place_of_flexo_s_own_or_another_file_s(
    tmp_path: Path,
) -> None:
    from flexo.themes import resolve_palette

    before = resolve_palette("paper").get("canvas")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "night.yaml").write_text(
        "theme: {name: paper, base: dark, palette: ['#ff0000']}\n"
    )
    (tmp_path / "b" / "night.yaml").write_text(
        "theme: {name: paper, base: paper, palette: ['#0000ff']}\n"
    )
    first = flexo.register_theme(tmp_path / "a" / "night.yaml")
    second = flexo.register_theme(tmp_path / "b" / "night.yaml")
    assert first != second and "paper" not in {first, second}
    assert resolve_palette("paper").get("canvas") == before
    assert resolve_palette(first).get("canvas") != before
    assert flexo.register_theme(tmp_path / "a" / "night.yaml") == first


def test_themes_on_the_theme_path_load_themselves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lab.yaml").write_text(LAB.replace("lab-test", "lab-from-path"))
    monkeypatch.setenv("FLEXO_THEME_PATH", str(tmp_path))
    monkeypatch.setattr(theme_files, "_ENVIRONMENT_LOADED", False)
    THEMES.pop("lab-from-path", None)
    assert theme("lab-from-path").description == "A test lab."


def test_a_setting_a_theme_does_not_have_is_refused_with_a_suggestion() -> None:
    with pytest.raises(flexo.FlexoError, match='no setting "extends"') as caught:
        flexo.register_theme({"name": "wrong", "extends": "tikz"})
    assert 'Did you mean "base"' in str(caught.value.diagnostics[0].hint)
    with pytest.raises(flexo.FlexoError, match='"type" has no setting "sise"'):
        flexo.register_theme({"name": "wrong", "type": {"sise": "9pt"}})


def test_a_theme_file_brings_the_fonts_it_is_set_in(tmp_path: Path) -> None:
    from fontTools.ttLib import TTFont

    from flexo.fonts import bundled_font_directory, family_faces

    # A face Flexo does not ship: a bundled one under a name of its own.
    face = TTFont(bundled_font_directory() / "Kalam-Regular.ttf")
    for record in face["name"].names:
        if record.nameID in (1, 4, 16):
            record.string = "Theme Hand Test"
        elif record.nameID == 6:
            record.string = "ThemeHandTest-Regular"
    (tmp_path / "fonts").mkdir()
    face.save(tmp_path / "fonts" / "ThemeHandTest-Regular.ttf")
    (tmp_path / "hand.yaml").write_text(
        "theme: {name: hand-test, base: paper, font: Theme Hand Test}\nfonts: [fonts/]\n"
    )
    assert flexo.register_theme(tmp_path / "hand.yaml") == "hand-test"
    assert family_faces("Theme Hand Test")
    compiled = compile_figure(_figure(theme="hand-test").spec)
    assert "Theme Hand Test" in compiled.document.text

    (tmp_path / "missing.yaml").write_text(
        "theme: {name: missing-font-test, base: paper}\nfonts: [nowhere.ttf]\n"
    )
    with pytest.raises(FlexoError, match=r"nowhere\.ttf"):
        flexo.register_theme(tmp_path / "missing.yaml")


def test_a_theme_files_palette_keeps_the_order_it_was_written_in(tmp_path: Path) -> None:
    from flexo.themes import resolve_palette

    # Left to itself Flexo would lead with the colour that stands out most (the blue);
    # a theme's author chose to lead with the pale red.
    (tmp_path / "ordered.yaml").write_text(
        "theme: {name: ordered-test, base: paper, palette: ['#e8a0a0', '#1d4e89', '#f2d06b']}\n"
    )
    flexo.register_theme(tmp_path / "ordered.yaml")
    paint = resolve_palette("ordered-test")
    first, second = paint.get("tone-1-stroke"), paint.get("tone-2-stroke")
    assert _hue(first) < 40 or _hue(first) > 330  # red
    assert 190 < _hue(second) < 250  # blue


def _hue(colour: str) -> float:
    import colorsys

    red, green, blue = (int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return colorsys.rgb_to_hsv(red, green, blue)[0] * 360
