"""Guides from beside the page (``studio/static/studio/beside.js``): what a deck's neighbouring
slides hold caught at as the page's own edges and middles are -- told apart, for their guides
to be drawn in a colour of their own, and the page's own kept its own -- and a nudge that would
step over one of them stopped on it, run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "beside.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const B = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_what_is_beside_the_page_is_caught_at_and_told_apart_from_the_page_s_own() -> None:
    made = run("""
      // The page's own: its edges and middle, one shape's.
      const targets = { xs: [0, 480, 960, 100, 150, 200], ys: [0, 270, 540, 50, 75, 100], boxes: [] };
      // On the slide before: a picture, its left edge the shape's own.
      const beside = { boxes: [[100, 300, 400, 500]] };
      const caught = B.withBeside(targets, beside);
      return {
        xs: caught.xs, ys: caught.ys,
        own: B.besideAt(caught, "x", 100), left: B.besideAt(caught, "x", 250),
        right: B.besideAt(caught, "x", 400), top: B.besideAt(caught, "y", 300),
        none: B.withBeside({ xs: [1], ys: [2], boxes: [] }, null),
      };
    """)
    # Its middle and right edge, its top, middle and bottom, are caught at too...
    assert made["xs"] == [0, 480, 960, 100, 150, 200, 250, 400]
    assert made["ys"] == [0, 270, 540, 50, 75, 100, 300, 400, 500]
    # ...told apart, with the box each came from; the page's own (its left edge) is the page's.
    assert made["own"] is None
    assert made["left"] == made["right"] == made["top"] == [100, 300, 400, 500]
    # Nothing beside: the page's own, as they were.
    assert made["none"] == {"xs": [1], "ys": [2], "boxes": []}


def test_a_nudge_that_would_step_over_a_guide_beside_the_page_stops_on_it() -> None:
    made = run("""
      const beside = { boxes: [[100, 300, 400, 500]] };
      // A box 0.4 to the right of the picture's left edge, nudged a point left at a time.
      const box = [100.4, 10, 160.4, 40];
      const first = B.nudgeCaught(box, -1, 0, beside);
      const lined = [100, 10, 160, 40];
      const second = B.nudgeCaught(lined, -1, 0, beside);
      // Ten points down at once (⇧), from 5 above the picture's top: stopped there.
      const down = B.nudgeCaught([0, 285, 30, 295], 0, 10, beside);
      // Nothing near: as it was asked.
      const far = B.nudgeCaught([600, 10, 640, 40], -1, 0, beside);
      // Just short of a guide (within half a point past the step): caught there too.
      const near = B.nudgeCaught([101.3, 10, 161.3, 40], -1, 0, beside);
      // Its middle a hair off the picture's, its edge 0.75 off: the hair is lined up already.
      const hair = B.nudgeCaught([100.755, 10, 399.255, 40], -1, 0, beside);
      return { first, second, down, far, near, hair };
    """)
    # Stopped on the edge, and lying on its guide.
    assert made["first"]["dx"] == pytest.approx(-0.4)
    assert made["first"]["dy"] == 0
    assert {(line["axis"], line["at"]) for line in made["first"]["guides"]} == {("x", 100)}
    # Lined up already, the next press moves it off, a whole point.
    assert made["second"] == {"dx": -1, "dy": 0, "guides": []}
    assert made["down"]["dy"] == pytest.approx(5)
    assert ("y", 300) in {(line["axis"], line["at"]) for line in made["down"]["guides"]}
    assert made["far"] == {"dx": -1, "dy": 0, "guides": []}
    assert made["near"]["dx"] == pytest.approx(-1.3)
    assert made["hair"]["dx"] == pytest.approx(-0.755)
