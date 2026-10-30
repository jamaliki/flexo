"""Reading a document a little at a time (the ``outline`` tool, and ``read_document``'s
``slides``): a deck of forty slides with figures in it is tens of thousands of words, read again
after every edit that does not match -- most of it about slides the agent is not working on.

- An **outline** says, a line a page, what the document holds -- for a deck each slide's
  number, title, layout, objects, build steps, TODOs and warnings; for a figure its parts,
  lines and shapes (the kind's ``outline``) -- and what each person in the studio has
  selected, as a path in its YAML (the kind's ``selected``), so "this" can be found.
- An **excerpt** is the slides asked for, line for line as the whole text has them, so what
  is copied from it matches for ``edit_document``.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

TODO = re.compile(r"(?<![A-Za-z0-9_])TODO(?![A-Za-z0-9_])")
"""Work left in a document: TODO in capitals, a word of its own, as the studio finds it
(``todos.js``): not "todo", nor "TODOs"."""


def todos(value: Any) -> int:
    """How many TODOs the words of ``value`` (a document, or part of one) hold."""

    if isinstance(value, str):
        return len(TODO.findall(value))
    if isinstance(value, dict):
        return sum(todos(item) for item in value.values())
    if isinstance(value, list):
        return sum(todos(item) for item in value)
    return 0


def items(text: str, key: str) -> list[tuple[int, int]]:
    """Where each item of the list under the top-level ``key`` of a YAML text is: its first
    line and the line after its last (counting from 0)."""

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    root = yaml.compose(text, Loader=loader)
    if not isinstance(root, yaml.MappingNode):
        return []
    found = next((value for name, value in root.value if getattr(name, "value", None) == key), None)
    if not isinstance(found, yaml.SequenceNode) or not found.value:
        return []
    starts = [_dash_line(text, item.start_mark.line) for item in found.value]
    end = found.end_mark.line + (1 if found.end_mark.column else 0)
    return [(start, stop) for start, stop in zip(starts, [*starts[1:], end], strict=True)]


def _dash_line(text: str, line: int) -> int:
    # (An item whose words start on the line after its "-" starts at the "-".)
    lines = text.splitlines()
    while (
        line > 0
        and line < len(lines)
        and not lines[line].lstrip().startswith("-")
        and (lines[line - 1].strip() == "-")
    ):
        line -= 1
    return line


def excerpt(text: str, key: str, numbers: list[int], noun: str = "slide") -> str:
    """The items of ``key`` numbered (1 is the first), each under a line naming it, as the text
    has them line for line."""

    lines = text.splitlines(keepends=True)
    found = items(text, key)
    if not found:
        raise ValueError(f"There are no {noun}s to read.")
    parts = []
    for number in numbers:
        if not 1 <= number <= len(found):
            parts.append(f"── there is no {noun} {number}; there are {len(found)} ──\n")
            continue
        start, stop = found[number - 1]
        parts.append(f"── {noun} {number} ──\n" + "".join(lines[start:stop]).rstrip("\n") + "\n")
    return "\n".join(parts)


def selections(workspace: Any, doc: Any, document: Any) -> list[str]:
    """What each person in the studio has selected in ``doc``, a line each: where it is in
    the YAML, so a request about "this" can be found."""

    lines = []
    for entry in workspace.focus_of_people():
        if entry.get("file") != doc.name or not entry.get("where"):
            continue
        said = selected(doc.kind, document, entry["where"])
        if said:
            lines.append(f"{_who(entry)} has selected {said}.")
    return lines


def selected(kind: Any, document: Any, where: Any) -> str | None:
    """Where a person is (their ``where``, as their page says it) as a path in the document's
    YAML, with the part of it chosen: the kind's ``selected``."""

    hook = getattr(kind, "selected", None)
    if hook is None or not isinstance(where, dict):
        return None
    try:
        return hook(document, where)
    except Exception:  # an old place in a document changed since: said as the page says it
        return None


def _who(entry: dict[str, Any]) -> str:
    name = entry["who"].get("name") or ""
    return "Someone in the studio" if name in {"", "You"} else name


def outline(workspace: Any, who: dict[str, Any], file: str) -> str:
    """The ``outline`` tool's answer."""

    doc = workspace.open(file)
    workspace.set_presence(who, doc.name, None, None)
    with doc.lock:
        document, version = doc.document, doc.version
    head = [f"{doc.name} ({doc.kind.name}), version {version}."]
    if doc.unread:
        return "\n".join(
            [*head, doc.problem or "It does not read.", "read_document shows it as written."]
        )
    drawing = workspace.drawing_of(doc.name)
    head += selections(workspace, doc, document)
    hook = getattr(doc.kind, "outline", None)
    if hook is not None:
        return "\n".join([*head, *hook(document, drawing)])
    lines = [
        f"{number}. {page.label or page.id}" for number, page in enumerate(drawing.pages, start=1)
    ]
    lines += warnings(
        drawing.messages, {page.id: n for n, page in enumerate(drawing.pages, start=1)}
    )
    return "\n".join([*head, *lines])


def warnings(messages: list[Any], numbers: dict[str, int], limit: int = 20) -> list[str]:
    """What a drawing warns of, a line each, by page number where it names a page."""

    said = [message for message in messages if message.severity in ("error", "warning")]
    if not said:
        return ["No warnings."]
    lines = [f"Warnings ({len(said)}):"]
    for message in said[:limit]:
        number = numbers.get(message.page)
        place = f"page {number}" if number else message.place or message.where
        lines.append(f"- {message.severity}{f' [{place}]' if place else ''}: {message.text}")
    if len(said) > limit:
        lines.append(f"- and {len(said) - limit} more (look shows them all, page by page).")
    return lines


def slides_of(doc: Any, text: str, version: int, numbers: list[int]) -> str:
    """``read_document``'s answer for some of a deck's slides (the kind's ``excerpt``)."""

    cut = getattr(doc.kind, "excerpt", None)
    if cut is None:
        raise ValueError(f"{doc.name} is a {doc.kind.name}: only a deck is read slide by slide.")
    count = len(items(text, "slides")) if doc.kind.name == "deck" else None
    total = f" of {count}" if count is not None else ""
    said = ("slides " if len(numbers) > 1 else "slide ") + ", ".join(
        str(number) for number in numbers
    )
    return (
        f"{doc.name} ({doc.kind.name}), version {version}: {said}{total}, as the whole text has "
        f"it (edit_document matches it so):\n\n{cut(text, numbers)}"
    )


def chosen(workspace: Any, entry: dict[str, Any]) -> str | None:
    """What a person has selected where they are looking (their presence ``entry``: its
    ``file`` and ``where``), as a path in the YAML -- "slides[2].right[0] (Figure), part
    encoder" -- or None, with nothing selected or the document not open."""

    where = entry.get("where")
    if not isinstance(where, dict) or not entry.get("file"):
        return None
    doc = workspace.docs.get(entry["file"])
    if doc is None:
        return None
    with doc.lock:
        document = doc.document
    return selected(doc.kind, document, where)
