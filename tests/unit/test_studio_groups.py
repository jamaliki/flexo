"""Groups entered as Inkscape's are, and taken apart at every level (``studio/static/studio/
groups.js``): a group's shapes written back into it, the page's host seen from inside one, going
in, out and back after an undo, Return, Esc and ⌘A, Ungroup All -- run in Node, the shapes'
editor stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "groups.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run(body: str, page: list | None = None) -> object:
    script = (
        f"const G = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"const PAGE = {json.dumps(page or [])};\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def box(x: float, y: float, **more: object) -> dict:
    return {"kind": "rectangle", "at": [x, y], "size": [10, 10], **more}


def group(*shapes: dict, **more: object) -> dict:
    return {"kind": "group", "shapes": list(shapes), **more}


WRITTEN = [box(0, 0), group(box(10, 0), group(box(20, 0, id="deep"), box(30, 0)), build=True)]


def test_a_group_s_shapes_are_written_back_into_it_and_nothing_else_is_changed() -> None:
    made = run(
        """
      const kept = JSON.stringify(PAGE);
      const moved = G.within(PAGE, [1, 1], (shapes) => {
        shapes[0] = { ...shapes[0], at: [25, 5] };
      });
      // Put in from the page: what only the page says of a shape (a build, a part it is on)
      // taken off, but locked; answered anew, as a list.
      const strip = G.strippedKeys(["behind", "build", "hidden", "locked"]);
      const put = { kind: "ellipse", at: [0, 0], size: [5, 5], build: true, on: "a", locked: true };
      const pasted = G.within(PAGE, [1], (shapes) => [...shapes, put], { strip });
      return {
        moved, pasted: pasted[1].shapes[2], strip,
        untouched: JSON.stringify(PAGE) === kept,
        shared: moved[0] === PAGE[0] && moved[1].shapes[0] === PAGE[1].shapes[0],
        found: G.groupAt(PAGE, [1, 1]).shapes.length, gone: G.groupAt(PAGE, [1, 0]),
        reached: G.reached(PAGE, [1, 1, 0, 4]),
        top: G.within(PAGE, [], (shapes) => shapes.slice(1)).length,
      };
    """,
        WRITTEN,
    )
    inner = made["moved"][1]["shapes"][1]["shapes"]
    assert inner == [{**box(25, 5), "id": "deep"}, box(30, 0)]
    assert made["moved"][1]["build"] is True
    # (The page as it was, untouched; what was not on the way to the change, the same objects.)
    assert made["untouched"] and made["shared"]
    assert made["pasted"] == {"kind": "ellipse", "at": [0, 0], "size": [5, 5], "locked": True}
    assert made["found"] == 2 and made["gone"] is None
    assert made["reached"] == 2 and made["top"] == 1
    assert set(made["strip"]) == {"behind", "build", "hidden", "on", "around", "margin", "side"}


def test_a_group_left_with_no_shapes_goes_and_so_does_one_left_empty_by_it() -> None:
    page = [box(0, 0), group(group(box(10, 0))), group(box(5, 5), group(box(1, 1)))]
    made = run(
        """
      return { both: G.within(PAGE, [1, 0], () => []), inner: G.within(PAGE, [2, 1], () => []) };
    """,
        page,
    )
    # (A group is one shape at least: emptied, it goes -- and the group it alone was in.)
    assert made["both"] == [box(0, 0), group(box(5, 5), group(box(1, 1)))]
    assert made["inner"][2] == group(box(5, 5))


def test_ungroup_all_takes_every_level_apart_as_it_was_drawn() -> None:
    made = run("""
      const shape = (kind, more = {}) => ({ kind, at: [0, 0], size: [1, 1], ...more });
      const drawing = { kind: "group", opacity: 0.5, shapes: [
        shape("rectangle"),
        { kind: "group", shapes: [shape("ellipse", { opacity: 0.5 }),
          { kind: "group", opacity: 0.4, shapes: [shape("star")] }] },
      ] };
      const plain = { kind: "group", shapes: [{ kind: "text", at: [0, 0], text: "A" }] };
      const empty = { kind: "group", shapes: [] };
      return {
        leaves: G.leaves(drawing), plain: G.leaves(plain),
        nested: [G.nested(drawing), G.nested(plain), G.nested(null)],
        enterable: [G.enterable(plain), G.enterable({ ...plain, locked: true }),
          G.enterable(empty), G.enterable(plain.shapes[0])],
      };
    """)
    # In order, each with the opacity the groups round it gave it.
    assert [leaf["kind"] for leaf in made["leaves"]] == ["rectangle", "ellipse", "star"]
    assert [leaf.get("opacity") for leaf in made["leaves"]] == [0.5, 0.25, 0.2]
    assert made["plain"] == [{"kind": "text", "at": [0, 0], "text": "A"}]
    assert made["nested"] == [True, False, False]
    assert made["enterable"] == [True, False, False, False]


# The page's host as a deck's slide gives it (editor.js): its list, its edits (kept), its ids,
# its marks, its own commands and settings for its shapes.
HOST = """
const page = { shapes: PAGE };
const marks = [], edits = [];
const host = {
  ownKeys: ["behind", "build", "hidden", "locked"], noun: "slide", crumb: () => "Slide 1",
  page: () => 0, list: () => page.shapes, source: () => "slide:0",
  edit: (mutate, options) => {
    page.shapes = mutate(structuredClone(page.shapes));
    edits.push(options.label);
    return true;
  },
  idOf: (index, at = 0) => `slide${at + 1}.shapes.${index}`,
  mark: (said) => marks.push(said),
  commands: () => ["Build In on Click"], panel: () => ["Builds"], grouped: () => ({}),
  ungrouped: (group) => (group.build ? { build: true } : {}),
  attachNew: (spec) => spec, drawnAt: () => null,
};
"""


def test_from_inside_a_group_the_page_is_the_group_s_shapes() -> None:
    page = [box(0, 0, id="a"), group(box(10, 0), group(box(20, 0), box(30, 0)), build=True)]
    made = run(
        HOST
        + """
      let where = [];
      const seen = G.scoped(host, () => where);
      const outside = { list: seen.list().length, commands: seen.commands(),
        id: seen.idOf(1), source: seen.source() };
      where = [1, 1];
      const own = ["commands", "panel", "grouped", "ungrouped", "attachNew", "drawnAt"];
      const inside = {
        list: seen.list(), ids: [seen.idOf(0), seen.idOf(1, 2)], source: seen.source(),
        own: own.map((key) => seen[key] === undefined), crumb: seen.crumb(), noun: seen.noun,
      };
      const lock = (shapes) => { shapes[1].locked = true; shapes[1].build = true; return shapes; };
      seen.edit(lock, { label: "Lock Shape" });
      seen.mark({ slide: 0, before: [1], after: [1] });
      // The group gone meanwhile (an undo, another's change): nothing written.
      where = [0, 1];
      const refused = seen.edit(() => [], { label: "Delete" });
      return { outside, inside, page: page.shapes, marks, edits, refused };
    """,
        page,
    )
    assert made["outside"] == {
        "list": 2,
        "commands": ["Build In on Click"],
        "id": "slide1.shapes.1",
        "source": "slide:0",
    }
    inside = made["inside"]
    assert inside["list"] == [box(20, 0), box(30, 0)]
    assert inside["ids"] == ["slide1.shapes.1.1.0", "slide3.shapes.1.1.1"]
    assert inside["source"] == "slide:0 \u203a 1.1"
    assert all(inside["own"]) and inside["crumb"] == "Slide 1" and inside["noun"] == "slide"
    # Written into the group, as one edit of the page's: locked kept, a build not (the group's).
    assert made["page"][1]["shapes"][1]["shapes"][1] == {**box(30, 0), "locked": True}
    assert made["page"][1]["build"] is True and made["edits"] == ["Lock Shape"]
    assert made["marks"] == [{"slide": 0, "before": [1], "after": [1], "inside": [1, 1]}]
    assert made["refused"] is False


# The shapes' editor, stood in for: shapes are hit where their box is, what it chose kept.
EDITOR = (
    HOST
    + """
const node = () => ({
  children: [], setAttribute() {}, append(...more) { this.children.push(...more); },
  replaceChildren() { this.children = []; }, get firstChild() { return this.children[0] || null; },
});
const tools = G.groupTools(host);
const seen = tools.host;
let chosen = [];
const hits = (spec, [x, y]) => (spec.kind === "group" ? spec.shapes.some((one) => hits(one, [x, y]))
  : x >= spec.at[0] && x <= spec.at[0] + spec.size[0]
    && y >= spec.at[1] && y <= spec.at[1] + spec.size[1]);
const hit = (event) => {
  const list = seen.list(), point = [event.clientX, event.clientY];
  for (let n = list.length - 1; n >= 0; n -= 1) if (hits(list[n], point)) return n;
  return null;
};
tools.bind({
  S: node, h: node, icon: node, ui: { button: (label) => label }, layer: { insertBefore() {} },
  before: null, pageNode: () => null, toScreen: (point) => point, unit: () => 1,
  list: () => seen.list(), chosen: () => chosen.filter((n) => n < seen.list().length),
  choose: (picks) => { chosen = [...picks]; }, hit, union: () => [0, 0, 1, 1], busy: () => false,
  settle() {}, place() {}, renderInspector() {}, reportFocus() {},
  edit: (mutate, label, options = {}) => {
    chosen = options.after || chosen;
    seen.edit((list) => mutate(list) || list, { label });
  },
  ungrouped: (...args) => seen.ungrouped?.(...args), crumb: () => "Slide 1",
  label: (spec) => (spec?.kind === "group" ? "Group" : "Shape"),
});
const unmodified = { metaKey: false, ctrlKey: false, altKey: false, shiftKey: false };
const key = (key, more = {}) => tools.key({ key, ...unmodified, ...more });
const at = (x, y) => ({ clientX: x, clientY: y });
"""
)

# A page: a box, then a drawing (a group: its frame, and a group of two boxes and a group).
DRAWING = [
    box(200, 200, id="alone"),
    group(
        box(0, 0, size=[100, 100]),
        group(box(10, 10, id="b1"), box(40, 10), group(box(10, 60), box(40, 60, id="b4"))),
    ),
]


def drawn(body: str) -> object:
    return run(EDITOR + body, DRAWING)


def test_a_group_is_entered_a_level_at_a_time_and_left_again() -> None:
    made = drawn("""
      const steps = {};
      // Double-clicked: in it, what is under the pointer in it chosen (its group of boxes).
      steps.entered = [tools.enter(1, { at: at(15, 15) }), tools.path(), chosen];
      steps.deeper = [tools.enter(1, { at: at(45, 15) }), tools.path(), chosen];
      steps.box = [tools.enter(2), tools.path(), chosen];
      // Out a level, the group left chosen; Esc with nothing chosen does it too.
      steps.out = [tools.out(), tools.path(), chosen];
      chosen = [];
      steps.esc = [key("Escape"), tools.path(), chosen];
      // Return goes into the group chosen; ⌘A there chooses all its shapes.
      chosen = [1];
      steps.ret = [key("Enter"), tools.path(), chosen];
      steps.all = [key("a", { metaKey: true }), chosen];
      // Not a box, nor a locked group.
      steps.notBox = tools.enter(0);
      steps.leave = [tools.leave(), tools.path(), chosen, tools.depth()];
      steps.esc0 = key("Escape");
      return steps;
    """)
    assert made["entered"] == [True, [1], [1]]
    assert made["deeper"] == [True, [1, 1], [1]]
    assert made["box"] == [True, [1, 1, 2], []]
    assert made["out"] == [True, [1, 1], [2]]
    assert made["esc"] == [True, [1], [1]]
    assert made["ret"] == [True, [1, 1], []]
    assert made["all"] == [True, [0, 1, 2]]
    assert made["notBox"] is False
    assert made["leave"] == [True, [], [], 0]
    assert made["esc0"] is False


def test_a_drawing_made_editable_is_entered_as_deep_as_the_point_as_option_click_is() -> None:
    made = drawn("""
      const deep = [tools.enter(1, { at: at(45, 65), deep: true }), tools.path(), chosen];
      tools.leave();
      // ⌥-click from the page: the box under the pointer, the groups round it entered.
      const option = [tools.deepPick(at(15, 15)), tools.path(), chosen];
      tools.leave();
      const none = tools.deepPick(at(500, 500));
      return { deep, option, none };
    """)
    assert made["deep"] == [True, [1, 1, 2], [1]]
    assert made["option"] == [True, [1, 1], [0]]
    assert made["none"] is False


def test_pressed_outside_the_group_one_is_taken_to_what_was_pressed() -> None:
    made = drawn("""
      tools.enter(1, { at: at(45, 65), deep: true });
      // A box beside the group one is in, in the group round it: out to there, nothing chosen
      // yet (the press chooses it).
      const beside = [tools.outward(at(15, 15)), tools.path(), chosen];
      // The drawing's frame, a level up: out to the drawing.
      const frame = [tools.outward(at(80, 90)), tools.path()];
      // A shape on the page: out of every group.
      const onPage = [tools.outward(at(205, 205)), tools.path()];
      tools.enter(1);
      const empty = [tools.outward(at(500, 500)), tools.path(), chosen];
      return { beside, frame, onPage, empty };
    """)
    assert made["beside"] == [0, [1, 1], []]
    assert made["frame"] == [0, [1]]
    assert made["onPage"] == [0, []]
    assert made["empty"] == [None, [], []]


def test_undone_inside_a_group_one_is_inside_again_once_it_is_there() -> None:
    made = drawn("""
      const now = [tools.restore({ slide: 0, inside: [1, 1] }, [0]), tools.path()];
      const top = [tools.restore({ slide: 0 }, [0]), tools.path()];
      // Not there yet (a figure drawn again only later): waited for, entered once it is.
      const later = [tools.restore({ slide: 0, inside: [2] }, [0]), tools.path()];
      const one = { kind: "rectangle", at: [0, 0], size: [1, 1] };
      host.list().push({ kind: "group", shapes: [one] });
      const there = [tools.check(), tools.path(), chosen];
      // Gone (another's change): out to the level still there.
      tools.leave();
      tools.enter(1);
      tools.enter(1);
      host.list()[1].shapes.splice(1, 1);
      const gone = [tools.check(), tools.path()];
      return { now, top, later, there, gone };
    """)
    assert made["now"] == [True, [1, 1]]
    assert made["top"] == [True, []]
    assert made["later"] == [False, []]
    assert made["there"] == [True, [2], [0]]
    assert made["gone"] == [True, [1]]


NESTED = [
    box(0, 0),
    group(box(1, 1), group(box(2, 2), group(box(3, 3))), build=True),
    group(box(5, 5)),
]


def test_ungroup_all_and_the_commands_offered_for_groups() -> None:
    made = run(
        EDITOR
        + """
      const named = (list) => list.map((command) => command.label);
      const command = (label) => tools.commands().find((one) => one.label === label);
      chosen = [1];
      const offered = named(tools.commands());
      tools.ungroupAll();
      const after = { list: host.list(), chosen, edits };
      chosen = [0];
      const box = named(tools.commands());
      tools.enter(4);
      const inside = named(tools.commands());
      return { offered, after, box, inside, menu: named(tools.menuItems(command)) };
    """,
        NESTED,
    )
    assert made["offered"] == ["Enter Group", "Ungroup All"]
    # Every level apart, one step, what the page says of the group (its build) each shape's.
    taken = [{**box(n, n), "build": True} for n in (1, 2, 3)]
    assert made["after"]["list"] == [box(0, 0), *taken, group(box(5, 5))]
    assert made["after"]["chosen"] == [1, 2, 3] and made["after"]["edits"] == ["Ungroup All"]
    assert made["box"] == []
    assert made["inside"] == ["Leave Group"] and made["menu"] == ["Leave Group"]


def test_inside_a_group_every_name_on_the_page_is_known() -> None:
    made = drawn("""
      const outside = tools.names();
      tools.enter(1, { at: at(15, 15) });
      const first = tools.names();
      return { outside, inside: first, same: tools.names() === first };
    """)
    assert made["outside"] == [] and made["inside"] == ["alone", "b1", "b4"] and made["same"]


def test_a_group_s_shape_may_be_locked_where_the_page_lets_its_shapes_be() -> None:
    # (Locked while the group is entered in the studio, it stays where it is.)
    locked = group(box(0, 0, locked=True), group(box(5, 5, locked=False)))
    made = freeform.checked(locked, extra=("behind", "build", "hidden", "locked"))
    assert made["shapes"][0]["locked"] is True
    assert made["shapes"][1]["shapes"][0]["locked"] is False
    # The page's other keys are the group's alone; a page that locks nothing, none.
    with pytest.raises(freeform.ShapeError, match="Unknown key build") as error:
        freeform.checked(group(box(0, 0, build=True)), extra=("build", "locked"))
    assert error.value.key == "shapes[0].build"
    with pytest.raises(freeform.ShapeError, match="Unknown key locked"):
        freeform.checked(group(box(0, 0, locked=True)))
    with pytest.raises(freeform.ShapeError, match="true or false"):
        freeform.checked(group(box(0, 0, locked="yes")), extra=("locked",))


# -- what is outside the group entered: what a piece in it catches at, lines glued across --


def test_what_a_piece_inside_a_group_catches_at_is_every_level_s_other_shapes() -> None:
    made = run(
        """
      return {
        top: G.outside(PAGE, []),
        one: G.outside(PAGE, [1]).map((one) => [one.path, one.spec.id ?? one.spec.kind]),
        two: G.outside(PAGE, [1, 1]).map((one) => [one.path, one.spec.id ?? one.spec.kind]),
        gone: G.outside(PAGE, [0, 4]).map((one) => one.path),
        places: [...G.places(PAGE)],
        deep: G.shapeAt(PAGE, [1, 1, 0]).id, none: G.shapeAt(PAGE, [0, 2]) ?? null,
        holds: [G.holds([1], [1, 1, 0]), G.holds([1, 1, 0], [1, 1, 0]), G.holds([1, 0], [1, 1]),
          G.holds([1, 1], [1])],
      };
    """,
        [
            box(0, 0, id="a"),
            group(box(10, 0, id="b"), group(box(20, 0, id="deep"), box(30, 0)), id="g"),
            box(40, 0),
        ],
    )
    # At the page's own level, nothing is outside; in a group, the page's other shapes; two
    # levels in, those and the outer group's other shapes too (a group among them, one shape).
    assert made["top"] == []
    assert made["one"] == [[[0], "a"], [[2], "rectangle"]]
    assert made["two"] == [[[0], "a"], [[2], "rectangle"], [[1, 0], "b"]]
    # (A path through a shape that is no group: the page's level alone.)
    assert made["gone"] == [[1], [2]]
    assert made["places"] == [["a", [0]], ["g", [1]], ["b", [1, 0]], ["deep", [1, 1, 0]]]
    assert made["deep"] == "deep" and made["none"] is None
    assert made["holds"] == [True, True, False, False]


# A shape (X) on the page; a group with a shape (Y) and a line glued from Y to X; a line on the
# page glued to Y; a group with a line glued between its own two shapes.
GLUED = [
    box(0, 0, id="X"),
    group(
        box(100, 0, id="Y"),
        {
            "kind": "line",
            "id": "L",
            "from": {"shape": "Y", "side": "left"},
            "to": {"shape": "X", "side": "right"},
        },
    ),
    {"kind": "line", "id": "M", "from": {"shape": "Y", "side": "bottom"}, "to": [100, 100]},
    group(
        box(200, 0, id="P"),
        box(300, 0, id="Q"),
        {"kind": "arrow", "from": {"shape": "P"}, "to": {"shape": "Q"}},
    ),
    {"kind": "line", "from": [0, 50], "to": [50, 50]},
]


def test_lines_glued_from_one_level_to_another_are_found_to_follow_what_moves() -> None:
    made = run(
        """
      const glued = (moving) => G.gluedAcross(PAGE, moving);
      return {
        // X moved on the page: the line in the group glued to it.
        x: glued([[0]]),
        // The group moved: its line glued to X (not moving), and the page's line glued to Y in it.
        group: glued([[1]]),
        // Y moved inside the group: the page's line, and the line beside it.
        y: glued([[1, 0]]),
        // The line itself moved: not one to follow (it is drawn as it is moved); M moved: none.
        line: glued([[1, 1]]), m: glued([[2]]),
        // A group moved with its line glued between its own shapes: it moves as it is.
        own: glued([[3]]), ownShape: glued([[3, 0]]),
        none: glued([[4]]),
      };
    """,
        GLUED,
    )
    assert made["x"] == [[1, 1]]
    assert made["group"] == [[1, 1], [2]]
    assert made["y"] == [[1, 1], [2]]
    assert made["line"] == [] and made["m"] == []
    assert made["own"] == [] and made["ownShape"] == [[3, 2]]
    assert made["none"] == []


def test_inside_a_group_what_is_outside_it_is_found_from_where_one_is() -> None:
    made = run(
        EDITOR
        + """
      const at0 = { outside: tools.outside(), glued: tools.glued([0]) };
      tools.enter(1);
      return {
        at0,
        outside: tools.outside().map((one) => one.path),
        located: [tools.locate("X"), tools.locate("L"), tools.locate("nobody")],
        shape: tools.shapeAt([1, 0]).id,
        drawn: [tools.drawnAt([1, 1]), tools.drawnAt([0])],
        // Y (index 0 where one is) moved: the line beside it, and the page's line glued to it.
        glued: tools.glued([0]),
        faded: [tools.faded([1, 0]), tools.faded([0])],
      };
    """,
        [*GLUED[:1], {**GLUED[1], "opacity": 0.5}, *GLUED[2:]],
    )
    assert made["at0"] == {"outside": [], "glued": [[1, 1]]}
    assert made["outside"] == [[0], [2], [3], [4]]
    assert made["located"] == [[0], [1, 1], None]
    assert made["shape"] == "Y"
    assert made["drawn"] == ["slide1.shapes.1.1", "slide1.shapes.0"]
    assert made["glued"] == [[1, 1], [2]]
    assert made["faded"] == [0.5, 1]


def test_pressed_on_the_page_s_empty_space_inside_a_group_one_stays_for_a_band() -> None:
    made = drawn("""
      tools.enter(1, { at: at(45, 65), deep: true });
      // Nothing there, at any level, and nothing of the page's own (the editor's band): still in.
      const clear = [tools.outward(at(500, 500), { clear: () => true }), tools.path(), chosen];
      // On something of the page's own (a slide's object): out of every group, as before.
      const object = [tools.outward(at(500, 500), { clear: () => false }), tools.path()];
      return { clear, object };
    """)
    assert made["clear"] == [None, [1, 1, 2], [1]]
    assert made["object"] == [None, []]


def test_shift_clicked_pieces_are_chosen_together_in_the_group_nearest_round_them() -> None:
    made = run("""
      return {
        two: G.widened([[1, 1, 0]], [1, 1, 1]),
        apart: G.widened([[1, 1, 0]], [1, 1, 2, 1]),
        page: G.widened([[1, 1, 0]], [0]),
        out: G.widened([[1, 1, 0], [1, 1, 1]], [1, 0]),
        // The piece chosen, or in one chosen, or nothing chosen: as ever.
        same: G.widened([[1, 1, 0]], [1, 1, 0]), inside: G.widened([[1]], [1, 1, 0]),
        none: G.widened([], [1, 0]),
      };
    """)
    assert made["two"] == {"level": [1, 1], "picks": [0, 1]}
    assert made["apart"] == {"level": [1, 1], "picks": [0, 2]}
    assert made["page"] == {"level": [], "picks": [1, 0]}
    assert made["out"] == {"level": [1], "picks": [1, 0]}
    assert made["same"] is None and made["inside"] is None and made["none"] is None


def test_a_click_then_a_shift_click_on_two_pieces_of_a_drawing_chooses_both_in_it() -> None:
    made = drawn("""
      // The drawing clicked at a box (chosen whole, the box under the pointer kept), then
      // another box of it ⇧-clicked: in the group round both, both chosen.
      const click = (x, y, index) => { chosen = [index]; tools.pressed(at(x, y), index); };
      click(15, 15, 1);
      const two = [tools.extend(at(45, 15)), tools.path(), chosen];
      tools.leave();
      // In groups of their own in it: those of the group round them both.
      click(15, 15, 1);
      const apart = [tools.extend(at(45, 65)), tools.path(), chosen];
      tools.leave();
      click(80, 90, 1);
      const frame = [tools.extend(at(15, 15)), tools.path(), chosen];
      tools.leave();
      // The same piece again, the page's empty space, another shape on the page: as ever (the
      // editor's: chosen or not where one is).
      click(15, 15, 1);
      const same = [tools.extend(at(16, 16)), tools.path()];
      const empty = [tools.extend(at(500, 500)), tools.path()];
      const onPage = [tools.extend(at(205, 205)), tools.path()];
      // Chosen some other way (no piece of it clicked): as ever.
      tools.pressed(at(205, 205), 0);
      chosen = [1];
      const other = [tools.extend(at(45, 15)), tools.path()];
      // In the group, two chosen: ⇧ on a piece outside it, in the drawing -- out to the
      // drawing, the group and that piece chosen.
      click(15, 15, 1);
      tools.extend(at(45, 15));
      const out = [tools.extend(at(80, 90)), tools.path(), chosen];
      return { two, apart, frame, same, empty, onPage, other, out };
    """)
    assert made["two"] == [True, [1, 1], [0, 1]]
    assert made["apart"] == [True, [1, 1], [0, 2]]
    assert made["frame"] == [True, [1], [0, 1]]
    assert (
        made["same"] == [False, []]
        and made["empty"] == [False, []]
        and made["onPage"] == [False, []]
    )
    assert made["other"] == [False, []]
    assert made["out"] == [True, [1], [1, 0]]
