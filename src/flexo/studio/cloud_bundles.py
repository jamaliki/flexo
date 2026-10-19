"""A bundle in a folder a cloud service keeps (Google Drive, iCloud Drive, Dropbox, OneDrive),
edited on two computers at once.

Each computer's studio keeps the bundle in step with its working folder
(``flexo.studio.bundles.Keeper``). Two computers saving it within moments of each other is a
conflict to the service: it keeps both, one as the bundle and the other beside it, named as
it names such copies (``is_copy_of``)::

    Google Drive    talk (1).flexo, talk (2).flexo
    iCloud Drive    talk 2.flexo
    Dropbox         talk (Ann's conflicted copy 2026-10-19).flexo
    OneDrive        talk-Anns-MacBook-Pro.flexo
    any             talk [Conflict].flexo, talk.sync-conflict-20261019-101500-ABCDEFG.flexo

Such a copy of the same bundle -- made at the same moment (its manifest's ``created``),
holding the same document -- is merged into it as a bundle saved on another computer is:
each document from the last version both had. To know which that is, each saving of a
bundle names itself and those it was made from (the manifest's ``revisions``), and each
computer keeps the versions of the bundle it has had (``History``): the newest of them the
copy was made from is the one both had. The copy merged and saved in the bundle, it is put
in the Trash (``put_away``): the folder holds one bundle again.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import os
import re
import secrets
import shutil
import time
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flexo.bundle import MOST_REVISIONS, SUFFIX

VERSIONS = 100
"""Versions of a bundle a computer keeps (its documents' words, its files' CRCs), to merge
another computer's copy from the one both had: every saving, the newest -- some minutes of
steady typing, hours of work."""

MOST_TEXT = 8_000_000
"""Bytes of a document kept to merge from, at most (a data file larger is not merged)."""


def revision() -> str:
    """A name for a saving of a bundle, never another's."""

    return secrets.token_hex(6)


@dataclass
class Version:
    """A version of a bundle this computer has had: read, written, or two merged."""

    heads: list[str]
    """The saving it is (one), the savings it merges (more), or none (a bundle saved by an
    older studio, which named none)."""
    texts: dict[str, str] = field(default_factory=dict)
    """Each document's words, by their digest (kept in the history's folder)."""
    entries: dict[str, tuple[int, int]] = field(default_factory=dict)
    """Each file: its CRC and size."""


class History:
    """The versions of a bundle this computer has had, newest last; which savings its working
    folder holds (``lineage``, newest first), and which the bundle on disk holds (``disk``)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.versions: list[Version] = []
        self.lineage: list[str] = []
        self.disk: list[str] = []

    # -- kept with the working folder's state --

    def load(self, state: Mapping[str, Any]) -> None:
        def names(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, str)][:MOST_REVISIONS]

        self.lineage = names(state.get("lineage"))
        self.disk = names(state.get("disk"))
        self.versions = []
        # (Each kept as what changed since the one before: most savings change one file.)
        texts: dict[str, str] = {}
        entries: dict[str, tuple[int, int]] = {}
        for item in state.get("versions") or []:
            if not isinstance(item, dict):
                continue
            try:
                texts = {**texts, **{str(name): str(at) for name, at in item["texts"].items()}}
                entries = {
                    **entries,
                    **{
                        str(name): (int(crc), int(size))
                        for name, (crc, size) in item["entries"].items()
                    },
                }
                for name in item.get("gone") or []:
                    entries.pop(name, None)
                for name in item.get("unread") or []:
                    texts.pop(name, None)
            except (KeyError, TypeError, ValueError, AttributeError):
                self.versions, texts, entries = [], {}, {}
                continue
            self.versions.append(Version(names(item.get("heads")), texts, entries))
        self.versions = self.versions[-VERSIONS:]

    def state(self) -> dict[str, Any]:
        kept = []
        texts: dict[str, str] = {}
        entries: dict[str, tuple[int, int]] = {}
        for item in self.versions:
            kept.append(
                {
                    "heads": item.heads,
                    "texts": {name: at for name, at in item.texts.items() if texts.get(name) != at},
                    "entries": {
                        name: entry
                        for name, entry in item.entries.items()
                        if entries.get(name) != entry
                    },
                    "gone": sorted(set(entries) - set(item.entries)),
                    "unread": sorted(set(texts) - set(item.texts)),
                }
            )
            texts, entries = item.texts, item.entries
        return {"lineage": self.lineage, "disk": self.disk, "versions": kept}

    def forget(self) -> None:
        self.versions, self.lineage, self.disk = [], [], []

    # -- versions --

    @property
    def latest(self) -> Version | None:
        return self.versions[-1] if self.versions else None

    def record(
        self,
        heads: Iterable[str],
        texts: Mapping[str, bytes],
        entries: Mapping[str, tuple[int, int]],
    ) -> Version:
        """A version this computer now has, kept (the oldest let go beyond ``VERSIONS``)."""

        made = Version(
            sorted(set(heads)),
            {name: self._keep(words) for name, words in texts.items() if len(words) <= MOST_TEXT},
            {name: (int(entry[0]), int(entry[1])) for name, entry in entries.items()},
        )
        if self.versions and self.versions[-1] == made:
            return self.versions[-1]
        self.versions.append(made)
        if len(self.versions) > VERSIONS:
            del self.versions[: len(self.versions) - VERSIONS]
            self._prune()
        return made

    def text(self, version: Version, name: str) -> bytes | None:
        digest = version.texts.get(name)
        if digest is None:
            return None
        try:
            return zlib.decompress((self.folder / digest).read_bytes())
        except (OSError, zlib.error):
            return None

    def took(self, revisions: Iterable[str]) -> None:
        """The working folder holds these savings too (a bundle taken in, a copy merged)."""

        self.lineage = woven(self.lineage, list(revisions))

    def wrote(self, saving: str) -> list[str]:
        """The savings a bundle written now holds: ``saving``, and all the folder held."""

        return [saving, *(name for name in self.lineage if name != saving)][:MOST_REVISIONS]

    # -- which version two had in common --

    def base_for(self, revisions: list[str]) -> Version | None:
        """The newest version here that a bundle naming ``revisions`` was made from: one whose
        savings it all holds -- else, from before savings were named, the newest such (a
        bundle first saved by this studio since); None if none is."""

        given = set(revisions)
        for version in reversed(self.versions):
            if version.heads and set(version.heads) <= given:
                return version
        for version in reversed(self.versions):
            if not version.heads:
                return version
        return None

    def nearest(self, name: str, words: bytes, among: list[Version]) -> Version | None:
        """Of ``among``, the version whose document ``name`` is most like ``words``: for a
        bundle that names no savings, the one it was most likely made from (the newest, of
        those alike)."""

        lines = words.decode("utf-8", "replace").splitlines()
        scores: dict[str, float] = {}
        best: tuple[float, Version] | None = None
        for version in reversed(among):
            digest = version.texts.get(name)
            if digest is None:
                continue
            if digest not in scores:
                kept = self.text(version, name)
                if kept is None:
                    continue
                other = kept.decode("utf-8", "replace").splitlines()
                scores[digest] = difflib.SequenceMatcher(None, other, lines).ratio()
            if best is None or scores[digest] > best[0]:
                best = (scores[digest], version)
        return best[1] if best is not None else None

    def had(self, name: str, words: bytes) -> bool:
        """Whether a version here had these words for document ``name``."""

        digest = _digest(words)
        return any(version.texts.get(name) == digest for version in self.versions)

    # -- the words kept --

    def _keep(self, words: bytes) -> str:
        digest = _digest(words)
        target = self.folder / digest
        if not target.exists():
            self.folder.mkdir(parents=True, exist_ok=True)
            partial = self.folder / f".{digest}.{secrets.token_hex(4)}"
            try:
                partial.write_bytes(zlib.compress(words, 6))
                os.replace(partial, target)
            finally:
                with contextlib.suppress(OSError):
                    partial.unlink()
        return digest

    def _prune(self) -> None:
        used = {digest for version in self.versions for digest in version.texts.values()}
        with contextlib.suppress(OSError):
            for entry in os.scandir(self.folder):
                if entry.name not in used and not entry.name.startswith("."):
                    with contextlib.suppress(OSError):
                        os.unlink(entry.path)


def _digest(words: bytes) -> str:
    return hashlib.sha256(words).hexdigest()[:32]


def woven(first: list[str], second: list[str]) -> list[str]:
    """Two lists of savings (newest first) as one: taken in turn from each, each once, so the
    newest of both stay when it is cut short."""

    made: list[str] = []
    seen: set[str] = set()
    for at in range(max(len(first), len(second))):
        for names in (first, second):
            if at < len(names) and names[at] not in seen:
                seen.add(names[at])
                made.append(names[at])
    return made[:MOST_REVISIONS]


# -- the copies a cloud service keeps -------------------------------------------------------

_CONFLICTED = re.compile(r"conflict", re.IGNORECASE)
_DRIVE = re.compile(r" \(\d{1,3}\)")
_ICLOUD = re.compile(r" \d{1,3}")
_ONEDRIVE = re.compile(r"-[^/]+")


def is_copy_of(path: Path, other: Path, service: str | None = None) -> bool:
    """Whether ``other``, beside the bundle ``path``, is named as ``service`` names the copy it
    keeps of a file two computers wrote at once (see the module's words): with "conflict" in
    its name, wherever it is; numbered, in Google Drive ("talk (1)") and iCloud Drive
    ("talk 2"); with a computer's name, in OneDrive ("talk-Anns-MacBook-Pro")."""

    if other.parent != path.parent or other.name == path.name:
        return False
    name, stem, suffix = other.name, path.name[: -len(path.suffix)], path.suffix
    if not suffix or not name.startswith(stem) or not name.lower().endswith(suffix.lower()):
        return False
    middle = name[len(stem) : len(name) - len(suffix)]
    if not middle:
        return False
    if _CONFLICTED.search(middle):
        return True
    pattern = {"Google Drive": _DRIVE, "iCloud Drive": _ICLOUD, "OneDrive": _ONEDRIVE}.get(
        service or ""
    )
    return pattern is not None and pattern.fullmatch(middle) is not None


def copies_beside(path: Path, service: str | None = None) -> list[Path]:
    """The bundles beside ``path`` named as copies of it (``is_copy_of``), by name."""

    found = []
    with contextlib.suppress(OSError):
        for entry in os.scandir(path.parent):
            if not entry.name.lower().endswith(SUFFIX) or entry.name == path.name:
                continue
            other = Path(entry.path)
            with contextlib.suppress(OSError):
                if is_copy_of(path, other, service) and entry.is_file():
                    found.append(other)
    return sorted(found)


# -- a copy put away ---------------------------------------------------------------------


def put_away(path: Path, keep: Path) -> str | None:
    """Move a copy merged into its bundle out of the folder, never deleting it: into the Trash,
    as the Finder does (on a Mac, through Foundation); else -- no Foundation, or a studio run
    apart from this computer's own (``FLEXO_BUNDLES`` set) -- into ``keep``, a folder of a
    day's copies. Where it went, for the person; None if it could not be moved."""

    if not os.environ.get("FLEXO_BUNDLES") and _trashed(path):
        return "the Trash"
    day = keep / time.strftime("%Y-%m-%d")
    try:
        day.mkdir(parents=True, exist_ok=True)
        target = day / path.name
        if target.exists():
            target = day / f"{path.stem} {secrets.token_hex(3)}{path.suffix}"
        try:
            os.rename(path, target)
        except OSError:
            # (Another disk: a cloud service's folder is one.)
            shutil.copy2(path, target)
            path.unlink()
    except OSError:
        return None
    home = str(Path.home())
    said = str(day)
    return "~" + said[len(home) :] if said.startswith(home + os.sep) else said


def _trashed(path: Path) -> bool:
    try:
        from Foundation import NSURL, NSFileManager  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        url = NSURL.fileURLWithPath_(str(path))
        done = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            url, None, None
        )
    except Exception:
        return False
    return bool(done[0] if isinstance(done, tuple) else done)
