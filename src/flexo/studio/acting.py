"""An edit a page asks a document's kind to make (``/api/act``), sent as no more than what it is.

A page whose document is the studio's -- nothing of its own still on its way -- sends an edit
with the version it has (``base``) rather than the whole document: the studio makes it on its
own copy of that version. Asked to (``commit``), it keeps what the edit makes at once, as an
update from that version would; asked to (``draw``), it draws the document so made in the
same request. The answer says what the edit changed (``delta``: :func:`changes`) and the
version it became, never the whole document, with the drawing's pages that changed alone
(``Workspace.draw``): one request where an edit took an edit, an update and a drawing, each
carrying the whole document both ways.

Each such edit carries an id the page made for it (``once``), the same however often it is
sent: one the studio has kept already -- its answer lost, the studio stopped and started
again after its file was written -- is answered ``repeat``, never made twice. The ids kept
are written beside each save of the file (``saving``), each save's with the very words it
wrote, so that a studio started again knows those its file holds, and only those.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

MISSING = object()

KEPT_IDS = 256
"""How many of a document's edits are remembered as made, by their ids (``once``)."""
KEPT_SAVES = 8
"""How many of its saves are remembered, each with the ids of the edits it holds."""


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


# -- edits made once --

_LOCK = threading.Lock()
_MADE: dict[str, OrderedDict[str, int]] = {}
"""The ids of the edits each document holds (by ``_named``), and the version each became."""


def _named(workspace: Any, doc: Any) -> str:
    """A document, by where it is kept for its person: its bundle (wherever that is unpacked
    each time it is opened), or the folder it is in -- and its name there."""

    keeper = getattr(workspace, "bundle", None)
    where = keeper.path if keeper is not None else workspace.root
    return hashlib.sha256(f"{Path(where).resolve()}\0{doc.name}".encode()).hexdigest()[:32]


def _folder() -> Path | None:
    """Where the ids of edits made are kept between studios (``FLEXO_ACTS``: elsewhere, or
    "0" for nowhere)."""

    setting = os.environ.get("FLEXO_ACTS", "")
    if setting == "0":
        return None
    if setting:
        return Path(setting)
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/flexo/acts"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "flexo" / "acts"


def _saves(name: str) -> list[dict[str, Any]]:
    folder = _folder()
    try:
        saves = json.loads((folder / f"{name}.json").read_text(encoding="utf-8")) if folder else []
    except (OSError, ValueError):
        return []
    return [save for save in saves if isinstance(save, dict)] if isinstance(saves, list) else []


def _made(workspace: Any, doc: Any) -> OrderedDict[str, int]:
    """The ids of the edits ``doc`` holds: those made here, and -- found the first time it is
    asked, its file as the last studio left it -- those its file was written with: the save
    whose words it has, else (changed since by another app) the last."""

    name = _named(workspace, doc)
    with _LOCK:
        made = _MADE.get(name)
        if made is not None:
            return made
        saves = _saves(name)
        found: list[str] = []
        if saves:
            try:
                words = hashlib.sha256(doc.path.read_bytes()).hexdigest()
            except OSError:
                words = None
            held = next((save for save in reversed(saves) if save.get("words") == words), saves[-1])
            found = [str(item) for item in held.get("ids") or []]
        _MADE[name] = made = OrderedDict((item, 0) for item in found)
        return made


def made_already(workspace: Any, doc: Any, once: str) -> bool:
    """Whether the edit ``once`` is one the document holds already."""

    return bool(once) and once in _made(workspace, doc)


def saving(workspace: Any, doc: Any, written: Path, version: int | None = None) -> None:
    """``doc`` about to be written, its words in ``written`` -- the document at ``version``
    (written from what it was when the writing began: edits made since are not in them) --
    the ids of the edits they hold kept beside them first: a studio stopped before the file
    is put in place finds the file's words those of the save before, and the ids that save
    held."""

    folder = _folder()
    made = _made(workspace, doc)
    name = _named(workspace, doc)
    if folder is None or (not made and not (folder / f"{name}.json").exists()):
        return
    try:
        words = hashlib.sha256(written.read_bytes()).hexdigest()
    except OSError:
        return
    upto = doc.version if version is None else version
    with _LOCK:
        ids = [once for once, made_at in made.items() if made_at <= upto][-KEPT_IDS:]
    saves = [*_saves(name), {"words": words, "ids": ids}][-KEPT_SAVES:]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / f".{name}.{os.getpid()}.json"
        partial.write_text(json.dumps(saves), encoding="utf-8")
        os.replace(partial, folder / f"{name}.json")
    except OSError:
        return


def _keep(workspace: Any, doc: Any, once: str, version: int) -> None:
    made = _made(workspace, doc)
    with _LOCK:
        made.pop(once, None)
        made[once] = version
        while len(made) > KEPT_IDS:
            made.popitem(last=False)


def repeated(doc: Any) -> dict[str, Any]:
    """The answer to an edit the document holds already: nothing made again; the studio's
    version, for the page to take in what it has."""

    return {"repeat": True, "version": doc.version, "instance": doc.workspace.instance}


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
    once = str(data.get("once") or "")
    if data.get("commit") and not doc.held and not doc.unread:
        with doc.lock:
            # (Made once: sent again while the first was on its way, it is not made again.)
            if made_already(workspace, doc, once):
                return repeated(doc)
            # (Kept only on the version it was made from: made on an older one, the page has
            # yet to take in what changed since, and sends it as any edit, to be merged.)
            if base == doc.version:
                try:
                    version, final = doc.update(made, base, who, client)
                except ValueError:
                    final = made  # (refused, it is said when the page sends it)
                else:
                    answer["version"] = version
                    if once:
                        _keep(workspace, doc, once, version)
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
        if "version" in answer:
            # (Written to its file once its drawing is answered, not while it is drawn: the
            # two would only wait on each other.)
            with doc.lock:
                doc.changed_at = max(doc.changed_at, time.monotonic())
    return answer
