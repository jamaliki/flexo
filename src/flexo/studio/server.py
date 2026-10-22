"""The studio's server: the page, and the calls it and agents make, on this machine only.

It serves one folder and reads and writes files only inside it. Every call
carries a token the page is given when it loads (an agent finds it in the
studio's session file, readable only by its owner), and a request for another
host name is refused, so neither another site open in the browser nor a
rebound domain name can reach it.
"""

from __future__ import annotations

import argparse
import contextlib
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
import time
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
LEAVE_GRACE = 1.0
"""Seconds a window whose connection broke without a word is still taken as there: back by
then (a page reconnecting, half a second after: its ``retry``), its person never left. A window
closed says so as it goes (``/api/leave``), and goes at once."""
HANG_UP_CHECK = 0.25
"""How often, in seconds, a quiet connection is looked at for a window gone without a word
(crashed, killed, its browser closed under it)."""
FILE_TYPES = {
    "image": (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".heic",
              ".heif", ".avif", ".pdf", ".ai"),
    "figure": (".yaml", ".yml", ".json"),
    "python": (".py",),
    "theme": (".yaml", ".yml", ".json"),
    "structure": (".pdb", ".cif", ".mmcif", ".ent", ".json"),
}
"""The files each kind of thing is chosen from, by their endings. (A ``.json`` is a
structure only when it is a mol-sketch scene: ``_files``.)"""


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
        # Sent as it is, never compressed: the studio answers on this machine alone, where
        # gzip costs more than the bytes it saves -- a slide drawing a protein's surface is
        # 1.5 MB of SVG that compresses poorly, 65 milliseconds at every keystroke on it.
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400, immutable" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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
        elif route == "/api/drawing":
            self._json(self._drawing(query))
        elif route == "/api/drawn":
            self._drawn(query)
        elif route == "/api/picture":
            # A photograph a drawing names: its address carries its version, so it keeps.
            # (A GIF plays, or is shown still at a frame of it: ``still``, from 1.)
            path = workspace.path(_one(query, "path"))
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"} or not path.is_file():
                raise FileNotFoundError(f"no picture {_one(query, 'path')}")
            from flexo.animated import still_frame
            from flexo.studio import pictures

            still = still_frame((query.get("still") or ["0"])[0]) if query.get("still") else 0
            body, kind = pictures.shown(path, still)
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
        elif route == "/api/assistant/models":
            self._json(_assistant(workspace).models(_one(query, "provider")))
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
                self._fail(HTTPStatus.CONFLICT, doc.problem or f"Can\u2019t read {doc.name}")
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
            # A bundle's: the bundle written now, not once things are quiet, and named -- a
            # Save is saved in the file its person sees (flexo.studio.bundles).
            keeper = getattr(workspace, "bundle", None)
            answer = {"ok": True, "saved": doc.saved}
            if keeper is not None:
                keeper.save()
                if keeper.problem is None:
                    answer["bundle"] = keeper.path.name
            self._json(answer)
        elif route == "/api/mend":
            # A file that does not read, put right by its person where the studio shows it.
            workspace.open(name).mend(str(data.get("text", "")), over=bool(data.get("over")))
            self._json({"ok": True})
        elif route == "/api/new":
            doc = workspace.new(name, data.get("kind", ""), data.get("data"), who)
            self._json({"file": doc.name})
        elif route == "/api/rename":
            # The File menu's Rename: the file renamed, the open document following it.
            self._json({"file": workspace.rename(name, str(data.get("to") or ""), who)})
        elif route == "/api/duplicate":
            # The File menu's Duplicate: a copy beside it, opened.
            self._json({"file": workspace.duplicate(name, str(data.get("to") or ""), who).name})
        elif route == "/api/export":
            self._export(workspace.open(name), data)
        elif route == "/api/copy":
            # What the page copies, drawn for other apps: its picture and its SVG.
            from flexo.studio import copying

            self._json(copying.answer(workspace, data))
        elif route == "/api/import-drawing":
            # A drawing pasted or dropped, made the page's own shapes (flexo.svgimport).
            from flexo.studio.importing import imported

            self._json(imported(workspace, name, data))
        elif route == "/api/act":
            # An edit the page asks the document's kind to make (a figure's parts added,
            # connected, renamed): the kind answers with the document as it would be.
            doc = workspace.open(name)
            act = getattr(doc.kind, "act", None)
            if act is None:
                self._fail(HTTPStatus.NOT_FOUND, f"a {doc.kind.title.lower()} takes no such edits")
                return
            workspace.acting(name, data.get("action") or {})
            if workspace.set_aside and "document" in data:
                # A file taken out of a bundle as no document named it, named again by the
                # page's document (an embedding undone, not yet sent): back before it is read.
                with contextlib.suppress(Exception):
                    workspace.follow_uploads([(doc.path.parent, data["document"])])
            # (A design's previews are drawings: drawn as the document's are, its own Python
            # run only once the folder is trusted.)
            drawing = (data.get("action") or {}).get("do") == "previews"
            with workspace.running() if drawing else contextlib.nullcontext():
                answer = act(data.get("document", doc.document), data.get("action") or {},
                             doc.path.parent)
            if isinstance(answer, dict) and "released" in answer:
                # Files the edit leaves the document no longer needing (a figure file whose
                # figure went into the deck): a bundle's own, taken out of it once no document
                # names them -- a folder's, its person's, left be.
                answer = dict(answer)
                workspace.release([Path(str(file)) for file in answer.pop("released") or []])
            if isinstance(answer, dict) and "uploaded" in answer:
                # Files the edit copied into the folder (slides pasted from another deck, with
                # theirs): the studio's copies, taken away again if nothing comes to use them.
                answer = dict(answer)
                for file in answer.pop("uploaded") or []:
                    with contextlib.suppress(PermissionError):
                        workspace.relative(Path(str(file)))
                        workspace.uploads.add(Path(str(file)).resolve())
            self._json(answer)
        elif route == "/api/theme/use":
            from flexo.studio import theming

            targets = [str(target) for target in data.get("targets") or []]
            self._json({"documents": theming.use(workspace, name, targets, who)})
        elif route == "/api/trust":
            workspace.trust()
            self._json({"ok": True})
        elif route == "/api/bundle/new":
            # New Deck: a bundle of its own, beside the folder's documents (beside the bundle
            # edited here, for one), opened in a studio of its own for a tab of its own.
            from flexo.studio.bundles import new_bundle, open_beside

            keeper = getattr(workspace, "bundle", None)
            folder = keeper.path.parent if keeper is not None else workspace.root
            stem = str(data.get("name") or "").strip()
            if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
                raise ValueError("Enter a name.")
            made = new_bundle(folder / stem, str(data.get("kind") or "deck"))
            address = open_beside(workspace, made)
            self._json({"path": str(made), "name": made.name, "address": address})
        elif route == "/api/bundle/unpack":
            # File > Unpack Bundle: the bundle edited here, written out as a plain folder.
            from flexo.studio.bundles import unpack_beside

            self._json({"folder": str(unpack_beside(workspace))})
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
        elif route == "/api/assistant/provider":
            model = data.get("model")
            why = _assistant(workspace).choose(
                str(data.get("provider") or ""), None if model is None else str(model)
            )
            if why:
                self._fail(HTTPStatus.CONFLICT, why)
            else:
                self._json({"ok": True})
        else:
            self._fail(HTTPStatus.NOT_FOUND, "not found")

    def _session(self) -> dict[str, Any]:
        workspace = self.workspace
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
            "assistant": _assistant(workspace).state(),
            "start": self.start_file,
            # A bundle (one .flexo file) edited here: named as it is (flexo.studio.bundles).
            "bundle": workspace.bundle.info() if getattr(workspace, "bundle", None) else None,
        }

    def _files(self, name: str, types: list[str]) -> dict[str, Any]:
        folder = self.workspace.path(name).parent
        from flexo.structures import is_scene

        suffixes = tuple(suffix for kind in types for suffix in FILE_TYPES.get(kind, ()))
        # A .json chosen as a structure is a mol-sketch scene, not a figure or a theme.
        any_json = any(".json" in FILE_TYPES.get(kind, ()) for kind in types if kind != "structure")
        found = [
            file.relative_to(folder).as_posix()
            for file in sorted(walk(folder))
            if file.suffix.lower() in suffixes
            and (file.suffix.lower() != ".json" or any_json or is_scene(file))
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
        target = folder / _named_as_it_is(clean, data)
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
        if formats == ["flexo"]:
            # A bundle: the document and every file it names, as one file (flexo.bundle).
            from flexo.studio.bundles import exported

            def write(document, base, stem, formats, into=None):
                made, doc.kind.export_notes = exported(
                    workspace, doc, document, into or base / "build"
                )
                return [made]

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

    def _picture_file(self, query: dict[str, list[str]]) -> Path:
        """A picture in the folder, named from a document's own folder."""

        base = self.workspace.path(_one(query, "file")).parent
        target = (base / _one(query, "path")).resolve()
        self.workspace.relative(target)  # inside the folder, or PermissionError
        if not target.is_file():
            raise FileNotFoundError(f"no file {_one(query, 'path')}")
        return target

    def _drawing(self, query: dict[str, list[str]]) -> dict[str, object]:
        """An SVG picture's texts and colours as its file has them, for its panel to show
        and change (``flexo.restyle.described``); none for a photograph, or an SVG that
        does not read -- and a GIF's ``animation``. ``stamp``: when the file last changed."""

        from flexo.artwork import load_artwork
        from flexo.diagnostics import FlexoError
        from flexo.restyle import described

        target = self._picture_file(query)
        stamp = target.stat().st_mtime_ns
        if target.suffix.lower() == ".gif":
            # How it plays, for its panel to say: its frames, and the seconds they take.
            from flexo.animated import animation

            played = animation(target)
            shown = {"frames": played.frames, "seconds": played.seconds} if played else None
            return {"texts": [], "colours": [], "stamp": stamp, "animation": shown}
        if target.suffix.lower() != ".svg":
            return {"texts": [], "colours": [], "stamp": stamp}
        try:
            return {**described(load_artwork("drawing", str(target))), "stamp": stamp}
        except FlexoError as error:
            return {"texts": [], "colours": [], "stamp": stamp, "problem": explain(error)}

    def _drawn(self, query: dict[str, list[str]]) -> None:
        """An SVG picture as a slide draws it -- its words in ``family`` (the deck's figure
        font) or as ``font`` says, its ``texts`` and ``colours`` (JSON) changed -- carrying
        the faces it is drawn in: its thumbnail, an ``<img>`` the page's faces do not reach."""

        from flexo.artwork import load_artwork
        from flexo.restyle import restyle_of, restyled

        target = self._picture_file(query)

        def given(name: str) -> object:
            words = (query.get(name) or [""])[0]
            return json.loads(words) if words else None

        font = (query.get("font") or [""])[0] or None
        restyle = restyle_of(font, given("texts"), given("colours"))
        family = (query.get("family") or [""])[0] or "IBM Plex Sans"
        art = restyled(load_artwork("drawing", str(target)), restyle, family, embed=True)
        data = art.markup.encode("utf-8") if art.format == "svg" else target.read_bytes()
        self.send_response(200)
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", "image/svg+xml" if art.format == "svg" else kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
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
            quiet = time.monotonic()
            while True:
                try:
                    event = listener.events.get(timeout=HANG_UP_CHECK)
                except queue.Empty:
                    # A window gone without a word (crashed, killed) has closed its end:
                    # seen in a moment, not at the next heartbeat that fails.
                    if self._hung_up():
                        return
                    if time.monotonic() - quiet >= 15:
                        quiet = time.monotonic()
                        self.wfile.write(b": still here\n\n")
                        self.wfile.flush()
                    continue
                if event is None:
                    return
                quiet = time.monotonic()
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


_SUFFIX_OF = {
    "png": (".png",),
    "jpeg": (".jpg", ".jpeg"),
    "gif": (".gif",),
    "webp": (".webp",),
    "tiff": (".tiff", ".tif"),
    "bmp": (".bmp",),
    "heic": (".heic", ".heif"),
    "avif": (".avif",),
}
"""The names each kind of photograph goes by, its usual one first."""


def _named_as_it_is(name: str, data: bytes) -> str:
    """A photograph's file name with the ending of what its bytes are: a PNG copied from a web
    page under a ``.jpg`` address is saved as ``.png``. Other files keep their names."""

    from flexo.artwork import RASTER_SUFFIXES, _sniffed

    path = Path(name)
    if path.suffix.lower() not in RASTER_SUFFIXES:
        return name
    kind = _sniffed(data[:64])
    endings = _SUFFIX_OF.get(kind or "")
    if not endings or path.suffix.lower() in endings:
        return name
    return f"{path.stem}{endings[0]}"


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
    trusted: bool | None = None,
    offered: tuple[str, ...] | None = None,
) -> tuple[ThreadingHTTPServer, Workspace]:
    """A studio server for a folder or a file in it (not yet serving: call ``serve_forever``),
    or a bundle (``.flexo``). Code the folder brings runs only if it is ``trusted`` (the app
    asks; a person who starts ``flexo studio`` in a folder has chosen it, but a bundle is
    trusted only once its person has said so). ``offered`` are the kinds of document the
    page offers to make (all, if not given)."""

    path = Path(target or ".").resolve()
    if path.suffix.lower() == ".flexo" and not path.exists():
        # A bundle that is not there yet: made, holding a new document (a deck, unless
        # ``kind`` says), as a new deck is made by default -- one file, to keep and to send.
        from flexo.studio import kinds
        from flexo.studio.bundles import new_bundle

        new_bundle(path, kind or ("deck" if "deck" in kinds() else "figure"))
        trusted = True if trusted is None else trusted  # (made here, by its person)
    folder, start_file = (path, "") if path.is_dir() else (path.parent, path.name)
    keeper = None
    if path.suffix.lower() == ".flexo":
        # A bundle: unpacked into a folder of its own, edited there, saved back into it.
        from flexo.studio.bundles import opened

        keeper = opened(path)
        folder, start_file = keeper.root, keeper.document
        # Someone else's until its person trusts it: its Python runs only then. (Another
        # bundle put in its place is asked about again.)
        trusted = (keeper.trusted if trusted is None else trusted) and not keeper.replaced
    workspace = Workspace(folder, kind=kind, trusted=trusted is not False, offered=offered)
    if keeper is not None:
        keeper.attach(workspace)
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
    if start_file:  # (drawn while the page loads: flexo.studio.warmup)
        from flexo.studio.warmup import warm

        warm(workspace, start_file)
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
    keeper = getattr(workspace, "bundle", None)
    if keeper is not None:
        print(f"  bundle {keeper.path}, saved as it is edited (Ctrl+C to stop)")
    else:
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
    parser.add_argument(
        "file",
        nargs="?",
        help="a document, a folder (default: this folder), or a bundle (.flexo: made, with a new "
        "document in it, if it is not there)",
    )
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
