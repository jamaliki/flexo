"""Pictures a drawing carries in itself, named by address instead as the studio sends it to
its page.

Some pictures go in a drawing as their own bytes (``data:`` URIs): a molecule's surface drawn
as a PNG (1.2 MB of base64 on one slide of the owner's deck), an SVG picture drawn as a picture
of its own (two of 460 kB on another), a photograph cut to a circle. Sent to the page in its
drawing, each went with every keystroke on its slide, was read again by the page with it, and
was held in the slide list's copy of it. As the studio sends a drawing to its page
(``Workspace.draw``), each such picture is taken out of it and named by an address of its own
(``/api/picture?made=``): named by what it is, so the browser keeps it for good and asks for it
once. Photographs are named by address as they are drawn (``flexo.studio.pictures``); these are
pictures made in the drawing, which no file holds.

What the kinds draw is as it was: an export, and anything else drawn outside the studio's page,
carries every picture as ever -- only what the page is sent changes. A picture copied out of the
page is carried again as the very ``data:`` URI it was (``flexo.studio.copying``).

What is taken out is kept in memory, up to ``MEMORY`` bytes, and on disk beside the pictures
``flexo.raster_kept`` keeps, up to ``KEPT`` of them and ``SIZE`` bytes: a page left open on a
studio started again, with the drawings the studio sent it before, finds them there.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

SMALLEST = 8192
"""Characters of base64 a picture must have to be named by address: a smaller one stays in its
drawing, where it costs the page less than a request of its own."""

MEMORY = 128 << 20
"""Bytes of pictures kept in memory."""

KEPT = 4096
"""Pictures kept on disk; the least recently used go first."""

SIZE = 256 << 20
"""Bytes they may take on disk in all."""

ROUTE = "/api/picture"

_KINDS = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}
"""The media types a picture is taken out of a drawing in, by the suffix of its name."""
_SUFFIXES = {f"data:{kind};base64": suffix for suffix, kind in _KINDS.items()}
# (A GIF is left in its drawing: the page holds one still, and plays one, by its file's address.)

_NAME = re.compile(r"[0-9a-f]{32}\.(?:png|jpg|svg)")
_OPENING = 'href="data:image/'

TOUCHED = 600.0
"""Seconds between marking a picture on disk used as it is sent again from memory: the least
recently used are let go there first."""

_KEPT: OrderedDict[str, bytes] = OrderedDict()
_TOUCHED: dict[str, float] = {}
_LOCK = threading.Lock()
_WRITTEN = [0]


def linked(svg: str, token: str) -> str:
    """``svg`` as the studio sends it to its page: each picture it carries as a PNG, a JPEG or
    an SVG of ``SMALLEST`` characters or more named by its address (with ``token``) instead,
    and kept to be sent. A drawing with none is returned as it is."""

    if _OPENING not in svg:
        return svg
    pieces: list[str] = []
    done = 0
    start = svg.find(_OPENING)
    while start >= 0:
        value = start + len('href="')
        end = svg.find('"', value)
        if end < 0:
            break
        # (An element's href, or xlink:href: never another attribute ending so.)
        name = _taken(svg, value, end) if svg[start - 1 : start] in {" ", ":", "\n", "\t"} else None
        if name is not None:
            pieces.append(svg[done:value])
            pieces.append(f"{ROUTE}?made={name}&amp;token={token}")
            done = end
        start = svg.find(_OPENING, end)
    if not pieces:
        return svg
    pieces.append(svg[done:])
    return "".join(pieces)


def _taken(svg: str, value: int, end: int) -> str | None:
    """The name the picture whose ``data:`` URI is ``svg[value:end]`` is kept by, kept now if
    it was not -- or None, for one left in the drawing."""

    comma = svg.find(",", value, end)
    if comma < 0 or end - comma - 1 < SMALLEST:
        return None
    suffix = _SUFFIXES.get(svg[value:comma])
    if suffix is None:
        return None
    try:
        payload = svg[comma + 1 : end].encode("ascii")
    except UnicodeEncodeError:
        return None
    name = f"{hashlib.sha256(payload).hexdigest()[:32]}.{suffix}"
    touch = False
    with _LOCK:
        known = name in _KEPT
        if known:
            _KEPT.move_to_end(name)
            touch = time.monotonic() - _TOUCHED.get(name, 0.0) > TOUCHED
            if touch:
                _TOUCHED[name] = time.monotonic()
    if known:
        if touch:
            _touch(name)  # (in use: the last let go on disk)
        return name
    try:
        data = base64.b64decode(payload, validate=True)
    except ValueError:
        return None
    if base64.b64encode(data) != payload:
        return None  # (carried back by its bytes, it would not be the URI it was)
    _remember(name, data)
    _write(name, data)
    return name


def found(name: str) -> tuple[bytes, str] | None:
    """The picture kept by ``name`` (as ``linked`` names it) and its media type, or None."""

    if not _NAME.fullmatch(name):
        return None
    with _LOCK:
        data = _KEPT.get(name)
        if data is not None:
            _KEPT.move_to_end(name)
    if data is None:
        data = _read(name)
        if data is None:
            return None
        _remember(name, data)
    return data, _KINDS[name.rsplit(".", 1)[1]]


def data_uri(name: str) -> str | None:
    """The ``data:`` URI the picture kept by ``name`` was taken out of a drawing as, or None."""

    kept = found(name)
    if kept is None:
        return None
    data, kind = kept
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"


def folder() -> Path | None:
    """Where pictures taken out of drawings are kept on disk, or None when none are
    (``FLEXO_PICTURE_CACHE=0``)."""

    from flexo.raster_kept import folder as pictures

    where = pictures()
    return None if where is None else where / "shown"


def _remember(name: str, data: bytes) -> None:
    with _LOCK:
        _KEPT[name] = data
        _KEPT.move_to_end(name)
        _TOUCHED[name] = time.monotonic()
        total = sum(len(item) for item in _KEPT.values())
        while total > MEMORY and len(_KEPT) > 1:
            gone, data = _KEPT.popitem(last=False)
            _TOUCHED.pop(gone, None)
            total -= len(data)


def _touch(name: str) -> None:
    where = folder()
    if where is not None:
        with contextlib.suppress(OSError):
            os.utime(where / name)


def _read(name: str) -> bytes | None:
    where = folder()
    if where is None:
        return None
    kept = where / name
    try:
        data = kept.read_bytes()
        os.utime(kept)  # used now: kept the longest
    except OSError:
        return None
    return data


def _write(name: str, data: bytes) -> None:
    where = folder()
    if where is None:
        return
    target = where / name
    try:
        if target.is_file():
            os.utime(target)
            return
        where.mkdir(parents=True, exist_ok=True)
        partial = where / f"{name}.{os.getpid()}.{threading.get_ident()}.saving"
        partial.write_bytes(data)
        partial.replace(target)
    except OSError:
        return  # (kept in memory alone: a studio started again draws it anew)
    _WRITTEN[0] += 1
    if _WRITTEN[0] % 64 == 1:
        _prune(where)


def _prune(where: Path) -> None:
    """The least recently used let go, past ``KEPT`` of them or ``SIZE`` bytes."""

    found = []
    with contextlib.suppress(OSError):
        for item in where.iterdir():
            if _NAME.fullmatch(item.name):
                with contextlib.suppress(OSError):
                    stat = item.stat()
                    found.append((stat.st_mtime, stat.st_size, item))
    found.sort(reverse=True)
    total = 0
    for place, (_, size, item) in enumerate(found):
        total += size
        if place >= KEPT or total > SIZE:
            item.unlink(missing_ok=True)
