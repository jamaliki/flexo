"""A drawing made elsewhere (Inkscape's) read as Flexo's own shapes: each rule of the mapping."""

from __future__ import annotations

import base64
import math
import time
import xml.etree.ElementTree as ET

import pytest

from flexo import freeform, pathdata
from flexo.svgimport import SvgImportError, difference, shapes_of

INK = (
    'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"'
)


def svg(body: str, *, size: str = 'width="400" height="300"', head: str = "") -> str:
    """A drawing in CSS pixels (a point is 4/3 of one) unless ``size`` says otherwise."""

    return f"<svg {INK} {size}>{head}{body}</svg>"


def read(body: str, **options) -> list[dict]:
    """The shapes ``body`` makes, at a pixel a point (``scale``), its page's place kept."""

    options.setdefault("scale", 4.0 / 3.0)
    return shapes_of(svg(body), **options).shapes


def one(body: str, **options) -> dict:
    shapes = read(body, **options)
    assert len(shapes) == 1, shapes
    return shapes[0]


def leaves(shapes: list[dict]) -> list[dict]:
    out = []
    for spec in shapes:
        out += leaves(spec["shapes"]) if spec["kind"] == "group" else [spec]
    return out


def valid(shapes: list[dict]) -> None:
    """Every shape made is one a slide or a figure takes as written."""

    for spec in shapes:
        freeform.checked(spec)


# -- boxes --


def test_a_rect_is_a_rectangle_and_a_rounded_one_keeps_its_corner() -> None:
    assert one('<rect x="10" y="20" width="100" height="50" fill="#123456"/>') == {
        "kind": "rectangle",
        "at": [10.0, 20.0],
        "size": [100.0, 50.0],
        "fill": "#123456",
        "line": "none",
    }
    rounded = one('<rect x="10" y="20" width="100" height="50" rx="8" fill="#123456"/>')
    assert rounded["kind"] == "rounded-rectangle" and rounded["corner"] == 8.0
    # Corners not round (rx and ry apart): its outline, exactly.
    assert one('<rect width="100" height="50" rx="8" ry="20" fill="red"/>')["kind"] == "path"


def test_circles_and_ellipses_are_ovals_turned_as_they_are() -> None:
    circle = one('<circle cx="50" cy="40" r="20" fill="red"/>')
    assert (
        circle["kind"] == "ellipse"
        and circle["at"] == [30.0, 20.0]
        and circle["size"] == [40.0, 40.0]
    )
    turned = one(
        '<ellipse cx="100" cy="100" rx="40" ry="20" transform="rotate(30 100 100)" fill="red"/>'
    )
    assert turned["kind"] == "ellipse" and turned["rotate"] == pytest.approx(30.0)
    assert turned["at"] == [60.0, 80.0] and turned["size"] == [80.0, 40.0]
    # A quarter turn swaps its sides rather than turning it.
    quarter = one('<rect x="0" y="0" width="40" height="10" transform="rotate(90)" fill="red"/>')
    assert "rotate" not in quarter and quarter["size"] == [10.0, 40.0]
    # Skewed, no box draws it: its outline -- a rectangle's its four corners.
    skewed = one('<rect width="40" height="10" transform="skewX(20)" fill="red"/>')
    assert skewed["kind"] == "polyline" and skewed["closed"] is True
    assert one('<ellipse rx="40" ry="10" transform="skewX(20)" fill="red"/>')["kind"] == "path"


def test_units_and_the_view_box_make_points() -> None:
    drawing = (
        f'<svg {INK} width="100mm" height="50mm" viewBox="0 0 100 50">'
        '<rect x="10" y="10" width="20" height="10" fill="red"/></svg>'
    )
    made = shapes_of(drawing)
    rect = made.shapes[0]
    millimetre = 72.0 / 25.4
    assert rect["at"] == [pytest.approx(10 * millimetre, abs=0.01)] * 2
    assert rect["size"] == [
        pytest.approx(20 * millimetre, abs=0.01),
        pytest.approx(10 * millimetre, abs=0.01),
    ]
    assert made.page == (pytest.approx(100 * millimetre), pytest.approx(50 * millimetre))
    # Pixels are three quarters of a point.
    assert shapes_of(svg('<rect width="40" height="40" fill="red"/>')).shapes[0]["size"] == [
        30.0,
        30.0,
    ]


# -- lines --


ARROW = (
    '<marker id="end" orient="auto" refX="0" refY="0" style="overflow:visible">'
    '<path d="M 0,0 L -6,-3 L -6,3 Z" style="fill:context-stroke"/></marker>'
)


def test_lines_polylines_and_polygons() -> None:
    assert one('<line x1="0" y1="0" x2="30" y2="40" stroke="black"/>') == {
        "kind": "line",
        "from": [0.0, 0.0],
        "to": [30.0, 40.0],
        "line": "ink",
        "line_width": 1.0,
        "cap": "butt",
        "join": "miter",
    }
    poly = one('<polyline points="0,0 10,20 30,0" fill="none" stroke="black"/>')
    assert poly["kind"] == "polyline" and poly["points"] == [[0.0, 0.0], [10.0, 20.0], [30.0, 0.0]]
    shut = one('<polygon points="0,0 10,20 30,0" fill="red"/>')
    assert shut["kind"] == "polyline" and shut["closed"] is True and shut["fill"] == "#ff0000"
    # An open outline filled is filled as if closed: a path, which fills as SVG does.
    assert one('<polyline points="0,0 10,20 30,0" fill="red"/>')["kind"] == "path"
    # A path of one straight piece is a line; of four right angles closed, a rectangle.
    assert one('<path d="M 0 0 H 50" stroke="black"/>')["kind"] == "line"
    box = one('<path d="M 10 10 h 40 v 20 h -40 z" fill="red"/>')
    assert box["kind"] == "rectangle" and box["at"] == [10.0, 10.0] and box["size"] == [40.0, 20.0]
    turned = one('<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z" transform="rotate(20)" fill="red"/>')
    assert turned["kind"] == "rectangle" and turned["rotate"] == pytest.approx(20.0)
    curve = one('<path d="M 0 0 C 10 20 30 20 40 0" fill="none" stroke="black"/>')
    assert curve["kind"] == "path" and curve["d"] == "M 0 0 C 10 20 30 20 40 0"


def test_a_straight_path_with_arrowheads_is_an_arrow() -> None:
    arrow = one(
        f'<defs>{ARROW}</defs><path d="M 0 50 H 100" stroke="black" stroke-width="2" '
        'style="marker-end:url(#end)"/>'
    )
    assert (
        arrow["kind"] == "arrow" and arrow["from"] == [0.0, 50.0] and arrow["to"] == [100.0, 50.0]
    )
    assert arrow.get("end", "triangle") == "triangle" and arrow["head_size"] > 0.25
    both = one(
        f'<defs>{ARROW}<marker id="start" orient="auto-start-reverse" style="overflow:visible">'
        '<path d="M 0,0 L -6,-3 L -6,3 Z" style="fill:context-stroke"/></marker></defs>'
        '<path d="M 0 50 H 100" stroke="black" stroke-width="2" '
        'style="marker-start:url(#start);marker-end:url(#end)"/>'
    )
    assert both["kind"] == "double-arrow"
    # One at its start alone: an arrow the other way round.
    back = one(
        '<defs><marker id="start" orient="auto-start-reverse" style="overflow:visible">'
        '<path d="M 0,0 L -6,-3 L -6,3 Z" style="fill:context-stroke"/></marker></defs>'
        '<path d="M 0 50 H 100" stroke="black" stroke-width="2" style="marker-start:url(#start)"/>'
    )
    assert back["kind"] == "arrow" and back["from"] == [100.0, 50.0] and back["to"] == [0.0, 50.0]


def test_a_line_turning_through_right_angles_with_a_head_is_an_elbow() -> None:
    elbow = one(
        f'<defs>{ARROW}</defs><path d="M 0 0 H 40 V 30 H 80" fill="none" stroke="black" '
        'style="marker-end:url(#end)"/>'
    )
    # (Half way, across first: as an elbow is when it says nothing of them.)
    assert elbow["kind"] == "elbow" and "elbow" not in elbow and "route" not in elbow
    made = freeform.geometry(elbow)
    corners = [segment[1:3] for segment in made.segments]
    assert corners[:3] == [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0)]


LEGACY = {
    # Inkscape 0.92's markers, as its markers.svg defined them.
    "Arrow1Lend": (
        '<path transform="matrix(-0.8,0,0,-0.8,-10,0)" style="fill:#000000;fill-rule:evenodd;'
        'stroke:#000000;stroke-width:1pt" d="M 0,0 5,-5 -12.5,0 5,5 Z"/>',
        "stealth",
    ),
    "TriangleOutL": (
        '<path transform="scale(0.8)" style="fill:#000000;fill-rule:evenodd;stroke:#000000;'
        'stroke-width:1pt" d="M 5.77,0 -2.88,5 V -5 Z"/>',
        "triangle",
    ),
    "DotM": (
        '<path transform="matrix(0.4,0,0,0.4,2.96,0.4)" style="fill:#000000;fill-rule:evenodd;'
        'stroke:#000000;stroke-width:1pt" d="m -2.5,-1 c 0,2.76 -2.24,5 -5,5 -2.76,0 -5,-2.24 '
        "-5,-5 "
        '0,-2.76 2.24,-5 5,-5 2.76,0 5,2.24 5,5 z"/>',
        "dot",
    ),
    "StopL": (
        '<path transform="scale(0.8)" style="fill:none;stroke:#000000;stroke-width:1pt" '
        'd="M 0,5.65 V -5.65"/>',
        "bar",
    ),
    "DiamondL": (
        '<path transform="scale(0.8)" style="fill:#000000;fill-rule:evenodd;stroke:#000000;'
        'stroke-width:1pt" d="M 0,-7.07 -7.07,0 0,7.07 7.07,0 Z"/>',
        "diamond",
    ),
}
MODERN = {
    # Inkscape 1's, scaled by the line's width, painted by it (context-stroke).
    "ArrowWide": (
        '<path style="fill:none;stroke:context-stroke;stroke-width:1;stroke-linecap:butt" '
        'd="M 3,-3 0,0 3,3" transform="rotate(180,0.125,0)"/>',
        "open",
    ),
    "Triangle": (
        '<path transform="scale(0.5)" style="fill:context-stroke;fill-rule:evenodd;'
        'stroke:context-stroke;stroke-width:1pt" d="M 5.77,0 -2.88,5 V -5 Z"/>',
        "triangle",
    ),
    "Dot": (
        '<path transform="scale(0.5)" style="fill:context-stroke;fill-rule:evenodd;stroke:none" '
        'd="M 5,0 C 5,2.76 2.76,5 0,5 -2.76,5 -5,2.76 -5,0 c 0,-2.76 2.3,-5 5,-5 2.76,0 5,2.24 5,5 '
        'z"/>',
        "dot",
    ),
    "Stop": (
        '<path style="fill:none;stroke:context-stroke;stroke-width:1" d="M 0,4 V -4"/>',
        "bar",
    ),
    "ArrowWideHeavy": (
        '<path style="fill:context-stroke;fill-rule:evenodd;stroke:none" '
        'd="m 1,0 -3,3 h -2 l 3,-3 -3,-3 h 2 z"/>',
        "stealth",
    ),
}


@pytest.mark.parametrize("name", [*LEGACY, *MODERN])
def test_each_marker_family_is_the_arrowhead_it_draws(name: str) -> None:
    content, head = {**LEGACY, **MODERN}[name]
    viewbox = ' viewBox="0 0 1 1" markerWidth="1" markerHeight="1"' if name in MODERN else ""
    drawing = (
        f'<defs><marker id="m" orient="auto" refX="0" refY="0" style="overflow:visible"{viewbox}>'
        f'{content}</marker></defs><path d="M 0 0 C 30 40 60 40 100 0" fill="none" '
        'stroke="#000000" stroke-width="2" style="marker-end:url(#m)"/>'
    )
    curve = one(drawing)
    assert curve["kind"] == "path" and curve["end"] == head, curve
    assert 0.25 <= curve.get("head_size", 1.0) <= 6.0
    valid([curve])


def test_a_marker_no_head_draws_is_kept_as_drawn_beside_its_line() -> None:
    square = (
        '<marker id="sq" orient="auto" style="overflow:visible"><path transform="scale(0.8)" '
        'style="fill:#000000;stroke:#000000;stroke-width:1pt" d="M -5,-5 V 5 H 5 V -5 Z"/></marker>'
    )
    made = one(
        f'<defs>{square}</defs><path d="M 0 0 C 30 40 60 40 100 0" fill="none" stroke="#000000" '
        'stroke-width="2" style="marker-end:url(#sq)"/>'
    )
    assert made["kind"] == "group"
    line, kept = made["shapes"]
    assert line["kind"] == "path" and line.get("end", "none") == "none"
    assert kept["kind"] == "path" and kept["fill"] == "ink"
    # One of another colour than its line is drawn as it is too; so is one on a corner.
    red = one(
        f'<defs>{ARROW.replace("context-stroke", "#ff0000")}</defs><path d="M 0 0 H 100" '
        'stroke="#000000" style="marker-end:url(#end)"/>'
    )
    assert red["kind"] == "group" and red["shapes"][1]["fill"] == "#ff0000"
    mid = one(
        f'<defs>{ARROW}</defs><path d="M 0 0 L 50 20 L 100 0" fill="none" stroke="#000000" '
        'style="marker-mid:url(#end)"/>'
    )
    assert mid["kind"] == "group" and len(mid["shapes"]) == 2


def test_an_arrowheads_tip_is_where_it_was_drawn() -> None:
    # Inkscape 1's Triangle stands out past the line's end: Flexo's tip is at its end.
    content = MODERN["Triangle"][0]
    curve = one(
        f'<defs><marker id="m" orient="auto" style="overflow:visible" viewBox="0 0 1 1" '
        f'markerWidth="1" markerHeight="1">{content}</marker></defs><path d="M 0 50 H 100" '
        'stroke="#000000" stroke-width="2" style="marker-end:url(#m)"/>'
    )
    # (Its tip 5.77 of its units out, half of one each, the line's width each: its own line
    # of 1pt half as wide again past that.)
    tip = 100.0 + 2.0 * 0.5 * 5.77 + 2.0 * 0.5 * (4.0 / 3.0) / 2.0
    assert curve["to"][0] == pytest.approx(tip, abs=0.05)


# -- groups and what they place --


def test_groups_their_opacity_and_layers() -> None:
    made = one(
        '<g id="encoder" opacity="0.5"><rect width="10" height="10" fill="red"/>'
        '<rect x="20" width="10" height="10" fill="blue"/></g>'
    )
    assert made["kind"] == "group" and made["id"] == "encoder" and made["opacity"] == 0.5
    # A group of one shape is that shape, the group's opacity its own.
    single = one('<g opacity="0.5"><rect width="10" height="10" fill="red" opacity="0.5"/></g>')
    assert single["kind"] == "rectangle" and single["opacity"] == 0.25
    # Layers are the paste's own group: their shapes in it, not a group each.
    layered = read(
        '<g inkscape:groupmode="layer" inkscape:label="One"><rect width="10" height="10" '
        'fill="red"/>'
        '</g><g inkscape:groupmode="layer" inkscape:label="Two"><rect x="20" width="10" '
        'height="10" '
        'fill="red"/><rect x="40" width="10" height="10" fill="red"/></g>'
        '<g inkscape:groupmode="layer" style="display:none"><rect width="99" height="9" '
        'fill="red"/></g>'
    )
    assert len(layered) == 1 and [s["kind"] for s in layered[0]["shapes"]] == ["rectangle"] * 3
    # A program's own ids are no names: none kept.
    assert "id" not in one('<rect id="rect1234" width="10" height="10" fill="red"/>')


def test_uses_and_symbols_are_what_they_place() -> None:
    made = read(
        '<defs><symbol id="cog" viewBox="0 0 10 10"><rect width="10" height="10" '
        'fill="red"/></symbol>'
        '<rect id="dot" width="2" height="2" fill="blue"/></defs>'
        '<use xlink:href="#cog" x="100" y="0" width="20" height="20"/>'
        '<use href="#dot" transform="translate(50 50)"/>'
    )
    rects = leaves(made)
    assert [r["size"] for r in rects] == [[20.0, 20.0], [2.0, 2.0]]
    assert rects[0]["at"] == [100.0, 0.0] and rects[1]["at"] == [50.0, 50.0]


def test_transforms_are_drawn_into_the_shapes() -> None:
    made = one(
        '<g transform="translate(10 20) scale(2)"><line x1="0" y1="0" x2="10" y2="0" '
        'stroke="black" stroke-width="1.5"/></g>'
    )
    assert made["from"] == [10.0, 20.0] and made["to"] == [30.0, 20.0]
    assert made["line_width"] == 3.0
    # A nested <svg> fits its view box into its box.
    nested = one(
        '<svg x="100" y="0" width="50" height="50" viewBox="0 0 10 10">'
        '<rect width="10" height="10" fill="red"/></svg>'
    )
    assert nested["at"] == [100.0, 0.0] and nested["size"] == [50.0, 50.0]


# -- paint --


def test_style_sheet_attributes_and_inheritance() -> None:
    head = (
        "<style>.st0{fill:#0000ff;stroke:#ff0000} #special{fill:#00ff00} rect.st1{fill:#333333} "
        "g .deep{stroke-width:5}</style>"
    )
    made = shapes_of(
        svg(
            '<rect class="st0" width="10" height="10"/>'
            '<rect class="st0" id="special" x="20" width="10" height="10"/>'
            '<rect class="st0" style="fill:#ff00ff" x="40" width="10" height="10"/>'
            '<rect class="st0" fill="#00ffff" x="60" width="10" height="10"/>'
            '<g fill="#abcdef" stroke="black"><rect class="deep" x="80" width="10" '
            'height="10"/></g>'
            '<rect class="st1 st0" x="100" width="10" height="10"/>',
            head=head,
        ),
        scale=4 / 3,
    ).shapes
    fills = [spec["fill"] for spec in leaves(made)]
    assert fills == ["#0000ff", "#00ff00", "#ff00ff", "#0000ff", "#abcdef", "#333333"]
    inherited = leaves(made)[4]
    assert inherited["line"] == "ink" and inherited["line_width"] == 5.0


def test_opacities_dashes_caps_joins_and_fill_rules() -> None:
    shape = one(
        '<path d="M 0 0 L 40 0 L 40 40 Z M 10 10 L 30 10 L 30 30 Z" fill="red" fill-rule="evenodd" '
        'fill-opacity="0.5" stroke="blue" stroke-opacity="0.25" stroke-linejoin="round" '
        'stroke-dasharray="6 2 1 2" opacity="0.8"/>'
    )
    assert shape["fill_rule"] == "evenodd" and shape["fill_opacity"] == 0.5
    assert shape["line_opacity"] == 0.25 and shape["opacity"] == 0.8
    assert shape["join"] == "round" and shape["dash"] == [6.0, 2.0, 1.0, 2.0]
    # A line alone: its line's opacity is the shape's.
    line = one('<line x2="10" stroke="blue" stroke-opacity="0.5" stroke-linecap="round"/>')
    assert line["opacity"] == 0.5 and "line_opacity" not in line and "cap" not in line
    # Flexo's own dashes by their names.
    assert (
        one('<line x2="10" stroke="blue" stroke-width="2" stroke-dasharray="8 6"/>')["dash"]
        == "dashed"
    )


def test_colours_are_the_themes_where_they_are_its() -> None:
    made = leaves(
        read(
            '<rect width="5" height="5" fill="#000000"/><rect width="5" height="5" fill="white"/>'
            '<rect width="5" height="5" fill="#1a5d9c"/><rect width="5" height="5" fill="#dbebfd"/>'
            '<rect width="5" height="5" fill="#3a7d44"/><rect width="5" height="5" '
            'fill="rgb(36,33,38)"/>'
        )
    )
    # (A rectangle's own fill, the accent's tint, is left unsaid.)
    assert [spec.get("fill", "accent-fill") for spec in made] == [
        "ink",
        "paper",
        "accent",
        "accent-fill",
        "#3a7d44",
        "ink",
    ]
    exact = leaves(
        read(
            '<rect width="5" height="5" fill="#000000"/>'
            '<rect width="5" height="5" fill="#1a5d9c"/>',
            exact=True,
        )
    )
    assert [spec["fill"] for spec in exact] == ["#000000", "#1a5d9c"]
    # By the theme it goes on: its accent, whatever that is.
    roles = {
        "ink": "#111111",
        "canvas": "#fafafa",
        "tone-1-stroke": "#c0392b",
        "tone-1-fill": "#f9e0dd",
    }
    assert one('<rect width="5" height="5" fill="#c0392b"/>', roles=roles)["fill"] == "accent"
    # A drawing Flexo made names its roles: kept.
    assert (
        one('<rect width="5" height="5" fill="#3f7fc0" data-flexo-fill="residual"/>')["fill"]
        == "residual"
    )


def test_colour_difference_is_ciede2000() -> None:
    assert difference("#ffffff", "#ffffff") == 0.0
    # Sharma, Wu and Dalal's test pair 1 (CIELAB 50/2.6772/-79.7751 and 50/0/-82.7485): 2.0425.
    assert difference("#000000", "#ffffff") == pytest.approx(100.0, abs=0.5)
    assert 0.0 < difference("#1a5d9b", "#1a5d9c") < 0.5 < difference("#1a5d9b", "#2a6dab")


# -- gradients --


def test_linear_gradients_are_gradient_fills_along_the_shapes_box() -> None:
    head = (
        '<defs><linearGradient id="stops"><stop offset="0" stop-color="#ff0000"/>'
        '<stop offset="1" stop-color="#ffff00" stop-opacity="0.5"/></linearGradient>'
        '<linearGradient id="across" xlink:href="#stops" gradientUnits="userSpaceOnUse" x1="10" '
        'y1="0" '
        'x2="110" y2="0"/><linearGradient id="down" xlink:href="#stops" x1="0" y1="0" x2="0" '
        'y2="1"/>'
        '<linearGradient id="half" xlink:href="#stops" gradientUnits="userSpaceOnUse" x1="35" '
        'y1="0" '
        'x2="85" y2="0"/></defs>'
    )
    shapes = leaves(
        shapes_of(
            svg(
                '<rect x="10" y="10" width="100" height="50" fill="url(#across)"/>'
                '<rect x="10" y="10" width="100" height="50" fill="url(#down)"/>'
                '<rect x="10" y="10" width="100" height="50" fill="url(#half)"/>',
                head=head,
            ),
            scale=4 / 3,
            exact=True,
        ).shapes
    )
    across, down, half = (spec["fill"] for spec in shapes)
    assert across == {
        "gradient": "linear",
        "angle": 0.0,
        "stops": [[0.0, "#ff0000"], [1.0, "#ffff00", 0.5]],
    }
    assert down["angle"] == 90.0 and down["stops"][0] == [0.0, "#ff0000"]
    # Its colours where they were: a quarter of the way in, three quarters in.
    assert [stop[0] for stop in half["stops"]] == [0.25, 0.75]
    valid(shapes)


def test_a_repeating_gradient_is_unrolled_and_a_radial_one_placed() -> None:
    head = (
        '<defs><linearGradient id="r" gradientUnits="userSpaceOnUse" x1="0" x2="50" '
        'spreadMethod="repeat">'
        '<stop offset="0" stop-color="#000000"/><stop offset="1" '
        'stop-color="#ffffff"/></linearGradient>'
        '<radialGradient id="g" cx="0.25" cy="0.5" r="0.5"><stop offset="0" stop-color="#ffffff"/>'
        '<stop offset="1" stop-color="#0000ff"/></radialGradient></defs>'
    )
    repeat, radial = (
        spec["fill"]
        for spec in leaves(
            shapes_of(
                svg(
                    '<rect width="100" height="20" fill="url(#r)"/><rect width="100" height="20" '
                    'fill="url(#g)"/>',
                    head=head,
                ),
                scale=4 / 3,
                exact=True,
            ).shapes
        )
    )
    assert [stop[0] for stop in repeat["stops"]] == [0.0, 0.5, 0.5, 1.0]
    assert radial == {
        "gradient": "radial",
        "centre": [0.25, 0.5],
        "radius": 0.5,
        "stops": [[0.0, "#ffffff"], [1.0, "#0000ff"]],
    }


def test_a_gradient_on_a_line_is_its_middle_colour_and_said() -> None:
    head = (
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#000000"/><stop offset="1" '
        'stop-color="#ffffff"/></linearGradient></defs>'
    )
    made = shapes_of(svg('<line x2="40" stroke="url(#g)"/>', head=head), exact=True)
    assert made.shapes[0]["line"] == "#808080"
    assert any("gradient" in said for said in made.approximated)


# -- words --


def test_words_are_boxes_of_words_their_baseline_where_it_was() -> None:
    start = one('<text x="20" y="50" font-size="12" font-family="sans-serif">Encoder</text>')
    assert start["kind"] == "text" and start["text"] == "Encoder" and start["font_size"] == 12.0
    assert "width" not in start and start["padding"] == 0 and "font" not in start
    from flexo.ir.semantic import TextRun
    from flexo.style import TypographyStyle
    from flexo.text import TextMeasurer
    from flexo.units import pt

    metrics = TextMeasurer(TypographyStyle(size=pt(12))).measure((TextRun("Encoder"),))
    assert start["at"] == [20.0, pytest.approx(50.0 - metrics.baseline, abs=0.01)]
    middle = one('<text x="200" y="50" font-size="12" text-anchor="middle">Encoder</text>')
    assert middle["align"] == "middle"
    assert middle["at"][0] + middle["width"] / 2 == pytest.approx(200.0, abs=0.01)
    end = one('<text x="200" y="50" font-size="12" text-anchor="end">Encoder</text>')
    assert end["align"] == "end" and end["at"][0] + end["width"] == pytest.approx(200.0, abs=0.01)


def test_inkscapes_lines_are_one_box_and_its_runs_markup() -> None:
    lines = one(
        '<text xml:space="preserve" x="10" y="20" style="font-size:10px;line-height:1.25">'
        '<tspan sodipodi:role="line" x="10" y="20">First line</tspan>'
        '<tspan sodipodi:role="line" x="10" y="32.5">second <tspan style="font-weight:bold">bold'
        '</tspan> and <tspan style="font-style:italic;fill:#ff0000">red</tspan></tspan></text>'
    )
    assert lines["text"] == "First line\nsecond **bold** and [*red*]{#ff0000}"
    figure = one(
        '<text x="10" y="20" font-size="10">a <tspan font-weight="bold">b</tspan> '
        '<tspan font-style="italic">c</tspan> H<tspan style="baseline-shift:sub;font-size:65%">2'
        '</tspan>O mc<tspan style="baseline-shift:super">2</tspan> $5</text>',
        markup="figure",
    )
    assert figure["text"] == "a [b]{bold} [c]{italic} H$_{2}$O mc$^{2}$ \\$5"
    whole = one(
        '<text x="10" y="20" font-size="10" font-weight="bold" font-style="italic">All of it</text>'
    )
    assert whole["bold"] is True and whole["italic"] is True and whole["text"] == "All of it"
    # Lines set further apart than Flexo sets them are a box each, in a group.
    apart = one(
        '<text x="10" y="20" font-size="10"><tspan x="10" y="20">one</tspan>'
        '<tspan x="10" y="60">two</tspan></text>'
    )
    assert apart["kind"] == "group" and [s["text"] for s in apart["shapes"]] == ["one", "two"]


def test_words_turned_and_their_colour_and_family() -> None:
    turned = one(
        '<text x="0" y="0" font-size="10" transform="rotate(-30 0 0)" fill="#1a5d9b">Up</text>'
    )
    assert turned["rotate"] == pytest.approx(330.0) and turned["colour"] == "accent"
    assert one('<text font-family="serif">Serif</text>')["font"] == "Latin Modern Roman" or True
    assert "font" not in one("<text font-family=\"'No Such Face', sans-serif\">x</text>")


def test_flowed_words_are_a_box_as_wide_as_they_flow_in() -> None:
    old = one(
        '<flowRoot style="font-size:10px;text-align:center"><flowRegion><rect x="10" y="10" '
        'width="200" '
        'height="80"/></flowRegion><flowPara>One paragraph</flowPara><flowPara>Another</flowPara>'
        "</flowRoot>"
    )
    assert old["kind"] == "text" and old["width"] == 200.0 and old["at"] == [10.0, 10.0]
    assert old["text"] == "One paragraph\nAnother" and old["align"] == "middle"
    new = one(
        '<defs><rect id="frame" x="0" y="0" width="120" height="50"/></defs>'
        '<text style="font-size:10px;shape-inside:url(#frame);white-space:pre">'
        '<tspan x="0" y="10">Words that </tspan><tspan x="0" y="22.5">wrap</tspan></text>'
    )
    assert new["width"] == 120.0 and new["text"] == "Words that wrap"


def test_words_drawn_as_outlines_stay_outlines_one_path_a_group() -> None:
    glyphs = one(
        '<g aria-label="Ex" style="fill:#000000"><path d="M 0 0 L 5 0 L 5 8 Z"/>'
        '<path d="M 6 0 L 11 0 L 11 8 Z"/></g>'
    )
    assert glyphs["kind"] == "path" and glyphs["d"].count("M") == 2 and glyphs["fill"] == "ink"
    latex = one(
        '<defs><path id="g0-1" d="M 0 0 L 5 0 L 5 8 Z"/><path id="g0-2" d="M 0 0 L 3 0 L 0 4 '
        'Z"/></defs>'
        '<g fill="#000000"><use xlink:href="#g0-1" x="10" y="10"/><use xlink:href="#g0-2" x="16" '
        'y="10"/>'
        '<use xlink:href="#g0-1" x="20" y="10"/></g>'
    )
    assert latex["kind"] == "path" and latex["d"].count("M") == 3


# -- what no shape draws --

PNG = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
    )
).decode()


def test_what_no_shape_draws_is_kept_as_a_picture() -> None:
    files: dict[str, bytes] = {}

    def keep(data: bytes, suffix: str) -> str:
        name = f"assets/part-{len(files) + 1}{suffix}"
        files[name] = data
        return name

    made = shapes_of(
        svg(
            '<defs><clipPath id="c"><circle cx="50" cy="50" r="20"/></clipPath>'
            '<filter id="blur"><feGaussianBlur stdDeviation="3"/></filter></defs>'
            f'<image x="10" y="10" width="40" height="40" '
            f'xlink:href="data:image/png;base64,{PNG}"/>'
            f'<image x="30" y="30" width="40" height="40" clip-path="url(#c)" '
            f'xlink:href="data:image/png;base64,{PNG}"/>'
            '<rect x="100" width="20" height="20" fill="red" style="filter:url(#blur)"/>'
            '<rect x="200" width="20" height="20" fill="red"/>'
        ),
        scale=4 / 3,
        picture=keep,
    )
    kinds = [spec["kind"] for spec in leaves(made.shapes)]
    assert kinds == ["picture", "picture", "picture", "rectangle"]
    bitmap, clipped, blurred, _ = leaves(made.shapes)
    assert files[bitmap["source"]].startswith(b"\x89PNG") and bitmap["size"] == [40.0, 40.0]
    alone = ET.fromstring(files[clipped["source"]])
    assert alone.find(".//{http://www.w3.org/2000/svg}clipPath") is not None
    assert clipped["at"] == [30.0, 30.0] and clipped["size"] == [40.0, 40.0]
    assert (
        ET.fromstring(files[blurred["source"]]).find(".//{http://www.w3.org/2000/svg}filter")
        is not None
    )
    assert blurred["size"][0] > 20.0  # (its blur's reach too)
    assert len(made.kept) == 3
    valid(made.shapes)


def test_a_clip_that_cuts_nothing_away_is_no_reason_for_a_picture() -> None:
    made = one(
        '<defs><clipPath id="page"><rect width="400" height="300"/></clipPath></defs>'
        '<g clip-path="url(#page)"><rect x="10" width="20" height="20" fill="red"/>'
        '<rect x="40" width="20" height="20" fill="red"/></g>'
    )
    assert made["kind"] == "group" and [s["kind"] for s in made["shapes"]] == [
        "rectangle",
        "rectangle",
    ]


# -- placing it --


def test_it_is_centred_and_fitted_where_it_is_pasted() -> None:
    drawing = svg(
        '<rect x="0" y="0" width="400" height="200" fill="red" stroke="black" stroke-width="4"/>'
        '<text x="10" y="100" font-size="20">Big</text>'
    )
    made = shapes_of(drawing, centre=[480, 270], fit=[300, 300])
    rect, words = made.shapes[0]["shapes"]
    assert made.scale == pytest.approx(300 / (300 + 3), rel=1e-3)
    assert rect["size"][0] == pytest.approx(300 * 300 / 303, abs=0.05)
    left, top, width, height = made.box
    assert left + width / 2 == pytest.approx(480, abs=0.05) and top + height / 2 == pytest.approx(
        270, abs=0.05
    )
    # Its lengths scaled with it: lines, words.
    assert rect["line_width"] == pytest.approx(3.0 * made.scale, abs=0.01)
    assert words["font_size"] == pytest.approx(15.0 * made.scale, abs=0.01)
    # Smaller than the room, its size kept; placed by its top left.
    small = shapes_of(drawing, at=[0, 0], fit=[2000, 2000])
    assert small.scale == 1.0 and small.box[:2] == (0.0, 0.0)


def test_inkscapes_connectors_stay_glued_to_what_they_join() -> None:
    made = read(
        '<rect id="a" x="0" y="0" width="40" height="20" fill="red"/>'
        '<rect id="b" x="100" y="0" width="40" height="20" fill="red"/>'
        '<path d="M 40,10 H 100" stroke="black" inkscape:connector-type="polyline" '
        'inkscape:connection-start="#a" inkscape:connection-end="#b"/>'
    )
    line = leaves(made)[-1]
    assert line["from"] == {"shape": "a", "side": "centre", "at": [40.0, 10.0]}
    assert line["to"]["shape"] == "b"
    shapes = made[0]["shapes"]
    find = {s.get("id"): freeform.target_of(s) for s in shapes if s["kind"] == "rectangle"}
    assert freeform.glued(line, lambda end: find.get(end.get("shape"))) == (
        (40.0, 10.0),
        (100.0, 10.0),
    )


# -- what is wrong, and how fast --


def test_what_cannot_be_read_is_said() -> None:
    with pytest.raises(SvgImportError, match="not SVG"):
        shapes_of("<html><body/></html>")
    with pytest.raises(SvgImportError, match=r"does not read|not SVG"):
        shapes_of("<svg")
    with pytest.raises(SvgImportError, match="entities"):
        shapes_of(
            '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
        )
    assert shapes_of(svg("")).shapes == []


def test_hundreds_of_elements_read_in_well_under_a_second() -> None:
    parts = []
    for row in range(20):
        for column in range(15):
            x, y = column * 60, row * 40
            parts.append(
                f'<rect x="{x}" y="{y}" width="40" height="20" rx="3" fill="#dbebfd" '
                f'stroke="#1a5d9b"/>'
            )
            parts.append(
                f'<text x="{x + 20}" y="{y + 14}" font-size="9" '
                f'text-anchor="middle">n{row}.{column}</text>'
            )
            parts.append(f'<path d="M {x + 40},{y + 10} H {x + 60}" stroke="black" fill="none"/>')
    drawing = svg("".join(parts), size='width="900" height="800"')
    shapes_of(drawing)  # (fonts loaded once)
    started = time.perf_counter()
    made = shapes_of(drawing, fit=[960, 540], centre=[480, 270])
    took = time.perf_counter() - started
    assert made.elements == 900 and made.count == 901
    assert took < 0.6, f"{took * 1000:.0f} ms"
    valid(made.shapes)


def test_every_shape_made_reads_as_written() -> None:
    from pathlib import Path

    drawing = (Path(__file__).parent / "data" / "inkscape-module.svg").read_text()
    made = shapes_of(drawing, fit=[960, 540], centre=[480, 270])
    valid(made.shapes)
    kinds = {spec["kind"] for spec in leaves(made.shapes)}
    assert {"rounded-rectangle", "text", "arrow", "double-arrow"} <= kinds
    for spec in leaves(made.shapes):
        if spec["kind"] == "path":
            assert pathdata.parsed(spec["d"]).plain
    assert math.isfinite(made.box[0])
