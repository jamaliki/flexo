"""Zoom insets (``flexo.insets``) and pictures masked by shapes (``flexo.masks``): read, placed
and drawn alike here and in the studio's twins, and read back by every other writer."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo import freeform, insets, masks
from flexo.drawing import Group, Image, read_drawing
from flexo.themes import resolve_palette, with_tone_roles

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SVG = "http://www.w3.org/2000/svg"
PALETTE = with_tone_roles(resolve_palette("paper", "default"))


def _palette():
    return PALETTE


# -- what may be written --


def test_an_inset_reads_as_written() -> None:
    made = freeform.checked(
        {
            "kind": "inset",
            "of": "body[0]",
            "region": [0.5, 0.25, 0.25, 0.5],
            "at": [10, 20],
            "size": [200, 100],
            "frame_line": "accent2",
            "connector_line": "none",
            "connector_dash": "dashed",
            "connector_width": 0.75,
            "text": "b",
        }
    )
    assert made["region"] == [0.5, 0.25, 0.25, 0.5]
    assert made["connector_line"] == "none"
    assert freeform.LABELS["inset"] == "Zoom Inset"
    assert freeform.normalised(made)["valign"] == "top"


@pytest.mark.parametrize(
    ("spec", "key"),
    [
        ({"kind": "inset", "at": [0, 0], "size": [10, 10]}, "of"),
        (
            {"kind": "inset", "of": "a", "at": [0, 0], "size": [9, 9], "region": [0.9, 0, 0.5, 1]},
            "region",
        ),
        (
            {"kind": "inset", "of": "a", "at": [0, 0], "size": [9, 9], "region": [0, 0, 0, 1]},
            "region",
        ),
        (
            {"kind": "inset", "of": "a", "at": [0, 0], "size": [9, 9], "frame_dash": "wavy"},
            "frame_dash",
        ),
        ({"kind": "rectangle", "at": [0, 0], "size": [9, 9], "of": "a"}, "of"),
    ],
)
def test_an_inset_written_wrong_says_where(spec: dict, key: str) -> None:
    with pytest.raises(freeform.ShapeError) as raised:
        freeform.checked(spec)
    assert raised.value.key == key


# -- where it goes --


@pytest.mark.parametrize(
    ("box", "wanted"),
    [
        ((300, 0, 100, 100), [((110, 10), (300, 0)), ((110, 60), (300, 100))]),
        ((-300, 0, 100, 100), [((10, 10), (-200, 0)), ((10, 60), (-200, 100))]),
        ((0, 300, 100, 100), [((10, 60), (0, 300)), ((110, 60), (100, 300))]),
        ((0, -300, 100, 100), [((10, 10), (0, -200)), ((110, 10), (100, -200))]),
        ((20, 20, 30, 30), []),
    ],
)
def test_the_lines_join_the_corners_facing_each_other(box: tuple, wanted: list) -> None:
    joined = insets.connectors((10, 10, 100, 50), box)
    assert [tuple(map(tuple, line)) for line in joined] == wanted


def test_the_region_fills_the_box_magnified() -> None:
    spec = {
        "kind": "inset",
        "of": "x",
        "region": [0.5, 0.5, 0.25, 0.25],
        "at": [500, 0],
        "size": [200, 100],
    }
    shown = insets.placed(spec, (0, 0, 400, 200))
    assert shown.region == (200, 100, 100, 50)
    assert shown.scale == pytest.approx(2.0)
    # The region's corners land on the box's.
    x, y = shown.offset
    assert (x + shown.scale * 200, y + shown.scale * 100) == pytest.approx((500, 0))
    assert (x + shown.scale * 300, y + shown.scale * 150) == pytest.approx((700, 100))


def test_a_piece_is_drawn_as_the_box_unless_it_says() -> None:
    spec = {
        "kind": "inset",
        "of": "x",
        "at": [0, 0],
        "size": [1, 1],
        "line": "accent2",
        "dash": "dotted",
    }
    assert insets.piece(spec, "frame")["line"] == "accent2"
    assert insets.piece({**spec, "connector_width": 0.5}, "connector")["line_width"] == 0.5
    assert insets.piece(spec, "connector")["dash"] == "dotted"


# -- drawn --


def test_an_inset_draws_its_frame_lines_box_and_what_it_shows() -> None:
    root = ET.Element(f"{{{SVG}}}svg")
    spec = freeform.checked(
        {"kind": "inset", "of": "x", "region": [0, 0, 0.5, 0.5], "at": [300, 0], "size": [100, 100]}
    )
    made = freeform.geometry(spec)
    drawn = insets.draw(
        root, spec, made, "s0", _palette(), source=(0, 0, 100, 100), target="pic", unit=2.0
    )
    ids = [item.get("id") for item in drawn.iter() if item.get("id")]
    assert ids[:2] == ["s0", "s0.frame"]
    assert "s0.connectors" in ids and "s0.view" in ids and "s0.border" in ids
    used = drawn.find(f".//{{{SVG}}}use")
    assert used.get("href") == "#pic"
    # Its target is in units twice the shapes': magnified 2x, then halved.
    assert used.get("transform").startswith("matrix(1 0 0 1 ")
    assert drawn.get("data-flexo-region") == "0 0 50 50"


def test_with_nothing_to_magnify_it_is_its_box() -> None:
    root = ET.Element(f"{{{SVG}}}svg")
    spec = freeform.checked({"kind": "inset", "of": "gone", "at": [0, 0], "size": [100, 60]})
    drawn = insets.draw(
        root, spec, freeform.geometry(spec), "s0", _palette(), source=None, target=None
    )
    assert drawn.find(f".//{{{SVG}}}use") is None
    assert drawn.find(f".//{{{SVG}}}path") is not None


FIGURE = """
figure: {id: demo}
nodes:
- {id: encoder, label: Encoder}
- {id: decoder, label: Decoder}
edges:
- {from: encoder, to: decoder}
shapes:
- {kind: inset, of: encoder, on: encoder, region: [0.1, 0.1, 0.5, 0.5], at: [0, 70],
   size: [80, 50], text: b}
"""


def _figure(tmp_path: Path, text: str = FIGURE) -> str:
    from flexo.compiler import compile_figure
    from flexo.serialization import load_figure

    path = tmp_path / "figure.yaml"
    path.write_text(text)
    return compile_figure(load_figure(path)).document.text


def test_a_figures_inset_shows_its_part_and_moves_with_it(tmp_path: Path) -> None:
    svg = _figure(tmp_path)
    root = ET.fromstring(svg)
    inset = next(item for item in root.iter() if item.get("data-flexo-shape") == "inset")
    assert inset.get("data-flexo-of") == "encoder"
    assert inset.find(f".//{{{SVG}}}use").get("href") == "#encoder"
    # The box is on its part: at [0, 70] from the part's top left.
    part = next(item for item in root.iter() if item.get("id") == "encoder")
    assert part is not None
    region = [float(value) for value in inset.get("data-flexo-region").split()]
    box = [float(value) for value in inset.get("data-flexo-box").split()]
    assert box[1] - region[1] == pytest.approx(70 - 0.1 * region[3] / 0.5, abs=0.5)


def test_every_writer_reads_an_inset_as_the_part_magnified_and_clipped(tmp_path: Path) -> None:
    from flexo.pdf import pdf_bytes
    from flexo.portable import portable_svg

    svg = _figure(tmp_path)
    drawing = read_drawing(svg)

    def find(group: Group) -> Group | None:
        for item in group.items:
            if isinstance(item, Group):
                if item.data.get("data-flexo-inset") == "view":
                    return item
                found = find(item)
                if found is not None:
                    return found
        return None

    view = find(drawing.root)
    assert view is not None and view.clip is not None
    left, _, right, _ = view.clip
    assert right - left == pytest.approx(80, abs=0.01)
    assert view.items, "what it shows is read: the part's shapes and words, magnified"
    portable = portable_svg(svg)
    assert "clip-path" in portable
    assert pdf_bytes([svg]).startswith(b"%PDF")


def test_an_inset_of_what_holds_it_is_drawn_once(tmp_path: Path) -> None:
    svg = (
        f'<svg xmlns="{SVG}" viewBox="0 0 100 100"><g id="all"><rect x="0" y="0" width="10" '
        'height="10" fill="#f00"/><use href="#all" transform="translate(20 0)"/></g></svg>'
    )
    drawing = read_drawing(svg)
    assert len(list(drawing.walk())) == 2


# -- masks --


def test_a_mask_reads_as_written() -> None:
    assert masks.checked("circle") == "circle"
    assert masks.checked(None) is None
    assert masks.checked({"kind": "star", "tips": 6}) == {"kind": "star", "tips": 6}
    made = masks.checked({"kind": "polyline", "points": [[0, 0], [1, 0], [0.5, 1]]})
    assert made["closed"] is True
    for wrong in ({"kind": "arrow", "from": [0, 0], "to": [1, 1]}, {"kind": "inset"}, "square"):
        with pytest.raises(freeform.ShapeError):
            masks.checked(wrong)


def test_a_mask_in_a_box_fills_the_part_kept() -> None:
    segments = masks.outline({"kind": "rectangle"}, (10, 20, 100, 50))
    points = [segment[1:] for segment in segments if segment[0] != "Z"]
    assert min(p[0] for p in points) == pytest.approx(10)
    assert max(p[1] for p in points) == pytest.approx(70)


def test_a_turned_mask_is_drawn_turned_in_its_box() -> None:
    star = masks.outline(
        {"kind": "rectangle", "rotate": 90, "at": [0.25, 0], "size": [0.5, 1]}, (0, 0, 100, 100)
    )
    xs = [segment[1] for segment in star if segment[0] != "Z"]
    ys = [segment[2] for segment in star if segment[0] != "Z"]
    # Half as wide as it is tall, turned a quarter: as wide as the part kept, half as tall.
    assert max(xs) - min(xs) == pytest.approx(100)
    assert max(ys) - min(ys) == pytest.approx(50)


def test_a_mask_through_points_is_stretched_over_the_part_kept() -> None:
    segments = masks.outline(
        {"kind": "polyline", "points": [[0, 0], [1, 0], [0.5, 1]]}, (0, 0, 200, 100)
    )
    assert segments[0][:3] == ("M", 0.0, 0.0)
    assert segments[1][1:] == pytest.approx((200.0, 0.0))
    assert segments[-1] == ("Z",)


def _masked(outline: str) -> str:
    pixel = (
        "iVBORw0KGgoAAAANSUhEUgAAAAQAAAACCAIAAADwyuo0AAAAFElEQVR4nGM8ISfHAANMcBYDAwMAGVgBC"
        "NdbWuMAAAAASUVORK5CYII="
    )
    return (
        f'<svg xmlns="{SVG}" viewBox="0 0 200 100"><pattern id="p" patternUnits="userSpaceOnUse" '
        f'x="0" y="0" width="200" height="100"><image width="200" height="100" '
        f'href="data:image/png;base64,{pixel}"/></pattern>'
        f'<path id="pic" d="{outline}" fill="url(#p)"/></svg>'
    )


def test_a_masked_picture_is_read_as_a_picture_within_its_outline() -> None:
    from flexo.pdf import pdf_bytes
    from flexo.portable import portable_svg

    svg = _masked("M 0 0 L 200 0 L 100 100 Z")
    images = [item for item in read_drawing(svg).walk() if isinstance(item, Image)]
    assert len(images) == 1
    picture = images[0]
    assert picture.clip == pytest.approx((0, 0, 200, 100))
    assert [segment.kind for segment in picture.outline] == ["M", "L", "L", "Z"]
    assert "pic.mask" in portable_svg(svg)
    document = pdf_bytes([svg])
    assert document.startswith(b"%PDF")


# -- the studio's twins --


def _node(script: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_the_studio_places_insets_as_these_are() -> None:
    sources = [(0, 0, 400, 300), (50, 60, 120, 90)]
    specs = [
        {
            "kind": "inset",
            "of": "a",
            "at": [500, 40],
            "size": [200, 150],
            "region": [0.1, 0.2, 0.3, 0.2],
        },
        {"kind": "inset", "of": "a", "at": [-300, 10], "size": [100, 60]},
        {
            "kind": "inset",
            "of": "a",
            "at": [0, 400],
            "size": [300, 50],
            "region": [0.5, 0.5, 0.5, 0.5],
        },
        {
            "kind": "inset",
            "of": "a",
            "at": [10, 10],
            "size": [40, 40],
            "frame_line": "accent2",
            "connector_width": 0.5,
            "connector_dash": "dotted",
        },
    ]
    script = (
        f"import * as i from {json.dumps((STATIC / 'insets.js').as_uri())};\n"
        f"const specs = {json.dumps(specs)}, sources = {json.dumps(sources)};\n"
        "const out = sources.flatMap((source) => specs.map((spec) => "
        "({ placed: i.placed(spec, source), frame: i.piece(spec, 'frame'), "
        "connector: i.piece(spec, 'connector') })));\n"
        "console.log(JSON.stringify(out));\n"
    )
    theirs = iter(_node(script))
    for source in sources:
        for spec in specs:
            other = next(theirs)
            ours = insets.placed(spec, source)
            assert list(ours.box) == pytest.approx(other["placed"]["box"])
            assert list(ours.region) == pytest.approx(other["placed"]["region"])
            assert ours.scale == pytest.approx(other["placed"]["scale"])
            assert list(ours.offset) == pytest.approx(other["placed"]["offset"])
            assert [[list(a), list(b)] for a, b in ours.connectors] == other["placed"]["connectors"]
            assert insets.piece(spec, "frame") == other["frame"]
            assert insets.piece(spec, "connector") == other["connector"]


def test_the_studio_draws_masks_as_these_are() -> None:
    kept = (30, 40, 300, 200)
    shapes = [{"kind": kind} for kind in freeform.BOXED if masks.maskable(kind)] + [
        {
            "kind": "star",
            "tips": 7,
            "ratio": 0.6,
            "rotate": 25,
            "at": [0.1, 0.1],
            "size": [0.8, 0.7],
        },
        {"kind": "rounded-rectangle", "corner": 30, "flip": "horizontal"},
        {"kind": "bubble", "tail": [0.2, 1.4]},
        {"kind": "pen", "points": [[0, 0], [1, 0.2], [0.8, 1], [0.1, 0.7]], "closed": True},
        {"kind": "polyline", "points": [[0, 0], [1, 0.2], [0.8, 1]], "closed": True},
    ]
    script = (
        f"import * as m from {json.dumps((STATIC / 'masks.js').as_uri())};\n"
        f"const shapes = {json.dumps(shapes)}, kept = {json.dumps(kept)};\n"
        "console.log(JSON.stringify(shapes.map((mask) => m.outline(mask, kept))));\n"
    )
    for mask, other in zip(shapes, _node(script), strict=True):
        ours = masks.outline(mask, kept)
        assert len(ours) == len(other), mask
        for one, theirs in zip(ours, other, strict=True):
            assert one[0] == theirs[0], mask
            assert list(one[1:]) == pytest.approx(theirs[1:], abs=1e-6), mask


def test_a_shape_over_a_picture_masks_it_where_it_is() -> None:
    star = {
        "kind": "star",
        "at": [150, 80],
        "size": [120, 100],
        "rotate": 20,
        "tips": 6,
        "line": "accent2",
    }
    whole = (100, 50, 400, 300)
    script = (
        f"import * as m from {json.dumps((STATIC / 'masks.js').as_uri())};\n"
        f"console.log(JSON.stringify(m.fromShape({json.dumps(star)}, {json.dumps(whole)})));\n"
    )
    made = _node(script)
    assert "line" not in made["mask"] and made["mask"]["tips"] == 6
    crop = made["crop"]
    kept = (
        whole[0] + crop[0] * whole[2],
        whole[1] + crop[1] * whole[3],
        crop[2] * whole[2],
        crop[3] * whole[3],
    )
    # Masked, it is drawn where the shape was.
    ours = masks.outline(masks.checked(made["mask"]), kept)
    shape = freeform.geometry(star)
    turned = [
        freeform._turned(segment[1:3], shape.centre, shape.turn)
        for segment in shape.segments
        if segment[0] in ("M", "L")
    ]
    drawn = [segment[1:3] for segment in ours if segment[0] in ("M", "L")]
    for point, other in zip(drawn, turned, strict=True):
        assert math.dist(point, other) < 0.5
