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
from flexo.studio.workspace import Workspace, walk

STATIC = Path(__file__).parent / "static"
FILE_TYPES = {
    "image": (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"),
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
        compressible = len(body) > 2048 and not kind.startswith("font/")
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
            self._fail(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            traceback.print_exc()
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

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
            doc = workspace.open(_one(query, "file"), (query.get("kind") or [None])[0])
            self._json({**doc.info(), "catalog": doc.kind.catalog()})
        elif route == "/api/documents":
            self._json({"documents": workspace.documents()})
        elif route == "/api/files":
            types = (query.get("types") or ["image"])[0].split(",")
            self._json(self._files(_one(query, "file"), types))
        elif route == "/api/raw":
            self._raw(query)
        elif route == "/api/events":
            self._events(_one(query, "client"), (query.get("name") or ["You"])[0])
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
            version, document = doc.update(data["document"], int(data["base"]), who, who["id"])
            self._json({"version": version, "document": document})
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
            if doc.write():
                workspace.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})
            self._json({"ok": True, "saved": doc.saved})
        elif route == "/api/new":
            doc = workspace.new(name, data.get("kind", ""), data.get("data"))
            self._json({"file": doc.name})
        elif route == "/api/export":
            doc = workspace.open(name)
            document = data.get("document", doc.document)
            with workspace.drawing:
                written = doc.kind.export(
                    document, doc.path.parent, doc.path.stem, list(data.get("formats") or [])
                )
            self._json({"files": [workspace.relative(file) for file in written]})
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
        elif route == "/api/presence":
            workspace.set_presence(who, data.get("file"), data.get("where"), data.get("doing"))
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
            "kinds": [
                {"name": kind.name, "title": kind.title} for kind in workspace.kinds.values()
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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": target.relative_to(self.workspace.path(name).parent).as_posix()}

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

    def _events(self, client: str, name: str) -> None:
        """Server-sent events: everything that happens in the workspace, as it happens."""

        who = {"id": client, "name": name, "kind": "person"}
        listener = self.workspace.listen(client, who)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b"event: hello\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = listener.events.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
                    continue
                if event is None:
                    return
                payload = json.dumps(event, ensure_ascii=False, default=str)
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.workspace.leave(listener)


def _one(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values:
        raise ValueError(f"missing {key}")
    return values[0]


def _person(data: dict[str, Any]) -> dict[str, Any]:
    who = data.get("who") or {}
    client = str(data.get("client") or who.get("id") or "someone")
    return {"id": client, "name": str(who.get("name") or "You"), "kind": "person"}


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
) -> tuple[ThreadingHTTPServer, Workspace]:
    """A studio server for a folder or a file in it (not yet serving: call ``serve_forever``)."""

    path = Path(target or ".").resolve()
    folder, start_file = (path, "") if path.is_dir() else (path.parent, path.name)
    workspace = Workspace(folder, kind=kind)
    handler = type("StudioHandler", (Handler,), {"workspace": workspace, "start_file": start_file})
    server = Server(("127.0.0.1", port), handler)
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        workspace.close()
        sessions.unregister(workspace.root, server.server_address[1])
        server.server_close()


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
