"""A figure's page (a journal's column, a sheet of paper, a size of one's own) and its panels,
lettered as a journal letters them."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import flexo
from flexo import FlexoError, Severity, compile_figure
from flexo.pages import PAGE_SIZES, PANEL_LABELS, lettered, page_size, panel_letter, panels
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.units import Length

PANELS = """
figure: {id: multi, style: paper, width: 183mm}
groups:
- {id: root, role: canvas, layout: {kind: grid, columns: 2}, children: [one, two, three]}
- {id: one, role: panel, layout: {kind: row}, children: [x, enc]}
- {id: two, role: panel, label: Decoder side, layout: {kind: column}, children: [dec, y]}
- {id: three, role: panel, layout: {kind: row}, children: [store]}
nodes:
- {id: x, kind: text, label: Input}
- {id: enc, label: Encoder}
- {id: dec, label: Decoder}
- {id: y, kind: text, label: Output}
- {id: store, kind: database, label: Store}
edges:
- {from: x, to: enc}
- {from: dec, to: y}
"""


def _figure(text: str = PANELS, **figure: object) -> flexo.FigureSpec:
    document = yaml.safe_load(text)
    document["figure"].update(figure)
    return parse_figure(document)


def _titles(svg: str) -> dict[str, str]:
    """Each group's title as drawn: its words, an em between a letter and a title."""

    found = re.findall(r'<text[^>]*id="([\w.-]+)\.label"[^>]*>(.*?)</text>', svg, re.DOTALL)
    return {group: re.sub(r"<[^>]+>", "", words) for group, words in found}


# -- panels --


def test_panels_are_lettered_in_the_order_they_are_read_and_drawn_with_no_frame() -> None:
    svg = compile_figure(_figure()).document.text
    titles = _titles(svg)
    assert titles["one"] == "a" and titles["three"] == "c"
    # A panel with a title has it after its letter.
    assert titles["two"] == "b\u2003Decoder side"
    assert not re.search(r'id="(one|two|three)\.container"', svg)


def test_a_panel_moved_takes_the_letter_of_where_it_is() -> None:
    document = yaml.safe_load(PANELS)
    document["groups"][0]["children"] = ["three", "one", "two"]
    figure = parse_figure(document)
    assert panels(figure) == ("three", "one", "two")
    titles = _titles(compile_figure(figure).document.text)
    assert (titles["three"], titles["one"]) == ("a", "b")


def test_panels_are_lettered_as_the_figure_says() -> None:
    assert [panel_letter(index) for index in (0, 1, 25, 26, 27)] == ["a", "b", "z", "aa", "ab"]
    assert [panel_letter(index, "(A)") for index in (0, 2)] == ["(A)", "(C)"]
    assert panel_letter(1, "a)") == "b)"
    titles = _titles(compile_figure(_figure(panel_labels="(A)")).document.text)
    assert titles["one"] == "(A)" and titles["two"].startswith("(B)")
    with pytest.raises(FlexoError, match="lettered"):
        panel_letter(0, "one")


def test_a_theme_that_sets_titles_in_capitals_leaves_a_panels_letter_as_chosen() -> None:
    capitals = next(
        name
        for name in flexo.THEMES
        if flexo.resolve_style(name).typography.title_transform == "upper"
    )
    titles = _titles(compile_figure(_figure(style=capitals)).document.text)
    assert titles["one"] == "a"


def test_panels_side_by_side_start_together() -> None:
    document = yaml.safe_load(PANELS)
    document["groups"][0]["layout"] = {"kind": "row"}
    fitted = compile_figure(parse_figure(document)).fitted
    tops = {group.measured.spec.id: group.bounds.y for group in fitted.groups}
    assert tops["one"] == pytest.approx(tops["two"]) == pytest.approx(tops["three"])


def test_a_figure_with_no_panels_is_as_it_was() -> None:
    with flexo.Figure("plain") as figure:
        figure.block("a", label="A")
    assert lettered(figure.spec) is figure.spec or lettered(figure.spec) == figure.spec


def test_the_builder_makes_panels_and_takes_a_page_by_name() -> None:
    with flexo.Figure("built", page="nature-page", panel_labels="A") as figure:
        with figure.panel("left") as left:
            left.block("encoder", label="Encoder")
        with figure.panel("right", "Read-out") as right:
            right.block("decoder", label="Decoder")
    spec = figure.spec
    assert [group.role for group in spec.groups if group.id in {"left", "right"}] == ["panel"] * 2
    assert spec.width == "183mm" and spec.height == Length.parse("247mm")
    compiled = compile_figure(spec)
    assert compiled.document.width_mm == pytest.approx(183.0)
    assert compiled.document.height_mm == pytest.approx(247.0)
    assert _titles(compiled.document.text)["right"] == "B\u2003Read-out"
    with pytest.raises(FlexoError, match="Unknown page size"):
        flexo.Figure("x", page="nature")


def test_how_panels_are_lettered_is_kept_in_the_file_only_when_chosen() -> None:
    assert "panel_labels" not in figure_to_document(_figure())["figure"]
    document = figure_to_document(_figure(panel_labels="(a)"))
    assert document["figure"]["panel_labels"] == "(a)"
    assert parse_figure(document).panel_labels == "(a)"
    wrong = yaml.safe_load(PANELS)
    wrong["figure"]["panel_labels"] = "one"
    with pytest.raises(FlexoError, match="schema"):
        validate_document(wrong)


# -- the page --


def test_the_named_sizes_are_lengths_a_figure_can_be_given() -> None:
    assert len({size.name for size in PAGE_SIZES}) == len(PAGE_SIZES)
    for size in PAGE_SIZES:
        assert Length.parse(size.width).points > 0
        assert size.height is None or Length.parse(size.height).points > 0
    nature = page_size("nature-2")
    assert (nature.width, nature.height) == ("183mm", None)
    assert (page_size("a4").width, page_size("a4").height) == ("210mm", "297mm")
    assert set(PANEL_LABELS) == {"a", "A", "(a)", "(A)"}


def test_a_page_with_a_height_is_that_size() -> None:
    compiled = compile_figure(_figure(width="210mm", height="297mm"))
    assert compiled.document.width_mm == pytest.approx(210.0)
    assert compiled.document.height_mm == pytest.approx(297.0)
    assert not compiled.measured.diagnostics


def test_a_figure_taller_than_its_page_is_drawn_and_said_not_refused() -> None:
    """Once a height too small for the figure was an error with nothing drawn; too wide for
    its page it had always been drawn, and said."""

    compiled = compile_figure(_figure(height="10mm"))
    (said,) = compiled.measured.diagnostics
    assert said.code == "layout.height.grown" and said.severity is Severity.WARNING
    assert compiled.document.height_mm > 10.0
    assert 'id="one.label"' in compiled.document.text


def test_a_figure_a_little_too_tall_for_its_page_is_drawn_closer_together() -> None:
    free = compile_figure(_figure()).document.height_mm
    compiled = compile_figure(_figure(height=f"{free - 2:.2f}mm"))
    assert not compiled.measured.diagnostics
    assert compiled.document.height_mm == pytest.approx(free - 2, abs=0.01)


def test_a_figure_fitted_to_a_box_leaves_its_own_page_behind() -> None:
    """A slide's figure is laid out for its box: at the box's width under an A4 page's height
    it was left with a page's depth of nothing below it."""

    fitted = flexo.fit_in_box(_figure(width="210mm", height="297mm"), 300.0, 200.0)
    assert fitted.compilation.measured.semantic.height is None
    assert fitted.compilation.document.height_mm < 150.0
    _, _, wide, tall = fitted.ink
    assert wide * fitted.scale <= 300.0 + 1e-6 and tall * fitted.scale <= 200.0 + 1e-6


# -- the editor's side --


def _studio(code: str) -> object:
    from test_studio import FAKE_PAGE, STATIC_ADDRESSES

    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/parts.js"
    program = (
        FAKE_PAGE
        + STATIC_ADDRESSES % json.dumps(script.parents[1].as_uri() + "/")
        + f"const parts = await import({json.dumps(script.as_uri())});\n"
        + f"console.log(JSON.stringify({code}));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_editor_names_a_page_by_its_size_whatever_unit_it_is_written_in() -> None:
    from flexo.studio.figure_parts import page_sizes

    sizes = json.dumps(page_sizes())
    asked = [
        ("double-column", None),
        ("single-column", None),
        ("183mm", None),
        ("18.3cm", None),
        ("183mm", "247mm"),
        ("210mm", "297mm"),
        ("8.5in", "11in"),
        ("215.9mm", "279.4mm"),
        ("120mm", None),
        ("183mm", "100mm"),
        ("double-column", "100mm"),
    ]
    named = _studio(
        f"{json.dumps(asked)}.map(([width, height]) => parts.pageNamed({sizes}, width, height))"
    )
    assert named == [
        "double-column",
        "single-column",
        "nature-2",
        "nature-2",
        "nature-page",
        "a4",
        "letter",
        "letter",
        "",
        "",
        "",
    ]
    titles = _studio(f"{sizes}.map((size) => parts.pageTitle(size))")
    assert "Nature, Two Columns · 183 mm" in titles
    assert "A4 · 210 \u00d7 297 mm" in titles and "US Letter · 8.5 \u00d7 11 in" in titles
    assert titles[:2] == ["Single Column", "Double Column"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_editor_letters_panels_as_they_are_drawn() -> None:
    figure = _figure(panel_labels="(a)")
    groups = [
        {"id": group.id, "role": group.role, "children": list(group.children)}
        for group in reversed(figure.groups)
    ]
    letters = _studio(
        f"[...parts.panelLetters({json.dumps(groups)}, {json.dumps(figure.root)}, '(a)')]"
    )
    drawn = {
        group: panel_letter(index, "(a)") for index, group in enumerate(panels(figure))
    }
    assert dict(letters) == drawn == {"one": "(a)", "two": "(b)", "three": "(c)"}
    many = [{"id": f"p{index}", "role": "panel", "children": []} for index in range(28)]
    assert dict(_studio(f"[...parts.panelLetters({json.dumps(many)}, 'root')]"))["p27"] == "ab"


# -- a figure of several panels, in one step --


def test_a_figure_is_laid_out_as_panels_in_one_step() -> None:
    """A figure of four panels took a group made for each, each from shapes chosen in one
    row, and the figure's own layout set by hand to a grid."""

    from flexo.studio.figure_edit import apply

    plain = (
        "figure: {id: fig, style: paper}\n"
        "nodes:\n- {id: a, label: Encoder}\n- {id: b, label: Decoder}\n"
        "edges:\n- {from: a, to: b}\n"
    )
    made = apply(plain, {"do": "panels", "count": 4, "columns": 2})
    document = yaml.safe_load(made["text"])
    groups = {group["id"]: group for group in document["groups"]}
    assert groups["root"]["layout"] == {"kind": "grid", "columns": 2}
    assert groups["root"]["children"] == made["select"] and len(made["select"]) == 4
    # What the figure had is its first panel, laid out as it was; the rest have a shape each.
    first, *others = (groups[name] for name in made["select"])
    assert first["children"] == ["a", "b"] and first["layout"]["kind"] == "column"
    assert all(group["role"] == "panel" and len(group["children"]) == 1 for group in others)
    titles = _titles(compile_figure(parse_figure(document)).document.text)
    assert [titles[name] for name in made["select"]] == ["a", "b", "c", "d"]
    # Asked for again another way, the panels are kept and laid out anew: in a row, a column.
    row = yaml.safe_load(apply(made["text"], {"do": "panels", "count": 4, "columns": 4})["text"])
    assert row["groups"][0]["layout"] == {"kind": "row"} and len(row["groups"]) == 5
    column = yaml.safe_load(apply(made["text"], {"do": "panels", "count": 4, "columns": 1})["text"])
    assert column["groups"][0]["layout"] == {"kind": "column"}
    # One more is one more, after the last.
    five = apply(made["text"], {"do": "panels", "count": 5, "columns": 2})
    assert len(five["select"]) == 5 and five["select"][:4] == made["select"]


def test_science_has_its_columns_and_panels_have_sizes_and_letters_in_view() -> None:
    from flexo.studio.figure_parts import catalogue

    assert (page_size("science-1").width, page_size("science-2").width) == ("90mm", "184mm")
    offered = catalogue()
    letters = next(f for f in offered["figure_fields"] if f["key"] == "figure.panel_labels")
    assert not letters.get("more")
    sizes = {f["key"] for f in offered["group_fields"]} & {"layout.width", "layout.height"}
    assert sizes == {"layout.width", "layout.height"}
    sized = _figure()
    sized = parse_figure(
        {**yaml.safe_load(PANELS), "groups": [
            {**group, "layout": {**group["layout"], "width": "60mm"}}
            if group["id"] == "one" else group
            for group in yaml.safe_load(PANELS)["groups"]
        ]}
    )
    wide = {g.measured.spec.id: g.bounds.width for g in compile_figure(sized).fitted.groups}
    assert wide["one"] == pytest.approx(Length.parse("60mm").points)
