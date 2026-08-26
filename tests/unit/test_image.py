from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest
import yaml

from flexo.artwork import load_artwork
from flexo.builder import Figure
from flexo.compiler import Compilation, compile_figure
from flexo.components import label_band_height, motif_area
from flexo.diagnostics import FlexoError
from flexo.geometry import Point, Side
from flexo.serialization import dump_figure, parse_figure
from flexo.style import PALETTES, STYLES
from flexo.svg import SVG_NS
from flexo.theme import retheme_svg
from flexo.units import pt

_ARTWORK = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- a molecule the author drew -->
<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90" viewBox="0 0 120 90">
  <defs>
    <linearGradient id="sheen"><stop offset="0" stop-color="#54606e"/></linearGradient>
  </defs>
  <g id="bonds" stroke="url(#sheen)"><path d="M 30 62 L 60 40"/></g>
  <circle id="carbon" cx="60" cy="40" r="14" fill="#2b3440"/>
</svg>
"""


def write_artwork(directory: Path, body: str = _ARTWORK, name: str = "molecule.svg") -> Path:
    target_file = directory / name
    target_file.write_text(body, encoding="utf-8")
    return target_file


def write_png(directory: Path, width: int = 8, height: int = 4) -> Path:
    """A real, minimal RGB PNG, so the loader reads a real IHDR."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    rows = b"".join(b"\x00" + bytes([255, 90, 40] * width) for _ in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    target_file = directory / "render.png"
    target_file.write_bytes(data)
    return target_file


def compiled(source: Path, **options: object) -> Compilation:
    with Figure("artwork", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("panel") as panel:
            art = panel.image("art", source, **options)
            following = panel.block("next", label="Next")
            panel.connect(art.output, following.input)
    return compile_figure(figure.spec)


def artwork_element(compilation: Compilation, node_id: str = "panel.art.artwork") -> ET.Element:
    root = ET.fromstring(compilation.document.text)
    found = [item for item in root.iter() if item.get("id") == node_id]
    assert len(found) == 1
    return found[0]


def test_image_lowers_to_a_node_carrying_its_source(tmp_path: Path) -> None:
    source = write_artwork(tmp_path)
    with Figure("artwork", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("panel") as panel:
            handle = panel.image("art", source)
    node = figure.spec.node("panel.art")
    assert node.kind == "image"
    assert node.property("source") == str(source)
    assert handle.ports == ("input", "output", "north", "south")


def test_image_ports_are_the_four_side_centres(tmp_path: Path) -> None:
    node = compiled(write_artwork(tmp_path)).fitted.node("panel.art")
    bounds = node.bounds
    assert {port.name: (port.side, port.position) for port in node.ports} == {
        "input": (Side.WEST, Point(bounds.left, bounds.center.y)),
        "output": (Side.EAST, Point(bounds.right, bounds.center.y)),
        "north": (Side.NORTH, Point(bounds.center.x, bounds.top)),
        "south": (Side.SOUTH, Point(bounds.center.x, bounds.bottom)),
    }


def test_image_without_author_size_takes_the_artwork_size(tmp_path: Path) -> None:
    """A 120x90 px drawing is 90x67.5 pt, because SVG user units are CSS pixels."""

    bounds = compiled(write_artwork(tmp_path)).fitted.node("panel.art").bounds
    assert bounds.width == pytest.approx(90.0)
    assert bounds.height == pytest.approx(67.5)


def test_one_author_extent_scales_the_other_by_the_artwork_aspect(tmp_path: Path) -> None:
    source = write_artwork(tmp_path)
    wide = compiled(source, width="96pt").fitted.node("panel.art").bounds
    assert (wide.width, wide.height) == pytest.approx((96.0, 72.0))
    tall = compiled(source, height="45pt").fitted.node("panel.art").bounds
    assert (tall.width, tall.height) == pytest.approx((60.0, 45.0))


def test_both_extents_box_the_artwork_and_letterbox_it(tmp_path: Path) -> None:
    compilation = compiled(write_artwork(tmp_path), width="100pt", height="100pt")
    bounds = compilation.fitted.node("panel.art").bounds
    assert (bounds.width, bounds.height) == pytest.approx((100.0, 100.0))
    assert artwork_element(compilation).get("preserveAspectRatio") == "xMidYMid meet"


def test_a_cell_span_sizes_an_image_like_any_other_node(tmp_path: Path) -> None:
    from flexo.style import STYLES, vector_stack_height

    compilation = compiled(write_artwork(tmp_path), height="cells:3")
    bounds = compilation.fitted.node("panel.art").bounds
    assert bounds.height == pytest.approx(vector_stack_height(STYLES["paper"], 3).points)


def test_an_unsized_artwork_needs_an_author_size(tmp_path: Path) -> None:
    body = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
    source = write_artwork(tmp_path, body)
    with pytest.raises(FlexoError, match=r"image\.size\.unknown"):
        compiled(source)
    boxed = compiled(source, width="40pt", height="30pt").fitted.node("panel.art").bounds
    assert (boxed.width, boxed.height) == pytest.approx((40.0, 30.0))


def test_svg_artwork_is_inlined_as_nested_vector_content(tmp_path: Path) -> None:
    """R: crisp means real vector content at the node's bounds, not a raster."""

    compilation = compiled(write_artwork(tmp_path), width="96pt")
    nested = artwork_element(compilation)
    bounds = compilation.fitted.node("panel.art").bounds
    assert nested.tag == f"{{{SVG_NS}}}svg"
    assert nested.get("viewBox") == "0 0 120 90"
    assert float(nested.get("x", "")) == pytest.approx(bounds.x)
    assert float(nested.get("y", "")) == pytest.approx(bounds.y)
    assert float(nested.get("width", "")) == pytest.approx(96.0)
    assert float(nested.get("height", "")) == pytest.approx(72.0)
    assert [item.get("id") for item in nested.iter(f"{{{SVG_NS}}}circle")] == ["panel.art.carbon"]


def test_embedded_ids_are_prefixed_so_two_copies_never_share_a_gradient(
    tmp_path: Path,
) -> None:
    source = write_artwork(tmp_path)
    with Figure("artwork", width=pt(360.0)) as figure:  # noqa: SIM117
        with figure.module("panel") as panel:
            panel.image("left", source, width="72pt")
            panel.image("right", source, width="72pt")
    text = compile_figure(figure.spec).document.text
    root = ET.fromstring(text)
    ids = {item.get("id") for item in root.iter() if item.get("id")}
    assert {"panel.left.sheen", "panel.right.sheen"} <= ids
    assert "sheen" not in ids
    references = {
        item.get("stroke") for item in root.iter() if (item.get("stroke") or "").startswith("url")
    }
    assert references == {"url(#panel.left.sheen)", "url(#panel.right.sheen)"}


def test_the_xml_declaration_doctype_and_comments_do_not_travel(tmp_path: Path) -> None:
    text = compiled(write_artwork(tmp_path)).document.text
    assert text.count("<?xml") == 1
    assert "DOCTYPE" not in text
    assert "a molecule the author drew" not in text


def test_png_artwork_becomes_a_self_contained_data_uri(tmp_path: Path) -> None:
    compilation = compiled(write_png(tmp_path), width="48pt")
    image = artwork_element(compilation)
    bounds = compilation.fitted.node("panel.art").bounds
    assert image.tag == f"{{{SVG_NS}}}image"
    assert (image.get("href") or "").startswith("data:image/png;base64,")
    # 8x4 px at 96 dpi is 6x3 pt, so 48 pt wide is 24 pt tall.
    assert (bounds.width, bounds.height) == pytest.approx((48.0, 24.0))
    assert float(image.get("width", "")) == pytest.approx(48.0)
    assert float(image.get("height", "")) == pytest.approx(24.0)


def test_png_artwork_takes_its_pixel_size_at_96_dpi(tmp_path: Path) -> None:
    bounds = compiled(write_png(tmp_path)).fitted.node("panel.art").bounds
    assert (bounds.width, bounds.height) == pytest.approx((6.0, 3.0))


def test_artwork_carries_no_palette_role_and_survives_retheme(tmp_path: Path) -> None:
    """R: author art is author paint, exactly as preset vector cells are."""

    compilation = compiled(write_artwork(tmp_path))
    nested = artwork_element(compilation)
    assert not [
        name
        for item in nested.iter()
        for name in item.attrib
        if name.startswith("data-flexo-")
    ]
    themed = ET.fromstring(retheme_svg(compilation.document.text, PALETTES["grayscale"]))
    carbon = next(item for item in themed.iter() if item.get("id") == "panel.art.carbon")
    assert carbon.get("fill") == "#2b3440"
    body = next(item for item in themed.iter() if item.get("id") == "panel.next.body")
    assert body.get("fill") != next(
        item for item in ET.fromstring(compilation.document.text).iter()
        if item.get("id") == "panel.next.body"
    ).get("fill")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<script>alert(1)</script></svg>',
            "image.svg.script",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<circle r="4" onload="alert(1)"/></svg>',
            "image.svg.event-handler",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<image href="https://example.invalid/logo.png"/></svg>',
            "image.svg.external-reference",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<image href="../secrets/logo.png"/></svg>',
            "image.svg.external-reference",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 8 8"><use xlink:href="http://example.invalid/#a"/></svg>',
            "image.svg.external-reference",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<circle r="4" fill="url(https://example.invalid/p.svg#a)"/></svg>',
            "image.svg.external-reference",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            "<style>@import url(https://example.invalid/a.css);</style></svg>",
            "image.svg.external-reference",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle r="4"',
            "image.svg.invalid",
        ),
    ],
)
def test_the_sanitizer_rejects_artwork_that_does_more_than_draw(
    tmp_path: Path,
    body: str,
    code: str,
) -> None:
    source = write_artwork(tmp_path, body)
    with pytest.raises(FlexoError, match=code.replace(".", r"\.")) as raised:
        compiled(source)
    assert raised.value.diagnostics[0].entity_id == "panel.art"
    assert str(source) in raised.value.diagnostics[0].message


def test_internal_fragment_references_are_fine(tmp_path: Path) -> None:
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 8 8"><defs><circle id="dot" r="2"/></defs>'
        '<use xlink:href="#dot" x="4" y="4"/></svg>'
    )
    compilation = compiled(write_artwork(tmp_path, body), width="24pt")
    nested = artwork_element(compilation)
    use = next(item for item in nested.iter() if item.tag.endswith("use"))
    assert use.get("{http://www.w3.org/1999/xlink}href") == "#panel.art.dot"


def test_a_missing_or_unsupported_source_names_the_node_and_the_path(tmp_path: Path) -> None:
    absent = tmp_path / "absent.svg"
    with pytest.raises(FlexoError, match=r"image\.source\.unreadable") as missing:
        compiled(absent)
    assert missing.value.diagnostics[0].entity_id == "panel.art"
    assert str(absent) in missing.value.diagnostics[0].message

    other = tmp_path / "artwork.eps"
    other.write_text("not artwork", encoding="utf-8")
    with pytest.raises(FlexoError, match=r"image\.source\.unsupported") as unsupported:
        compiled(other)
    assert str(other) in unsupported.value.diagnostics[0].message


def test_a_png_that_is_not_a_png_is_rejected(tmp_path: Path) -> None:
    target_file = tmp_path / "render.png"
    target_file.write_bytes(b"GIF89a not really")
    with pytest.raises(FlexoError, match=r"image\.png\.invalid"):
        load_artwork("panel.art", str(target_file))


def test_an_image_node_round_trips_through_the_schema_document(tmp_path: Path) -> None:
    source = write_artwork(tmp_path)
    with Figure("artwork", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("panel") as panel:
            panel.image("art", source, width="96pt", label="Ligand")
    original = figure.spec
    parsed = parse_figure(yaml.safe_load(dump_figure(original)))
    assert parsed == original
    assert parsed.node("panel.art").property("source") == str(source)


def test_an_image_is_a_solid_obstacle_for_routing(tmp_path: Path) -> None:
    """Nothing special: an image has bounds and no transparency exemption."""

    from flexo.components import TRANSPARENT_KINDS

    assert "image" not in TRANSPARENT_KINDS
    compilation = compiled(write_artwork(tmp_path), width="60pt")
    bounds = compilation.fitted.node("panel.art").bounds
    route = compilation.routed.edges[0].centerline
    assert all(not bounds.contains_point(point, strict=True) for point in route)


def test_a_label_takes_a_band_off_the_top_and_the_artwork_takes_the_rest(
    tmp_path: Path,
) -> None:
    """R27: an image captions like an inset, never across its own drawing."""

    compilation = compiled(write_artwork(tmp_path), width="96pt", label="Ligand")
    node = compilation.fitted.node("panel.art")
    style = STYLES["paper"]
    band = label_band_height("image", node.measured.label, style)
    area = motif_area(node.measured.spec, node.bounds, node.measured.label, style)
    root = ET.fromstring(compilation.document.text)
    label = next(item for item in root.iter() if item.get("id") == "panel.art.label")
    assert "".join(item.text or "" for item in label.iter()).strip() == "Ligand"
    assert float(label.get("x", "")) == pytest.approx(node.bounds.center.x)
    baseline = float(label.get("y", ""))
    assert baseline == pytest.approx(
        node.bounds.y + style.padding_y.points + node.measured.label.baseline
    )
    artwork = artwork_element(compilation)
    assert float(artwork.get("y", "")) == pytest.approx(area.y)
    assert area.y >= node.bounds.y + band, "the drawing starts below the words"
    assert float(artwork.get("height", "")) == pytest.approx(area.height)
    assert float(artwork.get("width", "")) == pytest.approx(area.width)
    # The band is reserved rather than taken from the drawing: an unlabelled
    # image of the same authored width keeps its whole aspect-ratio height.
    plain = compiled(write_artwork(tmp_path), width="96pt").fitted.node("panel.art")
    assert node.bounds.height > plain.bounds.height


def test_a_height_only_extent_shrinks_the_artwork_and_not_the_label(
    tmp_path: Path,
) -> None:
    """The author chose the box; the caption's line is the one size they did not."""

    style = STYLES["paper"]
    roomy = compiled(write_artwork(tmp_path), height="80pt", label="Ligand")
    tight = compiled(write_artwork(tmp_path), height="50pt", label="Ligand")
    for compilation in (roomy, tight):
        node = compilation.fitted.node("panel.art")
        area = motif_area(node.measured.spec, node.bounds, node.measured.label, style)
        assert node.bounds.height == pytest.approx(
            80.0 if compilation is roomy else 50.0
        )
        assert float(artwork_element(compilation).get("height", "")) == pytest.approx(
            area.height
        )
    roomy_label = roomy.fitted.node("panel.art").measured.label
    tight_label = tight.fitted.node("panel.art").measured.label
    assert roomy_label.height == tight_label.height, "the words keep their line"
    assert (
        motif_area(
            tight.fitted.node("panel.art").measured.spec,
            tight.fitted.node("panel.art").bounds,
            tight_label,
            style,
        ).height
        < motif_area(
            roomy.fitted.node("panel.art").measured.spec,
            roomy.fitted.node("panel.art").bounds,
            roomy_label,
            style,
        ).height
    )


def test_an_unlabelled_image_reserves_no_band_at_all(tmp_path: Path) -> None:
    """The whole promise of the kind: the bounds are the artwork."""

    compilation = compiled(write_artwork(tmp_path))
    bounds = compilation.fitted.node("panel.art").bounds
    artwork = artwork_element(compilation)
    assert (float(artwork.get("x", "")), float(artwork.get("y", ""))) == pytest.approx(
        (bounds.x, bounds.y)
    )
    assert (
        float(artwork.get("width", "")),
        float(artwork.get("height", "")),
    ) == pytest.approx((bounds.width, bounds.height))
