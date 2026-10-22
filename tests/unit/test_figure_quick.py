"""The figure editor kept quick (``studio/static/figure/parts.js``, ``parts.css``): a line
measured once however often it is drawn anew; a figure read back as it is drawing nothing again;
and no drag's class that has every element of the page styled again as it begins and ends -- run
in Node where it is code."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[2] / "src/flexo/studio/static"

# A stand-in for the page (as test_studio's), and the studio's addresses resolved to its files.
PAGE = """
class Node {
  constructor(tag) {
    Object.assign(this, { tag, children: [], attributes: {}, style: {}, dataset: {} });
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  remove() { this.removed = true; }
}
globalThis.Node = Node;
globalThis.SVGElement = class extends Node {};
globalThis.document = {
  body: new Node("body"), head: new Node("head"), documentElement: new Node("html"),
  addEventListener() {}, querySelector() { return null; },
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new SVGElement(tag),
  createTextNode: (text) => Object.assign(new Node("#text"), { text }),
};
Node.prototype.getContext = () => null;
import { register } from "node:module";
const STATIC = %s;
const SHELL = "data:text/javascript," + encodeURIComponent(
  "export * from " + JSON.stringify(STATIC + "studio/ui.js") + ";"
  + "export const menu = () => {};");
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  const at = (path) => ({ url: STATIC + path, shortCircuit: true });
  if (specifier === "/static/studio/studio.js") return { url: SHELL, shortCircuit: true };
  if (specifier.startsWith("/static/kinds/figure/")) return at("figure/" + specifier.slice(21));
  if (specifier.startsWith("/static/studio/")) return at("studio/" + specifier.slice(15));
  return next(specifier, context);
}`.replace("STATIC", JSON.stringify(STATIC)).replace("SHELL", JSON.stringify(SHELL))));
const P = await import(STATIC + "figure/parts.js");
"""


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = PAGE % json.dumps(STATIC.as_uri() + "/") + (
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\nprocess.exit(0);\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_line_is_measured_once_however_often_it_is_drawn_anew() -> None:
    out = run("""
      let measures = 0;
      const path = (d) => ({ d, getAttribute() { return this.d; },
        getTotalLength() { measures += 1; return 10; } });
      const one = path("M 0 0 H 10"), again = path("M 0 0 H 10"), other = path("M 0 0 V 5");
      const first = P.measuredPath(one);
      const same = P.measuredPath(again) === first && P.measuredPath(one) === first;
      const afterTwo = measures;
      P.measuredPath(other);
      // The same element drawn as another line is measured again.
      one.d = "M 0 0 H 20";
      const changed = P.measuredPath(one) !== first;
      return { same, afterTwo, measures, changed };
    """)
    assert out == {"same": True, "afterTwo": 1, "measures": 3, "changed": True}


def test_a_figure_read_back_as_it_is_draws_nothing_again() -> None:
    out = run("""
      const model = { figure: { id: "f" }, root: "root", edges: [], nets: [],
        nodes: [{ id: "a", kind: "block", label: "A" }],
        groups: [{ id: "root", children: ["a"] }] };
      let answer = model, changes = 0;
      const figure = P.figureParts({
        catalog: { parts: {}, groups: [] }, overlay: new Node("div"), idOf: (id) => id,
        changed() { changes += 1; }, element: () => null, box: () => null,
        run: async () => ({ model: structuredClone(answer) }),
      });
      figure.setModel(structuredClone(model));
      const read = () => new Promise((done) => {
        figure.act({ do: "read" }, { select: false, then: done });
      });
      const before = changes;
      await read();
      const same = changes - before;
      answer = { ...model, nodes: [{ id: "a", kind: "block", label: "B" }] };
      await read();
      return { same, changed: changes - before - same, label: figure.model.nodes[0].label };
    """)
    assert out == {"same": 0, "changed": 1, "label": "B"}


# The classes a drag, a size, a landing or a turn puts on the page or the body as it begins and
# takes off as it ends.
STATES = ("fig-grabbing", "fig-copying", "fig-dragging", "fig-landing", "fig-sizing", "fig-ending")


def test_no_drag_has_every_element_of_the_page_styled_again_as_it_begins_and_ends() -> None:
    sheet = (STATIC / "figure/parts.css").read_text(encoding="utf-8")
    sheet = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    universal = []
    for selectors in re.findall(r"([^{}]+)\{", sheet):
        for selector in selectors.split(","):
            words = selector.split()
            # A state's class before a universal selector (`.fig-dragging .x *`,
            # `body.fig-grabbing *`): every element under it, the slide's whole drawing, styled
            # again when it changes.
            for at, word in enumerate(words):
                if any(f".{state}" in word for state in STATES) and any(
                    after == "*" or after.startswith("*") for after in words[at + 1 :]
                ):
                    universal.append(selector.strip())
    assert universal == []
