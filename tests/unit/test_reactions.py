"""Regulation heads after SBGN, reversible steps, and cofactors written beside a reaction."""

from __future__ import annotations

import re

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.drawing import Shape, read_drawing
from flexo.lint import lint_compilation
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure

HEADS = ("inhibition", "catalysis", "stimulation", "necessary", "modulation")


def _pathway(layout: str = "row", theme: str = "paper") -> flexo.Figure:
    with flexo.Figure("pathway", theme=theme, layout="flow" if layout == "flow" else None) as fig:
        parent = fig.root if layout == "flow" else fig.root.row("steps", gap=60)
        glucose = parent.text("glucose", label="Glucose")
        g6p = parent.text("g6p", label="Glucose-6-P")
        f6p = parent.text("f6p", label="Fructose-6-P")
        fig.connect(glucose, g6p, id="hk", label="hexokinase", cofactors=("ATP", "ADP"))
        fig.connect(g6p, f6p, id="pgi", arrow="reversible", label="$k_1$", back_label="$k_{-1}$")
    return fig


def test_each_head_is_its_own_marker_and_reads_back_by_name() -> None:
    with flexo.Figure("heads") as figure:
        source = figure.root.block("source", label="Regulator")
        for head in HEADS:
            target = figure.root.block(head, label=head)
            figure.connect(source, target, id=f"to-{head}", head=head)
    compiled = compile_figure(figure.spec)
    svg = compiled.document.text
    assert not lint_compilation(compiled).diagnostics
    for head in HEADS:
        assert f'id="arrow.flow.{head}"' in svg
        assert re.search(rf'id="to-{head}.shaft"[^>]*marker-end="url\(#arrow.flow.{head}\)"', svg)
    # Heads nobody uses are not defined.
    assert "harpoon" not in svg
    shapes = {
        item.id: item for item in read_drawing(svg).walk() if isinstance(item, Shape) and item.id
    }
    assert [head.shape for head in shapes["to-inhibition.shaft"].arrowheads] == ["inhibition"]


def test_a_regulation_head_touches_its_target() -> None:
    with flexo.Figure("repression") as figure:
        tetr = figure.root.block("tetr", label="TetR")
        ptet = figure.root.block("ptet", label="pTet")
        figure.connect(tetr, ptet, id="represses", head="inhibition")
    compiled = compile_figure(figure.spec)
    drawing = read_drawing(compiled.document.text)
    shaft = next(item for item in drawing.walk() if getattr(item, "id", None) == "represses.shaft")
    (head,) = shaft.arrowheads
    target = compiled.routed.fitted.node("ptet").bounds
    reach = [point for segment in head.outline for point in segment.points]

    def gap(x: float, y: float) -> float:
        dx = max(target.left - x, 0.0, x - target.right)
        dy = max(target.top - y, 0.0, y - target.bottom)
        return (dx * dx + dy * dy) ** 0.5

    # The bar stands on the target's edge, not a standoff short of it.
    assert min(gap(x, y) for x, y in reach) < 1.0


def test_a_reversible_step_is_two_harpoons_with_a_rate_constant_each_side() -> None:
    compiled = compile_figure(_pathway().spec)
    assert not lint_compilation(compiled).diagnostics
    svg = compiled.document.text
    assert 'id="pgi.forward"' in svg and 'id="pgi.back"' in svg
    assert svg.count('marker-end="url(#arrow.flow.harpoon)"') == 2
    edge = next(edge for edge in compiled.routed.edges if edge.spec.id == "pgi")
    line = edge.centerline[0].y
    assert edge.label_position is not None and edge.aside is not None
    # k1 over the lines, k-1 under them, both clear of the outer harpoons.
    assert edge.label_position.y < line
    assert edge.aside.box.top > line + 2.0


def test_cofactors_curve_to_the_line_opposite_the_enzyme() -> None:
    for layout in ("row", "flow"):
        compiled = compile_figure(_pathway(layout).spec)
        assert not lint_compilation(compiled).diagnostics, layout
        svg = compiled.document.text
        for name in ("hk.cofactors", "hk.cofactors.head", "hk.taken", "hk.given"):
            assert f'id="{name}"' in svg, (layout, name)
        edge = next(edge for edge in compiled.routed.edges if edge.spec.id == "hk")
        assert edge.aside is not None and edge.label_position is not None
        # The arc dips to touch the line; the enzyme is written across it.
        touch = edge.aside.arc[0]
        side = edge.aside.normal
        at = edge.aside.at
        label = edge.label_position
        assert (label.x - at.x) * side.x + (label.y - at.y) * side.y < 0
        assert (touch.x - at.x) * side.x + (touch.y - at.y) * side.y > 0
        # No component sits under the writing.
        for node in compiled.routed.fitted.nodes:
            assert not node.bounds.intersects(edge.aside.box, strict=True), layout


def test_one_sided_cofactors_draw_half_the_curve() -> None:
    with flexo.Figure("water") as figure:
        row = figure.root.row("row", gap=60)
        a, b = row.text("ester", label="Ester"), row.text("acid", label="Acid")
        figure.connect(a, b, id="hydrolysis", label="esterase", cofactors=("H₂O", ""))
    svg = compile_figure(figure.spec).document.text
    assert 'id="hydrolysis.taken"' in svg
    assert 'id="hydrolysis.given"' not in svg and 'id="hydrolysis.cofactors.head"' not in svg


def test_reactions_read_back_from_yaml_and_validate() -> None:
    spec = _pathway().spec
    document = figure_to_document(spec)
    validate_document(document)
    edges = {edge["id"]: edge for edge in document["edges"]}
    assert edges["hk"]["cofactors"] == ["ATP", "ADP"]
    assert edges["pgi"]["arrow"] == "reversible"
    assert parse_figure(document) == spec


@pytest.mark.parametrize(
    ("options", "words"),
    [
        ({"head": "repress"}, 'unknown head "repress"'),
        ({"head": "inhibition", "arrow": "none"}, 'a head needs arrow "end" or "both"'),
        ({"cofactors": ("", "")}, "either may be empty, not both"),
        ({"cofactors": ("ATP", "ADP"), "back_label": "k"}, "one or the other"),
    ],
)
def test_a_wrong_reaction_says_what_is_wrong(options: dict, words: str) -> None:
    with flexo.Figure("wrong") as figure:
        a, b = figure.root.block("a"), figure.root.block("b")
        with pytest.raises(ValueError, match=re.escape(words)):
            figure.connect(a, b, **options)


@pytest.mark.parametrize("theme", ["sketch", "dark", "tikz", "swiss"])
def test_reactions_draw_in_every_theme_and_export(theme: str, tmp_path) -> None:
    result = flexo.build(_pathway(theme=theme).spec, tmp_path, formats=("portable", "pdf"))
    assert len(result.outputs.existing()) == 3  # the editable SVG always
    assert result.ok


def test_cofactors_beside_a_diagonal_edge_keep_off_their_own_line() -> None:
    with flexo.Figure("diagonal") as figure:
        grid = figure.root.grid("g", columns=2, gap=60)
        a = grid.block("a", label="A")
        grid.block("b", label="B")
        grid.block("c", label="C")
        d = grid.block("d", label="D")
        figure.connect(a, d, id="r", shape="straight", label="kinase", cofactors=("ATP", "ADP"))
    assert not lint_compilation(compile_figure(figure.spec)).diagnostics


def test_a_long_label_keeps_its_block_clear_of_the_motif() -> None:
    with flexo.Figure("cnn") as figure:
        figure.root.cnn("one", label="U-Net")
        figure.root.cnn("two", label="Ca prediction\n(U-Net)")
    svg = compile_figure(figure.spec).document.text
    assert 'id="one.motif"' in svg and 'id="two.motif"' not in svg
