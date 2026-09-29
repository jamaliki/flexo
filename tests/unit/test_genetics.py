"""Genetic designs: constructs in SBOL Visual glyphs, and plasmid maps."""

from __future__ import annotations

import math
import re

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.genetics import construct_drawing, plasmid_drawing
from flexo.ir.semantic import NodeSpec, freeze_property
from flexo.lint import lint_compilation
from flexo.schema import validate_document
from flexo.serialization import dump_figure, figure_to_document, parse_figure
from flexo.themes import figure_style

PARTS = [
    {"type": "promoter", "label": "pTet", "id": "ptet"},
    {"type": "rbs", "label": "B0034"},
    {"type": "cds", "label": "GFP", "id": "gfp"},
    {"type": "terminator", "label": "B0015"},
    {"type": "cds", "label": "TetR", "strand": "-", "id": "tetr"},
]
FEATURES = [
    {"type": "promoter", "label": "pTet", "start": 120, "end": 180},
    {"type": "cds", "label": "GFP", "start": 220, "end": 940},
    {"type": "cds", "label": "TetR", "start": 1300, "end": 1920, "strand": "-"},
    {"type": "origin", "label": "ColE1", "start": 2500, "end": 3090},
    {"type": "site", "label": "EcoRI", "start": 5},
]


def _figure(theme: str = "paper") -> flexo.Figure:
    with flexo.Figure("genes", theme=theme) as figure:
        circuit = figure.root.construct("circuit", PARTS, label="Reporter")
        figure.root.plasmid("vector", 5421, FEATURES, label="pTet-GFP")
        protein = figure.root.block("protein", label="Fluorescence", tone="GFP")
        figure.connect(circuit.port("gfp"), protein)
    return figure


def _style(figure: flexo.Figure):
    return figure_style(figure.spec)


def test_a_construct_and_a_plasmid_compile_lint_clean_and_read_back() -> None:
    figure = _figure()
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    text = dump_figure(figure.spec)
    assert "parts:" in text and "- type: promoter" in text
    again = parse_figure(figure_to_document(figure.spec))
    assert again == figure.spec
    validate_document(figure_to_document(figure.spec))


def test_parts_run_left_to_right_and_a_reverse_part_hangs_below() -> None:
    figure = _figure()
    node = next(node for node in figure.spec.nodes if node.id == "circuit")
    drawing = construct_drawing(node, _style(figure))
    base = _points(drawing.shapes[0].d)[0][1]
    lefts: dict[str, float] = {}
    for shape in drawing.shapes[1:]:
        part = shape.id.split(".")[1]
        lefts[part] = min([lefts.get(part, math.inf), *(x for x, _ in _points(shape.d))])
    order = [lefts[f"part{index}"] for index in range(1, 6)]
    assert order == sorted(order)
    # The forward gene sits on the backbone; the reverse one is turned over, pointing left.
    tetr = _points(next(shape for shape in drawing.shapes if shape.id == "circuit.part5").d)
    tip = min(tetr)
    assert abs(tip[1] - base) < 0.5
    # A part with an id is a port under its glyph (over it on the reverse strand).
    ports = {port.name: port for port in drawing.ports}
    assert ports["gfp"].side.value == "south" and ports["tetr"].side.value == "north"
    assert ports["ptet"].offset < ports["gfp"].offset < ports["tetr"].offset


def test_a_gene_is_one_colour_wherever_it_appears() -> None:
    svg = compile_figure(_figure().spec).document.text

    def role(identifier: str) -> str:
        found = re.search(rf'id="{re.escape(identifier)}"[^>]*data-flexo-fill="([^"]+)"', svg)
        assert found, identifier
        return found.group(1)

    # GFP in the construct, GFP on the plasmid, and the box toned "GFP" share one colour;
    # TetR takes another; the promoter is drawn in ink.
    assert role("circuit.part3") == role("vector.feature2") == role("protein.body")
    assert role("circuit.part5") != role("circuit.part3")
    assert 'id="circuit.part1.stem"' in svg and 'id="circuit.part1.stem" d=' in svg


def test_plasmid_features_sit_by_their_base_pairs_and_overlaps_stack() -> None:
    figure = _figure()
    style = _style(figure)
    node = next(node for node in figure.spec.nodes if node.id == "vector")
    drawing = plasmid_drawing(node, style)
    words = {word.id: word for word in drawing.words}
    name = words["vector.label"]
    # GFP (220-940 of 5421) is on the right; the origin (2500-3090) at the bottom.
    assert words["vector.feature2.label"].x > name.x
    assert words["vector.feature4.label"].y > name.y
    assert "5,421 bp" in "".join(run.text for run in words["vector.length"].runs)
    # Two features over the same bases are drawn in two lanes, one outside the other.
    overlapping = [
        {"type": "cds", "label": "A", "start": 100, "end": 900},
        {"type": "cds", "label": "B", "start": 500, "end": 1400},
    ]
    stacked = NodeSpec(
        "stacked",
        "plasmid",
        properties=(("features", freeze_property("features", overlapping)), ("length", 3000)),
    )
    shapes = {shape.id: shape for shape in plasmid_drawing(stacked, style).shapes}
    centre = _centre(shapes["stacked.backbone"].d)
    assert (
        _reach(shapes["stacked.feature2"].d, centre)
        > _reach(shapes["stacked.feature1"].d, centre) + 3
    )


def _points(d: str) -> list[tuple[float, float]]:
    """The end point of every command of a path of M, L, A and Z."""

    tokens = re.findall(r"[MLAZ]|-?\d+(?:\.\d+)?", d)
    points, index = [], 0
    while index < len(tokens):
        command = tokens[index]
        size = {"M": 2, "L": 2, "A": 7, "Z": 0}[command]
        values = [float(value) for value in tokens[index + 1 : index + 1 + size]]
        if values:
            points.append((values[-2], values[-1]))
        index += 1 + size
    return points


def _centre(backbone: str) -> tuple[float, float]:
    (left, y), (right, _) = _points(backbone)[:2]
    return (left + right) / 2.0, y


def _reach(d: str, centre: tuple[float, float]) -> float:
    """How far a shape's farthest point lies from the plasmid's centre."""

    return max(math.hypot(x - centre[0], y - centre[1]) for x, y in _points(d))


@pytest.mark.parametrize(
    ("features", "words"),
    [
        ([{"type": "cds", "start": 10, "end": 9000}], "outside the plasmid"),
        ([{"type": "enhancer", "start": 10, "end": 20}], 'no part called "enhancer"'),
        ([{"type": "cds", "start": 10, "end": 20, "colour": "red"}], "colour is not a part field"),
    ],
)
def test_a_wrong_feature_says_what_is_wrong(features: list[dict], words: str) -> None:
    with flexo.Figure("wrong") as figure:
        figure.root.plasmid("p", 5000, features)
    with pytest.raises(FlexoError, match=words):
        compile_figure(figure.spec)


def test_genetic_designs_draw_by_hand_and_in_every_theme() -> None:
    for theme in ("sketch", "dark", "tikz", "swiss"):
        compiled = compile_figure(_figure(theme).spec)
        assert 'id="vector.backbone"' in compiled.document.text or "vector.backbone" in (
            compiled.document.text
        )
