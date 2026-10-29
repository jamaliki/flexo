"""A bundle (``flexo.bundle``) open in the studio: edited as a folder, saved as one file.

The studio edits a folder. A bundle it opens is unpacked into a working folder of its own
-- in ``~/Library/Application Support/flexo/bundles`` (on Linux, the XDG data folder), one
for each bundle's place on this computer, never beside the file its person sees -- and
the studio serves that folder as any other. Opened again, a bundle unchanged since is not
unpacked again: its folder is as it was left.

A ``Keeper`` keeps the two in step while the studio runs. What changes in the folder (a
document saved, a picture dropped in, an agent's edit) is written back into the bundle a
moment later, once things are quiet -- beside it and moved over it, so a crash never leaves
half a bundle -- on a thread of its own, entries unchanged copied as they are: typing never
waits for it. What changes in the bundle (saved on another computer, carried here by
iCloud Drive or Dropbox) is taken into the folder, where the studio takes it in as it takes
in any file changed on disk -- a document this studio changed too merged with it first, from
the version both had. And the copy a cloud service keeps beside it when two computers save it
at once (``talk (1).flexo``) is merged in likewise, and put in the Trash: the folder holds one
bundle again (``flexo.studio.cloud_bundles``).

A bundle trusted to run its Python is trusted by its place, as a folder is: the browser's
studio remembers it in the working folder's state, the Mac app in its list of trusted folders.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import zlib
from pathlib import Path
from typing import Any

from flexo import bundle as bundles
from flexo.bundle import Bundle, BundleError
from flexo.studio import cloud_bundles as cloud

POLL = 0.4
"""Seconds between looks at the working folder and at the bundle."""
RESTING = 2.0
"""Seconds between looks once nothing has changed in the folder for ``RESTED`` seconds: a
studio left open is not woken for nothing. A document the studio writes wakes it at once
(``Keeper.nudge``)."""
RESTED = 10.0
QUIET = 0.8
PATIENCE = 4.0
"""Seconds the folder rests unchanged before the bundle is written, and the most it waits
while it keeps changing."""
SHARED_QUIET = 3.0
SHARED_PATIENCE = 20.0
"""The same, for a bundle a cloud service keeps (each write is one it carries to the others)."""
UNREAD_PATIENCE = 6.0
"""Seconds a bundle changed on disk that does not read (still arriving?) is waited for before
what is here is written over it."""
HOLD = 45.0
"""Seconds the folder waits to be written back, in a folder a cloud service keeps, once it
is merged with a bundle another computer saved without this one's last saving (which the
service keeps as a copy beside it): time for that computer, merging the copy, to save the
merge both want -- one saving, not two at once that conflict again."""
LOOK = 10.0
"""Seconds between looks beside the bundle for copies a cloud service made of it (and each
time its folder changes)."""
STATE = "bundle.json"


def support() -> Path:
    """Where the working folders are: ``FLEXO_BUNDLES``, else this computer's own keeping."""

    given = os.environ.get("FLEXO_BUNDLES")
    if given:
        return Path(given).expanduser()
    home = Path.home()
    mac = home / "Library" / "Application Support"
    base = mac if mac.is_dir() else Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    return base / "flexo" / "bundles"


def home_of(path: Path) -> Path:
    """The folder kept for the bundle at ``path``: one for each place a bundle is."""

    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    return support() / digest


def _stem(path: Path) -> str:
    stem = path.name[: -len(path.suffix)] if path.suffix else path.name
    return re.sub(r"[\x00/]", "-", stem).strip() or "Bundle"


def _facts(path: Path) -> tuple[int, int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_mtime_ns, found.st_size, found.st_ino


def _entries(opened: Bundle) -> dict[str, tuple[int, int]]:
    return {name: (opened.info(name).CRC, opened.info(name).file_size) for name in opened.names}


def _documentlike(name: str) -> bool:
    return name.lower().endswith(bundles.DOCUMENTS)


class Keeper:
    """A bundle and the folder it is edited in, kept in step (see the module's docs)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.home = home_of(self.path)
        self.root = self.home / _stem(self.path)
        self.lock = threading.RLock()
        self.workspace: Any = None
        self.document = ""
        self.kind = ""
        self.created = ""
        self.trusted = False
        self.replaced = False
        """Whether the bundle at its place is another than the one last opened there."""
        self.left: list[dict[str, str]] = []
        self.conflict: str | None = None
        """A bundle beside this one holding edits made here that never reached it, the bundle
        having changed meanwhile on another computer (said once, as it opens)."""
        self.notices: list[str] = []
        """What became of the copies a cloud service made beside it, as it opened (said once)."""
        self.synced: dict[str, tuple[int, int]] = {}
        """Each file of the bundle, as it was last read or written: its CRC and size."""
        self.stamps: dict[str, tuple[int, int]] = {}
        """Each file of the folder as it was then: its time (ns) and size."""
        self.texts: dict[str, bytes] = {}
        """Each document's words as they were then."""
        self.history = cloud.History(self.home / "versions")
        """The versions of the bundle this computer has had, to merge from the one two had."""
        self.known: bundles.Known = {}
        self.facts: tuple[int, int, int] | None = None
        """The bundle's file as it was last read or written."""
        self.keep_build = False
        self.problem: str | None = None
        self.changed_at = 0.0
        self.waiting_since = 0.0
        self.unread_since = 0.0
        self.written_at = 0.0
        self.held_until = 0.0
        """Until when the folder is not written back, merged with a bundle saved on another
        computer from an older version (see ``HOLD``)."""
        self.since = time.time()
        """When this studio began keeping it: a copy of a saving here made since is the cloud
        service's, not someone's own copy of the bundle."""
        self._last: dict[str, tuple[int, int]] | None = None
        self._looked: dict[str, tuple[Any, ...]] = {}
        """The copies beside the bundle looked at, as each was then (and the bundle on disk)."""
        self._kept: dict[str, tuple[int, int, int] | None] = {}
        """Copies left as they are (they could not be merged), as each was then: said once."""
        self._away: dict[Path, tuple[tuple[int, int, int] | None, bool]] = {}
        """Copies to put away once the bundle is written with them (as each was then, and
        whether it was merged here or held nothing new)."""
        self._lost: set[str] = set()
        """Savings here whose changes another computer's changed too, kept in a copy beside
        the bundle: that copy is never put away."""
        self._beside: tuple[int, int] | None = None
        self._looked_at: float | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.service = _service(self.path.parent)
        shared = self.service is not None
        self.quiet = SHARED_QUIET if shared else QUIET
        self.patience = SHARED_PATIENCE if shared else PATIENCE

    # -- opening --

    def open(self) -> Keeper:
        """Unpack the bundle into its working folder, or find the folder as it was left: the
        bundle unchanged since, it is not unpacked again; changed (on another computer), what
        changed is taken in, merged with edits made here that never reached it -- or, where
        both changed one thing, those edits are kept in a bundle beside it, as a cloud service
        keeps a conflicting copy. Then the copies a cloud service made beside it are merged
        (``_look_for_copies``)."""

        if not self.path.is_file():
            raise BundleError(f"{self.path.name} isn\u2019t there.")
        state = self._read_state()
        with Bundle(self.path) as opened:
            self.document = opened.document
            self.kind = opened.kind
            self.created = str(opened.manifest.get("created") or "")
            self.left = opened.left
            entries = _entries(opened)
            self.keep_build = any(name.startswith("build/") for name in entries)
            synced = {name: tuple(value) for name, value in (state.get("synced") or {}).items()}
            stamps = {name: tuple(value) for name, value in (state.get("stamps") or {}).items()}
            fresh = not self.root.is_dir() or not state or state.get("bundle") != str(self.path)
            # Another bundle altogether put in its place (made anew, not this one saved again:
            # its manifest says when it was first made)?
            made = state.get("created")
            self.replaced = bool(made) and bool(self.created) and made != self.created
            if state.get("bundle") == str(self.path) and not self.replaced:
                self.history.load(state)  # (the versions this computer had of it)
            if fresh:
                self._unpack(opened)
                self.history.lineage = []
                self._read_version(opened, entries)
            else:
                local = bundles.snapshot(self.root, keep_build=self.keep_build)
                mine = any(local.get(name) != stamps.get(name) for name in set(local) | set(stamps))
                theirs = entries != synced
                self.synced, self.stamps = synced, stamps  # type: ignore[assignment]
                if self.replaced:
                    if mine:
                        self.conflict = self._keep_aside()
                    self._unpack(opened)
                    self._read_version(opened, entries)
                elif theirs:
                    self._from_bundle(opened, entries, time.monotonic(), opening=mine)
                elif self.history.latest is None:
                    self._read_version(opened, entries)
            self.facts = _facts(self.path)
        # Trusted by its place -- unless what is there now is another bundle altogether.
        self.trusted = (
            bool(state.get("trusted"))
            and state.get("bundle") == str(self.path)
            and not self.replaced
        )
        self._seed()
        self._read_texts()
        self._write_state()
        with self.lock:
            self._look_for_copies(time.monotonic())
        return self

    def _unpack(self, opened: Bundle) -> None:
        """Unpack the whole bundle afresh: into a folder beside the working one, then put in
        its place."""

        self.home.mkdir(parents=True, exist_ok=True)
        fresh = self.home / f".unpacking-{secrets.token_hex(4)}"
        try:
            opened.extract(fresh)
            if self.root.exists():
                gone = self.home / f".old-{secrets.token_hex(4)}"
                os.replace(self.root, gone)
                shutil.rmtree(gone, ignore_errors=True)
            os.replace(fresh, self.root)
        finally:
            shutil.rmtree(fresh, ignore_errors=True)
        self.synced = _entries(opened)
        self.stamps = bundles.snapshot(self.root, keep_build=self.keep_build)
        self.known = {}

    def _read_version(self, opened: Bundle, entries: dict[str, tuple[int, int]]) -> None:
        """The bundle as it is read: a version this computer has had, and the one on disk."""

        revisions = opened.revisions
        self.history.record(revisions[:1], _documents(opened, entries), entries)
        self.history.took(revisions)
        self.history.disk = revisions

    def _keep_aside(self) -> str | None:
        """The working folder as it is, written as a bundle beside this one (``talk (edits
        not saved).flexo``): its name, or None if it could not be."""

        stem, count = _stem(self.path), 1
        while True:
            suffix = "" if count == 1 else f" {count}"
            target = self.path.with_name(f"{stem} (edits not saved{suffix}){bundles.SUFFIX}")
            if not target.exists():
                break
            count += 1
        try:
            files = {
                name: self.root / name for name in bundles.snapshot(self.root, keep_build=True)
            }
            bundles.write(
                target, files, bundles.manifest(self.document, self.kind, files=len(files))
            )
        except (OSError, BundleError):
            traceback.print_exc()
            return None
        return target.name

    # -- the studio --

    def attach(self, workspace: Any) -> None:
        """Keep the bundle in step with ``workspace`` (serving the working folder) until it
        closes; the person trusting it is remembered."""

        self.workspace = workspace
        workspace.bundle = self
        workspace.on_close.append(self.close)
        workspace.on_trust.append(self.remember_trust)
        self._thread = threading.Thread(
            target=self._run, name=f"bundle {self.path.name}", daemon=True
        )
        self._thread.start()

    def info(self) -> dict[str, Any]:
        """For the page: the bundle's name and place, its document, what its maker's document
        named that is not in it, and what is wrong (if anything)."""

        # (Not waiting on a bundle being written: what it says is as it is.)
        return {
            "name": self.path.name,
            "path": str(self.path),
            "stem": _stem(self.path),
            "document": self.document,
            "kind": self.kind,
            "left": self.left,
            "conflict": self.conflict,
            "notices": self.notices,
            "problem": self.problem,
        }

    def remember_trust(self) -> None:
        self.trusted = True
        with contextlib.suppress(OSError):
            self._write_state()

    def close(self) -> None:
        """Stop, writing back first whatever is not yet in the bundle."""

        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        with contextlib.suppress(Exception):
            self.save(force=False)

    # -- in step --

    def _run(self) -> None:
        while True:
            self._wake.wait(self._interval(time.monotonic()))
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self.step()
            except Exception:
                traceback.print_exc()

    def _interval(self, now: float) -> float:
        """How long until the next look: ``POLL``, or ``RESTING`` while nothing has changed
        for a while and nothing waits to be written, taken in or held."""

        waiting = self.waiting_since or self.unread_since or now < self.held_until or self._away
        return RESTING if not waiting and now - self.changed_at >= RESTED else POLL

    def nudge(self) -> None:
        """Look now: the studio has just written a file in the folder."""

        self._wake.set()

    def step(self, now: float | None = None) -> None:
        """One look: the bundle changed on disk is taken in, and copies a cloud service made
        beside it merged; the folder changed, and rested (or changing too long), is written
        back."""

        now = time.monotonic() if now is None else now
        with self.lock:
            facts = _facts(self.path)
            if facts != self.facts:
                self._bundle_changed(facts, now)
            if self._copies_due(now):
                self._look_for_copies(now)
            local = bundles.snapshot(self.root, keep_build=self.keep_build)
            if local != self._last:
                self._last = local
                self.changed_at = now
            if local == self.stamps:
                self.waiting_since = 0.0
                return
            if not self.waiting_since:
                self.waiting_since = now
            if self.unread_since and now - self.unread_since < UNREAD_PATIENCE:
                return
            if now < self.held_until:
                return
            rested = now - self.changed_at >= self.quiet
            if rested or now - self.waiting_since >= self.patience:
                self.save()

    def _bundle_changed(self, facts: tuple[int, int, int] | None, now: float) -> None:
        if facts is None:
            # Moved or deleted: followed if it was renamed beside itself; else it is written
            # there again with the next change. (Renamed as a cloud service names the copy it
            # keeps, it is not followed: the service is putting the other computer's saving in
            # its place, and the copy is merged once it has.)
            moved = self._renamed()
            if moved is not None and not cloud.is_copy_of(self.path, moved, self.service):
                self._follow(moved)
                return
            if moved is not None:
                if not self.unread_since:
                    self.unread_since = now
                if now - self.unread_since < UNREAD_PATIENCE:
                    return
            if self.problem is None:
                self._said(
                    problem=f"{self.path.name} was moved or deleted: it is saved there "
                    "again with your next change."
                )
            return
        try:
            with Bundle(self.path) as opened:
                entries = _entries(opened)
                if entries != self.synced:
                    taken = self._from_bundle(opened, entries, now)
                    if taken:
                        self._said(taken=taken)
                elif opened.revisions and opened.revisions != self.history.disk:
                    # (Saved again elsewhere, as it is here: the savings it holds are these.)
                    self._took_saving(opened.revisions)
        except BundleError as error:
            # Still arriving (a cloud service mid-copy)? Waited for a moment, then written over.
            if not self.unread_since:
                self.unread_since = now
                self._said(problem=str(error))
            if now - self.unread_since < UNREAD_PATIENCE:
                return
        self.unread_since = 0.0
        self.facts = facts
        if self.problem is not None:
            self._said(problem=None)
        self._write_state()

    def _took_saving(self, revisions: list[str]) -> None:
        latest = self.history.latest
        self.history.took(revisions)
        self.history.disk = revisions
        if latest is not None and set(latest.heads) <= set(revisions):
            self.held_until = 0.0

    def _from_bundle(
        self,
        opened: Bundle,
        entries: dict[str, tuple[int, int]],
        now: float,
        *,
        opening: bool = False,
    ) -> list[str]:
        """Take a bundle changed elsewhere into the folder: each file changed there since the
        version both had written here -- over this one if it is unchanged here, else, a
        document, merged with it from that version -- and each it no longer has taken away if
        unchanged here. The names changed.

        Saved from what this computer last saved or took in, the version both had is that;
        saved from an older one (this computer's saving kept by a cloud service as a copy
        beside it, or lost), it is the newest both had, and where both changed one thing the
        bundle's change stands, what was here kept in that copy, or in a bundle beside it
        (``_keep_aside``); in a folder a cloud service keeps, the folder then waits (``HOLD``)
        for the other computer to save the merge both want. As it opens, edits made here that
        never reached it are merged likewise. One that names no savings (saved by an older
        studio, packed again by hand) is taken as made from the version here it is most like
        (``_most_like``): what was saved here since, it never had, and did not undo."""

        revisions = opened.revisions
        latest = self.history.latest
        base, apart = latest, False
        if (
            revisions
            and latest is not None
            and latest.heads
            and not set(latest.heads) <= set(revisions)
            and revisions[0] not in self.history.lineage
        ):
            found = self.history.base_for(revisions)
            if found is not None and found is not latest:
                base, apart = found, True
        elif not revisions and latest is not None:
            base = self._most_like(opened) or latest
        theirs = _Side(entries, _reader(opened))
        before = self._folder_side()
        outcome, unclean = self._absorb(self._base_side(base), before, theirs)
        if unclean and (apart or opening):
            kept = self._copy_of(latest.heads) if apart and latest is not None else None
            if kept is not None:
                self._lost.update(latest.heads if latest is not None else ())
                aside = kept.name
            else:
                aside = self._keep_aside()
            self.conflict = aside
            if aside and not opening:
                self._notice(
                    f"{self.path.name} was saved on another computer, changing the same "
                    "things as this one did: the other computer\u2019s changes are in place, "
                    f"and this one\u2019s are kept in \u201c{aside}\u201d, beside it."
                )
            # (The bundle's stands where both changed one thing.)
            outcome.update({name: "theirs" for name in unclean if outcome.get(name) == "ours"})
        taken = self._apply(outcome, opened)
        self._settle(entries, outcome, before)
        if apart and latest is not None and base is not None:
            self._record_merged(base, latest, theirs, revisions, flip=False)
        else:
            self.history.record(revisions[:1], _documents(opened, entries), entries)
        self.history.took(revisions)
        self.history.disk = revisions
        self.held_until = now + HOLD if apart and self.service else 0.0
        self._seed()
        return taken

    def _most_like(self, opened: Bundle) -> cloud.Version | None:
        """The version a bundle that names no savings -- saved by an older studio, packed again
        by hand -- was most likely made from: the one here whose document its own is nearest
        (``History.nearest``), what was saved here since it was made being no change of its.
        None if its document is word for word one this computer had (put back, or unchanged),
        or can't be read."""

        try:
            words = opened.read(self.document, most=bundles.MOST_MANIFEST * 50)
        except (KeyError, BundleError, OSError):
            return None
        if self.history.had(self.document, words):
            return None
        return self.history.nearest(self.document, words, self.history.versions)

    def _absorb(
        self, base: _Side, ours: _Side, theirs: _Side, *, flip: bool = False
    ) -> tuple[dict[str, str | bytes | None], set[str]]:
        """What becomes of each file, ``theirs`` (another computer's version) taken into
        ``ours`` from ``base``, the version both had: ``"theirs"``, taken as it is there;
        words, a document merged; None, taken away; ``"ours"``, kept as it is here -- only
        those not already alike. And those changed both ways where a merge loses one side's
        change (a picture changed on both, a document both changed one thing in, a document
        that can't be merged): what becomes of them keeps one side's (the merged document,
        ``theirs``'s picture -- or ``ours``'s with ``flip``)."""

        outcome: dict[str, str | bytes | None] = {}
        unclean: set[str] = set()
        for name in sorted(set(base.entries) | set(theirs.entries)):
            was, other = base.entries.get(name), theirs.entries.get(name)
            if other == was:
                continue  # not changed there
            mine = ours.entry(name)
            if mine == other:
                continue  # (alike already)
            if mine == was:
                outcome[name] = "theirs" if other is not None else None
            elif other is None:
                outcome[name] = "ours"  # changed here, taken away there: kept
            elif mine is None:
                outcome[name] = "theirs"  # taken away here, changed there: kept
            elif _documentlike(name) and was is not None:
                merged, clashed = self._merged(
                    name, base.text(name), ours.text(name), theirs.text(name), flip=flip
                )
                outcome[name] = merged if merged is not None else "ours"
                if merged is None or clashed:
                    unclean.add(name)
            else:
                outcome[name] = "ours" if flip else "theirs"
                unclean.add(name)
        return outcome, unclean

    def _apply(self, outcome: dict[str, str | bytes | None], source: Bundle) -> list[str]:
        """Each file's outcome (``_absorb``) made in the folder: the names changed."""

        changed: list[str] = []
        merging = getattr(self.workspace, "merging", None)
        for name, made in outcome.items():
            target = self.root.joinpath(*name.split("/"))
            if made == "ours":
                continue
            if merging is not None and made is not None and _documentlike(name):
                merging(target)  # (taken in from what the studio has, as merged here)
            if made == "theirs":
                source.extract(self.root, [name], replace=True)
            elif isinstance(made, bytes):
                target.parent.mkdir(parents=True, exist_ok=True)
                _replace(target, made, self.root)
            else:
                with contextlib.suppress(OSError):
                    target.unlink()
            changed.append(name)
        return changed

    def _settle(
        self,
        entries: dict[str, tuple[int, int]],
        outcome: dict[str, str | bytes | None],
        before: _Side,
    ) -> None:
        """The folder, a bundle taken into it, in step with that bundle: each file as the
        bundle has it known unchanged since; any other, to be written back."""

        now_here = bundles.snapshot(self.root, keep_build=True)
        stamps: dict[str, tuple[int, int]] = {}
        for name, stamp in now_here.items():
            made = outcome.get(name, "")
            if made == "theirs" or (made == "" and before.entry(name) == entries.get(name)):
                stamps[name] = stamp
        self.stamps = stamps
        self.synced = dict(entries)

    def _merged(
        self,
        name: str,
        base: bytes | None,
        ours: bytes | None,
        theirs: bytes | None,
        *,
        flip: bool = False,
    ) -> tuple[bytes | None, bool]:
        """A document changed both here and elsewhere since both last had it, merged by its
        kind as the studio merges two people's edits -- ``theirs`` standing where both changed
        one thing (``ours``, with ``flip``), in ``ours``'s words: its words (None if it can't
        be), and whether both changed one thing (words one wrote anew as the other typed in
        them, kept together, among them)."""

        from flexo.studio import kinds as all_kinds
        from flexo.studio.merge import clashes, merge3

        if base is None or ours is None or theirs is None:
            return None, False
        kinds = all_kinds()
        scratch = self.home / f".merging-{secrets.token_hex(4)}"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            suffix = Path(name).suffix
            versions = {}
            for label, data in (("base", base), ("ours", ours), ("theirs", theirs)):
                file = scratch / f"{label}{suffix}"
                file.write_bytes(data)
                versions[label] = file
            parsed = bundles._parsed(theirs.decode("utf-8"), suffix)
            kind = next(
                (
                    kind
                    for kind in sorted(kinds.values(), key=lambda k: k.name == "figure")
                    if _claims(kind, parsed)
                ),
                None,
            )
            if kind is None:
                return None, False
            loaded = {label: kind.load(file) for label, file in versions.items()}
            notes: list = []
            first, second = ("theirs", "ours") if flip else ("ours", "theirs")
            with clashes() as clashed:
                merged = merge3(loaded["base"], loaded[first], loaded[second], notes)
                clashed += [note for note in notes if "rewritten" in note]
                mend = getattr(kind, "mended", None)
                if mend is not None:
                    merged = mend(merged, notes, loaded["base"])
            out = scratch / f"merged{suffix}"
            try:
                kind.save(out, merged, previous=ours.decode("utf-8"))
            except TypeError:
                kind.save(out, merged)
            return out.read_bytes(), bool(clashed)
        except Exception:
            traceback.print_exc()
            return None, False
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    # -- the versions two computers had --

    def _base_side(self, version: cloud.Version | None) -> _Side:
        """A version this computer had, as one side of a merge; with none kept (a working
        folder left by an older studio), the bundle as last read or written, its words not
        known."""

        if version is None:
            return _Side(dict(self.synced), lambda name: None)
        return _Side(version.entries, lambda name: self.history.text(version, name))

    def _folder_side(self) -> _Side:
        """The working folder as it is, as one side of a merge: each file's CRC (as the bundle
        has it, if unchanged since; else read) and its words."""

        local = bundles.snapshot(self.root, keep_build=True)
        found: dict[str, tuple[int, int] | None] = {}

        def entry(name: str) -> tuple[int, int] | None:
            if name not in found:
                stamp = local.get(name)
                if stamp is None:
                    found[name] = None
                elif stamp == self.stamps.get(name) and name in self.synced:
                    found[name] = self.synced[name]
                else:
                    try:
                        found[name] = (bundles._crc(self._file(name)), stamp[1])
                    except OSError:
                        found[name] = None
            return found[name]

        def text(name: str) -> bytes | None:
            try:
                return self._file(name).read_bytes()
            except OSError:
                return None

        return _Side({}, text, entry)

    def _record_merged(
        self,
        base: cloud.Version,
        latest: cloud.Version,
        theirs: _Side,
        revisions: list[str],
        *,
        flip: bool,
    ) -> None:
        """The version two computers both come to: this one's latest and another's, merged
        from the one both had -- what the other, merging this one's, makes too -- kept to
        merge their next from (the edits here not yet saved left out)."""

        ours = _Side(
            latest.entries, lambda name: self.history.text(latest, name), latest.entries.get
        )
        outcome, _ = self._absorb(self._base_side(base), ours, theirs, flip=flip)
        entries = dict(latest.entries)
        texts = {
            name: words
            for name in latest.texts
            if (words := self.history.text(latest, name)) is not None
        }
        for name, made in outcome.items():
            if made == "theirs":
                entries[name] = theirs.entries[name]
                if _documentlike(name) and (words := theirs.text(name)) is not None:
                    texts[name] = words
            elif isinstance(made, bytes):
                entries[name] = (zlib.crc32(made), len(made))
                texts[name] = made
            elif made is None:
                entries.pop(name, None)
                texts.pop(name, None)
        self.history.record([*latest.heads, *revisions[:1]], texts, entries)

    # -- copies a cloud service made beside the bundle --

    def _copies_due(self, now: float) -> bool:
        try:
            found = os.stat(self.path.parent)
        except OSError:
            return False
        beside = (found.st_mtime_ns, found.st_ino)
        if beside != self._beside:
            return True
        return self._looked_at is None or abs(now - self._looked_at) >= LOOK

    def _look_for_copies(self, now: float) -> None:
        """Merge each copy of the bundle a cloud service made beside it, when two computers
        saved it at once (``flexo.studio.cloud_bundles``): its changes taken in as a bundle
        saved on another computer, from the version both had, the bundle written with them,
        and the copy put in the Trash. One that changes the same things as edits here, or
        that can't be told apart from them, is left as it is, and said."""

        with contextlib.suppress(OSError):
            found = os.stat(self.path.parent)
            self._beside = (found.st_mtime_ns, found.st_ino)
        self._looked_at = now
        if not self.path.is_file():
            return  # (being put back in its place: looked at once it is)
        copies = cloud.copies_beside(self.path, self.service)
        for gone in set(self._looked) - {copy.name for copy in copies}:
            self._looked.pop(gone, None)
            self._kept.pop(gone, None)
        for copy in copies:
            facts = _facts(copy)
            if self._kept.get(copy.name, ()) == facts:
                continue
            seen = (facts, tuple(self.history.disk[:1]), tuple(self.history.lineage[:1]))
            if self._looked.get(copy.name) == seen:
                continue
            self._looked[copy.name] = seen
            try:
                self._take_copy(copy, facts)
            except Exception:
                traceback.print_exc()
        # (Merged: written now, not once things are quiet -- then put away.)
        if self._away and not self.save():
            self._write_state()

    def _take_copy(self, copy: Path, facts: tuple[int, int, int] | None) -> None:
        try:
            opened = Bundle(copy)
        except BundleError:
            return  # (still arriving: looked at again once it changes)
        with opened:
            if (
                not self.created
                or opened.manifest.get("created") != self.created
                or opened.document != self.document
                or _its_own(copy)
            ):
                return  # another bundle named alike, or one opened as itself
            revisions = opened.revisions
            entries = _entries(opened)
            if revisions and revisions[0] in self.history.lineage:
                # A saving the folder holds: once the bundle holds it too (or all it has), the
                # copy is put away -- made since this studio opened (a saving here the service
                # kept as a copy), not someone's own copy of an older saving.
                if (
                    (revisions[0] in self.history.disk or entries == self.synced)
                    and revisions[0] not in self._lost
                    and _made(copy) >= self.since - 60
                ):
                    self._away[copy] = (facts, False)
                return
            if not revisions and self._had(opened, entries):
                return  # (from an older studio, with nothing but versions had here)
            if revisions:
                base = self.history.base_for(revisions)
            else:
                # From an older studio: the version here most like it, before the latest (it
                # was saved apart from that, or it would be the bundle).
                main = opened.read(self.document, most=bundles.MOST_MANIFEST * 50)
                base = self.history.nearest(self.document, main, self.history.versions[:-1])
            if base is None:
                self._keep_copy(
                    copy,
                    facts,
                    f"\u201c{copy.name}\u201d holds edits from another computer that can\u2019t "
                    f"be matched with {self.path.name}\u2019s, so it isn\u2019t merged: it is "
                    "kept beside it.",
                )
                return
            theirs = _Side(entries, _reader(opened))
            outcome, unclean = self._absorb(
                self._base_side(base), self._folder_side(), theirs, flip=True
            )
            if unclean:
                self._keep_copy(
                    copy,
                    facts,
                    f"\u201c{copy.name}\u201d holds edits from another computer that change the "
                    "same things as edits here, so it isn\u2019t merged: it is kept beside "
                    f"{self.path.name}.",
                )
                return
            for name in self._apply(outcome, opened):
                self.stamps.pop(name, None)
            latest = self.history.latest
            if latest is not None and revisions:
                self._record_merged(base, latest, theirs, revisions, flip=True)
            elif not revisions:
                self._kept[copy.name] = facts  # (merged once, never again: it names no saving)
            self.history.took(revisions)
            self._seed()
            self._away[copy] = (facts, True)

    def _keep_copy(self, copy: Path, facts: tuple[int, int, int] | None, said: str) -> None:
        self._kept[copy.name] = facts
        self._notice(said)

    def _put_away(self) -> None:
        """The copies merged, now in the bundle as it is written, moved out of its folder."""

        for copy, (facts, merged) in list(self._away.items()):
            del self._away[copy]
            self._looked.pop(copy.name, None)  # (looked at again, if it is still there)
            if _facts(copy) != facts:
                continue  # changed since: merged again
            went = cloud.put_away(copy, support().parent / "merged")
            if went is None and merged:
                self._notice(
                    f"Merged edits from another computer ({copy.name}); it couldn\u2019t be "
                    f"moved away, and holds nothing {self.path.name} doesn\u2019t."
                )
            elif went is not None:
                self._notice(
                    f"Merged edits from another computer ({copy.name}, now in {went})."
                    if merged
                    else f"\u201c{copy.name}\u201d held nothing that isn\u2019t in "
                    f"{self.path.name}: it is now in {went}."
                )

    def _copy_of(self, heads: list[str]) -> Path | None:
        """A copy beside the bundle of this computer's saving ``heads``, if one is there."""

        for copy in cloud.copies_beside(self.path, self.service):
            with contextlib.suppress(BundleError), Bundle(copy) as opened:
                if opened.revisions[:1] and opened.revisions[0] in heads:
                    return copy
        return None

    def _had(self, opened: Bundle, entries: dict[str, tuple[int, int]]) -> bool:
        """Whether every file of a bundle is as a version here had it."""

        had = {entry for version in self.history.versions for entry in version.entries.items()}
        for name, entry in entries.items():
            if (name, entry) in had:
                continue
            if not _documentlike(name):
                return False
            words = opened.read(name, most=bundles.MOST_MANIFEST * 50)
            if not self.history.had(name, words):
                return False
        return True

    # -- writing --

    def save(self, *, force: bool = False) -> bool:
        """Write the folder back into the bundle if it changed since (``force``: whatever):
        whether it was written. A bundle changed on disk since it was last read (saved on
        another computer) is taken in first, never written over. Said to the pages when it
        could not be."""

        with self.lock:
            for _ in range(3):
                now = time.monotonic()
                facts = _facts(self.path)
                if facts is not None and self.facts is not None and facts != self.facts:
                    self._bundle_changed(facts, now)
                local = bundles.snapshot(self.root, keep_build=self.keep_build)
                if local == self.stamps and not force:
                    if self._away:
                        self._put_away()
                    return False
                files = {name: self.root.joinpath(*name.split("/")) for name in local}
                if self.document not in files:
                    self._follow_document(files)
                saving = cloud.revision()
                revisions = self.history.wrote(saving)
                about = bundles.manifest(
                    self.document,
                    self.kind,
                    created=self.created or None,
                    files=len(files),
                    revisions=revisions,
                )
                there = _facts(self.path)
                previous = self.path if self.facts is not None and there == self.facts else None

                def unchanged(there: tuple[int, int, int] | None = there) -> None:
                    if _facts(self.path) != there:
                        raise _Changed

                try:
                    self.known = bundles.write(
                        self.path,
                        files,
                        about,
                        previous=previous,
                        known=self.known,
                        check=unchanged,
                    )
                except _Changed:
                    continue  # (saved elsewhere as this was written: taken in, then written)
                except (OSError, BundleError) as error:
                    said = (
                        error.strerror
                        if isinstance(error, OSError) and error.strerror
                        else str(error)
                    )
                    self._said(
                        problem=f"{self.path.name} could not be saved: {said.rstrip('.')}. "
                        "Your changes are kept, and saved once it can be."
                    )
                    self.waiting_since = time.monotonic()
                    return False
                break
            else:
                return False
            self.created = about["created"]
            self.facts = _facts(self.path)
            self.stamps = {name: value[:2] for name, value in self.known.items()}
            self.synced = {name: (value[2], value[1]) for name, value in self.known.items()}
            self._read_texts()
            self.history.record([saving], self.texts, self.synced)
            self.history.lineage = revisions
            self.history.disk = revisions
            self.held_until = 0.0
            self.waiting_since = 0.0
            self.written_at = time.monotonic()
            if self.problem is not None:
                self._said(problem=None)
            self._write_state()
            if self._away:
                self._put_away()
            return True

    def _follow_document(self, files: dict[str, Path]) -> None:
        """The bundle's document renamed in the studio: the bundle's document is the one it is
        now (the open document of its kind most like it), else the one document at its root."""

        workspace = self.workspace
        if workspace is not None:
            followed = getattr(workspace, "followed", {}).get(self.document)
            if followed is not None and followed.name in files:
                self.document = followed.name
                return
        roots = [name for name in files if "/" not in name and _documentlike(name)]
        if len(roots) == 1:
            self.document = roots[0]

    def _renamed(self) -> Path | None:
        """The bundle, renamed beside itself as it was open (in the Finder): the very file."""

        if self.facts is None:
            return None
        with contextlib.suppress(OSError):
            for entry in os.scandir(self.path.parent):
                suffixed = entry.name.lower().endswith(bundles.SUFFIX)
                if suffixed and entry.is_file() and entry.stat().st_ino == self.facts[2]:
                    return Path(entry.path)
        return None

    def _follow(self, moved: Path) -> None:
        """Renamed as it was open: the bundle is the file it is now, its working folder kept."""

        # (Its working folder stays where it is while the studio serves it; opened again from
        # its new place, it is unpacked afresh there.)
        self.path = moved.resolve()
        self.facts = _facts(self.path)
        self._write_state()
        self._said(renamed=self.path.name)

    def _seed(self) -> None:
        """What each file was as the bundle has it, for its next writing to copy what has not
        changed as it is (``bundles.write``)."""

        self.known = {
            name: (*self.stamps[name], self.synced[name][0])
            for name in self.stamps
            if name in self.synced and self.synced[name][1] == self.stamps[name][1]
        }

    def _read_texts(self) -> None:
        """Each document as the bundle has it: read from the folder, where it is as written
        (else from the bundle)."""

        self.texts = {}
        written: Bundle | None = None
        try:
            for name in self.stamps:
                if not _documentlike(name):
                    continue
                with contextlib.suppress(OSError, BundleError, KeyError):
                    words = self._file(name).read_bytes()
                    if name in self.synced and zlib.crc32(words) != self.synced[name][0]:
                        # (Changed again as it was written.)
                        if written is None:
                            written = Bundle(self.path)
                        words = written.read(name, most=bundles.MOST_MANIFEST * 50)
                    self.texts[name] = words
        finally:
            if written is not None:
                written.close()

    def _file(self, name: str) -> Path:
        return self.root.joinpath(*name.split("/"))

    def _notice(self, said: str) -> None:
        """Say what became of a copy beside the bundle: to the pages, or as it opens."""

        if self.workspace is None:
            self.notices.append(said)
        else:
            self._said(notices=[said])

    def _said(
        self,
        *,
        problem: str | bool | None = False,
        taken: list[str] | None = None,
        renamed: str | None = None,
        notices: list[str] | None = None,
    ) -> None:
        if problem is not False:
            self.problem = problem  # type: ignore[assignment]
        workspace = self.workspace
        if workspace is None:
            return
        event: dict[str, Any] = {"type": "bundle", **self.info(), "notices": notices or []}
        if taken:
            event["taken"] = taken[:20]
        if renamed:
            event["renamed"] = renamed
        workspace.broadcast(event)

    # -- the state kept beside the working folder --

    def _read_state(self) -> dict[str, Any]:
        try:
            said = json.loads((self.home / STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return said if isinstance(said, dict) else {}

    def _write_state(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        state = {
            "bundle": str(self.path),
            "document": self.document,
            "trusted": self.trusted,
            "opened": time.time(),
            "synced": self.synced,
            "stamps": self.stamps,
            "created": self.created,
            **self.history.state(),
        }
        partial = self.home / f".{STATE}.{secrets.token_hex(4)}"
        partial.write_text(json.dumps(state), encoding="utf-8")
        os.replace(partial, self.home / STATE)


class _Changed(Exception):
    """The bundle changed on disk as it was being written: written once that is taken in."""


class _Side:
    """One side of a merge of bundles (``Keeper._absorb``): its files' CRCs and sizes, and its
    documents' words."""

    def __init__(
        self,
        entries: dict[str, tuple[int, int]],
        text: Any,
        entry: Any = None,
    ) -> None:
        self.entries = entries
        self.text = text
        self.entry = entry if entry is not None else entries.get


def _reader(opened: Bundle) -> Any:
    def text(name: str) -> bytes | None:
        try:
            return opened.read(name, most=bundles.MOST_MANIFEST * 50)
        except (KeyError, BundleError):
            return None

    return text


def _documents(opened: Bundle, entries: dict[str, tuple[int, int]]) -> dict[str, bytes]:
    """A bundle's documents' words."""

    found = {}
    for name in entries:
        if _documentlike(name):
            with contextlib.suppress(BundleError, KeyError):
                found[name] = opened.read(name, most=bundles.MOST_MANIFEST * 50)
    return found


def _its_own(copy: Path) -> bool:
    """Whether a bundle was opened on this computer as itself (not merged: someone's own)."""

    try:
        said = json.loads((home_of(copy) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(said, dict) and said.get("bundle") == str(copy.resolve())


def _made(path: Path) -> float:
    """When a file came to be as it is, there: written, or renamed (by a cloud service)."""

    try:
        found = path.stat()
    except OSError:
        return 0.0
    return max(found.st_mtime, found.st_ctime)


def _claims(kind: Any, parsed: Any) -> bool:
    try:
        return bool(kind.claims(parsed))
    except Exception:
        return False


def _replace(target: Path, data: bytes, root: Path) -> None:
    """Write a file of the working folder as the studio does: beside it, moved over it."""

    place = target.parent.resolve()
    real = root.resolve()
    if place != real and real not in place.parents:
        raise BundleError(f"{target.name} would be written outside the folder.")
    partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.saving")
    try:
        partial.write_bytes(data)
        os.replace(partial, target)
    finally:
        with contextlib.suppress(OSError):
            partial.unlink()


def _service(folder: Path) -> str | None:
    """The cloud service keeping ``folder`` (``flexo.studio.workspace.cloud_service``)."""

    from flexo.studio.workspace import cloud_service

    return cloud_service(folder)


def opened(path: str | Path) -> Keeper:
    """The bundle at ``path``, unpacked (or found as it was left) for the studio to serve."""

    return Keeper(path).open()


# -- what the pages ask of a bundle ------------------------------------------------------


def exported(workspace: Any, doc: Any, document: Any, into: Path) -> tuple[Path, list[str]]:
    """A bundle of a document as the page has it now (``document``, its words not yet all
    written), made in ``into`` -- named as the bundle it is edited in, else as its file: the
    bundle, and what to say of it (what was left out)."""

    keeper = getattr(workspace, "bundle", None)
    stem = (
        _stem(keeper.path) if keeper is not None and doc.name == keeper.document else doc.path.stem
    )
    into.mkdir(parents=True, exist_ok=True)
    target = into / f"{stem}{bundles.SUFFIX}"
    scratch = into / f".{doc.path.name}.{secrets.token_hex(4)}.saving{doc.path.suffix}"
    text = None
    try:
        save = doc.kind.save
        try:
            save(scratch, document, previous=doc.disk_text)
        except TypeError:
            save(scratch, document)
        text = scratch.read_text(encoding="utf-8")
    except Exception:
        text = None  # (bundled as its file has it)
    finally:
        with contextlib.suppress(OSError):
            scratch.unlink()
    made = bundles.pack(doc.path, target, text=text)
    return made.path, said_left(made.gathered.left)


def said_left(left: list[bundles.Left]) -> list[str]:
    """What a bundle left out, in a sentence each, for the page (and the command line)."""

    notes = []
    missing = [item.name for item in left if item.why == "missing"]
    outside = [item.name for item in left if item.why == "outside"]
    reserved = [item.name for item in left if item.why == "reserved"]
    if missing:
        notes.append(f"Not in the bundle, as it isn\u2019t in the folder: {_listed(missing)}.")
    if outside:
        notes.append(
            "Not in the bundle, as it is outside the document\u2019s folder (or named by "
            f"its whole path): {_listed(outside)}."
        )
    if reserved:
        notes.append(
            f"Not in the bundle: a file named {bundles.MANIFEST} beside the document "
            "(the bundle\u2019s own name). Rename it."
        )
    return notes


def _listed(names: list[str], most: int = 4) -> str:
    shown = ", ".join(names[:most])
    return shown + (f" and {len(names) - most} more" if len(names) > most else "")


def new_bundle(target: Path, kind: str = "deck") -> Path:
    """A new bundle at ``target`` (``.flexo`` added if it has no ending of a bundle's) holding a
    new document of ``kind`` named as it is ("Untitled.flexo" holds "Untitled.yaml"), as a new
    deck is made by default: one file, to keep and to send. Never over a file there."""

    import tempfile

    from flexo.studio import kinds

    target = Path(target).expanduser()
    if target.suffix.lower() != bundles.SUFFIX:
        target = target.with_name(target.name + bundles.SUFFIX)
    if target.exists():
        raise FileExistsError(f"\u201c{target.name}\u201d already exists. Choose a different name.")
    found = kinds()
    made = found.get(kind)
    if made is None:
        raise ValueError(f"No kind of document called {kind}: kinds are {', '.join(found)}.")
    with tempfile.TemporaryDirectory(prefix="flexo-new-") as aside:
        document = Path(aside) / f"{_stem(target)}.yaml"
        made.save(document, made.new(document))
        return bundles.pack(document, target).path


def open_beside(workspace: Any, target: Path) -> str:
    """A bundle opened in a studio of its own, served by this process beside ``workspace``'s (a
    browser's page opens it in a tab of its own), until ``workspace`` closes: its address."""

    from flexo.studio import sessions
    from flexo.studio.server import start

    server, opened = start(target, browser=False, trusted=True)
    threading.Thread(target=server.serve_forever, name=f"studio {target.name}", daemon=True).start()

    def close() -> None:
        try:
            opened.close()
        finally:
            server.shutdown()
            sessions.unregister(opened.root, server.server_address[1])
            server.server_close()

    workspace.on_close.append(close)
    return str(opened.address)


def unpack_beside(workspace: Any, folder: Path | None = None) -> Path:
    """The bundle the studio edits, written out as a plain folder: ``folder``, else one named
    as the bundle beside it (``talk``, ``talk 2``...). The folder."""

    keeper = getattr(workspace, "bundle", None)
    if keeper is None:
        raise ValueError("This window isn\u2019t a bundle\u2019s.")
    workspace.flush()
    keeper.save()
    if folder is None:
        stem, count = _stem(keeper.path), 1
        while True:
            folder = keeper.path.with_name(stem if count == 1 else f"{stem} {count}")
            if not folder.exists():
                break
            count += 1
    bundles.unpack(keeper.path, folder)
    return folder
