"""Parts of a figure hidden, dimmed or highlighted where they stand: a talk's one figure,
shown many ways, with nothing moved."""

from __future__ import annotations

import re

import pytest
import yaml

import flexo
from flexo import FlexoError, compile_figure
from flexo.portable import portable_svg
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.showing import DIMMED, HIDDEN, faint, states
from flexo.studio.figure_edit import apply

PIPELINE = """
figure: {id: shown, style: paper}
groups:
- {id: root, role: canvas, layout: {kind: row}, children: [client, backend, store]}
- {id: backend, role: module, label: Backend, layout: {kind: row}, children: [api, queue, worker]}
nodes:
- {id: client, kind: person, label: Customer}
- {id: api, label: API, properties: {tone: 1}}
- {id: queue, kind: queue, label: Orders, properties: {tone: 2}}
- {id: worker, label: Worker, properties: {tone: 3}}
- {id: store, kind: database, label: Store, properties: {tone: 4}}
- {id: ring, kind: frame, label: Later, properties: {around: "worker, store", layer: front}}
edges:
- {from: client, to: api, label: HTTPS}
- {from: api, to: queue}
- {from: queue, to: worker}
- {from: worker, to: store}
"""


def _figure(**shown: list[str]) -> flexo.FigureSpec:
    document = yaml.safe_load(PIPELINE)
    document["figure"].update(shown)
    return parse_figure(document)


def _marked(svg: str) -> dict[str, str]:
    return dict(re.findall(r'<\w+ id="([^"]+)"[^>]*data-flexo-show="(\w+)"', svg))


def test_what_is_hidden_takes_its_lines_and_a_box_with_nothing_left_in_it() -> None:
    shown = states(_figure(hide=["worker", "store"], dim=["client"]))
    assert shown["worker"] == shown["store"] == HIDDEN and shown["client"] == DIMMED
    # A line is shown as the less shown of its ends.
    assert shown["edge.3.queue-to-worker"] == shown["edge.4.worker-to-store"] == HIDDEN
    assert shown["edge.1.client-to-api"] == DIMMED and "edge.2.api-to-queue" not in shown
    # The frame round nothing that is left goes; the module, with shapes still shown, stays.
    assert shown["ring"] == HIDDEN and "backend" not in shown
    # A group named takes all it holds, and its own box.
    whole = states(_figure(hide=["backend"]))
    assert {whole[name] for name in ("backend", "api", "queue", "worker")} == {HIDDEN}
    assert states(_figure()) == {}


def test_highlighting_is_dimming_the_rest() -> None:
    shown = states(_figure(highlight=["api", "queue"]))
    assert {name for name, how in shown.items() if how == DIMMED} >= {"client", "worker", "store"}
    assert "api" not in shown and "queue" not in shown and "edge.2.api-to-queue" not in shown
    assert shown["edge.1.client-to-api"] == DIMMED
    # The box they are in, and its title, are faint with the rest: only what is named
    # stands out. (With all that is shown in it highlighted, the box is too.)
    assert shown["backend"] == DIMMED
    assert "backend" not in states(_figure(highlight=["api", "queue"], hide=["worker"]))
    assert "backend" not in states(_figure(highlight=["api", "queue", "worker"]))
    # A group highlighted is all of it; what is hidden stays hidden.
    module = states(_figure(highlight=["backend"], hide=["worker"]))
    assert "api" not in module and "backend" not in module and module["worker"] == HIDDEN
    assert module["client"] == module["store"] == DIMMED


def test_nothing_moves_and_the_drawing_says_what_is_hidden_and_faint() -> None:
    plain = compile_figure(_figure())
    partly = compile_figure(_figure(hide=["worker", "store"], dim=["client"]))
    where = lambda compiled: {  # noqa: E731
        node.measured.spec.id: node.bounds for node in compiled.fitted.nodes
    }
    assert where(plain) == where(partly)
    assert plain.document.width_mm == partly.document.width_mm
    svg = partly.document.text
    marked = _marked(svg)
    assert marked["worker"] == marked["store"] == marked["ring"] == "hidden"
    assert marked["client"] == marked["edge.1.client-to-api"] == "dimmed"
    assert re.search(r'<g id="worker"[^>]*visibility="hidden"', svg)
    # What is faint is drawn nearer the page's colour, not see-through: its words too, and
    # the arrowhead of its line -- a copy, the other lines' own left as it was.
    words = re.search(r'<text id="client.label"[^>]*fill="(#\w+)"', svg)[1]
    assert words == faint("#242126", "#ffffff") != "#242126"
    dimmed = re.search(r'<g id="edge.1.client-to-api"[^>]*>.*?</g>', svg, re.DOTALL)[0]
    assert 'marker-end="url(#arrow.flow.dimmed)"' in dimmed
    assert 'marker-end="url(#arrow.flow)"' in svg and 'id="arrow.flow.dimmed"' in svg
    assert "data-flexo-stroke" not in dimmed
    assert "data-flexo-show" not in plain.document.text


def test_what_is_hidden_is_left_out_of_what_is_exported() -> None:
    drawn = portable_svg(compile_figure(_figure(hide=["worker", "store"])).document.text)
    said = set(re.findall(r'aria-label="([^"]+)"', drawn))
    assert {"API", "Orders", "Customer"} <= said and not {"Worker", "Store", "Later"} & said


def test_it_is_kept_in_the_file_and_the_builder_takes_it() -> None:
    written = figure_to_document(_figure(hide=["store"], highlight=["api"]))["figure"]
    assert written["hide"] == ["store"] and written["highlight"] == ["api"] and "dim" not in written
    assert "hide" not in figure_to_document(_figure())["figure"]
    wrong = yaml.safe_load(PIPELINE)
    wrong["figure"]["hide"] = "store"
    with pytest.raises(FlexoError, match="schema"):
        validate_document(wrong)
    with flexo.Figure("built", dim=["a"]) as figure:
        figure.block("a", label="A")
        figure.block("b", label="B")
    assert figure.spec.dimmed == ("a",)
    assert _marked(compile_figure(figure.spec).document.text) == {"a": "dimmed"}
    # A name the figure has nothing of is passed over: a shape since deleted.
    assert states(_figure(hide=["gone"])) == {}


def test_the_studio_hides_dims_highlights_and_shows_again() -> None:
    def shown(text: str) -> dict[str, list[str]]:
        settings = yaml.safe_load(text)["figure"]
        return {key: settings[key] for key in ("hide", "dim", "highlight") if key in settings}

    text = apply(PIPELINE, {"do": "show", "ids": ["worker", "store"], "as": "hidden"})["text"]
    assert shown(text) == {"hide": ["worker", "store"]}
    # Shown another way, a part is in one list alone.
    text = apply(text, {"do": "show", "ids": ["store", "client"], "as": "dimmed"})["text"]
    assert shown(text) == {"hide": ["worker"], "dim": ["store", "client"]}
    # Renamed, it is still hidden; deleted, it is in no list.
    text = apply(text, {"do": "rename", "id": "worker", "to": "labourer"})["text"]
    text = apply(text, {"do": "delete", "ids": ["store"]})["text"]
    assert shown(text) == {"hide": ["labourer"], "dim": ["client"]}
    text = apply(text, {"do": "show", "ids": ["labourer"], "as": "shown"})["text"]
    assert shown(text) == {"dim": ["client"]}
    assert shown(apply(text, {"do": "show", "all": True})["text"]) == {}


def test_a_branch_to_a_hidden_shape_is_hidden_and_the_rest_of_its_line_stays() -> None:
    """A line that branches to three shapes, one of them hidden, kept its branch to where
    that one had been."""

    document = {
        "figure": {"id": "fan", "style": "paper", "hide": ["c"], "dim": ["b"]},
        "groups": [
            {"id": "root", "role": "canvas", "layout": {"kind": "row"}, "children": ["s", "outs"]},
            {"id": "outs", "role": "layout", "layout": {"kind": "column"},
             "children": ["a", "b", "c"]},
        ],
        "nodes": [{"id": name, "label": name.upper()} for name in ("s", "a", "b", "c")],
        "nets": [{"id": "fan", "kind": "fan-out", "sources": ["s"], "targets": ["a", "b", "c"]}],
    }
    compiled = compile_figure(parse_figure(document))
    (net,) = compiled.routed.nets
    marked = _marked(compiled.document.text)
    order = [stem.port.node_id for stem in net.target_stems]
    assert marked[f"{net.spec.id}.target.{order.index('c') + 1}"] == "hidden"
    assert marked[f"{net.spec.id}.target.{order.index('b') + 1}"] == "dimmed"
    assert f"{net.spec.id}.target.{order.index('a') + 1}" not in marked
    assert net.spec.id not in marked and f"{net.spec.id}.rail" not in marked
