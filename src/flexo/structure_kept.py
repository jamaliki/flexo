"""Molecules drawn before, kept on disk: what mol-sketch drew of a structure -- its picture
or its shapes -- and what was found wrong with it, kept by all it was drawn from, so a figure
opened again (in the studio, or built again) is drawn without reading or drawing its
molecules anew. A ribosome takes seconds to read and draw; read back, a few milliseconds.

They are kept in flexo's cache folder (``~/Library/Caches/flexo/structures`` on a Mac), or
in the folder ``FLEXO_STRUCTURE_CACHE`` names (``FLEXO_STRUCTURE_CACHE=0`` keeps none), by
everything the drawing is made from: the structure's settings as it is drawn (its ask), its
files -- where each is, when it was last saved and how long it is -- and flexo's and
mol-sketch's own code. A change to any of them draws it afresh. The most recently used are
kept, up to ``KEPT`` of them and ``SIZE`` bytes in all.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path

VERSION = 1
"""Changed whenever what is kept changes, so what was kept before is drawn again."""

KEPT = 96
"""How many drawings and checks are kept; the least recently used go first."""

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
    """What was found wrong with ``ask`` (its fields, or None), kept."""

    key = _key("checked", ask, name)
    if key is not None:
        _write(key + ".json", json.dumps({"problem": problem}).encode("utf-8"))


def _key(kind: str, ask, *more) -> str | None:
    """What ``ask`` is kept by: its settings, its files as they are now, and the code that
    draws it -- None when a file of it can't be looked at, or nothing is kept."""

    if folder() is None:
        return None
    files = []
    for name in (ask.source, ask.ss_from, ask.density):
        if not name:
            continue
        path = Path(name).expanduser()
        if not path.exists():
            files.append(name)  # a PDB entry or a map by its ID: the same wherever it is read
            continue
        try:
            stat = path.stat()
            files.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
        except OSError:
            return None
    named = repr((VERSION, kind, _code(), tuple(files), ask, more))
    return hashlib.sha256(named.encode("utf-8")).hexdigest()[:32]


_CODE: list[str] = []


def _code() -> str:
    """flexo's own source and mol-sketch's (its engine and the Python that draws with it),
    hashed, with the versions of what draws for it: a change to any draws it afresh."""

    if not _CODE:
        import importlib.metadata
        import importlib.util

        import flexo

        digest = hashlib.sha256()
        for path in sorted(Path(flexo.__file__).parent.rglob("*.py")):
            digest.update(path.read_bytes())
        spec = importlib.util.find_spec("molsketch")
        if spec is not None and spec.origin:
            here = Path(spec.origin).parent
            for path in sorted([*here.glob("*.py"), *here.glob("*.js")]):
                digest.update(path.read_bytes())
        for package in ("skia-python", "mini-racer"):
            with contextlib.suppress(importlib.metadata.PackageNotFoundError):
                digest.update(importlib.metadata.version(package).encode())
        _CODE.append(digest.hexdigest()[:16])
    return _CODE[0]


def _read(name: str) -> bytes | None:
    kept = folder() / name  # type: ignore[operator]
    try:
        data = kept.read_bytes()
        os.utime(kept)  # used now: kept the longest
    except OSError:
        return None
    return data


def _write(name: str, data: bytes) -> None:
    where = folder()
    assert where is not None
    try:
        where.mkdir(parents=True, exist_ok=True)
        partial = where / f"{name}.{os.getpid()}.saving"
        partial.write_bytes(data)
        partial.replace(where / name)
        _prune(where)
    except OSError:
        pass  # a cache that cannot be written is only slower


def _prune(where: Path) -> None:
    """The least recently used let go, past ``KEPT`` of them or ``SIZE`` bytes."""

    found = []
    for item in where.iterdir():
        if item.suffix in (".svg", ".png", ".json"):
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
