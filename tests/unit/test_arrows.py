"""An arrow drawn as a curve, and an arrow of its own width and head size."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.drawing import read_drawing
from flexo.ir.semantic import EDGE_HEADS, EdgeSpec, PortRef
from flexo.lint import lint_compilation
from flexo.serialization import figure_to_document, parse_figure
from flexo.themes import figure_style


def _elements(compiled) -> dict[str, ET.Element]:
    root = ET.fromstring(compiled.document.text)
    return {item.get("id"): item for item in root.iter() if item.get("id")}


def _row(*, gap: str = "60pt"):
    figure = Figure("row")
    with figure, figure.module("m", layout="row", column_gap=gap) as m:
        a = m.block("a", label="A")
        b = m.block("b", label="B")
    return figure, a, b


def _bow(edge) -> float:
    """How far a curved edge's middle stands off the line between its ends (signed: up
    is positive)."""

    line = edge.centerline
    middle = line[len(line) // 2]
    return (line[0].y + line[-1].y) / 2.0 - middle.y


def test_a_curved_arrow_is_one_curve_from_outline_to_outline() -> None:
    figure, a, b = _row()
    with figure:
        figure.connect(a, b, shape="curved", label="embed")
    compiled = compile_figure(figure.spec)
    (edge,) = compiled.routed.edges
    assert edge.curve is not None and edge.straight
    start, end = edge.centerline[0], edge.centerline[-1]
    first, second = compiled.fitted.node("m.a").bounds, compiled.fitted.node("m.b").bounds
    # Each end on its outline: on the box's edge, not inside it.
    assert first.inflated(0.01).contains_point(start)
    assert not first.inflated(-0.5).contains_point(start)
    assert second.inflated(0.01).contains_point(end)
    assert not second.inflated(-0.5).contains_point(end)
    assert _bow(edge) > 3.0, "a row's arrow bows up, to the left of its travel"
    shaft = _elements(compiled)[f"{edge.spec.id}.shaft"]
    assert shaft.get("d").startswith("M ") and " C " in shaft.get("d")
    assert shaft.get("marker-end") == "url(#arrow.flow)"
    # Its caption by its middle (outside its bow where there is room; here, under the
    # figure's top margin, inside it).
    label = edge.label_position
    assert label is not None and label.x == pytest.approx((start.x + end.x) / 2.0, abs=4.0)
    assert not lint_compilation(compiled).errors


def test_two_curved_arrows_between_one_pair_bow_apart() -> None:
    figure, a, b = _row()
    with figure:
        figure.connect(a, b, shape="curved")
        figure.connect(b, a, shape="curved")
    there, back = compile_figure(figure.spec).routed.edges
    assert _bow(there) > 3.0 and _bow(back) < -3.0


def test_a_curved_arrow_bows_the_way_via_says() -> None:
    figure, a, b = _row()
    with figure:
        figure.connect(a, b, shape="curved", via="south")
    (edge,) = compile_figure(figure.spec).routed.edges
    assert _bow(edge) < -3.0


def test_a_curved_arrow_leaves_and_meets_the_sides_named_square() -> None:
    edge = {"from": "a", "to": "b", "shape": "curved", "depart": "south", "arrive": "south"}
    compiled = compile_figure(parse_figure(_two(edge)))
    (routed,) = compiled.routed.edges
    first, second = compiled.fitted.node("a").bounds, compiled.fitted.node("b").bounds
    start, end = routed.centerline[0], routed.centerline[-1]
    assert start.x == pytest.approx(first.center.x) and start.y == pytest.approx(first.bottom)
    assert end.x == pytest.approx(second.center.x) and end.y == pytest.approx(second.bottom)
    # A U under them, as deep as the figure's margin lets it be.
    lowest = max(point.y for point in routed.centerline)
    assert first.bottom + 5.0 < lowest <= compiled.fitted.canvas_size.height
    assert not lint_compilation(compiled).errors


def _two(*edges: dict) -> dict:
    return {
        "figure": {"id": "two"},
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "groups": [
            {"id": "root", "layout": {"kind": "row", "gap": "60pt"}, "children": ["a", "b"]}
        ],
        "edges": list(edges),
    }


def test_a_wider_arrow_has_heads_grown_to_match_and_its_own_head_size() -> None:
    figure, a, b = _row()
    with figure:
        plain = figure.connect(a, b)
        wide = figure.connect(b, a, width=1.8, head_size=1.5)
    compiled = compile_figure(figure.spec)
    style = figure_style(figure.spec)
    by_id = _elements(compiled)
    scale = round(1.8 / style.connector_width.points * 1.5, 2)
    marker = f"arrow.flow-s{round(scale * 100)}"
    shaft = by_id[f"{wide.id}.shaft"]
    assert shaft.get("stroke-width") == "1.8"
    assert shaft.get("marker-end") == f"url(#{marker})"
    assert by_id[f"{plain.id}.shaft"].get("marker-end") == "url(#arrow.flow)"
    assert float(by_id[marker].get("markerWidth")) > float(by_id["arrow.flow"].get("markerWidth"))
    routed = {edge.spec.id: edge for edge in compiled.routed.edges}

    def trimmed(edge) -> float:
        return edge.centerline[-1].distance_to(edge.shaft[-1])

    # Its shaft stops a head's length short, as long as its head now is.
    grown = trimmed(routed[wide.id]) - style.connector_standoff.points
    theme = trimmed(routed[plain.id]) - style.connector_standoff.points
    assert grown == pytest.approx(theme * scale, rel=1e-6)
    assert not lint_compilation(compiled).errors
    # Read back, the large head is a head of its own size.
    drawing = read_drawing(compiled.document.text)
    heads = [head for item in drawing.walk() for head in getattr(item, "arrowheads", ())]
    lengths = sorted(head.length for head in heads)
    assert lengths[-1] == pytest.approx(lengths[0] * scale, rel=1e-3)


def test_curves_widths_and_head_sizes_are_written_and_read_back() -> None:
    data = {
        "figure": {"id": "kept"},
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"from": "a", "to": "b", "shape": "curved", "width": 2, "head_size": 1.5}],
    }
    spec = parse_figure(data)
    (edge,) = spec.edges
    assert (edge.shape, edge.width, edge.head_size) == ("curved", 2.0, 1.5)
    (written,) = figure_to_document(spec)["edges"]
    assert (written["shape"], written["width"], written["head_size"]) == ("curved", 2.0, 1.5)


@pytest.mark.parametrize(("key", "value"), [("width", 0.0), ("width", 40), ("head_size", 0)])
def test_a_width_or_head_size_out_of_range_is_refused(key: str, value: float) -> None:
    with pytest.raises(ValueError, match=key):
        EdgeSpec("e", PortRef("a", "output"), PortRef("b", "input"), **{key: value})


@pytest.mark.parametrize("head", [head for head in EDGE_HEADS if head != "arrow"])
def test_each_head_is_drawn_and_read_back_as_itself(head: str) -> None:
    figure, a, b = _row()
    with figure:
        edge = figure.connect(a, b, head=head)
    compiled = compile_figure(figure.spec)
    shaft = _elements(compiled)[f"{edge.id}.shaft"]
    assert shaft.get("marker-end") == f"url(#arrow.flow.{head})"
    drawing = read_drawing(compiled.document.text)
    heads = [found for item in drawing.walk() for found in getattr(item, "arrowheads", ())]
    assert [(found.shape, found.end) for found in heads] == [(head, "end")]
    assert not lint_compilation(compiled).errors


def test_a_line_with_heads_at_both_ends_may_start_with_another() -> None:
    figure, a, b = _row()
    with figure:
        edge = figure.connect(a, b, arrow="both", head="triangle", tail="dot")
        same = figure.connect(b, a, arrow="both", head="diamond")
    compiled = compile_figure(figure.spec)
    by_id = _elements(compiled)
    assert by_id[f"{edge.id}.shaft"].get("marker-start") == "url(#arrow.flow.dot.start)"
    assert by_id[f"{edge.id}.shaft"].get("marker-end") == "url(#arrow.flow.triangle)"
    assert by_id[f"{same.id}.shaft"].get("marker-start") == "url(#arrow.flow.diamond.start)"
    drawing = read_drawing(compiled.document.text)
    heads = {
        (found.shape, found.end)
        for item in drawing.walk()
        for found in getattr(item, "arrowheads", ())
    }
    assert heads == {
        ("triangle", "end"), ("dot", "start"), ("diamond", "end"), ("diamond", "start")
    }
    (written, _) = figure_to_document(figure.spec)["edges"]
    assert written["tail"] == "dot"
