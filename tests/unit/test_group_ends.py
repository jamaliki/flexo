"""Lines to groups: a line may start or end at a group, as at a part -- everything going in,
a step, everything coming out -- meeting it where it is seen to end, and moving nothing."""

from __future__ import annotations

import re
from itertools import pairwise

import pytest
import yaml

import flexo
from flexo import compile_figure
from flexo.diagnostics import FlexoError, Severity
from flexo.lint import lint_compilation
from flexo.serialization import figure_to_document, parse_figure

FLOW = """
figure: {id: flow, style: paper}
groups:
- id: root
  role: canvas
  layout: {kind: row, gap: 40, align: center}
  children: [ins, cell, outs, sink]
- {id: ins, role: layout, layout: {kind: column, gap: 8, padding: 20}, children: [a, b, c]}
- {id: outs, role: module, label: Products, layout: {kind: column}, children: [x, y]}
nodes:
- {id: a, label: Glucose}
- {id: b, label: Oxygen}
- {id: c, label: ADP}
- {id: cell, label: Cell, height: 60}
- {id: x, label: CO2}
- {id: y, label: Water}
- {id: sink, label: Air}
"""


def _document(*edges: dict, **settings: object) -> dict:
    document = yaml.safe_load(FLOW)
    document["edges"] = list(edges)
    document["figure"] |= settings
    return document


def _drawn(*edges: dict, **settings: object) -> flexo.Compilation:
    return compile_figure(parse_figure(_document(*edges, **settings)))


def _line(compilation: flexo.Compilation, source: str, target: str):
    return next(
        edge
        for edge in compilation.routed.edges
        if (edge.spec.source.node_id, edge.spec.target.node_id) == (source, target)
    )


def _box(compilation: flexo.Compilation, name: str) -> flexo.Rect:
    found = [node.bounds for node in compilation.fitted.nodes if node.measured.spec.id == name]
    found += [g.bounds for g in compilation.fitted.groups if g.measured.spec.id == name]
    return found[0]


def _held(compilation: flexo.Compilation, *names: str) -> flexo.Rect:
    """The box round the parts ``names``: what a line to a group that draws no outline meets."""

    return flexo.Rect.union(_box(compilation, name) for name in names)


def _side_met(box: flexo.Rect, point: flexo.Point) -> str | None:
    across = box.x - 1e-6 <= point.x <= box.right + 1e-6
    down = box.y - 1e-6 <= point.y <= box.bottom + 1e-6
    for side, at, on in (
        ("north", box.y, point.y),
        ("south", box.bottom, point.y),
        ("west", box.x, point.x),
        ("east", box.right, point.x),
    ):
        if abs(at - on) < 1e-6 and (across if side in {"north", "south"} else down):
            return side
    return None


def _enters(line: tuple[flexo.Point, ...], box: flexo.Rect) -> bool:
    inner = box.inflated(-0.5)
    for one, other in pairwise(line):
        for share in (0.0, 0.25, 0.5, 0.75, 1.0):
            at = flexo.Point(one.x + (other.x - one.x) * share, one.y + (other.y - one.y) * share)
            if inner.contains_point(at):
                return True
    return False


def _errors(compilation: flexo.Compilation) -> list[str]:
    found = lint_compilation(compilation).diagnostics
    return [item.code for item in found if item.severity is Severity.ERROR]


def test_a_line_meets_a_plain_group_at_the_box_round_what_it_holds() -> None:
    """A line from a layout group was refused (``port reference "ins" must have the form
    node.port``). It starts at the box round the group's parts -- not the group's padding,
    which draws nothing -- at the middle of the side that faces its other end, and stops as
    short of them as it would of a part."""

    drawn = _drawn({"from": "ins", "to": "cell"}, {"from": "cell", "to": "sink"})
    assert _errors(drawn) == []
    held, group = _held(drawn, "a", "b", "c"), _box(drawn, "ins")
    assert group.width > held.width + 30  # (its padding: room the line does not stop at)
    line = _line(drawn, "ins", "cell")
    assert _side_met(held, line.centerline[0]) == "east"
    assert line.centerline[0].y == pytest.approx(held.center.y)
    # Its start is as far from the parts as a line's from a part it leaves.
    other = _line(drawn, "cell", "sink")
    gap = line.shaft[0].x - held.right
    assert gap == pytest.approx(other.shaft[0].x - _box(drawn, "cell").right)


def test_a_line_meets_a_group_drawn_round_at_its_outline() -> None:
    """A module is drawn with a box round it: a line to it meets that box, its arrowhead as
    far short of the outline as of a part's."""

    drawn = _drawn({"from": "cell", "to": "outs"}, {"from": "a", "to": "cell"})
    assert _errors(drawn) == []
    outs = _box(drawn, "outs")
    line = _line(drawn, "cell", "outs")
    assert _side_met(outs, line.centerline[-1]) == "west"
    assert line.centerline[-1].y == pytest.approx(outs.center.y)
    short = outs.x - line.shaft[-1].x
    into_part = _line(drawn, "a", "cell")
    assert short > 0
    assert short == pytest.approx(_box(drawn, "cell").x - into_part.shaft[-1].x)
    assert 'id="edge.1.cell-to-outs"' in drawn.document.text


def test_a_line_to_a_group_moves_nothing() -> None:
    plain = _drawn()
    drawn = _drawn({"from": "ins", "to": "cell"}, {"from": "cell", "to": "outs"})
    assert drawn.fitted.canvas_size == plain.fitted.canvas_size
    assert [node.bounds for node in drawn.fitted.nodes] == [n.bounds for n in plain.fitted.nodes]
    assert [group.bounds for group in drawn.fitted.groups] == [
        group.bounds for group in plain.fitted.groups
    ]
    # The layout never saw them; routing did, the groups standing in for their lines.
    assert drawn.measured.semantic.edges == ()
    assert len(drawn.routed.edges) == 2


def test_a_line_from_group_to_group_goes_round_what_is_between_and_into_neither() -> None:
    drawn = _drawn({"from": "ins", "to": "outs"})
    assert _errors(drawn) == []
    line = _line(drawn, "ins", "outs").centerline
    held, outs = _held(drawn, "a", "b", "c"), _box(drawn, "outs")
    assert _side_met(held, line[0]) == "east" and _side_met(outs, line[-1]) == "west"
    for box in (held, outs, _box(drawn, "cell")):
        assert not _enters(line, box)


def test_a_line_to_a_group_runs_through_none_of_its_parts_on_its_way_in() -> None:
    """From under the group to its top: round the group, never between its parts."""

    drawn = _drawn({"from": "sink", "to": "ins", "arrive": "north"})
    assert _errors(drawn) == []
    line = _line(drawn, "sink", "ins").centerline
    held = _held(drawn, "a", "b", "c")
    assert _side_met(held, line[-1]) == "north"
    assert line[-1].x == pytest.approx(held.center.x)
    assert not _enters(line, held)


def test_depart_and_arrive_name_the_sides_a_line_meets_groups_on() -> None:
    """The sides asked for, at their middles."""

    drawn = _drawn(
        {"from": "ins", "to": "cell", "depart": "south", "arrive": "south"},
        {"from": "cell", "to": "outs", "arrive": "north"},
    )
    assert _errors(drawn) == []
    held, outs = _held(drawn, "a", "b", "c"), _box(drawn, "outs")
    first = _line(drawn, "ins", "cell").centerline
    assert _side_met(held, first[0]) == "south" and first[0].x == pytest.approx(held.center.x)
    second = _line(drawn, "cell", "outs").centerline
    assert _side_met(outs, second[-1]) == "north"
    assert second[-1].x == pytest.approx(outs.center.x)
    style = flexo.resolve_style("paper")
    assert outs.y - second[-2].y >= style.arrival_clearance.points - 1e-6


TOP = """
figure: {id: top, style: paper}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 40, align: center}, children: [cell, outs]}
- {id: outs, role: module, label: Products, layout: {kind: column}, children: [x, y]}
nodes:
- {id: cell, label: Cell}
- {id: x, label: CO2}
- {id: y, label: Water}
"""


@pytest.mark.parametrize("end", ["outs", "stage"])
def test_a_line_into_the_top_of_a_group_at_the_pages_top_is_given_room_for_its_arrow(
    end: str,
) -> None:
    """The module stands at the top of the page, and the layout never saw the line: it came
    round over it and turned down into it too late for its arrow. The page is given the room,
    as for a line round a box -- and the same for a line to a frame there."""

    document = yaml.safe_load(TOP)
    document["nodes"].append({"id": "stage", "kind": "frame", "properties": {"around": "outs"}})
    plain = compile_figure(parse_figure(document))
    document["edges"] = [{"from": "cell", "to": end, "arrive": "north"}]
    drawn = compile_figure(parse_figure(document))
    assert _errors(drawn) == []
    line = _line(drawn, "cell", end).centerline
    met = drawn.routed.fitted.node(end).bounds
    assert _side_met(met, line[-1]) == "north"
    style = flexo.resolve_style("paper")
    assert met.y - line[-2].y >= style.shortest_arrival.points - 1e-6
    assert drawn.fitted.group("outs").bounds.y > plain.fitted.group("outs").bounds.y


def test_a_line_between_a_group_and_what_it_holds_is_refused_in_plain_words() -> None:
    for edge, said in (
        ({"from": "ins", "to": "a"}, "joins it to “a”, which it holds"),
        ({"from": "b", "to": "ins"}, "joins it to “b”, which it holds"),
        ({"from": "ins", "to": "ins"}, "starts and ends at it"),
    ):
        with pytest.raises(FlexoError) as refused:
            _drawn(edge)
        (diagnostic,) = refused.value.diagnostics
        assert diagnostic.code == "group.line.inside"
        assert "from inside it" in diagnostic.message and said in diagnostic.message
        assert "port" not in diagnostic.message
    with pytest.raises(FlexoError, match="the group that holds the whole figure"):
        _drawn({"from": "root", "to": "cell"})
    # A group holding another: no line between the two.
    document = _document({"from": "outer", "to": "ins"})
    document["groups"][0]["children"][0] = "outer"
    document["groups"].append(
        {"id": "outer", "role": "layout", "layout": {"kind": "row"}, "children": ["ins"]}
    )
    with pytest.raises(FlexoError, match="joins it to “ins”, which it holds"):
        compile_figure(parse_figure(document))
    # Nor between a group and a frame round it.
    document = _document({"from": "ins", "to": "stage"})
    document["nodes"].append(
        {"id": "stage", "kind": "frame", "properties": {"around": "ins, cell"}}
    )
    with pytest.raises(FlexoError, match="the frame “stage”, which goes round it"):
        compile_figure(parse_figure(document))


def test_an_end_that_names_nothing_is_said_with_what_it_could_be() -> None:
    """``port reference "products" must have the form node.port`` named neither the id nor what
    a line's end may be."""

    for end, hint in (
        ("inz", 'Did you mean "ins"?'),
        ("ins.top", '"ins" is a group, which has no ports: write "ins" alone'),
        ("cell.2", '"cell" is a part, and its ports are cell.input, cell.output.'),
        ("cell.", '"cell" is a part, and its ports are'),
    ):
        with pytest.raises(FlexoError) as refused:
            _drawn({"from": end, "to": "sink"})
        (diagnostic,) = refused.value.diagnostics
        assert diagnostic.code == "edge.source.unknown-node"
        assert diagnostic.message == (
            f'Source "{end}" does not exist: a line starts at a part, a group, or a part\u2019s '
            "port (part.port)."
        )
        assert hint in (diagnostic.hint or "")
    with pytest.raises(FlexoError, match='Target "nowhere" does not exist: a line ends at'):
        _drawn({"from": "sink", "to": "nowhere"})


def test_a_group_written_with_a_plain_port_is_the_group_and_the_figure_round_trips() -> None:
    """The figure writes its own lines' ends with their ports (``ins.output``): read back,
    that is the group."""

    document = _document({"from": "ins", "to": "cell", "depart": "south"})
    written = figure_to_document(parse_figure(document))
    assert written["edges"][0]["from"] == "ins.output"
    again = parse_figure(written)
    assert (again.edges[0].source.node_id, again.edges[0].depart) == ("ins", flexo.Side.SOUTH)
    compile_figure(again)
    # A port of the group's that is not its plain way in or out is refused, from Python too.
    figure = parse_figure(document)
    edge = figure.edges[0]
    bad = flexo.ir.semantic.PortRef("ins", "top")
    from dataclasses import replace

    from flexo.validate import normalize_and_validate

    with pytest.raises(FlexoError, match="a group has none"):
        normalize_and_validate(replace(figure, edges=(replace(edge, source=bad),)))


def test_python_connects_a_group_as_it_does_a_shape() -> None:
    with flexo.Figure("built") as figure:
        with figure.module("inputs", label="Inputs") as inputs:
            inputs.block("p", label="P")
            inputs.block("q", label="Q")
        figure.block("z", label="Z")
        figure.connect(inputs, "z")
        figure.connect("z", "inputs")  # (a group by its id, as a shape is)
    spec = figure.spec
    ends = [(edge.source.node_id, edge.target.node_id) for edge in spec.edges]
    assert ends == [("inputs", "z"), ("z", "inputs")]
    drawn = compile_figure(spec)
    assert _errors(drawn) == [] and len(drawn.routed.edges) == 2


def test_a_line_to_a_group_is_hidden_and_dimmed_with_it() -> None:
    hidden = _drawn({"from": "ins", "to": "cell"}, hide=["ins"])
    line = re.search(r'<g[^>]*id="edge\.1\.ins-to-cell"[^>]*>', hidden.document.text).group(0)
    assert 'visibility="hidden"' in line
    dimmed = _drawn({"from": "ins", "to": "cell"}, dim=["a", "b", "c"])
    line = re.search(r'<g[^>]*id="edge\.1\.ins-to-cell"[^>]*>', dimmed.document.text).group(0)
    assert 'data-flexo-show="dimmed"' in line


def test_a_line_that_branches_and_one_from_a_frame_may_end_at_a_group() -> None:
    document = _document({"from": "stage", "to": "outs"})
    document["nets"] = [
        {"id": "fan", "kind": "fan-out", "sources": ["cell"], "targets": ["outs", "sink"]}
    ]
    document["nodes"].append(
        {"id": "stage", "kind": "frame", "label": "Stage", "properties": {"around": "cell"}}
    )
    drawn = compile_figure(parse_figure(document))
    assert _errors(drawn) == []
    assert [net.spec.id for net in drawn.routed.nets] == ["fan"]
    framed = _line(drawn, "stage", "outs").centerline
    assert _side_met(_box(drawn, "outs"), framed[-1]) == "west"


def test_a_figure_turned_to_fit_a_box_keeps_its_lines_to_groups() -> None:
    """A deck turns a figure to fit a tall place (``fit_in_box``): rows become columns, and a
    line to a group meets it on the side that faces its other end there."""

    from flexo.orient import turned

    spec = parse_figure(_document({"from": "ins", "to": "cell"}, {"from": "cell", "to": "outs"}))
    upright = compile_figure(turned(spec))
    assert _errors(upright) == []
    line = _line(upright, "ins", "cell").centerline
    assert _side_met(_held(upright, "a", "b", "c"), line[0]) == "south"
    fit = flexo.fit_in_box(spec, 200.0, 700.0)
    assert fit.layout.startswith("turned") and fit.errors == 0
    assert {edge.spec.id for edge in fit.compilation.routed.edges} == {
        "edge.1.ins-to-cell",
        "edge.2.cell-to-outs",
    }


REACTION = """
figure: {id: reaction, width: 420}
groups:
- {id: root, role: canvas, layout: {kind: row, gap: 30, align: center}, children: [ins, cell, outs]}
- {id: ins, role: layout, layout: {kind: grid, columns: 3, column_gap: 6, align: center},
   children: [water, plus, oxygen]}
- {id: outs, role: layout, layout: {kind: grid, columns: 2, column_gap: 6, align: center},
   children: [two, product]}
nodes:
- {id: water, kind: mechanism, properties: {steps: [{smiles: O, arrow: none, label: Water}]}}
- {id: plus, kind: text, label: "+"}
- {id: oxygen, kind: mechanism, properties: {steps: [{smiles: O=O, arrow: none, label: Oxygen}]}}
- {id: cell, label: Cell, height: 40}
- {id: two, kind: text, label: "2"}
- {id: product, kind: mechanism, properties: {steps: [{smiles: OO, arrow: none, label: Peroxide}]}}
"""


def test_a_line_beside_a_group_of_named_molecules_meets_it_level_with_the_molecules() -> None:
    """The substrates' line left their box at its middle -- half a name's line under the
    molecules, which a centred row lines up by their drawings -- and stepped up into the
    next part. It meets the group on the line its parts stand on, and runs straight."""

    from flexo.title_sides import middle_y

    document = yaml.safe_load(REACTION)
    document["edges"] = [{"from": "ins", "to": "cell"}, {"from": "cell", "to": "outs"}]
    drawn = compile_figure(parse_figure(document))
    assert _errors(drawn) == []
    ins = drawn.fitted.group("ins")
    level = ins.bounds.y + ins.measured.middle
    assert level == pytest.approx(middle_y(drawn.fitted.node("oxygen")))
    assert level < _held(drawn, "water", "plus", "oxygen").center.y - 2.0
    for source, target in (("ins", "cell"), ("cell", "outs")):
        line = _line(drawn, source, target).centerline
        assert len(line) == 2
        assert [point.y for point in line] == pytest.approx([level, level])
    # Above or below it, a line meets the middle of the group's side, as ever.
    document["edges"] = [{"from": "ins", "to": "cell", "depart": "south", "arrive": "south"}]
    under = compile_figure(parse_figure(document))
    start = _line(under, "ins", "cell").centerline[0]
    held = _held(under, "water", "plus", "oxygen")
    assert _side_met(held, start) == "south" and start.x == pytest.approx(held.center.x)
