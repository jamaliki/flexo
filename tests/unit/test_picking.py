"""What a click picks follows what is drawn (``studio/static/studio/picking.js``): a box of words
with no fill and no outline is picked only where its words are drawn, a few pixels round them,
so a node's circle under its letters is picked beside them; one filled or outlined, anywhere in
its frame. And the page's drawn shapes found by id once a drawing -- run in Node, the page's
drawing and its geometry stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "picking.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

# The browser's DOMMatrix and DOMPoint, as much of them as is asked of: a plane's affine maps.
PRELUDE = """
class Matrix {
  constructor(a = 1, b = 0, c = 0, d = 1, e = 0, f = 0) {
    Object.assign(this, { a, b, c, d, e, f });
  }
  multiply(o) {
    return new Matrix(this.a * o.a + this.c * o.b, this.b * o.a + this.d * o.b,
      this.a * o.c + this.c * o.d, this.b * o.c + this.d * o.d,
      this.a * o.e + this.c * o.f + this.e, this.b * o.e + this.d * o.f + this.f);
  }
  inverse() {
    const det = this.a * this.d - this.b * this.c;
    return new Matrix(this.d / det, -this.b / det, -this.c / det, this.a / det,
      (this.c * this.f - this.d * this.e) / det, (this.b * this.e - this.a * this.f) / det);
  }
}
globalThis.DOMPoint = class {
  constructor(x, y) { this.x = x; this.y = y; }
  matrixTransform(m) {
    return new DOMPoint(m.a * this.x + m.c * this.y + m.e, m.b * this.x + m.d * this.y + m.f);
  }
};
const P = await import(URL);
const F = await import(FREEFORM);
const round = (values) => values.map((value) => Math.round(value * 1000) / 1000);
"""


def run(body: str) -> object:
    script = (
        f"const URL = {json.dumps(SCRIPT.as_uri())};\n"
        f"const FREEFORM = {json.dumps((SCRIPT.parent / 'freeform.js').as_uri())};\n"
        f"{PRELUDE}\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_box_of_words_with_no_fill_nor_outline_is_picked_where_its_words_are() -> None:
    made = run("""
      const words = { kind: "text", at: [100, 50], width: 40, text: "A1" };
      return {
        bare: [
          P.bare(words), P.bare({ ...words, fill: "accent-fill" }),
          P.bare({ ...words, line: "ink" }),
          // Painted, but not to be seen: no fill, an outline of no width or none at all.
          P.bare({ ...words, fill: "accent", fill_opacity: 0 }),
          P.bare({ ...words, line: "ink", line_width: 0 }),
          P.bare({ ...words, line: "ink", line_opacity: 0 }),
          P.bare({ ...words, fill: { linear: ["accent", "ink"] } }),
          // Only a box of words: a shape's own words are it, wherever they are.
          P.bare({ kind: "ellipse", at: [0, 0], size: [10, 10], fill: "none", line: "none" }),
          P.bare(null),
        ],
      };
    """)
    assert made["bare"] == [True, False, False, True, True, True, False, False, False]


def test_its_words_are_where_they_are_drawn_in_its_box_turned_or_not() -> None:
    made = run("""
      const flat = { box: [100, 50, 40, 16], turn: 0 };
      // Words drawn from (105, 52) to (125, 62): from the box's top left, (5, 2) to (25, 12).
      const corners = [[105, 52], [125, 52], [125, 62], [105, 62]];
      const words = P.wordsFrom(corners, flat);
      const on = (made, point, margin = 1.5) => P.onWords(made, words, point, margin);
      // The box turned by 90° about its middle (120, 58), its words with it.
      const turned = { box: [100, 50, 40, 16], turn: 90 };
      const turn = (point) => F.turned(point, [120, 58], 90);
      return {
        words, again: round(P.wordsFrom(corners.map(turn), turned)),
        flat: [on(flat, [106, 55]), on(flat, [126.4, 55]), on(flat, [127, 55]),
          on(flat, [101, 64]), on(flat, [115, 63.4])],
        turned: [on(turned, turn([106, 55])), on(turned, turn([101, 64])), on(turned, [106, 55])],
        // Nothing drawn: none (it is then picked by its frame).
        none: [P.wordsFrom([[1, 1], [1, 1], [1, 1], [1, 1]], flat),
          P.wordsFrom([[NaN, 1], [1, 1], [1, 1], [1, 1]], flat)],
      };
    """)
    assert made["words"] == [5, 2, 25, 12] and made["again"] == [5, 2, 25, 12]
    # On them, within the margin of them (1.5 here), off them: in the box's frame all the same.
    assert made["flat"] == [True, True, False, False, True]
    assert made["turned"] == [True, False, False]
    assert made["none"] == [None, None]


def test_the_picker_measures_each_box_s_words_once_as_the_page_draws_them() -> None:
    made = run("""
      // The layer: two pixels to a unit; the words' element drawn in units of its own, a
      // tenth of the layer's, moved (as a slide's drawing is: its units scaled to the shapes').
      const layer = { getScreenCTM: () => new Matrix(2, 0, 0, 2, 10, 20) };
      const local = new Matrix(0.1, 0, 0, 0.1, 0, 0);
      let measured = 0;
      const element = (box) => ({
        getBBox: () => { measured += 1; return box; },
        getScreenCTM: () => layer.getScreenCTM().multiply(local),
      });
      // Words at (105, 52)-(125, 62) in the layer's units: (1050, 520)-(1250, 620) in its own.
      const drawn = {
        "s.0.text": element({ x: 1050, y: 520, width: 200, height: 100 }),
        "s.2.text": element({ x: 0, y: 0, width: 0, height: 0 }),
      };
      const hits = P.wordsPicker({ node: (id) => drawn[id] || null, layer, unit: () => 2 });
      const words = { kind: "text", at: [100, 50], width: 40, text: "A1" };
      const made = { box: [100, 50, 40, 16], turn: 0 };
      return {
        on: hits(words, made, [106, 55], "s.0"), off: hits(words, made, [101, 64], "s.0"),
        // Three pixels round them (a unit and a half, here) are them too.
        near: hits(words, made, [126.4, 55], "s.0"),
        measured,
        // Filled, not drawn, or drawn as nothing: none of its words' -- its frame's, as before.
        filled: hits({ ...words, fill: "accent-fill" }, made, [101, 64], "s.0"),
        missing: hits(words, made, [101, 64], "s.1"), empty: hits(words, made, [101, 64], "s.2"),
      };
    """)
    assert made["on"] is True and made["off"] is False and made["near"] is True
    assert made["measured"] == 1
    assert made["filled"] is None and made["missing"] is None and made["empty"] is None


def test_the_page_s_drawn_shapes_are_found_by_id_once_a_drawing() -> None:
    made = run("""
      let passes = 0;
      const drawing = (ids) => ({
        querySelectorAll: () => {
          passes += 1;
          return ids.map((id) => ({ id, isConnected: true }));
        },
      });
      let now = drawing(["a", "b", "a"]);
      const byId = P.drawnIds(() => now);
      const first = [byId("a")?.id, byId("b")?.id, byId("c"), passes];
      // The same drawing: found without another pass; another drawing, found again.
      now = drawing(["c"]);
      const second = [byId("a"), byId("c")?.id, passes];
      // One found no longer in it (drawn again in place): found again.
      byId("c").isConnected = false;
      const third = [byId("c")?.isConnected, passes];
      now = null;
      return { first, second, third, none: byId("c") };
    """)
    assert made["first"] == ["a", "b", None, 1]
    assert made["second"] == [None, "c", 2]
    assert made["third"] == [True, 3]
    assert made["none"] is None


def test_a_box_of_words_is_measured_by_its_letters_ink_not_its_lines_height() -> None:
    made = run("""
      // A <text> of two lines, each a <tspan>: "A1" bold at (623, 222.9), "B" at (626, 238.3);
      // each letter 7 across. The ink of "A1" reaches 9.2 above its baseline, none below; of "B",
      // 9 above and 0.1 below.
      const run = (text, x, y, weight) => ({
        localName: "tspan", textContent: text, weight, querySelector: () => null,
        getNumberOfChars: () => text.length,
        getStartPositionOfChar: () => ({ x, y }),
        getEndPositionOfChar: (n) => ({ x: x + 7 * (n + 1), y }),
      });
      const lines = [run("A1", 623, 222.9, "700"), run("B", 626, 238.3, "400")];
      const text = (children) => ({
        querySelectorAll: (what) => (what === "tspan"
          ? children.filter((c) => c.localName === "tspan") : children),
      });
      globalThis.getComputedStyle = (node) => ({
        fontStyle: "normal", fontWeight: node.weight, fontSize: "12.8px", fontFamily: "Figtree",
      });
      const fonts = [];
      const ink = (words, font) => {
        fonts.push(font);
        return words === "A1" ? { up: 9.2, down: 0 } : { up: 9, down: 0.1 };
      };
      return {
        two: P.wordsInk(text(lines), ink).map((v) => Math.round(v * 100) / 100), fonts,
        // Words with more than letters in them (maths drawn as a group): none said.
        maths: P.wordsInk(text([...lines, { localName: "g" }]), ink),
        // No way to measure: none said.
        unmeasured: P.wordsInk(text(lines), () => null),
      };
    """)
    assert made["two"] == [623, 213.7, 637, 238.4]
    assert made["fonts"] == ["normal 700 12.8px Figtree", "normal 400 12.8px Figtree"]
    assert made["maths"] is None and made["unmeasured"] is None
