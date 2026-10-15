"""The studio's tools for paths (``studio/static/studio/pathops.js``), run in Node: a path's
pieces as anchors and back, points added on a curve keeping it, made smooth and corners,
deleted, an edit of a turned path leaving what was not moved; every kind of shape made a path
of the same outline (Make Editable); and shapes combined -- union, subtract, intersect,
exclude -- their areas as they should be, holes and touching edges and all, curves in and
curves out, quickly."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform, pathdata

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"


def node(body: str) -> object:
    found = shutil.which("node")
    if found is None:
        pytest.skip("Node is not installed")
    script = (
        f"import * as O from {json.dumps((STATIC / 'pathops.js').as_uri())};\n"
        f"import * as P from {json.dumps((STATIC / 'pathdata.js').as_uri())};\n"
        f"import * as F from {json.dumps((STATIC / 'freeform.js').as_uri())};\n"
        f"const out = (() => {{ {body} }})();\n"
        "console.log(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        [found, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def area(data: str) -> float:
    """What path data fills, even-odd: its rings' areas, finely cut."""

    total = 0.0
    for points, _ in pathdata.rings(pathdata.segments_of(data)):
        count = len(points)
        total += (
            sum(
                points[n][0] * points[(n + 1) % count][1]
                - points[(n + 1) % count][0] * points[n][1]
                for n in range(count)
            )
            / 2.0
        )
    return abs(total)


# -- a path's pieces --


def test_a_paths_pieces_are_anchors_and_back() -> None:
    made = node(
        """
        const d = "M 0 0 C 10 -10 30 -10 40 0 L 40 30 L 0 30 Z M 60 0 L 80 0";
        const pieces = O.piecesOf(P.parse(d));
        const corner = (at) => ({ at, in: null, out: null });
        const smooth = { at: [50, 0], in: [40, -20], out: [60, 20] };
        const anchors = [corner([0, 0]), smooth, corner([100, 0])];
        return { pieces, again: O.dataOf(pieces),
                 smooth: O.smooth({ at: [0, 0], in: [-5, 0], out: [9, 0] }),
                 cusp: O.smooth({ at: [0, 0], in: [-5, 1], out: [9, 1] }),
                 pen: O.dataOf([{ anchors, closed: false }]) };
        """
    )
    assert made["again"] == "M 0 0 C 10 -10 30 -10 40 0 L 40 30 L 0 30 Z M 60 0 L 80 0"
    first, second = made["pieces"]
    assert first["closed"] and not second["closed"] and len(first["anchors"]) == 4
    assert first["anchors"][0]["out"] == [10, -10] and first["anchors"][1]["in"] == [30, -10]
    assert made["smooth"] and not made["cusp"]
    # The pen: a corner, a smooth point dragged out, a corner.
    assert made["pen"] == "M 0 0 C 0 0 40 -20 50 0 C 60 20 100 0 100 0"


def test_a_point_added_on_a_curve_keeps_its_shape() -> None:
    made = node(
        """
        const pieces = O.piecesOf(P.parse("M 0 0 C 0 -60 120 -60 120 0 L 120 50"));
        const split = O.splitAt(pieces[0], 0, 0.3), line = O.splitAt(pieces[0], 1, 0.5);
        const before = P.rings(P.parse(O.dataOf(pieces)))[0][0];
        const after = P.parse(O.dataOf([split]));
        const near = O.nearestOn(pieces, [60, -46]);
        const ring = [P.rings(after)[0][0]];
        return { count: split.anchors.length, added: split.anchors[1].at, line: line.anchors[2].at,
                 far: Math.max(...before.map((point) => P.distance(ring, point, [false]))), near };
        """
    )
    assert made["count"] == 4 and made["line"] == [120, 25]
    # (The curve at 0.3: (1-t)^3 0 + 3(1-t)^2 t 0 + 3(1-t) t^2 120 + t^3 120.)
    assert made["added"] == pytest.approx([3 * 0.7 * 0.09 * 120 + 0.027 * 120, -60 * 3 * 0.3 * 0.7])
    assert made["far"] < 0.5
    assert made["near"]["n"] == 0 and made["near"]["t"] == pytest.approx(0.5, abs=0.01)
    assert made["near"]["distance"] == pytest.approx(1.0, abs=0.05)


def test_points_made_smooth_and_corners_and_deleted() -> None:
    made = node(
        """
        const piece = O.piecesOf(P.parse("M 0 0 L 60 0 L 60 60 L 0 60 Z"))[0];
        const smooth = O.toggled(piece, 1);
        const corner = O.toggled({ anchors: [piece.anchors[0], smooth, piece.anchors[2]] }, 1);
        const gone = O.without([piece], new Set(["0:1"]));
        const all = O.without([piece], new Set(["0:0", "0:1", "0:2"]));
        return { smooth, corner, gone: O.dataOf(gone), all };
        """
    )
    # Smooth: along the way from its neighbour before to the one after, a third of the way.
    smooth = made["smooth"]
    assert smooth["at"] == [60, 0]
    assert smooth["in"] == pytest.approx([60 - 20 / math.sqrt(2), -20 / math.sqrt(2)])
    assert smooth["out"] == pytest.approx([60 + 20 / math.sqrt(2), 20 / math.sqrt(2)])
    assert made["corner"] == {"at": [60, 0], "in": None, "out": None}
    assert made["gone"] == "M 0 0 L 60 60 L 0 60 Z"
    # A piece left with fewer than two points goes.
    assert made["all"] == []


def test_an_edit_of_a_turned_path_leaves_what_was_not_moved() -> None:
    made = node(
        """
        const d = "M 0 0 L 100 0 L 100 50 L 0 50 Z";
        const spec = { kind: "path", d, rotate: 30, flip: "horizontal" };
        const frame = O.frameOf(spec, F.geometry(spec)), pieces = O.piecesOf(P.parse(spec.d));
        const before = pieces[0].anchors.map((a) => O.toPage(frame, a.at));
        pieces[0].anchors[1].at = [160, -40];
        const edited = { ...spec, d: P.written(O.steadied(frame, O.segmentsFrom(pieces))) };
        const now = O.frameOf(edited, F.geometry(edited));
        const after = O.piecesOf(P.parse(edited.d))[0].anchors.map((a) => O.toPage(now, a.at));
        const back = O.toLocal(frame, O.toPage(frame, [12, 34]));
        return { before, after, back };
        """
    )
    for index in (0, 2, 3):
        assert made["after"][index] == pytest.approx(made["before"][index], abs=0.02)
    assert made["after"][1] != pytest.approx(made["before"][1], abs=1)
    assert made["back"] == pytest.approx([12, 34])


# -- Make Editable --

SHAPES = [
    {"kind": "rectangle", "at": [40, 50], "size": [180, 110], "rotate": 30, "text": "Box"},
    {
        "kind": "rounded-rectangle",
        "at": [40, 50],
        "size": [120, 80],
        "corner": 20,
        "flip": "vertical",
    },
    {"kind": "ellipse", "at": [0, 0], "size": [100, 60], "rotate": 75},
    {"kind": "triangle", "at": [0, 0], "size": [100, 80], "apex": 0.2, "flip": "horizontal"},
    {"kind": "star", "at": [10, 10], "size": [100, 100], "tips": 7, "rotate": 10},
    {"kind": "cloud", "at": [0, 0], "size": [180, 120], "rotate": 200},
    {"kind": "arrow-left-right", "at": [0, 0], "size": [200, 60]},
    {"kind": "bubble", "at": [100, 100], "size": [200, 100], "tail": [80, 20], "rotate": 15},
    {"kind": "highlight", "at": [0, 0], "size": [200, 40]},
    {"kind": "check", "at": [0, 0], "size": [100, 80]},
    {"kind": "arrow", "from": [0, 0], "to": [200, 90], "start": "dot"},
    {"kind": "curved-arrow", "from": [0, 0], "to": [200, 0], "bend": 0.4},
    {"kind": "elbow", "from": [0, 0], "to": [100, 80]},
    {"kind": "brace", "from": [0, 0], "to": [0, 200], "depth": -24},
    {"kind": "polyline", "points": [[0, 0], [50, 80], [100, 10]], "closed": True},
    {"kind": "pen", "points": [[0, 0], [50, 80], [100, 10], [160, 60]]},
    {"kind": "dimension", "from": [10, 10], "to": [210, 10], "text": "3.1 Å"},
]


def test_every_kind_made_editable_draws_the_same_outline() -> None:
    made = node(
        f"""
        const shapes = {json.dumps(SHAPES)};
        // The points each outline passes through on the page, and how far the other's are.
        const pieces = (spec) => O.outlinesOf(spec).map((one) => one.segments);
        const outline = (spec) => pieces(spec)
          .flatMap((one) => P.rings(one).map(([points]) => points));
        const open = (rings) => rings.map(() => false);
        const reach = (spec) => P.extent(pieces(spec).flat());
        return shapes.map((spec) => {{
          const path = O.editable(spec), ours = outline(spec), theirs = outline(path);
          const far = Math.max(...ours.flat().map((p) => P.distance(theirs, p, open(theirs))),
                               ...theirs.flat().map((p) => P.distance(ours, p, open(ours))));
          const heads = [F.geometry(spec).heads.length, F.geometry(path).heads.length];
          return {{ path, far, bounds: [reach(spec), reach(path)], heads }};
        }});
        """
    )
    for spec, one in zip(SHAPES, made, strict=True):
        path = one["path"]
        assert path["kind"] == "path" and freeform.checked(path) == path, spec
        assert one["far"] < 0.05, (spec, one["far"])
        assert one["bounds"][1] == pytest.approx(one["bounds"][0], abs=0.05), spec
        assert one["heads"][0] == one["heads"][1], spec
        # Its look as it was drawn: a line's unfilled, its head kept; words kept.
        assert ("text" in path) == ("text" in spec), spec
    arrow = made[SHAPES.index(SHAPES[10])]["path"]
    assert (arrow["fill"], arrow["start"], arrow["end"]) == ("none", "dot", "triangle")
    assert made[0]["path"]["rotate"] == 30 and "flip" not in made[1]["path"]
    shapes = json.dumps([*SHAPES[:2], {"kind": "text", "at": [0, 0]}])
    group = node(f'return O.editable({{ kind: "group", shapes: {shapes} }});')
    assert [child["kind"] for child in group["shapes"]] == ["path", "path", "text"]


# -- shapes combined --


def rect(x: float, y: float, w: float, h: float, rule: str = "nonzero") -> dict:
    return {"segments": f"M {x} {y} H {x + w} V {y + h} H {x} Z", "rule": rule}


def circle(cx: float, cy: float, r: float, back: bool = False) -> dict:
    sweep = 0 if back else 1
    return {
        "segments": f"M {cx + r} {cy} A {r} {r} 0 1 {sweep} {cx - r} {cy} "
        f"A {r} {r} 0 1 {sweep} {cx + r} {cy} Z",
        "rule": "nonzero",
    }


def combined(operation: str, *shapes: dict) -> str | None:
    found = node(
        f"""
        const shapes = {json.dumps(list(shapes))}
          .map((one) => ({{ segments: P.parse(one.segments), rule: one.rule }}));
        const made = O.combined({json.dumps(operation)}, shapes);
        return made && P.written(made);
        """
    )
    if found is not None:
        assert freeform.checked({"kind": "path", "d": found, "fill_rule": "evenodd"})
    return found


def test_two_boxes_are_combined_each_way() -> None:
    a, b = rect(0, 0, 100, 100), rect(50, 50, 100, 100)
    assert (
        combined("union", a, b)
        == "M 0 0 L 100 0 L 100 50 L 150 50 L 150 150 L 50 150 L 50 100 L 0 100 Z"
    )
    assert area(combined("subtract", a, b)) == pytest.approx(7500)
    assert area(combined("intersect", a, b)) == pytest.approx(2500)
    assert area(combined("exclude", a, b)) == pytest.approx(15000)
    # The one at the back less those in front: in front, less nothing of it.
    assert area(combined("subtract", b, a)) == pytest.approx(7500)


def test_holes_touching_edges_and_shapes_apart() -> None:
    holed = combined("subtract", rect(0, 0, 100, 100), rect(25, 25, 50, 50))
    assert holed.count("M") == 2 and area(holed) == pytest.approx(7500)
    # Edges lying on one another: one outline, no seam.
    assert combined("union", rect(0, 0, 100, 100), rect(100, 0, 100, 100)).count("M") == 1
    assert area(combined("union", rect(0, 0, 100, 100), rect(100, 20, 100, 60))) == pytest.approx(
        16000
    )
    assert area(combined("union", rect(0, 0, 100, 100), rect(0, 0, 100, 100))) == pytest.approx(
        10000
    )
    # Meeting at a corner only; far apart; not overlapping at all.
    assert area(combined("union", rect(0, 0, 100, 100), rect(100, 100, 50, 50))) == pytest.approx(
        12500
    )
    assert combined("intersect", rect(0, 0, 10, 10), rect(50, 50, 10, 10)) is None
    assert area(combined("union", rect(0, 0, 10, 10), rect(50, 50, 10, 10))) == pytest.approx(200)
    # A hole of the shapes' own: an even-odd shape's inner piece stays a hole.
    framed = rect(0, 0, 100, 100) | {
        "segments": "M 0 0 H 100 V 100 H 0 Z M 25 25 H 75 V 75 H 25 Z",
        "rule": "evenodd",
    }
    assert area(combined("union", framed, rect(200, 0, 10, 10))) == pytest.approx(7500 + 100)


def test_curves_go_in_and_come_out() -> None:
    made = combined("union", circle(0, 0, 50), circle(60, 0, 50))
    # Two circles' arcs, each a curve or two: none cut into lines.
    assert "L" not in made and made.count("C") >= 4
    lens = 2 * (50 * 50 * math.acos(30 / 50) - 30 * math.sqrt(50 * 50 - 30 * 30))
    assert area(made) == pytest.approx(2 * math.pi * 2500 - lens, rel=0.005)
    assert area(combined("intersect", circle(0, 0, 50), circle(60, 0, 50))) == pytest.approx(
        lens, rel=0.01
    )
    # A circle less one within it, wound either way: a ring.
    for back in (False, True):
        ring = combined("subtract", circle(0, 0, 50), circle(0, 0, 25, back))
        assert area(ring) == pytest.approx(math.pi * (2500 - 625), rel=0.005)


def test_large_shapes_are_combined_quickly() -> None:
    made = node(
        """
        const wobbly = (cx, cy, r, n, k) => {
          const words = [];
          for (let i = 0; i <= n; i += 1) {
            const a = i / n * 2 * Math.PI, rr = r + 8 * Math.sin(k * a);
            const b = (i - 0.5) / n * 2 * Math.PI, rb = 1.01 * (r + 8 * Math.sin(k * b));
            const to = `${cx + rr * Math.cos(a)} ${cy + rr * Math.sin(a)}`;
            const control = `${cx + rb * Math.cos(b)} ${cy + rb * Math.sin(b)}`;
            words.push(i === 0 ? `M ${to}` : `Q ${control} ${to}`);
          }
          return { segments: P.parse(words.join(" ") + " Z"), rule: "nonzero" };
        };
        const shapes = [wobbly(0, 0, 200, 300, 17), wobbly(120, 40, 200, 300, 23),
                        wobbly(60, -80, 150, 300, 11)];
        const out = {};
        for (const operation of O.OPERATIONS) {
          const began = performance.now(), made = O.combined(operation, shapes);
          const curves = made.filter((s) => s[0] === "C").length;
          out[operation] = { ms: performance.now() - began, curves, all: made.length };
        }
        return out;
        """
    )
    for operation, found in made.items():
        assert found["ms"] < 400, (operation, found)
        assert found["curves"] >= found["all"] * 0.9, operation
