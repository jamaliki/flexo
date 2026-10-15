"""SVG path data as a ``path`` shape writes its outline (``flexo.pathdata``): every command read,
absolute and relative, and written back as absolute moves, lines, cubics and closes; arcs as
cubics; what is wrong said in words; and the studio's twin (``pathdata.js``) reading, writing,
moving and saying what is wrong word for word as this does."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import pathdata

SCRIPT = Path(pathdata.__file__).parent / "studio" / "static" / "studio" / "pathdata.js"


def flat(data: str) -> list:
    return [list(segment) for segment in pathdata.segments_of(data)]


# -- reading every command --


def test_every_command_is_read_absolute_and_relative() -> None:
    assert pathdata.normalised("M 10 20 L 30 40 H 50 V 60 Z") == (
        "M 10 20 L 30 40 L 50 40 L 50 60 Z"
    )
    assert pathdata.normalised("m 10 20 l 20 20 h 20 v 20 z") == (
        "M 10 20 L 30 40 L 50 40 L 50 60 Z"
    )
    assert pathdata.normalised("M0 0 C 10 0 20 10 20 20 S 30 40 40 40") == (
        "M 0 0 C 10 0 20 10 20 20 C 20 30 30 40 40 40"
    )
    assert pathdata.normalised("M0 0 c 10 0 20 10 20 20 s 10 20 20 20") == (
        "M 0 0 C 10 0 20 10 20 20 C 20 30 30 40 40 40"
    )
    # A quadratic is a cubic with its controls two thirds of the way to its own.
    assert pathdata.normalised("M 0 0 Q 30 30 60 0") == "M 0 0 C 20 20 40 20 60 0"
    assert pathdata.normalised("M 0 0 q 30 30 60 0 t 60 0") == (
        "M 0 0 C 20 20 40 20 60 0 C 80 -20 100 -20 120 0"
    )
    # A smooth curve after no curve starts at its own start; after a quadratic, too.
    assert pathdata.normalised("M 0 0 L 10 0 S 30 10 40 0") == "M 0 0 L 10 0 C 10 0 30 10 40 0"
    assert pathdata.normalised("M 0 0 Q 10 10 20 0 S 30 10 40 0") == (
        "M 0 0 C 6.67 6.67 13.33 6.67 20 0 C 20 0 30 10 40 0"
    )
    assert pathdata.normalised("M 0 0 L 10 0 T 30 0") == "M 0 0 L 10 0 C 10 0 16.67 0 30 0"


def test_numbers_are_read_as_svg_writes_them() -> None:
    # Signs, points and exponents run together; a move's further pairs are lines.
    assert flat("M1-2.5.5e1 3L-1e-1,.25") == [
        ["M", 1.0, -2.5],
        ["L", 5.0, 3.0],
        ["L", -0.1, 0.25],
    ]
    assert flat("m 10 10 5 5 5 0") == [["M", 10.0, 10.0], ["L", 15.0, 15.0], ["L", 20.0, 15.0]]
    # An arc's flags may be written without anything between them, or the end after them.
    assert pathdata.normalised("M0,0a10 10 0 0110 10") == pathdata.normalised(
        "M 0 0 a 10 10 0 0 1 10 10"
    )


def test_pieces_are_kept_holes_and_all_and_a_close_starts_the_next_where_it_began() -> None:
    data = "M 10 10 C 20 0 40 0 50 10 L 50 40 Z M 20 20 L 30 20 L 30 30 Z"
    assert pathdata.normalised(data) == data
    assert pathdata.normalised("M 0 0 L 10 0 L 10 10 z l 5 5") == (
        "M 0 0 L 10 0 L 10 10 Z M 0 0 L 5 5"
    )
    # A move with nothing drawn from it is no piece; a close after a close is none either.
    assert pathdata.normalised("M 1 1 M 2 2 L 3 3 M 9 9") == "M 2 2 L 3 3"
    assert pathdata.normalised("M 0 0 L 1 0 Z Z") == "M 0 0 L 1 0 Z"
    read = pathdata.parsed("M 0 0 L 1 0 Z M 5 5 L 6 6")
    assert read.opens == (False, True)


def test_numbers_are_written_to_a_hundredth_halves_up() -> None:
    assert pathdata.normalised("M 0.004 -0.004 L 1.005 2.675 L 12.30 -7") == (
        "M 0 0 L 1 2.68 L 12.3 -7"
    )
    assert pathdata.normalised("M 0.1 0.2 L 1234.5678 -0.05") == "M 0.1 0.2 L 1234.57 -0.05"


# -- arcs --


def _on_ellipse(data: str, centre: tuple[float, float], rx: float, ry: float) -> None:
    for segment in pathdata.segments_of(data)[1:]:
        assert segment[0] == "C"
    read = pathdata.parsed(data)
    for points, _ in pathdata.rings(read.segments):
        for x, y in points:
            reach = ((x - centre[0]) / rx) ** 2 + ((y - centre[1]) / ry) ** 2
            assert reach == pytest.approx(1.0, abs=2e-3)


@pytest.mark.parametrize(("large", "sweep"), [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_an_arc_is_cubics_on_its_circle(large: int, sweep: int) -> None:
    # Two ends a quarter of a circle apart, its centre one side of them or the other.
    data = f"M 100 0 A 100 100 0 {large} {sweep} 0 100"
    centre = (100.0, 100.0) if sweep == large else (0.0, 0.0)
    _on_ellipse(data, centre, 100.0, 100.0)
    segments = pathdata.segments_of(data)
    assert segments[-1][-2:] == (0.0, 100.0)
    # A large arc goes the long way round: three quarters, in three cubics; else one.
    assert len(segments) - 1 == (3 if large else 1)


def test_an_arc_sweeps_the_way_it_says() -> None:
    # From the left of a circle to its right, sweeping clockwise on the page (y down): over
    # its top.
    over = pathdata.parsed("M 0 0 A 50 50 0 0 1 100 0")
    assert over.box == pytest.approx((0.0, -50.0, 100.0, 50.0))
    under = pathdata.parsed("M 0 0 A 50 50 0 0 0 100 0")
    assert under.box == pytest.approx((0.0, 0.0, 100.0, 50.0))


def test_a_turned_ellipse_and_radii_too_small_for_their_ends() -> None:
    # An ellipse turned a quarter: its long axis down the page.
    turned = "M 0 -100 A 100 50 90 1 1 0 100 A 100 50 90 1 1 0 -100"
    box = pathdata.parsed(turned).box
    assert box == pytest.approx((-50.0, -100.0, 100.0, 200.0), abs=1e-6)
    # Radii too small to reach are grown until they do: a half circle on the ends.
    grown = pathdata.parsed("M 0 0 A 1 1 0 0 1 100 0")
    assert grown.box == pytest.approx((0.0, -50.0, 100.0, 50.0), abs=1e-6)
    # No radius, a line; no distance, nothing.
    assert pathdata.normalised("M 0 0 A 0 10 0 0 1 50 50") == "M 0 0 L 50 50"
    assert pathdata.normalised("M 0 0 L 5 5 A 10 10 0 0 1 5 5") == "M 0 0 L 5 5"


# -- what is wrong --


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ("", "d is empty"),
        ("L 1 1", "a path starts with M (a move to its first point)"),
        ("10 10 L 20 20", "a path starts with M"),
        ("M 1", "M at character 1 needs 2 numbers (x y), but it has 1."),
        ("M 1 1 L", "L at character 7 needs 2 numbers (x y), but it has none."),
        ("M 1 1 L 2 2 3", "L at character 7 needs 2 numbers (x y) at a time, but 1 is left over."),
        ("M 0 0 C 1 2 3 4", "C at character 7 needs 6 numbers (x1 y1 x2 y2 x y), but it has 4."),
        ("M0 0 Z 4", "'4' at character 8 follows Z, which takes no numbers"),
        ("M 0 0 X 1", "'X' at character 7 is not a path command or a number"),
        ("M 0 0 L 1e 2", "'e' at character 10 is not a path command or a number"),
        ("M 0 0 a 1 1 0 2 1 3 3", "the arc at character 7 has a large-arc flag of '2'"),
        ("M 0 0 A 1 1 0 1", "A at character 7 needs 7 numbers"),
        ("M 1 1", "d only moves: a path needs a line or a curve after its M"),
        ("M 0 0 L 1e9 0", "d has a point 1e+09 points from the page"),
    ],
)
def test_what_is_wrong_is_said_in_words(data: str, words: str) -> None:
    with pytest.raises(pathdata.PathError) as raised:
        pathdata.parsed(data)
    assert words in str(raised.value)


def test_a_path_too_long_is_said() -> None:
    data = "M 0 0 " + "L 1 1 " * (pathdata.MOST + 1)
    with pytest.raises(pathdata.PathError, match="a path has 100,000 at most"):
        pathdata.parsed(data)


# -- geometry --


def test_a_curves_box_is_what_it_draws_not_its_controls() -> None:
    # A curve bowed up by controls at y -40 reaches only -30, three quarters of the way.
    read = pathdata.parsed("M 0 0 C 0 -40 100 -40 100 0")
    assert read.box == pytest.approx((0.0, -30.0, 100.0, 30.0))
    # Turned a quarter about its middle, its reach is turned with it.
    left, top, right, bottom = pathdata.extent(read.segments, 90.0, (50.0, -15.0))
    assert (left, top, right, bottom) == pytest.approx((35.0, -65.0, 65.0, 35.0))


def test_inside_by_the_fill_rule() -> None:
    outer = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    same = [(25.0, 25.0), (75.0, 25.0), (75.0, 75.0), (25.0, 75.0)]
    back = list(reversed(same))
    middle = (50.0, 50.0)
    assert pathdata.inside([outer, same], middle, "nonzero")
    assert not pathdata.inside([outer, same], middle, "evenodd")
    assert not pathdata.inside([outer, back], middle, "nonzero")
    assert pathdata.inside([outer, back], (10.0, 10.0), "nonzero")


def test_powerpoints_fills_are_gathered_by_the_fill_rule() -> None:
    # Even-odd: one gathering. Non-zero: a hole that winds the other way stays with what it
    # is in; a piece winding the same way is filled, a gathering of its own.
    holed = "M 0 0 H 100 V 100 H 0 Z M 25 25 V 75 H 75 V 25 Z"
    filled = "M 0 0 H 100 V 100 H 0 Z M 25 25 H 75 V 75 H 25 Z"
    for data, rule, count in (
        (filled, "evenodd", 1),
        (holed, "nonzero", 1),
        (filled, "nonzero", 2),
    ):
        groups = pathdata.fill_groups(pathdata.segments_of(data), rule)
        assert len(groups) == count, (data, rule)
        assert sum(len(group) for group in groups) == len(pathdata.segments_of(data))


def test_moved_and_stretched_paths_are_written_again() -> None:
    data = "M 10 10 C 20 0 40 0 50 10 L 50 40 Z"
    assert pathdata.moved(data, 5, -2.5) == "M 15 7.5 C 25 -2.5 45 -2.5 55 7.5 L 55 37.5 Z"
    # Stretched into a box: its box becomes that box.
    fitted = pathdata.fitted(data, (0, 0, 80, 70))
    assert pathdata.parsed(fitted).box == pytest.approx((0.0, 0.0, 80.0, 70.0), abs=0.01)
    mirrored = pathdata.mapped(data, lambda point: (100 - point[0], point[1]))
    assert mirrored.startswith("M 90 10 C 80 0 60 0 50 10")


def test_a_path_is_read_once() -> None:
    data = "M 0 0 L 10 0 L 10 10 L 3 3 Z"
    assert pathdata.parsed(data) is pathdata.parsed(data)
    # Written again, what it says is kept as read: no second reading, the same numbers.
    moved = pathdata.moved(data, 1, 1)
    assert list(pathdata.parsed(moved).segments) == pathdata._parse(moved + " ")


def test_plain_words_are_read_quickly_as_they_would_be_slowly() -> None:
    for data in (
        "M 10 10 C 20 0 40 0 50 10 L 50 40 Z M 20 20 L 30 20 L 30 30 Z",
        "M 0 0 L 10 0 Z L 5 5",
        "M 1 1 M 2 2 L 3 3 M 9 9",
        " M 1.5 -2 C .5 2e1 3 4 5 6 Z Z ",
    ):
        quick = pathdata._plain(data)
        assert quick is not None, data
        # (Commas leave the quick way, and say the same.)
        slow = pathdata._parse(data.strip().replace(" ", ","))
        assert pathdata._finished(quick) == slow, data


# -- the studio's twin --

CASES = [
    "M 10 10 C 20 0 40 0 50 10 L 50 40 Z M 20 20 L 30 20 L 30 30 Z",
    "m 10 20 l 20 20 h 20 v 20 z l 5 5",
    "M0 0 Q 10 10 20 0 T 40 0 S 60 10 70 0",
    "M 0 0 q 30 30 60 0 t 60 0 c 1 2 3 4 5 6 s 7 8 9 10",
    "M1-2.5.5e1 3L-1e-1,.25",
    "M 0.004 -0.004 L 1.005 2.675 L 12.30 -7",
    "M 1 1 M 2 2 L 3 3 M 9 9 Z Z L 4 4",
    "M 100 0 A 100 100 0 1 1 0 100",
    "M0,0a10 10 0 0110 10",
    "M 0 -100 A 100 50 90 1 1 0 100 A 100 50 90 1 1 0 -100",
    "M 0 0 A 1 1 0 0 1 100 0 a 0 4 0 0 0 10 10",
]
WRONG = [
    "",
    "L 1 1",
    "10 10 L 20 20 and a good deal more",
    "M 1",
    "M 1 1 L",
    "M 1 1 L 2 2 3",
    "M 0 0 C 1 2 3 4",
    "M0 0 Z 4",
    "M 0 0 X 1",
    "M 0 0 L 1e 2",
    "M 0 0 a 1 1 0 2 1 3 3",
    "M 0 0 A 1 1 0 1",
    "M 0 0 A 1 1",
    "M 0 0 L 1 1 A 1 1 0 0 1 2 2 3",
    "M 0 0 a 1 1 0 1.e5 1 1",
    "M 1 1",
    "M 0 0 L 1e9 0",
    "m 0 0 l 1",
]


def test_the_studio_reads_writes_and_moves_paths_as_these_are() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"import * as p from {json.dumps(SCRIPT.as_uri())};\n"
        f"const cases = {json.dumps(CASES)}, wrong = {json.dumps(WRONG)};\n"
        "console.log(JSON.stringify({\n"
        "  read: cases.map((d) => p.parse(d)),\n"
        "  words: cases.map((d) => p.normalised(d)),\n"
        "  moved: cases.map((d) => p.moved(d, 3.25, -1.5)),\n"
        "  fitted: cases.map((d) => p.fitted(d, [10, 20, 300, 40])),\n"
        "  boxes: cases.map((d) => p.parsed(d).box),\n"
        "  opens: cases.map((d) => p.parsed(d).opens),\n"
        "  turned: cases.map((d) => p.extent(p.parse(d), 33, [5, 7])),\n"
        "  rings: cases.map((d) => p.rings(p.parse(d))),\n"
        "  wrong: wrong.map((d) => p.problem(d)),\n"
        "}));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    theirs = json.loads(result.stdout)
    for index, data in enumerate(CASES):
        ours = pathdata.segments_of(data)
        assert len(ours) == len(theirs["read"][index]), data
        for one, other in zip(ours, theirs["read"][index], strict=True):
            assert one[0] == other[0], data
            assert list(one[1:]) == pytest.approx(other[1:], abs=1e-9), data
        read = pathdata.parsed(data)
        assert list(read.box) == pytest.approx(theirs["boxes"][index], abs=1e-9), data
        assert list(read.opens) == theirs["opens"][index], data
        turned = pathdata.extent(read.segments, 33.0, (5.0, 7.0))
        assert list(turned) == pytest.approx(theirs["turned"][index], abs=1e-9), data
        rings = pathdata.rings(read.segments)
        assert len(rings) == len(theirs["rings"][index]), data
        for (points, closed), (other, shut) in zip(rings, theirs["rings"][index], strict=True):
            assert closed == shut and len(points) == len(other), data
            assert [value for point in points for value in point] == pytest.approx(
                [value for point in other for value in point], abs=1e-9
            )
        if "A" in data.upper():
            # (Arcs are found by sines and cosines, which may differ in their last place.)
            for key, made in (
                ("words", pathdata.normalised(data)),
                ("moved", pathdata.moved(data, 3.25, -1.5)),
            ):
                assert [float(word) for word in made.split() if word not in "MLCZ"] == (
                    pytest.approx(
                        [float(word) for word in theirs[key][index].split() if word not in "MLCZ"],
                        abs=0.011,
                    )
                ), (data, key)
            continue
        assert pathdata.normalised(data) == theirs["words"][index], data
        assert pathdata.moved(data, 3.25, -1.5) == theirs["moved"][index], data
        assert pathdata.fitted(data, (10, 20, 300, 40)) == theirs["fitted"][index], data
    for data, said in zip(WRONG, theirs["wrong"], strict=True):
        with pytest.raises(pathdata.PathError) as raised:
            pathdata.parsed(data)
        assert str(raised.value) == said, data


def test_a_long_path_is_read_and_moved_quickly() -> None:
    import time

    words = ["M 300 100"]
    for n in range(1, 20001):
        angle = n / 20000 * 2 * math.pi
        x, y = 300 + 200 * math.cos(angle), 300 + 200 * math.sin(angle)
        words.append(f"C {x:.2f} {y:.2f} {x:.2f} {y:.2f} {x:.2f} {y:.2f}")
    data = " ".join(words) + " Z"
    began = time.perf_counter()
    pathdata.parsed(data)
    pathdata.parsed(pathdata.moved(data, 1.5, 2.5))
    # (Generous: a slow machine, a busy one.)
    assert time.perf_counter() - began < 2.0
