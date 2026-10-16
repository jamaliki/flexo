"""The grid over a page (``studio/static/studio/grid.js``): hidden until shown, kept for the
person, its squares sized to the page or as its host says, and what a drag catches at on it --
run in Node, with this browser's storage stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "grid.js"

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


def test_hidden_until_shown_kept_and_shown_in_another_tab_too() -> None:
    made = run("""
      const g = await fresh();
      const was = g.gridShown();
      const told = [];
      g.onGrid((shown, how) => told.push([shown, how]));
      g.toggleGrid();
      g.setGrid(true);  // shown already: nothing
      const stored = kept.get("flexo-studio-grid");
      const again = (await fresh()).gridShown();
      // Hidden in another tab: hidden here, not stored again.
      kept.set("flexo-studio-grid", "off");
      heard[0]({ key: "flexo-studio-grid" });
      return { was, told, stored, again, now: g.gridShown() };
    """)
    assert made == {
        "was": False,
        "told": [[True, "here"], [False, "stored"]],
        "stored": "on",
        "again": True,
        "now": False,
    }


def test_its_squares_are_the_hosts_or_sized_to_the_page() -> None:
    made = run("""
      const g = await fresh();
      return {
        // A wide slide, as a deck says: squares of 12, every fifth line darker -- 80 by 45.
        slide: g.spacingOf([0, 0, 960, 540], { step: 12, major: 5 }),
        lines: (({ xs, ys }) => [xs.length, ys.length, xs.at(-1), ys.at(-1)])(
          g.linesOf([0, 0, 960, 540], 12)),
        // A figure says nothing: the round number nearest an 80th of it.
        figure: g.spacingOf([0, 0, 510.24, 147]),
        wide: g.spacingOf([0, 0, 2000, 1000]),
        // Never more than 400 across, whatever is asked.
        fine: g.spacingOf([0, 0, 960, 540], { step: 0.5 }),
        // From the page's top left, wherever that is.
        moved: g.linesOf([-10, 5, 30, 10], 10),
      };
    """)
    assert made == {
        "slide": {"step": 12, "major": 5},
        "lines": [81, 46, 960, 540],
        "figure": {"step": 5, "major": 5},
        "wide": {"step": 25, "major": 5},
        "fine": {"step": 2.4, "major": 5},
        "moved": {"xs": [-10, 0, 10, 20], "ys": [5, 15]},
    }


def test_snapping_to_it_catches_at_its_lines_and_its_layout() -> None:
    made = run("""
      const g = await fresh();
      // A slide 120 by 60, squares of 12; its layout a margin at 6 and 114, and a place.
      const layout = { xs: [6, 114], ys: [6], boxes: [[6, 18, 54, 54]] };
      const t = g.targetsOf([0, 0, 120, 60], { step: 12, layout });
      const sorted = (values) => [...values].sort((a, b) => a - b);
      return {
        xs: sorted(t.xs), ys: sorted(t.ys),
        // A box's middle catches at the layout's lines and the page's middles alone.
        edgesX: sorted(t.xs.edges), edgesY: sorted(t.ys.edges),
        boxes: t.boxes, grid: t.grid,
        // A place that is no box is left out.
        odd: g.targetsOf([0, 0, 24, 24],
          { step: 12, layout: { boxes: [[5, 5, 1, 1], "box", [1, 2, 3]] } }).xs.length,
      };
    """)
    assert made == {
        "xs": [0, 6, 12, 24, 30, 36, 48, 54, 60, 72, 84, 96, 108, 114, 120],
        "ys": [0, 6, 12, 18, 24, 30, 36, 48, 54, 60],
        "edgesX": [0, 12, 24, 36, 48, 72, 84, 96, 108, 120],
        "edgesY": [0, 12, 24, 48, 60],
        "boxes": [],
        "grid": True,
        "odd": 3,
    }
