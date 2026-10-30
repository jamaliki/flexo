"""Snapping to guides, to the grid or off (``studio/static/studio/snapping.js``): what ⌘ does to
a drag either way, kept for the person from one launch to the next, turned in one tab, turned in
the others, and what a box catches at on the grid -- run in Node, with this browser's storage
stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SCRIPT = STATIC / "snapping.js"

# This browser's storage and window, stood in for before the module is read: `kept` is what
# the storage holds, `fails` makes it throw, `heard` the window's storage listener.
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


def test_on_command_frees_a_drag_and_off_command_catches() -> None:
    made = run("""
      const s = await fresh();
      const drag = (meta, ctrl = false) => ({ metaKey: meta, ctrlKey: ctrl });
      const ways = () => ({ plain: s.free(drag(false)), command: s.free(drag(true)),
        control: s.free(drag(false, true)), held: s.free(true), none: s.free(undefined),
        hint: s.withCommand() });
      const on = { snapping: s.snapping(), ...ways() };
      s.setSnapping(false);
      const off = { snapping: s.snapping(), ...ways() };
      return { on, off };
    """)
    assert made == {
        "on": {
            "snapping": True,
            "plain": False,
            "command": True,
            "control": True,
            "held": True,
            "none": False,
            "hint": "without snapping",
        },
        "off": {
            "snapping": False,
            "plain": True,
            "command": False,
            "control": False,
            "held": False,
            "none": True,
            "hint": "with snapping",
        },
    }


def test_it_is_kept_for_the_next_launch_and_read_with_care() -> None:
    made = run("""
      const first = await fresh();
      const was = first.snapping();
      first.toggleSnapping();
      const stored = kept.get("flexo-studio-snapping");
      const again = (await fresh()).snapping();
      kept.set("flexo-studio-snapping", "nonsense");
      const odd = (await fresh()).snapping();
      fails = true;
      const unreadable = (await fresh()).snapping();
      // (Turned while the storage refuses: turned all the same, in this window.)
      const refused = (await fresh());
      refused.setSnapping(false);
      return { was, stored, again, odd, unreadable, refused: refused.snapping() };
    """)
    # On to start with; turned off, kept off; anything else kept (or nothing readable) is on.
    assert made == {
        "was": True,
        "stored": "off",
        "again": False,
        "odd": True,
        "unreadable": True,
        "refused": False,
    }


def test_those_listening_are_told_once_each_time_it_turns() -> None:
    made = run("""
      const s = await fresh();
      const told = [];
      const stop = s.onSnapping((on, how) => told.push([on, how]));
      s.setSnapping(true);           // already on: nothing
      s.toggleSnapping();            // off, here
      s.setSnapping(false, "app");   // already off: nothing
      s.setSnapping(true, "app");    // on, from another window of the app
      stop();
      s.toggleSnapping();            // no longer listened to
      return { told, kept: kept.get("flexo-studio-snapping") };
    """)
    assert made == {"told": [[False, "here"], [True, "app"]], "kept": "off"}


def test_turned_in_another_tab_it_turns_here_without_storing_again() -> None:
    made = run("""
      const s = await fresh();
      const told = [];
      s.onSnapping((on, how) => told.push([on, how]));
      const listener = heard[heard.length - 1];
      // Another tab turned it off: its storage says so, and this one is told.
      kept.set("flexo-studio-snapping", "off");
      let writes = 0;
      const set = storage.setItem;
      storage.setItem = (...args) => { writes += 1; set(...args); };
      listener({ key: "flexo-studio-snapping" });
      listener({ key: "something else" });
      const off = s.snapping();
      // Its storage cleared (null key): on again, as with nothing kept.
      kept.clear();
      listener({ key: null });
      return { told, off, on: s.snapping(), writes };
    """)
    assert made == {
        "told": [[False, "stored"], [True, "stored"]],
        "off": False,
        "on": True,
        "writes": 0,
    }


def test_the_magnet_goes_from_guides_to_the_grid_to_off_and_round_again() -> None:
    made = run("""
      const s = await fresh();
      const told = [];
      s.onSnapping((on, how, mode) => told.push([on, how, mode]));
      const seen = [s.snapMode()];
      for (let turn = 0; turn < 3; turn += 1) seen.push(s.cycleSnapping());
      // On to the grid, then turned on: still the grid's; off, then on: guides.
      s.setSnapMode("grid");
      const stays = s.setSnapping(true) && s.snapMode();
      s.setSnapping(false);
      s.setSnapping(true);
      const back = s.snapMode();
      s.setSnapMode("sideways");
      return { seen, told: told.slice(0, 3), stays, back, odd: s.snapMode(),
        grid: (s.setSnapMode("grid"),
          [s.snapping(), s.toGrid(), s.toGuides(), s.free(false), s.free(true), s.snapWord()]) };
    """)
    assert made == {
        "seen": ["guides", "grid", "off", "guides"],
        "told": [[True, "here", "grid"], [False, "here", "off"], [True, "here", "guides"]],
        "stays": "grid",
        "back": "guides",
        "odd": "guides",
        # Snapping to the grid is snapping: ⌘ frees a drag, as it does from guides.
        "grid": [True, True, False, False, True, "grid"],
    }


def test_the_grid_is_kept_as_its_word_and_read_back() -> None:
    made = run("""
      const first = await fresh();
      first.setSnapMode("grid");
      const stored = kept.get("flexo-studio-snapping");
      const again = (await fresh()).snapMode();
      first.setSnapMode("guides");
      return { stored, again, guides: kept.get("flexo-studio-snapping"),
        words: ["on", "grid", "off", "maybe", undefined].map((word) => first.fromWord(word)) };
    """)
    assert made == {
        "stored": "grid",
        "again": "grid",
        "guides": "on",
        "words": ["guides", "grid", "off", None, None],
    }


def test_a_box_catches_at_the_grid_by_its_edges_and_at_the_layout_by_its_middle_too() -> None:
    made = run("""
      const s = await fresh();
      // Squares' lines at 0, 12, 24, 36; a layout's at 30 (its middle may catch there).
      const values = [0, 12, 24, 30, 36];
      values.edges = new Set([0, 12, 24, 36]);
      return {
        // A box 3.4 wide, its middle a hair from 12 -- but on the squares a middle does not
        // catch; its left does, at 12, a little further.
        edges: s.nearest([10.5, 12.2, 13.9], values, 2),
        // Its middle near the layout's line: caught there.
        middle: s.nearest([26.5, 29.5, 32.5], values, 2),
        // A point catches at the squares' lines by itself.
        point: s.nearest([11], values, 2),
        // Guides (no edges said): any of the three, as ever.
        guides: s.nearest([13.5, 18.5, 23.5], [19], 2),
        none: s.nearest([5], values, 2),
      };
    """)
    assert made == {
        "edges": {"gap": 1.5, "at": 12},
        "middle": {"gap": 0.5, "at": 30},
        "point": {"gap": 1, "at": 12},
        "guides": {"gap": 0.5, "at": 19},
        "none": None,
    }


def test_a_side_sized_catches_where_it_is_as_wide_as_another() -> None:
    made = run("""
      const s = await fresh();
      const boxes = [[0, 0, 40, 30], [100, 0, 160, 20], [0, 100, 40.0004, 120], [5, 5, 5.5, 50]];
      const [widths, heights] = s.sizesOf(boxes);
      return {
        widths, heights,
        // Its right edge at 158, its left at 100: 58 wide, near another's 60.
        right: s.sizeAt(158, 100, widths, 4),
        // Its left edge dragged out to 63, its right at 100: 37 wide, near 40.
        left: s.sizeAt(63, 100, widths, 4),
        far: s.sizeAt(150, 100, widths, 4),
        same: s.sameSize(boxes, 40, 0).length,
      };
    """)
    # Each size once, and none a hair wide (a line's box, edge on).
    assert sorted(made["widths"]) == [40, 60]
    assert sorted(made["heights"]) == [20, 30, 45]
    assert made["right"] == {"shift": 2, "size": 60}
    assert made["left"] == {"shift": -3, "size": 40}
    assert made["far"] is None
    assert made["same"] == 2
