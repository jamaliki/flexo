"""A photograph is read as what its bytes are, not as its name says -- a PNG saved from a web
page as ``.jpg`` is the PNG it is -- and the photographs no drawing's viewers all show (WebP,
TIFF, BMP, a phone's HEIC, AVIF) are placed as the PNG they are made, once, in the cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from flexo import pdfart
from flexo.artwork import load_artwork
from flexo.diagnostics import FlexoError

Image = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # (Made pictures kept in the test's own folder, not the person's cache.)
    folder = tmp_path / "cache"
    monkeypatch.setattr(pdfart, "_cache_folder", lambda: folder)
    return folder


def _picture(path: Path, kind: str, size=(120, 80), mode="RGB") -> Path:
    picture = Image.new(mode, size, (200, 16, 46, 255) if mode == "RGBA" else (200, 16, 46))
    if mode == "RGBA":
        picture.paste((0, 0, 0, 0), (0, 0, 40, 40))  # a corner clear, as a cut-out's is
    picture.save(path, kind, **({"lossless": True} if kind == "WEBP" else {}))
    return path


def test_a_png_named_jpg_is_read_as_the_png_it_is(tmp_path: Path) -> None:
    # (Mickey at the wheel, saved from a web page as steamboat-willie.jpg: a PNG, its
    # background clear, that the slide refused as "not a readable JPEG".)
    path = _picture(tmp_path / "steamboat-willie.jpg", "PNG", mode="RGBA")
    art = load_artwork("willie", str(path))
    assert art.format == "png"
    assert (round(art.width), round(art.height)) == (90, 60)  # 120 by 80 px, in points
    assert art.data_uri.startswith("data:image/png;base64,")


def test_a_jpeg_named_png_is_read_as_the_jpeg_it_is(tmp_path: Path) -> None:
    art = load_artwork("photo", str(_picture(tmp_path / "photo.png", "JPEG")))
    assert art.format == "jpeg"
    assert art.data_uri.startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize(
    ("name", "kind"),
    [("cell.webp", "WEBP"), ("cell.tiff", "TIFF"), ("cell.tif", "TIFF"), ("cell.bmp", "BMP")],
)
def test_a_webp_tiff_or_bmp_is_placed_as_the_png_it_is_made(
    tmp_path: Path, cache: Path, name: str, kind: str
) -> None:
    source = _picture(tmp_path / name, kind)
    art = load_artwork("cell", str(source))
    assert art.format == "png"
    assert (round(art.width), round(art.height)) == (90, 60)
    assert art.path.parent == cache / "pictures" and art.path.suffix == ".png"
    with Image.open(art.path) as made:
        assert made.size == (120, 80) and made.getpixel((10, 10))[:3] == (200, 16, 46)
    # Read again, it is the PNG made before: made once for each version of the file.
    assert load_artwork("cell", str(source)).path == art.path


def test_a_webp_saved_as_jpg_is_made_a_png_too(tmp_path: Path) -> None:
    art = load_artwork("cell", str(_picture(tmp_path / "cell.jpg", "WEBP")))
    assert art.format == "png"


def test_a_clear_background_stays_clear(tmp_path: Path) -> None:
    art = load_artwork("cell", str(_picture(tmp_path / "cell.webp", "WEBP", mode="RGBA")))
    with Image.open(art.path) as made:
        assert made.mode == "RGBA" and made.getpixel((5, 5))[3] == 0


def test_a_file_that_is_no_picture_says_so_whatever_its_name(tmp_path: Path) -> None:
    path = tmp_path / "notes.jpg"
    path.write_bytes(b"These are words, not a picture.")
    with pytest.raises(FlexoError, match=r"image\.source\.unknown") as raised:
        load_artwork("notes", str(path))
    assert "none of PNG, JPEG, GIF, WebP, TIFF, BMP, HEIC or AVIF" in str(raised.value)
