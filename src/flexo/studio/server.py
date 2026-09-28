"""The studio's server: the page, and the few calls it makes, on this machine only.

It serves one folder -- the one holding the document it was opened with -- and
reads and writes files only inside it. Every call carries a token the page is
given when it loads, and a request for another host name is refused, so neither
another site open in the browser nor a rebound domain name can reach it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import mimetypes
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Sequence
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import yaml

from flexo.studio import Kind, kinds

STATIC = Path(__file__).parent / "static"
IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", ".cache", ".ruff_cache"}
FILE_TYPES = {
    "image": (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"),
    "figure": (".yaml", ".yml", ".json"),
    "python": (".py",),
    "theme": (".yaml", ".yml", ".json"),
}


class Studio:
    """What the server keeps between calls: the folder, the kinds, the token, and
    for each open document the files its last drawing read."""

    def __init__(self, root: Path, *, kind: str | None = None) -> None:
        self.root = root.resolve()
        self.kinds = kinds()
        self.default_kind = kind
        self.token = secrets.token_urlsafe(24)
        self.drawing = threading.Lock()
        self.latest: dict[str, int] = {}
        self.depends: dict[Path, set[Path]] = {}
        self.written: dict[Path, float] = {}
        """When the studio itself last wrote each file, so its own saves are not news."""

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

    def kind_of(self, path: Path) -> Kind:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            try:
                parsed = (
                    json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
                )
            except (yaml.YAMLError, json.JSONDecodeError):
                parsed = None
            for kind in self.kinds.values():
                if kind.name != "figure" and kind.claims(parsed):
                    return kind
            if parsed is not None and self.kinds["figure"].claims(parsed):
                return self.kinds["figure"]
        if self.default_kind and self.default_kind in self.kinds:
            return self.kinds[self.default_kind]
        return self.kinds["figure"]

    # -- calls --

    def session(self, name: str) -> dict[str, Any]:
        path = self.path(name)
        kind = self.kind_of(path)
        exists = path.is_file()
        document = kind.load(path) if exists else kind.new(path)
        return {
            "file": self.relative(path),
            "name": path.name,
            "folder": str(self.root),
            "exists": exists,
            "kind": kind.name,
            "title": kind.title,
            "kinds": [{"name": item.name, "title": item.title} for item in self.kinds.values()],
            "document": document,
            "catalog": kind.catalog(),
        }

    def draw(
        self, name: str, document: Any, version: int, known: dict[str, str], hints: dict[str, Any]
    ) -> dict[str, Any]:
        path = self.path(name)
        kind = self.kind_of(path)
        # Each page open on the document counts its own drawings.
        client = f"{name}\0{hints.get('client', '')}"
        self.latest[client] = max(self.latest.get(client, 0), version)
        with self.drawing:
            if version < self.latest[client]:
                return {"version": version, "stale": True}
            started = time.perf_counter()
            try:
                drawing = kind.draw(document, path.parent, hints)
            except Exception as error:  # the page shows what went wrong, and stays up
                traceback.print_exc()
                return {
                    "version": version,
                    "pages": [],
                    "messages": [
                        {
                            "text": f"{type(error).__name__}: {error}",
                            "severity": "error",
                            "where": "",
                            "page": "",
                            "code": "studio.crash",
                        }
                    ],
                    "seconds": time.perf_counter() - started,
                }
            elapsed = time.perf_counter() - started
        self.depends[path] = {file.resolve() for file in drawing.files}
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
            "messages": [asdict(message) for message in drawing.messages],
            "info": drawing.info,
            "unfinished": drawing.unfinished,
            "seconds": elapsed,
        }

    def save(self, name: str, document: Any) -> dict[str, Any]:
        path = self.path(name)
        kind = self.kind_of(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        kind.save(path, document)
        self.written[path] = path.stat().st_mtime
        return {"ok": True, "file": self.relative(path)}

    def new(self, name: str, kind_name: str, data: Any = None) -> dict[str, Any]:
        """Make a file of a kind: its kind's starting document, or ``data`` (a parsed
        document of that kind) when given. An existing file is left as it is."""

        path = self.path(name)
        kind = self.kinds.get(kind_name)
        if kind is None:
            raise ValueError(f"no kind {kind_name}")
        if path.exists():
            if data is not None:
                raise FileExistsError(f"{name} already exists")
            return {"file": self.relative(path)}
        adopt = getattr(kind, "adopt", None)
        document = kind.new(path) if data is None else adopt(data) if adopt else data
        path.parent.mkdir(parents=True, exist_ok=True)
        kind.save(path, document)
        self.written[path] = path.stat().st_mtime
        return {"file": self.relative(path)}

    def export(self, name: str, document: Any, formats: list[str]) -> dict[str, Any]:
        path = self.path(name)
        kind = self.kind_of(path)
        with self.drawing:
            written = kind.export(document, path.parent, path.stem, formats)
        return {"files": [self.relative(file) for file in written]}

    def files(self, name: str, types: list[str]) -> dict[str, Any]:
        folder = self.path(name).parent
        suffixes = tuple(suffix for kind in types for suffix in FILE_TYPES.get(kind, ()))
        found: list[str] = []
        for file in sorted(_walk(folder, depth=4)):
            if file.suffix.lower() in suffixes:
                found.append(file.relative_to(folder).as_posix())
            if len(found) >= 500:
                break
        return {"files": found}

    def upload(self, name: str, filename: str, data: bytes) -> dict[str, Any]:
        folder = self.path(name).parent / "assets"
        clean = (
            "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._- ").strip()
            or "file"
        )
        target = folder / clean
        self.relative(target)  # inside the folder, or PermissionError
        stem, suffix, count = target.stem, target.suffix, 1
        while target.exists() and target.read_bytes() != data:
            count += 1
            target = target.with_name(f"{stem}-{count}{suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": target.relative_to(self.path(name).parent).as_posix()}

    def changes(self, name: str, since: dict[Path, float]) -> list[str]:
        """What has changed on disk since last looked: the document itself
        (``document``, unless the studio wrote it) or a file its drawing read (``depends``)."""

        path = self.path(name)
        events = []
        watched = {path, *self.depends.get(path, set())}
        for file in watched:
            try:
                stamp = file.stat().st_mtime
            except OSError:
                continue
            before = since.get(file)
            since[file] = stamp
            if before is None or stamp == before:
                continue
            if file == path:
                if self.written.get(path) != stamp:
                    events.append("document")
            else:
                events.append("depends")
        return sorted(set(events))


def _walk(folder: Path, depth: int):
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(".") or entry.name in IGNORED:
            continue
        if entry.is_dir():
            if depth > 0:
                yield from _walk(entry, depth - 1)
        else:
            yield entry


class Handler(BaseHTTPRequestHandler):
    studio: Studio
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
        if len(body) > 2048 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            encoding = "gzip"
        else:
            encoding = None
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: object, status: int = 200) -> None:
        self._reply(
            status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json"
        )

    def _fail(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in {"127.0.0.1", "localhost", "[::1]"}

    def _token_ok(self, query: dict[str, list[str]]) -> bool:
        given = self.headers.get("X-Studio-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(given, self.studio.token)

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
        self._reply(
            200, target.read_bytes(), f"{kind}; charset=utf-8" if kind.startswith("text") else kind
        )

    # -- routes --

    def do_GET(self) -> None:
        if not self._host_ok():
            self._fail(HTTPStatus.FORBIDDEN, "the studio answers on 127.0.0.1 and localhost only")
            return
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path
        if route == "/" or route == "/index.html":
            self._index(query)
        elif route.startswith("/static/studio/"):
            self._static(STATIC / "studio", route.removeprefix("/static/studio/"))
        elif route.startswith("/static/kinds/"):
            name, _, rest = route.removeprefix("/static/kinds/").partition("/")
            kind = self.studio.kinds.get(name)
            if kind is None:
                self._fail(HTTPStatus.NOT_FOUND, f"no kind {name}")
            else:
                self._static(Path(kind.static), rest)
        elif route.startswith("/api/"):
            if not self._token_ok(query):
                self._fail(HTTPStatus.FORBIDDEN, "missing or wrong studio token")
                return
            self._api_get(route, query)
        else:
            self._fail(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._host_ok() or not self._token_ok(query):
            self._fail(HTTPStatus.FORBIDDEN, "missing or wrong studio token")
            return
        body = self._body()
        try:
            if url.path == "/api/upload":
                self._json(self.studio.upload(_one(query, "file"), _one(query, "name"), body))
                return
            data = json.loads(body or b"{}")
            name = data.get("file", "")
            if url.path == "/api/draw":
                self._json(
                    self.studio.draw(
                        name,
                        data.get("document"),
                        int(data.get("version", 0)),
                        data.get("known") or {},
                        data.get("hints") or {},
                    )
                )
            elif url.path == "/api/save":
                self._json(self.studio.save(name, data.get("document")))
            elif url.path == "/api/new":
                self._json(self.studio.new(name, data.get("kind", ""), data.get("data")))
            elif url.path == "/api/export":
                self._json(
                    self.studio.export(name, data.get("document"), list(data.get("formats") or []))
                )
            else:
                self._fail(HTTPStatus.NOT_FOUND, "not found")
        except (BrokenPipeError, ConnectionResetError):
            raise
        except PermissionError as error:
            self._fail(HTTPStatus.FORBIDDEN, str(error))
        except FileExistsError as error:
            self._fail(HTTPStatus.CONFLICT, str(error))
        except (ValueError, FileNotFoundError) as error:
            # Something the document says (a missing file, a malformed block): the page shows it.
            self._fail(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            traceback.print_exc()
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    def _index(self, query: dict[str, list[str]]) -> None:
        name = (query.get("file") or [self.server.start_file])[0]  # type: ignore[attr-defined]
        page = (STATIC / "studio" / "index.html").read_text(encoding="utf-8")
        settings = json.dumps({"token": self.studio.token, "file": name})
        page = page.replace("/*STUDIO*/null", settings.replace("</", "<\\/"))
        self._reply(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _api_get(self, route: str, query: dict[str, list[str]]) -> None:
        try:
            if route == "/api/session":
                self._json(self.studio.session(_one(query, "file")))
            elif route == "/api/files":
                types = (query.get("types") or ["image"])[0].split(",")
                self._json(self.studio.files(_one(query, "file"), types))
            elif route == "/api/raw":
                self._raw(query)
            elif route == "/api/events":
                self._events(_one(query, "file"))
            else:
                self._fail(HTTPStatus.NOT_FOUND, "not found")
        except PermissionError as error:
            self._fail(HTTPStatus.FORBIDDEN, str(error))
        except FileNotFoundError as error:
            self._fail(HTTPStatus.NOT_FOUND, str(error))
        except Exception as error:
            traceback.print_exc()
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    def _raw(self, query: dict[str, list[str]]) -> None:
        """A file in the folder, named from the document's own folder (a picture a
        slide shows, an export to download)."""

        base = self.studio.path(_one(query, "file")).parent
        target = (base / _one(query, "path")).resolve()
        self.studio.relative(target)  # inside the folder, or PermissionError
        if not target.is_file():
            raise FileNotFoundError(f"no file {_one(query, 'path')}")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix.lower() == ".svg":
            kind = "image/svg+xml"
        self.send_response(200)
        data = target.read_bytes()
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

    def _events(self, name: str) -> None:
        """Server-sent events: ``document`` when the file changes on disk (not by the
        studio), ``depends`` when a file its drawing read changes."""

        self.studio.path(name)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        since: dict[Path, float] = {}
        self.studio.changes(name, since)
        beat = 0
        try:
            while True:
                time.sleep(0.4)
                for event in self.studio.changes(name, since):
                    self.wfile.write(f"event: {event}\ndata: {{}}\n\n".encode())
                    self.wfile.flush()
                beat += 1
                if beat % 30 == 0:
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def _one(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values:
        raise ValueError(f"missing {key}")
    return values[0]


def serve(
    file: str | Path | None = None,
    *,
    port: int = 0,
    kind: str | None = None,
    browser: bool = True,
) -> None:
    """Serve the studio for ``file`` (made when saved, if it does not exist) until interrupted."""

    target = Path(file or "figure.yaml").resolve()
    studio = Studio(target.parent, kind=kind)
    handler = type("StudioHandler", (Handler,), {"studio": studio})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    server.start_file = target.name  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{server.server_address[1]}/?file={quote(target.name)}"
    print(f"flexo studio: {url}")
    print(f"  editing {target} (Ctrl+C to stop)")
    sys.stdout.flush()
    if browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def main(argv: Sequence[str] | None = None, *, kind: str | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flexo studio", description="Edit a document in the browser."
    )
    parser.add_argument("file", nargs="?", help="the document to edit (made when first saved)")
    parser.add_argument(
        "--port", type=int, default=0, help="the port to serve on (default: any free one)"
    )
    parser.add_argument(
        "--kind", default=kind, help="the kind of a new document (figure, deck, ...)"
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    arguments = parser.parse_args(argv)
    serve(
        arguments.file, port=arguments.port, kind=arguments.kind, browser=not arguments.no_browser
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
