"""An edit a page asks a document's kind to make (``/api/act``), sent as no more than what it is.

A page whose document is the studio's -- nothing of its own still on its way -- sends an edit
with the version it has (``base``) rather than the whole document: the studio makes it on its
own copy of that version. Asked to (``commit``), it keeps what the edit makes at once, as an
update from that version would; asked to (``draw``), it draws the document so made in the
same request. The answer says what the edit changed (``delta``: :func:`changes`) and the
version it became, never the whole document, with the drawing's pages that changed alone
(``Workspace.draw``): one request where an edit took an edit, an update and a drawing, each
carrying the whole document both ways.
"""

from __future__ import annotations

import copy
from typing import Any

MISSING = object()


def sent_document(doc: Any, data: dict[str, Any]) -> Any:
    """The document an edit asked of ``doc`` is made on: the page's own, sent whole
    (``document``), or the studio's at the version the page has (``base``), which is the
    page's own -- a copy, for the kind to make the edit on. ``None`` when that version is no
    longer kept: the page sends its document whole."""

    if "document" in data:
        return data["document"]
    base = data.get("base")
    if base is None:
        return doc.document
    with doc.lock:
        if int(base) == doc.version:
            # (As the page has it: in the order its own keys are written in, as the studio's
            # history, written sorted, would not keep them.)
            return copy.deepcopy(doc.document)
    return doc.base(int(base))


def changes(before: Any, after: Any, at: tuple = ()) -> list[list[Any]]:
    """What changed from ``before`` to ``after``, as the page makes it again: ``[path,
    value]`` puts ``value`` at ``path`` (a list of keys and indices; ``[]`` the whole), and
    ``[path]`` takes away what is there. A mapping whose keys changed, or changed order, and
    a list whose length changed are put whole, in the order ``after`` has them."""

    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict) and list(before) == list(after):
        found: list[list[Any]] = []
        for key, value in after.items():
            if before[key] != value:
                found += changes(before[key], value, (*at, key))
        return found
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        found = []
        for index, (was, now) in enumerate(zip(before, after, strict=True)):
            if was != now:
                found += changes(was, now, (*at, index))
        return found
    return [[list(at), after]]


def changed(document: Any, made: list[list[Any]]) -> Any:
    """``document`` with ``made`` (:func:`changes`) made to it, in place where it can be."""

    for item in made:
        path, value = item[0], item[1] if len(item) > 1 else MISSING
        if not path:
            document = value
            continue
        holder = document
        for key in path[:-1]:
            holder = holder[key]
        if value is MISSING:
            del holder[path[-1]]
        else:
            holder[path[-1]] = value
    return document


def answered(
    workspace: Any, doc: Any, data: dict[str, Any], sent: Any, answer: Any, who: dict[str, Any]
) -> Any:
    """The kind's ``answer`` to an edit sent with ``base`` (``sent_document``), as the page
    takes it: kept (``commit``) when the studio's document is still the version the page has
    -- or else left for the page to send, merged as any edit of its own is -- what it changed
    (``delta``), the version it became (``version``, once kept) and, asked for (``draw``),
    its drawing (``drawing``)."""

    if not isinstance(answer, dict) or "document" not in answer:
        return answer
    answer = dict(answer)
    made = answer.pop("document")
    final = made
    base = int(data["base"])
    client = str(data.get("client") or who.get("id") or "")
    if data.get("commit") and not doc.held and not doc.unread:
        with doc.lock:
            # (Kept only on the version it was made from: made on an older one, the page has
            # yet to take in what changed since, and sends it as any edit, to be merged.)
            if base == doc.version:
                try:
                    version, final = doc.update(made, base, who, client)
                except ValueError:
                    final = made  # (refused, it is said when the page sends it)
                else:
                    answer["version"] = version
    answer["delta"] = changes(sent, final)
    asked = data.get("draw")
    if isinstance(asked, dict):
        answer["drawing"] = workspace.draw(
            doc.name,
            final,
            int(asked.get("version", 0)),
            asked.get("known") or {},
            asked.get("hints") or {},
        )
    return answer
