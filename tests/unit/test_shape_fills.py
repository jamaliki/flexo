"""What a shape may be filled and lined with besides one colour -- a gradient, a dash pattern of
its own, a line fainter than its fill -- and a picture shape: written, checked, drawn (SVG,
PDF), kept in the studio's YAML, and drawn the same by the studio's twin."""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo import freeform, gradients, shape_pictures
from flexo.drawing import read_drawing
from flexo.svg import svg_tag
from flexo.themes import resolve_palette, with_tone_roles

PALETTE = with_tone_roles(resolve_palette("paper", "default"))
STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
LINEAR = {"gradient": "linear", "angle": 90, "stops": [[0, "accent"], [1, "#ffffff", 0.5]]}
RADIAL = {
    "gradient": "radial",
    "centre": [0.25, 0.5],
    "radius": [0.5, 0.25],
    "stops": [[0, "paper"], [1, "accent2"]],
}


def drawn(spec: dict) -> ET.Element:
    root = ET.Element(svg_tag("svg"))
    freeform.draw(root, spec, freeform.geometry(spec), "s", PALETTE)
    return root


def test_a_gradient_fill_is_checked_as_written() -> None:
    made = freeform.checked({"kind": "rectangle", "at": [0, 0], "size": [10, 10], "fill": LINEAR})
    assert made["fill"] == {
        "gradient": "linear",
        "angle": 90.0,
        "stops": [[0.0, "accent"], [1.0, "#ffffff", 0.5]],
    }
    assert freeform.checked({"kind": "ellipse", "at": [0, 0], "size": [10, 10], "fill": RADIAL})[
        "fill"
    ]["radius"] == [0.5, 0.25]
    wrong = {
        "sideways": "fill's gradient must be linear or radial",
        "few": "two colours or more",
        "order": "in order",
        "colour": "must be none, a theme colour",
        "key": "A linear gradient has no centre",
    }
    cases = {
        "sideways": {"gradient": "sideways", "stops": [[0, "ink"], [1, "paper"]]},
        "few": {"gradient": "linear", "stops": [[0, "ink"]]},
        "order": {"gradient": "linear", "stops": [[0.5, "ink"], [0.2, "paper"]]},
        "colour": {"gradient": "linear", "stops": [[0, "nonsense"], [1, "paper"]]},
        "key": {"gradient": "linear", "centre": [0, 0], "stops": [[0, "ink"], [1, "paper"]]},
    }
    for name, fill in cases.items():
        with pytest.raises(freeform.ShapeError) as raised:
            freeform.checked({"kind": "rectangle", "at": [0, 0], "size": [10, 10], "fill": fill})
        assert raised.value.key == "fill" and wrong[name] in raised.value.message, (
            raised.value.message
        )


def test_a_linear_gradient_runs_corner_to_corner_at_its_angle() -> None:
    assert gradients.linear_ends({"angle": 0}, (0, 0, 100, 50)) == pytest.approx((0, 25, 100, 25))
    assert gradients.linear_ends({"angle": 90}, (0, 0, 100, 50)) == pytest.approx((50, 0, 50, 50))
    x1, y1, x2, y2 = gradients.linear_ends({"angle": 45}, (0, 0, 100, 100))
    # (Its ends level with the corners it runs from and to, along its way.)
    assert (x2 - x1) == pytest.approx(100.0) and (y2 - y1) == pytest.approx(100.0)


def test_a_gradient_is_drawn_in_the_shapes_own_box_turned_with_it() -> None:
    root = drawn(
        {"kind": "rectangle", "at": [10, 20], "size": [100, 50], "rotate": 30, "fill": LINEAR}
    )
    gradient = root.find(f".//{svg_tag('linearGradient')}")
    assert gradient is not None and gradient.get("gradientUnits") == "userSpaceOnUse"
    assert [gradient.get(k) for k in ("x1", "y1", "x2", "y2")] == ["60", "20", "60", "70"]
    stops = gradient.findall(svg_tag("stop"))
    assert (
        stops[0].get("stop-color") == PALETTE.get("tone-1-stroke")
        and stops[0].get("data-flexo-stop") == "tone-1-stroke"
    )
    assert stops[1].get("stop-opacity") == "0.5"
    outline = root.find(f".//{svg_tag('path')}")
    assert outline.get("fill") == "url(#s.fill)"
    radial = drawn({"kind": "ellipse", "at": [0, 0], "size": [100, 40], "fill": RADIAL}).find(
        f".//{svg_tag('radialGradient')}"
    )
    assert [radial.get(k) for k in ("cx", "cy", "r")] == ["25", "20", "50"]
    assert "scale(1 0.2)" in radial.get("gradientTransform")
    # Where one colour is wanted (words read against it): its colour half way.
    assert freeform.paint(LINEAR, PALETTE)[0].startswith("#")


def test_a_gradient_is_read_back_for_the_pdf_and_drawn_there() -> None:
    root = ET.Element(svg_tag("svg"), {"width": "200", "height": "100", "viewBox": "0 0 200 100"})
    freeform.draw(
        root,
        {"kind": "rectangle", "at": [10, 20], "size": [100, 50], "rotate": 90, "fill": LINEAR},
        freeform.geometry({"kind": "rectangle", "at": [10, 20], "size": [100, 50], "rotate": 90}),
        "s",
        PALETTE,
    )
    drawing = read_drawing(ET.tostring(root, encoding="unicode"))
    shape = drawing.root.items[0].items[0]
    gradient = shape.paint.gradient
    assert gradient is not None and gradient.kind == "linear"
    assert [stop[1] for stop in gradient.stops] == [PALETTE.get("tone-1-stroke"), "#ffffff"]
    # Its run (0, 0) to (1, 0) carried onto the page, turned with the shape: top to bottom
    # in its box is right to left on the page.
    a, b = gradient.matrix[:2]
    assert (a, b) == pytest.approx((0.0, 50.0), abs=1e-6) or (a, b) == pytest.approx(
        (-50.0, 0.0), abs=1e-6
    )
    from flexo.pdf import pdf_bytes

    pdf = pdf_bytes([ET.tostring(root, encoding="unicode")])
    assert b"/ShadingType 2" in pdf and b"/Shading << /Sh0" in pdf
    import re
    import zlib

    streams = [
        zlib.decompress(found) for found in re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S)
    ]
    assert any(b"W n" in stream and b"/Sh0 sh" in stream for stream in streams)


def test_dashes_of_its_own_and_a_fainter_line() -> None:
    spec = freeform.checked(
        {"kind": "line", "from": [0, 0], "to": [10, 0], "dash": [6, 2, 1, 2], "line_opacity": 0.4}
    )
    assert spec["dash"] == [6.0, 2.0, 1.0, 2.0] and spec["line_opacity"] == 0.4
    assert freeform.dash_array(spec) == (6.0, 2.0, 1.0, 2.0)
    path = drawn(spec).find(f".//{svg_tag('path')}")
    assert path.get("stroke-dasharray") == "6 2 1 2" and path.get("stroke-opacity") == "0.4"
    for wrong in ([5], [0, 0], [-1, 2], ["a", 1]):
        with pytest.raises(freeform.ShapeError, match="dash must be"):
            freeform.checked({"kind": "line", "from": [0, 0], "to": [10, 0], "dash": wrong})


def test_a_picture_shape_is_its_file_in_its_box(tmp_path: Path) -> None:
    (tmp_path / "part.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<circle cx="5" cy="5" r="5" fill="red"/></svg>'
    )
    spec = freeform.checked(
        {"kind": "picture", "at": [10, 10], "size": [40, 20], "source": "part.svg", "rotate": 15}
    )
    assert freeform.LABELS["picture"] == "Picture" and "picture" not in [
        k for _, kinds in freeform.SECTIONS for k in kinds
    ]
    with pytest.raises(freeform.ShapeError, match="needs source"):
        freeform.checked({"kind": "picture", "at": [0, 0], "size": [1, 1]})
    anchored = shape_pictures.anchored([{"kind": "group", "shapes": [spec]}], tmp_path)
    source = anchored[0]["shapes"][0]["source"]
    assert Path(source).is_absolute()
    image = drawn({**spec, "source": source}).find(f".//{svg_tag('image')}")
    assert image.get("href").startswith("data:image/svg+xml;base64,")
    assert (image.get("x"), image.get("width"), image.get("preserveAspectRatio")) == (
        "10",
        "40",
        "none",
    )
    # A file gone: its box, faintly, never an error.
    gone = drawn({**spec, "source": str(tmp_path / "gone.svg")})
    assert (
        gone.find(f".//{svg_tag('image')}") is None
        and gone.find(f".//{svg_tag('rect')}") is not None
    )
    assert shape_pictures.sources([{"kind": "group", "shapes": [spec]}]) == ["part.svg"]


def test_short_lists_of_numbers_are_written_on_one_line() -> None:
    import yaml

    from flexo.roundtrip import rewrite

    document = {"shapes": [{"kind": "polyline", "points": [[1, 2], [3, 4.5]], "fill": LINEAR}]}
    written = rewrite("shapes: []\n", document, lambda d: yaml.safe_dump(d, sort_keys=False))
    assert (
        "- [1, 2]\n" in written
        and "- [0, accent]" in written
        and "- [1, '#ffffff', 0.5]" in written
    )
    assert yaml.safe_load(written) == document


def test_the_studio_draws_these_as_flexo_does() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    shapes = [
        {
            "kind": "rectangle",
            "at": [10, 20],
            "size": [100, 50],
            "rotate": 30,
            "fill": LINEAR,
            "line_opacity": 0.5,
            "dash": [3, 1],
        },
        {"kind": "ellipse", "at": [0, 0], "size": [100, 40], "fill": RADIAL},
        {
            "kind": "picture",
            "at": [5, 5],
            "size": [30, 20],
            "source": "a.svg",
            "flip": "horizontal",
        },
    ]
    script = (
        f"import * as f from {json.dumps((STATIC / 'freeform.js').as_uri())};\n"
        f"import * as g from {json.dumps((STATIC / 'gradients.js').as_uri())};\n"
        f"const shapes = {json.dumps(shapes)};\n"
        "const out = shapes.map((spec) => { const made = f.geometry(spec); return { box: made.box, "
        "segments: made.segments, "
        "svg: f.svg(spec, made, { 'tone-1-stroke': '#1a5d9b', 'tone-2-stroke': '#824c0d', canvas: "
        "'#ffffff' }) }; });\n"
        "const ends = g.linearEnds({ angle: 45 }, [0, 0, 100, 50]);\n"
        "console.log(JSON.stringify({ out, ends, dash: f.dashArray({ dash: [3, 1] }), "
        "defaults: f.defaults('picture') }));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    answered = json.loads(result.stdout)
    assert answered["ends"] == pytest.approx(
        list(gradients.linear_ends({"angle": 45}, (0, 0, 100, 50)))
    )
    assert answered["dash"] == [3, 1]
    assert answered["defaults"] == freeform.defaults("picture")
    for spec, theirs in zip(shapes, answered["out"], strict=True):
        made = freeform.geometry(spec)
        assert list(made.box) == pytest.approx(theirs["box"])
        assert len(made.segments) == len(theirs["segments"])
    rect, oval, picture = (item["svg"] for item in answered["out"])
    assert 'x1="60" y1="20" x2="60" y2="70"' not in rect  # (turned: its own box, its own frame)
    assert (
        "<linearGradient" in rect
        and 'stroke-opacity="0.5"' in rect
        and 'stroke-dasharray="3 1"' in rect
    )
    assert "<radialGradient" in oval and "scale(1 0.2)" in oval
    # Not yet drawn by the page: its box, faintly.
    assert 'stroke-dasharray="3 2"' in picture
