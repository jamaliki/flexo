"""Shapes drawn where they are put (``flexo.freeform``): what may be written, each kind's
outline, arrowheads, glue, painting -- and the studio's twin in JavaScript, which must draw
every shape number for number as this does."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo import freeform
from flexo.themes import resolve_palette, with_tone_roles

PALETTE = with_tone_roles(resolve_palette("paper", "default"))
SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "freeform.js"


HOLED = "M 10 10 C 20 0 40 0 50 10 L 50 40 Z M 20 20 L 30 20 L 30 30 Z"
DONUT = (
    "M 100 50 A 50 50 0 1 1 0 50 A 50 50 0 1 1 100 50 Z "
    "M 75 50 A 25 25 0 1 0 25 50 A 25 25 0 1 0 75 50 Z"
)
PATHS = [
    {"kind": "path", "d": HOLED, "fill_rule": "evenodd", "text": "words"},
    {"kind": "path", "d": HOLED, "rotate": 30, "flip": "horizontal", "fill": "accent"},
    {"kind": "path", "d": DONUT, "flip": "both", "rotate": 200},
    {"kind": "path", "d": "M 0 0 C 50 -50 100 50 150 0", "start": "dot", "end": "triangle"},
    {"kind": "path", "d": "m 0 0 q 30 30 60 0 t 60 0", "end": "stealth", "rotate": 45},
    {
        "kind": "path",
        "d": "M 0 0 L 40 0 L 40 40 Z M 60 60 L 90 60",
        "start": "triangle",
        "end": "bar",
    },
    {"kind": "path", "d": "M 5 5 h 20 v 20 h -20 z", "start": "triangle", "end": "triangle"},
]
"""Paths: holes, mirrored and turned, open with heads (at an open end only), arcs and
quadratics."""


def every_kind() -> list[dict]:
    """A shape of every kind, and of each kind's settings worth seeing apart."""

    shapes: list[dict] = []
    for kind in freeform.LINES:
        shapes.append({"kind": kind, "from": [100, 120], "to": [300, 220], "text": "label"})
        shapes.append(
            {
                "kind": kind,
                "from": [300, 100],
                "to": [120, 40],
                "line_width": 3,
                "start": "dot",
                "end": "stealth",
            }
        )
    for head in freeform.HEADS:
        shapes.append(
            {
                "kind": "arrow",
                "from": [10, 10],
                "to": [200, 90],
                "start": head,
                "end": head,
                "head_size": 1.5,
            }
        )
    shapes += [
        {
            "kind": "curved-arrow",
            "from": [0, 0],
            "to": [200, 0],
            "bend": -0.6,
            "lean": 0.2,
            "start": "open",
        },
        {"kind": "arc", "from": [0, 0], "to": [100, 100], "bend": 0.9},
        {"kind": "arc", "from": [0, 0], "to": [100, 0], "bend": 0.0},
        {"kind": "elbow", "from": [0, 0], "to": [100, 80], "route": "down", "elbow": 0.25},
        {"kind": "brace", "from": [0, 0], "to": [0, 200], "depth": -24, "curl": 0.2, "tip": 0.3},
        {"kind": "bracket", "from": [0, 0], "to": [180, 0], "depth": 20, "curl": 0.4},
        {"kind": "scale-bar", "from": [200, 400], "to": [80, 400], "text": "10 µm"},
    ]
    for kind in freeform.TRACED:
        shapes.append(
            {"kind": kind, "points": [[10, 10], [60, 90], [110, 30], [170, 80]], "end": "triangle"}
        )
        shapes.append({"kind": kind, "points": [[10, 10], [60, 90], [110, 30]], "closed": True})
        shapes.append({"kind": kind, "points": [[10, 10], [60, 90]]})
    for kind in freeform.BOXED:
        # (A zoom inset needs what it shows part of: it is never turned nor mirrored.)
        of = {"of": "body[0]"} if kind == "inset" else {}
        shapes.append({"kind": kind, "at": [40, 50], "size": [180, 110], **of})
        shapes.append(
            {
                "kind": kind,
                "at": [40, 50],
                "size": [90, 150],
                "rotate": 30,
                "flip": "horizontal",
                **of,
            }
        )
    shapes += [
        {"kind": "polygon", "at": [0, 0], "size": [100, 100], "sides": 3},
        {"kind": "polygon", "at": [0, 0], "size": [140, 100], "sides": 11, "flip": "both"},
        {"kind": "star", "at": [0, 0], "size": [100, 100], "tips": 8, "ratio": 0.7},
        {"kind": "rounded-rectangle", "at": [0, 0], "size": [40, 200], "corner": 300},
        {"kind": "bubble", "at": [100, 100], "size": [200, 100], "tail": [420, 160]},
        {
            "kind": "bubble",
            "at": [100, 100],
            "size": [200, 100],
            "tail": [80, 20],
            "body": "rectangle",
        },
        {
            "kind": "bubble",
            "at": [100, 100],
            "size": [200, 100],
            "tail": [150, 400],
            "body": "oval",
            "rotate": 40,
        },
        {"kind": "triangle", "at": [0, 0], "size": [100, 80], "apex": 0.0, "flip": "vertical"},
        {"kind": "text", "at": [10, 20], "width": 300},
        *PATHS,
        {
            "kind": "group",
            "shapes": [
                {"kind": "ellipse", "at": [0, 0], "size": [50, 50]},
                {"kind": "arrow", "from": [60, 60], "to": [160, 20]},
            ],
        },
    ]
    return shapes


# -- what may be written --


def test_every_kind_reads_as_written_and_is_drawn() -> None:
    root = ET.Element("svg")
    for index, spec in enumerate(every_kind()):
        made = freeform.checked(spec)
        geometry = freeform.geometry(made)
        group = freeform.draw(root, made, geometry, f"s{index}", PALETTE, freeform.Shadow())
        left, top, right, bottom = freeform.bounds(made, geometry)
        assert right >= left and bottom >= top, spec
        if made["kind"] != "group" and made["kind"] != "text":
            assert group.find("{http://www.w3.org/2000/svg}path") is not None, spec


@pytest.mark.parametrize(
    ("spec", "key", "words"),
    [
        ({"kind": "hexagon"}, "kind", "Unknown kind of shape 'hexagon'"),
        ({"kind": "arrow", "from": [0, 0]}, "to", "needs to"),
        ({"kind": "arrow", "from": [0, 0], "to": [1]}, "to", "must be a point"),
        (
            {"kind": "arrow", "from": [0, 0], "to": [1, 2], "end": "harpoon"},
            "end",
            "end must be one of none, triangle",
        ),
        (
            {"kind": "rectangle", "at": [0, 0], "size": [10, 10], "fill": "accent9"},
            "fill",
            "fill must be none",
        ),
        (
            {"kind": "rectangle", "at": [0, 0], "size": [10, 10], "fill": "#12"},
            "fill",
            "#rgb or #rrggbb",
        ),
        (
            {"kind": "rectangle", "at": [0, 0], "size": [10, 10], "sides": 5},
            "sides",
            "Unknown key sides",
        ),
        ({"kind": "polygon", "at": [0, 0], "size": [10, 10], "sides": 2}, "sides", "from 3 to 24"),
        (
            {"kind": "star", "at": [0, 0], "size": [10, 10], "ratio": 1.5},
            "ratio",
            "between 0.05 and 0.95",
        ),
        (
            {"kind": "ellipse", "at": [0, 0], "size": [10, 10], "opacity": "half"},
            "opacity",
            "must be a number",
        ),
        (
            {"kind": "arrow", "from": {"shape": "a", "side": "inside"}, "to": [0, 0]},
            "from",
            "side must be one of",
        ),
        ({"kind": "arrow", "from": {"side": "top"}, "to": [0, 0]}, "from", "glued to"),
        ({"kind": "group", "shapes": []}, "shapes", "one at least"),
        ({"kind": "group", "shapes": [{"kind": "oval"}]}, "shapes[0].kind", "Unknown kind"),
        ({"kind": "pen", "points": [[0, 0]]}, "points", "two points or more"),
        ({"kind": "line", "from": [0, 0], "to": [1e9, 0]}, "to", "points from the page"),
        (
            {"kind": "text", "at": [0, 0], "dash": "wavy"},
            "dash",
            "dash must be one of solid, dashed, dotted",
        ),
    ],
)
def test_what_is_wrong_is_said_under_its_key(spec: dict, key: str, words: str) -> None:
    with pytest.raises(freeform.ShapeError) as raised:
        freeform.checked(spec)
    assert raised.value.key == key
    assert words in str(raised.value)


def test_a_pages_own_keys_are_left_to_it() -> None:
    made = freeform.checked(
        {"kind": "arrow", "from": [0, 0], "to": [1, 1], "build": True}, extra=("build",)
    )
    assert made["build"] is True
    with pytest.raises(freeform.ShapeError):
        freeform.checked({"kind": "arrow", "from": [0, 0], "to": [1, 1], "build": True})


def test_names_are_read_as_a_person_writes_them() -> None:
    made = freeform.checked(
        {"kind": "text", "at": [0, 0], "align": "centre", "valign": "center", "fill": "None"}
    )
    assert (made["align"], made["valign"], made["fill"]) == ("middle", "middle", "none")
    assert (
        freeform.checked({"kind": "rectangle", "at": [0, 0], "size": [1, 1], "flip": "h"})["flip"]
        == "horizontal"
    )
    assert (
        freeform.checked({"kind": "ellipse", "at": [0, 0], "size": [1, 1], "rotate": 725})["rotate"]
        == 5
    )


def test_theme_colours_are_painted_by_their_roles() -> None:
    assert freeform.role_of("accent") == "tone-1-stroke"
    assert freeform.role_of("accent3-fill") == "tone-3-fill"
    assert freeform.role_of("paper") == "canvas"
    colour, role = freeform.paint("accent2", PALETTE)
    assert role == "tone-2-stroke" and colour == PALETTE.get("tone-2-stroke")
    assert freeform.paint("#c0392b", PALETTE) == ("#c0392b", None)
    assert freeform.paint("none", PALETTE) == (None, None)


# -- geometry --


def test_an_arrow_points_exactly_where_it_is_written_to() -> None:
    made = freeform.geometry({"kind": "arrow", "from": [0, 0], "to": [100, 0]})
    head = made.heads[0]
    tip = max(
        (
            point
            for segment in head.segments
            for point in zip(segment[1::2], segment[2::2], strict=True)
        ),
        key=lambda point: point[0],
    )
    assert tip == pytest.approx((100.0, 0.0))
    # The line stops under the head, not past its point.
    assert made.segments[-1][1] < 100.0


def test_a_curve_passes_through_its_bend() -> None:
    made = freeform.geometry(
        {"kind": "curved-arrow", "from": [0, 0], "to": [200, 0], "bend": 0.5, "end": "none"}
    )
    (_, x0, y0), (_, c1x, c1y, c2x, c2y, x3, y3) = made.segments
    middle = (
        0.125 * x0 + 0.375 * c1x + 0.375 * c2x + 0.125 * x3,
        0.125 * y0 + 0.375 * c1y + 0.375 * c2y + 0.125 * y3,
    )
    # Left of the way it runs on the page (y down): above a line running right.
    assert middle == pytest.approx((100.0, -100.0))


def test_an_arc_is_a_circles() -> None:
    made = freeform.geometry({"kind": "arc", "from": [0, 0], "to": [200, 0], "bend": 0.5})
    points = freeform.flattened(made.segments, 16)
    for x, y in points:
        assert math.hypot(x - 100.0, y - 0.0) == pytest.approx(100.0, abs=0.05)


def test_a_brace_reaches_its_depth_at_its_tip() -> None:
    made = freeform.geometry(
        {"kind": "brace", "from": [0, 0], "to": [0, 200], "depth": 20, "tip": 0.25}
    )
    points = freeform.flattened(made.segments, 32)
    far = max(points, key=lambda point: point[0])
    # Running down the page, its left is the page's right.
    assert far[0] == pytest.approx(20.0, abs=1e-6)
    assert far[1] == pytest.approx(50.0, abs=1.0)
    assert made.label.align == "start"


def test_a_polygon_and_a_star_fill_their_box() -> None:
    for spec in (
        {"kind": "polygon", "at": [10, 20], "size": [100, 60], "sides": 5},
        {"kind": "star", "at": [10, 20], "size": [100, 60], "tips": 5},
    ):
        left, top, right, bottom = freeform.bounds(spec)
        assert (left, top, right, bottom) == pytest.approx((10.0, 20.0, 110.0, 80.0))


def test_a_bubbles_tail_points_where_it_is_written() -> None:
    for body in ("rounded", "rectangle", "oval"):
        made = freeform.geometry(
            {"kind": "bubble", "at": [0, 0], "size": [200, 100], "tail": [260, 180], "body": body}
        )
        assert any(segment[-2:] == (260.0, 180.0) for segment in made.segments), body


def test_a_turned_box_turns_its_frame_and_not_its_outline() -> None:
    made = freeform.geometry({"kind": "rectangle", "at": [0, 0], "size": [100, 50], "rotate": 90})
    assert made.turn == 90.0 and made.centre == (50.0, 25.0)
    assert freeform.bounds(
        {"kind": "rectangle", "at": [0, 0], "size": [100, 50], "rotate": 90}, made
    ) == pytest.approx((25.0, -25.0, 75.0, 75.0))


def test_a_closed_shapes_words_go_inside_it_as_a_slide_program_sets_them() -> None:
    assert freeform.geometry({"kind": "rectangle", "at": [0, 0], "size": [100, 50]}).area == (
        0,
        0,
        100,
        50,
    )
    assert freeform.geometry(
        {"kind": "ellipse", "at": [0, 0], "size": [100, 100]}
    ).area == pytest.approx((14.645, 14.645, 70.71, 70.71))
    # Mirrored, its words go where its room is now (a triangle's apex at the left).
    flipped = freeform.geometry(
        {"kind": "triangle", "at": [0, 0], "size": [100, 100], "apex": 0.0, "flip": "vertical"}
    )
    assert flipped.area == pytest.approx((0.0, 0.0, 50.0, 50.0))


def test_dashes_keep_their_look_whatever_the_cap() -> None:
    assert freeform.dash_array({"dash": "dashed", "line_width": 2, "cap": "butt"}) == (8.0, 6.0)
    assert freeform.dash_array({"dash": "dashed", "line_width": 2, "cap": "round"}) == (6.0, 8.0)
    assert freeform.dash_array({"dash": "dotted", "line_width": 2, "cap": "round"}) == (0.0, 6.0)
    assert freeform.dash_array({"dash": "solid", "line_width": 2}) == ()


# -- glue --


def test_an_end_glued_to_a_side_follows_it() -> None:
    box = freeform.target_of({"kind": "rectangle", "at": [100, 100], "size": [100, 50]})
    line = {"kind": "arrow", "from": [0, 0], "to": {"shape": "box", "side": "left"}}
    assert freeform.glued(line, lambda end: box)[1] == (100.0, 125.0)
    # Left to itself, it meets the side facing its other end.
    line = {"kind": "arrow", "from": [150, 400], "to": {"shape": "box"}}
    assert freeform.glued(line, lambda end: box)[1] == (150.0, 150.0)


def test_an_end_at_a_centre_stops_at_the_outline() -> None:
    ring = freeform.target_of({"kind": "ellipse", "at": [0, 0], "size": [100, 100]})
    line = {"kind": "arrow", "from": [300, 50], "to": {"shape": "ring", "side": "centre"}}
    end = freeform.glued(line, lambda _: ring)[1]
    assert math.hypot(end[0] - 50, end[1] - 50) == pytest.approx(50.0, abs=0.2)
    assert end[0] > 95


def test_an_end_glued_to_what_is_gone_stays_where_it_was() -> None:
    line = {"kind": "arrow", "from": [0, 0], "to": {"shape": "gone", "at": [40, 60]}}
    assert freeform.glued(line, lambda _: None)[1] == (40.0, 60.0)


def test_a_turned_shapes_sides_turn_with_it() -> None:
    box = freeform.target_of({"kind": "rectangle", "at": [0, 0], "size": [100, 50], "rotate": 90})
    assert freeform.sites(box)["right"] == pytest.approx((50.0, 75.0))


# -- paths --


def test_a_path_is_read_as_written_and_drawn_in_its_box() -> None:
    spec = {
        "kind": "path",
        "d": HOLED,
        "fill_rule": "evenodd",
        "fill": "accent",
        "line": "ink",
        "line_width": 1.5,
        "text": "words",
    }
    assert freeform.checked(spec) == spec
    made = freeform.geometry(spec)
    # Its box is what it draws (the curve reaches 2.5 above its ends, not its controls' 0).
    assert made.box == pytest.approx((10.0, 2.5, 40.0, 37.5))
    assert made.closed and made.area == made.box and made.turn == 0.0
    root = ET.Element("svg")
    group = freeform.draw(root, spec, made, "p", PALETTE, freeform.Shadow())
    assert group.get("fill-rule") == "evenodd"
    outline = group.find("{http://www.w3.org/2000/svg}path")
    assert outline.get("d") == HOLED
    assert freeform.closed(spec) and freeform.family("path") == "path"
    assert freeform.LABELS["path"] == "Path" and "path" in freeform.KINDS
    # Drawn by the pen, among the lines; the pencil draws by hand.
    assert "path" in dict(freeform.SECTIONS)["Lines"]
    assert freeform.TOOLS["path"] == "Pen" and freeform.LABELS["pen"] == "Pencil"


def test_a_path_turns_and_mirrors_about_its_boxs_middle() -> None:
    plain = freeform.geometry({"kind": "path", "d": "M 0 0 L 100 0 L 100 50"})
    mirrored = freeform.geometry({"kind": "path", "d": "M 0 0 L 100 0 L 100 50", "flip": "both"})
    assert mirrored.box == plain.box
    assert [list(segment) for segment in mirrored.segments] == [
        ["M", 100.0, 50.0],
        ["L", 0.0, 50.0],
        ["L", 0.0, 0.0],
    ]
    spec = {"kind": "path", "d": "M 0 0 L 100 0 L 100 50 L 0 50 Z", "rotate": 90}
    made = freeform.geometry(spec)
    assert made.turn == 90.0 and made.centre == (50.0, 25.0)
    assert freeform.bounds(spec, made) == pytest.approx((25.0, -25.0, 75.0, 75.0))
    root = ET.Element("svg")
    group = freeform.draw(root, spec, made, "p", PALETTE)
    assert group.get("transform") == "rotate(90 50 25)"


def test_a_paths_heads_go_on_its_open_ends_only() -> None:
    open_path = freeform.geometry(
        {"kind": "path", "d": "M 0 0 C 50 -50 100 50 150 0", "start": "dot", "end": "triangle"}
    )
    assert [head.end for head in open_path.heads] == ["start", "end"]
    assert open_path.heads[1].tip == pytest.approx((150.0, 0.0))
    # Under the triangle the curve is cut short.
    assert open_path.segments[-1][-2] < 150.0
    closed_path = freeform.geometry(
        {"kind": "path", "d": "M 0 0 L 40 0 L 40 40 Z", "start": "dot", "end": "triangle"}
    )
    assert closed_path.heads == []
    # Its first piece closed and its last open: an end, and no start.
    both = freeform.geometry(
        {
            "kind": "path",
            "d": "M 0 0 L 40 0 L 40 40 Z M 60 60 L 90 60",
            "start": "dot",
            "end": "bar",
        }
    )
    assert [head.end for head in both.heads] == ["end"]
    assert freeform.path_open({"kind": "path", "d": "M 0 0 L 40 0 L 40 40 Z M 60 60 L 90 60"})
    assert not freeform.path_open({"kind": "path", "d": "M 0 0 L 40 0 L 40 40 Z"})


def test_a_path_moved_is_written_again() -> None:
    spec = {"kind": "path", "id": "p", "d": "m 10 10 h 20 v 20 z", "rotate": 15}
    moved = freeform.moved(spec, 5, -2.5)
    assert moved == {"kind": "path", "id": "p", "d": "M 15 7.5 L 35 7.5 L 35 27.5 Z", "rotate": 15}
    # Not moved, it is as written.
    assert freeform.moved(spec, 0, 0)["d"] == "m 10 10 h 20 v 20 z"
    group = freeform.moved({"kind": "group", "shapes": [spec]}, 1, 1)
    assert group["shapes"][0]["d"] == "M 11 11 L 31 11 L 31 31 Z"


@pytest.mark.parametrize(
    ("spec", "key", "words"),
    [
        ({"kind": "path"}, "d", "A path needs d"),
        ({"kind": "path", "d": "L 1 1"}, "d", "a path starts with M"),
        ({"kind": "path", "d": 12}, "d", "d must be SVG path data"),
        ({"kind": "path", "d": "M 0 0 C 1 2"}, "d", "C at character 7 needs 6 numbers"),
        ({"kind": "path", "d": "M 0 0 L 1 1", "at": [0, 0]}, "at", "Unknown key at for a path"),
        ({"kind": "path", "d": "M 0 0 L 1 1", "size": [1, 1]}, "size", "Unknown key size"),
        (
            {"kind": "path", "d": "M 0 0 L 1 1", "fill_rule": "odd"},
            "fill_rule",
            "fill_rule must be one of nonzero, evenodd",
        ),
    ],
)
def test_what_is_wrong_with_a_path_is_said_under_its_key(spec: dict, key: str, words: str) -> None:
    with pytest.raises(freeform.ShapeError) as raised:
        freeform.checked(spec)
    assert raised.value.key == key
    assert words in str(raised.value)


def test_a_figures_path_written_wrong_is_said_where_it_is() -> None:
    from flexo.figure_shapes import read

    shapes = [{"kind": "arrow", "from": [0, 0], "to": [1, 1]}] * 3 + [{"kind": "path", "d": "L 1"}]
    found, said = read(shapes)
    assert found[3] is None
    assert said[0].message.startswith("shapes[3].d: a path starts with M")


def test_a_lines_end_is_glued_to_a_paths_outline() -> None:
    # A ring: its sides' sites are on its outline, level with its middle.
    ring = freeform.target_of({"kind": "path", "d": DONUT})
    sites = freeform.sites(ring)
    assert sites["right"] == pytest.approx((100.0, 50.0), abs=0.05)
    assert sites["top"] == pytest.approx((50.0, 0.0), abs=0.05)
    assert sites["centre"] == (50.0, 50.0)
    # At its centre an end stops at its outline -- the outer one, its hole passed over.
    line = {"kind": "arrow", "from": [300, 50], "to": {"shape": "ring", "side": "centre"}}
    end = freeform.glued(line, lambda _: ring)[1]
    assert math.hypot(end[0] - 50, end[1] - 50) == pytest.approx(50.0, abs=0.3)
    # A wedge's sides are where its outline is, level with its middle (or straight above it):
    # not its box's.
    wedge = freeform.target_of({"kind": "path", "d": "M 0 0 L 100 50 L 0 100 Z"})
    assert freeform.sites(wedge)["right"] == pytest.approx((100.0, 50.0))
    assert freeform.sites(wedge)["top"] == pytest.approx((50.0, 25.0))
    # Turned, its sites turn with it.
    turned = freeform.target_of({"kind": "path", "d": "M 0 0 L 100 50 L 0 100 Z", "rotate": 90})
    assert freeform.sites(turned)["right"] == pytest.approx((50.0, 100.0))
    glued = freeform.glued(
        {"kind": "arrow", "from": [50, 300], "to": {"shape": "wedge"}}, lambda _: turned
    )
    assert glued[1] == pytest.approx((50.0, 100.0))


# -- the studio's twin --


def test_the_studios_shapes_are_drawn_as_these_are() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    shapes = every_kind()
    script = (
        f"import * as f from {json.dumps(SCRIPT.as_uri())};\n"
        f"const shapes = {json.dumps(shapes)};\n"
        "const out = shapes.map((spec) => { const made = f.geometry(spec); "
        "return { segments: made.segments, heads: made.heads.map((head) => head.segments), "
        "area: made.area, box: made.box, turn: made.turn, label: made.label, "
        "bounds: f.bounds(spec, made) }; });\n"
        "const tables = { sections: f.SECTIONS, labels: f.LABELS, tools: f.TOOLS, heads: f.HEADS, "
        "sizes: f.SIZES, "
        "defaults: Object.fromEntries(f.KINDS.map((kind) => [kind, f.defaults(kind)])) };\n"
        "console.log(JSON.stringify({ out, tables }));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    answered = json.loads(result.stdout)
    tables = answered["tables"]
    assert [[name, list(kinds)] for name, kinds in freeform.SECTIONS] == tables["sections"]
    assert tables["labels"] == freeform.LABELS
    assert tables["tools"] == freeform.TOOLS
    assert list(freeform.HEADS) == tables["heads"]
    assert {kind: list(size) for kind, size in freeform.SIZES.items()} == tables["sizes"]
    assert {kind: freeform.defaults(kind) for kind in freeform.KINDS} == tables["defaults"]
    for spec, theirs in zip(shapes, answered["out"], strict=True):
        made = freeform.geometry(spec)
        _same(made.segments, theirs["segments"], spec)
        assert len(made.heads) == len(theirs["heads"]), spec
        for head, other in zip(made.heads, theirs["heads"], strict=True):
            _same(head.segments, other, spec)
        assert made.turn == pytest.approx(theirs["turn"]), spec
        assert list(made.box) == pytest.approx(theirs["box"]), spec
        assert (list(made.area) if made.area else None) == (
            pytest.approx(theirs["area"]) if theirs["area"] else None
        )
        assert list(freeform.bounds(spec, made)) == pytest.approx(theirs["bounds"]), spec
        if made.label is not None:
            label = theirs["label"]
            assert (made.label.x, made.label.y, made.label.angle) == pytest.approx(
                (label["x"], label["y"], label["angle"])
            )
            assert (made.label.align, made.label.valign) == (label["align"], label["valign"]), spec


def _same(ours: list, theirs: list, spec: dict) -> None:
    assert len(ours) == len(theirs), spec
    for one, other in zip(ours, theirs, strict=True):
        assert one[0] == other[0], spec
        assert list(one[1:]) == pytest.approx(other[1:], abs=1e-6), spec


def test_the_cloud_is_a_figures_cloud() -> None:
    from flexo.drawing import parse_path
    from flexo.shapes import _cloud

    (start, arcs), _ = _cloud()
    data = f"M {start[0]!r} {start[1]!r} " + " ".join(
        f"A {radii[0]!r} {radii[1]!r} 0 {1 if large else 0} 1 {end[0]!r} {end[1]!r}"
        for radii, large, end in arcs
    )
    cubics = [segment for segment in parse_path(data) if segment.kind == "C"]
    assert len(cubics) == len(freeform.CLOUD)
    for segment, ours in zip(cubics, freeform.CLOUD, strict=True):
        assert [value for point in segment.points for value in point] == pytest.approx(
            list(ours), abs=1e-4
        )


def test_the_studios_paths_are_glued_to_and_moved_as_these_are() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"import * as f from {json.dumps(SCRIPT.as_uri())};\n"
        f"const paths = {json.dumps(PATHS)};\n"
        "console.log(JSON.stringify(paths.map((spec) => {\n"
        "  const target = f.targetOf(spec, f.geometry(spec));\n"
        "  const glued = ['top', 'right', 'bottom', 'left', 'centre', null].map((side) =>\n"
        "    f.glued({ kind: 'arrow', from: [300, 40],\n"
        "      to: { shape: 'p', ...(side ? { side } : {}) } }, () => target));\n"
        "  const moved = f.moved(spec, 2.5, -4);\n"
        "  const group = f.moved({ kind: 'group', shapes: [spec] }, 1, 1);\n"
        "  return { sites: f.sites(target), glued, moved: moved.d, keys: Object.keys(moved),\n"
        "    group: group.shapes[0].d, bounds: f.bounds(moved),\n"
        "    copy: JSON.parse(JSON.stringify(moved)) };\n"
        "})));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    for spec, theirs in zip(PATHS, json.loads(result.stdout), strict=True):
        target = freeform.target_of(spec)
        for side, point in freeform.sites(target).items():
            assert list(point) == pytest.approx(theirs["sites"][side], abs=1e-9), (spec, side)
        for side, other in zip(
            ("top", "right", "bottom", "left", "centre", None), theirs["glued"], strict=True
        ):
            line = {"kind": "arrow", "from": [300, 40], "to": {"shape": "p"}}
            if side:
                line["to"]["side"] = side
            ours = freeform.glued(line, lambda _, target=target: target)
            assert [list(point) for point in ours] == [
                pytest.approx(point, abs=1e-9) for point in other
            ], (spec, side)
        moved = freeform.moved(spec, 2.5, -4)
        # Moved, its outline is written again -- in its place among its keys.
        assert theirs["moved"] == moved["d"] and theirs["keys"] == list(moved)
        assert theirs["copy"] == moved
        assert theirs["group"] == freeform.moved(spec, 1, 1)["d"]
        assert list(freeform.bounds(moved)) == pytest.approx(theirs["bounds"], abs=0.01)


def test_a_paths_holes_are_kept_in_the_pdf_and_the_portable_svg() -> None:
    import re
    import zlib

    from flexo.drawing import read_drawing
    from flexo.pdf import pdf_bytes
    from flexo.portable import portable_svg
    from flexo.svg import svg_tag

    root = ET.Element(svg_tag("svg"), width="200", height="200", viewBox="0 0 200 200")
    for index, rule in enumerate(("evenodd", "nonzero")):
        spec = {"kind": "path", "d": DONUT, "fill_rule": rule, "fill": "accent", "line": "none"}
        freeform.draw(root, spec, freeform.geometry(spec), f"p{index}", PALETTE)
    text = ET.tostring(root, encoding="unicode")
    painted = [item for item in read_drawing(text).walk() if getattr(item, "segments", None)]
    assert [item.paint.fill_rule for item in painted] == ["evenodd", "nonzero"]
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes(text), re.S)
    content = b"".join(zlib.decompress(stream) for stream in streams if stream[:1] == b"x")
    assert content.count(b"\nf*") + content.count(b" f*") == 1
    assert portable_svg(text).count('fill-rule="evenodd"') == 1
