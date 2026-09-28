"""Where running studios can be found: one small file per studio, readable only by
its owner, so an agent's ``flexo studio mcp`` joins the studio open on its folder."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _folder() -> Path:
    base = (
        os.environ.get("XDG_RUNTIME_DIR")
        or os.environ.get("XDG_CACHE_HOME")
        or str(Path.home() / ".cache")
    )
    return Path(base) / "flexo-studio" / "sessions"


def _file(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
    return _folder() / f"{digest}.json"


def register(root: Path, port: int, token: str) -> Path:
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = _file(root)
    data = {"root": str(root.resolve()), "port": port, "token": token, "pid": os.getpid()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def unregister(root: Path) -> None:
    path = _file(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        return


def find(folder: Path) -> dict[str, Any] | None:
    """The live studio serving ``folder`` or a folder above it, if one runs."""

    current = folder.resolve()
    for candidate in [current, *current.parents]:
        path = _file(candidate)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _alive(int(data.get("pid", 0))):
            return data
        with contextlib.suppress(OSError):
            path.unlink()
    return None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
