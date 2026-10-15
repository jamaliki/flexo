"""Snapping on or off (``studio/static/studio/snapping.js``): what ⌘ does to a drag either way,
kept for the person from one launch to the next, and turned in one tab, turned in the others --
run in Node, with this browser's storage stood in for."""

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
