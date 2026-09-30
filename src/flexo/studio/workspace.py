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
import hashlib
import json
import os
import queue
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
RETRY = 5.0
"""Seconds before a document that could not be written is tried again."""
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
        self.document = kind.load(path) if self.exists else kind.new(path)
        _bounded(self.document)
        self.version = 1
        self.history: OrderedDict[int, str] = OrderedDict({1: _dumps(self.document)})
        self.saved = 1 if self.exists else 0
        self.changed_at = 0.0
        self.unsaved_since = 0.0
        self.retry_at = 0.0
        self.on_disk = copy.deepcopy(self.document) if self.exists else None
        self.disk_text = path.read_text(encoding="utf-8") if self.exists else None
        self.disk_stamp = _stamp(path)
        self.problem: str | None = None
        self.depends: set[Path] = set()
        self.depend_stamps: dict[Path, float] = {}

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
            }

    def update(
        self, document: Any, base: int, who: dict[str, Any], client: str = ""
    ) -> tuple[int, Any]:
        """Take a changed document made from version ``base``; return the version and
        document it became (merged with changes made since ``base``)."""

        with self.lock:
            if base == self.version:
                merged = document
            else:
                known = self.history.get(base)
                start = json.loads(known) if known is not None else self.document
                merged = merge3(start, self.document, document)
            return self._become(merged, who, client)

    def _become(self, merged: Any, who: dict[str, Any], client: str) -> tuple[int, Any]:
        before = self.document
        if _dumps(merged) == _dumps(before):
            return self.version, self.document
        self.version += 1
        self.document = merged
        self.history[self.version] = _dumps(merged)
        while len(self.history) > HISTORY:
            self.history.popitem(last=False)
        self.changed_at = time.monotonic()
        if self.saved >= self.version - 1:
            self.unsaved_since = self.changed_at
        self.workspace.changed(self, before, merged, who, client)
        return self.version, merged

    def base(self, version: int) -> Any:
        known = self.history.get(version)
        return json.loads(known) if known is not None else None

    # -- the file --

    def write(self) -> bool:
        """Write the document if it has changed since last written; whether it did."""

        with self.lock:
            if self.saved >= self.version:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside the file and moved over it: a write cut short (a full disk,
            # the app quitting) leaves the file as it was, not half of the new one.
            partial = self.path.with_name(
                f".{self.path.name}.{secrets.token_hex(4)}.saving{self.path.suffix}"
            )
            try:
                self.kind.save(partial, self.document)
                with contextlib.suppress(OSError):
                    os.chmod(partial, self.path.stat().st_mode & 0o7777)
                os.replace(partial, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    partial.unlink()
                raise
            self.disk_text = self.path.read_text(encoding="utf-8")
            self.disk_stamp = _stamp(self.path)
            self.on_disk = copy.deepcopy(self.document)
            self.saved = self.version
            self.exists = True
            self.problem = None
            return True

    def reread(self) -> str | None:
        """Take in the file if something else changed it; what happened, if anything."""

        stamp = _stamp(self.path)
        if stamp == self.disk_stamp:
            return None
        with self.lock:
            self.disk_stamp = stamp
            if stamp == 0.0:
                return None  # removed: keep what is open; saving writes it again
            try:
                text = self.path.read_text(encoding="utf-8")
            except OSError:
                return None
            if text == self.disk_text:
                return None
            try:
                found = self.kind.load(self.path)
            except Exception as error:  # a file half-written, or wrong: say so, keep ours
                self.problem = f"{self.name} on disk does not read: {explain(error)}"
                self.disk_text = text
                return "problem"
            self.problem = None
            base = self.on_disk if self.on_disk is not None else self.document
            merged = merge3(base, self.document, found)
            self.on_disk = found
            self.disk_text = text
            self.exists = True
            who = self.workspace.agent_on(self.name) or {
                "id": "disk",
                "name": "The file",
                "kind": "file",
            }
            unsaved = self.saved < self.version
            self._become(merged, who, "")
            if not unsaved and _dumps(merged) == _dumps(found):
                self.saved = self.version
            return "changed"


class Workspace:
    """A folder being edited: its open documents, who is here, and what happened."""

    def __init__(self, root: Path, *, kind: str | None = None, trusted: bool = True) -> None:
        self.root = root.resolve()
        self.trusted = trusted
        """Whether code the folder brings (a deck's plots) may run; a folder someone else
        made runs none until its person says they trust it."""
        self.on_trust: list[Any] = []
        self.kinds = kinds()
        self.default_kind = kind
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.docs: dict[str, Doc] = {}
        self.listeners: dict[str, Listener] = {}
        self.presence: dict[str, dict[str, Any]] = {}
        self.activity: deque[dict[str, Any]] = deque(maxlen=300)
        self.drawing = threading.Lock()
        self.latest: dict[str, int] = {}
        self._documents: dict[Path, tuple[float, str | None]] = {}
        self._stop = threading.Event()
        self.assistant = None
        self.on_close: list[Any] = []
        """What to do when the workspace closes (forget its agents' tools, say)."""
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
        finally:
            with self.lock:
                listeners = list(self.listeners.values())
            for listener in listeners:
                listener.events.put(None)  # the page's event stream ends
            for then in self.on_close:
                with contextlib.suppress(Exception):
                    then()

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

    def _claim(self, path: Path) -> str | None:
        stamp = _stamp(path)
        cached = self._documents.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        found = None
        try:
            if path.stat().st_size < CLAIM_LIMIT:
                text = path.read_text(encoding="utf-8")
                json_file = path.suffix.lower() == ".json"
                parsed = json.loads(text) if json_file else yaml.load(text, _LOADER)
                # The figure kind claims broadly; every other kind is asked first.
                for kind in sorted(self.kinds.values(), key=lambda item: item.name == "figure"):
                    if kind.claims(parsed):
                        found = kind.name
                        break
        except Exception:
            # Anything a file can be (a typo mid-edit, a date that is no date, nesting too
            # deep to read): not a document now, but one it was stays that kind.
            found = cached[1] if cached else None
        self._documents[path] = (stamp, found)
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
        for file in sorted(files):
            try:
                name = self.relative(file)
            except PermissionError:
                continue  # a link to somewhere outside the folder
            if name in seen:
                continue
            kind = self._claim(file)
            if kind:
                seen.add(name)
                found.append({"file": name, "kind": kind, "title": self.kinds[kind].title})
            if len(found) >= 300:
                break
        return found

    def open(self, name: str, kind: str | None = None) -> Doc:
        path = self.path(name)
        relative = unicodedata.normalize("NFC", self.relative(path))
        with self.lock:
            doc = self.docs.get(relative)
            if doc is None:
                # The same file by another spelling (decomposed accents, other capitals, as
                # macOS allows) is the document already open.
                doc = next((open_ for open_ in self.docs.values() if _same(open_.path, path)), None)
            if doc is None:
                doc = Doc(self, relative, path, self.kind_of(path, kind))
                self.docs[relative] = doc
            return doc

    def new(self, name: str, kind_name: str, data: Any = None) -> Doc:
        """Make a file of a kind -- its starting document, or ``data`` (a parsed
        document of that kind) -- and open it. An existing file is opened as it is."""

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
        self.record(
            {"id": "studio", "name": "Studio", "kind": "system"}, doc.name, f"made {path.name}"
        )
        self.broadcast({"type": "documents", "documents": self.documents()})
        return doc

    def flush(self) -> None:
        for doc in list(self.docs.values()):
            self._write(doc)

    def _write(self, doc: Doc) -> None:
        """Write one document; one that cannot be written says why on its page, and is
        tried again later, while the others are written as usual."""

        try:
            wrote = doc.write()
        except Exception as error:
            problem = f"{doc.name} could not be saved: {_reason(error)}"
            doc.retry_at = time.monotonic() + RETRY
            if doc.problem != problem:
                doc.problem = problem
                self.broadcast({"type": "problem", "file": doc.name, "text": problem})
            return
        if wrote:
            self.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})

    # -- changes --

    def changed(self, doc: Doc, before: Any, after: Any, who: dict[str, Any], client: str) -> None:
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
            if (
                last
                and last["who"].get("id") == who.get("id")
                and last["file"] == file
                and last["text"] == text
                and last["where"] == where
                and now - last["at"] < 20
            ):
                last["at"] = now
                last["count"] = last.get("count", 1) + 1
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
        self, who: dict[str, Any], file: str | None, where: Any, doing: str | None
    ) -> None:
        key = who.get("id") or who.get("name", "someone")
        with self.lock:
            entry = self.presence.get(key, {"who": who})
            entry.update(who=who, file=file, where=where, at=time.time())
            if doing is not None:
                entry["doing"] = doing
            self.presence[key] = entry
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
        with self.lock:
            return [dict(entry) for entry in self.presence.values()]

    def focus_of_people(self) -> list[dict[str, Any]]:
        return [entry for entry in self.present() if entry["who"].get("kind") == "person"]

    # -- listeners --

    def listen(self, client: str, who: dict[str, Any]) -> Listener:
        listener = Listener(client, who)
        with self.lock:
            self.listeners[client] = listener
        return listener

    def leave(self, listener: Listener) -> None:
        with self.lock:
            if self.listeners.get(listener.client) is listener:
                del self.listeners[listener.client]
            if listener.client in self.presence and not any(
                other.who.get("id") == listener.who.get("id") for other in self.listeners.values()
            ):
                del self.presence[listener.client]
        self.broadcast({"type": "presence", "presence": self.present()})

    def broadcast(self, event: dict[str, Any]) -> None:
        with self.lock:
            listeners = list(self.listeners.values())
        for listener in listeners:
            listener.events.put(event)

    # -- drawing --

    def draw(
        self, name: str, document: Any, version: int, known: dict[str, str], hints: dict[str, Any]
    ) -> dict[str, Any]:
        doc = self.open(name)
        # Each page counts its own drawings; an older one waiting its turn is dropped.
        client = f"{name}\0{hints.get('client', '')}"
        self.latest[client] = max(self.latest.get(client, 0), version)
        with self.drawing:
            if version < self.latest[client]:
                return {"version": version, "stale": True}
            started = time.perf_counter()
            try:
                # The page has every bundled font; drawings name them rather than carry them.
                with fonts_linked(), self.running(), pictures.linked(self):
                    drawing = doc.kind.draw(document, doc.path.parent, hints)
            except Exception as error:  # the page shows what went wrong, and stays up
                traceback.print_exc()
                return {
                    "version": version,
                    "pages": [],
                    "seconds": time.perf_counter() - started,
                    "messages": [
                        {
                            "text": explain(error),
                            "severity": "error",
                            "where": "",
                            "page": "",
                            "code": "studio.crash",
                        }
                    ],
                }
            elapsed = time.perf_counter() - started
        doc.depends = {file.resolve() for file in drawing.files}
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
            "messages": [asdict(message) for message in drawing.messages],
            "unfinished": drawing.unfinished,
        }

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

    def _step(self) -> None:
        now = time.monotonic()
        for doc in list(self.docs.values()):
            happened = doc.reread()
            if happened == "problem":
                self.broadcast({"type": "problem", "file": doc.name, "text": doc.problem})
            rested = now - doc.changed_at > QUIET or now - doc.unsaved_since > PATIENCE
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


def _reason(error: Exception) -> str:
    if isinstance(error, OSError) and error.strerror:
        return error.strerror.lower()
    return str(error) or type(error).__name__


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime_ns / 1e9
    except OSError:
        return 0.0


def _dumps(document: Any) -> str:
    return json.dumps(document, sort_keys=True, ensure_ascii=False, default=str)
