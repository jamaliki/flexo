"""One choice of two kinds (``studio/static/studio/mixing.js``): a slide's objects and its shapes,
a figure's parts and the shapes drawn over it -- what it is called, Flexo's own copy of both,
the steps a change of both made joined into one, and one put in or taken out by ⇧-click --
run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "mixing.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const M = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_choice_of_both_is_named_for_each_kind() -> None:
    assert run("""
      return [M.mixedName(2, 3), M.mixedName(1, 1), M.mixedName(0, 2), M.mixedName(3, 0),
        M.mixedName(1, 2, ["Shape", "Drawn Shape"]),
        M.mixedName(2, 1, ["Figure Shape", "Shape"])];
    """) == [
        "2 Objects, 3 Shapes",
        "1 Object, 1 Shape",
        "2 Shapes",
        "3 Objects",
        "1 Shape, 2 Drawn Shapes",
        "2 Figure Shapes, 1 Shape",
    ]


def test_a_step_done_to_both_names_both() -> None:
    assert run("""
      return [M.mixedLabel("Delete", 1, 1), M.mixedLabel("Paste", 2, 3),
        M.mixedLabel("Cut", 1, 0), M.mixedLabel("Duplicate", 1, 2, ["Shape", "Drawn Shape"])];
    """) == [
        "Delete 1 Object and 1 Shape",
        "Paste 2 Objects and 3 Shapes",
        "Cut 1 Object",
        "Duplicate 1 Shape and 2 Drawn Shapes",
    ]


def test_a_copy_of_both_holds_each_kinds_copy_as_it_copies_alone() -> None:
    result = run("""
      const objects = { what: "block", block: { text: "Words" }, label: "text" };
      const shape = { kind: "rectangle", at: [0, 0], size: [10, 10] };
      const shapes = { what: "shapes", shapes: [shape], label: "rectangle" };
      const both = M.mixedClip([objects, shapes], "1 object, 1 shape");
      const kinds = (clip) => M.clipsOf(clip).map((one) => one.what);
      return {
        both, alone: M.mixedClip([objects, null], "x"), none: M.mixedClip([null], "x"),
        each: kinds(both), one: kinds(shapes), nothing: M.clipsOf(null),
        broken: M.clipsOf({ what: "mixed", clips: "not a list" }),
        // (As the clipboard keeps it: JSON, and back.)
        kept: M.clipsOf(JSON.parse(JSON.stringify(both))).length,
      };
    """)
    assert result["both"]["what"] == "mixed" and result["both"]["label"] == "1 object, 1 shape"
    assert result["alone"]["what"] == "block"
    assert result["none"] is None
    assert result["each"] == ["block", "shapes"] and result["one"] == ["shapes"]
    assert result["nothing"] == [] and result["broken"] == []
    assert result["kept"] == 2


def test_the_steps_a_change_of_both_made_are_one() -> None:
    result = run("""
      const A = { n: 1 }, B = { n: 2 }, C = { n: 3 };
      let stepped = 0;
      const studio = { past: [
        { before: { n: 0 }, after: A, label: "Earlier" },
        { before: A, after: B, label: "Delete Rectangle" },
        { before: B, after: C, label: "Delete Object" },
      ], step() { stepped += 1; } };
      const joined = M.joinSteps(studio, 1, "Delete 1 Object and 1 Shape");
      return { count: studio.past.length, label: joined.label, from: joined.before === A,
        to: joined.after === C, parts: joined.parts ?? null, earlier: studio.past[0].label,
        top: studio.past[1] === joined, stepped };
    """)
    assert result == {
        "count": 2,
        "label": "Delete 1 Object and 1 Shape",
        "from": True,
        "to": True,
        "parts": None,
        "earlier": "Earlier",
        "top": True,
        "stepped": 1,
    }


def test_another_change_between_two_keeps_each_a_part_of_its_own() -> None:
    result = run("""
      const A = { n: 1 }, B = { n: 2 }, B2 = { n: 22 }, C = { n: 3 };
      const studio = { past: [
        { before: A, after: B, label: "Paste Shape" },
        { before: B2, after: C, label: "Paste Object" },
      ] };
      const joined = M.joinSteps(studio, 0, "Paste 1 Object and 1 Shape");
      return { count: studio.past.length, before: joined.before.n, after: joined.after.n,
        parts: joined.parts.map((part) => [part.before.n, part.after.n]) };
    """)
    assert result == {"count": 1, "parts": [[1, 2], [22, 3]], "before": 1, "after": 3}


def test_steps_made_elsewhere_or_none_are_not_joined() -> None:
    result = run("""
      const A = { n: 1 }, B = { n: 2 };
      const kept = { past: [
        { before: A, after: A, apply: () => {}, label: "Edit Figure File" },
        { before: A, after: B, label: "Delete Shape" },
      ] };
      const one = { past: [{ before: A, after: B, label: "Delete Shape", said: { text: "x" } }] };
      const alone = () => { const step = M.joinSteps(one, 0, "Delete 1 Shape");
        return [step.label, step.said]; };
      return {
        elsewhere: M.joinSteps(kept, 0, "Delete Both"), still: kept.past.length,
        none: M.joinSteps(one, 1, "Delete Both"), outside: M.joinSteps(one, -1, "Delete Both"),
        // (One alone is named anew, what it said forgotten: said again as named.)
        alone: alone(),
      };
    """)
    assert result == {
        "elsewhere": None,
        "still": 2,
        "none": None,
        "outside": None,
        "alone": ["Delete 1 Shape", None],
    }


def test_steps_made_elsewhere_and_here_are_one_put_back_where_each_was_made() -> None:
    result = run("""
      const A = { n: 1 }, B = { n: 2 }, C = { n: 3 };
      const done = [];
      const file = (name) => ({
        before: B, after: B, label: name,
        apply: (target) => { done.push(`${name} ${target}`); return Promise.resolve(); },
      });
      const studio = {
        past: [
          { before: A, after: B, label: "Delete Rectangle" }, file("Delete “a”"),
          { before: B, after: C, label: "Move Shape" }, file("Delete “b”"),
        ],
        travelPart: (step, target) => done.push(`${step.label} ${target}`),
        said: (step) => (step.label === "Delete Rectangle"
          ? { text: step.label, place: "Slide 3", where: 2 } : { text: step.label }),
      };
      const joined = M.joinSteps(studio, 0, "Delete Both");
      await joined.apply("before");
      const undone = [...done];
      done.length = 0;
      await joined.apply("after");
      return { count: studio.past.length, label: joined.label,
        place: [joined.place, joined.where], undone, redone: done };
    """)
    # Undone: each file put back, the last first, then the deck's changes taken back, the last
    # first; made again, in the order they were made.
    assert result == {
        "count": 1,
        "label": "Delete Both",
        "place": ["Slide 3", 2],
        "undone": [
            "Delete “b” before",
            "Delete “a” before",
            "Move Shape before",
            "Delete Rectangle before",
        ],
        "redone": [
            "Delete “a” after",
            "Delete “b” after",
            "Delete Rectangle after",
            "Move Shape after",
        ],
    }


def test_shift_click_puts_one_in_or_takes_it_out() -> None:
    result = run("""
      const same = (a, b) => a.region === b.region && a.index === b.index;
      const picks = [{ region: "left", index: 0 }, { region: "right", index: 1 }];
      return {
        out: M.toggled(picks, { region: "right", index: 1 }, same),
        in: M.toggled(picks, { region: "body", index: 2 }, same),
        ids: M.toggled(["a", "b"], "a"),
        // (The same things chosen in another order are the same choice.)
        key: M.choiceKey(picks) === M.choiceKey([...picks].reverse()),
        other: M.choiceKey(picks) === M.choiceKey(picks.slice(1)),
      };
    """)
    assert result == {
        "out": [{"region": "left", "index": 0}],
        "in": [
            {"region": "left", "index": 0},
            {"region": "right", "index": 1},
            {"region": "body", "index": 2},
        ],
        "ids": ["b"],
        "key": True,
        "other": False,
    }
