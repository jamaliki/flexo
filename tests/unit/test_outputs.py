"""Outputs, all written in Python: the notebook display, portable SVG, PDF, and PNG."""

from __future__ import annotations

import re
import zlib
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


def _png(width: int, height: int, colour_type: int, rows: bytes) -> bytes:
    """A PNG of 8-bit ``rows`` (each led by its filter byte), written by hand."""

    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        check = struct.pack(">I", zlib.crc32(tag + payload))
        return struct.pack(">I", len(payload)) + tag + payload + check

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


def test_pdf_parts_a_pictures_colour_from_its_alpha_pixel_for_pixel() -> None:
    import re
    import zlib

    from flexo.pdf import _image_object, _Writer

    pixels = [(index, 2 * index, 3 * index, 255 - index) for index in range(12)]
    flat = bytes(value for pixel in pixels for value in pixel)
    rows = b"".join(b"\x00" + flat[at : at + 16] for at in (0, 16, 32))
    writer = _Writer("t")
    _image_object(writer, "image/png", _png(4, 3, 6, rows))
    streams = [re.search(rb"stream\n(.*)\nendstream", body, re.S) for body in writer.objects[1:]]
    mask, colour = (zlib.decompress(found.group(1)) for found in streams if found)
    assert mask == bytes(alpha for *_, alpha in pixels)
    assert colour == bytes(value for *rgb, _ in pixels for value in rgb)


def test_a_picture_much_enlarged_shows_its_pixels_in_the_png_as_in_the_pdf() -> None:
    import base64

    from flexo.export import _pixels_shown, rasterise
    from flexo.pdf import _png_decode

    def page(width: int, height: int) -> str:
        """A grey picture, black at its left half and white at its right, filling the page."""

        row = b"\x00" + bytes(0 if x < width // 2 else 255 for x in range(width))
        data = _png(width, height, 0, row * height)
        href = "data:image/png;base64," + base64.b64encode(data).decode()
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="200pt" height="100pt" '
                f'viewBox="0 0 200 100"><image width="200" height="100" preserveAspectRatio="none" '
                f'href="{href}"/></svg>')

    width, _, channels, pixels = _png_decode(rasterise(page(2, 1), dpi=72))
    middle = pixels[50 * width * channels : 51 * width * channels : channels]
    assert middle[95] == 0 and middle[104] == 255  # two crisp pixels, not a ramp between them
    # A picture drawn smaller than its pixels is smoothed, as before.
    assert "image-rendering" not in _pixels_shown(page(400, 200), 72)


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


def test_pdf_rasterises_svg_artwork_sized_in_points(tmp_path: Path) -> None:
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    source = tmp_path / "art.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="60pt" height="40pt" viewBox="0 0 60 40">'
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#000"/>'
        '<stop offset="1" stop-color="#fff"/></linearGradient></defs>'
        '<rect width="60" height="40" fill="url(#g)"/></svg>'
    )
    with Figure("art") as figure:
        figure.root.image("art", source)
    data = pdf_bytes(compile_figure(figure.spec).document.text)
    assert b"/Subtype /Image" in data


def test_links_are_clickable_in_every_format(tmp_path: Path) -> None:
    from flexo.markup import parse_label

    runs = parse_label("See [the paper](https://arxiv.org/abs/1706.03762) now")
    assert [run.link for run in runs] == ["", "https://arxiv.org/abs/1706.03762", ""]
    with Figure("linked") as figure:
        figure.block("b", label="See [the paper](https://arxiv.org/abs/1706.03762)")
    outputs = flexo.build(figure, tmp_path, formats=("editable", "portable", "pdf")).outputs
    editable = outputs.editable_svg.read_text()
    assert '<a href="https://arxiv.org/abs/1706.03762">' in editable
    portable = outputs.portable_svg.read_text()  # type: ignore[union-attr]
    assert 'href="https://arxiv.org/abs/1706.03762"' in portable
    pdf = outputs.pdf.read_bytes()  # type: ignore[union-attr]
    assert b"/Subtype /Link" in pdf and b"/URI (https://arxiv.org/abs/1706.03762)" in pdf
    # A link is underlined in every format, as the slide's PowerPoint export underlines it.
    assert 'text-decoration="underline"' in editable
    link = portable[portable.index("<a href") : portable.index("</a>")]
    assert re.search(r'<rect [^>]*height="0\.5" fill="#1a5d9b"', link)
    assert any(re.search(rb"\d re f", stream) for stream in _streams(pdf))


def _streams(pdf: bytes) -> list[bytes]:
    found = re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S)
    return [zlib.decompress(body) for body in found if body[:1] == b"x"]


def test_a_pdf_keeps_the_space_where_a_line_wraps_so_words_copy_apart() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    def spaces_and_wraps(label: str) -> tuple[int, int]:
        with Figure("wrapped") as figure:
            figure.root.block("b", label=label, width=80)
        pdf = pdf_bytes(compile_figure(figure.spec).document.text)
        wraps = pdfium.PdfDocument(pdf)[0].get_textpage().get_text_range().count("\r\n")
        return sum(stream.count(b" 3 Tr ") for stream in _streams(pdf)), wraps

    # Each soft wrap is given back its space, laid invisibly at the end of the line.
    assert spaces_and_wraps("Hexamers") == (0, 0)
    spaces, wraps = spaces_and_wraps("Capsid hexamers assemble across a two-fold axis to build")
    assert wraps >= 2 and spaces == wraps


def test_maths_in_words_and_a_drawn_formula_read_alike_in_a_pdf() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    with Figure("read") as figure:
        figure.root.block("a", label=r"$k_{\text{auto}} p$, $k_B p$, $x^2$ and $T \approx 24$")
        figure.root.block("b", label=r"$\frac{dp}{dt} = k_{\text{auto}} p - k_B p + x^2$")
    pdf = pdf_bytes(compile_figure(figure.spec).document.text)
    said = " ".join(pdfium.PdfDocument(pdf)[0].get_textpage().get_text_range().split())
    # Scripts set among words read as a formula's do: digits raised, words after a mark, kept
    # apart from a letter after them; and an italic letter's lean is no second space.
    assert "k_auto p, k_B p, x² and T ≈ 24" in said
    assert "dp/dt = k_auto p \u2212 k_B p + x²" in said


def test_words_after_invisible_ones_on_a_pdf_page_are_still_drawn() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    # A wrapped label (its spaces laid invisibly), a formula (its words laid invisibly), then words.
    with Figure("hidden") as figure:
        figure.root.block("a", label="Capsid hexamers assemble across a two-fold axis", width=80)
        figure.root.block("m", label=r"$\frac{a}{b}$")
        figure.root.block("z", label="Zebra")
    pdf = pdf_bytes(compile_figure(figure.spec).document.text)
    content = b"".join(_streams(pdf)).decode("latin-1")
    # The render mode and scaling are graphics state, kept past ET: walk them as a reader does.
    stack: list[tuple[int, float]] = []
    mode, scale, shown = 0, 100.0, []
    for token in re.findall(r"[\d.]+ Tr|[\d.]+ Tz|(?<![\w/])(?:q|Q|TJ|Tj)(?!\w)", content):
        if token == "q":
            stack.append((mode, scale))
        elif token == "Q":
            mode, scale = stack.pop()
        elif token.endswith("Tr"):
            mode = int(token.split()[0])
        elif token.endswith("Tz"):
            scale = float(token.split()[0])
        else:
            shown.append((mode, scale))
    objects = re.findall(r"\bBT\s(.*?)\sET\b", content, re.S)
    hidden = sum(len(re.findall(r"T[Jj]\b", body)) for body in objects if body.startswith("3 Tr"))
    assert hidden >= 3 and sum(1 for state in shown if state[0] == 3) == hidden
    assert all(state == (0, 100.0) for state in shown if state[0] != 3)
    # And it is ink where the last word is, as both a reader and a printer draw it.
    page = pdfium.PdfDocument(pdf)[0]
    text = page.get_textpage()
    at = text.get_text_range().index("Zebra")
    left, bottom, right, top = text.get_charbox(at)
    height = page.get_height()
    picture = page.render(scale=2).to_pil().convert("L")
    letter = picture.crop(
        (int(left * 2), int((height - top) * 2), int(right * 2) + 1, int((height - bottom) * 2) + 1)
    )
    assert min(letter.getextrema()) < 128


def test_a_drawn_formula_is_found_in_a_pdf_as_the_words_it_reads_as() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    from flexo.compiler import compile_figure
    from flexo.pdf import pdf_bytes

    with Figure("ratio") as figure:
        figure.root.block("b", label=r"$\frac{a+b}{2}$")
    document = pdfium.PdfDocument(pdf_bytes(compile_figure(figure.spec).document.text))
    # Drawn as outlines, it reads, is found and is copied as its words, laid invisibly under it.
    assert "(a + b)/2" in document[0].get_textpage().get_text_range()


def test_a_tagged_pdf_has_headings_described_figures_and_decoration_passed_over() -> None:
    import re
    import zlib

    pdfium = pytest.importorskip("pypdfium2")
    from flexo.drawing import Group, Shape, Text
    from flexo.pdf import ARTIFACT, Tag, pdf_bytes

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<rect id="band" width="200" height="30" fill="#683476"/>'
        '<text id="s.title" x="10" y="20" font-family="Figtree" font-size="12">A heading</text>'
        '<g id="s.figure">'
        '<rect id="s.figure.box" x="10" y="40" width="40" height="20" fill="#eee"/>'
        '<text id="s.figure.label" x="12" y="54" font-family="Figtree" font-size="8">Box</text></g>'
        '<text id="s.words" x="10" y="90" font-family="Figtree" font-size="10">Some words</text>'
        "</svg>"
    )

    def tag(item: object, within: Tag | None) -> Tag | None:
        if isinstance(item, Group) and item.id == "s.figure":
            return Tag((("Figure", "s.figure"),), alt="A box")
        if isinstance(item, Text) and item.id == "s.title":
            return Tag((("H1", "s.title"),))
        return ARTIFACT if isinstance(item, Shape) and within is None else None

    data = pdf_bytes(svg, title="Tagged", tags=tag, language="en-GB")
    assert b"/MarkInfo << /Marked true >>" in data and b"/StructTreeRoot" in data
    assert b"/Lang (en-GB)" in data and b"/StructParents 0" in data
    kinds = re.findall(rb"/Type /StructElem /S /(\w+)", data)
    assert kinds == [b"Document", b"Sect", b"H1", b"Figure", b"P"]
    assert b"/S /Figure" in data and b"/Alt (A box)" in data
    def streams(pdf: bytes) -> list[bytes]:
        found = re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S)
        return [zlib.decompress(body) for body in found if body[:1] == b"x"]

    content = next(stream for stream in streams(data) if b"BDC" in stream)
    # The band is decoration; the heading, the figure (box and label) and the words are marked.
    assert content.count(b"/Artifact BMC") == 1 and content.count(b" BDC") == 4
    assert pdfium.PdfDocument(data)[0].get_textpage().get_text_range().startswith("A heading")
    # Untagged, as a figure's own PDF is: nothing of the sort.
    untagged = pdf_bytes(svg)
    assert b"/StructTreeRoot" not in untagged and b"BDC" not in b"".join(streams(untagged))
