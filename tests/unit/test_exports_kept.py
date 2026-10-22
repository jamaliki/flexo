"""What an export makes of a picture or a slide is kept, and what comes of it is the same:
an SVG picture drawn as pixels once (``raster_kept``), a slide's SVG read into a drawing once
(``drawings_kept``), a PDF's picture written once for every page it is on."""

from __future__ import annotations

import base64
import re
import zlib
from pathlib import Path

import pytest

from flexo import drawings_kept, raster_kept
from flexo.drawing import Group, read_drawing
from flexo.pdf import pdf_bytes

ART = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20">'
    '<rect x="2" y="2" width="36" height="16" rx="4" fill="#3f7fc0"/>'
    '<circle cx="10" cy="10" r="5" fill="#f0a030"/></svg>'
)


def _slide(art: str = ART, *, twice: bool = False) -> str:
    """A page with a picture on it (twice, where asked), a box, and a group."""

    href = "data:image/svg+xml;base64," + base64.b64encode(art.encode()).decode()
    picture = f'<image x="{{x}}" y="10" width="120" height="60" href="{href}"/>'
    pictures = picture.format(x=10) + (picture.format(x=200) if twice else "")
    box = '<rect id="box" x="10" y="100" width="80" height="40" fill="#222222"/>'
    line = '<path id="line" d="M 10 180 L 390 180" stroke="#000000" fill="none"/>'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">'
        f'<g id="slide">{box}{pictures}<g id="inner">{line}</g></g></svg>'
    )


def _resvg_calls(monkeypatch) -> list[int]:
    import resvg_py

    calls: list[int] = []
    real = resvg_py.svg_to_bytes

    def counted(**options):
        calls.append(options["width"])
        return real(**options)

    monkeypatch.setattr(resvg_py, "svg_to_bytes", counted)
    return calls


def test_an_svg_picture_is_drawn_once_and_found_again_in_memory_and_on_disk(
    tmp_path: Path, monkeypatch
) -> None:
    import resvg_py

    from flexo.fonts import font_directories

    monkeypatch.setenv("FLEXO_PICTURE_CACHE", str(tmp_path))
    raster_kept._KEPT.clear()
    calls = _resvg_calls(monkeypatch)
    folders = [str(folder) for folder in font_directories()]
    drawn = bytes(resvg_py.svg_to_bytes(svg_string=ART, dpi=72, width=500, font_dirs=folders))
    calls.clear()
    assert raster_kept.png_of(ART, 500) == drawn
    assert raster_kept.png_of(ART, 500) == drawn
    assert calls == [500]
    # Gone from memory (another process, the next build): read back from the disk.
    raster_kept._KEPT.clear()
    assert raster_kept.png_of(ART, 500) == drawn
    assert calls == [500]
    # Drawn at another size, or another picture: drawn.
    raster_kept.png_of(ART, 250)
    raster_kept.png_of(ART.replace("#3f7fc0", "#c03f3f"), 500)
    assert calls == [500, 250, 500]
    assert len(list(tmp_path.glob("*.png"))) == 3


def test_none_is_kept_on_disk_where_none_is_to_be(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEXO_PICTURE_CACHE", "0")
    monkeypatch.setenv("HOME", str(tmp_path))
    raster_kept._KEPT.clear()
    raster_kept.png_of(ART, 120)
    assert raster_kept.folder() is None
    assert not any(tmp_path.rglob("*.png"))


def test_a_drawing_kept_is_the_drawing_read_and_its_groups_are_each_reader_s_own() -> None:
    slide = _slide()
    first = drawings_kept.drawing_of(slide)
    assert first == read_drawing(slide)
    # A writer takes a group's contents apart (a PowerPoint takes out the lists it writes):
    # the next one to ask has them all, and its shapes are the very ones read.
    first.root.items[0].items.clear()
    second = drawings_kept.drawing_of(slide)
    assert second == read_drawing(slide)
    inner = [item for item in second.root.items[0].items if isinstance(item, Group)]
    assert inner and inner[0].items
    third = drawings_kept.drawing_of(slide)
    assert third.root is not second.root
    assert third.root.items[0].items[0] is second.root.items[0].items[0]


def _images(data: bytes) -> int:
    """How many pictures a PDF holds (their colour: not their alpha, an image of its own)."""

    return len(re.findall(rb"/Subtype /Image /Width \d+ /Height \d+ /ColorSpace /DeviceRGB", data))


def _contents(data: bytes) -> list[bytes]:
    streams = []
    for match in re.finditer(rb"<< /Filter /FlateDecode /Length (\d+) >>\nstream\n", data):
        body = data[match.end() : match.end() + int(match.group(1))]
        streams.append(zlib.decompress(body))
    return streams


def test_a_pdf_writes_a_picture_once_for_every_page_and_place_it_is_on(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FLEXO_PICTURE_CACHE", str(tmp_path))
    raster_kept._KEPT.clear()
    calls = _resvg_calls(monkeypatch)
    pages = [_slide(twice=True), _slide()]
    data = pdf_bytes(pages)
    # One picture, drawn once, on three places of two pages: one image, used three times.
    assert len(calls) == 1
    assert _images(data) == 1
    uses = [re.findall(rb"/(I\d+) Do", stream) for stream in _contents(data)]
    assert uses == [[b"I0", b"I0"], [b"I0"]]
    # Written again, it is the same.
    assert _contents(pdf_bytes(pages)) == _contents(data)
    assert len(calls) == 1


def test_a_pdf_written_from_what_was_kept_is_what_was_written_before(
    tmp_path: Path, monkeypatch
) -> None:
    from flexo import pdf

    monkeypatch.setenv("FLEXO_PICTURE_CACHE", str(tmp_path))
    pages = [_slide(), _slide(ART.replace("#f0a030", "#20a070"))]
    raster_kept._KEPT.clear()
    drawings_kept._KEPT.clear()
    pdf._IMAGES.clear()
    fresh = pdf_bytes(pages)
    again = pdf_bytes(pages)
    assert again == fresh


@pytest.fixture(autouse=True)
def _forgotten():
    yield
    raster_kept._KEPT.clear()
    drawings_kept._KEPT.clear()
