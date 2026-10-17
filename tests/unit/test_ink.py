"""A figure's ink -- what ``flexo.fit_in_box`` sizes and centres it by -- is what it draws: each
curve as far as it goes, not as far as its control points; each line half its width beyond
that; nothing a clip cuts away. So a picture's drawing measures as a browser draws it, and a
photograph or a PDF's page as it did."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.drawing import Drawing, Group, curve_extent, ink_bounds, parse_path, read_drawing
from flexo.units import pt

SVG = "http://www.w3.org/2000/svg"


def test_a_curve_reaches_where_it_turns_not_its_control_points() -> None:
    # An arch whose controls stand 100 over its ends rises three quarters of that.
    assert curve_extent(parse_path("M0 0 C0 -100 100 -100 100 0")) == pytest.approx(
        (0, -75, 100, 0)
    )
    # A quadratic rises half as far as its control.
    assert curve_extent(parse_path("M0 0 Q50 -100 100 0")) == pytest.approx((0, -50, 100, 0))
    # A half circle, drawn as cubics, reaches its radius.
    half = curve_extent(parse_path("M0 0 A50 50 0 0 1 100 0"))
    assert half == pytest.approx((0, -50, 100, 0), abs=0.05)
    # An S lying on its side bulges each way by a little under a third of its controls' reach.
    assert curve_extent(parse_path("M0 0 C100 0 -100 100 0 100")) == pytest.approx(
        (-28.868, 0, 28.868, 100), abs=1e-3
    )
    # Relative and smooth curves, and a closed shape, alike.
    assert curve_extent(parse_path("m10 10 c0 -40 40 -40 40 0 s40 40 40 0 z")) == pytest.approx(
        (10, -20, 90, 40)
    )
    # Lines alone are their corners; nothing is nothing.
    assert curve_extent(parse_path("M5 5 L20 -3 H30 V40")) == (5, -3, 30, 40)
    assert curve_extent(()) is None


def test_a_line_reaches_half_its_width_beyond_its_curve() -> None:
    svg = (
        f'<svg xmlns="{SVG}" viewBox="0 0 200 200">'
        '<path d="M50 150 C50 50 150 50 150 150" fill="none" stroke="#000" stroke-width="4"/>'
        "</svg>"
    )
    assert ink_bounds(read_drawing(svg)) == pytest.approx((48, 73, 152, 152))


def test_what_a_clip_cuts_away_is_no_ink() -> None:
    svg = (
        f'<svg xmlns="{SVG}" viewBox="0 0 200 200">'
        '<clipPath id="c"><rect x="0" y="0" width="120" height="60"/></clipPath>'
        '<g clip-path="url(#c)">'
        '<path d="M10 100 C10 -20 180 -20 180 100" fill="#888"/>'
        '<text x="10" y="190" font-size="12">Cut off</text>'
        "</g>"
        '<circle cx="20" cy="20" r="5" fill="#000"/>'
        "</svg>"
    )
    # The curve, kept whole by the reader, shows only within the clip; the words not at all.
    assert ink_bounds(read_drawing(svg)) == pytest.approx((10, 10, 120, 60))


# -- pictures in a figure ----------------------------------------------------------------------

_ARCH = (
    f'<svg xmlns="{SVG}" viewBox="0 0 100 100" width="100" height="100">'
    # Its top (stroke and all) just meets the viewBox's, its controls 32 above it.
    '<path d="M10 99 C10 -31.6667 90 -31.6667 90 99 Z" fill="#d7f2d8" stroke="#246c2d" '
    'stroke-width="2"/>'
    "</svg>"
)


def _placed(source: Path) -> tuple[tuple[float, float, float, float], tuple[float, ...]]:
    """The box a picture is drawn in, in a figure of it alone, and the figure's ink."""

    with Figure("picture", width=pt(400.0), background=False) as figure:
        figure.root.image("art", source, height="100pt")
    svg = compile_figure(figure.spec).document.text
    art = next(item for item in ET.fromstring(svg).iter() if item.get("id") == "art.artwork")
    box = tuple(float(art.get(name, "0")) for name in ("x", "y", "width", "height"))
    return box, ink_bounds(read_drawing(svg))  # type: ignore[return-value]


def test_a_drawing_s_ink_is_its_drawn_extent_in_its_box(tmp_path: Path) -> None:
    source = tmp_path / "arch.svg"
    source.write_text(_ARCH, encoding="utf-8")
    (x, y, _, height), (left, top, right, bottom) = _placed(source)
    scale = height / 100.0
    # Top and bottom are the box's, as the drawing fills it; across, its curve's edges and the
    # half of its line beyond them -- not the controls 32 over the box's top.
    assert (top, bottom) == pytest.approx((y, y + height), abs=1e-3)
    assert (left, right) == pytest.approx((x + 9 * scale, x + 91 * scale), abs=1e-3)


def test_a_photograph_s_ink_is_its_box(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    for name, kind in (("photo.png", "PNG"), ("spin.gif", "GIF")):
        out = io.BytesIO()
        image.new("RGB", (40, 20), (200, 90, 40)).save(out, kind)
        source = tmp_path / name
        source.write_bytes(out.getvalue())
        (x, y, width, height), ink = _placed(source)
        assert ink == pytest.approx((x, y, x + width, y + height)), name
        assert (width, height) == pytest.approx((200, 100)), name


def test_a_pdf_page_s_ink_is_what_is_drawn_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pypdfium2")
    from flexo import pdfart
    from flexo.pdf import write_pdf

    monkeypatch.setattr(pdfart, "_cache_folder", lambda: tmp_path / "pages")  # (not the user's)

    page = (
        f'<svg xmlns="{SVG}" viewBox="0 0 200 100" width="200pt" height="100pt">'
        '<rect x="50" y="20" width="100" height="60" fill="#3f7fc0"/>'
        "</svg>"
    )
    source = write_pdf(page, tmp_path / "art.pdf")
    (x, y, _, height), ink = _placed(source)
    scale = height / 100.0
    assert ink == pytest.approx(
        (x + 50 * scale, y + 20 * scale, x + 150 * scale, y + 80 * scale), abs=0.05
    )


def test_ink_is_found_for_one_part_as_for_a_whole() -> None:
    svg = (
        f'<svg xmlns="{SVG}" viewBox="0 0 200 200">'
        '<g id="one"><path d="M0 100 C0 0 100 0 100 100" fill="#888"/></g>'
        '<g id="two"><rect x="150" y="150" width="20" height="20" fill="#000"/></g>'
        "</svg>"
    )
    drawing = read_drawing(svg)
    one, two = drawing.root.items
    assert ink_bounds(Drawing(0.0, 0.0, Group(None, [one]))) == pytest.approx((0, 25, 100, 100))
    assert ink_bounds(Drawing(0.0, 0.0, Group(None, [two]))) == (150, 150, 170, 170)
    assert ink_bounds(drawing) == pytest.approx((0, 25, 170, 170))
