"""Where a figure or deck may read the files it names: anywhere, unless the studio, for
a folder it serves, says that folder. A document someone sends then cannot carry a file
of yours (a picture, a structure) into what it draws and exports."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

folder_root: ContextVar[Path | None] = ContextVar("flexo_folder_root", default=None)
"""The folder a document is drawn in, while the studio draws or exports it."""


def outside(path: Path) -> bool:
    """Whether ``path`` lies outside the folder being served (never, outside the studio)."""

    root = folder_root.get()
    if root is None:
        return False
    resolved = path.expanduser().resolve()
    return resolved != root and root not in resolved.parents
