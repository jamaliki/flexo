"""Copy Style and Paste Style (``studio/static/studio/styles.js``): a shape's style on shapes, a
figure's part's on parts, and either on the other where it maps -- run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "styles.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"import * as s from {json.dumps(SCRIPT.as_uri())};\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_a_shapes_style_goes_on_shapes_as_each_takes_it() -> None:
    made = run("""
      const box = { kind: "rectangle", at: [0, 0], size: [10, 10], fill: "accent2-fill",
        line: "#c0392b", line_width: 3,
        dash: "dashed", shadow: true, bold: true, text: "Kept" };
      const style = s.shapeStyle(box);
      return {
        oval: s.onShape({ kind: "ellipse", at: [5, 5], size: [20, 20], text: "Mine" }, style),
        line: s.onShape({ kind: "arrow", from: [0, 0], to: [9, 9] }, style),
        back: s.onShape({ kind: "rectangle", at: [1, 1], size: [2, 2], fill: "accent3" },
          s.shapeStyle({ kind: "rectangle", at: [0, 0], size: [1, 1] })),
        group: s.onShape({ kind: "group", shapes: [{ kind: "ellipse", at: [0, 0], size: [5,
          5] }] }, style),
      };
    """)
    assert made["oval"] == {
        "kind": "ellipse",
        "at": [5, 5],
        "size": [20, 20],
        "text": "Mine",
        "fill": "accent2-fill",
        "line": "#c0392b",
        "line_width": 3,
        "dash": "dashed",
        "shadow": True,
        "bold": True,
    }
    # A line takes no fill; a box keeps its own words, and no arrowheads.
    assert "fill" not in made["line"] and made["line"]["line"] == "#c0392b"
    assert "end" not in made["line"], "a box has no arrowheads to give"
    # A default style pasted is the kind's own: nothing said.
    assert made["back"] == {"kind": "rectangle", "at": [1, 1], "size": [2, 2]}
    assert made["group"]["shapes"][0]["dash"] == "dashed"


def test_a_shapes_theme_colours_are_a_parts_tone() -> None:
    made = run("""
      const style = s.shapeStyle({ kind: "rectangle", at: [0, 0], size: [1, 1],
        fill: "accent3-fill", line: "accent3",
        dash: "dotted", italic: true, font_size: 9, align: "start" });
      const own = s.shapeStyle({ kind: "ellipse", at: [0, 0], size: [1, 1], fill: "#ffcc00",
        line: "#123456" });
      return { node: s.partValues(style, "node"), edge: s.partValues(style, "edge"),
        own: s.partValues(own, "node"),
        group: s.partValues(own, "group") };
    """)
    assert made["node"] == {
        "properties.tone": "3",
        "properties.paint-fill": None,
        "properties.paint-stroke": None,
        "properties.paint-label": None,
        "line": "dotted",
        "shadow": None,
        "properties.bold": None,
        "properties.italic": True,
        "properties.size": 9,
        "properties.align": "left",
    }
    assert made["edge"] == {"tone": "3", "line": "dotted"}
    assert made["own"]["properties.paint-fill"] == "#ffcc00"
    assert made["own"]["properties.paint-stroke"] == "#123456"
    assert made["group"]["paint.fill"] == "#ffcc00"


def test_a_parts_style_goes_on_parts_and_on_shapes() -> None:
    made = run("""
      const part = s.partStyle({ id: "a", label: "A", properties: { tone: 2, bold: true,
        size: "7pt", "paint-label": "#ff0000" }, line: "dashed" }, "node");
      const group = s.partStyle({ id: "g", paint: { fill: "#eeeeee", stroke: "#333333" } },
        "group");
      return {
        node: s.partValues(part, "node"),
        shape: s.onShape({ kind: "rounded-rectangle", at: [0, 0], size: [9, 9] }, part),
        line: s.onShape({ kind: "line", from: [0, 0], to: [9, 9] }, part),
        fromGroup: s.partValues(group, "node"),
        groupShape: s.onShape({ kind: "rectangle", at: [0, 0], size: [9, 9] }, group),
      };
    """)
    assert made["node"]["properties.tone"] == 2 and made["node"]["line"] == "dashed"
    assert made["node"]["properties.bold"] is True and made["node"]["properties.size"] == "7pt"
    shape = made["shape"]
    assert (
        shape["fill"],
        shape["line"],
        shape["dash"],
        shape["bold"],
        shape["font_size"],
        shape["colour"],
    ) == ("accent2-fill", "accent2", "dashed", True, 7, "#ff0000")
    assert "fill" not in made["line"] and made["line"]["line"] == "accent2"
    assert made["fromGroup"]["properties.paint-fill"] == "#eeeeee"
    assert made["groupShape"]["fill"] == "#eeeeee" and made["groupShape"]["line"] == "#333333"


def test_paste_style_is_one_update_of_the_parts_chosen() -> None:
    made = run("""
      const acts = [];
      const nodes = { a: { id: "a", properties: { tone: 4 } }, b: { id: "b" } },
        groups = { g: { id: "g", children: ["b"] } };
      const figure = { selected: ["a"], model: { root: "root" }, nodeOf: (id) => nodes[id],
        groupOf: (id) => groups[id],
        edgeOf: () => null, netOf: () => null, nameOf: (id) => id, act: (action,
          options) => acts.push([action, options]) };
      globalThis.localStorage = undefined;
      s.copyPartStyle(figure);
      figure.selected = ["b", "g"];
      s.pastePartStyle(figure);
      return acts;
    """)
    ((action, options),) = made
    assert options["label"] == "Paste Style" and action["do"] == "update"
    assert [target["type"] for target in action["targets"]] == ["node", "group"]
    assert action["targets"][0]["values"]["properties.tone"] == 4
    assert "paint.fill" in action["targets"][1]["values"]
