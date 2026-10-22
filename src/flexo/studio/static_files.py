"""The studio's own files -- its page's scripts and styles -- as a window keeps them.

A window of the studio loads a hundred modules, three megabytes of them, and every window and
every launch asked for each afresh (``no-store``). The page now names each by its version, a
hash of what is in it -- ``/static/studio/ui.js?v=...`` -- its styles in its links and its
modules in an import map, which names a module so wherever it is imported from (``./ui.js``
too). Asked for by its version, a file is kept by the window for good (``immutable``): changed,
it has another address. Asked for otherwise -- a style a script adds, the module the page starts
from, a page with no import map -- it is told by its hash (an ``ETag``), and asked for again
it is answered "not changed", without its bytes.

(Not compressed: on this machine alone, gzip costs more than the bytes it saves.)
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

KEPT = "max-age=31536000, immutable"
"""How a file asked for by its version is kept."""
ASKED = "no-cache"
"""And one asked for otherwise: kept, but asked after (by its ``ETag``) each time it is used."""

_VERSIONS: dict[str, tuple[tuple[int, int, int], str]] = {}
_LOCK = threading.Lock()
_STYLE = re.compile(r'(<link rel="stylesheet" href=")(/static/[^"?]+\.css)(")')


def version(path: Path) -> str:
    """A hash of what is in the file at ``path``: read again only once it is changed."""

    facts = path.stat()
    key = (facts.st_ino, facts.st_mtime_ns, facts.st_size)
    name = str(path)
    kept = _VERSIONS.get(name)
    if kept is not None and kept[0] == key:
        return kept[1]
    said = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    with _LOCK:
        _VERSIONS[name] = (key, said)
    return said


def _file(url: str, folders: dict[str, Path]) -> Path | None:
    for prefix, folder in folders.items():
        if url.startswith(prefix):
            target = folder / url.removeprefix(prefix)
            return target if target.is_file() else None
    return None


def versioned(page: str, folders: dict[str, Path], entry: str) -> str:
    """The HTML ``page`` with its styles named by their versions and an import map naming every
    module in ``folders`` (each an address's beginning and the folder it serves) by its
    version: all but ``entry``, the module the page starts from, which is named as it is."""

    def styled(found: re.Match[str]) -> str:
        target = _file(found.group(2), folders)
        if target is None:
            return found.group(0)
        return f"{found.group(1)}{found.group(2)}?v={version(target)}{found.group(3)}"

    page = _STYLE.sub(styled, page)
    imports: dict[str, str] = {}
    for prefix, folder in folders.items():
        for path in sorted(folder.rglob("*.js")):
            url = prefix + path.relative_to(folder).as_posix()
            if url != entry:
                imports[url] = f"{url}?v={version(path)}"
    said = json.dumps({"imports": imports}, separators=(",", ":")).replace("</", "<\\/")
    mark = '<script type="module"'
    at = page.find(mark)
    if at < 0:
        return page
    return f'{page[:at]}<script type="importmap">{said}</script>\n  {page[at:]}'
