"""Colours by their code (``studio/static/studio/hexcolour.js``): every way a colour is typed or
pasted read as #rrggbb and its alpha, words that are no colour refused, the colours applied last
kept for the person and read with care, and what is chosen offered to ⇧⌘C by its colours
(with the shapes' own, ``shapecolours.js``) -- run in Node, with this browser's storage stood
in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SCRIPT = STATIC / "hexcolour.js"
SHAPES = STATIC / "shapecolours.js"

PRELUDE = """
const kept = new Map(Object.entries(START));
let fails = false;
const refuse = () => { if (fails) throw new Error("denied"); };
const storage = {
  getItem: (key) => { refuse(); return kept.has(key) ? kept.get(key) : null; },
  setItem: (key, value) => { refuse(); kept.set(key, String(value)); },
};
Object.defineProperty(globalThis, "localStorage",
  { value: storage, configurable: true, writable: true });
const heard = [];
const listen = (name, listener) => { if (name === "storage") heard.push(listener); };
globalThis.window = { addEventListener: listen };
const fresh = async () => import(`${URL}?${Math.random()}`);
const C = await fresh();
"""

KEY = "flexo-studio-recent-colours"


def run(body: str, start: dict[str, str] | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const START = {json.dumps(start or {})};\n"
        f"const URL = {json.dumps(SCRIPT.as_uri())};\n"
        f"const SHAPES = {json.dumps(SHAPES.as_uri())};\n"
        f"{PRELUDE}\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def parsed(*texts: str) -> list[object]:
    return run(f"return {json.dumps(list(texts))}.map((text) => C.parseColour(text));")  # type: ignore[return-value]


def test_every_way_a_colour_is_written_reads_as_its_hex() -> None:
    blue = {"hex": "#1f77b4", "alpha": None}
    assert (
        parsed(
            "#1f77b4",
            "1f77b4",
            "#1F77B4",
            "  #1f77b4\n",
            "0x1f77b4",
            "rgb(31, 119, 180)",
            "rgb(31,119,180)",
            "RGB(31 119 180)",
            "rgb(12.2%, 46.7%, 70.6%)",
            "(31, 119, 180)",
            "[31, 119, 180]",
            "31, 119, 180",
            "tab:blue",
            "fill: #1f77b4;",
            "color:#1f77b4",
            '"#1f77b4"',
            "'#1f77b4'",
            "`#1f77b4`",
        )
        == [blue] * 18
    )
    # Three digits each doubled, as CSS reads them; matplotlib's fractions of one.
    assert parsed("#17b", "17b", "(0.12, 0.47, 0.71)", "(1, 1, 1)", "(0, 0, 0)") == [
        {"hex": "#1177bb", "alpha": None},
        {"hex": "#1177bb", "alpha": None},
        {"hex": "#1f78b5", "alpha": None},
        {"hex": "#ffffff", "alpha": None},
        {"hex": "#000000", "alpha": None},
    ]
    # HSL, by degrees or turns, percentages of saturation and lightness.
    assert parsed("hsl(205, 71%, 41%)", "hsl(0.5turn 100% 50%)", "hsl(120deg, 100%, 25%)") == [
        {"hex": "#1e75b3", "alpha": None},
        {"hex": "#00ffff", "alpha": None},
        {"hex": "#008000", "alpha": None},
    ]
    # A CSS colour's name, however it is written.
    assert parsed("steelblue", "SteelBlue", "rebeccapurple", "light gray") == [
        {"hex": "#4682b4", "alpha": None},
        {"hex": "#4682b4", "alpha": None},
        {"hex": "#663399", "alpha": None},
        {"hex": "#d3d3d3", "alpha": None},
    ]


def test_an_alpha_written_after_a_colour_is_read_apart() -> None:
    assert parsed(
        "#1f77b4cc",
        "#17bc",
        "1f77b4cc",
        "0x1f77b4cc",
        "rgba(31, 119, 180, 0.8)",
        "rgb(31 119 180 / 80%)",
        "(31, 119, 180, 0.8)",
        "hsla(205, 71%, 41%, 0.8)",
    ) == [
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1177bb", "alpha": 0.8},
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1f77b4", "alpha": 0.8},
        {"hex": "#1e75b3", "alpha": 0.8},
    ]
    # Opaque, transparent, and two places at most, as the inspector's sliders keep it.
    assert parsed("#1f77b4ff", "#1f77b400", "#1f77b480") == [
        {"hex": "#1f77b4", "alpha": 1},
        {"hex": "#1f77b4", "alpha": 0},
        {"hex": "#1f77b4", "alpha": 0.5},
    ]


def test_words_that_are_no_colour_are_refused() -> None:
    assert (
        parsed(
            "",
            "   ",
            "#",
            "#12",
            "#12345",
            "#1234567",
            "#gggggg",
            "1f77b",
            "0x123",
            "rgb(31, 119)",
            "rgb(31, 119, 180, 0.5, 1)",
            "rgb(a, b, c)",
            "rgb(31 119 180 /)",
            "hsl(205, 71, 41)",
            "(300, 0, 0)",
            "(-1, 0, 0)",
            "transparent",
            "accent",
            "not a colour",
            "#1f77b4 and more",
            "x" * 80,
        )
        == [None] * 21
    )
    assert run("return [C.parseColour(null), C.parseColour(12), C.parseColour(undefined)];") == [
        None,
        None,
        None,
    ]


def test_a_colour_as_written_in_a_file_and_as_the_field_shows_it() -> None:
    assert run("""
      return [C.hexOf("#1f77b4"), C.hexOf("#17b"), C.hexOf("#1F77B4CC"), C.hexOf("accent"),
        C.hexOf("1f77b4"), C.hexOf(null), C.hexOf({ stops: [] }), C.shownHex("#1f77b4")];
    """) == ["#1f77b4", "#1177bb", "#1f77b4", None, None, None, None, "#1F77B4"]


def test_the_colours_applied_last_are_kept_newest_first_and_read_with_care() -> None:
    made = run(f"""
      const first = C.recentColours();
      C.rememberColour("#1f77b4");
      C.rememberColour("#ff7f0e");
      C.rememberColour("#1F77B4");      // again: first, once
      C.rememberColour("accent");       // a theme's colour by its name: none to keep
      for (let n = 0; n < 10; n += 1) C.rememberColour(`#00000${{n}}`);
      const stored = JSON.parse(kept.get("{KEY}"));
      const again = (await fresh()).recentColours();
      kept.set("{KEY}", "nonsense");
      const odd = (await fresh()).recentColours();
      kept.set("{KEY}", JSON.stringify({{ not: "a list" }}));
      const other = (await fresh()).recentColours();
      kept.set("{KEY}", JSON.stringify(["#abc", 7, "red", "#ABCDEF", "#abcdef", null]));
      const sifted = (await fresh()).recentColours();
      fails = true;
      const unreadable = await fresh();
      const none = unreadable.recentColours();
      unreadable.rememberColour("#2ca02c");
      return {{ first, most: C.RECENT_MOST, stored, again, odd, other, sifted, none,
        refused: unreadable.recentColours() }};
    """)
    assert made["first"] == []
    assert made["most"] == 8
    assert made["stored"] == [f"#00000{n}" for n in range(9, 1, -1)]
    assert made["again"] == made["stored"]
    # Whatever else is kept (or nothing readable): none; what is not a colour, left out.
    assert made["odd"] == made["other"] == made["none"] == []
    assert made["sifted"] == ["#aabbcc", "#abcdef"]
    # Applied while the storage refuses: kept all the same, in this window.
    assert made["refused"] == ["#2ca02c"]


def test_those_listening_hear_of_a_colour_applied_here_or_in_another_tab() -> None:
    made = run(f"""
      const told = [];
      const stop = C.onRecentColours((list) => told.push(list[0]));
      C.rememberColour("#1f77b4");
      kept.set("{KEY}", JSON.stringify(["#ff7f0e", "#1f77b4"]));
      heard[heard.length - 1]({{ key: "{KEY}" }});
      heard[heard.length - 1]({{ key: "another" }});
      stop();
      C.rememberColour("#2ca02c");
      return {{ told, now: C.recentColours() }};
    """)
    assert made == {"told": ["#1f77b4", "#ff7f0e"], "now": ["#2ca02c", "#ff7f0e", "#1f77b4"]}


def test_a_colour_applied_by_its_code_is_a_step_of_its_own() -> None:
    made = run("""
      const steps = [];
      globalThis.flexoStudio = { active: { step: () => steps.push("step") } };
      C.applyColour((hex, alpha) => steps.push(["apply", hex, alpha]), "#1f77b4", 0.8);
      return { steps, recent: C.recentColours() };
    """)
    assert made == {"steps": ["step", ["apply", "#1f77b4", 0.8], "step"], "recent": ["#1f77b4"]}


CHOICES = """
  const applied = [];
  const colour = (kind, name, value) =>
    ({ name, value, set: (hex, alpha) => applied.push([kind, name, hex, alpha]) });
  const objects = { noun: "2 Objects", main: 0, colours: [colour("objects", "Text", "accent")] };
  const shapes = { noun: "3 Shapes", main: 0, colours: [colour("shapes", "Fill", "#ff0000"),
    colour("shapes", "Outline", "ink"), colour("shapes", "Text", "accent")] };
  const said = (list) => list.map((choice) => [choice.name, choice.said, choice.value ?? null]);
"""


def test_what_is_chosen_is_offered_by_its_colours_its_main_one_first() -> None:
    made = run(
        CHOICES
        + """
      const lines = { noun: "Line", main: 1,
        colours: [colour("line", "Fill"), colour("line", "Line", "#00ff00")] };
      return { shapes: said(C.colourChoices([shapes])), line: said(C.colourChoices([lines])),
        none: C.colourChoices([]),
        empty: C.colourChoices([null, { noun: "Picture", colours: [] }]) };
    """
    )
    assert made == {
        "shapes": [
            ["Fill", "Fill of 3 Shapes", "#ff0000"],
            ["Outline", "Outline of 3 Shapes", "ink"],
            ["Text", "Text of 3 Shapes", "accent"],
        ],
        "line": [["Line", "Line of Line", "#00ff00"], ["Fill", "Fill of Line", None]],
        "none": [],
        "empty": [],
    }


def test_two_kinds_chosen_are_coloured_each_by_its_own_and_by_the_colours_they_share() -> None:
    made = run(
        CHOICES
        + """
      const both = C.colourChoices([objects, shapes]);
      both[0].set("#1f77b4", null);
      both[1].set("#ff7f0e", null);
      // Both seen by their words: that colour first, no "Both".
      const words = { noun: "Text Box", main: 2, colours: shapes.colours };
      return { both: said(both), applied, alike: said(C.colourChoices([objects, words])) };
    """
    )
    assert made == {
        "both": [
            ["Both", "Text of 2 Objects, Fill of 3 Shapes", None],
            ["Text", "Text of 2 Objects and 3 Shapes", "accent"],
            ["Fill", "Fill of 3 Shapes", "#ff0000"],
            ["Outline", "Outline of 3 Shapes", "ink"],
        ],
        "applied": [
            ["objects", "Text", "#1f77b4", None],
            ["shapes", "Fill", "#1f77b4", None],
            ["objects", "Text", "#ff7f0e", None],
            ["shapes", "Text", "#ff7f0e", None],
        ],
        "alike": [
            ["Text", "Text of 2 Objects and Text Box", "accent"],
            ["Fill", "Fill of Text Box", "#ff0000"],
            ["Outline", "Outline of Text Box", "ink"],
        ],
    }


def test_shapes_chosen_are_offered_by_the_colours_they_are_seen_by() -> None:
    made = run("""
      const S = await import(SHAPES);
      const made = [];
      const editor = (specs) => ({ typing: () => false, specs: () => specs,
        label: () => (specs.length === 1 ? "Shape" : `${specs.length} Shapes`),
        order: () => specs.map((_, n) => n),
        set: (changes, label) => made.push(["set", changes, label]),
        change: (mutate, label) => {
          const list = structuredClone(specs);
          mutate(list);
          made.push(["change", list, label]);
        } });
      const box = { kind: "rectangle", at: [0, 0], size: [10, 10], fill: "accent-fill" };
      const line = { kind: "line", from: [0, 0], to: [10, 10] };
      const words = { kind: "text", at: [0, 0], width: 100, text: "Hi" };
      const group = { kind: "group", shapes: [box, { ...box, fill: "grey" }] };
      const sum = (specs) => {
        const kind = S.shapeColours(editor(specs));
        return kind && { noun: kind.noun, main: kind.colours[kind.main].name,
          names: kind.colours.map((colour) => colour.name) };
      };
      const kinds = { box: sum([box]), line: sum([line]), words: sum([words]),
        group: sum([group]), mixed: sum([box, line]), none: sum([]) };
      const both = S.shapeColours(editor([box, line]));
      both.colours[0].set("#1f77b4", 0.5);
      S.shapeColours(editor([box])).colours[0].set("#ff7f0e", 0.8);
      S.shapeColours(editor([line])).colours[0].set("#2ca02c", null);
      const pen = { kind: "pen", points: [[0, 0], [1, 1]] };
      return { kinds, made, mains: [box, line, words, pen].map(S.mainPaint),
        typing: S.shapeColours({ ...editor([box]), typing: () => true }) };
    """)
    assert made["kinds"] == {
        "box": {"noun": "Shape", "main": "Fill", "names": ["Fill", "Outline", "Text"]},
        "line": {"noun": "Shape", "main": "Colour", "names": ["Colour", "Text"]},
        "words": {"noun": "Shape", "main": "Text", "names": ["Fill", "Outline", "Text"]},
        "group": {"noun": "Shape", "main": "Fill", "names": ["Fill", "Outline"]},
        "mixed": {
            "noun": "2 Shapes",
            "main": "Colour",
            "names": ["Colour", "Fill", "Outline", "Text"],
        },
        "none": None,
    }
    assert made["mains"] == ["fill", "line", "colour", "line"]
    change, fill, colour = made["made"]
    # A box and a line together: each by its own -- the box's fill, the line's line.
    assert change[0] == "change" and change[2] == "Change Colour"
    assert change[1][0]["fill"] == "#1f77b4" and change[1][0]["fill_opacity"] == 0.5
    assert change[1][1]["line"] == "#1f77b4" and change[1][1]["line_opacity"] == 0.5
    assert "fill" not in change[1][1]
    assert fill == ["set", {"fill": "#ff7f0e", "fill_opacity": 0.8}, "Change Fill"]
    assert colour == ["set", {"line": "#2ca02c"}, "Change Line"]
    assert made["typing"] is None
