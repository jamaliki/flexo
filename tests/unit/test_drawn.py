"""Protein domain maps, trees, well plates, and timelines: drawn components."""

from __future__ import annotations

import re

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.drawn import picture
from flexo.lint import lint_compilation
from flexo.phylogeny import NewickError, parse_newick
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.themes import figure_style

ABL = [
    {"type": "domain", "label": "SH3", "start": 61, "end": 121},
    {"type": "domain", "label": "SH2", "start": 127, "end": 217},
    {"type": "domain", "label": "Kinase", "start": 242, "end": 493, "id": "kinase"},
    {"type": "region", "label": "Disordered", "start": 540, "end": 960},
    {"type": "mutation", "label": "T315I", "at": 315},
    {"type": "mutation", "label": "E255K", "at": 255},
    {"type": "phosphorylation", "label": "Y412", "at": 412},
    {"type": "disulfide", "start": 600, "end": 700},
]
NEWICK = "(((Human:0.08,Chimp:0.09)100:0.12,Gorilla:0.21)98:0.25,(Mouse:0.35,Rat:0.33):0.3);"


def _figure(theme: str = "paper") -> flexo.Figure:
    with flexo.Figure("bench", theme=theme) as figure:
        column = figure.root.column("all", gap=16)
        abl = column.protein("abl", 1130, ABL, label="ABL1")
        column.protein(
            "constructs",
            1130,
            ABL[:3],
            tracks=[
                {"label": "Full length"},
                {"label": "ΔSH3", "delete": "61-121"},
                {"label": "Kinase domain", "start": 229, "end": 500},
            ],
        )
        drug = column.block("drug", label="Imatinib", tone="Kinase")
        figure.connect(drug, abl.port("kinase"), head="inhibition")
        column.tree(
            "tree", NEWICK, support=True, clades=[{"tips": "Human, Gorilla", "label": "Apes"}]
        )
        column.tree("ring", NEWICK, layout="circular")
        column.wellplate(
            "plate",
            [{"wells": "A1-A12", "label": "Control"}, {"wells": "B-D", "label": "Drug"}],
        )
        column.timeline(
            "protocol",
            events=[{"at": 0, "label": "Seed"}, {"at": 2, "label": "Induce", "id": "induce"}],
            spans=[{"start": 2, "end": 5, "label": "Doxycycline"}],
            unit="day",
        )
    return figure


def _drawing(figure: flexo.Figure, node_id: str):
    node = next(node for node in figure.spec.nodes if node.id.endswith(node_id))
    return picture(node, figure_style(figure.spec))


def test_every_drawn_component_compiles_lint_clean_and_reads_back() -> None:
    figure = _figure()
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    document = figure_to_document(figure.spec)
    validate_document(document)
    assert parse_figure(document) == figure.spec


def test_a_protein_is_drawn_to_scale_and_its_domains_take_their_names_colours() -> None:
    figure = _figure()
    drawing = _drawing(figure, "abl")
    shapes = {shape.id: shape for shape in drawing.shapes}

    def left(identifier: str) -> float:
        return min(float(x) for x in re.findall(r"[ML] (-?[\d.]+)", shapes[identifier].d))

    chain = left("all.abl.chain")
    sh3, kinase = left("all.abl.feature1"), left("all.abl.feature3")
    # Residue 61 and residue 242 stand where the scale puts them.
    scale = (kinase - chain) / 241
    assert abs((sh3 - chain) / scale - 60) < 1.5
    svg = compile_figure(figure.spec).document.text

    def fill(identifier: str) -> str:
        found = re.search(rf'id="{re.escape(identifier)}"[^>]*data-flexo-fill="([^"]+)"', svg)
        assert found, identifier
        return found.group(1)

    # The kinase domain is one colour in both proteins and in the box toned "Kinase".
    assert fill("all.abl.feature3") == fill("all.constructs.track1.feature3")
    assert fill("all.abl.feature3") == fill("all.drug.body")
    # Every mutation shares a colour; a phosphorylation takes another.
    assert fill("all.abl.site1") == fill("all.abl.site2") != fill("all.abl.site3")


def test_a_deletion_breaks_the_chain_and_a_truncation_keeps_only_its_residues() -> None:
    drawing = _drawing(_figure(), "constructs")
    ids = {shape.id for shape in drawing.shapes}
    assert "all.constructs.track2.deletion1" in ids
    assert "all.constructs.track2.feature1" not in ids  # SH3 is deleted
    assert "all.constructs.track3.feature2" not in ids  # SH2 is before residue 229
    assert "all.constructs.track3.feature3" in ids


def test_newick_reads_names_lengths_support_and_quotes() -> None:
    root = parse_newick("((A:1,'B c':2)95:0.5,C_d:3);")
    assert [tip.name for tip in root.tips()] == ["A", "B c", "C d"]
    assert root.children[0].name == "95" and root.children[0].length == 0.5
    for bad in ("((A,B);", "(A,B));", "(A:x,B);", ""):
        with pytest.raises(NewickError):
            parse_newick(bad)


def test_a_tree_puts_tips_in_order_and_colours_a_clade() -> None:
    figure = _figure()
    drawing = _drawing(figure, "all.tree")
    tips = [words for words in drawing.words if ".tip" in words.id]
    assert [words.runs[0].text for words in tips] == ["Human", "Chimp", "Gorilla", "Mouse", "Rat"]
    assert [words.y for words in tips] == sorted(words.y for words in tips)
    coloured = {shape.tone for shape in drawing.shapes if shape.tone}
    assert coloured == {"Apes"}
    # A phylogram: Mouse, on the longer path, reaches further right than Human.
    x = {words.runs[0].text: words.x for words in tips}
    assert x["Mouse"] > x["Human"]
    assert any(words.id.endswith(".scale.label") for words in drawing.words)


def test_a_plate_fills_its_groups_and_leaves_the_rest_empty() -> None:
    drawing = _drawing(_figure(), "plate")
    paints = {shape.id: (shape.paint, shape.tone) for shape in drawing.shapes}
    assert paints["all.plate.A1"] == ("body", "Control")
    assert paints["all.plate.C7"] == ("body", "Drug")
    assert paints["all.plate.H12"][0] == "hollow"
    assert sum(shape.id.startswith("all.plate.") and shape.id[10:11].isalpha() and
               shape.id[11:].isdigit() for shape in drawing.shapes) == 96


def test_a_timeline_writes_its_times_and_stacks_its_spans() -> None:
    drawing = _drawing(_figure(), "protocol")
    times = [words.runs[0].text for words in drawing.words if ".tick" in words.id]
    assert times[0] == "Day 0" and "Day 5" in times
    ports = {port.name for port in drawing.ports}
    assert "induce" in ports


@pytest.mark.parametrize(
    ("make", "words"),
    [
        (lambda g: g.protein("p", 100, [{"type": "domain", "start": 50, "end": 200}]),
         "outside the protein"),
        (lambda g: g.protein("p", 100, [{"type": "helicase", "start": 5, "end": 9}]),
         'no feature called "helicase"'),
        (lambda g: g.protein("p", 100, tracks=[{"delete": "a-b"}]), "not a stretch"),
        (lambda g: g.tree("t", "((A,B);"), "does not read"),
        (lambda g: g.tree("t", "(A,B);", clades=[{"tips": "A, Z"}]), "no tip called 'Z'"),
        (lambda g: g.wellplate("w", [{"wells": "Q1"}]), "not on this plate"),
        (lambda g: g.wellplate("w", wells=100), "not a plate format"),
        (lambda g: g.timeline("t", spans=[{"start": 5, "end": 1}]), "before it starts"),
    ],
)
def test_a_wrong_drawing_says_what_is_wrong(make, words: str) -> None:
    with pytest.raises(FlexoError, match=re.escape(words)):
        with flexo.Figure("wrong") as figure:
            make(figure.root)
        compile_figure(figure.spec)


@pytest.mark.parametrize("theme", ["sketch", "dark", "tikz"])
def test_drawn_components_draw_in_every_theme(theme: str) -> None:
    compiled = compile_figure(_figure(theme).spec)
    assert 'id="all.abl.chain"' in compiled.document.text
