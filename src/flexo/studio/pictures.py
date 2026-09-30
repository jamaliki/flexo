"""Photographs as the studio's page is shown them: a drawing names each by its address
instead of carrying it (a photo of 20 MB went to the page with every keystroke on its
slide), and the page is sent it once for each version, no larger than a screen needs."""

from __future__ import annotations

import contextlib
import io
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

LONGEST = 2400
"""Pixels along a photograph's longer side, at most, as the page is sent it."""
LIGHT = 1_500_000
"""Bytes: a smaller photograph is sent as it is."""
KEPT = 256_000_000
"""Bytes of photographs kept ready to send again."""

_KEPT: OrderedDict[tuple[str, int], tuple[bytes, str]] = OrderedDict()
_LOCK = threading.Lock()


@contextlib.contextmanager
def linked(workspace: Any):
    """While drawing for the page: photographs in the folder are named by address."""

    from flexo.artwork import picture_link

    def link(artwork: Any) -> str:
        try:
            name = workspace.relative(artwork.path)
        except PermissionError:
            return artwork.data_uri
        query = urlencode({"path": name, "v": artwork.stamp, "token": workspace.token})
        return f"/api/picture?{query}"

    token = picture_link.set(link)
    try:
        yield
    finally:
        picture_link.reset(token)


def shown(path: Path) -> tuple[bytes, str]:
    """The photograph at ``path`` as the page is sent it, and its media type."""

    stamp = path.stat().st_mtime_ns
    key = (str(path), stamp)
    with _LOCK:
        if key in _KEPT:
            _KEPT.move_to_end(key)
            return _KEPT[key]
        data = path.read_bytes()
        kind = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        if len(data) > LIGHT:
            data, kind = _smaller(data, kind)
        _KEPT[key] = (data, kind)
        while len(_KEPT) > 1 and sum(len(item[0]) for item in _KEPT.values()) > KEPT:
            _KEPT.popitem(last=False)
        return data, kind


def _smaller(data: bytes, kind: str) -> tuple[bytes, str]:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow comes with flexo's plots
        return data, kind
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((LONGEST, LONGEST))
            clear = image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info
            out = io.BytesIO()
            if clear:
                image.save(out, "PNG")
                return out.getvalue(), "image/png"
            image.convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception:  # a file Pillow cannot read: sent as it is
        return data, kind
