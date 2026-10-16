"""A GIF is a picture that plays (``flexo.animated``): placed as a photograph is, sized by its
pixels, carried as its own bytes in every drawing a screen shows, and -- in a PDF or a PNG,
which cannot play -- the frame its picture names, as a PNG."""

from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest
from PIL import Image

from flexo.animated import (
    STILL,
    animation,
    gif_size,
    still_frame,
    still_href,
    still_png,
    stilled,
    timing,
)
from flexo.artwork import load_artwork, picture_href, picture_link
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.drawing import read_drawing
from flexo.export import export_outputs, rasterise
from flexo.pdf import pdf_bytes
from flexo.units import pt

COLOURS = ((200, 16, 46), (31, 119, 180), (44, 160, 44))
"""Red, blue and green: one frame each."""


def gif(width: int = 6, height: int = 4, delays: tuple[int, ...] = (400, 400, 400)) -> bytes:
    """A GIF of a frame of each colour, each shown ``delays`` milliseconds, played for ever."""

    frames = [Image.new("RGB", (width, height), COLOURS[n % 3]) for n in range(len(delays))]
    out = io.BytesIO()
    frames[0].save(
        out, "GIF", save_all=True, append_images=frames[1:], duration=list(delays), loop=0
    )
    return out.getvalue()


def colour_of(png: bytes) -> tuple[int, int, int]:
    with Image.open(io.BytesIO(png)) as picture:
        return picture.convert("RGB").getpixel((picture.width // 2, picture.height // 2))


def svg_of(*images: str, size: str = 'width="60" height="40"') -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 40" {size}>'
        + "".join(images)
        + "</svg>"
    )


def uri(data: bytes, kind: str = "gif") -> str:
    return f"data:image/{kind};base64,{base64.b64encode(data).decode()}"


def test_a_gif_says_its_frames_how_long_they_take_and_how_often_it_plays() -> None:
    played = timing(gif(delays=(400, 400, 400)))
    assert (played.frames, played.seconds, played.loops, played.animated) == (3, 1.2, 0, True)
    # A frame saved with no delay is shown a tenth of a second, as a browser shows it.
    assert timing(gif(delays=(0, 0, 250, 0))).seconds == pytest.approx(0.55)
    # One frame does not play; a GIF that says nothing of loops plays once.
    single = io.BytesIO()
    Image.new("RGB", (3, 3), COLOURS[0]).save(single, "GIF")
    still = timing(single.getvalue())
    assert (still.frames, still.seconds, still.loops, still.animated) == (1, 0.0, None, False)
    # A file cut short counts the frames it has; one that is no GIF is said so.
    whole = gif(delays=(100,) * 5)
    assert 1 <= timing(whole[: len(whole) * 2 // 3]).frames < 5
    with pytest.raises(ValueError):
        timing(b"\x89PNG\r\n\x1a\n")
    assert gif_size(gif(9, 7)) == (9, 7) and gif_size(b"GIF8") is None


def test_a_gif_is_artwork_sized_by_its_pixels_and_carried_whole(tmp_path: Path) -> None:
    source = tmp_path / "spin.gif"
    source.write_bytes(gif(240, 160))
    art = load_artwork("figure.spin", str(source))
    # A GIF's pixel is a CSS pixel, as a PNG's is: 240 by 160 pixels is 180 by 120 points.
    assert (art.format, art.width, art.height, art.aspect) == ("gif", 180.0, 120.0, 1.5)
    assert art.data_uri == uri(source.read_bytes())
    assert animation(source).frames == 3 and animation(tmp_path / "absent.gif") is None
    # The studio names it by its address, as it names a photograph.
    token = picture_link.set(lambda artwork: f"/api/picture?path={artwork.path.name}&v=1")
    try:
        assert picture_href(art) == "/api/picture?path=spin.gif&v=1"
        assert still_href(art, 2) == "/api/picture?path=spin.gif&v=1&still=2"
    finally:
        picture_link.reset(token)
    assert colour_of(base64.b64decode(still_href(art, 3).split(",", 1)[1])) == COLOURS[2]
    broken = tmp_path / "broken.gif"
    broken.write_bytes(b"not a GIF at all")
    # (Read as what its bytes are, whatever its name: these are no picture's.)
    with pytest.raises(Exception, match=r"image\.source\.unknown"):
        load_artwork("figure.broken", str(broken))


def test_a_still_is_the_frame_named_from_one_and_the_last_for_one_past_it() -> None:
    data = gif()
    assert [colour_of(still_png(data, frame)) for frame in (1, 2, 3, 9)] == [
        COLOURS[0],
        COLOURS[1],
        COLOURS[2],
        COLOURS[2],
    ]
    assert [still_frame(value) for value in (12, "4", 2.0, 0, -3, 1.5, True, None, "x")] == [
        12,
        4,
        2,
        1,
        1,
        1,
        1,
        1,
        1,
    ]


def test_paper_shows_the_frame_a_gif_names_and_a_screen_plays_it(tmp_path: Path) -> None:
    data = gif()
    svg = svg_of(
        f'<image id="a" x="0" y="0" width="30" height="40" href="{uri(data)}" {STILL}="2"/>',
        f'<image id="b" x="30" y="0" width="30" height="40" href="{uri(data)}"/>',
    )
    still = stilled(svg)
    hrefs = {
        item.get("id"): item.get("href") for item in ET.fromstring(still).iter() if item.get("id")
    }
    assert all(href.startswith("data:image/png;base64,") for href in hrefs.values())
    shown = {key: colour_of(base64.b64decode(href.split(",", 1)[1])) for key, href in hrefs.items()}
    assert shown == {"a": COLOURS[1], "b": COLOURS[0]}
    # A drawing with no GIF is as it was; the SVG itself keeps the GIF, every frame.
    plain = svg_of(f'<image href="{uri(b"x", "png")}" width="1" height="1"/>')
    assert stilled(plain) is plain and uri(data) in svg
    # The PNG: the frame named, drawn.
    with Image.open(io.BytesIO(rasterise(svg, dpi=72.0))) as picture:
        assert picture.convert("RGB").getpixel((15, 20)) == COLOURS[1]
        assert picture.convert("RGB").getpixel((45, 20)) == COLOURS[0]
    # The PDF: the frame named, as its image's pixels.
    pixels = b"".join(_streams(pdf_bytes(svg)))
    blue, red = bytes(COLOURS[1]) * 6, bytes(COLOURS[0]) * 6
    assert blue in pixels and red in pixels and bytes(COLOURS[2]) * 6 not in pixels
    # A drawing given as a drawing (a copy's): each GIF its first frame.
    assert bytes(COLOURS[0]) * 6 in b"".join(_streams(pdf_bytes(read_drawing(svg))))


def _streams(pdf: bytes) -> list[bytes]:
    out = []
    for found in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            out.append(zlib.decompress(found.group(1)))
        except zlib.error:
            out.append(found.group(1))
    return out


def test_a_figure_image_of_a_gif_plays_and_names_its_still(tmp_path: Path) -> None:
    source = tmp_path / "spin.gif"
    source.write_bytes(gif(60, 40))
    with Figure("animated", width=pt(320.0)) as figure:  # noqa: SIM117
        with figure.module("panel") as panel:
            panel.image("art", source, properties={"still": 3})
    compilation = compile_figure(figure.spec)
    drawn = next(
        item
        for item in ET.fromstring(compilation.document.text).iter()
        if item.get("id") == "panel.art.artwork"
    )
    assert drawn.get("href") == uri(source.read_bytes()) and drawn.get(STILL) == "3"
    # Its PDF and its PNG show that frame.
    out = export_outputs(compilation, tmp_path / "out", formats=("pdf", "png"))
    assert bytes(COLOURS[2]) * 6 in b"".join(_streams(out.pdf.read_bytes()))
    with Image.open(out.png) as picture:
        assert COLOURS[2] in {colour for _, colour in picture.convert("RGB").getcolors(1 << 20)}


def test_a_gif_cropped_is_read_as_one_picture_cropped_round_or_to_a_shape() -> None:
    """A GIF stops playing as a pattern's tile, so a slide crops one with a window on it: a
    nested <svg> (the part kept its viewport) saying where the whole picture is, holding it
    -- clipped to an oval or a shape's outline. Read, it is the one picture, cropped."""

    href = uri(gif())

    def window(clip: str = "", shaped: str = "") -> str:
        return svg_of(
            '<svg id="pic" x="10" y="5" width="20" height="30" viewBox="10 5 20 30" '
            'preserveAspectRatio="none" data-flexo-whole="0 5 40 30">'
            f"{clip}"
            f'<image x="0" y="5" width="40" height="30" href="{href}" '
            f'preserveAspectRatio="none" {shaped}/></svg>'
        )

    plain = next(read_drawing(window()).walk())
    assert (plain.id, plain.x, plain.y, plain.width, plain.height) == ("pic", 0.0, 5.0, 40.0, 30.0)
    assert plain.clip == (10.0, 5.0, 30.0, 35.0) and not plain.oval and plain.href == href
    oval = next(
        read_drawing(
            window(
                '<clipPath id="pic.crop"><ellipse cx="20" cy="20" rx="10" ry="15"/></clipPath>',
                'clip-path="url(#pic.crop)"',
            )
        ).walk()
    )
    assert oval.oval and oval.clip == (10.0, 5.0, 30.0, 35.0)
    star = next(
        read_drawing(
            window(
                '<clipPath id="pic.crop"><path d="M 20 5 L 30 35 L 10 35 Z"/></clipPath>',
                'clip-path="url(#pic.crop)"',
            )
        ).walk()
    )
    assert star.outline and star.clip == (10.0, 5.0, 30.0, 35.0) and not star.oval
    # Any other nested drawing is read as it was: a group of what it holds.
    other = read_drawing(window().replace(' data-flexo-whole="0 5 40 30"', ""))
    assert other.root.items[0].id == "pic"
    assert next(other.walk()).id is None


def test_the_studio_sends_a_gif_whole_or_a_frame_of_it(tmp_path: Path) -> None:
    from flexo.studio import pictures

    source = tmp_path / "large.gif"
    # Larger than a photograph is sent as it is: a GIF still goes whole, every frame.
    source.write_bytes(gif(900, 900, delays=(100,) * 12))
    data, kind = pictures.shown(source)
    assert (data, kind) == (source.read_bytes(), "image/gif")
    still, kind = pictures.shown(source, 2)
    assert kind == "image/png" and colour_of(still) == COLOURS[1]


def test_a_gif_in_a_drawing_imported_stays_a_gif() -> None:
    from flexo.svgimport import _picture_bytes

    data = gif()
    assert _picture_bytes(uri(data)) == (data, ".gif")
