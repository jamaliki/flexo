"""Outputs, all written in Python: the notebook display, portable SVG, PDF, and PNG."""

from __future__ import annotations

from pathlib import Path

import pytest

import flexo
from flexo.builder import Figure


def _figure() -> Figure:
    with Figure("small") as figure, figure.module("m", label="Small") as m:
        m.block("b", label="$x_t$", input=m.text("a", "A"))
    return figure


def test_a_figure_displays_itself_in_a_notebook() -> None:
    svg = _figure()._repr_svg_()
    assert svg.lstrip().startswith("<?xml") and "<svg" in svg


def test_every_format_is_written_natively(tmp_path: Path) -> None:
    result = flexo.build(_figure().spec, tmp_path, dpi=96)
    outputs = result.outputs
    assert outputs.png is not None and outputs.png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert outputs.pdf is not None
    pdf = outputs.pdf.read_bytes()
    assert pdf.startswith(b"%PDF-1.7") and pdf.rstrip().endswith(b"%%EOF")
    # Words stay text in embedded TrueType subsets that map back to Unicode.
    assert b"/CIDFontType2" in pdf and b"/FontFile2" in pdf and b"/ToUnicode" in pdf
    assert outputs.portable_svg is not None
    portable = outputs.portable_svg.read_text()
    assert "<text" not in portable and 'aria-label="A"' in portable
    assert 'id="m.b.body"' in portable and 'inkscape:label="' in portable


def test_pdf_text_is_found_where_it_was_drawn() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    document = pdfium.PdfDocument(pdf_bytes(compile_figure(_figure().spec).document.text))
    text = document[0].get_textpage().get_text_range()
    assert "Small" in text and "A" in text


def test_a_pdf_takes_several_pages_and_shares_fonts() -> None:
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    page = compile_figure(_figure().spec).document.text
    data = pdf_bytes([page, page, page])
    assert data.count(b"/Type /Page ") == 3
    assert data.count(b"/FontFile2") == pdf_bytes(page).count(b"/FontFile2")


def test_pdf_embeds_png_artwork_with_its_alpha(tmp_path: Path) -> None:
    import struct
    import zlib

    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    def chunk(tag: bytes, payload: bytes) -> bytes:
        check = struct.pack(">I", zlib.crc32(tag + payload))
        return struct.pack(">I", len(payload)) + tag + payload + check

    rows = b"".join(b"\x00" + bytes([200, 40, 40, 128] * 6) for _ in range(3))
    source = tmp_path / "art.png"
    source.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 6, 3, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    with Figure("art") as figure:
        figure.root.image("art", source)
    data = pdf_bytes(compile_figure(figure.spec).document.text)
    assert b"/Subtype /Image /Width 6 /Height 3 /ColorSpace /DeviceRGB" in data
    assert b"/SMask" in data


def test_the_same_figure_compiles_to_the_same_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Embedded font subsets must not carry the time they were made."""

    import time

    from flexo.compiler import compile_figure

    first = compile_figure(_figure().spec).document.text
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 86_400.0)
    assert compile_figure(_figure().spec).document.text == first


def test_a_script_no_bundled_font_has_is_set_in_one_installed_font() -> None:
    """Characters outside every bundled font come from an installed font that has them all."""

    import re

    from flexo.compiler import compile_figure
    from flexo.fonts import family_covering

    word = "编码器"
    if family_covering(word) is None:
        pytest.skip("no installed font covers CJK")
    with Figure("cjk") as figure, figure.module("m", label=word) as m:
        m.block("b", label="注意力")
    compilation = compile_figure(figure.spec)
    families = {
        text: family
        for family, text in re.findall(
            r'<tspan font-family="([^"]+)">([^<]*)<', compilation.document.text
        )
    }
    assert word in families and "注意力" in families


def test_a_figure_is_transparent_unless_it_asks_for_a_page() -> None:
    """The page is left unpainted by default; ``background`` paints it."""

    import re

    import yaml

    from flexo.builder import Figure
    from flexo.compiler import compile_figure
    from flexo.serialization import dump_figure, parse_figure

    def page(**options: object) -> str:
        with Figure("page", theme="archive", **options) as figure:
            figure.root.block("a", label="A")
        text = compile_figure(figure.spec).document.text
        return re.search(r'<rect id="canvas\.background"[^>]*>', text).group(0)  # type: ignore[union-attr]

    assert 'fill="none"' in page() and "data-flexo-fill" not in page()
    assert 'data-flexo-fill="canvas"' in page(background=True)
    assert 'fill="#fdfaf2"' not in page() and 'fill="#123456"' in page(background="#123456")
    with Figure("page", background=True) as figure:
        figure.root.block("a", label="A")
    assert parse_figure(yaml.safe_load(dump_figure(figure.spec))).background is True
