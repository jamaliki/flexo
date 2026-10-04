"""The studio's server: the page, and the calls it and agents make, on this machine only.

It serves one folder and reads and writes files only inside it. Every call
carries a token the page is given when it loads (an agent finds it in the
studio's session file, readable only by its owner), and a request for another
host name is refused, so neither another site open in the browser nor a
rebound domain name can reach it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import queue
import secrets
import select
import signal
import socket
import socketserver
import sys
import threading
import traceback
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from flexo.studio import sessions
from flexo.studio.plain import explain
from flexo.studio.workspace import Workspace, walk

STATIC = Path(__file__).parent / "static"
LEAVE_GRACE = 2.5
"""Seconds a window whose connection broke is still taken as there: back by then (a page
reconnecting), its person never left."""
FILE_TYPES = {
    "image": (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf", ".ai"),
    "figure": (".yaml", ".yml", ".json"),
    "python": (".py",),
    "theme": (".yaml", ".yml", ".json"),
    "structure": (".pdb", ".cif", ".mmcif", ".ent"),
}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer asks DNS what its address is called, a reverse lookup that can wait
        # half a minute on macOS (inside an app, say); nothing here uses the name.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    workspace: Workspace
    start_file: str = ""
    server_version = "FlexoStudio"
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        # A page closed or reloaded mid-reply is not the studio's problem.
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, format: str, *args: object) -> None:  # quiet by default
        return

    # -- plumbing --

    def _reply(self, status: int, body: bytes, kind: str, *, cache: bool = False) -> None:
        encoding = None
        # Fonts and photographs are compressed already.
        packed = kind.startswith(("font/", "image/png", "image/jpeg"))
        compressible = len(body) > 2048 and not packed
        if compressible and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            encoding = "gzip"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400, immutable" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._reply(status, body, "application/json")

    def _fail(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in {"127.0.0.1", "localhost", "[::1]"}

    def _token_ok(self, query: dict[str, list[str]]) -> bool:
        given = self.headers.get("X-Studio-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(given, self.workspace.token)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _static(self, folder: Path, name: str) -> None:
        target = (folder / name).resolve()
        if folder.resolve() not in target.parents or not target.is_file():
            self._fail(HTTPStatus.NOT_FOUND, f"no {name}")
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            kind = "text/javascript"
        charset = "; charset=utf-8" if kind.startswith("text") else ""
        self._reply(200, target.read_bytes(), kind + charset)

    # -- routes --

    def do_GET(self) -> None:
        if not self._host_ok():
            self._fail(HTTPStatus.FORBIDDEN, "the studio answers on 127.0.0.1 and localhost only")
            return
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path
        if route in {"/", "/index.html"}:
            self._index(query)
        elif route.startswith("/static/studio/"):
            self._static(STATIC / "studio", route.removeprefix("/static/studio/"))
        elif route.startswith("/fonts/"):
            self._font(route.removeprefix("/fonts/"))
        elif route.startswith("/static/kinds/"):
            name, _, rest = route.removeprefix("/static/kinds/").partition("/")
            kind = self.workspace.kinds.get(name)
            if kind is None:
                self._fail(HTTPStatus.NOT_FOUND, f"no kind {name}")
            else:
                self._static(Path(kind.static), rest)
        elif route.startswith("/api/"):
            if not self._token_ok(query):
                self._fail(HTTPStatus.FORBIDDEN, "missing or wrong studio token")
                return
            self._guarded(lambda: self._api_get(route, query))
        else:
            self._fail(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._host_ok() or not self._token_ok(query):
            # Its body is not read: the connection ends with the answer, so the body is
            # not taken for the next request on it.
            self.close_connection = True
            self._fail(HTTPStatus.FORBIDDEN, "missing or wrong studio token")
            return
        body = self._body()
        self._guarded(lambda: self._api_post(url.path, query, body))

    def _guarded(self, action) -> None:
        try:
            action()
        except (BrokenPipeError, ConnectionResetError):
            raise
        except PermissionError as error:
            self._fail(HTTPStatus.FORBIDDEN, str(error))
        except FileExistsError as error:
            self._fail(HTTPStatus.CONFLICT, str(error))
        except FileNotFoundError as error:
            self._fail(HTTPStatus.NOT_FOUND, str(error))
        except ValueError as error:
            # Something the document says (a missing file, a malformed block): the page shows it.
            self._fail(HTTPStatus.BAD_REQUEST, explain(error))
        except Exception as error:
            traceback.print_exc()
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, explain(error))

    def _font(self, name: str) -> None:
        """The bundled fonts, which drawings in the studio name rather than embed."""

        from flexo.svg_resources import bundled_faces, bundled_font_css

        faces = bundled_faces()
        if name == "faces.css":
            body = bundled_font_css(lambda index, face: f"/fonts/{index}").encode("utf-8")
            self._reply(200, body, "text/css; charset=utf-8")
            return
        if not name.isdigit() or int(name) >= len(faces):
            self._fail(HTTPStatus.NOT_FOUND, f"no font {name}")
            return
        source = Path(faces[int(name)].source)
        kind = "font/otf" if source.suffix.lower() == ".otf" else "font/ttf"
        self._reply(200, source.read_bytes(), kind, cache=True)

    def _index(self, query: dict[str, list[str]]) -> None:
        name = (query.get("file") or [self.start_file])[0]
        page = (STATIC / "studio" / "index.html").read_text(encoding="utf-8")
        settings = json.dumps({"token": self.workspace.token, "file": name})
        page = page.replace("/*STUDIO*/null", settings.replace("</", "<\\/"))
        self._reply(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _api_get(self, route: str, query: dict[str, list[str]]) -> None:
        workspace = self.workspace
        if route == "/api/session":
            self._json(self._session())
        elif route == "/api/open":
            held = (query.get("held") or [""])[0] == "1"
            doc = workspace.open(_one(query, "file"), (query.get("kind") or [None])[0], held=held)
            self._json({**doc.info(), "catalog": doc.kind.catalog()})
        elif route == "/api/documents":
            self._json({"documents": workspace.documents()})
        elif route == "/api/files":
            types = (query.get("types") or ["image"])[0].split(",")
            self._json(self._files(_one(query, "file"), types))
        elif route == "/api/raw":
            self._raw(query)
        elif route == "/api/picture":
            # A photograph a drawing names: its address carries its version, so it keeps.
            path = workspace.path(_one(query, "path"))
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not path.is_file():
                raise FileNotFoundError(f"no picture {_one(query, 'path')}")
            from flexo.studio import pictures

            body, kind = pictures.shown(path)
            self._reply(200, body, kind, cache=True)
        elif route == "/api/events":
            name, person = (query.get("name") or [""])[0], (query.get("person") or [""])[0]
            self._events(_one(query, "client"), name, person)
        elif route == "/api/themes":
            from flexo.studio import theming

            self._json({"themes": theming.cards(workspace, _one(query, "file"))})
        elif route == "/api/theme/uses":
            from flexo.studio import theming

            self._json({"documents": theming.uses(workspace, _one(query, "file"))})
        elif route == "/api/agent/tools":
            from flexo.studio.agent import TOOLS

            self._json({"tools": TOOLS})
        else:
            self._fail(HTTPStatus.NOT_FOUND, "not found")

    def _api_post(self, route: str, query: dict[str, list[str]], body: bytes) -> None:
        workspace = self.workspace
        if route == "/api/upload":
            self._json(self._upload(_one(query, "file"), _one(query, "name"), body))
            return
        data = json.loads(body or b"{}")
        name = data.get("file", "")
        who = _person(data)
        if route == "/api/update":
            doc = workspace.open(name)
            if data.get("instance") not in (None, workspace.instance):
                # Made from a version of a studio since stopped: this one counts afresh.
                self._json({"restarted": True})
                return
            if data.get("kind") not in (None, doc.kind.name):
                # Made in another kind's editor: the file has become this kind's since.
                self._json({"reopen": True, "kind": doc.kind.name})
                return
            # Told to the pages with the window it came from, so that window knows its own.
            client = str(data.get("client") or who["id"])
            version, document = doc.update(data["document"], int(data["base"]), who, client)
            # Whose changes it was merged with, for the page to name them.
            others = doc.author_since(int(data["base"]), who)
            self._json({"version": version, "document": document, "who": others})
        elif route == "/api/draw":
            self._json(
                workspace.draw(
                    name,
                    data.get("document"),
                    int(data.get("version", 0)),
                    data.get("known") or {},
                    data.get("hints") or {},
                )
            )
        elif route == "/api/save":
            doc = workspace.open(name)
            workspace.reread(doc)
            if doc.held:
                self._fail(HTTPStatus.CONFLICT, doc.problem or f"Can't read {doc.name}")
                return
            wrote = doc.write(again=True)
            if wrote:
                workspace.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})
            if doc.foreign:
                # Another kind's document (now): it opens again as that kind.
                workspace.broadcast(doc.said())
                workspace.open(doc.name)
                if not wrote:
                    self._fail(HTTPStatus.CONFLICT, doc.problem or f"{doc.name} was not saved")
                    return
            self._json({"ok": True, "saved": doc.saved})
        elif route == "/api/mend":
            # A file that does not read, put right by its person where the studio shows it.
            workspace.open(name).mend(str(data.get("text", "")))
            self._json({"ok": True})
        elif route == "/api/new":
            doc = workspace.new(name, data.get("kind", ""), data.get("data"), who)
            self._json({"file": doc.name})
        elif route == "/api/export":
            self._export(workspace.open(name), data)
        elif route == "/api/act":
            # An edit the page asks the document's kind to make (a figure's parts added,
            # connected, renamed): the kind answers with the document as it would be.
            doc = workspace.open(name)
            act = getattr(doc.kind, "act", None)
            if act is None:
                self._fail(HTTPStatus.NOT_FOUND, f"a {doc.kind.title.lower()} takes no such edits")
                return
            self._json(act(data.get("document", doc.document), data.get("action") or {},
                           doc.path.parent))
        elif route == "/api/theme/use":
            from flexo.studio import theming

            targets = [str(target) for target in data.get("targets") or []]
            self._json({"documents": theming.use(workspace, name, targets, who)})
        elif route == "/api/trust":
            workspace.trust()
            self._json({"ok": True})
        elif route == "/api/presence":
            file, where, doing = data.get("file"), data.get("where"), data.get("doing")
            workspace.set_presence(who, file, where, doing, str(data.get("client") or ""))
            self._json({"ok": True})
        elif route == "/api/leave":
            workspace.depart(str(data.get("client") or ""))
            self._json({"ok": True})
        elif route == "/api/kept":
            # What a page's own merge kept against its person's change (an object they
            # deleted that another was typing in): told to the others' pages, as the studio's
            # merges are told (Doc._tell), so the one typing hears of it too.
            items = [item for item in data.get("items") or [] if isinstance(item, dict | str)]
            notes = [{"kept": item, "by": who, "to": None} for item in items[:20]]
            if notes:
                file, client = str(data.get("file") or ""), str(data.get("client") or "")
                said = {"type": "merged", "file": file, "client": client, "notes": notes}
                workspace.broadcast(said)
            self._json({"ok": True})
        elif route == "/api/agent/call":
            tools = _agent_tools(workspace, data.get("who") or {})
            content, failed = tools.call(str(data.get("name")), data.get("input") or {})
            self._json({"content": content, "is_error": failed})
        elif route == "/api/assistant":
            assistant = _assistant(workspace)
            assistant.ask(str(data.get("text", "")), data.get("context") or {}, who)
            self._json({"ok": True})
        elif route == "/api/assistant/stop":
            _assistant(workspace).stop()
            self._json({"ok": True})
        elif route == "/api/assistant/clear":
            _assistant(workspace).clear()
            self._json({"ok": True})
        else:
            self._fail(HTTPStatus.NOT_FOUND, "not found")

    def _session(self) -> dict[str, Any]:
        workspace = self.workspace
        from flexo.studio.assistant import unavailable

        assistant = workspace.assistant
        return {
            "folder": str(workspace.root),
            "address": getattr(workspace, "address", ""),
            "trusted": workspace.trusted,
            "kinds": [
                {"name": kind.name, "title": kind.title, "offered": kind.name in workspace.offered}
                for kind in workspace.kinds.values()
            ],
            "documents": workspace.documents(),
            "open": sorted(workspace.docs),
            "presence": workspace.present(),
            "activity": list(workspace.activity)[-120:],
            "assistant": assistant.state()
            if assistant
            else {
                "available": unavailable() is None,
                "why": unavailable(),
                "running": False,
                "transcript": [],
            },
            "start": self.start_file,
        }

    def _files(self, name: str, types: list[str]) -> dict[str, Any]:
        folder = self.workspace.path(name).parent
        suffixes = tuple(suffix for kind in types for suffix in FILE_TYPES.get(kind, ()))
        found = [
            file.relative_to(folder).as_posix()
            for file in sorted(walk(folder))
            if file.suffix.lower() in suffixes
        ]
        return {"files": found[:500]}

    def _upload(self, name: str, filename: str, data: bytes) -> dict[str, Any]:
        # A file dropped from the document's own folder is used where it is, not copied.
        beside = self.workspace.path(name).parent / Path(filename).name
        if beside.is_file() and beside.read_bytes() == data:
            self.workspace.relative(beside)
            return {"path": beside.name}
        folder = self.workspace.path(name).parent / "assets"
        clean = (
            "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._- ").strip()
            or "file"
        )
        target = folder / clean
        self.workspace.relative(target)  # inside the folder, or PermissionError
        stem, suffix, count = target.stem, target.suffix, 1
        while target.exists() and target.read_bytes() != data:
            count += 1
            target = target.with_name(f"{stem}-{count}{suffix}")
        if not target.exists():
            # A copy of this studio's making: taken away again if, when it closes, no
            # document uses it (Workspace.tidy_uploads).
            self.workspace.uploads.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": target.relative_to(self.workspace.path(name).parent).as_posix()}

    def _export(self, doc: Any, data: dict[str, Any]) -> None:
        """A document's outputs, written into ``build/`` beside it, as agents and the CLI
        have them; or made aside, for the page to hand to its person (``deliver``):
        ``"download"`` answers with the file itself, or a zip of several, and ``"staged"``
        with where the file, or a folder of several, was made, for the Mac app to move
        where its person says. ``options`` go to the kind's export as far as it takes
        them (a deck's ``steps``)."""

        import inspect
        import shutil
        import tempfile

        workspace = self.workspace
        document = data.get("document", doc.document)
        formats = list(data.get("formats") or [])
        deliver = data.get("deliver") or "build"
        if deliver not in {"build", "download", "staged"}:
            raise ValueError(f"An export is delivered to build, download or staged, not {deliver}.")
        # One part of the document, exported by itself (a figure on a slide).
        part = data.get("part")
        write = doc.kind.export if part is None else getattr(doc.kind, "export_part", None)
        if write is None:
            self._fail(HTTPStatus.NOT_FOUND, f"a {doc.kind.title.lower()} exports no parts")
            return
        takes = inspect.signature(write).parameters
        extra = {key: value for key, value in (data.get("options") or {}).items()
                 if key in takes and key != "into"}
        aside = None if deliver == "build" else Path(tempfile.mkdtemp(prefix="flexo-export-"))
        into = aside / "files" if aside is not None else None
        if into is not None and "into" in takes:
            extra["into"] = into
        given = (document, doc.path.parent, doc.path.stem, *([] if part is None else [part]))
        try:
            with workspace.drawing, workspace.running():
                # What the export left out and says so (a figure that can't be drawn, left an
                # empty box): told to the page with what was made.
                doc.kind.export_notes = []
                written = write(*given, formats, **extra)
                notes = [str(note) for note in getattr(doc.kind, "export_notes", None) or []]
            if into is None:
                files = [workspace.relative(file) for file in written]
                self._json({"files": files, "notes": notes})
                return
            if "into" not in takes:  # a kind that writes into build/ alone: its files, copied
                into.mkdir(parents=True, exist_ok=True)
                for file in written:
                    shutil.copy2(file, into / Path(file).name)
            made = _made(into, doc.path.stem)
            if deliver == "staged":
                self._json(
                    {"path": str(made), "name": made.name, "folder": made.is_dir(), "notes": notes}
                )
                aside = None  # the Mac app moves it, and clears the rest away
                return
            self._attachment(made, aside, notes)
        finally:
            if aside is not None:
                shutil.rmtree(aside, ignore_errors=True)

    def _attachment(
        self, made: Path, aside: Path | None = None, notes: list[str] | None = None
    ) -> None:
        """A file made aside, as a download: itself, or a folder of several as a zip. Read,
        what was made `aside` is cleared away before it is sent, so nothing is left once the
        download has come."""

        import io
        import shutil
        import zipfile

        if made.is_dir():
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(made.rglob("*")):
                    if file.is_file():
                        archive.write(file, file.relative_to(made).as_posix())
            data, name, kind = buffer.getvalue(), f"{made.name}.zip", "application/zip"
        else:
            data, name = made.read_bytes(), made.name
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if aside is not None:
            shutil.rmtree(aside, ignore_errors=True)
        plain = name.encode("ascii", "replace").decode("ascii").replace('"', "'")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        disposition = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"
        self.send_header("Content-Disposition", disposition)
        if notes:
            self.send_header("X-Flexo-Notes", quote(json.dumps(notes)))
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, query: dict[str, list[str]]) -> None:
        """A file in the folder, named from a document's own folder (a picture a slide
        shows, an export to download)."""

        base = self.workspace.path(_one(query, "file")).parent
        target = (base / _one(query, "path")).resolve()
        self.workspace.relative(target)  # inside the folder, or PermissionError
        if not target.is_file():
            raise FileNotFoundError(f"no file {_one(query, 'path')}")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix.lower() == ".svg":
            kind = "image/svg+xml"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        if (query.get("download") or [""])[0]:
            self.send_header(
                "Content-Disposition", f"attachment; filename*=UTF-8''{quote(target.name)}"
            )
        self.end_headers()
        self.wfile.write(data)

    def _events(self, client: str, name: str, person: str = "") -> None:
        """Server-sent events: everything that happens in the workspace, as it happens,
        to one window (``client``) of a ``person``."""

        who = {"id": person or client, "name": name, "kind": "person"}
        listener = self.workspace.listen(client, who)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            # Who is here, as the studio knows it now: a window back after the studio was
            # started again shows no one gone meanwhile (presence is sent only as it changes).
            here = {"presence": self.workspace.present()}
            hello = json.dumps(here, ensure_ascii=False, default=str)
            # Lost (the studio started again), a window tries again within half a second, not
            # the browser's three: its edits held meanwhile are said to be saved as soon as
            # they are.
            self.wfile.write(f"retry: 500\nevent: hello\ndata: {hello}\n\n".encode())
            self.wfile.flush()
            quiet = 0
            while True:
                try:
                    event = listener.events.get(timeout=1)
                except queue.Empty:
                    # A window gone without a word (crashed, killed) has closed its end:
                    # seen within a second, not at the next heartbeat that fails.
                    if self._hung_up():
                        return
                    quiet += 1
                    if quiet >= 15:
                        quiet = 0
                        self.wfile.write(b": still here\n\n")
                        self.wfile.flush()
                    continue
                if event is None:
                    return
                quiet = 0
                payload = json.dumps(event, ensure_ascii=False, default=str)
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            # A moment's break (the page reconnecting) does not make its person flicker out.
            self.workspace.leave(listener, grace=LEAVE_GRACE)

    def _hung_up(self) -> bool:
        """Whether the page has closed its end of this connection (it sends nothing else)."""

        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True


def _one(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values:
        raise ValueError(f"missing {key}")
    return values[0]


def _person(data: dict[str, Any]) -> dict[str, Any]:
    """Who made a call: the person (one in every window they have open), else the window."""

    who = data.get("who") or {}
    person = str(who.get("id") or data.get("client") or "someone")
    # Unnamed, a person has no name: each page calls them You to themselves, Someone to others.
    return {"id": person, "name": str(who.get("name") or ""), "kind": "person"}


def _made(into: Path, stem: str) -> Path:
    """What an export made in ``into`` comes to: its one file or folder, or, of several,
    the folder holding them, named ``stem``."""

    made = sorted(into.iterdir()) if into.is_dir() else []
    if not made:
        raise ValueError("Nothing was exported.")
    if len(made) == 1:
        return made[0]
    return into.rename(into.with_name(stem))


_AGENTS: dict[tuple[int, str], Any] = {}
_AGENTS_LOCK = threading.Lock()


def _agent_tools(workspace: Workspace, who: dict[str, Any]):
    from flexo.studio.agent import Tools

    ident = str(who.get("id") or "agent")
    with _AGENTS_LOCK:
        key = (id(workspace), ident)
        if key not in _AGENTS:
            _AGENTS[key] = Tools(workspace, {"id": ident, "name": str(who.get("name") or "Agent")})
            workspace.on_close.append(lambda: _forget(key))
        return _AGENTS[key]


def _forget(key: tuple[int, str]) -> None:
    with _AGENTS_LOCK:
        _AGENTS.pop(key, None)


def _assistant(workspace: Workspace):
    from flexo.studio.assistant import Assistant

    with _AGENTS_LOCK:
        if workspace.assistant is None:
            workspace.assistant = Assistant(workspace)
        return workspace.assistant


def start(
    target: str | Path | None = None,
    *,
    port: int = 0,
    kind: str | None = None,
    browser: bool = True,
    trusted: bool = True,
    offered: tuple[str, ...] | None = None,
) -> tuple[ThreadingHTTPServer, Workspace]:
    """A studio server for a folder or a file in it (not yet serving: call ``serve_forever``).
    Code the folder brings runs only if it is ``trusted`` (the app asks; a person who
    starts ``flexo studio`` in a folder has chosen it). ``offered`` are the kinds of
    document the page offers to make (all, if not given)."""

    path = Path(target or ".").resolve()
    folder, start_file = (path, "") if path.is_dir() else (path.parent, path.name)
    workspace = Workspace(folder, kind=kind, trusted=trusted, offered=offered)
    handler = type("StudioHandler", (Handler,), {"workspace": workspace, "start_file": start_file})
    server = Server(("127.0.0.1", port), handler)
    if port:
        # On a port of its own choosing, a studio started again keeps its token: a page
        # left open on it goes on where it was.
        workspace.token = sessions.kept_token(folder, port, workspace.token)
    workspace.address = f"http://127.0.0.1:{server.server_address[1]}/"  # type: ignore[attr-defined]
    if start_file:
        workspace.address += f"?file={quote(start_file)}"  # type: ignore[attr-defined]
    sessions.register(folder, server.server_address[1], workspace.token)
    if browser:
        threading.Timer(0.3, webbrowser.open, (workspace.address,)).start()  # type: ignore[attr-defined]
    return server, workspace


def serve(
    target: str | Path | None = None,
    *,
    port: int = 0,
    kind: str | None = None,
    browser: bool = True,
) -> None:
    """Serve the studio for a folder, or a file in it (made when first changed), until stopped."""

    server, workspace = start(target, port=port, kind=kind, browser=browser)
    print(f"flexo studio: {workspace.address}")  # type: ignore[attr-defined]
    print(f"  folder {workspace.root} (Ctrl+C to stop)")
    print("  agents join with: claude mcp add flexo-studio -- flexo studio mcp")
    sys.stdout.flush()
    # Stopped as Ctrl+C stops it (a `kill`, a session ending): edits it has taken that are
    # not yet in their files are written first.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _interrupted)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        workspace.close()
        sessions.unregister(workspace.root, server.server_address[1])
        server.server_close()


def _interrupted(signum: int, frame: object) -> None:
    signal.signal(signum, signal.SIG_DFL)  # asked again, it stops at once
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None, *, kind: str | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["mcp"]:
        from flexo.studio.mcp import main as mcp_main

        return mcp_main(arguments[1:])
    parser = argparse.ArgumentParser(
        prog="flexo studio", description="Edit documents in the browser."
    )
    parser.add_argument("file", nargs="?", help="a document, or a folder (default: this folder)")
    parser.add_argument(
        "--port", type=int, default=0, help="the port to serve on (default: any free one)"
    )
    parser.add_argument(
        "--kind", default=kind, help="the kind of a new document (figure, deck, theme)"
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parsed = parser.parse_args(arguments)
    serve(parsed.file, port=parsed.port, kind=parsed.kind, browser=not parsed.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
