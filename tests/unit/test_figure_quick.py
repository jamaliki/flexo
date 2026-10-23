"""The figure editor kept quick (``studio/static/figure/parts.js``, ``parts.css``): a theme colour
painted on a shape at once, as the figure will paint it -- a frame's too, and one undone; a
shape chosen marked at once, its + a moment later should placing it measure the drawing; a line
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


TONES = """
const tones = {
  colours: [
    { fill: "#dbebfd", stroke: "#1a5d9b", ink: "#242126", motif: "#1a5d9b" },
    { fill: "#fee4ce", stroke: "#824c0d", ink: "#3a2006", motif: "#a0601a" },
  ],
  neutral: { fill: "#f1eff4", stroke: "#76707d", ink: "#242126", motif: "#76707d" },
};
"""


def test_a_shape_given_a_theme_colour_is_painted_as_the_figure_paints_it() -> None:
    out = run(
        TONES
        + """
      return {
        // A shape of the block's paint given the second colour: its fill, outline and words the
        // tone's, by the tone's roles; its shadow as it was.
        toned: P.retoned([{ role: "block-fill", colour: "#F1EFF4" },
          { role: "block-stroke", colour: "#76707d" }, { role: "ink", colour: "#242126" },
          { role: "shadow", colour: "#2c2830" }], tones, "2"),
        // One of the first colour made grey again: the block's paint, its words the ink.
        neutral: P.retoned([{ role: "tone-1-fill", colour: "#dbebfd" },
          { role: "tone-1-ink", colour: "#242126" }, { role: "tone-1-motif", colour: "#1a5d9b" }],
          tones, "neutral"),
      };
    """
    )
    assert out == {
        "toned": [
            {"role": "tone-2-fill", "colour": "#fee4ce"},
            {"role": "tone-2-stroke", "colour": "#824c0d"},
            {"role": "tone-2-ink", "colour": "#3a2006"},
            None,
        ],
        "neutral": [
            {"role": "block-fill", "colour": "#f1eff4"},
            {"role": "ink", "colour": "#242126"},
            {"role": "block-motif", "colour": "#76707d"},
        ],
    }


def test_a_shape_the_page_cannot_tell_the_paint_of_waits_for_its_drawing() -> None:
    out = run(
        TONES
        + """
      const block = [{ role: "block-fill", colour: "#f1eff4" }];
      return [
        // Painted otherwise than the theme says (a figure in a theme of its own).
        P.retoned([{ role: "block-fill", colour: "#123456" }], tones, "1"),
        // Of a kind's own colour family, which a tone takes over the page cannot tell.
        P.retoned([{ role: "accent-fill", colour: "#dbebfd" }], tones, "1"),
        // A colour the theme does not have, a tone by name, or none (the kind's own).
        P.retoned(block, tones, "9"), P.retoned(block, tones, "encoder"),
        P.retoned(block, tones, null),
        // A theme that says nothing of its tones' words (an older studio's answer).
        P.retoned([{ role: "ink", colour: "#242126" }],
          { colours: [{ fill: "#dbebfd", stroke: "#1a5d9b" }], neutral: tones.neutral }, "1"),
      ];
    """
    )
    assert out == [None, None, None, None, None, None]


FRAME_TONES = TONES.replace(
    "neutral: {", 'container: { fill: "#f7f5fa", stroke: "#d9d5de" },\n  neutral: {'
)


def test_a_frame_given_a_theme_colour_is_painted_as_flexo_frames_paints_it() -> None:
    out = run(
        FRAME_TONES
        + """
      const frame = (items) => items.map((item) => ({ ...item, family: "container" }));
      return {
        // A frame of no colour given the second: its outline and fill the container's until
        // then, the tone's now; its title's words the tone's ink.
        toned: P.retoned(frame([{ role: "container-stroke", colour: "#D9D5DE" },
          { role: "container-fill", colour: "#f7f5fa" },
          { role: "ink", colour: "#242126" }]), tones, "2"),
        // Of the first colour made grey again: the container's, not the block's.
        neutral: P.retoned(frame([{ role: "tone-1-stroke", colour: "#1a5d9b" },
          { role: "tone-1-ink", colour: "#242126" }]), tones, "neutral"),
        // The page not told the container's colours (an older studio's answer), or a frame's
        // outline not as the theme it knows paints it: the drawing is waited for.
        untold: P.retoned(frame([{ role: "container-stroke", colour: "#d9d5de" }]),
          { colours: tones.colours, neutral: tones.neutral }, "1"),
        other: P.retoned(frame([{ role: "container-stroke", colour: "#123456" }]), tones, "1"),
        // A shape that is not a frame painted with a container's role: waited for, as before.
        block: P.retoned([{ role: "container-stroke", colour: "#d9d5de" }], tones, "1"),
      };
    """
    )
    assert out == {
        "toned": [
            {"role": "tone-2-stroke", "colour": "#824c0d"},
            {"role": "tone-2-fill", "colour": "#fee4ce"},
            {"role": "tone-2-ink", "colour": "#3a2006"},
        ],
        "neutral": [
            {"role": "container-stroke", "colour": "#d9d5de"},
            {"role": "ink", "colour": "#242126"},
        ],
        "untold": None,
        "other": None,
        "block": None,
    }


# A part's drawing as the page has it, enough for paintTone: elements with attributes, the
# ones under them, and what holds each.
DRAWN = """
const roled = (each) => each.attributes["data-flexo-fill"] || each.attributes["data-flexo-stroke"];
class El {
  constructor(tag, attributes = {}, children = []) {
    Object.assign(this, { tagName: tag, attributes: { ...attributes }, children });
    this.parentNode = null;
    for (const child of children) child.parentNode = this;
  }
  get id() { return this.attributes.id || ""; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  setAttribute(key, value) { this.attributes[key] = value; }
  all() { return this.children.flatMap((child) => [child, ...child.all()]); }
  querySelectorAll() { return this.all().filter(roled); }
  contains(other) {
    for (let at = other; at; at = at.parentNode) if (at === this) return true;
    return false;
  }
  closest(selector) {
    for (let at = this; at; at = at.parentNode) {
      if (selector.includes("text") && at.tagName === "text") return at;
      if (selector.includes(".label") && at.id.endsWith(".label")) return at;
    }
    return null;
  }
  get ownerSVGElement() { return { querySelectorAll: () => [] }; }
}
const paint = (element) => [element, ...element.all()].filter(roled).map((each) => [
  each.id || each.tagName, each.attributes.fill, each.attributes["data-flexo-fill"] || null,
  each.attributes.stroke || null, each.attributes["data-flexo-stroke"] || null]);
"""


def test_an_undone_colour_is_painted_back_at_once_its_words_own_colours_left_be() -> None:
    out = run(
        FRAME_TONES
        + DRAWN
        + """
      // A frame toned 2 (a colour chosen), its title with a run of words in the accent's colour.
      const run = new El("tspan", { fill: "#1a5d9b", "data-flexo-fill": "tone-1-stroke" });
      const title = new El("text",
        { id: "f.label", fill: "#3a2006", "data-flexo-fill": "tone-2-ink" }, [run]);
      const body = new El("rect",
        { id: "f.body", fill: "#ffffff", stroke: "#824c0d", "data-flexo-stroke": "tone-2-stroke" });
      const drawn = new El("g", { id: "f" }, [body, title]);
      const node = (tone) => ({ id: "f", kind: "frame", label: "F",
        properties: { around: "a", tone, "paint-fill": "#ffffff" } });
      const model = (tone) => ({ figure: { id: "x" }, root: "root", edges: [], nets: [],
        nodes: [node(tone), { id: "a", kind: "block", label: "A" }],
        groups: [{ id: "root", children: ["a", "f"] }] });
      const figure = P.figureParts({
        catalog: { parts: {}, groups: [] }, overlay: new Node("div"), idOf: (id) => id,
        changed() {}, element: (id) => (id === "f" ? drawn : null), box: () => null,
        tones: () => tones, run: async () => null,
      });
      figure.setModel(model("2"));
      // Undone (the figure as the undo left it, before its drawing): grey again at once.
      figure.setModel(model("neutral"), { afresh: true });
      const undone = paint(drawn);
      // Changed in more than its colour: left for its drawing.
      const relabelled = [{ ...node("3"), label: "G" }, model("3").nodes[1]];
      figure.setModel({ ...model("3"), nodes: relabelled }, { afresh: true });
      const more = paint(drawn);
      return { undone, more: JSON.stringify(more) === JSON.stringify(undone) };
    """
    )
    assert out["undone"] == [
        ["f.body", "#ffffff", None, "#d9d5de", "container-stroke"],
        ["f.label", "#242126", "ink", None, None],
        # (A run of its words in a colour of its own keeps it.)
        ["tspan", "#1a5d9b", "tone-1-stroke", None, None],
    ]
    assert out["more"] is True


def test_a_shape_chosen_is_marked_at_once_its_plus_placed_a_moment_later() -> None:
    out = run("""
      document.querySelectorAll = () => [];
      const rect = (left, top, width, height) =>
        ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top });
      const at = (tag, box) => Object.assign(new Node(tag),
        { getBoundingClientRect: () => box, querySelector: () => null,
          querySelectorAll: () => [] });
      const overlay = at("div", rect(0, 0, 800, 600));
      const shape = at("g", rect(100, 100, 80, 40)), root = at("g", rect(0, 0, 400, 300));
      const model = { figure: { id: "f" }, root: "root", edges: [], nets: [],
        nodes: [{ id: "a", kind: "block", label: "A" }, { id: "b", kind: "block", label: "B" }],
        groups: [{ id: "root", children: ["a", "b"], layout: { kind: "row" } }] };
      const figure = P.figureParts({
        catalog: { parts: { block: { title: "Block", fields: [] } }, groups: [] },
        overlay, idOf: (id) => id,
        changed() {}, element: (id) => (id === "root" ? root : id === "a" ? shape : null),
        box: (id) => (id === "a" ? rect(95, 95, 90, 50) : null), run: async () => null,
      });
      figure.setModel(model);
      figure.select(["a"]);
      const plus = (views) => views.filter((view) => String(view.tag).startsWith("button")).length;
      const quick = figure.markViews({ quick: true });
      const whole = figure.markViews();
      const again = figure.markViews({ quick: true });
      return { quick: [quick.later, plus(quick)], whole: [whole.later, plus(whole)],
        again: [again.later, plus(again)] };
    """)
    # Marked at once with no + (no point round it tried), it is owed; marked in full, it has one;
    # placed once, a quick marking has it where it was put.
    assert out == {"quick": [True, 0], "whole": [False, 1], "again": [False, 1]}


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
