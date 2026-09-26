"""Hand drawing: a sketched figure has the clean one's layout, drawn by hand."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import yaml

import flexo
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation
from flexo.serialization import dump_figure, parse_figure
from flexo.sketch import Sketch, parse_sketch, path_outlines
from flexo.svg import SVG_NS


def _figure(**options: object) -> Figure:
    with Figure("pipeline", **options) as figure, figure.module("m", label="Model") as m:
        x = m.text("x", "input")
        encoder = m.block("encoder", label="Encoder", input=x, tone="model")
        head = m.block("head", label="Head", input=encoder)
        m.op("sum", "+", inputs=[encoder, head])
    return figure


def _svg(figure: Figure) -> ET.Element:
    return ET.fromstring(compile_figure(figure.spec).document.text)


def test_the_sketch_theme_draws_by_hand_in_kalam_and_stays_lint_clean() -> None:
    compiled = compile_figure(_figure(theme="sketch").spec)
    assert not lint_compilation(compiled).diagnostics
    text = compiled.document.text
    assert 'font-family="Kalam"' in text
    # Washes under the boxes, and a second pass over every line.
    assert ".wash" in text and ".pass1" in text


def test_any_theme_can_be_drawn_by_hand_without_moving_anything() -> None:
    ruled = compile_figure(_figure().spec)
    drawn = compile_figure(_figure(sketch=True).spec)
    assert [node.bounds for node in drawn.fitted.nodes] == [
        node.bounds for node in ruled.fitted.nodes
    ]
    assert [edge.centerline for edge in drawn.routed.edges] == [
        edge.centerline for edge in ruled.routed.edges
    ]
    assert not lint_compilation(drawn).diagnostics
    ids = {item.get("id") for item in _svg(_figure()).iter()} - {None}
    assert ids <= {item.get("id") for item in _svg(_figure(sketch=True)).iter()}


def test_a_sketch_draws_the_same_way_every_time_and_differently_with_another_seed() -> None:
    first = compile_figure(_figure(sketch=True).spec).document.text
    again = compile_figure(_figure(sketch=True).spec).document.text
    other = compile_figure(_figure(sketch={"seed": 3}).spec).document.text
    assert first == again
    assert first != other


def test_a_connector_keeps_its_two_ends_exactly() -> None:
    ruled, drawn = _svg(_figure()), _svg(_figure(sketch=True))

    def ends(root: ET.Element) -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
        result = {}
        for item in root.iter(f"{{{SVG_NS}}}path"):
            if item.get("marker-end"):
                (points, _), *_ = path_outlines(item.get("d", ""))
                result[item.get("id")] = (points[0], points[-1])
        return result

    before, after = ends(ruled), ends(drawn)
    assert before and before.keys() == after.keys()
    for key, (start, end) in before.items():
        assert after[key][0] == pytest.approx(start, abs=1e-4)
        assert after[key][1] == pytest.approx(end, abs=1e-4)


@pytest.mark.parametrize("fill", ["wash", "hatch", "solid", "none"])
def test_every_fill_draws_a_clean_figure(fill: str) -> None:
    compiled = compile_figure(_figure(theme="sketch", sketch={"fill": fill}).spec)
    assert not lint_compilation(compiled).diagnostics
    text = compiled.document.text
    assert (".hatch" in text) is (fill == "hatch")
    assert (".wash" in text) is (fill == "wash")


def test_sketch_settings_are_checked_and_laid_over_the_theme() -> None:
    with pytest.raises(ValueError, match="roughness"):
        Sketch(roughness=2.0)
    with pytest.raises(ValueError, match="fill"):
        parse_sketch({"fill": "crayon"})
    with pytest.raises(ValueError, match="unknown sketch setting"):
        parse_sketch({"rough": 0.2})
    style = flexo.themes.figure_style(_figure(theme="sketch", sketch={"fill": "hatch"}).spec)
    assert style.sketch == Sketch(roughness=0.5, fill="hatch")


def test_a_sketch_round_trips_through_yaml() -> None:
    for value in (True, {"roughness": 0.25, "fill": "hatch"}):
        spec = _figure(sketch=value).spec
        document = yaml.safe_load(dump_figure(spec))
        assert parse_figure(document).sketch == spec.sketch


def test_path_outlines_flatten_every_command() -> None:
    (points, closed), = path_outlines("M 0 0 H 10 V 10 Q 10 20 0 20 A 5 5 0 0 1 0 10 Z")
    assert closed
    assert points[0] == (0.0, 0.0) and points[-1] == (0.0, 0.0)
    assert any(point[0] < 0 for point in points)  # the arc bulges left
