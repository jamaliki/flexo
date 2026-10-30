"""Comments: review notes on a document's parts, kept in the document; and an agent's tools.

A comment is a thread written where it is about -- a deck's slide, an object on it, a part of a
figure there -- under ``comments``, so it travels with the document (a bundle synced by a cloud
service, a file in git) and merges as any edit does: two people replying at once keep both
replies, one resolving while another replies keeps both. Never drawn: no export shows one.

```yaml
comments:
- id: c3f9a2b
  author: Kiarash Jamali
  time: '2026-10-29T14:03:00Z'
  text: The y axis needs units
  part: encoder              # on a figure: the part it is about, by its id
  replies:
  - {author: Claude Code, time: '2026-10-29T14:05:00Z', text: Labelled it “Binding (nM)”.}
  resolved: true             # left out while it is open
```

The kind says where a mapping holding ``comments`` is (``comment_place``: "Slide 3 · Figure"),
and which mapping a new comment goes in (``comment_holder``). The tools here list them, reply,
resolve and add -- so "work through my comments" is a task an agent can be given: each reply
and resolve is a change by the agent, part of its turn (``flexo.studio.turns``).
"""

from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime
from typing import Any

THREAD_KEYS = ("id", "author", "time", "text", "part", "replies", "resolved")
REPLY_KEYS = ("author", "time", "text")

COMMENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_comments",
        "description": (
            "The comments people left on a document -- on a deck's slides, the objects on them, "
            "the parts of its figures -- open ones (all, with all=true): each thread's id, where "
            "it is, "
            "who wrote it and when, its words, and its replies. A person's comments are often what "
            "they want done: do what each asks, then reply_to_comment saying what you did, "
            "resolving it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"file": {"type": "string"}, "all": {"type": "boolean"}},
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reply_to_comment",
        "description": (
            "Reply to a comment thread (by its id, from list_comments), in your own name; with "
            "resolve=true, resolve it too -- when what it asked for is done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "id": {"type": "string"},
                "text": {"type": "string"},
                "resolve": {"type": "boolean"},
                "label": {"type": "string"},
            },
            "required": ["file", "id", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "resolve_comment",
        "description": (
            "Resolve a comment thread (by its id), or open it again (resolved=false). Reply first "
            "if there is something to say about it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "id": {"type": "string"},
                "resolved": {"type": "boolean"},
                "label": {"type": "string"},
            },
            "required": ["file", "id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_comment",
        "description": (
            "Leave a comment for the people in the studio, in your own name: on a deck's slide "
            "(`slide`, 1 is the first), on an object on it (`object`, as `body[0]`, `left[1]`, "
            "`columns[1][0]`), or on a part of the figure that object is (`part`, its id). Use it "
            "for "
            "what you need them to decide or check, not to say what you did."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "text": {"type": "string"},
                "slide": {"type": "integer"},
                "object": {"type": "string"},
                "part": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["file", "text"],
            "additionalProperties": False,
        },
    },
]

COMMENTS_SAID = (
    "People may leave comments on a deck's slides, objects and figure parts (list_comments): when "
    "asked to work through them, do what each asks, look, then reply to it saying what you did and "
    "resolve it; one you cannot do, reply saying why and leave it open."
)
"""What an agent is told of comments, beside its other instructions."""


def now() -> str:
    """A comment's time: UTC, to the second, as ISO 8601 writes it."""

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(document: Any = None) -> str:
    """An id for a new thread, none of ``document``'s."""

    taken = (
        {str(found["thread"].get("id")) for found in threads(document)}
        if document is not None
        else set()
    )
    while True:
        ident = f"c{secrets.token_hex(3)}"
        if ident not in taken:
            return ident


def thread(
    author: str, text: str, *, part: str | None = None, document: Any = None
) -> dict[str, Any]:
    """A new thread, its first comment ``text`` by ``author``."""

    made: dict[str, Any] = {"id": new_id(document), "author": author, "time": now(), "text": text}
    if part:
        made["part"] = str(part)
    return made


def threads(document: Any) -> list[dict[str, Any]]:
    """Every comment thread in ``document``, in the order they are written: each as ``{"path":
    the mapping holding it, as keys and indices from the document's top; "index": its place
    in that mapping's comments; "thread": the thread}``. One written wrongly (no words, not a
    mapping) is passed over."""

    found: list[dict[str, Any]] = []

    def walk(value: Any, path: list[Any]) -> None:
        if isinstance(value, dict):
            held = value.get("comments")
            if isinstance(held, list):
                for index, item in enumerate(held):
                    if isinstance(item, dict) and isinstance(item.get("text"), str | int | float):
                        found.append({"path": list(path), "index": index, "thread": item})
            for key, item in value.items():
                if key != "comments" and isinstance(item, dict | list):
                    walk(item, [*path, key])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict | list):
                    walk(item, [*path, index])

    walk(document, [])
    return found


def problems(document: Any) -> list[str]:
    """What is wrong with how ``document``'s comments are written, each said where it is."""

    said: list[str] = []

    def place(path: list[Any]) -> str:
        return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(
            "."
        )

    def walk(value: Any, path: list[Any]) -> None:
        if isinstance(value, dict):
            held = value.get("comments")
            if "comments" in value and not isinstance(held, list):
                said.append(f"{place([*path, 'comments'])}: comments must be a list of threads")
            for index, item in enumerate(held if isinstance(held, list) else []):
                where = place([*path, "comments", index])
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    said.append(f"{where}: a comment is a mapping with its words in text")
                    continue
                unknown = [str(key) for key in item if key not in THREAD_KEYS]
                if unknown:
                    said.append(
                        f"{where}: unknown key {', '.join(unknown)} "
                        f"(a comment takes {', '.join(THREAD_KEYS)})"
                    )
                replies = item.get("replies", [])
                if not isinstance(replies, list) or not all(
                    isinstance(reply, dict) and isinstance(reply.get("text"), str)
                    for reply in replies
                ):
                    said.append(
                        f"{where}.replies: each reply is a mapping with author, time and text"
                    )
                if not isinstance(item.get("resolved", False), bool):
                    said.append(f"{where}.resolved: resolved must be true or false")
            for key, item in value.items():
                if key != "comments" and isinstance(item, dict | list):
                    walk(item, [*path, key])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict | list):
                    walk(item, [*path, index])

    walk(document, [])
    return said


def find(document: Any, ident: str) -> dict[str, Any]:
    """The thread ``ident`` in ``document`` (as ``threads`` gives it); a ``ValueError`` saying
    so, if there is none."""

    ident = str(ident).strip()
    for found in threads(document):
        if str(found["thread"].get("id", "")) == ident:
            return found
    raise ValueError(f"There is no comment {ident!r}: list_comments says which there are.")


def changed_at(document: Any, path: list[Any], change) -> Any:
    """``document`` with the mapping at ``path`` changed by ``change(mapping)`` -- a copy of
    each mapping and list along the way, the rest shared with ``document``."""

    top = copy.copy(document)
    holder = top
    for key in path:
        inner = copy.copy(holder[key])
        holder[key] = inner
        holder = inner
    change(holder)
    return top


def with_thread(document: Any, ident: str, change) -> Any:
    """``document`` with the thread ``ident`` changed by ``change(thread)``."""

    found = find(document, ident)

    def into(holder: dict[str, Any]) -> None:
        held = list(holder["comments"])
        item = copy.deepcopy(held[found["index"]])
        change(item)
        held[found["index"]] = item
        holder["comments"] = held

    return changed_at(document, found["path"], into)


def with_new(document: Any, path: list[Any], made: dict[str, Any]) -> Any:
    """``document`` with the thread ``made`` added to the mapping at ``path``."""

    def into(holder: dict[str, Any]) -> None:
        held = holder.get("comments")
        holder["comments"] = [*(held if isinstance(held, list) else []), made]

    return changed_at(document, path, into)


def said(found: dict[str, Any], place: str) -> str:
    """A thread in words, for an agent: its id, where it is, whether it is open; then each
    comment in it, by whom and when."""

    item = found["thread"]
    state = "resolved" if item.get("resolved") is True else "open"
    part = f", part “{item['part']}”" if item.get("part") else ""
    lines = [f"{item.get('id', '?')} · {place}{part} · {state}"]
    for one in [item, *[reply for reply in item.get("replies") or [] if isinstance(reply, dict)]]:
        lines.append(
            f"  {one.get('author') or 'Someone'} ({_when(one.get('time'))}): {one.get('text', '')}"
        )
    return "\n".join(lines)


def _when(value: Any) -> str:
    text = str(value or "").strip()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text or "some time ago"
    return (
        moment.strftime("%d %b %Y %H:%M UTC")
        if moment.tzinfo
        else moment.strftime("%d %b %Y %H:%M")
    )


class Commenting:
    """The comment tools, for ``flexo.studio.agent.Tools``: ``self.workspace`` and ``self.who``."""

    workspace: Any
    who: dict[str, Any]

    def _place(self, doc: Any, document: Any, path: list[Any]) -> str:
        place = getattr(doc.kind, "comment_place", None)
        if place is not None:
            try:
                return str(place(document, path)["label"])
            except Exception:
                pass
        return (
            "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(".")
            or "the document"
        )

    def _list_comments(self, file: str, all: bool = False) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        with doc.lock:
            document = doc.document
            found = threads(document)
            shown = [item for item in found if all or item["thread"].get("resolved") is not True]
            lines = [self._said(doc, document, item) for item in shown]
        if not found:
            return [{"type": "text", "text": f"{doc.name} has no comments."}]
        if not shown:
            return [
                {
                    "type": "text",
                    "text": f"{doc.name} has no open comments ({len(found)} resolved).",
                }
            ]
        closed = len(found) - len(
            [item for item in found if item["thread"].get("resolved") is not True]
        )
        head = f"{doc.name}: {len(shown)} comment thread{'s' if len(shown) != 1 else ''}" + (
            f" ({closed} resolved not shown)" if closed and not all else ""
        )
        return [{"type": "text", "text": head + ":\n\n" + "\n\n".join(lines)}]

    def _said(self, doc: Any, document: Any, item: dict[str, Any]) -> str:
        return said(item, self._place(doc, document, item["path"]))

    def _changed(self, doc: Any, change) -> tuple[int, int, Any]:
        with doc.lock:
            document, version = doc.document, doc.version
        made = change(document)
        new_version, merged = doc.update(made, version, self.who)
        return version, new_version, merged

    def _reply_to_comment(
        self, file: str, id: str, text: str, resolve: bool = False
    ) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        if not str(text).strip():
            raise ValueError("Say something in the reply: text is empty.")

        def reply(item: dict[str, Any]) -> None:
            replies = item.get("replies")
            item["replies"] = [
                *(replies if isinstance(replies, list) else []),
                {"author": self.who.get("name") or "Agent", "time": now(), "text": str(text)},
            ]
            if resolve:
                item["resolved"] = True

        _, version, merged = self._changed(doc, lambda document: with_thread(document, id, reply))
        found = find(merged, id)
        done = "Replied and resolved" if resolve else "Replied"
        return [
            {
                "type": "text",
                "text": f"{done}, in {doc.name} (version {version}):\n"
                + self._said(doc, merged, found),
            }
        ]

    def _resolve_comment(self, file: str, id: str, resolved: bool = True) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)

        def resolve(item: dict[str, Any]) -> None:
            if resolved:
                item["resolved"] = True
            else:
                item.pop("resolved", None)

        before, version, _ = self._changed(doc, lambda document: with_thread(document, id, resolve))
        if version == before:
            return [
                {"type": "text", "text": f"{id} was {'resolved' if resolved else 'open'} already."}
            ]
        return [
            {
                "type": "text",
                "text": f"{'Resolved' if resolved else 'Opened again'} {id}, in {doc.name}: "
                f"now version {version}.",
            }
        ]

    def _add_comment(
        self,
        file: str,
        text: str,
        slide: int | None = None,
        object: str | None = None,
        part: str | None = None,
    ) -> list[dict[str, Any]]:
        doc = self.workspace.open(file)
        if not str(text).strip():
            raise ValueError("Say something in the comment: text is empty.")
        holder = getattr(doc.kind, "comment_holder", None)
        if holder is None:
            raise ValueError(f"A {doc.kind.title.lower()} takes no comments.")
        made: dict[str, Any] = {}

        def add(document: Any) -> Any:
            path = holder(document, {"slide": slide, "object": object, "part": part})
            made.update(
                thread(self.who.get("name") or "Agent", str(text), part=part, document=document)
            )
            return with_new(document, path, dict(made))

        _, version, merged = self._changed(doc, add)
        found = find(merged, made["id"])
        return [
            {
                "type": "text",
                "text": f"Added, in {doc.name} (version {version}):\n"
                + self._said(doc, merged, found),
            }
        ]
