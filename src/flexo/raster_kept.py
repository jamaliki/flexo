"""SVG pictures drawn as PNGs, kept: a picture drawn once for a PDF or a PowerPoint is not
drawn again -- for the other, for the next export of the same deck, or for the next build of
it on the command line. Drawing an SVG of a few hundred kilobytes takes resvg a quarter of a
second or more, and a deck may have a dozen of them.

What is drawn is kept by everything it is drawn from: the SVG's text, how many pixels wide
it is drawn, resvg's version, and the folders of fonts it is drawn with (as the disk has
them: a font put in one draws it afresh). The most recently used are kept in memory, up to
``MEMORY`` bytes, and on disk in flexo's cache folder (``~/Library/Caches/flexo/pictures``
on a Mac), or in the folder ``FLEXO_PICTURE_CACHE`` names (``FLEXO_PICTURE_CACHE=0`` keeps
none on disk), up to ``KEPT`` of them and ``SIZE`` bytes.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

VERSION = 1
"""Changed whenever what is kept changes, so what was kept before is drawn again."""

MEMORY = 96 << 20
"""How many bytes of drawn pictures are kept in memory."""

KEPT = 256
"""How many drawn pictures are kept on disk; the least recently used go first."""

SIZE = 256 << 20
"""How many bytes they may take on disk in all."""

_KEPT: OrderedDict[str, bytes] = OrderedDict()
_LOCK = threading.Lock()


def png_of(svg: str, pixels: int) -> bytes:
    """``svg`` (an SVG's text) drawn ``pixels`` wide as a PNG, by resvg with the fonts flexo
    measures with -- as it was drawn before, where it was."""

    import resvg_py

    from flexo.fonts import font_directories

    folders = [str(folder) for folder in font_directories()]
    key = _key(svg, pixels, folders)
    with _LOCK:
        data = _KEPT.get(key)
        if data is not None:
            _KEPT.move_to_end(key)
            return data
    data = _read(key)
    if data is None:
        # A dpi lets resvg resolve sizes given in pt or mm; the width sets the pixels.
        data = bytes(resvg_py.svg_to_bytes(svg_string=svg, dpi=72, width=pixels, font_dirs=folders))
        _write(key, data)
    _remember(key, data)
    return data


def remembered(svg: str, how: object, make: Callable[[], bytes]) -> bytes:
    """``make()``, a PNG drawn from ``svg`` as ``how`` says (a slide, at its resolution): as
    drawn before by this program, where it was. Kept in memory with the pictures above, and
    not on disk: what draws it (a slide's words as outlines) may change with flexo itself."""

    from flexo.fonts import font_directories

    key = _key(svg, how, [str(folder) for folder in font_directories()])
    with _LOCK:
        data = _KEPT.get(key)
        if data is not None:
            _KEPT.move_to_end(key)
            return data
    data = make()
    _remember(key, data)
    return data


def _remember(key: str, data: bytes) -> None:
    with _LOCK:
        _KEPT[key] = data
        _KEPT.move_to_end(key)
        total = sum(len(item) for item in _KEPT.values())
        while total > MEMORY and len(_KEPT) > 1:
            _, gone = _KEPT.popitem(last=False)
            total -= len(gone)


def _key(svg: str, pixels: object, folders: list[str]) -> str:
    digest = hashlib.sha256()
    stamps = []
    for folder in folders:
        try:
            stamps.append((folder, os.stat(folder).st_mtime_ns))
        except OSError:
            stamps.append((folder, 0))
    digest.update(repr((VERSION, _resvg(), pixels, stamps)).encode("utf-8"))
    digest.update(svg.encode("utf-8"))
    return digest.hexdigest()[:32]


_RESVG: list[str] = []


def _resvg() -> str:
    """resvg's version: another may draw the same picture otherwise."""

    if not _RESVG:
        import importlib.metadata

        try:
            _RESVG.append(importlib.metadata.version("resvg-py"))
        except importlib.metadata.PackageNotFoundError:
            _RESVG.append("")
    return _RESVG[0]


def folder() -> Path | None:
    """Where drawn pictures are kept on disk, or None when none are."""

    setting = os.environ.get("FLEXO_PICTURE_CACHE", "")
    if setting == "0":
        return None
    if setting:
        return Path(setting)
    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flexo" / "pictures"


def _read(key: str) -> bytes | None:
    where = folder()
    if where is None:
        return None
    kept = where / f"{key}.png"
    try:
        data = kept.read_bytes()
        os.utime(kept)  # used now: kept the longest
    except OSError:
        return None
    return data


def _write(key: str, data: bytes) -> None:
    where = folder()
    if where is None:
        return
    try:
        where.mkdir(parents=True, exist_ok=True)
        partial = where / f"{key}.png.{os.getpid()}.{threading.get_ident()}.saving"
        partial.write_bytes(data)
        partial.replace(where / f"{key}.png")
        _prune(where)
    except OSError:
        pass  # a cache that cannot be written is only slower


def _prune(where: Path) -> None:
    """The least recently used let go, past ``KEPT`` of them or ``SIZE`` bytes."""

    found = []
    for item in where.iterdir():
        if item.suffix == ".png":
            try:
                stat = item.stat()
            except OSError:
                continue
            found.append((stat.st_mtime, stat.st_size, item))
    found.sort(reverse=True)
    total = 0
    for place, (_, size, item) in enumerate(found):
        total += size
        if place >= KEPT or total > SIZE:
            item.unlink(missing_ok=True)
