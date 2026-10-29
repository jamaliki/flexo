"""An agent's turn -- the edits it makes for one request -- is one row of the activity, named as
the agent names it, and undone from there as one step of its person's, what anyone changed
meanwhile kept (flexo.studio.turns, static/studio/turns.js). And the comments people leave in a
document, as an agent's tools read and answer them (flexo.studio.commenting)."""

from __future__ import annotations

import copy
import io
import json
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

from flexo.studio import commenting, turns
from flexo.studio.agent import TOOLS, Tools
from flexo.studio.assistant import Assistant
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}
AGENT = {"id": "mcp:claude-code", "name": "Claude Code"}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TURNS_JS = Path(turns.__file__).parent / "static" / "studio" / "turns.js"


@pytest.fixture(autouse=True)
def _apart(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Workspace]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    opened = Workspace(tmp_path)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace]]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, opened = start(tmp_path / "figure.yaml", browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", opened
    finally:
        opened.close()
        server.shutdown()
        server.server_close()


def _call(url: str, token: str, body: object = None) -> tuple[int, bytes]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-Studio-Token": token}
    try:
        with OPENER.open(urllib.request.Request(url, data=data, headers=headers)) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _edit(tools: Tools, old: str, new: str, label: str | None = None) -> None:
    arguments = {"file": "figure.yaml", "old": old, "new": new}
    if label is not None:
        arguments["label"] = label
    blocks, failed = tools.call("edit_document", arguments)
    assert not failed, blocks


def _person_edit(workspace: Workspace, old: str, new: str) -> None:
    doc = workspace.open("figure.yaml")
    edited = copy.deepcopy(doc.document)
    edited["text"] = edited["text"].replace(old, new)
    doc.update(edited, doc.version, PERSON, "page-a")


def _turns(workspace: Workspace) -> list[dict]:
    return [entry for entry in workspace.activity if "turn" in entry]


def test_an_agents_edits_for_one_request_are_one_row_named_as_it_names_them(
    workspace: Workspace,
) -> None:
    tools = Tools(workspace, AGENT)
    _edit(tools, "label: Encoder", "label: Reader", "rename the parts")
    _person_edit(workspace, "Input $x$", "Input $u$")
    _edit(tools, "label: Output $y$", "label: Answer $y$", "rename the parts")
    (row,) = _turns(workspace)
    assert row["text"] == "Rename the parts" and row["turn"]["named"]
    assert row["who"]["name"] == "Claude Code" and row["who"]["kind"] == "agent"
    assert row["turn"]["edits"] == 2 and row["turn"]["files"] == ["figure.yaml"]
    assert "renamed “Encoder” to “Reader”" in row["turn"]["done"]
    # The person's edit between the agent's is a row of its own, as ever.
    assert [entry["who"]["id"] for entry in workspace.activity if "turn" not in entry] == ["page-a"]
    # The turn gone on is the latest row.
    assert workspace.activity[-1] is row
    # Another label is another request: another row. An edit with none is the open turn's.
    _edit(tools, "label: Reader", "label: Encoder", "Undo the renaming of the encoder")
    _edit(tools, "label: Answer $y$", "label: Output $y$")
    first, second = _turns(workspace)
    assert first["turn"]["edits"] == 2
    assert second["text"] == "Undo the renaming of the encoder" and second["turn"]["edits"] == 2


def test_an_unnamed_turn_is_named_by_what_it_did_and_ends_with_a_pause(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = Tools(workspace, AGENT)
    # (What it says it is doing is where it is now, not what it changed.)
    tools.call("status", {"doing": "Reading the figure"})
    _edit(tools, "label: Encoder", "label: Reader")
    (row,) = _turns(workspace)
    assert row["text"] == "renamed \u201cEncoder\u201d to \u201cReader\u201d"
    assert not row["turn"]["named"]
    _edit(tools, "label: Output $y$", "label: Answer $y$")
    (row,) = _turns(workspace)
    assert row["text"].startswith("renamed \u201cEncoder\u201d to \u201cReader\u201d and renamed")
    # A label given later names it.
    _edit(tools, "label: Input $x$", "label: Question $x$", "Rename the parts")
    (row,) = _turns(workspace)
    assert row["text"] == "Rename the parts" and row["turn"]["edits"] == 3
    # A pause longer than QUIET, and the next edit with no label is another turn's.
    monkeypatch.setattr(turns, "QUIET", 0.0)
    monkeypatch.setattr(turns, "GAP", 0.0)
    time.sleep(0.01)
    _edit(tools, "label: Reader", "label: Writer")
    assert len(_turns(workspace)) == 2


def test_an_agents_edit_to_the_file_itself_is_its_turns(workspace: Workspace) -> None:
    import os

    doc = workspace.open("figure.yaml")
    tools = Tools(workspace, AGENT)
    _edit(tools, "label: Encoder", "label: Reader", "Rename the encoder")
    workspace.flush()
    path = workspace.root / "figure.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("Output $y$", "Answer $y$"), "utf-8")
    later = time.time_ns() + 2_000_000_000
    os.utime(path, ns=(later, later))
    workspace.reread(doc)
    (row,) = _turns(workspace)
    assert row["turn"]["edits"] == 2 and "Answer $y$" in doc.document["text"]


def test_the_page_takes_a_turn_back_keeping_what_was_changed_meanwhile(
    served: tuple[str, Workspace],
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    base, workspace = served
    token = workspace.token
    tools = Tools(workspace, AGENT)
    _edit(tools, "label: Encoder", "label: Reader", "Rename the parts")
    _person_edit(workspace, "Input $x$", "Input $u$")
    _edit(tools, "label: Output $y$", "label: Answer $y$", "Rename the parts")
    _person_edit(workspace, "tone: encoder", "tone: decoder")
    (row,) = _turns(workspace)
    status, body = _call(f"{base}/api/turn?id={row['id']}&file=figure.yaml", token)
    assert status == 200
    answer = json.loads(body)
    assert answer["turn"]["label"] == "Rename the parts"
    # Two runs: the person's edit came between the agent's two.
    assert len(answer["runs"]) == 2
    now = workspace.open("figure.yaml").document
    code = (
        FAKE_PAGE
        + f"const {{ takeBack }} = await import({json.dumps(TURNS_JS.as_uri())});\n"
        + f"const answer = {json.dumps(answer)};\nconst now = {json.dumps(now)};\n"
        + "const { document, lost } = takeBack(now, answer.runs);\n"
        + "console.log(JSON.stringify({ text: document.text, lost: lost.length }));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    )
    said = json.loads(result.stdout.strip().splitlines()[-1])
    # The agent's edits taken back, the person's -- between them and after -- kept.
    assert "label: Encoder" in said["text"] and "label: Output $y$" in said["text"]
    assert "Input $u$" in said["text"] and "tone: decoder" in said["text"]
    assert said["lost"] == 0
    # Undone: its row says so (and so does the person's row of the change that undid it); the
    # agent's next edit is another turn.
    _person_edit(workspace, "label: Reader", "label: Encoder")
    status, _ = _call(
        f"{base}/api/turn/undone", token, {"id": row["id"], "undone": True, "who": PERSON}
    )
    assert status == 200
    assert row["turn"]["undone"]["who"]["id"] == "page-a"
    assert workspace.activity[-1]["text"] == "undid Claude Code\u2019s \u201cRename the parts\u201d"
    _edit(tools, "label: Encoder", "label: Reader", "Rename the parts")
    assert len(_turns(workspace)) == 2
    # Made again (the person's ⌘Z of their undo): said so.
    _call(f"{base}/api/turn/undone", token, {"id": row["id"], "undone": False, "who": PERSON})
    assert row["turn"]["undone"] is None


def test_a_turn_too_long_ago_is_not_offered_to_be_undone(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(turns, "KEPT", 1)
    tools = Tools(workspace, AGENT)
    _edit(tools, "label: Encoder", "label: Reader", "First")
    _edit(tools, "label: Reader", "label: Writer", "Second")
    first, second = _turns(workspace)
    assert first["turn"]["kept"] is False and second["turn"]["kept"] is True
    with pytest.raises(ValueError, match="too long ago"):
        turns.of(workspace).runs(first["id"], "figure.yaml")
    assert b"Writer" in turns.of(workspace).runs(second["id"], "figure.yaml")


def test_an_agent_over_mcp_names_its_turn(served: tuple[str, Workspace]) -> None:
    from flexo.studio.mcp import serve

    _, workspace = served
    edit = {"file": "figure.yaml", "old": "Encoder", "new": "Reader", "label": "Rename it"}
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "claude-code"}},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "edit_document", "arguments": edit},
        },
    ]
    out = io.StringIO()
    serve(workspace.root, io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    listed = {tool["name"]: tool for tool in answers[1]["result"]["tools"]}
    assert "label" in listed["edit_document"]["inputSchema"]["properties"]
    assert {"list_comments", "reply_to_comment", "resolve_comment", "add_comment"} <= set(listed)
    assert "label" in answers[0]["result"]["instructions"]
    assert not answers[2]["result"]["isError"]
    (row,) = _turns(workspace)
    assert row["text"] == "Rename it" and row["who"]["name"] == "Claude Code"


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


def test_the_assistants_answer_to_one_request_is_one_turn(workspace: Workspace) -> None:
    edits = [
        ("edit_document", {"file": "figure.yaml", "old": "Encoder", "new": "Reader"}),
        ("edit_document", {"file": "figure.yaml", "old": "Output $y$", "new": "Answer $y$"}),
    ]
    client = _Client([("Renaming.", edits), ("Done.", [])])
    assistant = Assistant(workspace, client=client)
    assistant.ask("rename the encoder and the output", {"file": "figure.yaml"}, PERSON)
    deadline = time.monotonic() + 10
    while assistant.running and time.monotonic() < deadline:
        time.sleep(0.02)
    (row,) = _turns(workspace)
    assert row["text"] == "Rename the encoder and the output"
    assert row["turn"]["edits"] == 2 and row["who"]["id"] == "assistant"
    # Its next answer is another turn, even with no label.
    back = ("edit_document", {"file": "figure.yaml", "old": "Reader", "new": "Encoder"})
    client.script = [("Again.", [back]), ("Done.", [])]
    assistant.ask("put it back", {"file": "figure.yaml"}, PERSON)
    deadline = time.monotonic() + 10
    while assistant.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert [row["text"] for row in _turns(workspace)] == [
        "Rename the encoder and the output",
        "Put it back",
    ]


def test_every_editing_tool_takes_a_label() -> None:
    for tool in TOOLS:
        if tool["name"] in {"edit_document", "write_document", "convert_to_figure_parts"}:
            assert "label" in tool["input_schema"]["properties"]


# -- comments, as an agent reads and answers them ----------------------------------------


DOCUMENT = {
    "slides": [
        {
            "title": "One",
            "comments": [
                {"id": "c1", "author": "Ana", "time": "2026-10-29T09:00:00Z", "text": "Shorter?"},
                {"id": "c2", "author": "Ana", "text": "Done already", "resolved": True},
            ],
            "body": [{"text": "Hi", "comments": [{"id": "c3", "author": "Bo", "text": "Bigger"}]}],
        },
    ]
}


def test_threads_are_found_wherever_they_are_written_and_changed_on_a_copy() -> None:
    found = commenting.threads(DOCUMENT)
    assert [(item["path"], item["thread"]["id"]) for item in found] == [
        (["slides", 0], "c1"),
        (["slides", 0], "c2"),
        (["slides", 0, "body", 0], "c3"),
    ]
    before = json.dumps(DOCUMENT, sort_keys=True)

    def reply(thread: dict) -> None:
        thread["replies"] = [{"author": "Claude", "time": commenting.now(), "text": "Yes"}]
        thread["resolved"] = True

    changed = commenting.with_thread(DOCUMENT, "c3", reply)
    assert json.dumps(DOCUMENT, sort_keys=True) == before
    assert changed["slides"][0]["body"][0]["comments"][0]["resolved"] is True
    # (What it did not change is the very same.)
    assert changed["slides"][0]["comments"] is DOCUMENT["slides"][0]["comments"]
    added = commenting.with_new(DOCUMENT, ["slides", 0], commenting.thread("Claude", "A note"))
    assert len(added["slides"][0]["comments"]) == 3 and len(DOCUMENT["slides"][0]["comments"]) == 2
    with pytest.raises(ValueError, match="no comment"):
        commenting.find(DOCUMENT, "c9")


def test_a_comment_written_wrongly_is_said_where_it_is() -> None:
    wrong = {
        "slides": [
            {"comments": "a note"},
            {"comments": [{"words": "x"}, {"text": "y", "by": "Ana", "resolved": "yes"}]},
        ]
    }
    said = commenting.problems(wrong)
    assert said[0].startswith("slides[0].comments: comments must be a list")
    assert any(line.startswith("slides[1].comments[0]: a comment is a mapping") for line in said)
    assert any("unknown key by" in line for line in said)
    assert any(line.startswith("slides[1].comments[1].resolved") for line in said)
    assert commenting.problems(DOCUMENT) == []


FAKE_PAGE = """
class Node {
  constructor(tag) {
    Object.assign(this, { tag, children: [], attributes: {}, style: {}, dataset: {} });
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  remove() { this.removed = true; }
}
globalThis.Node = Node;
globalThis.SVGElement = class extends Node {};
globalThis.document = {
  body: new Node("body"), head: new Node("head"), documentElement: new Node("html"),
  addEventListener() {}, querySelector() { return null; },
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new SVGElement(tag),
  createTextNode: (text) => Object.assign(new Node("#text"), { text }),
};
"""
