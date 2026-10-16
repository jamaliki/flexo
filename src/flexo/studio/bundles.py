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
the version both had.

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
from pathlib import Path
from typing import Any

from flexo import bundle as bundles
from flexo.bundle import Bundle, BundleError

POLL = 0.4
"""Seconds between looks at the working folder and at the bundle."""
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
        self.synced: dict[str, tuple[int, int]] = {}
        """Each file of the bundle, as it was last read or written: its CRC and size."""
        self.stamps: dict[str, tuple[int, int]] = {}
        """Each file of the folder as it was then: its time (ns) and size."""
        self.texts: dict[str, bytes] = {}
        """Each document's words as they were then: what both sides had, to merge from."""
        self.known: bundles.Known = {}
        self.facts: tuple[int, int, int] | None = None
        """The bundle's file as it was last read or written."""
        self.keep_build = False
        self.problem: str | None = None
        self.changed_at = 0.0
        self.waiting_since = 0.0
        self.unread_since = 0.0
        self.written_at = 0.0
        self._last: dict[str, tuple[int, int]] | None = None
        self._merging: set[str] = set()
        """Documents merged here with a bundle changed elsewhere: still to be written back."""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        shared = _cloud(self.path.parent)
        self.quiet = SHARED_QUIET if shared else QUIET
        self.patience = SHARED_PATIENCE if shared else PATIENCE

    # -- opening --

    def open(self) -> Keeper:
        """Unpack the bundle into its working folder, or find the folder as it was left: the
        bundle unchanged since, it is not unpacked again; changed (on another computer), what
        changed is taken in -- and edits made here that never reached it are kept in a bundle
        beside it, as a cloud service keeps a conflicting copy."""

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
            if fresh:
                self._unpack(opened)
            else:
                local = bundles.snapshot(self.root, keep_build=self.keep_build)
                mine = {
                    name for name in set(local) | set(stamps) if local.get(name) != stamps.get(name)
                }
                theirs = entries != synced
                self.synced, self.stamps = synced, stamps  # type: ignore[assignment]
                if theirs and mine:
                    self.conflict = self._keep_aside()
                    self._unpack(opened)
                elif theirs:
                    self._take(opened, entries)
            self.facts = _facts(self.path)
        # Trusted by its place -- unless what is there now is another bundle altogether (made
        # anew, not this one saved again: its manifest says when it was first made).
        made = state.get("created")
        self.replaced = bool(made) and bool(self.created) and made != self.created
        self.trusted = (
            bool(state.get("trusted"))
            and state.get("bundle") == str(self.path)
            and not self.replaced
        )
        self._seed()
        self._read_texts()
        self._write_state()
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
            "problem": self.problem,
        }

    def remember_trust(self) -> None:
        self.trusted = True
        with contextlib.suppress(OSError):
            self._write_state()

    def close(self) -> None:
        """Stop, writing back first whatever is not yet in the bundle."""

        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        with contextlib.suppress(Exception):
            self.save(force=False)

    # -- in step --

    def _run(self) -> None:
        while not self._stop.wait(POLL):
            try:
                self.step()
            except Exception:
                traceback.print_exc()

    def step(self, now: float | None = None) -> None:
        """One look: the bundle changed on disk is taken in; the folder changed, and rested
        (or changing too long), is written back."""

        now = time.monotonic() if now is None else now
        with self.lock:
            facts = _facts(self.path)
            if facts != self.facts:
                self._bundle_changed(facts, now)
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
            rested = now - self.changed_at >= self.quiet
            if rested or now - self.waiting_since >= self.patience:
                self.save()

    def _bundle_changed(self, facts: tuple[int, int, int] | None, now: float) -> None:
        if facts is None:
            # Moved or deleted: followed if it was renamed beside itself; else it is written
            # there again with the next change.
            moved = self._renamed()
            if moved is not None:
                self._follow(moved)
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
                    taken = self._take(opened, entries)
                    if taken:
                        self._said(taken=taken)
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

    def _take(self, opened: Bundle, entries: dict[str, tuple[int, int]]) -> list[str]:
        """Take a bundle changed elsewhere into the folder: each file changed there written
        here -- over this one if it is unchanged here since, else, a document, merged with it
        from what both had -- and each it no longer has taken away if unchanged here. The
        names changed."""

        local = bundles.snapshot(self.root, keep_build=True)
        taken: list[str] = []
        for name, entry in entries.items():
            if self.synced.get(name) == entry:
                continue
            mine = name in local and local.get(name) != self.stamps.get(name)
            target = self.root.joinpath(*name.split("/"))
            if mine and _documentlike(name) and name in self.texts:
                theirs = opened.read(name, most=bundles.MOST_MANIFEST * 50)
                merged = self._merged(name, self.texts[name], target, theirs)
                if merged is None:
                    continue  # (kept as it is here: written back with the rest)
                _replace(target, merged, self.root)
            else:
                opened.extract(self.root, [name], replace=True)
            taken.append(name)
        for name in set(self.synced) - set(entries):
            target = self.root.joinpath(*name.split("/"))
            if name in local and local.get(name) == self.stamps.get(name):
                with contextlib.suppress(OSError):
                    target.unlink()
                taken.append(name)
        now_here = bundles.snapshot(self.root, keep_build=True)
        for name in taken:
            if name in now_here and name in entries and name not in self._merging:
                self.stamps[name] = now_here[name]
            elif name not in entries:
                self.stamps.pop(name, None)
        self.synced = dict(entries)
        self._seed()
        for name in taken:
            if _documentlike(name) and name in entries:
                with contextlib.suppress(Exception):
                    self.texts[name] = opened.read(name, most=bundles.MOST_MANIFEST * 50)
        return sorted(taken)

    def _merged(self, name: str, base: bytes, ours_path: Path, theirs: bytes) -> bytes | None:
        """A document changed both here and elsewhere since both last had it, merged by its
        kind as the studio merges two people's edits: its words, or None if it can't be."""

        from flexo.studio import kinds as all_kinds
        from flexo.studio.merge import merge3

        try:
            ours_text = ours_path.read_bytes()
        except OSError:
            return None
        kinds = all_kinds()
        scratch = self.home / f".merging-{secrets.token_hex(4)}"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            suffix = Path(name).suffix
            versions = {}
            for label, data in (("base", base), ("ours", ours_text), ("theirs", theirs)):
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
                return None
            loaded = {label: kind.load(file) for label, file in versions.items()}
            notes: list = []
            merged = merge3(loaded["base"], loaded["ours"], loaded["theirs"], notes)
            mend = getattr(kind, "mended", None)
            if mend is not None:
                merged = mend(merged, notes, loaded["base"])
            out = scratch / f"merged{suffix}"
            try:
                kind.save(out, merged, previous=ours_text.decode("utf-8"))
            except TypeError:
                kind.save(out, merged)
            self._merging.add(name)
            return out.read_bytes()
        except Exception:
            traceback.print_exc()
            return None
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def save(self, *, force: bool = False) -> bool:
        """Write the folder back into the bundle if it changed since (``force``: whatever):
        whether it was written. Said to the pages when it could not be."""

        with self.lock:
            local = bundles.snapshot(self.root, keep_build=self.keep_build)
            if local == self.stamps and not force:
                return False
            files = {name: self.root.joinpath(*name.split("/")) for name in local}
            if self.document not in files:
                self._follow_document(files)
            about = bundles.manifest(
                self.document, self.kind, created=self.created or None, files=len(files)
            )
            previous = (
                self.path if self.facts is not None and _facts(self.path) == self.facts else None
            )
            try:
                self.known = bundles.write(
                    self.path, files, about, previous=previous, known=self.known
                )
            except (OSError, BundleError) as error:
                said = (
                    error.strerror if isinstance(error, OSError) and error.strerror else str(error)
                )
                self._said(
                    problem=f"{self.path.name} could not be saved: {said.rstrip('.')}. "
                    "Your changes are kept, and saved once it can be."
                )
                self.waiting_since = time.monotonic()
                return False
            self.created = about["created"]
            self.facts = _facts(self.path)
            self.stamps = {name: value[:2] for name, value in self.known.items()}
            self.synced = {name: (value[2], value[1]) for name, value in self.known.items()}
            self._merging.clear()
            self._read_texts()
            self.waiting_since = 0.0
            self.written_at = time.monotonic()
            if self.problem is not None:
                self._said(problem=None)
            self._write_state()
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
        self.texts = {}
        for name in self.stamps:
            if _documentlike(name):
                with contextlib.suppress(OSError):
                    self.texts[name] = self.root.joinpath(*name.split("/")).read_bytes()

    def _said(
        self,
        *,
        problem: str | bool | None = False,
        taken: list[str] | None = None,
        renamed: str | None = None,
    ) -> None:
        if problem is not False:
            self.problem = problem  # type: ignore[assignment]
        workspace = self.workspace
        if workspace is None:
            return
        event: dict[str, Any] = {"type": "bundle", **self.info()}
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
        }
        partial = self.home / f".{STATE}.{secrets.token_hex(4)}"
        partial.write_text(json.dumps(state), encoding="utf-8")
        os.replace(partial, self.home / STATE)


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


def _cloud(folder: Path) -> bool:
    from flexo.studio.workspace import cloud_service

    return cloud_service(folder) is not None


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
