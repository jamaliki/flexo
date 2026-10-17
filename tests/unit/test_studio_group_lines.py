"""Lines to groups in the figure editor (``flexo.studio.group_lines``): Connect draws one
from a group, what the figure would refuse is said first, and a line to a group is renamed,
and goes, with it."""

from __future__ import annotations

import pytest
import yaml

from flexo import compile_figure
from flexo.serialization import parse_figure

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


def test_the_editor_draws_a_line_from_a_group_and_keeps_it_right() -> None:
    """Connect took shapes alone, and a line written to a group was taken out of the
    drawing as one to nothing (``A line from “substrates” has no shape to start from.``)."""

    from flexo.studio.figure_edit import EditError, apply, astray, model

    def edges(text: str) -> list[dict]:
        return yaml.safe_load(text).get("edges", [])

    text = yaml.safe_dump(yaml.safe_load(FLOW), sort_keys=False)
    made = apply(text, {"do": "connect", "source": "ins", "target": "cell"})
    assert made["select"] == ["edge.1.ins-to-cell"]
    both = apply(made["text"], {"do": "connect", "source": "cell", "target": "outs"})["text"]
    assert edges(both) == [{"from": "ins", "to": "cell"}, {"from": "cell", "to": "outs"}]
    compile_figure(parse_figure(yaml.safe_load(both)))
    assert [edge["id"] for edge in model(both)["edges"]] == [
        "edge.1.ins-to-cell",
        "edge.2.cell-to-outs",
    ]
    data = yaml.safe_load(both)
    assert astray(data) == [] and len(data["edges"]) == 2

    # What the figure would refuse, said before it is made.
    for source, target, said in (
        ("ins", "a", "A line can\u2019t end at “ins” from inside it: the group holds “Glucose”."),
        ("b", "ins", "A line can\u2019t end at “ins” from inside it: the group holds “Oxygen”."),
        ("outs", "x", "A line can\u2019t end at “Products” from inside it: the group holds “CO2”."),
        (
            "root",
            "cell",
            "A line can\u2019t end at the figure\u2019s layout: it holds every part. Join a "
            "group inside it.",
        ),
    ):
        with pytest.raises(EditError) as refused:
            apply(both, {"do": "connect", "source": source, "target": target})
        assert str(refused.value) == said

    # Its end taken to a side, to another group -- never to a part of the group at its other end.
    line = {"type": "edge", "id": "edge.2.cell-to-outs"}
    sided = apply(both, {"do": "update", "target": line, "values": {"arrive": "north"}})["text"]
    assert edges(sided)[1] == {"from": "cell", "to": "outs", "arrive": "north"}
    first = {"type": "edge", "id": "edge.1.ins-to-cell"}
    moved = apply(both, {"do": "update", "target": first, "values": {"to": "outs"}})
    assert edges(moved["text"])[0] == {"from": "ins", "to": "outs"}
    with pytest.raises(EditError, match="from inside it"):
        apply(both, {"do": "update", "target": line, "values": {"from": "x"}})

    # Renamed, its lines name it; ungrouped or deleted, they go with it.
    renamed = apply(both, {"do": "rename", "id": "ins", "to": "inputs"})["text"]
    assert edges(renamed)[0] == {"from": "inputs", "to": "cell"}
    ungrouped = apply(both, {"do": "ungroup", "id": "outs"})["text"]
    assert edges(ungrouped) == [{"from": "ins", "to": "cell"}]
    compile_figure(parse_figure(yaml.safe_load(ungrouped)))
    deleted = apply(both, {"do": "delete", "ids": ["ins"]})["text"]
    assert edges(deleted) == [{"from": "cell", "to": "outs"}]
    compile_figure(parse_figure(yaml.safe_load(deleted)))
