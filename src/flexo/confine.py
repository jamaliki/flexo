"""Where a figure or deck may read the files it names: anywhere, unless the studio, for
a folder it serves, says that folder. A document someone sends then cannot carry a file
of yours (a picture, a structure) into what it draws and exports."""

from __future__ import annotations

import contextlib
import os
from contextvars import ContextVar
from pathlib import Path

folder_root: ContextVar[Path | None] = ContextVar("flexo_folder_root", default=None)
"""The folder a document is drawn in, while the studio draws or exports it."""


def outside(path: Path) -> bool:
    """Whether ``path`` lies outside the folder being served (never, outside the studio)."""

    root = folder_root.get()
    if root is None:
        return False
    # (Every link on the way followed, as Path.resolve does; compared as text, which is
    # what comparing the paths' parts comes to.)
    resolved = os.path.realpath(os.path.expanduser(os.fspath(path)))
    inside = os.fspath(root)
    return resolved != inside and not resolved.startswith(inside.rstrip(os.sep) + os.sep)


_SEEN: dict[tuple[str, str], tuple[tuple[int, int, int, int], bool]] = {}
"""What ``found`` last found of a file by its name: the file it was, and whether it was
outside the folder then."""

SEEN = 4096
"""How many files ``found`` remembers; past that it starts again."""


_ONCE: ContextVar[dict | None] = ContextVar("flexo_found_once", default=None)
"""What ``found`` found while a figure is laid out (``once``), by name and folder."""


@contextlib.contextmanager
def once():
    """While a figure is laid out or compiled: each file ``found`` is asked about looked at
    once, however often it is asked after -- the figure laid out with its files as they were
    when it started, not looking at them again for each of the ways it is tried. (Nested,
    the outermost holds.) Also a decorator."""

    if _ONCE.get() is not None:
        yield
        return
    token = _ONCE.set({})
    try:
        yield
    finally:
        _ONCE.reset(token)


def found(path: Path) -> tuple[os.stat_result | None, bool]:
    """The file at ``path`` as it is now (None: there is none) and whether it lies outside the
    folder being served, as ``outside`` says -- asked of the disk afresh (every link on the way
    followed) only when the file there is not the one last found under the same name, in the
    same folder: the same file, unchanged since. One look at the file, where ``outside`` takes
    one for every folder on the way, and a structure is asked after a hundred times while its
    figure is laid out.

    A file put there since -- another, or a link to one elsewhere -- is another file (another
    inode), looked at afresh: one outside the folder is still refused. Only the very file found
    inside before passes unasked: one a link elsewhere now reaches is that file, moved.

    While a figure is laid out (``once``) a file is looked at the first time only."""

    held = _ONCE.get()
    if held is None:
        return _found(path)
    root = folder_root.get()
    key = (os.fspath(path), None if root is None else os.fspath(root))
    if key not in held:
        held[key] = _found(path)
    return held[key]


def _found(path: Path) -> tuple[os.stat_result | None, bool]:
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None, False
    root = folder_root.get()
    if root is None:
        return stat, False
    name = os.fspath(path)
    if not os.path.isabs(name):  # (relative to wherever the process is: asked each time)
        return stat, outside(path)
    key = (name, os.fspath(root))
    same = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)
    known = _SEEN.get(key)
    if known is not None and known[0] == same:
        return stat, known[1]
    verdict = outside(path)
    if len(_SEEN) >= SEEN:
        _SEEN.clear()
    _SEEN[key] = (same, verdict)
    return stat, verdict
