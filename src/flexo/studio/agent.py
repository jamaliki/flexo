"""What an agent can do in the studio: the tools, whoever calls them.

An agent -- Claude Code through ``flexo studio mcp``, or the assistant built
into the studio -- works on the same open documents as the people in the
studio, and they see its edits as it makes them. The tools read and change
documents as text (the file's own YAML), draw pages as pictures so the agent
can look at its work, and say what the people in the studio are looking at.
Each tool returns content blocks in the Messages API's shape: ``text`` and
``image``.
"""

from __future__ import annotations

import base64
import inspect
from typing import Any

import yaml

from flexo.studio.workspace import Workspace

MAX_LOOK = 4
"""Pages drawn per call to ``look``."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_documents",
        "description": (
            "List the documents in the studio's folder that it can edit (decks, figures, themes), "
            "which of them are open, what each person in the studio is looking at, and the "
            "studio's address to give the user."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "open_document",
        "description": (
            "Open a document in the studio (the people there see it appear), making it when it "
            "does not exist yet -- give `kind` (deck, figure, theme) for a new one. Returns the "
            "guide to that kind of document the first time, and the document's text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Path relative to the studio's folder."},
                "kind": {
                    "type": "string",
                    "description": "For a new file: deck, figure, or theme.",
                },
            },
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_document",
        "description": (
            "The document's current text (as YAML, exactly as edit_document matches it) and "
            "version. People may have changed it since you last read it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"file": {"type": "string"}},
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_document",
        "description": (
            "Replace `old` with `new` in the document's text, as read by read_document; `old` "
            "must occur exactly once (or set replace_all). The change is merged with any "
            "people make meanwhile and shown to them at once. Returns problems the change "
            "causes, if any."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "old": {"type": "string", "description": "Text to find, exactly."},
                "new": {"type": "string", "description": "Text to put in its place."},
                "replace_all": {"type": "boolean"},
            },
            "required": ["file", "old", "new"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_document",
        "description": (
            "Replace the whole document with `text` (YAML). Prefer edit_document for changes to "
            "part of it: it keeps what people change meanwhile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"file": {"type": "string"}, "text": {"type": "string"}},
            "required": ["file", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look",
        "description": (
            "Draw pages of a document and return them as pictures, with every warning the "
            "drawing gives -- look after changing something, to see what it looks like. For a "
            f"deck, `pages` are slide numbers (1 is the first); at most {MAX_LOOK} per call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "pages": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "status",
        "description": (
            "Tell the people in the studio what you are doing now, in a few words ('Tightening "
            "the wording on slide 4'), and where (file, and for a deck a slide number). Shown "
            "beside your name while you work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doing": {"type": "string"},
                "file": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["doing"],
            "additionalProperties": False,
        },
    },
]

INSTRUCTIONS = """\
Flexo studio is open in the user's browser on this folder: they watch the documents you work on \
change as you change them, and may edit the same documents at the same time. Work in small \
steps they can follow. Read a document before editing it, and read it again when an edit does \
not match -- they may have changed it. After changing what a page shows, look at it and fix what \
looks wrong (crowded slides, words too small, parts overlapping). Use status to say what you are \
doing. When asked about "this slide" or "this", list_documents says what the user is looking at."""


class Tools:
    """The tools, acting for one agent on one workspace."""

    def __init__(self, workspace: Workspace, who: dict[str, Any]) -> None:
        self.workspace = workspace
        self.who = {**who, "kind": "agent"}
        self.guided: set[str] = set()

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        """Run a tool; its content blocks, and whether it failed."""

        handler = getattr(self, f"_{name}", None)
        if handler is None or name not in {tool["name"] for tool in TOOLS}:
            return [_text(f"There is no tool {name}.")], True
        try:
            inspect.signature(handler).bind(**arguments)
        except TypeError as error:
            return [_text(f"{name} was given the wrong arguments: {error}")], True
        try:
            return handler(**arguments), False
        except (ValueError, KeyError, FileExistsError, PermissionError, FileNotFoundError) as error:
            return [_text(str(error))], True
        except Exception as error:
            # Whatever a document can make go wrong: the agent reads it and carries on, and
            # the conversation keeps going.
            return [_text(f"{name} failed: {type(error).__name__}: {error}")], True

    # -- the tools --

    def _list_documents(self) -> list[dict[str, Any]]:
        workspace = self.workspace
        lines = [f"Folder: {workspace.root}"]
        address = getattr(workspace, "address", None)
        if address:
            lines.append(f"Studio: {address}")
        documents = workspace.documents()
        lines.append("Documents:" if documents else "No documents yet (open_document makes one).")
        for entry in documents:
            open_ = " (open)" if entry["file"] in workspace.docs else ""
            lines.append(f"- {entry['file']}: {entry['kind']}{open_}")
        for entry in workspace.focus_of_people():
            if entry.get("file"):
                where = f", {_where(entry.get('where'))}" if entry.get("where") else ""
                name = entry["who"].get("name") or "You"
                who = "The person in the studio" if name == "You" else name
                lines.append(f"{who} is looking at {entry['file']}{where}.")
        return [_text("\n".join(lines))]

    def _open_document(self, file: str, kind: str | None = None) -> list[dict[str, Any]]:
        workspace = self.workspace
        path = workspace.path(file)
        if path.exists():
            doc = workspace.open(file)
        else:
            if not kind:
                raise ValueError(
                    f"{file} does not exist; give kind (deck, figure, theme) to make it"
                )
            doc = workspace.new(file, kind)
        workspace.broadcast({"type": "opened", "file": doc.name, "who": self.who})
        workspace.set_presence(self.who, doc.name, None, None)
        blocks = []
        if doc.kind.name not in self.guided:
            guide = getattr(doc.kind, "guide", None)
            if guide:
                blocks.append(_text(guide()))
            self.guided.add(doc.kind.name)
        blocks.extend(self._read_document(doc.name))
        return blocks

    def _read_document(self, file: str) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        with doc.lock:
            text, version = _dump(doc.kind, doc.document), doc.version
            # A file that does not read is shown as it is written, to be put right.
            if doc.unread and doc.source() is not None:
                text = doc.source()
        problem = f"\nNote: {doc.problem}" if doc.problem else ""
        return [_text(f"{doc.name} ({doc.kind.name}), version {version}:{problem}\n\n{text}")]

    def _edit_document(
        self, file: str, old: str, new: str, replace_all: bool = False
    ) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        with doc.lock:
            text, version = _dump(doc.kind, doc.document), doc.version
            if doc.unread and doc.source() is not None:
                text = doc.source()
        count = text.count(old) if old else 0
        if count == 0:
            raise ValueError(
                f"`old` does not occur in {doc.name} (version {version}). Read it again: it may "
                "have changed, and the text must match exactly, spaces and all."
            )
        if count > 1 and not replace_all:
            raise ValueError(
                f"`old` occurs {count} times in {doc.name}; give more of it, or set replace_all"
            )
        changed = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        return self._apply(doc, changed, version)

    def _write_document(self, file: str, text: str) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        with doc.lock:
            version = doc.version
        return self._apply(doc, text, version)

    def _apply(self, doc, text: str, version: int) -> list[dict[str, Any]]:
        if doc.unread:
            # Put right as written: taken in once it reads, else nothing is written.
            doc.mend(text)
            return [_text(f"{doc.name} reads now: version {doc.version}.")]
        try:
            document = _parse(doc.kind, text)
        except yaml.YAMLError as error:
            raise ValueError(
                f"The result does not read as YAML, so nothing changed: {error}"
            ) from None
        check = getattr(doc.kind, "check", None)
        problems = check(document, doc.path.parent) if check else []
        new_version, _ = doc.update(document, version, self.who)
        lines = [f"Changed {doc.name}: now version {new_version}."]
        if new_version == version:
            lines = [f"{doc.name} is unchanged (version {version})."]
        if problems:
            lines.append("Problems:")
            lines.extend(f"- {problem}" for problem in problems)
        return [_text("\n".join(lines))]

    def _look(self, file: str, pages: list[int] | None = None) -> list[dict[str, Any]]:
        from flexo.export import rasterise
        from flexo.portable import portable_svg

        doc = self.workspace.open(file)
        self.workspace.set_presence(self.who, doc.name, {"page": (pages or [1])[0]}, None)
        drawing = self.workspace.drawing_of(doc.name, {"focus": (pages or [1])[0] - 1})
        wanted = pages or list(range(1, min(len(drawing.pages), MAX_LOOK) + 1))
        blocks: list[dict[str, Any]] = []
        for number in wanted[:MAX_LOOK]:
            if not 1 <= number <= len(drawing.pages):
                blocks.append(
                    _text(f"There is no page {number}; {doc.name} has {len(drawing.pages)}.")
                )
                continue
            page = drawing.pages[number - 1]
            if not page.svg:
                continue
            png = rasterise(portable_svg(page.svg), dpi=72)
            blocks.append(_text(f"Page {number} ({page.label or page.id}):"))
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(png).decode("ascii"),
                    },
                }
            )
        messages = [message for message in drawing.messages if message.severity != "note"]
        notes = [message for message in drawing.messages if message.severity == "note"]
        summary = [f"{doc.name}: {len(drawing.pages)} page(s)."]
        if len(wanted) > MAX_LOOK:
            summary.append(f"Showing the first {MAX_LOOK} asked for.")
        for message in messages[:30]:
            place = f" [{message.page or message.where}]" if (message.page or message.where) else ""
            summary.append(f"{message.severity}{place}: {message.text}")
        for message in notes[:10]:
            summary.append(f"note: {message.text}")
        if not messages:
            summary.append("No warnings.")
        return [*blocks, _text("\n".join(summary))]

    def _status(
        self, doing: str, file: str | None = None, page: int | None = None
    ) -> list[dict[str, Any]]:
        where = {"page": page} if page else None
        self.workspace.set_presence(self.who, file, where, doing)
        return [_text("Shown.")]


def _dump(kind, document: Any) -> str:
    dump = getattr(kind, "dump", None)
    if dump:
        return dump(document)
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def _parse(kind, text: str) -> Any:
    parse = getattr(kind, "parse", None)
    return parse(text) if parse else yaml.safe_load(text)


def _where(where: Any) -> str:
    if isinstance(where, dict):
        parts = []
        if where.get("page"):
            parts.append(f"page {where['page']}")
        if where.get("label"):
            parts.append(str(where["label"]))
        return ", ".join(parts)
    return str(where)


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}
