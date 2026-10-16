"""Shapes lined up and spaced (``studio/static/studio/aligning.js``): aligned to the selection,
the first or last chosen, the biggest, the smallest or the page, beside one, as a group;
spaced by their gaps, edges or middles, a set gap apart, in a grid; caught at an equal spacing
while one is dragged; and what the person chose, kept as snapping is -- run in Node, with this
browser's storage stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SCRIPT = STATIC / "aligning.js"

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
const A = await fresh();
// Moves, rounded, by id: { id: [dx, dy] }.
const moved = (moves) => Object.fromEntries(moves.map((m) => [m.id,
  [Math.round(m.dx * 1000) / 1000, Math.round(m.dy * 1000) / 1000]]));
const box = (x, y, w, h) => [x, y, x + w, y + h];
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


# Three shapes, chosen in this order: a small one at the right, a big one, a middling one.
THREE = """
const items = [
  { id: 4, box: box(300, 10, 20, 20) },
  { id: 1, box: box(100, 50, 80, 60) },
  { id: 2, box: box(10, 200, 40, 30) },
];
const page = [0, 0, 960, 540];
"""


def test_aligned_to_each_thing_they_may_be_aligned_to() -> None:
    made = run(
        THREE
        + """
      const way = (relative, side = "left") =>
        moved(A.alignMoves(items, side, { relative, page }).moves);
      return {
        selection: way("selection"), first: way("first"), last: way("last"),
        biggest: way("biggest"), smallest: way("smallest"), page: way("page", "right"),
        centre: way("biggest", "centre"), bottom: way("smallest", "bottom"),
        anchor: A.alignMoves(items, "top", { relative: "biggest", page }).anchor,
      };
    """
    )
    # The selection's bounds: each left edge at the leftmost (10); the one aligned to stays.
    assert made["selection"] == {"4": [-290, 0], "1": [-90, 0], "2": [0, 0]}
    assert made["first"] == {"1": [200, 0], "2": [290, 0]}
    assert made["last"] == {"4": [-290, 0], "1": [-90, 0]}
    assert made["biggest"] == {"4": [-200, 0], "2": [90, 0]}
    assert made["smallest"] == {"1": [200, 0], "2": [290, 0]}
    # The page's right edge, every one.
    assert made["page"] == {"4": [640, 0], "1": [780, 0], "2": [910, 0]}
    assert made["centre"] == {"4": [-170, 0], "2": [110, 0]}
    assert made["bottom"] == {"1": [0, -80], "2": [0, -200]}
    assert made["anchor"] == {"box": [100, 50, 180, 110], "id": 1}


def test_one_alone_is_aligned_to_the_page_whatever_is_chosen() -> None:
    made = run("""
      const one = [{ id: 0, box: box(100, 100, 50, 20) }];
      return ["selection", "biggest", "first"].map((relative) =>
        moved(A.alignMoves(one, "centre", { relative, page: [0, 0, 960, 540] }).moves));
    """)
    assert made == [{"0": [355, 0]}] * 3


def test_beside_puts_an_edge_against_the_other_side() -> None:
    made = run(
        THREE
        + """
      const way = (side) => moved(A.alignMoves(items, side, { relative: "biggest", page }).moves);
      return { left: way("left-of"), right: way("right-of"),
        above: way("above"), below: way("below") };
    """
    )
    # Right edges at the biggest's left edge (100); left edges at its right (180); bottoms at
    # its top (50); tops at its bottom (110).
    assert made == {
        "left": {"4": [-220, 0], "2": [50, 0]},
        "right": {"4": [-120, 0], "2": [170, 0]},
        "above": {"4": [0, 20], "2": [0, -180]},
        "below": {"4": [0, 100], "2": [0, -90]},
    }


def test_as_a_group_they_keep_their_places_among_themselves() -> None:
    made = run(
        THREE
        + """
      const way = (relative, side) =>
        moved(A.alignMoves(items, side, { relative, page, group: true }).moves);
      return { biggest: way("biggest", "left"), page: way("page", "right"),
        beside: way("biggest", "right-of"), selection: way("selection", "left") };
    """
    )
    # The two that move (the biggest stays) go together: their bounds' left edge (10) to 100.
    assert made["biggest"] == {"4": [90, 0], "2": [90, 0]}
    # All three, their bounds' right edge (320) to the page's (960).
    assert made["page"] == {"4": [640, 0], "1": [640, 0], "2": [640, 0]}
    assert made["beside"] == {"4": [170, 0], "2": [170, 0]}
    # To their own bounds, as a group: nowhere.
    assert made["selection"] == {"4": [0, 0], "1": [0, 0], "2": [0, 0]}


def test_a_locked_shape_stays_and_may_be_what_they_are_aligned_to() -> None:
    made = run("""
      const items = [
        { id: 0, box: box(10, 10, 20, 20) },
        { id: 1, box: box(400, 0, 300, 200), locked: true },
        { id: 2, box: box(50, 300, 40, 40) },
      ];
      const page = [0, 0, 960, 540];
      return { biggest: moved(A.alignMoves(items, "right", { relative: "biggest", page }).moves),
        selection: moved(A.alignMoves(items, "top", { relative: "selection", page }).moves) };
    """)
    assert made == {
        "biggest": {"0": [670, 0], "2": [610, 0]},
        # (The selection's bounds count it; it does not move.)
        "selection": {"0": [0, -10], "2": [0, -300]},
    }


def test_distributed_by_gaps_edges_and_middles() -> None:
    made = run("""
      const items = [
        { id: 0, box: box(0, 0, 10, 10) },
        { id: 1, box: box(25, 40, 30, 10) },
        { id: 2, box: box(100, 80, 20, 10) },
        { id: 3, box: box(200, 120, 40, 10), locked: true },
      ];
      const ways = ["across", "lefts", "centres", "rights", "down", "tops", "middles", "bottoms"];
      return Object.fromEntries(ways.map((way) => [way, moved(A.distributeMoves(items, way))]));
    """)
    # Gaps: 0..10, then 30 wide, then 20 wide ending at 120: (120 - 60) / 2 = 30 apart.
    assert made["across"] == {"0": [0, 0], "1": [15, 0], "2": [0, 0]}
    # Left edges 0 .. 100: the middle one's at 50.
    assert made["lefts"] == {"0": [0, 0], "1": [25, 0], "2": [0, 0]}
    # Centres 5 .. 110: the middle one's (40) at 57.5.
    assert made["centres"] == {"0": [0, 0], "1": [17.5, 0], "2": [0, 0]}
    assert made["rights"] == {"0": [0, 0], "1": [10, 0], "2": [0, 0]}
    # Down: tops at 0, 40, 80 already; the locked one is not counted.
    assert made["down"] == {"0": [0, 0], "1": [0, 0], "2": [0, 0]}
    assert made["tops"] == made["middles"] == made["bottoms"] == made["down"]


def test_two_are_not_distributed() -> None:
    made = run("""
      const items = [{ id: 0, box: box(0, 0, 10, 10) }, { id: 1, box: box(50, 0, 10, 10) }];
      return A.distributeMoves(items, "across");
    """)
    assert made == []


def test_a_set_gap_follows_from_the_first_in_the_order_they_are_in() -> None:
    made = run("""
      const items = [
        { id: 0, box: box(200, 0, 50, 20) },
        { id: 1, box: box(0, 30, 40, 20) },
        { id: 2, box: box(90, 60, 10, 20) },
      ];
      return { across: moved(A.spacedMoves(items, "across", 12)),
        down: moved(A.spacedMoves(items, "down", 5)),
        tight: moved(A.spacedMoves(items, "across", -5)) };
    """)
    assert made["across"] == {"1": [0, 0], "2": [-38, 0], "0": [-126, 0]}
    assert made["down"] == {"0": [0, 0], "1": [0, -5], "2": [0, -10]}
    # (A gap below nothing overlaps them.)
    assert made["tight"] == {"1": [0, 0], "2": [-55, 0], "0": [-160, 0]}


def test_a_grid_of_rows_and_columns_in_reading_order() -> None:
    made = run("""
      // Five panels in a rough row, a little up and down: in a grid of three columns.
      const items = [
        { id: "c", box: box(300, 4, 60, 40) },
        { id: "a", box: box(10, 0, 40, 30) },
        { id: "e", box: box(500, 2, 20, 20) },
        { id: "b", box: box(150, 8, 50, 50) },
        { id: "d", box: box(420, 0, 30, 30) },
      ];
      const grid = A.gridMoves(items,
        { columns: 3, gap: 10, gapDown: 20, align: "left", valign: "top" });
      const centred = A.gridMoves(items, { rows: 2, gap: 10 });
      return { grid: { ...grid, moves: moved(grid.moves) },
        centred: { ...centred, moves: moved(centred.moves) },
        order: A.readingOrder(items).map((item) => item.id),
        counts: [A.rowsFor(7, 3), A.columnsFor(7, 2), A.rowsFor(6, 0)] };
    """)
    assert made["order"] == ["a", "b", "c", "d", "e"]
    grid = made["grid"]
    assert (grid["rows"], grid["columns"]) == (2, 3)
    # Columns 40, 50 and 60 wide (a and d, b and e, c), rows 50 and 30 tall, from (10, 0):
    # lefts 10, 60 and 120; tops 0 and 70.
    assert grid["moves"] == {
        "a": [0, 0],
        "b": [-90, -8],
        "c": [-180, -4],
        "d": [-410, 70],
        "e": [-440, 68],
    }
    centred = made["centred"]
    assert (centred["rows"], centred["columns"]) == (2, 3)
    # Each in the middle of its cell: a (40 by 30) in 40 by 50 at (10, 0) -> y 10.
    assert centred["moves"]["a"] == [0, 10]
    assert made["counts"] == [3, 4, 6]


def test_kept_for_the_person_and_read_with_care() -> None:
    made = run("""
      const was = A.aligning();
      const told = [];
      A.onAligning((now, how) => told.push([now.to, now.group, now.gap, how]));
      A.setAlignTo("biggest"); A.setAsGroup(true); A.setGap(12.5); A.setAlignTo("nonsense");
      A.setGap("words");
      const stored = Object.fromEntries(kept);
      const again = (await fresh()).aligning();
      kept.set("flexo-studio-align-to", "elsewhere"); kept.set("flexo-studio-align-gap", "many");
      const odd = (await fresh()).aligning();
      fails = true;
      const unreadable = (await fresh()).aligning();
      return { was, told, stored, again, odd, unreadable };
    """)
    assert made["was"] == {"to": "selection", "group": False, "gap": 20}
    assert made["told"] == [
        ["biggest", False, 20, "here"],
        ["biggest", True, 20, "here"],
        ["biggest", True, 12.5, "here"],
    ]
    assert made["stored"] == {
        "flexo-studio-align-to": "biggest",
        "flexo-studio-align-group": "on",
        "flexo-studio-align-gap": "12.5",
    }
    assert made["again"] == {"to": "biggest", "group": True, "gap": 12.5}
    assert made["odd"] == {"to": "selection", "group": True, "gap": 20}
    assert made["unreadable"] == {"to": "selection", "group": False, "gap": 20}


def test_set_in_another_tab_it_is_set_here_without_storing_again() -> None:
    made = run("""
      const told = [];
      A.onAligning((now, how) => told.push([now.to, how]));
      const listener = heard[heard.length - 1];
      kept.set("flexo-studio-align-to", "last");
      let writes = 0;
      const set = storage.setItem;
      storage.setItem = (...args) => { writes += 1; set(...args); };
      listener({ key: "flexo-studio-align-to" });
      listener({ key: "flexo-studio-snapping" });
      return { told, to: A.alignTo(), writes };
    """)
    assert made == {"told": [["last", "stored"]], "to": "last", "writes": 0}


SPACED = """
// A row of three, 30 apart: 0..40, 70..110, 140..180 (all 0..40 down).
const row = [box(0, 0, 40, 40), box(70, 0, 40, 40), box(140, 0, 40, 40)];
"""


def test_a_drag_catches_at_its_rows_spacing_and_shows_each_gap_as_wide() -> None:
    made = run(
        SPACED
        + """
      const s = A.spacing(row);
      // Dragged near where it would be 30 after the last: 212 instead of 210.
      const near = s.caught(box(212, 5, 40, 40), 6);
      const placed = box(210, 5, 40, 40);
      const marks = s.marks(near.x, placed);
      // Too far to catch.
      const far = s.caught(box(230, 5, 40, 40), 6);
      // A column apart: nothing in it.
      const below = s.caught(box(212, 200, 40, 40), 6);
      return { near, far: far.x, below: below.x, marks };
    """
    )
    near = made["near"]
    assert near["x"]["shift"] == pytest.approx(-2)
    assert near["x"]["size"] == pytest.approx(30)
    assert near["y"] is None
    assert made["far"] is None
    assert made["below"] is None
    spans = sorted((m["from"], m["to"]) for m in made["marks"])
    assert spans == [(40, 70), (110, 140), (180, 210)]
    assert all(m["axis"] == 0 and m["size"] == 30 for m in made["marks"])


def test_a_drag_catches_midway_between_its_neighbours() -> None:
    made = run("""
      const s = A.spacing([box(0, 0, 40, 40), box(200, 10, 40, 40)]);
      // 60 wide between 40 and 200: midway is 90 .. 150, 50 either side.
      const found = s.caught(box(93, 0, 60, 30), 6);
      return { found: found.x, marks: s.marks(found.x, box(90, 0, 60, 30)) };
    """)
    assert made["found"]["shift"] == pytest.approx(-3)
    assert made["found"]["size"] == pytest.approx(50)
    assert sorted((m["from"], m["to"]) for m in made["marks"]) == [(40, 90), (150, 200)]


def test_a_drag_catches_down_a_column_too() -> None:
    made = run("""
      const column = [box(0, 0, 40, 20), box(5, 50, 30, 20)];
      const s = A.spacing(column);
      // 30 below the second (70): 100.
      return s.caught(box(0, 104, 40, 20), 6).y;
    """)
    assert made["shift"] == pytest.approx(-4)
    assert made["size"] == pytest.approx(30)
    assert made["axis"] == 1


def test_each_move_looks_at_each_box_once() -> None:
    made = run("""
      // Two hundred boxes, a grid of them: neighbours found once, then many moves.
      const boxes = [];
      for (let n = 0; n < 200; n++)
        boxes.push(box((n % 20) * 50, Math.floor(n / 20) * 60, 30 + (n % 3) * 5, 40));
      let t = performance.now();
      const s = A.spacing(boxes);
      const built = performance.now() - t;
      const moves = 2000;
      t = performance.now();
      let caught = 0;
      for (let n = 0; n < moves; n++) {
        const found = s.caught(box(1003 + (n % 50), 3 + (n % 400), 30, 40), 6);
        if (found.x || found.y) caught += 1;
      }
      const each = (performance.now() - t) / moves;
      return { built, each, caught, pairs: s.pairs[0].length };
    """)
    # Each box's neighbour across, in each row of twenty but the last.
    assert made["pairs"] == 190
    assert made["caught"] > 0
    # A move well within a frame: a few hundredths of a millisecond, here.
    assert made["each"] < 1.0
    assert made["built"] < 50


def test_objects_chosen_with_shapes_are_spread_among_as_fixed_members() -> None:
    made = run("""
      // Two objects (laid out: fixed) at 0..100 and 300..400, a shape 40 wide at 120.
      const three = [
        { id: "own:a", box: box(0, 0, 100, 50), locked: true, fixed: true },
        { id: 7, box: box(120, 10, 40, 20) },
        { id: "own:b", box: box(300, 0, 100, 50), locked: true, fixed: true },
      ];
      // An object among four shapes: each run either side of it spread on its own, it staying.
      const five = [
        { id: 0, box: box(0, 0, 20, 10) }, { id: 1, box: box(30, 0, 20, 10) },
        { id: "own:m", box: box(100, 0, 40, 10), locked: true, fixed: true },
        { id: 2, box: box(150, 0, 20, 10) }, { id: 3, box: box(300, 0, 20, 10) },
      ];
      const locked = { id: 9, box: box(0, 0, 5, 5), locked: true };
      return {
        three: moved(A.distributeMoves(three, "across")),
        centres: moved(A.distributeMoves(three, "centres")),
        five: moved(A.distributeMoves(five, "across")),
        can: [A.distributable(three), A.distributable(three.slice(0, 2)),
          A.distributable([three[0], three[2], { ...three[0], id: "own:c" }]),
          A.distributable([three[0], three[2], locked])],
        none: A.distributeMoves([three[0], three[2], locked], "across"),
      };
    """)
    # The gaps either side of the shape made equal: (300 - 100 - 40) / 2 = 80 -> 180.
    assert made["three"] == {"7": [60, 0]}
    # Centres 50 and 350: the shape's (140) at 200.
    assert made["centres"] == {"7": [60, 0]}
    # Left of the object: 20 .. 100 with 20 between, 30 either side (50). Right of it: 140 ..
    # 300, 70 either side (210). The first and the last stay.
    assert made["five"] == {"0": [0, 0], "1": [20, 0], "2": [60, 0], "3": [0, 0]}
    # Three or more taking part, one free to move: a locked shape is not one.
    assert made["can"] == [True, False, False, False]
    assert made["none"] == []


def test_objects_placed_with_shapes_are_aligned_and_spread_as_shapes_are() -> None:
    """A slide's objects the page moves with the shapes (placed where they are put, or taken
    out of line as they move: mixed.js's own.movable) are no fixed members: aligned, spread and
    gridded as shapes are -- one locked still staying, what the rest line up with."""

    made = run("""
      const text = { id: "own:t", box: box(48, 127, 414, 24) };
      const picture = { id: "own:p", box: box(498, 127, 358, 268) };
      const shape = { id: 0, box: box(80, 400, 120, 80) };
      const page = [0, 0, 960, 540];
      const three = [text, picture, shape];
      const locked = { ...picture, locked: true }, held = [text, locked, shape];
      const between = [text, { ...picture, box: box(300, 200, 100, 50) }, shape];
      return {
        left: moved(A.alignMoves(three, "left", { page }).moves),
        bottom: moved(A.alignMoves(three, "bottom", { page }).moves),
        right: moved(A.alignMoves(three, "right", { relative: "page", page }).moves),
        held: moved(A.alignMoves(held, "top", { page }).moves),
        heldAnchor: A.alignMoves(held, "top", { relative: "biggest", page }).anchor.id,
        spread: moved(A.distributeMoves(between, "down")),
        can: A.distributable(three),
      };
    """)
    # Their bounds' left edge, the text's: the picture and the shape move to it.
    assert made["left"] == {"own:t": [0, 0], "own:p": [-450, 0], "0": [-32, 0]}
    # The shape's bottom, the lowest: the objects move down to it.
    assert made["bottom"] == {"own:t": [0, 329], "own:p": [0, 85], "0": [0, 0]}
    assert made["right"] == {"own:t": [498, 0], "own:p": [104, 0], "0": [760, 0]}
    # A locked picture stays, and is what the others line up with where it is the biggest.
    assert made["held"].get("own:p", [0, 0]) == [0, 0] and made["heldAnchor"] == "own:p"
    # Spread down, the text and the shape outermost staying, the picture between them.
    assert made["spread"]["own:t"] == [0, 0] and made["spread"]["0"] == [0, 0]
    assert made["spread"]["own:p"][1] == pytest.approx(((400 - 151) - 50) / 2 + 151 - 200, abs=1e-3)
    assert made["can"] is True


def test_set_by_the_app_all_at_once_kept_and_told_once() -> None:
    made = run("""
      const told = [];
      A.onAligning((now, how) => told.push([now.to, now.group, now.gap, how]));
      A.setAligning({ to: "last", group: true, gap: 8 }, "app");
      A.setAligning({ to: "last", group: true, gap: 8 }, "app");
      A.setAligning({ to: "nowhere", group: "yes", gap: "wide" }, "app");
      A.setAligning({ gap: 0 });
      const stored = Object.fromEntries(kept);
      kept.set("flexo-studio-align-to", "first");
      A.setAligning({ to: "biggest" }, "stored");
      return { told, stored, after: Object.fromEntries(kept), now: A.aligning() };
    """)
    assert made["told"] == [
        ["last", True, 8, "app"],
        ["last", True, 0, "app"],
        ["biggest", True, 0, "stored"],
    ]
    assert made["stored"] == {
        "flexo-studio-align-to": "last",
        "flexo-studio-align-group": "on",
        "flexo-studio-align-gap": "0",
    }
    # (Another tab's, already kept: not stored again.)
    assert made["after"]["flexo-studio-align-to"] == "first"
    assert made["now"] == {"to": "biggest", "group": True, "gap": 0}


def test_an_edge_sized_catches_where_its_gap_is_as_wide_as_its_rows() -> None:
    made = run("""
      // A row, the one sized aside: 0..40, 140..180 and 210..250 (30 apart).
      const s = A.spacing([box(0, 0, 40, 40), box(140, 0, 40, 40), box(210, 0, 40, 40)]);
      // Its right edge at 108 (it starts at 70, 30 after the first): caught at 110.
      const right = s.edge(box(70, 0, 38, 40), 0, "end", 6);
      const marks = s.marks(right, box(70, 0, 40, 40));
      // Its left edge at 66 (it ends at 110, 30 before the next): caught at 70.
      const left = s.edge(box(66, 0, 44, 40), 0, "start", 6);
      // Too far from any.
      const far = s.edge(box(70, 0, 20, 40), 0, "end", 6);
      // Down a column: 0..20 and 50..70 (30 apart), 170..190; its bottom edge at 138.
      const column = A.spacing([box(0, 0, 40, 20), box(0, 50, 40, 20), box(0, 170, 40, 20)]);
      const down = column.edge(box(0, 100, 40, 38), 1, "end", 6);
      // Never past its own other edge: the gap wanted would put its end before its start.
      const narrow = A.spacing([box(0, 0, 10, 10), box(100, 0, 10, 10), box(140, 0, 10, 10)]);
      const past = narrow.edge(box(96, 0, 3, 10), 0, "start", 6);
      return { right, marks, left, far, down, past };
    """)
    assert made["right"]["shift"] == pytest.approx(2)
    assert made["right"]["size"] == pytest.approx(30)
    # Its gaps either side as wide, and the row's own.
    spans = sorted((m["from"], m["to"]) for m in made["marks"])
    assert spans == [(40, 70), (110, 140), (180, 210)]
    assert made["left"]["shift"] == pytest.approx(4)
    assert made["far"] is None
    assert made["down"]["shift"] == pytest.approx(2)
    assert made["down"]["axis"] == 1
    assert made["past"] is None


def test_sized_or_drawn_the_nearer_of_a_guide_and_an_equal_gap_wins() -> None:
    made = run("""
      const s = A.spacing([box(0, 0, 40, 40), box(140, 0, 40, 40), box(210, 0, 40, 40)]);
      // Sized by its right edge (it starts at 70): the pointer at 108; a guide at 105 is
      // nearer than the gap's 110 -- or, at 112, farther.
      const across = { x: true, y: false };
      const caughtAt = (to) => (value) =>
        (Math.abs(to - value) <= 6 ? { gap: to - value, at: to } : null);
      const at = (x, to) => A.sizeCatch(s, { point: [x, 20], fixed: [70, 20], box: [70, 0, 100, 40],
        sides: across, reach: 6, guide: caughtAt(to) });
      const even = at(108, 1000), guide = at(108, 107), both = at(108, 110);
      // None: guides alone (⌥, a shape turned); drawn, its corner (from 70, 0) across alone.
      const plain = A.sizeCatch(null, { point: [108, 20], fixed: [70, 20], box: [70, 0, 100, 40],
        sides: across, reach: 6, guide: () => null });
      const drawn = A.sizeCatch(s, { point: [108, 38], fixed: [70, 0], box: [70, 0, 70, 0],
        sides: { x: true, y: true }, reach: 6, guide: () => null, ways: across });
      const made = [70, 0, 110, 40];
      return { even: even.point, evenMarks: even.marks(made).length,
        guide: [guide.point, guide.guides],
        both: [both.point, both.guides, both.marks(made).length],
        plain: plain.point, drawn: drawn.point };
    """)
    assert made["even"] == [110, 20]
    assert made["evenMarks"] == 3
    assert made["guide"] == [[107, 20], [{"axis": "x", "at": 107}]]
    # (One place for both: the guide drawn, and the gaps marked.)
    assert made["both"] == [[110, 20], [{"axis": "x", "at": 110}], 3]
    assert made["plain"] == [108, 20]
    assert made["drawn"] == [110, 38]


ORDERING = """
const O = await import(new globalThis.URL("./ordering.js", URL).href);
"""


def test_first_and_last_chosen_follow_the_clicks_not_the_list() -> None:
    made = run(
        ORDERING
        + """
      const order = O.chosenOrder();
      // Clicked: the fourth, then the second, then the third (⇧).
      order.chose([], [3]); order.chose([3], [3, 1]); order.chose([3, 1], [3, 1, 2]);
      const clicked = order.ordered([1, 2, 3]);
      const kept = order.entries();
      // Brought to front, the second and third: [s0, s1, s2, s3] -> [s0, s3, s1, s2].
      const was = ["s0", "s1", "s2", "s3"], now = ["s0", "s3", "s1", "s2"];
      order.moved(O.placesAfter(was, now));
      const fronted = order.ordered([1, 2, 3]);
      // One moved where it is (another made in its place), one taken away before it.
      const places = O.placesAfter(["a", "b", "c"], ["a", "B", "c"]);
      const gone = O.placesAfter(["a", "b", "c"], ["b", "c"]);
      // Undone: as it was then.
      order.restore(kept);
      const undone = order.ordered([1, 2, 3]);
      // One taken out and put back in: chosen again, last.
      order.chose([1, 2, 3], [1, 2]); order.chose([1, 2], [1, 2, 3]);
      const again = order.ordered([1, 2, 3]);
      order.chose([1, 2, 3], []);
      return { clicked, fronted, undone, again, places: [0, 1, 2].map(places),
        gone: [0, 1, 2].map(gone), cleared: order.entries() };
    """
    )
    assert made["clicked"] == [3, 1, 2]
    # By the shape, not its place: the fourth, first chosen, is now second in the list.
    assert made["fronted"] == [1, 2, 3]
    assert made["places"] == [0, 1, 2]
    assert made["gone"] == [-1, 0, 1]
    assert made["undone"] == [3, 1, 2]
    assert made["again"] == [1, 2, 3]
    assert made["cleared"] == []


def test_a_band_chooses_in_reading_order_after_what_it_kept() -> None:
    made = run(
        ORDERING
        + """
      const boxes = { 0: box(200, 0, 10, 10), 1: box(0, 100, 10, 10), 2: box(0, 0, 10, 10),
        3: box(100, 2, 10, 10), 4: box(0, 300, 5, 5) };
      const at = (key) => boxes[key];
      const order = O.chosenOrder();
      order.chose([], [3]);
      // ⇧ and a band, growing: the right one touched first, then two more.
      order.pressed(true);
      order.chose([3], [3, 0], { band: at });
      order.chose([3, 0], [3, 0, 1, 2], { band: at });
      const kept = order.ordered([0, 1, 2, 3]);
      // Then one clicked: after them all.
      order.pressed(true);
      order.chose([0, 1, 2, 3], [0, 1, 2, 3, 4]);
      const clicked = order.ordered([0, 1, 2, 3, 4]);
      // A band of its own (no ⇧): none kept, all in reading order.
      order.pressed(false);
      order.chose([0, 1, 2, 3, 4], [0, 3], { band: at });
      return { kept, clicked, fresh: order.ordered([0, 3]) };
    """
    )
    # The one clicked before it first; then top to bottom, left to right.
    assert made["kept"] == [3, 2, 0, 1]
    assert made["clicked"] == [3, 2, 0, 1, 4]
    assert made["fresh"] == [3, 0]


def test_one_order_across_a_slides_objects_and_its_shapes() -> None:
    made = run(
        ORDERING
        + """
      const own = O.chosenOrder(), shapes = O.chosenOrder();
      // An object chosen, then a shape (⇧), then another object, then another shape.
      own.chose([], ["own:a"]); shapes.chose([], [5]);
      own.chose(["own:a"], ["own:a", "own:b"]); shapes.chose([5], [5, 2]);
      const boxes = { "own:a": box(0, 200, 10, 10), "own:b": box(0, 0, 10, 10),
        2: box(50, 0, 10, 10), 5: box(50, 200, 10, 10) };
      const kind = (keys, order) => ({ keys: () => keys, stampOf: order.stampOf,
        stampAs: order.stampAs, box: (key) => boxes[key] });
      const both = O.acrossOrder([kind(["own:a", "own:b"], own), kind([2, 5], shapes)]);
      const clicks = both.ordered();
      // A band across both, keeping the second shape (⇧): it first, the rest as they read.
      both.banded({ kept: new Set([2]), base: null });
      return { clicks, banded: both.ordered() };
    """
    )
    assert made["clicks"] == ["own:a", 5, "own:b", 2]
    assert made["banded"] == [2, "own:b", "own:a", 5]
