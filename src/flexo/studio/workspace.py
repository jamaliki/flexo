"""The studio's shared state: the documents open in a folder, and everyone editing them.

A ``Workspace`` holds each open document in memory with a version. Every change
-- from a page, from an agent, or from the file changing on disk -- arrives as
a new whole document together with the version it was made from; the
workspace merges it with whatever happened since (``flexo.studio.merge``),
tells everyone, and writes the file a moment later. So a person and an agent
can edit one deck at once, and an agent working on the files with its own
tools is seen live.

It also keeps who is where (presence), what has happened (activity), and the
pages that are listening (``Listener``).
"""

from __future__ import annotations

import contextlib
import copy
import functools
import hashlib
import inspect
import json
import os
import queue
import re
import secrets
import threading
import time
import traceback
import unicodedata
from collections import OrderedDict, deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from flexo.draft import GivenUp, given_up_when
from flexo.roundtrip import writing
from flexo.studio import Kind, code_allowed, folder_root, kinds, pictures
from flexo.studio.merge import merge3
from flexo.studio.plain import explain
from flexo.svg_resources import fonts_linked

HISTORY = 400
"""Versions of each document kept, for merging changes made from an older one."""
QUIET = 0.35
"""Seconds a document rests unchanged before it is written."""
PATIENCE = 3.0
"""Seconds a document changing without rest waits, at most, before it is written anyway."""
SHARED_QUIET = 1.5
SHARED_PATIENCE = 8.0
"""The same, in a folder a cloud service keeps (``cloud_service``): written less often while
it is typed in, each write is one the service has to carry to the others, and one fewer
written at the moment another Mac writes it too (two such are a conflict: see
``conflict_copies``)."""
RECENT = 40
"""How many of what each document's file held, the last times it was read or written, are
kept: the one both sides of a conflicting copy were made from is among them
(``Doc.take_conflict``)."""
RETRY = 5.0
"""Seconds before a document that could not be written is tried again."""
LOOK = (1.0, 30.0)
"""Seconds before a document whose file has gone is looked for again in the folder, at first
and at most: each look not finding it waits twice as long for the next."""
AGENT_TIMEOUT = 120.0
"""Seconds after its last action an agent stops being shown as present."""
DOING_TIMEOUT = 45.0
"""Seconds after its last action an agent's word on what it is doing is dropped."""
IGNORED = {
    ".git", ".venv", "venv", "env", "node_modules", "bower_components", "__pycache__", "build",
    "dist", "target", "site-packages", ".cache", ".ruff_cache", "Library", "Applications",
    "Pods", "DerivedData", ".Trash",
}
"""Folders no document is looked for in: tools' output, caches, and a home's own folders."""
_READS = frozenset(
    {"read", "structure-view", "structure-settings", "structure-fetch", "structure-name"}
)
"""Edits a page asks of a kind that only read the document (``Workspace.acting``)."""
DOCUMENT_SUFFIXES = (".yaml", ".yml", ".json")
CLAIM_LIMIT = 2_000_000
"""Bytes: a larger file is not read to find out what kind of document it is."""
WALK_LIMIT = 20_000
"""Files looked at, at most, when listing a folder's documents."""
SIZE_LIMIT = 2_000_000
"""Values in one document, at most (a YAML file of aliases can name billions)."""
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class Listener:
    """A page (or an agent) receiving the workspace's events."""

    def __init__(self, client: str, who: dict[str, Any]) -> None:
        self.client = client
        self.who = who
        self.events: queue.Queue[dict[str, Any] | None] = queue.Queue()


class Doc:
    """One open document: its content, its versions, and what is on disk."""

    def __init__(self, workspace: Workspace, name: str, path: Path, kind: Kind) -> None:
        self.workspace = workspace
        self.name = name
        self.path = path
        self.kind = kind
        self.lock = threading.RLock()
        self.exists = path.is_file()
        self.problem: str | None = None
        self.held = False
        """Whether the file on disk does not read (or is not a document its kind can show):
        nothing is written over it until it reads again, so what is written there is kept."""
        self.unread = False
        """Whether the file has not read since it was opened: its kind's editor has nothing
        to show but why, and nothing is changed or written until the file reads."""
        self.foreign: str | None = None
        """The kind of document the file on disk is, when another kind's: this one does not
        write over it."""
        try:
            self.document = kind.load(path) if self.exists else kind.new(path)
            _bounded(self.document)
            _shaped(kind, self.document)
        except Exception as error:
            if not self.exists:
                raise
            # A typo left in the file: it opens all the same, empty, saying where the typo is.
            self.document = {}
            self.held = self.unread = True
            self.problem = f"Can\u2019t read {name}: {_unread(error, path.name)}"
        self.version = 1
        self.history: OrderedDict[int, str] = OrderedDict({1: _dumps(self.document)})
        self.authors: OrderedDict[int, dict[str, Any]] = OrderedDict()
        """Who made each version in the history (not the one the file was opened at)."""
        self.saved = 1 if self.exists else 0
        self.changed_at = 0.0
        self.unsaved_since = 0.0
        self.retry_at = 0.0
        self.on_disk = copy.deepcopy(self.document) if self.exists and not self.unread else None
        self.recent: deque[tuple[str, bool]] = deque(maxlen=RECENT)
        """What the file held, the last times it was read or written (as ``_dumps``), and
        whether this studio wrote it."""
        if self.on_disk is not None:
            self.recent.append((_dumps(self.on_disk), False))
        self.opened_at = time.time()
        self.disk_text = _words(path) if self.exists else None
        self.disk_stamp = _stamp(path)
        self.depends: set[Path] = set()
        self.depend_stamps: dict[Path, float] = {}
        self.moved: str | None = None
        """Where its file went, as far as the studio can tell (renamed while it was away)."""
        self.gone = False
        """Whether its file has gone from where it was (moved, renamed, deleted) and is not
        found: what is made of it meanwhile is held, never written there but by a save (its
        person's choice), until the file is found again -- back, or elsewhere in the folder."""
        self.file = _file(path) if self.exists else None
        """The file it was last read from or written to, as the disk knows it (its device and
        inode): the very file, wherever in the folder it is moved."""
        self.look_at = 0.0
        self.look_every = LOOK[0]

    def info(self) -> dict[str, Any]:
        with self.lock:
            return {
                "file": self.name,
                "kind": self.kind.name,
                "title": self.kind.title,
                "exists": self.exists,
                "version": self.version,
                "saved": self.saved,
                "document": self.document,
                "problem": self.problem,
                "moved": self.moved,
                "gone": self.gone,
                "held": self.held,
                "unread": self.unread,
                "source": self.source(),
                "instance": self.workspace.instance,
            }

    def source(self) -> str | None:
        """The words of a file that has not read, for its person to put right where the
        studio shows it (not a file too large to show)."""

        # (Not read since opened, or not reading now: shown the same way, as one that does
        # not read.)
        text = self.disk_text if self.unread or self.held else None
        return text if text is not None and len(text) <= CLAIM_LIMIT else None

    def said(self) -> dict[str, Any]:
        """The ``problem`` event telling the pages what is wrong with the file (or that
        nothing is)."""

        with self.lock:
            return {
                "type": "problem",
                "file": self.name,
                "text": self.problem,
                "moved": self.moved,
                "gone": self.gone,
                "held": self.held,
                "unread": self.unread,
                "source": self.source(),
            }

    def update(
        self, document: Any, base: int, who: dict[str, Any], client: str = ""
    ) -> tuple[int, Any]:
        """Take a changed document made from version ``base``; return the version and
        document it became (merged with changes made since ``base``)."""

        wrong = _malformed(self.kind, document)
        if wrong:
            raise ValueError(f"{wrong}, so nothing was changed")
        if self.unread:
            # Made from nothing (the file never read): it would stand for the whole document.
            raise ValueError(
                f"{(self.problem or '').rstrip('.')}. Nothing was changed: put the file right, "
                "and it opens as soon as it reads."
            )
        notes: list = []
        with self.lock:
            if base == self.version:
                # Nothing to merge it with; put right by the kind all the same, as merged
                # documents are (an object written with two kinds' words never written so).
                merged = self._mended(document, notes, self.document)
            else:
                known = self.history.get(base)
                start = json.loads(known) if known is not None else self.document
                merged = self._mended(merge3(start, self.document, document, notes), notes, start)
            others = self.author_since(base, who)
            result = self._become(merged, who, client)
        self._tell(notes, who, client, others)
        return result

    def _mended(self, merged: Any, notes: list, base: Any) -> Any:
        """Two edits merged, put right by the kind where they meet badly (a line kept to a
        shape the other side deleted; a paragraph typed in kept beside the list the other
        side made of it): a kind that knows how has ``mended``, told the merge's ``notes``
        (and leaving out those it settled) and its ``base``."""

        mend = getattr(self.kind, "mended", None)
        return mend(merged, notes, base) if mend is not None else merged

    def author_since(self, base: int, who: dict[str, Any]) -> dict[str, Any] | None:
        """Who other than ``who`` last changed the document since version ``base``."""

        with self.lock:
            found = [
                author
                for version, author in self.authors.items()
                if version > base and author.get("id") != who.get("id")
            ]
        return found[-1] if found else None

    def _tell(
        self, notes: list, who: dict[str, Any], client: str, others: dict[str, Any] | None
    ) -> None:
        """Tell the pages what a merge (merge3's ``notes``) kept for someone: what one side
        deleted while the other was editing it, and words one side wrote anew while the
        other typed in them. Each is told to the pages of whoever it was kept for -- the
        window the change came from (``client``), or every other -- with who deleted or
        rewrote it: the change's maker (``who``), or the last of the others (``others``)."""

        told = []
        for note in notes:
            # Kept for the change's maker ("theirs" in the merge), against the others.
            mine = note.get("kept") == "theirs" or note.get("rewritten") == "ours"
            if mine and not client:
                continue  # made on disk: there is no page of its own to tell
            said = (
                {"kept": note["item"]}
                if "kept" in note
                else {"rewritten": note["words"], "typed": note["typed"]}
            )
            told.append({**said, "by": others if mine else who, "to": client if mine else None})
        if told:
            self.workspace.broadcast(
                {"type": "merged", "file": self.name, "client": client, "notes": told}
            )

    def _become(
        self, merged: Any, who: dict[str, Any], client: str, *, news: bool = True
    ) -> tuple[int, Any]:
        before = self.document
        if _dumps(merged) == _dumps(before):
            return self.version, self.document
        self.version += 1
        self.document = merged
        self.history[self.version] = _dumps(merged)
        self.authors[self.version] = who
        while len(self.history) > HISTORY:
            self.history.popitem(last=False)
        while len(self.authors) > HISTORY:
            self.authors.popitem(last=False)
        self.changed_at = time.monotonic()
        if self.saved >= self.version - 1:
            self.unsaved_since = self.changed_at
        self.workspace.changed(self, before, merged, who, client, news=news)
        return self.version, merged

    def base(self, version: int) -> Any:
        known = self.history.get(version)
        return json.loads(known) if known is not None else None

    # -- the file --

    def write(self, *, again: bool = False) -> bool:
        """Write the document if it has changed since last written (``again``: or if its
        file was moved or deleted); whether it did. A file that does not read is not
        written over; one gone from where it was is written there again only by a save
        (``again``), never by an edit -- a second copy beside the one moved."""

        with self.lock:
            if self.held:
                return False
            if self.saved >= self.version and (self.exists or not again):
                return False
            if self.gone and not again:
                return False
            other = self.workspace.kind_on_disk(self.path) if self.path.is_file() else None
            if other is not None and other != self.kind.name:
                # Another kind's document now (put right by hand, an agent's): kept as it is.
                self._foreign(other)
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside the file and moved over it: a write cut short (a full disk,
            # the app quitting) leaves the file as it was, not half of the new one.
            partial = self.path.with_name(
                f".{self.path.name}.{secrets.token_hex(4)}.saving{self.path.suffix}"
            )
            try:
                # Over the file's words as they are (a kind that can keeps its comments and
                # quoting where the document did not change) -- as the file it is, not the
                # one beside it it is written to first: a deletion undone puts back its words.
                with writing(str(self.path.resolve())):
                    if _keeps_words(type(self.kind)):
                        self.kind.save(partial, self.document, previous=self.disk_text)
                    else:
                        self.kind.save(partial, self.document)
                with contextlib.suppress(OSError):
                    os.chmod(partial, self.path.stat().st_mode & 0o7777)
                os.replace(partial, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    partial.unlink()
                raise
            self.disk_text = _words(self.path)
            self.disk_stamp = _stamp(self.path)
            self.file = _file(self.path)
            self.on_disk = copy.deepcopy(self.document)
            self.recent.append((_dumps(self.on_disk), True))
            self.saved = self.version
            self.exists = True
            self.gone, self.moved = False, None
            self.problem = None
            other = self.workspace.kind_on_disk(self.path)
            if other is not None and other != self.kind.name:
                # Written as asked (its words put right in a figure's Source, say), and
                # another kind's document now: it opens as that kind from here on.
                self._foreign(other)
            return True

    def _foreign(self, other: str) -> None:
        title = self.workspace.kinds[other].title.lower()
        self.held = True
        self.foreign = other
        self.problem = (
            f"{self.name} is a {title} now, not a {self.kind.title.lower()}: it opens again "
            f"as a {title}."
        )

    def mend(self, text: str, *, over: bool = False) -> None:
        """Put the file right by hand while it does not read: ``text`` is written as it is
        once this kind reads it (and no other kind claims it), then taken in; else nothing
        is written, and why is said. ``over``: written over it though it reads now (put
        right elsewhere meanwhile, its person keeping their own words after all)."""

        with self.lock:
            if not self.held and not over:
                raise ValueError(f"{self.name} reads as it is: edit it here instead.")
            other = self.workspace.kind_of_text(text, self.path.suffix)
            if other is not None and other != self.kind.name:
                title = self.workspace.kinds[other].title.lower()
                raise ValueError(f"That is a {title}, not a {self.kind.title.lower()}.")
            partial = self.path.with_name(
                f".{self.path.name}.{secrets.token_hex(4)}.saving{self.path.suffix}"
            )
            try:
                partial.write_text(text, encoding="utf-8")
                try:
                    found = self.kind.load(partial)
                    _bounded(found)
                    _shaped(self.kind, found)
                except Exception as error:
                    raise ValueError(
                        f"{self.name} still can\u2019t be read: {_unread(error, partial.name)}"
                    ) from None
                with contextlib.suppress(OSError):
                    os.chmod(partial, self.path.stat().st_mode & 0o7777)
                os.replace(partial, self.path)
            finally:
                with contextlib.suppress(OSError):
                    partial.unlink()
        self.workspace.reread(self)

    def reread(self) -> str | None:
        """Take in the file if something else changed it; what happened, if anything:
        ``changed`` (taken in: the file reads), or ``problem`` (it does not read, or is
        gone; ``problem`` says which)."""

        stamp = _stamp(self.path)
        if stamp == self.disk_stamp:
            return None
        with self.lock:
            self.disk_stamp = stamp
            if stamp == 0.0:
                if not self.exists:
                    return None
                # Moved or deleted: kept open, and followed wherever in the folder it went
                # (Workspace._follow_rename); not found, its edits are held, written there
                # again only by a save (not one that never read: there is nothing of it to
                # write), and it is looked for again now and then. Renamed -- a file of its
                # words, or its kind's that names it, beside it -- its pages offer the new one.
                self.exists = False
                self.gone = True
                self.held = self.unread
                self.look_at, self.look_every = time.monotonic() + LOOK[0], LOOK[0]
                self.moved = self.workspace._moved(self)
                self.problem = (
                    f"{self.name} was renamed {self.moved}."
                    if self.moved
                    else f"{self.name} was moved or deleted."
                    + ("" if self.unread else " Save (⌘S) to put it back.")
                )
                return "problem"
            text = _words(self.path)
            if text is None:
                return None
            self.moved = None
            self.gone = False  # back where it was (or made there): what is held is written there
            self.file = _file(self.path)
            returned = not self.exists
            if text == self.disk_text and not returned:
                return None
            try:
                found = self.kind.load(self.path)
                _bounded(found)
                _shaped(self.kind, found)
            except Exception as error:
                # Half written, or wrong: said, and the studio's copy kept, but nothing
                # written over the file until it reads again.
                problem = f"Can\u2019t read {self.name}: {_unread(error, self.path.name)}"
                self.disk_text = text
                self.exists = True
                self.held = True
                if problem == self.problem and not self.unread:
                    return None
                self.problem = problem
                return "problem"
            other = self.workspace.kind_on_disk(self.path)
            if other is not None and other != self.kind.name:
                # Another kind's document now: not taken in as this kind's, nor written over.
                self.disk_text = text
                self.exists = True
                self._foreign(other)
                return "problem"
            opened = self.unread  # read at last: what it holds is no change anyone made
            self.held = self.unread = False
            self.foreign = None
            self.problem = None
            base = self.on_disk if self.on_disk is not None else self.document
            notes: list = []
            merged = self._mended(merge3(base, self.document, found, notes), notes, base)
            self.on_disk = found
            self.recent.append((_dumps(found), False))
            self.disk_text = text
            self.exists = True
            # Changed on disk by something the studio doesn't know (an editor, a script):
            # in the activity, "Another app edited slide 3".
            who = self.workspace.agent_on(self.name) or {
                "id": "disk",
                "name": "Another app",
                "kind": "file",
            }
            unsaved = self.saved < self.version
            self._become(merged, who, "", news=not opened)
            self._tell(notes, who, "", None)
            if not unsaved and _dumps(merged) == _dumps(found):
                self.saved = self.version
            return "changed"


    def take_conflict(self, copy_path: Path, service: str) -> bool:
        """Take in a conflicting copy of the document's file, made by the cloud service
        keeping the folder when this computer and another wrote it at once
        (``conflict_copies``): what is in it is merged with what is here, as a change from
        another app is, from what both sides had before (see ``_before``). Whether it was:
        a copy that does not read, of another document, or whose file the service has not
        yet put the other side's in place of (the copy still all the file holds), is left as
        it is for now."""

        try:
            found = self.kind.load(copy_path)
            _bounded(found)
            _shaped(self.kind, found)
        except Exception:
            return False
        with self.lock:
            if self.unread or self.held or self.on_disk is None:
                return False
            if not _same_document(found, self.document):
                return False
            theirs, now = _dumps(found), _dumps(self.on_disk)
            if theirs == now:
                return False
            base = self._before(theirs, now)
            if base is None:
                return False
            notes: list = []
            merged = self._mended(merge3(base, self.document, found, notes), notes, base)
            who = {"id": "conflict", "name": service or "Another computer", "kind": "file"}
            self._become(merged, who, "")
        self._tell(notes, who, "", None)
        return True

    def _before(self, theirs: str, now: str) -> Any:
        """What both sides of a conflict had before they parted (``theirs``: the copy put
        aside; ``now``: what the file holds instead), of what this studio last read and
        wrote. The copy one it wrote itself (the other computer's kept in the file), they
        parted at one before that write: the nearest what the file holds now. Else, the
        nearest the copy's. None if nothing here is from before (the document opened at the
        copy's words)."""

        kept = list(self.recent)
        mine = [at for at, (text, wrote) in enumerate(kept) if wrote and text == theirs]
        if mine:
            kept, aim = kept[: mine[-1]], now
        else:
            aim = theirs
        if not kept:
            return None
        aimed = _lines(aim)
        # (The latest of those alike: the nearer they parted.)
        text, _ = max(reversed(kept), key=lambda entry: _likeness(_lines(entry[0]), aimed))
        return json.loads(text)


class Workspace:
    """A folder being edited: its open documents, who is here, and what happened."""

    def __init__(
        self,
        root: Path,
        *,
        kind: str | None = None,
        trusted: bool = True,
        offered: tuple[str, ...] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.trusted = trusted
        """Whether code the folder brings (a deck's plots) may run; a folder someone else
        made runs none until its person says they trust it."""
        self.on_trust: list[Any] = []
        self.kinds = kinds()
        self.offered = tuple(offered) if offered else tuple(self.kinds)
        """The kinds of document the page offers to make (an app for decks offers no
        figure of its own: figures are made on slides). Any kind still opens."""
        self.default_kind = kind
        self.token = secrets.token_urlsafe(24)
        self.instance = secrets.token_hex(6)
        """This run of the studio: versions count afresh in each, so a page that last heard
        from another takes the document in again."""
        self.lock = threading.RLock()
        self.docs: dict[str, Doc] = {}
        self.followed: dict[str, Doc] = {}
        """The documents followed from each name they had (their files moved, renamed)."""
        self.listeners: dict[str, Listener] = {}
        self.presence: dict[str, dict[str, Any]] = {}
        self.activity: deque[dict[str, Any]] = deque(maxlen=300)
        self.uploads: set[Path] = set()
        """Files this studio copied into the folder for a document (a picture dropped on a
        slide): one no document uses any more is taken away (``follow_uploads``), and any
        no document uses when it closes."""
        self.used_uploads: set[Path] = set()
        """The copies a document has used: one none uses now was undone or deleted."""
        self.set_aside: dict[Path, bytes] = {}
        """Copies taken out of the folder while the studio runs, kept to be put back if a
        document uses one again (its picture's adding redone)."""
        self.drawing = threading.Lock()
        self.latest: dict[str, int] = {}
        self.acts: dict[str, int] = {}
        """How many edits the pages have asked of each document's kind (``acting``)."""
        self._documents: dict[Path, tuple[float, str | None]] = {}
        self._unread: dict[Path, bool] = {}  # files of a kind that do not read as it has them
        self._stop = threading.Event()
        self.assistant = None
        self.on_close: list[Any] = []
        """What to do when the workspace closes (forget its agents' tools, say)."""
        self.cloud = cloud_service(self.root)
        """The service keeping the folder in step with other Macs (Dropbox, Google Drive,
        iCloud Drive…), if one is: its documents are written less often while typed in, and
        the copies it makes when two Macs write one at once are merged back in."""
        shared = self.cloud is not None
        self.quiet = SHARED_QUIET if shared else QUIET
        self.patience = SHARED_PATIENCE if shared else PATIENCE
        self._conflicts_at = 0.0
        self._looked: dict[Path, tuple[float, float]] = {}
        """The conflicting copies looked at and left as they were, and when (the copy's time
        and its document's file's): looked at again only once either changes."""
        self._taken: dict[Path, float] = {}
        """The conflicting copies merged in but not yet put aside, and their times: never
        merged again (from what the file holds now, they would take back edits since)."""
        self._ticker = threading.Thread(target=self._tick, name="studio-tick", daemon=True)
        self._ticker.start()

    def trust(self) -> None:
        """Let the folder's own code run from now on, and have every page draw again."""

        self.trusted = True
        for then in self.on_trust:
            with contextlib.suppress(Exception):
                then()
        self.broadcast({"type": "trusted"})

    @contextlib.contextmanager
    def running(self):
        """Around drawing and exporting: the folder's trust, and the folder itself, for
        a kind that runs a document's code or reads the files it names."""

        allowed, root = code_allowed.set(self.trusted), folder_root.set(self.root)
        try:
            yield
        finally:
            code_allowed.reset(allowed)
            folder_root.reset(root)

    def close(self) -> None:
        self._stop.set()
        if self.assistant is not None:
            with contextlib.suppress(Exception):
                self.assistant.stop()
        try:
            self.flush()
            self.tidy_uploads()
        finally:
            with self.lock:
                listeners = list(self.listeners.values())
            for listener in listeners:
                listener.events.put(None)  # the page's event stream ends
            for then in self.on_close:
                with contextlib.suppress(Exception):
                    then()

    def follow_uploads(self) -> None:
        """Keep the copies this studio made in step with its documents, as a document
        changes: a copy no document uses any more (its picture's adding undone, or the
        picture deleted) is taken out of the folder at once, and put back if one uses it
        again (redone). A copy no document has used yet is left be -- its document is about
        to -- and so is one any other file in the folder names (a document not open here)."""

        with self.lock:
            if not self.uploads:
                return
            docs = list(self.docs.values())
            uploads = set(self.uploads)
        written = [
            (doc.path.parent, json.dumps(doc.document, ensure_ascii=False)) for doc in docs
        ]
        for upload in sorted(uploads):
            if any(_names(upload, folder, text) for folder, text in written):
                self.used_uploads.add(upload)
                kept = self.set_aside.pop(upload, None)
                if kept is not None and not upload.exists():
                    with contextlib.suppress(OSError):
                        upload.parent.mkdir(parents=True, exist_ok=True)
                        upload.write_bytes(kept)
            elif upload in self.used_uploads and upload.is_file() and upload not in self.set_aside:
                if self._named_elsewhere(upload, {doc.path for doc in docs}):
                    continue
                with contextlib.suppress(OSError):
                    self.set_aside[upload] = upload.read_bytes()
                    upload.unlink()
                    if upload.parent.name == "assets" and not any(upload.parent.iterdir()):
                        upload.parent.rmdir()

    def _named_elsewhere(self, upload: Path, open_files: set[Path]) -> bool:
        """Whether a file in the folder other than an open document's names ``upload``."""

        for file in walk(self.root):
            if file in open_files or file.suffix.lower() not in WRITTEN:
                continue
            with contextlib.suppress(OSError, UnicodeDecodeError):
                if _names(upload, file.parent, file.read_text(encoding="utf-8")):
                    return True
        return False

    def tidy_uploads(self) -> None:
        """Take away the files this studio copied in that no document uses now (a picture
        dropped and then undone), as Keynote keeps no media a deck no longer shows. Only
        copies it made itself, never a file that was there before."""

        with self.lock:
            docs = list(self.docs.values())
            uploads, self.uploads = set(self.uploads), set()
            self.set_aside.clear()
        for upload in uploads:
            if not upload.is_file():
                continue
            used = False
            for doc in docs:
                written = json.dumps(doc.document, ensure_ascii=False) + (doc.disk_text or "")
                where = os.path.relpath(upload, doc.path.parent).replace(os.sep, "/")
                if where in written or upload.name in written:
                    used = True
                    break
            if not used:
                with contextlib.suppress(OSError):
                    upload.unlink()
                    if upload.parent.name == "assets" and not any(upload.parent.iterdir()):
                        upload.parent.rmdir()

    # -- files --

    def path(self, name: str) -> Path:
        """A file named relative to the folder; never one outside it."""

        target = (self.root / name).resolve()
        if target != self.root and self.root not in target.parents:
            raise PermissionError(f"{name} is outside {self.root}")
        return target

    def relative(self, path: Path) -> str:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise PermissionError(f"{path} is outside {self.root}")
        return resolved.relative_to(self.root).as_posix()

    def kind_of(self, path: Path, wanted: str | None = None) -> Kind:
        if path.is_file():
            found = self._claim(path)
            if found:
                return self.kinds[found]
        if wanted and wanted in self.kinds:
            return self.kinds[wanted]
        if self.default_kind and self.default_kind in self.kinds:
            return self.kinds[self.default_kind]
        return self.kinds["figure"]

    def kind_on_disk(self, path: Path) -> str | None:
        """The kind of document the file is now, if any kind's."""

        return self._claim(path)

    def kind_of_text(self, text: str, suffix: str) -> str | None:
        """The kind of document ``text`` is (written in a file ending ``suffix``), if any
        kind's: the kind that claims it, or, when it does not read, the kind its top-level
        keys say."""

        try:
            return self._claiming(_parsed(text, suffix))
        except Exception:
            return self._claiming(_outline(text))

    def _claiming(self, parsed: Any) -> str | None:
        # The figure kind claims broadly; every other kind is asked first.
        for kind in sorted(self.kinds.values(), key=lambda item: item.name == "figure"):
            with contextlib.suppress(Exception):
                if kind.claims(parsed):
                    return kind.name
        return None

    def _claim(self, path: Path) -> str | None:
        stamp = _stamp(path)
        cached = self._documents.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        found, unread = None, False
        try:
            if path.stat().st_size < CLAIM_LIMIT:
                text = path.read_text(encoding="utf-8")
                try:
                    parsed = _parsed(text, path.suffix)
                    found = self._claiming(parsed)
                    # Its kind's, but not as its kind has them (a deck whose slides are a number).
                    unread = bool(found and _malformed(self.kinds[found], parsed))
                except Exception:
                    # Anything a file can be (a typo mid-edit, a date that is no date, nesting
                    # too deep to read): not a document now, but one it was stays that kind,
                    # and one never read is the kind its keys say (a deck's `slides:` is there
                    # to see past a typo further down).
                    found = cached[1] if cached else self._claiming(_outline(text))
                    unread = found is not None
        except Exception:
            found = cached[1] if cached else None
        self._documents[path] = (stamp, found)
        self._unread[path] = unread
        return found

    def documents(self) -> list[dict[str, Any]]:
        """Every document in the folder a kind can edit."""

        found = []
        seen: set[str] = set()
        files = []
        for count, file in enumerate(_walk(self.root, depth=4)):
            if count >= WALK_LIMIT:
                break
            if file.suffix.lower() in DOCUMENT_SUFFIXES:
                files.append(file)
        # In the Finder's order: by name, capitals or not, numbers as numbers (Pathway before
        # Pathway 2, before Pathway 10).
        for file in sorted(files, key=lambda found: _finder_key(self.root, found)):
            try:
                name = self.relative(file)
            except PermissionError:
                continue  # a link to somewhere outside the folder
            if name in seen:
                continue
            kind = self._claim(file)
            if kind:
                seen.add(name)
                # One that does not read is said to be, as the themes' list says it.
                # One that does not read is said to be, as the themes' list says it; one open
                # that does not draw as written, so.
                open_doc = self.docs.get(name)
                said = (
                    {"unread": True}
                    if self._unread.get(file) or (open_doc is not None and open_doc.unread)
                    else {"faulty": True}
                    if getattr(open_doc, "faulty", False)
                    else {}
                )
                found.append({"file": name, "kind": kind, "title": self.kinds[kind].title, **said})
            if len(found) >= 300:
                break
        return found

    def open(self, name: str, kind: str | None = None, *, held: bool = False) -> Doc:
        """The document ``name``, opened if it is not (as ``kind``, if its file does not say).
        ``held``: a page holds it already (open before the studio started again) -- a file
        gone meanwhile is not made anew from its kind: it is moved or deleted, and the page's
        document is held, written there again by a save."""

        path = self.path(name)
        relative = unicodedata.normalize("NFC", self.relative(path))
        with self.lock:
            doc = self.docs.get(relative)
            if doc is None:
                # The same file by another spelling (decomposed accents, other capitals, as
                # macOS allows) is the document already open.
                doc = next((open_ for open_ in self.docs.values() if _same(open_.path, path)), None)
            followed = self.followed.get(relative)
            if doc is None and followed is not None and not path.exists():
                # A name a document was followed from (its file moved, renamed): a window not
                # yet told, or a request on its way, still names it so -- it is that document,
                # not a new one made where it was.
                doc = followed if self.docs.get(followed.name) is followed else None
            if doc is not None and doc.foreign and self._claim(doc.path) == doc.foreign:
                # Its file is another kind's document now: opened again as that kind (what
                # its old kind held was never written over it), and the pages told.
                relative, path = doc.name, doc.path
                del self.docs[relative]
                doc = None
                reopened = True
            else:
                reopened = False
            if doc is None:
                doc = Doc(self, relative, path, self.kind_of(path, kind))
                moved = self._moved(doc) if not doc.exists else None
                if (held or moved) and not doc.exists:
                    # Nothing of its kind's own is written there -- nor, renamed while the
                    # studio was away, anything under its old name but by a save.
                    doc.saved = doc.version
                    doc.gone = True
                    doc.moved = moved
                    doc.problem = (
                        f"{doc.name} is gone: renamed {doc.moved}?"
                        if doc.moved
                        else f"{doc.name} was moved or deleted. Save (⌘S) to put it back."
                    )
                self.docs[relative] = doc
                if doc.exists:
                    self._around(doc)
        if reopened:
            self.broadcast({"type": "reopened", "file": doc.name, "kind": doc.kind.name})
        return doc

    def _around(self, doc: Doc) -> None:
        """What is beside a document's file -- in its folder, and the folders in that --
        kept as it changes while the file is there: once it is gone, only a file that was not
        there before can be it, renamed or moved."""

        folder = doc.path.parent
        inner = getattr(doc, "around_folders", [])
        stamps = tuple(_stamp(place) for place in [folder, *inner])
        if getattr(doc, "around", None) is not None and stamps == doc.around_stamps:
            return
        names: set[str] = set()
        folders = []
        with contextlib.suppress(OSError):
            for path in sorted(folder.iterdir()):
                if path.is_dir() and not path.name.startswith(".") and len(folders) < 20:
                    folders.append(path)
                    with contextlib.suppress(OSError):
                        names.update(f"{path.name}/{one.name}" for one in path.iterdir())
                else:
                    names.add(path.name)
        doc.around, doc.around_folders = names, folders
        doc.around_stamps = tuple(_stamp(place) for place in [folder, *folders])

    def _moved(self, doc: Doc) -> str | None:
        """The file a document whose own has gone most likely is now: renamed, a file beside
        it of its words as last read; else, renamed while the studio was away, another file of
        its kind beside it that names it inside (a deck's id is the name of the file it was
        made in), if a kind says what names it (``identity``). Gone while the studio looked
        on, only a file that has just appeared beside it (or in a folder in its folder) can
        be it: one there already is another, that a deck's id may name too. Anywhere else in
        the studio's folder -- a folder made for it as it was moved (the Finder's New Folder
        with Selection), one it was moved up into, its own folder renamed -- only the very
        file it was can be it, of its words as last read: moved, not a copy."""

        identity = getattr(doc.kind, "identity", None)
        around = getattr(doc, "around", None)
        folder = doc.path.parent
        places = [folder, *(getattr(doc, "around_folders", []) if around is not None else [])]
        found = None
        for path in [one for place in places if place.is_dir() for one in sorted(place.iterdir())]:
            if path == doc.path or path.suffix != doc.path.suffix or not path.is_file():
                continue
            if self._conflicting(doc, path):
                continue
            name = path.name if path.parent == folder else f"{path.parent.name}/{path.name}"
            if around is not None and name in around:
                continue
            # Its words as last read, word for word: the file renamed as it was.
            if doc.disk_text is not None and _words(path) == doc.disk_text:
                return self.relative(path)
            if found is None and identity is not None and self._claim(path) == doc.kind.name:
                with contextlib.suppress(Exception):
                    if identity(doc.kind.load(path)) == doc.path.stem:
                        found = self.relative(path)
        if doc.file is not None and doc.disk_text is not None:
            for count, path in enumerate(walk(self.root, depth=8)):
                if count >= WALK_LIMIT:
                    break
                if path.suffix != doc.path.suffix or _file(path) != doc.file:
                    continue
                if self._conflicting(doc, path):
                    continue
                if _words(path) == doc.disk_text:
                    with contextlib.suppress(PermissionError):
                        return self.relative(path)
        return found

    def _conflicting(self, doc: Doc, path: Path) -> bool:
        """Whether a file is the copy of a document's the cloud service keeping the folder
        made when two computers wrote it at once: its file renamed so, it is not followed
        there, but merged back in (``take_conflicts``) once the other's is in its place."""

        return self.cloud is not None and is_conflict_copy(doc.path, path, self.cloud)

    def new(
        self, name: str, kind_name: str, data: Any = None, who: dict[str, Any] | None = None
    ) -> Doc:
        """Make a file of a kind -- its starting document, or ``data`` (a parsed
        document of that kind) -- and open it, as made by ``who``. An existing file is
        opened as it is."""

        path = self.path(name)
        kind = self.kinds.get(kind_name)
        if kind is None:
            raise ValueError(f"no kind {kind_name}; kinds are {', '.join(self.kinds)}")
        if path.exists():
            if data is not None:
                raise FileExistsError(f"{name} already exists")
            return self.open(name)
        adopt = getattr(kind, "adopt", None)
        document = kind.new(path) if data is None else adopt(data) if adopt else data
        path.parent.mkdir(parents=True, exist_ok=True)
        kind.save(path, document)
        doc = self.open(name, kind_name)
        # Said as the person who made it would say it ("You made a new figure"), the document
        # named by its name (beside it, where the activity is), not its file's.
        title = str(getattr(kind, "title", "") or kind_name).lower()
        self.record(
            who or {"id": "studio", "name": "Studio", "kind": "system"}, doc.name,
            f"made a new {title}",
        )
        self.broadcast({"type": "documents", "documents": self.documents()})
        return doc

    def rename(self, name: str, to: str, who: dict[str, Any] | None = None) -> str:
        """A document's file given a new name in the folder, as the File menu's Rename gives one:
        never over another file. Open, the document follows it as it follows a file renamed
        in the Finder (``_follow_rename``) -- its edits written first, so nothing waits under
        the old name. The name it has now."""

        source, target = self.path(name), self._new_name(to)
        moved = self.relative(target)
        if not source.is_file():
            raise FileNotFoundError(f"{name} is no longer in this folder.")
        # (Only its capitals changed, on a disk that does not tell them apart: the same file.)
        if target.exists() and _file(target) != _file(source):
            raise FileExistsError(_taken(target))
        doc = self.docs.get(name)
        if doc is not None and (doc.unread or doc.held or not doc.exists):
            raise ValueError(f"{name} can be renamed once it can be read.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if doc is None:
            os.rename(source, target)
        else:
            with doc.lock:
                self._write(doc)
                os.rename(source, target)
                doc.moved = moved
                if not self._follow_rename(doc):
                    self.reread(doc)
        self.record(who or {"id": "studio", "name": "Studio", "kind": "system"}, moved,
                    f"renamed \u201c{_shown(name)}\u201d to \u201c{_shown(moved)}\u201d")
        self.broadcast({"type": "documents", "documents": self.documents()})
        return moved

    def duplicate(self, name: str, to: str, who: dict[str, Any] | None = None) -> Doc:
        """A copy of a document, as the File menu's Duplicate makes one: its file as it is now (its
        edits written first), under the name ``to`` in the folder, opened."""

        source, target = self.path(name), self._new_name(to)
        if target.exists():
            raise FileExistsError(_taken(target))
        doc = self.docs.get(name)
        if doc is not None and doc.exists:
            self._write(doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        copy = self.open(self.relative(target))
        self.record(who or {"id": "studio", "name": "Studio", "kind": "system"}, copy.name,
                    f"made a copy of \u201c{_shown(name)}\u201d")
        self.broadcast({"type": "documents", "documents": self.documents()})
        return copy

    def _new_name(self, to: str) -> Path:
        """Where a document named ``to`` (in the folder) goes: a file a kind reads."""

        if not to.strip() or to.strip().endswith("/"):
            raise ValueError("Enter a name.")
        target = self.path(to.strip())
        if target.suffix.lower() not in DOCUMENT_SUFFIXES:
            raise ValueError("A document\u2019s file name ends in .yaml, .yml or .json.")
        return target

    def flush(self) -> None:
        for doc in list(self.docs.values()):
            self._write(doc)

    def _write(self, doc: Doc) -> None:
        """Write one document; one that cannot be written says why on its page, and is
        tried again later, while the others are written as usual. A change made to the
        file meanwhile is taken in first, not written over."""

        self.reread(doc)
        said = doc.problem
        try:
            wrote = doc.write()
        except Exception as error:
            problem = f"{doc.name} could not be saved: {_reason(error)}"
            doc.retry_at = time.monotonic() + RETRY
            if doc.problem != problem:
                doc.problem = problem
                self.broadcast(doc.said())
            return
        if wrote:
            self.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})
        if doc.foreign:
            # Another kind's file now: the pages are told, and it opens again as that kind.
            if doc.problem != said or wrote:
                self.broadcast(doc.said())
            self.open(doc.name)

    # -- changes --

    def changed(
        self, doc: Doc, before: Any, after: Any, who: dict[str, Any], client: str, *,
        news: bool = True,
    ) -> None:
        # A picture undone goes from the folder, and one redone is back before it is drawn.
        with contextlib.suppress(Exception):
            self.follow_uploads()
        self.broadcast(
            {
                "type": "doc",
                "file": doc.name,
                "version": doc.version,
                "document": after,
                "who": who,
                "client": client,
            }
        )
        # What the activity list says was done keeps its place: clicked, it goes to the slide
        # or object where it is now (moved, dragged to another slide), or says it is gone.
        follow = getattr(doc.kind, "follow", None)
        try:
            moved = follow(before, after) if follow else None
        except Exception:
            moved = None
        if moved is not None:
            with self.lock:
                followed = []
                for entry in self.activity:
                    if entry["file"] != doc.name or not entry["where"]:
                        continue
                    with contextlib.suppress(Exception):
                        where = moved(entry["where"])
                        if where is not entry["where"]:
                            entry["where"] = where
                            followed.append(entry)
            for entry in followed:
                self.broadcast({"type": "activity", "entry": entry, "followed": True})
        if not news:
            return
        describe = getattr(doc.kind, "describe", None)
        try:
            notes = describe(before, after) if describe else [{"text": "edited", "where": None}]
        except Exception:
            notes = [{"text": "edited", "where": None}]
        for note in notes[:6]:
            self.record(who, doc.name, note["text"], note.get("where"))
        if who.get("kind") == "agent" and notes:
            self.set_presence(who, doc.name, notes[-1].get("where"), None)

    def record(self, who: dict[str, Any], file: str, text: str, where: Any = None) -> None:
        now = time.time()
        with self.lock:
            last = self.activity[-1] if self.activity else None
            same = (
                last is not None
                and last["who"].get("id") == who.get("id")
                and last["file"] == file
                and last["where"] == where
                and now - last["at"] < 20
            )
            # Words typed in a run (a shape renamed letter by letter, saved as it goes) are
            # one change, said with its first words and its last: "renamed “Customer” to
            # “Shopper”", not a row for each save.
            run = _run_of(last["text"], text) if same and last else None
            if same and last and last["text"] == text:
                last["at"] = now
                last["count"] = last.get("count", 1) + 1
                entry = last
            elif run is not None and last:
                last["at"] = now
                last["text"] = run
                entry = last
            else:
                entry = {
                    "id": secrets.token_hex(6),
                    "at": now,
                    "who": who,
                    "file": file,
                    "text": text,
                    "where": where,
                }
                self.activity.append(entry)
        self.broadcast({"type": "activity", "entry": entry})

    # -- who is here --

    def set_presence(
        self,
        who: dict[str, Any],
        file: str | None,
        where: Any,
        doing: str | None,
        client: str = "",
    ) -> None:
        """Where ``who`` is: in a window of theirs (``client``) -- each window its own, gone
        with it, so a window reloaded or opened again leaves none of its last place behind (the
        pages show a person once, where their latest window is) -- or, an agent, as itself."""

        person = who.get("id") or who.get("name", "someone")
        key = f"{person}#{client}" if client else person
        with self.lock:
            entry = self.presence.get(key)
            if entry is None:
                # A colour of their own while they are here (in all their windows), the first
                # none of the others here has (given in the order they came): the pages show
                # them by it.
                entries = list(self.presence.values())
                theirs = [other for other in entries if _person(other) == person]
                used = {other.get("colour") for other in entries if _person(other) != person}
                free = next(n for n in range(len(used) + 1) if n not in used)
                colour = theirs[0].get("colour") if theirs else free
                entry = {"who": who, "colour": colour, "client": client}
            entry.update(who=who, file=file, where=where, at=time.time())
            if doing is not None:
                entry["doing"] = doing
            self.presence[key] = entry
        self.broadcast({"type": "presence", "presence": self.present()})

    def absent(self, who: dict[str, Any]) -> None:
        """``who`` is no longer here: an agent whose turn did nothing in the documents is
        not shown at work in them afterwards."""

        key = who.get("id") or who.get("name", "someone")
        with self.lock:
            gone = self.presence.pop(key, None)
        if gone is not None:
            self.broadcast({"type": "presence", "presence": self.present()})

    def agent_on(self, file: str) -> dict[str, Any] | None:
        """The agent most recently at work on ``file``, if one is (its edits on disk are its)."""

        now = time.time()
        with self.lock:
            agents = [
                entry
                for entry in self.presence.values()
                if entry["who"].get("kind") == "agent"
                and entry.get("file") == file
                and now - entry["at"] < 30
            ]
        return max(agents, key=lambda entry: entry["at"])["who"] if agents else None

    def present(self) -> list[dict[str, Any]]:
        """Who is here and where: each person once, where their latest window is."""

        with self.lock:
            latest: dict[str, dict[str, Any]] = {}
            for entry in self.presence.values():
                person = _person(entry)
                if person not in latest or entry.get("at", 0) >= latest[person].get("at", 0):
                    latest[person] = entry
            return [dict(entry) for entry in latest.values()]

    def focus_of_people(self) -> list[dict[str, Any]]:
        return [entry for entry in self.present() if entry["who"].get("kind") == "person"]

    # -- listeners --

    def listen(self, client: str, who: dict[str, Any]) -> Listener:
        listener = Listener(client, who)
        with self.lock:
            self.listeners[client] = listener
        return listener

    def leave(self, listener: Listener, *, grace: float = 0.0) -> None:
        """A window gone. Where a person is goes with their last window -- after ``grace``
        seconds, if one is back by then (a page reconnecting), never."""

        with self.lock:
            if self.listeners.get(listener.client) is listener:
                del self.listeners[listener.client]
        person = str(listener.who.get("id") or listener.client)
        if grace <= 0:
            self._gone(listener.client, person)
            return
        timer = threading.Timer(grace, self._gone, args=(listener.client, person))
        timer.daemon = True
        timer.start()

    def _gone(self, client: str, person: str) -> None:
        """The window ``client`` of ``person`` gone, unless it is back (a page reconnecting):
        where it was goes with it -- and where they were with no window named, with their last."""

        with self.lock:
            if client in self.listeners:
                return
            last = not any(other.who.get("id") == person for other in self.listeners.values())

            def theirs(entry: dict[str, Any]) -> bool:
                if entry.get("client"):
                    return entry["client"] == client
                return last and _person(entry) == person

            left = [key for key, entry in self.presence.items() if theirs(entry)]
            entries = [self.presence.pop(key) for key in left]
        self.broadcast({"type": "presence", "presence": self.present()})
        for entry in entries:
            self._abandoned(entry)

    def _abandoned(self, entry: dict[str, Any]) -> None:
        """What a person gone (their window closed, or lost) left half made where they were
        typing: an object they added and never wrote in -- which their window takes away when
        its typing ends -- goes, unless another is at it. A kind that knows its empty objects
        has ``abandoned(document, where)``."""

        where = entry.get("where")
        doc = self.docs.get(entry.get("file") or "")
        tidy = getattr(doc.kind, "abandoned", None) if doc is not None else None
        if tidy is None or not isinstance(where, dict) or not where.get("editing"):
            return
        spot = (where.get("page"), where.get("block"))
        with self.lock:
            others = [
                other.get("where")
                for other in self.presence.values()
                if other.get("file") == doc.name and isinstance(other.get("where"), dict)
                and other.get("where", {}).get("editing")
            ]
        if any((other.get("page"), other.get("block")) == spot for other in others):
            return
        with doc.lock:
            document, version = copy.deepcopy(doc.document), doc.version
        if not doc.held and not doc.unread and tidy(document, where):
            studio = {"id": "studio", "name": "Flexo Studio", "kind": "system"}
            with contextlib.suppress(ValueError):
                doc.update(document, version, studio)

    def depart(self, client: str) -> None:
        """A page that closes says so: whoever it was is gone from the others' windows at
        once, not when the next heartbeat finds its connection dead."""

        with self.lock:
            listener = self.listeners.get(client)
        if listener is not None:
            self.leave(listener)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self.lock:
            listeners = list(self.listeners.values())
        for listener in listeners:
            listener.events.put(event)

    # -- drawing --

    def acting(self, name: str, action: dict[str, Any]) -> None:
        """An edit asked of a document's kind (``/api/act``): one that changes it, not one
        that only reads it, gives way to it whatever drawing of the document yields."""

        edit = action.get("edit")
        if action.get("do") in _READS or (isinstance(edit, dict) and edit.get("do") in _READS):
            return
        self.acts[name] = self.acts.get(name, 0) + 1

    def draw(
        self, name: str, document: Any, version: int, known: dict[str, str], hints: dict[str, Any]
    ) -> dict[str, Any]:
        doc = self.open(name)
        # Each page counts its own drawings; an older one waiting its turn is dropped.
        client = f"{name}\0{hints.get('client', '')}"
        self.latest[client] = max(self.latest.get(client, 0), version)
        # One that may take a while (a deck settling its figures) yields: the page asks for
        # the next without waiting for it, and it is given up as soon as that is asked for --
        # or as soon as an edit is asked of the document, whose drawing that will be.
        acted = self.acts.get(name, 0)
        yields = (
            given_up_when(
                lambda: self.latest.get(client, 0) > version or self.acts.get(name, 0) != acted
            )
            if hints.get("yields")
            else contextlib.nullcontext()
        )
        with self.drawing:
            if version < self.latest[client]:
                return {"version": version, "stale": True}
            started = time.perf_counter()
            try:
                # The page has every bundled font; drawings name them rather than carry them.
                with fonts_linked(), self.running(), pictures.linked(self), yields:
                    drawing = doc.kind.draw(document, doc.path.parent, hints)
            except GivenUp:
                # (Given up for an edit asked of it, the page is told: that edit's drawing, or
                # its page, asks again.)
                edited = self.acts.get(name, 0) != acted
                return {"version": version, "stale": True, **({"edited": True} if edited else {})}
            except Exception as error:  # the page shows what went wrong, and stays up
                traceback.print_exc()
                return {
                    "version": version,
                    "pages": [],
                    "seconds": time.perf_counter() - started,
                    "messages": [
                        {
                            "text": self.named(explain(error), doc),
                            "severity": "error",
                            "where": "",
                            "page": "",
                            "code": "studio.crash",
                        }
                    ],
                }
            elapsed = time.perf_counter() - started
        doc.depends = {file.resolve() for file in drawing.files}
        # Whether it draws as written (a problem said in it), for the folder's list of documents.
        faulty = any(message.severity == "error" for message in drawing.messages)
        current = not drawing.unfinished and version >= doc.version
        if current and faulty != getattr(doc, "faulty", False):
            doc.faulty = faulty
            self.broadcast({"type": "documents", "documents": self.documents()})
        pages = []
        for page in drawing.pages:
            if page.pending:
                pages.append({"id": page.id, "label": page.label, "pending": True, **page.extra})
                continue
            digest = hashlib.sha1(page.svg.encode("utf-8")).hexdigest()[:16]
            entry: dict[str, Any] = {
                "id": page.id,
                "label": page.label,
                "steps": page.steps,
                "hash": digest,
                **page.extra,
            }
            if known.get(page.id) != digest:
                entry["svg"] = page.svg
            pages.append(entry)
        return {
            "version": version,
            "pages": pages,
            "info": drawing.info,
            "seconds": elapsed,
            "messages": [
                {**asdict(message), "text": self.named(message.text, doc)}
                for message in drawing.messages
            ],
            "unfinished": drawing.unfinished,
        }

    def named(self, text: str, doc: Doc) -> str:
        """Words that name a file by where it is on this machine, naming it from the
        document's folder instead (as the document itself names it)."""

        for folder in dict.fromkeys((doc.path.parent, self.root)):
            text = text.replace(f"{folder}{os.sep}", "").replace(str(folder), "the folder")
        return text

    def drawing_of(self, name: str, hints: dict[str, Any] | None = None) -> Any:
        """The document's current drawing, every page drawn (for an agent to look at)."""

        doc = self.open(name)
        with doc.lock:
            document = copy.deepcopy(doc.document)
        with self.drawing:
            for _ in range(200):
                with fonts_linked(), self.running():
                    drawing = doc.kind.draw(document, doc.path.parent, dict(hints or {}))
                if not drawing.unfinished:
                    return drawing
        return drawing

    # -- the clock --

    def _tick(self) -> None:
        while not self._stop.wait(0.25):
            try:
                self._step()
            except Exception:
                traceback.print_exc()

    def reread(self, doc: Doc) -> None:
        """Take in a document's file if something else changed it, and tell the pages."""

        if doc.exists and _stamp(doc.path):
            self._around(doc)
        happened = doc.reread()
        if happened is None and doc.gone and not doc.unread and time.monotonic() >= doc.look_at:
            # Gone and not found, looked for again now and then (less often as time goes
            # on): moved back into the folder, or found where it went after all, it follows.
            doc.look_every = min(doc.look_every * 2, LOOK[1])
            doc.look_at = time.monotonic() + doc.look_every
            moved, was = self._moved(doc), doc.moved
            if moved and moved != was:
                doc.moved = moved
                if self._follow_rename(doc):
                    return
                doc.moved = was
        if happened == "problem" and self._follow_rename(doc):
            return
        if happened == "problem":
            self.broadcast(doc.said())
            if doc.foreign:
                self.open(doc.name)  # as the kind it is now
        elif happened == "changed":
            # The pages' word on the file -- saved, or a problem with it gone -- is current.
            self.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})

    def _follow_rename(self, doc: Doc) -> bool:
        """A document whose file was renamed or moved as it was open -- a file of its words as
        last read, word for word, by Finder or an agent: beside it, or the very file elsewhere
        in the folder (see _moved) -- follows it, as a Mac document does: it is the new file
        from now on, its edits saved there (those held meanwhile too), and its pages told (a
        ``renamed`` event), never written again under its old name -- nor made anew there by
        a page still naming it so (``open``). Answers whether it did."""

        moved = doc.moved
        if not moved or doc.unread or doc.disk_text is None:
            return False
        path = self.path(moved)
        # (The document's lock first, then the folder's, as a document takes them.)
        with doc.lock, self.lock:
            if moved in self.docs or _words(path) != doc.disk_text:
                return False
            old = doc.name
            del self.docs[old]
            doc.name, doc.path = moved, path
            doc.exists, doc.held, doc.problem, doc.moved, doc.gone = True, False, None, None, False
            doc.disk_stamp = _stamp(path)
            doc.file = _file(path)
            self.docs[moved] = doc
            self.followed[old] = doc
            self.followed.pop(moved, None)
            for entry in self.presence.values():
                if entry.get("file") == old:
                    entry["file"] = moved
        self.broadcast({"type": "renamed", "file": old, "to": moved})
        self.broadcast({"type": "presence", "presence": self.present()})
        return True

    def _step(self) -> None:
        now = time.monotonic()
        if self.cloud and now >= self._conflicts_at:
            self._conflicts_at = now + 2.0
            self.take_conflicts()
        for doc in list(self.docs.values()):
            self.reread(doc)
            rested = now - doc.changed_at > self.quiet or now - doc.unsaved_since > self.patience
            if doc.saved < doc.version and rested and now >= doc.retry_at:
                self._write(doc)
            moved = False
            for file in list(doc.depends):
                stamp = _stamp(file)
                if doc.depend_stamps.get(file, stamp) != stamp:
                    moved = True
                doc.depend_stamps[file] = stamp
            if moved:
                self.broadcast({"type": "depends", "file": doc.name})
        now = time.time()
        with self.lock:
            agents = [
                (key, entry)
                for key, entry in self.presence.items()
                if entry["who"].get("kind") == "agent"
            ]
            gone = [key for key, entry in agents if entry["at"] < now - AGENT_TIMEOUT]
            quiet = [
                entry
                for _, entry in agents
                if entry.get("doing") and entry["at"] < now - DOING_TIMEOUT
            ]
            for key in gone:
                del self.presence[key]
            for entry in quiet:
                entry["doing"] = ""
        if gone or quiet:
            self.broadcast({"type": "presence", "presence": self.present()})


    def take_conflicts(self) -> None:
        """Merge back the conflicting copies the cloud service made of the open documents'
        files since they were opened, and say so (``Doc.take_conflict``)."""

        looked: dict[Path, tuple[float, float]] = {}
        taken: dict[Path, float] = {}
        for doc in list(self.docs.values()):
            if not doc.exists or doc.gone:
                continue
            found = conflict_copies(doc.path, self.cloud or "", since=doc.opened_at)
            if not found:
                continue
            self.reread(doc)  # what the file holds now, taken in first
            for path in found:
                stamps = (_stamp(path), doc.disk_stamp)
                if self._taken.get(path) == stamps[0]:
                    if not set_aside(path):
                        taken[path] = stamps[0]
                elif self._looked.get(path) == stamps:
                    looked[path] = stamps
                elif doc.take_conflict(path, self.cloud or ""):
                    if not set_aside(path):
                        taken[path] = stamps[0]
                    self.broadcast({"type": "conflict", "file": doc.name, "copy": path.name,
                                    "service": self.cloud})
                else:
                    looked[path] = stamps
        self._looked, self._taken = looked, taken


def _person(entry: dict[str, Any]) -> str:
    """Whose a presence entry is: its person's id (else name)."""

    who = entry.get("who") or {}
    return str(who.get("id") or who.get("name", "someone"))


def _walk(folder: Path, depth: int):
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(".") or entry.name in IGNORED:
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            # A linked folder is not followed: it may lead outside, or round in a loop.
            if depth > 0 and not entry.is_symlink():
                yield from _walk(entry, depth - 1)
        else:
            yield entry


WRITTEN = frozenset({".yaml", ".yml", ".json", ".py", ".md", ".txt", ".tex", ".html"})
"""Files a person writes that may name a picture beside them."""


def _names(upload: Path, folder: Path, text: str) -> bool:
    """Whether ``text`` (a document in ``folder``) names ``upload``."""

    where = os.path.relpath(upload, folder).replace(os.sep, "/")
    return where in text or upload.name in text


def walk(folder: Path, depth: int = 4):
    """The files under ``folder`` a person would call theirs (no build output, no caches)."""

    return _walk(folder, depth)


def _same(one: Path, other: Path) -> bool:
    try:
        return one.samefile(other)
    except OSError:
        return False


def _bounded(document: Any, limit: int = SIZE_LIMIT) -> None:
    """Refuse a document of more values than anyone writes: a YAML file of aliases to
    aliases names billions, and would take the app down when shown."""

    budget = limit
    stack = [document]
    while stack:
        item = stack.pop()
        budget -= 1
        if budget < 0:
            raise ValueError(
                "the document is too large to open (does it repeat itself with aliases?)"
            )
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _malformed(kind: Kind, document: Any) -> str | None:
    malformed = getattr(kind, "malformed", None)
    return malformed(document) if malformed else None


def _shaped(kind: Kind, document: Any) -> None:
    """Refuse a document its kind's editor cannot show (a deck whose slides are a number)."""

    wrong = _malformed(kind, document)
    if wrong:
        raise ValueError(wrong)


def _unread(error: BaseException, name: str) -> str:
    """Why a file does not read, in words that do not name it again."""

    said = explain(error)
    for lead in (f"{name}: ", f"{name}, "):
        if said.startswith(lead):
            return said[len(lead):]
    return f"it {said[len(name) + 1:]}" if said.startswith(f"{name} ") else said


def _taken(target: Path) -> str:
    return f"\u201c{target.name}\u201d is already used in this folder. Choose a different name."


def _shown(name: str) -> str:
    """A document's name as the studio shows it: its file's, without the extension."""

    return re.sub(r"(\.theme)?\.(ya?ml|json)$", "", Path(name).name, flags=re.IGNORECASE)


def _reason(error: Exception) -> str:
    if isinstance(error, OSError) and error.strerror:
        return error.strerror.lower()
    return str(error) or type(error).__name__


_RENAMED = re.compile(
    r"^(?P<head>.*?)\u201c(?P<was>[^\u201d]*)\u201d to \u201c(?P<now>[^\u201d]*)\u201d(?P<tail>.*)$"
)


def _run_of(before: str, after: str) -> str | None:
    """Two notes of words changed one after the other ("renamed “S” to “Sh”", then "renamed
    “Sh” to “Shoppe”") as one, from the first words to the last; None if they are not."""

    first, then = _RENAMED.match(before), _RENAMED.match(after)
    if not first or not then or first["now"] != then["was"]:
        return None
    if (first["head"], first["tail"]) != (then["head"], then["tail"]):
        return None
    return f"{first['head']}\u201c{first['was']}\u201d to \u201c{then['now']}\u201d{first['tail']}"


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime_ns / 1e9
    except OSError:
        return 0.0


def _file(path: Path) -> tuple[int, int] | None:
    """A file as the disk knows it, whatever it is named: moved within a disk, it is the same;
    written anew beside it and moved over it (as the studio and most editors save), another."""

    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_dev, found.st_ino


def _finder_key(root: Path, file: Path) -> list[Any]:
    """A file's place in a list as the Finder sorts one: folder by folder, each name without
    its extension first, letters whatever their case, runs of digits by their value."""

    try:
        parts = file.relative_to(root).parts
    except ValueError:
        parts = file.parts
    key: list[Any] = []
    for at, part in enumerate(parts):
        name = Path(part).stem if at == len(parts) - 1 else part
        # (Accents folded first, as the Finder does: "étude" among the e's.)
        decomposed = unicodedata.normalize("NFKD", name)
        plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        key.append([(0, int(run), "") if run.isdigit() else (1, 0, run.casefold())
                    for run in re.findall(r"\d+|\D+", plain)])
        key.append(part.casefold())
    return key


@functools.cache
def _keeps_words(kind: type) -> bool:
    """Whether a kind writes its document over the file's words as they were
    (its ``save`` takes ``previous``)."""

    try:
        return "previous" in inspect.signature(kind.save).parameters
    except (TypeError, ValueError):
        return False


def _words(path: Path) -> str | None:
    """A file's words, to tell when they change: a file not in UTF-8 too."""

    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _parsed(text: str, suffix: str) -> Any:
    return json.loads(text) if suffix.lower() == ".json" else yaml.load(text, _LOADER)


_YAML_KEY = re.compile(
    # A key at the start of a line: quoted, or plain words (not a list's item, a comment).
    r"""^(?:"((?:[^"\\\n]|\\.)*)"|'([^'\n]*)'|([^\s#'"\-?:,\[\]{}&*!|>%@`][^:#\n]*?))"""
    r"[ \t]*:(?:[ \t]|$)",
    re.M,
)
_JSON_TOKEN = re.compile(r'"((?:[^"\\\n]|\\.)*)"(\s*:)?|[{}\[\]]')


def _outline(text: str) -> dict[str, Any]:
    """The top-level keys a file's text still shows when it does not read (a typo further
    down), each standing for a value: enough for a kind to tell its own documents."""

    keys = [next(key for key in found.groups() if key is not None).strip()
            for found in _YAML_KEY.finditer(text)]
    if not keys:
        # JSON, or YAML written as one: the keys of the outermost mapping.
        depth = 0
        for found in _JSON_TOKEN.finditer(text):
            token = found.group(0)
            if token in "{[":
                depth += 1
            elif token in "}]":
                depth -= 1
            elif depth == 1 and found.group(2):
                keys.append(found.group(1))
    return {key: {} for key in keys}


def _dumps(document: Any) -> str:
    return json.dumps(document, sort_keys=True, ensure_ascii=False, default=str)


# -- folders kept by a cloud service --

_CLOUD_HOMES = (
    ("Library/Mobile Documents", "iCloud Drive"),
    ("Dropbox", "Dropbox"),
    ("Google Drive", "Google Drive"),
    ("My Drive", "Google Drive"),
    ("OneDrive", "OneDrive"),
    ("Box", "Box"),
)
_CLOUD_STORAGE = (
    ("Dropbox", "Dropbox"),
    ("GoogleDrive", "Google Drive"),
    ("OneDrive", "OneDrive"),
    ("Box", "Box"),
    ("pCloud", "pCloud"),
)


def cloud_service(folder: Path) -> str | None:
    """The service keeping ``folder`` in step with other computers, by where it is: a Mac's
    cloud services keep theirs in ~/Library/CloudStorage (Dropbox, Google Drive, OneDrive,
    Box), iCloud Drive in ~/Library/Mobile Documents, and older clients in a folder of their
    own name in the home folder (~/Dropbox). None for a folder of this computer's alone."""

    try:
        inside = folder.resolve().relative_to(Path.home().resolve())
    except (ValueError, OSError, RuntimeError):
        return None
    parts = inside.parts
    if len(parts) >= 3 and parts[:2] == ("Library", "CloudStorage"):
        named = (said for prefix, said in _CLOUD_STORAGE if parts[2].startswith(prefix))
        return next(named, "Cloud storage")
    joined = "/".join(parts)
    for home, said in _CLOUD_HOMES:
        # (~/Dropbox, or ~/Dropbox (Work) beside it.)
        if joined == home or joined.startswith(home + "/") or joined.startswith(home + " ("):
            return said
    return None


_CONFLICTED = re.compile(r"conflict", re.IGNORECASE)
_NUMBERED = re.compile(r" \d+")


def conflict_copies(path: Path, service: str = "", *, since: float = 0.0) -> list[Path]:
    """The copies of ``path`` a cloud service made beside it, since ``since`` (a time), when
    two computers wrote it at once (``is_conflict_copy``)."""

    try:
        siblings = sorted(path.parent.iterdir())
    except OSError:
        return []
    return [
        sibling
        for sibling in siblings
        if is_conflict_copy(path, sibling, service) and sibling.is_file()
        and _stamp(sibling) >= since
    ]


def is_conflict_copy(path: Path, other: Path, service: str = "") -> bool:
    """Whether ``other`` is named as a cloud service names the copy of ``path`` it keeps
    when two computers wrote it at once: the file's name with the word "conflict" added
    before its extension, as Dropbox ("talk (Ann's conflicted copy 2026-10-08).yaml"),
    Google Drive ("talk [Conflict].yaml") and Syncthing ("talk.sync-conflict-….yaml") name
    theirs -- and, in iCloud Drive, numbered as it numbers its ("talk 2.yaml")."""

    name, stem, suffix = other.name, path.stem, path.suffix
    if other == path or other.parent != path.parent:
        return False
    if not name.startswith(stem) or not name.endswith(suffix):
        return False
    middle = name[len(stem) : len(name) - len(suffix)]
    if not middle:
        return False
    numbered = service == "iCloud Drive" and _NUMBERED.fullmatch(middle) is not None
    return numbered or _CONFLICTED.search(middle) is not None


def _same_document(one: Any, other: Any) -> bool:
    """Whether two documents are copies of one (the same id, where they have one): a copy of
    another deck beside it is not merged into this one."""

    def identity(document: Any) -> Any:
        if not isinstance(document, dict):
            return None
        for key in ("deck", "figure", "theme"):
            head = document.get(key)
            if isinstance(head, dict) and head.get("id"):
                return (key, head["id"])
        return None

    mine, theirs = identity(one), identity(other)
    return mine is None or theirs is None or mine == theirs


def _lines(text: str) -> list[str]:
    """A document (as ``_dumps``) a line to each value, to be compared (``_likeness``)."""

    return json.dumps(json.loads(text), sort_keys=True, indent=0, ensure_ascii=False).splitlines()


def _likeness(one: list[str], other: list[str]) -> float:
    """How alike two documents' lines (``_lines``) are, from 0 to 1."""

    import difflib

    return difflib.SequenceMatcher(None, one, other, autojunk=False).ratio()


def set_aside(path: Path) -> bool:
    """Move a file merged into its document out of the folder (where the cloud service would
    keep handing it round) into this computer's own keeping: ~/Library/Application Support/
    flexo/merged on a Mac, else $XDG_DATA_HOME/flexo/merged. Whether it went."""

    home = Path.home()
    mac = home / "Library" / "Application Support"
    base = mac if mac.is_dir() else Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    keep = base / "flexo" / "merged" / time.strftime("%Y-%m-%d")
    try:
        keep.mkdir(parents=True, exist_ok=True)
        target = keep / path.name
        if target.exists():
            target = keep / f"{path.stem} {secrets.token_hex(3)}{path.suffix}"
        os.replace(path, target) if _same_device(path, keep) else _move(path, target)
    except OSError:
        return False
    return True


def _same_device(path: Path, folder: Path) -> bool:
    try:
        return path.stat().st_dev == folder.stat().st_dev
    except OSError:
        return False


def _move(path: Path, target: Path) -> None:
    import shutil

    shutil.copy2(path, target)
    path.unlink()
