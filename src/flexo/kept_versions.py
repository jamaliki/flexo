"""What is kept on disk between sessions -- molecules drawn (``flexo.structure_kept``), a deck's
figures laid out (flexo-talk) -- kept by what it was made from and, apart, by the version of the
code that made it.

Each thing kept is found by what it was made from alone (its content's key), and its file says
which version of the code made it (``stamped``): kept again by another version, the file is
replaced. A version of the code is told by flexo's own source and mol-sketch's, hashed, with
the versions of what draws for them (``code``): any change to them is another version, which
draws afresh, as nearly every part of a drawing comes from them.

So, after an update, what the version before made of the same content is still there, until
the new version replaces it. The studio's page may be shown it at once while it is made again
(``earlier``): a deck opened just after an update shows every slide as quickly as on any other
day, each checked and, should it now be drawn otherwise, drawn anew a moment later. Nothing
else ever is: an export, a PDF or a PowerPoint, a slide presented, copied out, or looked at by
an agent is drawn by the version running.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

STAMP = b"flexo-kept "
"""How a file kept by a version of the code begins: then the version, and a new line."""

_EARLIER: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "flexo_kept_earlier", default=None
)


@contextlib.contextmanager
def earlier() -> Iterator[list[str]]:
    """Within it, what an earlier version of the code made may stand in for what this version
    has not made yet: each taken so is told in the list it gives (``took``), for what is drawn
    with it to be drawn again by this version. Only for the studio's page: what is drawn
    outside it is this version's alone."""

    taken: list[str] = []
    token = _EARLIER.set(taken)
    try:
        yield taken
    finally:
        _EARLIER.reset(token)


def allowed() -> bool:
    """Whether what an earlier version made may stand in here (``earlier``)."""

    return _EARLIER.get() is not None


def took(what: str) -> None:
    """Tell the drawing under way (``earlier``) that ``what`` is an earlier version's."""

    taken = _EARLIER.get()
    if taken is not None:
        taken.append(what)


def stamped(data: bytes) -> bytes:
    """``data`` as it is kept: its first line says the version of the code that made it."""

    return STAMP + code().encode("ascii") + b"\n" + data


def unstamped(data: bytes) -> tuple[str | None, bytes]:
    """The version of the code that made what was kept (``stamped``), and what it is -- or
    None and ``data`` as it is, for a file no version stamped."""

    if not data.startswith(STAMP):
        return None, data
    line, _, rest = data.partition(b"\n")
    return line[len(STAMP) :].decode("ascii", "replace"), rest


_CODE: list[str] = []


def code() -> str:
    """This version of the code: flexo's own source and mol-sketch's (its engine and the Python
    that draws with it), hashed, with the versions of what draws for it.

    An installed package (the app's) is told by the hashes its installation recorded of each
    of its files (``_recorded``): one file read, not every one -- in a busy studio each read is
    a wait, and reading them all took over a second. A package worked on in place is read."""

    if not _CODE:
        import importlib.metadata
        import importlib.util

        digest = hashlib.sha256()
        for package, nested, suffixes in (
            ("flexo", True, (".py",)),
            ("molsketch", False, (".py", ".js")),
        ):
            spec = importlib.util.find_spec(package)
            if spec is None or not spec.origin:
                continue
            here = Path(spec.origin).parent
            digest.update(
                _recorded(package, here, nested, suffixes) or _read_through(here, nested, suffixes)
            )
        for package in ("skia-python", "mini-racer"):
            with contextlib.suppress(importlib.metadata.PackageNotFoundError):
                digest.update(importlib.metadata.version(package).encode())
        _CODE.append(digest.hexdigest()[:16])
    return _CODE[0]


def _recorded(package: str, here: Path, nested: bool, suffixes: tuple[str, ...]) -> bytes | None:
    """What the installation of ``package`` recorded of its files with ``suffixes`` (in its
    folder ``here``, and those within it if ``nested``): each one's name and hash -- or None,
    where it recorded no hash of one, or none of them (a package installed to be worked on in
    place), or its record is not of the copy found at ``here``."""

    import importlib.metadata

    try:
        installed = importlib.metadata.distribution(package)
    except importlib.metadata.PackageNotFoundError:
        return None
    found = []
    for item in installed.files or ():
        parts = item.parts
        if not parts or parts[0] != package or item.suffix not in suffixes:
            continue
        if not nested and len(parts) != 2:
            continue
        if item.hash is None:
            return None
        found.append(f"{item.as_posix()}={item.hash.mode}:{item.hash.value}")
    if not found:
        return None
    with contextlib.suppress(OSError):
        if os.path.samefile(installed.locate_file(f"{package}/__init__.py"), here / "__init__.py"):
            return "\n".join(sorted(found)).encode("utf-8")
    return None


def _read_through(here: Path, nested: bool, suffixes: tuple[str, ...]) -> bytes:
    """Every file of ``here`` with ``suffixes`` (and those within it if ``nested``), read and
    hashed in turn."""

    digest = hashlib.sha256()
    names = here.rglob("*") if nested else here.glob("*")
    for path in sorted(name for name in names if name.suffix in suffixes):
        digest.update(path.read_bytes())
    return digest.digest()


_CONTENTS: dict[str, tuple[tuple[int, int, int, int], str]] = {}
"""What is in each file something kept is made from (``content``), with the file it was found
in: its device, inode, time saved and length."""


def content(path: str) -> str | None:
    """What is in the file at ``path``, hashed -- read once for as long as the disk says it is
    the same file, unchanged -- or None, for no file there. What is kept is kept by this, not by
    where a file is or when it was saved: a deck unpacked afresh (a copy of it, opened on another
    computer, its bundle put back in its place) has its files elsewhere, saved as they were
    unpacked, and what is in them is what it was."""

    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    same = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)
    where = os.path.abspath(path)
    known = _CONTENTS.get(where)
    if known is not None and known[0] == same:
        return known[1]
    try:
        with open(path, "rb") as handle:
            data = handle.read()  # (at once: a ribosome's 25 MB in one read, not a hundred)
    except OSError:
        return None
    held = hashlib.sha256(data).hexdigest()
    if len(_CONTENTS) >= 1024:
        _CONTENTS.clear()
    _CONTENTS[where] = (same, held)
    return held
