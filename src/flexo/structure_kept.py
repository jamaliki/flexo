"""Molecules drawn before, kept on disk: what mol-sketch drew of a structure -- its picture
or its shapes -- what was found wrong with it, how far its drawing reaches (``extent``) and
what it is framed by (``geometry``), kept by all it was drawn from, so a figure opened again
(in the studio, or built again) is drawn and laid out without reading, drawing or measuring
its molecules anew. A ribosome takes seconds to read and draw; read back, a few milliseconds.

They are kept in flexo's cache folder (``~/Library/Caches/flexo/structures`` on a Mac), or
in the folder ``FLEXO_STRUCTURE_CACHE`` names (``FLEXO_STRUCTURE_CACHE=0`` keeps none), by
everything the drawing is made from: the structure's settings as it is drawn (its ask), what
is in its files (by their names, not where they are or when they were saved: a deck unpacked
afresh draws from the same), and flexo's and mol-sketch's own code. A change to any of them
draws it afresh. The code is not in the file's name but in its first line
(``flexo.kept_versions``): drawn again after an update, a drawing replaces the one the version
before kept, rather than leaving it to take a place among those kept. The most recently used
are kept, up to ``KEPT`` of them and ``SIZE`` bytes in all.

Each file is looked at once for each thing looked up (``_key``; read only when the disk says
it has changed, ``flexo.kept_versions.content``), and what is read back is marked used once a
session (``_read``): a deck opened in a busy studio waits on every look at the disk, each one a
turn for the studio's other threads.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path

VERSION = 2
"""Changed whenever what is kept changes, so what was kept before is drawn again."""

KEPT = 600
"""How many drawings, checks, extents and geometries are kept; the least recently used go
first. (A deck of a few dozen structures keeps a hundred and fifty.)"""

PRUNED = 64
"""How many are kept between one pruning and the next: the folder is looked through on the
first keeping of a session and then after every ``PRUNED`` more, not after every one."""

SIZE = 256 << 20
"""How many bytes they may take in all."""

KINDS = {"shapes": (".svg", ".png"), "png": (".png",)}
"""What a drawing is kept as, by what it is (``shapes``: a look drawn as shapes, which may
have been drawn as a picture all the same; ``png``: a picture), and the files it may be."""


def folder() -> Path | None:
    """Where drawings are kept, or None when none are."""

    setting = os.environ.get("FLEXO_STRUCTURE_CACHE", "")
    if setting == "0":
        return None
    if setting:
        return Path(setting)
    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flexo" / "structures"


def drawing(ask, aspect: float, kind: str = "shapes") -> str | bytes | None:
    """The drawing kept for ``ask`` at ``aspect`` (an SVG's text, or a PNG's bytes), or None."""

    key = _key(kind, ask, aspect)
    if key is None:
        return None
    for suffix in KINDS[kind]:
        kept = _read(key + suffix)
        if kept is not None:
            return kept.decode("utf-8") if suffix == ".svg" else kept
    return None


def keep_drawing(ask, aspect: float, drawn: str | bytes, kind: str = "shapes") -> str | bytes:
    """``drawn`` kept for ``ask`` at ``aspect``; ``drawn`` itself."""

    key = _key(kind, ask, aspect)
    if key is not None:
        text = isinstance(drawn, str)
        _write(key + (".svg" if text else ".png"), drawn.encode("utf-8") if text else drawn)
    return drawn


def extent(ask, aspect: float, kind: str) -> tuple[bool, object]:
    """Whether how far the drawing kept for ``ask`` at ``aspect`` reaches was kept (a drawing
    as ``kind``, ``drawing``'s), and that: its ink, left, top, right and bottom, and its canvas,
    width and height, in the canvas's pixels -- or None, for a drawing of nothing."""

    key = _key(kind, ask, aspect)
    kept = None if key is None else _read(key + ".extent.json")
    if kept is None:
        return False, None
    try:
        found = json.loads(kept)["extent"]
        if found is None:
            return True, None
        (left, top, right, bottom), (width, height) = found
        return True, (
            (float(left), float(top), float(right), float(bottom)),
            (float(width), float(height)),
        )
    except (ValueError, KeyError, TypeError):
        return False, None


def keep_extent(ask, aspect: float, kind: str, found) -> None:
    """How far the drawing of ``ask`` at ``aspect`` reaches (``extent``'s), kept beside it."""

    key = _key(kind, ask, aspect)
    if key is not None:
        _write(key + ".extent.json", json.dumps({"extent": found}).encode("utf-8"))


GEOMETRY = ("points", "base", "seen")
"""The arrays a structure's geometry is kept as (``flexo.structure_frames._Geometry``)."""


def geometry(ask) -> dict | None:
    """What ``ask`` is framed by, as kept: its arrays (``GEOMETRY``) and its camera, or None."""

    key = _key("geometry", ask)
    kept = None if key is None else _read(key + ".npz")
    if kept is None:
        return None
    import io

    import numpy as np

    try:
        with np.load(io.BytesIO(kept), allow_pickle=False) as arrays:
            found = {name: arrays[name] for name in GEOMETRY}
            names, values = arrays["names"], arrays["values"]
        found["camera"] = tuple(
            (str(name), float(value)) for name, value in zip(names, values, strict=True)
        )
        return found
    except (OSError, ValueError, KeyError):
        return None


def keep_geometry(ask, arrays: dict, camera: tuple[tuple[str, float], ...]) -> None:
    """What ``ask`` is framed by (``geometry``'s), kept."""

    key = _key("geometry", ask)
    if key is None:
        return
    import io

    import numpy as np

    out = io.BytesIO()
    np.savez(
        out,
        names=np.array([name for name, _ in camera], dtype=str),
        values=np.array([value for _, value in camera], dtype=float),
        **{name: np.asarray(arrays[name], dtype=float) for name in GEOMETRY},
    )
    _write(key + ".npz", out.getvalue())


def checked(ask, name: str) -> tuple[bool, dict | None]:
    """Whether ``ask`` (a structure called ``name``) was checked before, and what was found
    wrong with it then (its fields, or None for nothing)."""

    key = _key("checked", ask, name)
    kept = None if key is None else _read(key + ".json")
    if kept is None:
        return False, None
    try:
        return True, json.loads(kept)["problem"]
    except (ValueError, KeyError, TypeError):
        return False, None


def keep_checked(ask, name: str, problem: dict | None) -> None:
    """What was found wrong with ``ask`` (its fields, or None), kept -- unless it says where one
    of its files is: kept by what is in its files, it is read back for the same files elsewhere."""

    words = " ".join(str(value) for value in (problem or {}).values())
    folders = [
        os.path.dirname(os.path.abspath(os.path.expanduser(name)))
        for name in (ask.source, ask.ss_from, ask.density)
        if name
    ]
    if any(len(where) > 1 and where in words for where in folders):
        return
    key = _key("checked", ask, name)
    if key is not None:
        _write(key + ".json", json.dumps({"problem": problem}).encode("utf-8"))


def _key(kind: str, ask, *more) -> str | None:
    """What ``ask`` is kept by: its settings, and what is in its files (by name, not by where
    they are or when they were saved) -- None when nothing is kept. (Kept, it is said which
    version of the code drew it: ``_read``.)

    A deck unpacked afresh -- opened on another computer, a copy of it, the bundle put back in
    its place -- has its files where it did not, saved when it was unpacked: what is in them
    is what it was, and so is what was drawn from them."""

    if folder() is None:
        return None
    from flexo.kept_versions import content

    files = []
    named = {}
    for field, stamp in (("source", "stamp"), ("ss_from", "ss_stamp"), ("density", None)):
        name = getattr(ask, field)
        if not name:
            continue
        path = os.path.expanduser(name)
        held = content(path)
        if held is None:
            files.append(name)  # a PDB entry or a map by its ID: the same wherever it is read
            continue
        files.append((os.path.basename(path), held))
        named[field] = os.path.basename(path)
        if stamp:
            named[stamp] = 0.0
    plain = dataclasses.replace(ask, **named) if named else ask
    # (The code that draws it is not in the name: each file says which version kept it.)
    said = repr((VERSION, kind, tuple(files), plain, more))
    return hashlib.sha256(said.encode("utf-8")).hexdigest()[:32]


def _code() -> str:
    """This version of flexo's and mol-sketch's code (``flexo.kept_versions.code``)."""

    from flexo.kept_versions import code

    return code()


_USED: set[Path] = set()
"""What has been read back this session, and marked used."""

_KEPT_SINCE = [0]
"""How many have been kept since the folder was last pruned (``PRUNED``)."""


def _read(name: str) -> bytes | None:
    """What is kept as ``name`` by this version of the code -- None for nothing, or what another
    version kept (``flexo.kept_versions.stamped``), which this one draws again."""

    from flexo.kept_versions import unstamped

    kept = folder() / name  # type: ignore[operator]
    try:
        data = kept.read_bytes()
    except OSError:
        return None
    version, data = unstamped(data)
    if version != _code():
        return None
    if kept not in _USED:
        with contextlib.suppress(OSError):
            os.utime(kept)  # used now: kept the longest (marked once a session)
        _USED.add(kept)
    return data


def _write(name: str, data: bytes) -> None:
    from flexo.kept_versions import stamped

    where = folder()
    assert where is not None
    try:
        where.mkdir(parents=True, exist_ok=True)
        partial = where / f"{name}.{os.getpid()}.saving"
        partial.write_bytes(stamped(data))
        partial.replace(where / name)
        _USED.add(where / name)
        if _KEPT_SINCE[0] % PRUNED == 0:
            _prune(where)
        _KEPT_SINCE[0] += 1
    except OSError:
        pass  # a cache that cannot be written is only slower


def _prune(where: Path) -> None:
    """The least recently used let go, past ``KEPT`` of them or ``SIZE`` bytes."""

    found = []
    for item in where.iterdir():
        if item.suffix in (".svg", ".png", ".json", ".npz"):
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
