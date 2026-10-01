"""The studio serves one folder to the page that knows its token, draws figures and
themes, and keeps everyone editing a document -- pages, agents, the file on disk -- in step."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

from flexo.studio import kinds
from flexo.studio.agent import Tools
from flexo.studio.assistant import Assistant
from flexo.studio.figure_kind import NEW_FIGURE, FigureKind
from flexo.studio.server import start
from flexo.studio.theme_kind import ThemeKind
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace]]:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def call(
    url: str, token: str | None, body: object = None, *, host: str | None = None
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Studio-Token"] = token
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with OPENER.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_for(condition, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("waited in vain")


# -- the server --------------------------------------------------------------------------


def test_the_page_carries_the_token_and_calls_need_it(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    page = OPENER.open(f"{base}/").read().decode()
    assert re.search(r'"token": "([^"]+)"', page).group(1) == workspace.token  # type: ignore[union-attr]
    assert call(f"{base}/api/open?file=figure.yaml", None)[0] == 403
    assert call(f"{base}/api/open?file=figure.yaml", "wrong")[0] == 403
    status, opened = call(f"{base}/api/open?file=figure.yaml", workspace.token)
    assert status == 200 and opened["kind"] == "figure" and "nodes:" in opened["document"]["text"]
    status, session = call(f"{base}/api/session", workspace.token)
    assert {item["file"] for item in session["documents"]} == {"figure.yaml"}
    assert session["start"] == "figure.yaml"


def test_another_host_name_is_refused(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    assert call(f"{base}/api/session", workspace.token, host="evil.example")[0] == 403


def test_files_outside_the_folder_are_refused(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    status, body = call(
        f"{base}/api/new", workspace.token, {"file": "../escape.yaml", "kind": "figure"}
    )
    assert status == 403 and "outside" in body["error"]
    assert not (workspace.root.parent / "escape.yaml").exists()


def test_a_figure_is_drawn_and_sent_only_when_changed(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    document = {"text": NEW_FIGURE.replace("Encoder", "Decoder")}
    request = {"file": "figure.yaml", "document": document, "version": 1, "known": {}, "hints": {}}
    status, drawn = call(f"{base}/api/draw", workspace.token, request)
    assert status == 200 and not drawn["unfinished"]
    (page,) = drawn["pages"]
    assert "Decoder" in page["svg"]
    assert page["outline"]["root"]["type"] == "group"
    request.update(version=2, known={page["id"]: page["hash"]})
    assert "svg" not in call(f"{base}/api/draw", workspace.token, request)[1]["pages"][0]


def test_drawings_name_the_fonts_the_page_loads_once(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    request = {"file": "figure.yaml", "document": {"text": NEW_FIGURE}, "version": 1, "known": {}}
    (page,) = call(f"{base}/api/draw", workspace.token, {**request, "hints": {}})[1]["pages"]
    assert "@font-face" not in page["svg"] and "font-family" in page["svg"]
    with OPENER.open(f"{base}/") as response:
        assert 'href="/fonts/faces.css"' in response.read().decode()
    with OPENER.open(f"{base}/fonts/faces.css") as response:
        css = response.read().decode()
    assert "font-family:'Figtree'" in css and "url(/fonts/0)" in css
    with OPENER.open(f"{base}/fonts/0") as response:
        assert response.headers["Content-Type"].startswith("font/")
        assert "max-age" in response.headers["Cache-Control"] and len(response.read()) > 10_000
    # Outside the studio a drawing still carries its fonts.
    assert "@font-face" in FigureKind().draw({"text": NEW_FIGURE}, workspace.root).pages[0].svg


def test_an_update_is_saved_and_told_to_everyone(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    listener = workspace.listen("page-b", {"id": "page-b", "name": "Bo", "kind": "person"})
    document = {"text": NEW_FIGURE.replace("Encoder", "Decoder")}
    status, result = call(
        f"{base}/api/update",
        workspace.token,
        {"file": "figure.yaml", "base": 1, "document": document, "client": "page-a", "who": PERSON},
    )
    assert status == 200 and result["version"] == 2
    event = listener.events.get(timeout=2)
    assert event["type"] == "doc" and event["who"]["name"] == "Ada" and event["version"] == 2
    wait_for(lambda: "Decoder" in (workspace.root / "figure.yaml").read_text(encoding="utf-8"))


def test_a_new_file_is_made_from_its_kind_or_given_data(served: tuple[str, Workspace]) -> None:
    base, workspace = served
    status, made = call(
        f"{base}/api/new", workspace.token, {"file": "figures/a.yaml", "kind": "figure"}
    )
    assert status == 200 and made["file"] == "figures/a.yaml"
    assert (workspace.root / "figures/a.yaml").read_text(encoding="utf-8") == NEW_FIGURE
    data = {"figure": {"id": "given"}, "nodes": [{"id": "n", "label": "N"}]}
    assert (
        call(
            f"{base}/api/new",
            workspace.token,
            {"file": "figures/a.yaml", "kind": "figure", "data": data},
        )[0]
        == 409
    )
    assert (
        call(
            f"{base}/api/new", workspace.token, {"file": "b.yaml", "kind": "figure", "data": data}
        )[0]
        == 200
    )
    assert "id: given" in (workspace.root / "b.yaml").read_text(encoding="utf-8")


def test_pictures_beside_the_document_are_listed_and_uploaded(
    served: tuple[str, Workspace],
) -> None:
    base, workspace = served
    (workspace.root / "pictures").mkdir()
    (workspace.root / "pictures" / "a.png").write_bytes(b"png")
    (workspace.root / "build").mkdir()
    (workspace.root / "build" / "skip.png").write_bytes(b"png")
    assert call(f"{base}/api/files?file=figure.yaml&types=image", workspace.token)[1]["files"] == [
        "pictures/a.png"
    ]
    request = urllib.request.Request(
        f"{base}/api/upload?file=figure.yaml&name=../../photo.png",
        data=b"data",
        headers={"X-Studio-Token": workspace.token},
    )
    assert json.loads(OPENER.open(request).read())["path"] == "assets/photo.png"
    assert (workspace.root / "assets" / "photo.png").read_bytes() == b"data"


# -- people and agents at once ------------------------------------------------------------


def test_edits_from_two_places_made_at_once_are_both_kept(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        first = NEW_FIGURE.replace("Input $x$", "Input $x_0$")
        second = NEW_FIGURE.replace("Output $y$", "Output $\\hat{y}$")
        doc.update({"text": first}, 1, PERSON)
        version, merged = doc.update(
            {"text": second}, 1, {"id": "agent", "name": "Claude", "kind": "agent"}
        )
        assert version == 3
        assert "$x_0$" in merged["text"] and "\\hat{y}" in merged["text"]
    finally:
        workspace.close()


def test_the_file_changed_on_disk_is_taken_in_and_kept_with_unsaved_edits(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        agent = {"id": "mcp:claude-code", "name": "Claude Code", "kind": "agent"}
        workspace.set_presence(agent, "figure.yaml", None, "Renaming things")
        listener = workspace.listen("page", PERSON)
        # An edit here, not yet written, and the agent writes the file with its own tools.
        doc.update({"text": NEW_FIGURE.replace("Encoder", "Encoder, here")}, 1, PERSON)
        time.sleep(0.02)
        (tmp_path / "figure.yaml").write_text(
            NEW_FIGURE.replace("Output $y$", "Output, there"), encoding="utf-8"
        )
        wait_for(lambda: "Output, there" in doc.document["text"])
        assert "Encoder, here" in doc.document["text"]
        events = []
        while not listener.events.empty():
            events.append(listener.events.get())
        assert any(
            event["type"] == "doc" and event["who"]["name"] == "Claude Code" for event in events
        )
        wait_for(lambda: "Encoder, here" in (tmp_path / "figure.yaml").read_text(encoding="utf-8"))
    finally:
        workspace.close()


def test_a_file_on_disk_that_does_not_read_is_reported_and_ours_kept(tmp_path: Path) -> None:
    theme = tmp_path / "lab.yaml"
    theme.write_text("theme: {name: lab, base: paper}\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("lab.yaml")
        theme.write_text("theme: {name: lab, base: [\n", encoding="utf-8")
        wait_for(lambda: doc.problem is not None)
        assert doc.document == {"theme": {"name": "lab", "base": "paper"}}
    finally:
        workspace.close()


def test_the_agent_tools_read_edit_and_look(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        tools = Tools(workspace, {"id": "agent", "name": "Claude"})
        listed, failed = tools.call("list_documents", {})
        assert not failed and "figure.yaml: figure" in listed[0]["text"]
        opened, _ = tools.call("open_document", {"file": "figure.yaml"})
        assert "flexo figure file" in opened[0]["text"] and "version 1" in opened[1]["text"]
        blocks, failed = tools.call(
            "edit_document",
            {"file": "figure.yaml", "old": "label: Encoder", "new": "label: Decoder"},
        )
        assert not failed and "version 2" in blocks[0]["text"]
        blocks, failed = tools.call(
            "edit_document", {"file": "figure.yaml", "old": "label: Nothing", "new": "x"}
        )
        assert failed and "does not occur" in blocks[0]["text"]
        blocks, failed = tools.call(
            "edit_document", {"file": "figure.yaml", "old": "kind: text", "new": "kind: text"}
        )
        assert failed and "occurs 2 times" in blocks[0]["text"]
        looked, failed = tools.call("look", {"file": "figure.yaml"})
        assert not failed
        image = next(block for block in looked if block["type"] == "image")
        assert image["source"]["media_type"] == "image/png" and len(image["source"]["data"]) > 1000
        _, failed = tools.call("open_document", {"file": "themes/new.yaml", "kind": "theme"})
        assert not failed and (tmp_path / "themes/new.yaml").is_file()
        assert tools.call("status", {"doing": "Looking around"})[1] is False
        assert workspace.present()[0]["doing"] == "Looking around"
        notes = [entry["text"] for entry in workspace.activity]
        assert "edited line 10" in notes
    finally:
        workspace.close()


def test_an_agent_speaks_mcp_to_the_studio_open_on_its_folder(
    served: tuple[str, Workspace],
) -> None:
    from flexo.studio.mcp import serve

    _, workspace = served
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-code"}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "edit_document",
                "arguments": {"file": "figure.yaml", "old": "Encoder", "new": "Decoder"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "look", "arguments": {"file": "figure.yaml"}},
        },
    ]
    out = io.StringIO()
    serve(workspace.root, io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [answer["id"] for answer in answers] == [1, 2, 3, 4]
    assert answers[0]["result"]["protocolVersion"] == "2025-06-18"
    assert "look" in {tool["name"] for tool in answers[1]["result"]["tools"]}
    assert not answers[2]["result"]["isError"]
    assert any(item["type"] == "image" for item in answers[3]["result"]["content"])
    assert "Decoder" in workspace.open("figure.yaml").document["text"]
    assert workspace.present()[0]["who"]["name"] == "Claude Code"


# -- the assistant, with a stand-in for the API ------------------------------------------


class _Stream:
    def __init__(self, text: str, tools: list[tuple[str, dict]]) -> None:
        self.text, self.tools = text, tools

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield NS(type="text", text=self.text)

    def get_final_message(self):
        content = [_block(type="text", text=self.text)]
        content += [
            _block(type="tool_use", id=f"toolu_{i}", name=name, input=args)
            for i, (name, args) in enumerate(self.tools)
        ]
        return NS(content=content, stop_reason="tool_use" if self.tools else "end_turn")


def _block(**fields):
    return NS(**fields, model_dump=lambda **_: dict(fields))


class _Client:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **request):
        self.requests.append(request)
        return _Stream(*self.script.pop(0))


def test_the_assistant_edits_through_the_tools_and_says_so_to_everyone(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        client = _Client(
            [
                (
                    "I'll rename it.",
                    [
                        (
                            "edit_document",
                            {"file": "figure.yaml", "old": "Encoder", "new": "Decoder"},
                        )
                    ],
                ),
                ("Renamed.", []),
            ]
        )
        assistant = Assistant(workspace, client=client)
        listener = workspace.listen("page", PERSON)
        assistant.ask("Rename the encoder", {"file": "figure.yaml"}, PERSON)
        wait_for(lambda: not assistant.running)
        assert "Decoder" in workspace.open("figure.yaml").document["text"]
        first = client.requests[0]
        assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
        assert all(tool.get("eager_input_streaming") for tool in first["tools"])
        assert "figure.yaml" in first["messages"][0]["content"][0]["text"]
        history = client.requests[1]["messages"]
        results = [
            block
            for message in history
            if message["role"] == "user"
            for block in message["content"]
            if block["type"] == "tool_result"
        ]
        assert len(results) == 1 and "version 2" in results[0]["content"][0]["text"]
        turn = assistant.transcript[-1]
        assert [part["type"] for part in turn["parts"]] == ["text", "tool", "text"]
        assert turn["parts"][1]["state"] == "done"
        events = []
        while not listener.events.empty():
            events.append(listener.events.get())
        assert {"user", "turn", "text", "tool", "idle"} <= {
            e.get("event") for e in events if e["type"] == "assistant"
        }
        assert any(e["type"] == "doc" and e["who"]["name"] == "Claude" for e in events)
    finally:
        workspace.close()


# -- keeping files safe ----------------------------------------------------------------------


def test_a_save_cut_short_leaves_the_file_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        doc.update({"text": NEW_FIGURE.replace("Encoder", "Changed")}, doc.version, PERSON)

        def full(path: Path, document: dict) -> None:
            path.write_text(document["text"][:20])
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(doc.kind, "save", full)
        workspace.flush()
        assert (tmp_path / "figure.yaml").read_text() == NEW_FIGURE
        assert "could not be saved: no space left on device" in (doc.problem or "")
        assert [path.name for path in tmp_path.iterdir()] == ["figure.yaml"]
    finally:
        monkeypatch.undo()
        workspace.close()
    assert "Changed" in (tmp_path / "figure.yaml").read_text()  # written once it could be


def test_a_file_that_cannot_be_written_does_not_stop_the_others(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(NEW_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        for name in ("a.yaml", "b.yaml"):
            doc = workspace.open(name)
            doc.update({"text": NEW_FIGURE.replace("Encoder", "Changed")}, doc.version, PERSON)
        (tmp_path / "a.yaml").unlink()
        (tmp_path / "a.yaml").mkdir()  # a folder where the file was: it cannot be written
        workspace.flush()
        assert "Changed" in (tmp_path / "b.yaml").read_text()
        assert "could not be saved" in (workspace.open("a.yaml").problem or "")
    finally:
        workspace.close()


def test_odd_files_in_the_folder_do_not_stop_it_opening(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(NEW_FIGURE)
    (tmp_path / "date.yaml").write_text("released: 2024-02-30\n")
    (tmp_path / "deep.json").write_text("[" * 5000 + "]" * 5000)
    (tmp_path / "binary.yaml").write_bytes(bytes(range(256)))
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "other.yaml").write_text(NEW_FIGURE)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    (tmp_path / "loop").mkdir()
    (tmp_path / "loop" / "again").symlink_to(tmp_path, target_is_directory=True)
    workspace = Workspace(tmp_path)
    try:
        assert [entry["file"] for entry in workspace.documents()] == ["figure.yaml"]
    finally:
        workspace.close()


def test_a_document_of_endless_aliases_is_refused(tmp_path: Path) -> None:
    letters = "abcdefghij"
    lines = ["a: &a [x, x, x, x, x, x, x, x, x, x]"]
    for index in range(1, 9):
        refs = ", ".join([f"*{letters[index - 1]}"] * 10)
        lines.append(f"{letters[index]}: &{letters[index]} [{refs}]")
    lines.append("theme: {name: bomb, notes: *i}")
    (tmp_path / "bomb.yaml").write_text("\n".join(lines) + "\n")
    workspace = Workspace(tmp_path)
    try:
        with pytest.raises(ValueError, match="too large"):
            workspace.open("bomb.yaml")
    finally:
        workspace.close()


def test_one_file_named_two_ways_is_one_document(tmp_path: Path) -> None:
    import unicodedata

    name = unicodedata.normalize("NFD", "résumé.yaml")
    (tmp_path / name).write_text(NEW_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        first = workspace.open(name)
        again = workspace.open(unicodedata.normalize("NFC", "résumé.yaml"))
        assert first is again
    finally:
        workspace.close()


def test_two_studios_on_one_folder_are_both_found_until_each_closes(tmp_path: Path) -> None:
    from flexo.studio import sessions

    first, _ = start(tmp_path, browser=False)
    second, _ = start(tmp_path, browser=False)
    ports = [first.server_address[1], second.server_address[1]]
    try:
        assert sessions.find(tmp_path)["port"] in ports
        sessions.unregister(tmp_path, ports[1])
        assert sessions.find(tmp_path)["port"] == ports[0]
        sessions.unregister(tmp_path, ports[0])
        assert sessions.find(tmp_path) is None
    finally:
        first.server_close()
        second.server_close()


def test_a_folder_is_trusted_to_run_its_code_when_its_person_says(tmp_path: Path) -> None:
    from flexo.studio import code_allowed, folder_root

    server, workspace = start(tmp_path, browser=False, trusted=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        listener = workspace.listen("page", PERSON)
        assert call(f"{url}/api/session", workspace.token)[1]["trusted"] is False
        with workspace.running():
            assert code_allowed.get() is False and folder_root.get() == tmp_path.resolve()
        assert code_allowed.get() is True and folder_root.get() is None
        assert call(f"{url}/api/trust", workspace.token, {})[0] == 200
        assert call(f"{url}/api/session", workspace.token)[1]["trusted"] is True
        events = [listener.events.get(timeout=2) for _ in range(listener.events.qsize())]
        assert {"type": "trusted"} in events
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_a_figure_drawn_in_the_studio_reads_no_file_outside_the_folder(tmp_path: Path) -> None:
    import struct
    import zlib

    folder = tmp_path / "sent"
    folder.mkdir()

    def png(path: Path) -> None:
        rows = b"\x00\xff\x00\x00"
        chunk = lambda kind, data: (  # noqa: E731
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )
        header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                         + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))

    png(tmp_path / "private.png")
    png(folder / "own.png")
    figure = (
        "figure: {id: f}\nnodes:\n"
        "- {id: a, kind: image, label: A, properties: {source: %s}}\n"
    )
    workspace = Workspace(folder)
    try:
        for source, allowed in ((folder / "own.png", True), (tmp_path / "private.png", False)):
            name = f"{source.stem}.yaml"
            (folder / name).write_text(figure % source)
            doc = workspace.open(name)
            drawn = workspace.draw(name, doc.document, 1, {}, {})
            refused = any("outside the folder" in m["text"] for m in drawn["messages"])
            assert refused is not allowed, drawn["messages"]
    finally:
        workspace.close()


def test_a_photograph_is_sent_to_the_page_once_by_address_and_exported_whole(
    tmp_path: Path,
) -> None:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    rows = (b"\x00" + b"\x33\x66\xaa" * 600) * 400
    header = struct.pack(">IIBBBBB", 600, 400, 8, 2, 0, 0, 0)
    (tmp_path / "photo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    (tmp_path / "figure.yaml").write_text(
        "figure: {id: f}\nnodes:\n"
        "- {id: a, kind: image, label: A, properties: {source: photo.png}}\n"
    )
    server, workspace = start(tmp_path, browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        doc = workspace.open("figure.yaml")
        svg = workspace.draw("figure.yaml", doc.document, 1, {}, {})["pages"][0]["svg"]
        assert "data:image" not in svg and "/api/picture?" in svg
        found = re.search(r'href="(/api/picture\?[^"]+)"', svg)
        with OPENER.open(url + found.group(1).replace("&amp;", "&")) as response:
            assert response.headers["Cache-Control"].endswith("immutable")
            assert response.read().startswith(b"\x89PNG")
        body = {"file": "figure.yaml", "formats": ["editable"]}
        exported = call(f"{url}/api/export", workspace.token, body)[1]["files"]
        written = (tmp_path / exported[0]).read_text()
        assert "data:image/png;base64," in written and "/api/picture" not in written
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


# -- themes --------------------------------------------------------------------------------


def test_a_theme_is_drawn_on_samples_and_its_changes_named(tmp_path: Path) -> None:
    kind = ThemeKind()
    document = {
        "theme": {"name": "studio-test", "base": "paper", "palette": ["#8b1e3f", "#1d4e89"]}
    }
    drawing = kind.draw(document, tmp_path, {})
    assert [page.id for page in drawing.pages] == ["sample", "slice"]
    assert drawing.info["effective"]["palette"][:2] == ["#8b1e3f", "#1d4e89"]
    assert drawing.info["tones"][0]["stroke"].startswith("#")
    assert kind.describe({"theme": {"name": "a"}}, document)[0]["text"] == "changed the name"
    assert kind.check({"theme": {"name": "x", "colours": []}}, tmp_path)
    assert "arrow_shape" in kind.catalog()["choices"]


def test_a_theme_file_changed_is_read_again(tmp_path: Path) -> None:
    from flexo.theme_files import register_theme
    from flexo.themes import resolve_palette

    path = tmp_path / "lab.yaml"
    path.write_text(
        yaml.safe_dump({"theme": {"name": "lab-reread", "base": "paper", "palette": ["#111111"]}})
    )
    assert register_theme(path) == "lab-reread"
    first = resolve_palette("lab-reread").get("tone-1-stroke")
    time.sleep(0.01)
    path.write_text(
        yaml.safe_dump({"theme": {"name": "lab-reread", "base": "paper", "palette": ["#ee0000"]}})
    )
    register_theme(path)
    assert resolve_palette("lab-reread").get("tone-1-stroke") != first


def test_the_themes_offered_are_the_folder_s_files_then_flexo_s_own(tmp_path: Path) -> None:
    from flexo.studio import theming

    (tmp_path / "lab.theme.yaml").write_text(
        yaml.safe_dump({"theme": {"name": "lab-offered", "palette": ["#c2410c", "#1d4e89"]}})
    )
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "a.yaml").write_text(NEW_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        found = theming.cards(workspace, "figures/a.yaml")
    finally:
        workspace.close()
    assert found[0]["value"] == "../lab.theme.yaml" and found[0]["source"] == "folder"
    assert found[0]["title"] == "lab-offered" and found[0]["tones"][0]["fill"].startswith("#")
    built_in = [card["value"] for card in found if card["source"] == "built-in"]
    assert {"paper", "classic"} <= set(built_in) and "lab-offered" not in built_in


def test_a_theme_file_is_put_to_use_in_several_figures_at_once(tmp_path: Path) -> None:
    from flexo.studio import theming

    (tmp_path / "lab.theme.yaml").write_text(
        yaml.safe_dump({"theme": {"name": "lab-used", "palette": ["#c2410c"]}})
    )
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(NEW_FIGURE)
    workspace = Workspace(tmp_path)
    try:
        listed = theming.uses(workspace, "lab.theme.yaml")
        before = {entry["file"]: entry["uses"] for entry in listed}
        after = theming.use(workspace, "lab.theme.yaml", ["a.yaml"], PERSON)
    finally:
        workspace.close()
    assert before == {"a.yaml": False, "b.yaml": False}
    assert {entry["file"]: entry["uses"] for entry in after} == {"a.yaml": True, "b.yaml": False}
    written = yaml.safe_load((tmp_path / "a.yaml").read_text())
    assert written["figure"]["style"] == "lab.theme.yaml"
    assert [node["id"] for node in written["nodes"]] == ["x", "encoder", "y"]


def test_a_drawn_figure_says_which_colour_each_tone_takes(tmp_path: Path) -> None:
    drawing = FigureKind().draw({"text": NEW_FIGURE}, tmp_path, {})
    tones = drawing.info["tones"]
    assert tones["used"] == {"encoder": 1} and len(tones["colours"]) == 8
    assert tones["colours"][0]["fill"].startswith("#")


def test_the_figure_kind_and_theme_kind_are_always_there() -> None:
    found = kinds()
    assert isinstance(found["figure"], FigureKind) and isinstance(found["theme"], ThemeKind)
    assert FigureKind().claims({"nodes": []}) and not FigureKind().claims({"slides": []})
    assert ThemeKind().claims({"theme": {"name": "x"}})


def test_a_figure_that_does_not_read_says_where() -> None:
    kind = FigureKind()
    drawing = kind.draw({"text": "nodes: [\n  - id: x\n"}, Path("."))
    (message,) = drawing.messages
    assert message.severity == "error" and message.where.startswith("line ")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_merges_as_the_server_does() -> None:
    from flexo.studio.merge import merge3

    cases = [
        [
            {"slides": [{"t": "A"}, {"t": "B"}]},
            {"slides": [{"t": "A!"}, {"t": "B"}]},
            {"slides": [{"t": "N"}, {"t": "A"}, {"t": "B"}]},
        ],
        [{"a": 1, "b": 2}, {"a": 1, "c": 3}, {"a": 5, "b": 2}],
        ["one\ntwo\nthree\n", "ONE\ntwo\nthree\n", "one\ntwo\nTHREE\n"],
        [
            {"s": [{"t": "A"}]},
            {"s": [{"t": "A"}, {"t": "Mine"}]},
            {"s": [{"t": "A"}, {"t": "Theirs"}]},
        ],
    ]
    pairs = [
        [{"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}],
        [{"a": 1, "b": 2}, {"b": 2, "a": 1}],
        [{"a": 1}, {"a": 1, "b": 2}],
        [[1, 2], [1, 2, 3]],
        [{"a": [1]}, {"a": {"0": 1}}],
        ["1", 1],
        [None, {}],
    ]
    script = Path(__file__).parents[2] / "src/flexo/studio/static/studio/merge.js"
    code = (
        f"import {{ merge3, same }} from {json.dumps(script.as_uri())};\n"
        f"const cases = {json.dumps(cases)};\n"
        f"const pairs = {json.dumps(pairs)};\n"
        "console.log(JSON.stringify([cases.map(([b, o, t]) => merge3(b, o, t)),"
        " pairs.map(([a, b]) => same(a, b))]));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    merged, equal = json.loads(result.stdout)
    assert merged == [merge3(*case) for case in cases]
    assert equal == [True, True, False, False, False, False, False]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_part_dragged_on_the_drawing_goes_where_it_is_let_go() -> None:
    script = Path(__file__).parents[2] / "src/flexo/studio/static/figure/drop.js"
    model = {
        "root": "root",
        "groups": [
            {"id": "root", "layout": {"kind": "column"}, "children": ["bench", "analysis"]},
            {"id": "bench", "layout": {"kind": "row"}, "children": ["a", "b", "c"]},
            {"id": "analysis", "layout": {"kind": "row"}, "children": ["d", "e"]},
        ],
    }
    boxes = {
        "root": [0, 0, 300, 130],
        "bench": [0, 0, 300, 50],
        "a": [10, 10, 60, 40],
        "b": [110, 10, 160, 40],
        "c": [210, 10, 260, 40],
        "analysis": [0, 80, 200, 130],
        "d": [10, 90, 60, 120],
        "e": [110, 90, 160, 120],
    }
    drags = [
        ["c", 5, 25],  # before the first of its row
        ["c", 85, 25],  # between a and b
        ["d", 290, 25],  # into the row above, at its end
        ["a", 150, -20],  # out of its row, above it
        ["e", 500, 500],  # far from the figure: nowhere
        ["bench", 100, 25],  # a group over itself: where it is
    ]
    code = (
        f"import {{ dropPlace, stays }} from {json.dumps(script.as_uri())};\n"
        f"const model = {json.dumps(model)};\n"
        f"const boxes = new Map(Object.entries({json.dumps(boxes)})"
        ".map(([id, [left, top, right, bottom]]) => [id, { left, top, right, bottom }]));\n"
        f"console.log(JSON.stringify({json.dumps(drags)}.map(([id, x, y]) => {{\n"
        "  const place = dropPlace(model, boxes, { x, y }, id);\n"
        "  if (!place) return null;\n"
        "  return { parent: place.parent, index: place.index, stays: stays(model, place, id) };\n"
        "})));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [
        {"parent": "bench", "index": 0, "stays": False},
        {"parent": "bench", "index": 1, "stays": False},
        {"parent": "bench", "index": 3, "stays": False},
        {"parent": "root", "index": 0, "stays": False},
        None,
        {"parent": "root", "index": 0, "stays": True},
    ]
