"""A PDF's page and an Illustrator file's artboard, read back as the drawing they are:
shapes and words as vectors, what SVG cannot say as pictures in place -- and checked."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")

from flexo import pdfart
from flexo.artwork import load_artwork
from flexo.diagnostics import FlexoError
from flexo.pdf import write_pdf

SVG = "{http://www.w3.org/2000/svg}"


def _pdf(
    content: str,
    *,
    resources: str = "",
    objects: tuple[str, ...] = (),
    box: str = "0 0 200 100",
    page: str = "",
    catalog: str = "",
) -> bytes:
    """A one-page PDF drawing ``content``; ``objects`` are numbered from 5 on."""

    stream = content.encode("latin-1")
    bodies = [
        f"<< /Type /Catalog /Pages 2 0 R {catalog} >>".encode(),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] {page} /Resources << {resources} >> "
        "/Contents 4 0 R >>".encode(),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        *(body.encode("latin-1") for body in objects),
    ]
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(bodies) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def _form(content: str, *, resources: str = "", box: str = "0 0 200 100") -> str:
    """A transparency group (a form XObject), as Illustrator writes a group with an opacity."""

    return (
        f"<< /Type /XObject /Subtype /Form /BBox [{box}] /Group << /S /Transparency >> "
        f"/Resources << {resources} >> /Length {len(content)} >>\nstream\n{content}\nendstream"
    )


def _read(tmp_path: Path, data: bytes, name: str = "art.pdf", **options) -> pdfart.PageArt:
    target = tmp_path / name
    target.write_bytes(data)
    return pdfart._read(str(target), 1, target.stat().st_mtime_ns, **options)


def _shapes(art: pdfart.PageArt) -> list[ET.Element]:
    return [item for item in ET.fromstring(art.markup).iter() if item.tag == f"{SVG}path"]


def _pictures(art: pdfart.PageArt) -> list[ET.Element]:
    return [item for item in ET.fromstring(art.markup).iter() if item.tag == f"{SVG}image"]


def test_shapes_keep_their_geometry_and_paint(tmp_path: Path) -> None:
    content = (
        "1 0 0 rg 20 10 60 30 re f\n"  # a red box, 20..80 across, 10..40 up
        "0 0 1 RG 2 w 1 J [6 3] 0 d 100 50 m 180 90 l S\n"  # a dashed blue line, round ends
        "0 g 110 10 m 190 10 l 190 40 l 110 40 l h 130 18 m 170 18 l 170 32 l 130 32 l h f*\n"
    )
    art = _read(tmp_path, _pdf(content))

    assert (art.width, art.height, art.whole, art.pictured) == (200, 100, False, 0)
    box, line, frame = _shapes(art)
    assert box.get("fill") == "#ff0000"
    # y runs down from the page's top: the box's top edge, 40 up, is 60 down.
    assert re.match(r"M20 90L80 90L80 60L20 60", box.get("d", "").replace("Z", ""))
    assert line.get("fill") == "none" and line.get("stroke") == "#0000ff"
    assert (line.get("stroke-width"), line.get("stroke-linecap")) == ("2", "round")
    assert line.get("stroke-dasharray") == "6 3"
    assert frame.get("fill-rule") == "evenodd"  # a frame with a hole in it


def test_words_become_the_outlines_of_their_glyphs(tmp_path: Path) -> None:
    # flexo's own PDF: real words in an embedded face.
    target = tmp_path / "words.pdf"
    write_pdf(
        ['<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60" viewBox="0 0 200 60">'
         '<text x="10" y="40" font-size="24" fill="#2060a0">Flexo 42</text></svg>'],
        target,
    )
    art = pdfart._read(str(target), 1, 0)

    assert not art.whole and art.pictured == 0
    assert "<text" not in art.markup
    glyphs = _shapes(art)
    assert glyphs and glyphs[0].get("fill") == "#2060a0"
    assert glyphs[0].get("d", "").count("M") >= 7  # F l e x o 4 2, and the holes


def test_a_gradient_is_a_picture_in_its_place(tmp_path: Path) -> None:
    shading = (
        "<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [40 0 160 0] /Extend [true true] "
        "/Function << /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0 0 1] /N 1 >> >>"
    )
    content = "q 40 20 120 60 re W n /Sh0 sh Q\n0 0 0 RG 1 w 10 10 m 30 10 l S\n"
    art = _read(tmp_path, _pdf(content, resources="/Shading << /Sh0 5 0 R >>", objects=(shading,)))

    assert not art.whole and art.pictured == 1
    (picture,) = _pictures(art)
    placed = [float(picture.get(name, "0")) for name in ("x", "y", "width", "height")]
    assert placed == pytest.approx([40, 20, 120, 60], abs=0.5)
    assert len(_shapes(art)) == 1  # the line beside it is still a line


def test_a_group_with_an_opacity_of_its_own_passes_it_to_its_one_shape(tmp_path: Path) -> None:
    content = "/GS0 gs /Fm0 Do\n"
    resources = "/ExtGState << /GS0 << /ca 0.5 /CA 0.5 >> >> /XObject << /Fm0 5 0 R >>"
    group = _form("0 0.5 0 rg 20 20 80 50 re f")
    art = _read(tmp_path, _pdf(content, resources=resources, objects=(group,)))

    assert not art.whole and art.pictured == 0
    (shape,) = _shapes(art)
    assert float(shape.get("fill-opacity", "1")) == pytest.approx(0.5, abs=0.01)


def test_a_multiplying_group_keeps_its_blend(tmp_path: Path) -> None:
    content = "0 0 1 rg 10 10 120 80 re f /GS0 gs /Fm0 Do\n"
    resources = "/ExtGState << /GS0 << /BM /Multiply >> >> /XObject << /Fm0 5 0 R >>"
    group = _form("1 1 0 rg 60 20 120 60 re f")
    art = _read(tmp_path, _pdf(content, resources=resources, objects=(group,)))

    assert not art.whole
    yellow = next(shape for shape in _shapes(art) if shape.get("fill") == "#ffff00")
    assert "mix-blend-mode:multiply" in (yellow.get("style") or "")


def test_a_hidden_layer_is_left_out(tmp_path: Path) -> None:
    catalog = "/OCProperties << /OCGs [5 0 R 6 0 R] /D << /OFF [6 0 R] >> >>"
    resources = "/Properties << /L1 5 0 R /L2 6 0 R >>"
    content = (
        "/OC /L1 BDC 1 0 0 rg 10 10 50 50 re f EMC\n"
        "/OC /L2 BDC 0 0 1 rg 100 10 50 50 re f EMC\n"
    )
    layers = ("<< /Type /OCG /Name (Shown) >>", "<< /Type /OCG /Name (Hidden) >>")
    art = _read(tmp_path, _pdf(content, resources=resources, objects=layers, catalog=catalog))

    assert [shape.get("fill") for shape in _shapes(art)] == ["#ff0000"]


def test_an_illustrator_file_shows_its_art_not_its_whole_artboard(tmp_path: Path) -> None:
    content = "0 g 250 400 100 60 re f\n"
    data = _pdf(content, box="0 0 595 842", page="/ArtBox [240 390 360 470]")

    whole = _read(tmp_path, data)
    art = _read(tmp_path, data, name="art.ai", art=True)

    assert (whole.width, whole.height) == (595, 842)
    assert (art.width, art.height) == pytest.approx((120, 80))


def test_a_reading_that_does_not_draw_as_pdfium_does_is_drawn_by_pdfium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Were a glyph read wrong -- here, every glyph lost -- the check finds the words that
    # differ and draws them as pictures, so the page is never seen wrong.
    target = tmp_path / "words.pdf"
    write_pdf(
        ['<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60" viewBox="0 0 200 60">'
         '<rect x="150" y="10" width="40" height="40" fill="#cc3300"/>'
         '<text x="10" y="40" font-size="24">Wrong</text></svg>'],
        target,
    )
    monkeypatch.setattr(pdfart._Reader, "_glyph", lambda self, font, code: [])
    art = pdfart._read(str(target), 1, 1)

    assert not art.whole and art.pictured == 1
    assert len(_pictures(art)) == 1 and len(_shapes(art)) == 1  # the box is still a shape


def test_artwork_loads_a_pdf_page_as_vectors_sized_in_points(tmp_path: Path) -> None:
    target = tmp_path / "panel.pdf"
    target.write_bytes(_pdf("0 0 1 rg 20 10 60 30 re f\n", box="0 0 144 72"))

    art = load_artwork("panel", str(target))

    assert art.format == "svg"
    assert (art.width, art.height) == pytest.approx((144, 72))
    assert "<path" in art.markup


def test_artwork_names_an_artboard_after_a_hash(tmp_path: Path) -> None:
    target = tmp_path / "boards.pdf"
    target.write_bytes(_pdf("0 g 0 0 10 10 re f\n"))

    with pytest.raises(FlexoError) as caught:
        load_artwork("boards", f"{target}#2")
    assert "has 1 page, not 2" in str(caught.value)
    assert "artboard" in (caught.value.diagnostics[0].hint or "")


def test_an_illustrator_file_without_its_pdf_says_how_to_save_one(tmp_path: Path) -> None:
    target = tmp_path / "private.ai"
    target.write_bytes(b"%!PS-Adobe-3.0\n%%Creator: Adobe Illustrator(R) 24.0\n")

    with pytest.raises(FlexoError) as caught:
        load_artwork("private", str(target))
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.code == "image.ai.private"
    assert "Create PDF Compatible File" in (diagnostic.hint or "")
