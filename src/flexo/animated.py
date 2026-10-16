"""Animated pictures: a GIF's frames, how long it plays, and the still that paper shows of it.

A GIF is placed as a photograph is -- sized by its pixels and its proportions, cropped,
carried as its own bytes -- and it plays wherever a screen shows it: the studio, a
slideshow, the SVG opened in a browser, PowerPoint and Keynote. Paper cannot play it, so a
PDF or a PNG shows one frame of it: the first, unless its picture names another (a deck's
``still: 12``, a figure image's ``still`` property; frames are counted from 1). The
``<image>`` that draws it carries that number as ``data-flexo-still``, and ``stilled`` puts
the frame in its place, as a PNG, wherever a drawing is made into a PDF or a PNG.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

GIF_SIGNATURES = (b"GIF87a", b"GIF89a")
STILL = "data-flexo-still"
"""The attribute of a GIF's ``<image>`` naming the frame a PDF or PNG shows (from 1)."""

SHORTEST = 0.1
"""Seconds a frame is shown that asks for 10 ms or less, as browsers (and PowerPoint) show
it: a GIF saved with no delay at all plays at ten frames a second, never as fast as it can."""


_LOOPING = (b"NETSCAPE2.0", b"ANIMEXTS1.0")
"""The application blocks that say how many times a GIF plays."""


@dataclass(frozen=True, slots=True)
class Animation:
    """How a GIF plays: its frames, and the seconds it takes to play them once."""

    frames: int
    seconds: float
    loops: int | None = 0
    """How many times it plays again: 0 for ever, ``None`` once only (it says nothing)."""

    @property
    def animated(self) -> bool:
        return self.frames > 1


def is_gif(data: bytes) -> bool:
    return data[:6] in GIF_SIGNATURES


def gif_size(data: bytes) -> tuple[int, int] | None:
    """A GIF's size in pixels, from its logical screen (its first ten bytes)."""

    if not is_gif(data) or len(data) < 10:
        return None
    return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")


def timing(data: bytes) -> Animation:
    """How the GIF ``data`` plays, read from its blocks without decoding a pixel: each image
    in it a frame, each frame's delay from the graphic control before it, and the loops its
    NETSCAPE2.0 block asks for. A file cut short counts the frames it has."""

    if not is_gif(data) or len(data) < 13:
        raise ValueError("not a GIF")
    end = len(data)
    at = 13
    if data[10] & 0x80:  # a global colour table
        at += 3 * (2 << (data[10] & 0x07))
    delays: list[int] = []
    delay = 0
    loops: int | None = None
    while at < end:
        kind = data[at]
        if kind == 0x3B:  # the trailer
            break
        if kind == 0x21 and at + 2 < end:  # an extension
            label, at = data[at + 1], at + 2
            if label == 0xF9 and at + 3 < end and data[at] >= 4:
                delay = data[at + 2] | data[at + 3] << 8
            elif label == 0xFF and data[at] == 11 and data[at + 1 : at + 12] in _LOOPING:
                sub = at + 12
                if sub + 3 < end and data[sub] >= 3 and data[sub + 1] == 1:
                    loops = data[sub + 2] | data[sub + 3] << 8
            at = _past_blocks(data, at)
        elif kind == 0x2C and at + 10 <= end:  # an image: one frame
            packed, at = data[at + 9], at + 10
            if packed & 0x80:  # a local colour table
                at += 3 * (2 << (packed & 0x07))
            at = _past_blocks(data, at + 1)  # (past the LZW code size, then its data)
            delays.append(delay)
            delay = 0
        else:
            break
    seconds = sum(SHORTEST if hundredths <= 1 else hundredths / 100.0 for hundredths in delays)
    return Animation(max(len(delays), 1), round(seconds, 3) if len(delays) > 1 else 0.0, loops)


def _past_blocks(data: bytes, at: int) -> int:
    """Where a run of data sub-blocks starting at ``at`` ends (past its empty one)."""

    end = len(data)
    while at < end:
        size = data[at]
        at += 1
        if size == 0:
            break
        at += size
    return at


def animation(path: str | Path) -> Animation | None:
    """How the GIF at ``path`` plays (read once for each version of it); None for a file
    that is not a GIF."""

    file = Path(path)
    try:
        stamp = file.stat().st_mtime_ns
    except OSError:
        return None
    return _animation(str(file.resolve()), stamp)


@lru_cache(maxsize=64)
def _animation(resolved: str, stamp: int) -> Animation | None:
    try:
        return timing(Path(resolved).read_bytes())
    except (OSError, ValueError):
        return None


def still_frame(value: object) -> int:
    """The frame a still is drawn from, as a picture names it (``still: 12``): from 1, the
    first for anything that is not a whole number of one or more."""

    if isinstance(value, bool):
        return 1
    try:
        number = float(str(value).strip()) if isinstance(value, str) else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return int(number) if number.is_integer() and number >= 1 else 1


def still_png(data: bytes, frame: int = 1) -> bytes:
    """Frame ``frame`` (from 1; the last for a number past it) of the GIF ``data``, as a
    PNG: drawn as a browser draws it there, over the frames before it as they ask."""

    from PIL import Image

    with Image.open(BytesIO(data)) as picture:
        count = getattr(picture, "n_frames", 1)
        picture.seek(min(max(frame, 1), count) - 1)
        shown = picture.convert("RGBA")
    out = BytesIO()
    shown.save(out, "PNG")
    return out.getvalue()


@lru_cache(maxsize=32)
def _still_uri(encoded: str, frame: int) -> str:
    try:
        png = still_png(base64.b64decode(encoded), frame)
    except Exception:  # a GIF Pillow cannot read: left as it is
        return ""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def still_href(artwork: object, frame: int = 1) -> str:
    """What a drawing's ``<image href>`` says for a GIF (an ``Artwork``) drawn still at
    ``frame``: the studio's address for that frame alone, while it draws for its page, and
    the frame itself, as a PNG, otherwise (an export's)."""

    from flexo.artwork import picture_href

    href = picture_href(artwork)  # type: ignore[arg-type]
    if href.startswith("/api/picture?"):
        return f"{href}&still={max(frame, 1)}"
    if href.startswith("data:image/gif;base64,"):
        return _still_uri(href.split(",", 1)[1], max(frame, 1)) or href
    return href


_IMAGE_TAG = re.compile(r"<image\b[^>]*>")
_GIF_HREF = re.compile(r'\bhref="data:image/gif;base64,([^"]*)"')
_STILL_OF = re.compile(rf'\b{STILL}="(\d+)"')


def stilled(svg_text: str) -> str:
    """``svg_text`` as paper shows it: each GIF it carries the still frame its ``<image>``
    names (``data-flexo-still``, else the first), as a PNG. A drawing with no GIF is
    returned as it is."""

    if "data:image/gif" not in svg_text:
        return svg_text

    def still(match: re.Match[str]) -> str:
        tag = match.group(0)
        found = _GIF_HREF.search(tag)
        if found is None:
            return tag
        named = _STILL_OF.search(tag)
        uri = _still_uri(found.group(1), int(named.group(1)) if named else 1)
        if not uri:
            return tag
        return f'{tag[: found.start()]}href="{uri}"{tag[found.end() :]}'

    return _IMAGE_TAG.sub(still, svg_text)
