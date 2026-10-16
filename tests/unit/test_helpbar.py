"""The help bar's keys (``studio/static/studio/helpkeys.js``): the keys that matter for what is
being done, the most to the point first, no more than seven; each one in the Keyboard Shortcuts
sheet (shell.js's SHORTCUTS) among the groups its context names, drawn as the sheet draws its
keycaps; and the bar shown until it is hidden, kept for the person -- run in Node, with this
browser's storage stood in for."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STUDIO = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SCRIPT = STUDIO / "helpkeys.js"

PRELUDE = """
const kept = new Map(Object.entries(START));
const storage = {
  getItem: (key) => (kept.has(key) ? kept.get(key) : null),
  setItem: (key, value) => { kept.set(key, String(value)); },
};
Object.defineProperty(globalThis, "localStorage",
  { value: storage, configurable: true, writable: true });
const heard = [];
const listen = (name, listener) => { if (name === "storage") heard.push(listener); };
globalThis.window = { addEventListener: listen };
const fresh = async () => import(`${URL}?${Math.random()}`);
const shown = (items) => items.map((item) => `${item.keys} ${item.words}`);
"""


def run(body: str, start: dict[str, str] | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const START = {json.dumps(start or {})};\n"
        f"const URL = {json.dumps(SCRIPT.as_uri())};\n"
        f"{PRELUDE}\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_nothing_chosen_on_a_slide_its_slides_finding_the_grid_and_the_sheet() -> None:
    made = run("""
      const k = await fresh();
      return {
        deck: shown(k.itemsFor({ page: "deck", grid: false, snapping: "guides" })),
        // The grid shown, Hide Grid; a figure's own, Select All.
        figure: shown(k.itemsFor({ page: "figure", grid: true, snapping: "grid" })),
        // A theme, or nothing open: the search and the sheet.
        theme: shown(k.itemsFor({ page: "theme" })),
      };
    """)
    assert made == {
        "deck": [
            "⇧ ⌘ N New Slide",
            "↑ ↓ Slides",
            "⌘ F Find",
            "# Show Grid",
            "% Snapping",
            "⌘ K Search",
            "⌘ / Shortcuts",
        ],
        "figure": [
            "⌘ A Select All",
            "⌘ F Find",
            "# Hide Grid",
            "% Snapping",
            "⌘ K Search",
            "⌘ / Shortcuts",
        ],
        "theme": ["⌘ K Search", "⌘ / Shortcuts"],
    }


def test_what_is_chosen_says_what_it_does_and_esc_lets_it_go() -> None:
    made = run("""
      const k = await fresh();
      const of = (c) => shown(k.itemsFor({ page: "deck", ...c }));
      return {
        shape: of({ chosen: "shape" }),
        shapes: of({ chosen: "shapes" }),
        group: of({ chosen: "group" }),
        // An object in its place's line, words: the arrows go from one to the next.
        object: of({ chosen: "object", edit: "text" }),
        // Placed where it is put, a picture: the arrows nudge it; Return crops it.
        placed: of({ chosen: "placed", edit: "crop" }),
        slides: of({ chosen: "slides" }),
        part: shown(k.itemsFor({ page: "figure", chosen: "part" })),
      };
    """)
    assert made == {
        "shape": [
            "↩ Edit Text",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ D Duplicate",
            "⌫ Delete",
            "⇧ ⌘ C Set Colour",
            "Esc Deselect",
        ],
        "shapes": [
            "⌘ G Group",
            "⇧ ⌘ A Align",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ D Duplicate",
            "⌫ Delete",
            "Esc Deselect",
        ],
        "group": [
            "↩ Enter Group",
            "⇧ ⌘ G Ungroup",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ D Duplicate",
            "⌫ Delete",
            "Esc Deselect",
        ],
        "object": [
            "↩ Edit Text",
            "↑ ↓ Choose",
            "⌥ ↑ ↓ Move",
            "⌘ D Duplicate",
            "⌫ Delete",
            "Esc Deselect",
        ],
        "placed": [
            "↩ Crop",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ D Duplicate",
            "⌫ Delete",
            "⌘ L Lock",
            "Esc Deselect",
        ],
        "slides": [
            "↑ ↓ Slides",
            "↩ New Slide",
            "⌘ D Duplicate",
            "⌫ Delete",
            "⌥ ↑ ↓ Move",
            "⇧ ↑ ↓ Select More",
        ],
        "part": [
            "↩ Edit Label",
            "← → ↑ ↓ Choose",
            "⌥ ← → ↑ ↓ Move",
            "⌘ D Duplicate",
            "⌫ Delete",
            "⌘ G Group",
            "Esc Deselect",
        ],
    }


def test_a_drag_says_what_its_modifiers_do_and_that_esc_takes_it_back() -> None:
    made = run("""
      const k = await fresh();
      const of = (c) => shown(k.itemsFor({ page: "deck", chosen: "shape", ...c }));
      return {
        move: of({ drag: "move", snapping: "guides" }),
        // Snapping off, ⌘ catches.
        free: of({ drag: "move", snapping: "off" }),
        corner: of({ drag: "corner" }),
        side: of({ drag: "side" }),
        turn: of({ drag: "turn" }),
        end: of({ drag: "end" }),
        // Words typed while a drag goes on (the find bar's): the drag's, first.
        over: of({ drag: "band", typing: "words", find: "find" }),
      };
    """)
    assert made == {
        "move": ["⇧ One Way", "⌥ Copy", "⌘ Without Snapping", "Esc Cancel"],
        "free": ["⇧ One Way", "⌥ Copy", "⌘ With Snapping", "Esc Cancel"],
        "corner": ["⇧ Keep Proportions", "⌥ From Centre", "⌘ Without Snapping", "Esc Cancel"],
        "side": ["⌥ From Centre", "⌘ Without Snapping", "Esc Cancel"],
        "turn": ["⇧ 15° Steps", "Esc Cancel"],
        "end": ["⇧ 45° Steps", "⌘ Without Snapping", "Esc Cancel"],
        "over": ["Esc Cancel"],
    }


def test_the_find_bar_its_field_and_n_and_shift_n_once_its_field_is_left() -> None:
    made = run("""
      const k = await fresh();
      return {
        field: shown(k.itemsFor({ page: "deck", find: "find", typing: "field" })),
        replace: shown(k.itemsFor({ page: "deck", find: "replace", typing: "field" })),
        // Left, nothing chosen: n and ⇧N first, then the slide's (⌘F said once).
        open: shown(k.itemsFor({ page: "deck", find: "open" })),
        // A shape chosen: the shape's after them, seven in all.
        chosen: shown(k.itemsFor({ page: "deck", find: "open", chosen: "shape" })),
        // Words typed elsewhere: theirs.
        typing: shown(k.itemsFor({ page: "deck", find: "open", typing: "list" })),
      };
    """)
    assert made == {
        "field": ["↩ Next", "⇧ ↩ Previous", "⌥ ⌘ F Replace", "Esc Close"],
        "replace": ["↩ Replace", "⌥ ↩ Replace All", "Esc Close"],
        "open": [
            "N Next",
            "⇧ N Previous",
            "⌘ F Find",
            "⇧ ⌘ N New Slide",
            "↑ ↓ Slides",
            "# Show Grid",
            "% Snapping",
        ],
        "chosen": [
            "N Next",
            "⇧ N Previous",
            "⌘ F Find",
            "↩ Edit Text",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ D Duplicate",
        ],
        "typing": [
            "⇥ Indent",
            "⇧ ⇥ Outdent",
            "↩ New Item",
            "⇧ ↩ New Line",
            "⌘ B Bold",
            "⌘ I Italic",
            "Esc Done",
        ],
    }


def test_words_typed_a_path_drawn_a_crop_and_nothing_while_presenting() -> None:
    made = run("""
      const k = await fresh();
      const of = (c) => shown(k.itemsFor({ page: "deck", ...c }));
      return {
        words: of({ typing: "words" }),
        label: shown(k.itemsFor({ page: "figure", typing: "label" })),
        // A field of a deck's inspector is left by Esc; a figure's keeps it.
        field: [of({ typing: "field" }), shown(k.itemsFor({ page: "figure", typing: "field" }))],
        pen: of({ mode: "pen" }),
        points: of({ mode: "points", chosen: "path" }),
        crop: of({ mode: "crop", chosen: "object" }),
        group: of({ inGroup: true }),
        hidden: of({ hidden: true, chosen: "shape" }),
      };
    """)
    assert made == {
        "words": [
            "⌘ B Bold",
            "⌘ I Italic",
            "⌘ E Code",
            "⌘ K Link",
            "⌥ ⌘ E Equation",
            "⇥ Next",
            "Esc Done",
        ],
        "label": ["↩ New Line", "⇥ Next Shape", "⇧ ⇥ Previous", "Esc Done"],
        "field": [["⇥ Next", "Esc Done"], ["⇥ Next", "⇧ ⇥ Previous"]],
        "pen": ["↩ Finish", "⌫ Remove Point", "⇧ 45° Steps", "⌘ Without Snapping", "Esc Cancel"],
        "points": [
            "↩ Done",
            "⌫ Delete Point",
            "← → ↑ ↓ Nudge",
            "⇧ \u00d710",
            "⌘ A All Points",
            "⌥ One Handle",
        ],
        "crop": ["↩ Keep Crop", "← → ↑ ↓ Move Frame", "⇧ \u00d710", "Esc Cancel"],
        "group": [
            "Esc Leave Group",
            "⌘ A Select All",
            "⇧ ⌘ N New Slide",
            "↑ ↓ Slides",
            "⌘ F Find",
            "# Show Grid",
            "% Snapping",
        ],
        "hidden": [],
    }


def test_what_the_shapes_editor_and_a_figure_say_is_read_as_a_context() -> None:
    made = run("""
      const k = await fresh();
      const none = { drag: null, corner: false, line: false, tool: null, points: false,
        pointDrag: false, group: 0, chosen: 0, kind: null, locked: false };
      const of = (said) => k.fromShapes({ ...none, ...said });
      return {
        corner: of({ drag: "size", corner: true, chosen: 1, kind: "rectangle" }),
        line: of({ drag: "draw", line: true, tool: "arrow" }),
        polyline: of({ drag: "draw", tool: "polyline" }),
        pen: of({ tool: "path", pointDrag: true }),
        points: of({ points: true, chosen: 1, kind: "path" }),
        group: of({ group: 1, chosen: 2 }),
        locked: of({ chosen: 1, kind: "ellipse", locked: true }),
        parts: k.fromParts({ selected: ["a", "b"], dragging: false, connecting: null }),
        sized: k.fromParts({ selected: ["a"], dragging: false }, { sizing: true }),
        // The first to say each thing has it.
        together: k.together({ chosen: "", drag: "move" }, { chosen: "part", drag: "part" }),
      };
    """)
    assert made == {
        "corner": {"drag": "corner", "chosen": "shape"},
        "line": {"drag": "draw-line", "mode": "tool-line"},
        "polyline": {"mode": "polyline"},
        "pen": {"drag": "pen", "mode": "pen"},
        "points": {"mode": "points", "chosen": "path"},
        "group": {"chosen": "shapes", "inGroup": True},
        "locked": {"chosen": "locked"},
        "parts": {"chosen": "parts"},
        "sized": {"drag": "scale", "chosen": "part"},
        "together": {"chosen": "part", "drag": "move"},
    }


def _sheet() -> list[list[object]]:
    """The Keyboard Shortcuts sheet's groups, as shell.js writes them."""

    source = (STUDIO / "shell.js").read_text("utf-8")
    start = source.index("const SHORTCUTS = [")
    end = source.index("\n];\n", start)
    table = source[start + len("const SHORTCUTS = ") : end + 2]
    # (Its comments taken out: what is left is a JSON array.)
    table = re.sub(r"^\s*//.*$", "", table, flags=re.MULTILINE)
    return json.loads(re.sub(r",\s*\]", "]", table))


# Every context the bar has: its keys are each in the sheet, among the rows of its groups.
CONTEXTS = [
    {"page": page, **extra}
    for page in ("deck", "figure", "theme")
    for extra in (
        {},
        {"find": "open"},
        {"find": "find"},
        {"find": "replace"},
        {"inGroup": True},
        *(
            {"typing": kind}
            for kind in (
                "words",
                "list",
                "cell",
                "code",
                "maths",
                "stat",
                "caption",
                "shape",
                "plain",
                "label",
                "notes",
                "field",
            )
        ),
        *(
            {"drag": kind}
            for kind in (
                "move",
                "corner",
                "side",
                "scale",
                "turn",
                "end",
                "draw-line",
                "draw",
                "handle",
                "point",
                "pen",
                "crop",
                "part",
                "plain",
            )
        ),
        *(
            {"mode": kind}
            for kind in (
                "crop",
                "pen",
                "polyline",
                "freehand",
                "tool",
                "tool-line",
                "points",
                "connect",
            )
        ),
        *(
            {"chosen": kind, "edit": edit}
            for kind in (
                "shape",
                "path",
                "group",
                "shapes",
                "locked",
                "object",
                "placed",
                "locked-object",
                "objects",
                "placed-objects",
                "mixed",
                "words",
                "logo",
                "slides",
                "part",
                "parts",
            )
            for edit in ("text", "crop", "")
        ),
    )
]


def test_each_key_the_bar_shows_is_in_the_sheet_among_its_contexts_groups() -> None:
    # A chord as a key is pressed: "⌥ ← →" is ⌥← and ⌥→, "↩ ⇧ ↩" ↩ and ⇧↩, "⌥ or ⇧ ←" ⌥← and
    # ⇧←, "⇧ Drag" ⇧drag -- and ⇧ alone, held while dragging, is ⇧.
    made = run(f"""
      const k = await fresh();
      const SHEET = {json.dumps(_sheet())};
      const MOD = /^[⌘⇧⌥⌃]$/;
      const WORDS = ["Click", "Drag", "Double-Click", "Type"];
      const meanings = (keys) => {{
        const words = keys.split(" ").filter(Boolean), out = [];
        const or = words.findIndex((w, at) => w === "or" && MOD.test(words[at - 1] || "")
          && MOD.test(words[at + 1] || ""));
        if (or >= 0) {{
          const mods = words.filter(MOD.test.bind(MOD));
          const rest = words.filter((w) => !MOD.test(w) && w !== "or");
          const said = (key) => (WORDS.includes(key) ? key.toLowerCase() : key);
          for (const mod of mods) for (const key of rest) out.push(mod + said(key));
          return out;
        }}
        let mods = "", last = false;
        for (const w of words) {{
          if (MOD.test(w)) {{ if (!last) mods = ""; mods += w; last = true; continue; }}
          if (w === "or") {{ mods = ""; last = false; continue; }}
          out.push(mods + (WORDS.includes(w) ? w.toLowerCase() : w));
          last = false;
        }}
        if (last) out.push(mods);
        return out;
      }};
      const wrong = [];
      for (const context of {json.dumps(CONTEXTS)}) {{
        const items = k.itemsFor(context);
        if (items.length > k.MOST) wrong.push([context, "too many", items.length]);
        const rows = SHEET.filter(([title]) => items.sheet.includes(title))
          .flatMap(([, rows]) => rows);
        if (items.length && !rows.length) wrong.push([context, "no groups", items.sheet]);
        const known = new Set(rows.flatMap(([keys]) => meanings(keys)));
        const said = rows.map(([, what]) => what.replace(/\\s+/g, "")).join(" ");
        for (const item of items) {{
          for (const chord of meanings(item.keys)) {{
            // A modifier alone (held as a drag goes on, or with the arrows): one the sheet has.
            const ok = MOD.test(chord)
              ? [...known].some((one) => one.includes(chord)) || said.includes(chord)
              : known.has(chord) || said.includes(chord);
            if (!ok) wrong.push([context, item.keys, chord]);
          }}
        }}
      }}
      return wrong;
    """)
    assert made == []


def test_its_keycaps_are_drawn_as_the_sheets_its_arrows_together() -> None:
    made = run(f"""
      const k = await fresh();
      const SHEET = {json.dumps(_sheet())};
      const drawn = (parts) => parts.map((part) => part.key ?? `(${{part.word}})`).join(" ");
      const cap = (keys) => drawn(k.chords(keys));
      // The bar's own: arrows side by side, under one modifier, one keycap.
      const bar = (keys) => drawn(k.compact(k.chords(keys)));
      return {{
        caps: ["⇧ ⌘ N", "↩ ⇧ ↩", "N ⇧ N", "⌥ or ⇧ ← → ↑ ↓", "Esc or ⌘ ↩", "⇧ Drag", "⇧",
               "⌘ ' ⇧ ⌘ '", "⇧ ⌘ ] ["].map(cap),
        bar: ["← → ↑ ↓", "⌥ ← → ↑ ↓", "↑ ↓", "⇧ ↑ ↓", "⌥ or ⇧ ← →", "← ⌫ →"].map(bar),
        // (The sheet's own rows all drawn: none ends on a modifier alone.)
        rows: SHEET.flatMap(([, rows]) => rows).filter(([keys]) => /[⌘⇧⌥⌃]$/.test(keys)).length,
      }};
    """)
    assert made == {
        "caps": [
            "⇧⌘N",
            "↩ ⇧↩",
            "N ⇧N",
            "⌥ (or) ⇧ ← → ↑ ↓",
            "Esc (or) ⌘↩",
            "⇧ (drag)",
            "⇧",
            "⌘' ⇧⌘'",
            "⇧⌘] ⇧⌘[",
        ],
        "bar": ["←→↑↓", "⌥←→↑↓", "↑↓", "⇧↑↓", "⌥ (or) ⇧ ←→", "← ⌫ →"],
        "rows": 0,
    }


def test_shown_until_hidden_kept_and_hidden_in_another_tab_too() -> None:
    made = run("""
      const k = await fresh();
      const was = [k.helpShown(), k.helpCommand().label];
      const told = [];
      k.onHelp((shown, how) => told.push([shown, how]));
      k.helpCommand().run();
      k.setHelpShown(false);  // hidden already: nothing
      const stored = kept.get("flexo-studio-help-bar");
      const again = (await fresh()).helpShown();
      const named = k.helpCommand().label;
      // Shown in another tab: shown here, not stored again.
      kept.set("flexo-studio-help-bar", "on");
      heard[0]({ key: "flexo-studio-help-bar" });
      return { was, told, stored, again, named, now: k.helpShown() };
    """)
    assert made == {
        "was": [True, "Hide Help Bar"],
        "told": [[False, "here"], [True, "stored"]],
        "stored": "off",
        "again": False,
        "named": "Show Help Bar",
        "now": True,
    }
