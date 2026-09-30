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


def _digest(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]


def _file(root: Path, port: int) -> Path:
    return _folder() / f"{_digest(root)}-{port}.json"


def register(root: Path, port: int, token: str) -> Path:
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = _file(root, port)
    data = {"root": str(root.resolve()), "port": port, "token": token, "pid": os.getpid()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def unregister(root: Path, port: int | None = None) -> None:
    """Take this process's studio on ``root`` (the one on ``port``, if given) off the list;
    another studio open on the same folder stays on it."""

    for path in _files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("pid") == os.getpid() and (port is None or data.get("port") == port):
            with contextlib.suppress(OSError):
                path.unlink()


def find(folder: Path) -> dict[str, Any] | None:
    """The live studio serving ``folder`` or a folder above it, if one runs (the one
    opened last, if several do)."""

    current = folder.resolve()
    for candidate in [current, *current.parents]:
        live = []
        for path in _files(candidate):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                stamp = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            if _alive(int(data.get("pid", 0))):
                live.append((stamp, data))
            else:
                with contextlib.suppress(OSError):
                    path.unlink()
        if live:
            return max(live, key=lambda item: item[0])[1]
    return None


def _files(root: Path) -> list[Path]:
    digest = _digest(root)
    # One file per studio on the folder; a studio from before kept the folder's alone.
    return [*sorted(_folder().glob(f"{digest}-*.json")), _folder() / f"{digest}.json"]


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
