"""A figure a document holds -- a deck's, on its slide -- edited in a tab of its own.

The figure editor edits a figure document: its words, as a figure file has them
(``flexo.studio.figure_kind``). A deck keeps its figures inside it (flexo-talk's
``flexo_talk.embedding``), and its kind says how to read one and put it back (``figure_in``,
``with_figure``, named by a key of the kind's: the figure's id, or its name among the deck's
own). ``talk.yaml#pipeline`` names the figure ``pipeline`` in the deck ``talk.yaml``: a document
of the figure kind that the workspace opens as any other (``Workspace.open``, ``view``) and the
figure editor edits as it edits a file -- its Source, its layout tree, its exports -- whose
words are the figure as the deck holds it, written out as YAML.

An edit made to it is made to the deck at once: one change of the deck's, merged with others'
as theirs are, written with the deck (``FigureView.update``). An edit made to the deck -- on the
slide, undone there, an agent's -- comes to it (``follow``). Each tab keeps its own history, as
two windows do: ⌘Z in the figure's tab takes back what was done there, in the deck's what was
done on the slide. Nothing is written but the deck: the figure has no file. Its words that do
not read as YAML (typed half-way in its Source) stay in the tab, the deck as it was, until they
read; the figure gone from the deck (its slide deleted), the tab says so, and takes no edits
until it is back (the deletion undone).
"""

from __future__ import annotations

import contextlib
import copy
import json
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

import yaml

from flexo.studio.merge import merge3
from flexo.studio.workspace import DOCUMENT_SUFFIXES, LOOK, RECENT, Doc, Workspace, _dumps

SEPARATOR = "#"
"""Between a document's name and the key of a figure it holds: ``talk.yaml#pipeline``."""


class _Dumper(yaml.SafeDumper):
    """A figure's words as a person writes them: block style, words over several lines as
    literal blocks (``|-``)."""


def _string(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    )


_Dumper.add_representer(str, _string)


def words_of(figure: Any) -> str:
    """A figure document as its words in the figure editor's Source."""

    return yaml.dump(figure, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def _read(text: str) -> Any:
    """A figure's words as data; None for words that do not read (yet)."""

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _same(one: Any, other: Any) -> bool:
    return json.dumps(one, sort_keys=True, default=str) == json.dumps(
        other, sort_keys=True, default=str
    )


def split(name: str) -> tuple[str, str] | None:
    """A view's name as its document's and the figure's key; None for any other name."""

    document, found, key = name.partition(SEPARATOR)
    if not found or not key or not document.lower().endswith(DOCUMENT_SUFFIXES):
        return None
    return document, key


class FigureView(Doc):
    """A figure a document holds, as a figure document of its own (see the module)."""

    def __init__(
        self, workspace: Workspace, name: str, parent: Doc, key: str, figure: dict[str, Any]
    ) -> None:
        # (Not Doc's own: there is no file to read. What a Doc has, it has.)
        self.workspace = workspace
        self.name = name
        self.parent = parent
        self.key = key
        self.kind = workspace.kinds["figure"]
        # Its folder the deck's, so the files its parts draw are found as the deck finds them;
        # its stem the figure's, for its exports' names. Never a file: nothing is written here.
        self.path = parent.path.parent / f"{_stem(key)}.yaml"
        self.lock = threading.RLock()
        self.drawing = threading.Lock()
        self.exists = True
        self.problem: str | None = None
        self.held = False
        self.unread = False
        self.foreign: str | None = None
        self.document = {"text": words_of(figure)}
        self.version = 1
        self.history: OrderedDict[int, str] = OrderedDict({1: _dumps(self.document)})
        self.authors: OrderedDict[int, dict[str, Any]] = OrderedDict()
        self.saved = 1
        self.changed_at = 0.0
        self.unsaved_since = 0.0
        self.retry_at = 0.0
        self.on_disk = None
        self.recent: deque[tuple[str, bool, bool]] = deque(maxlen=RECENT)
        self.told = None
        self.opened_at = time.time()
        self.disk_text = None
        self.disk_stamp = 0.0
        self.depends: set[Path] = set()
        self.depend_stamps: dict[Path, float] = {}
        self.moved: str | None = None
        self.gone = False
        self.file = None
        self.look_at = float("inf")  # (never looked for in the folder: it is in its deck)
        self.look_every = LOOK[1]

    # -- edits --

    def update(
        self, document: Any, base: int, who: dict[str, Any], client: str = ""
    ) -> tuple[int, Any]:
        """Take a changed figure made from version ``base`` -- merged with changes made since,
        as any document's are -- and make it the deck's: one change of the deck's."""

        if self.gone:
            raise ValueError(f"{self.problem} Nothing was changed.")
        if not isinstance(document, dict) or not isinstance(document.get("text"), str):
            raise ValueError("A figure is its words. Nothing was changed.")
        notes: list = []
        with self.lock:
            if base == self.version:
                merged = self._mended(document, notes, self.document)
            else:
                known = self.history.get(base)
                start = json.loads(known) if known is not None else self.document
                merged = self._mended(merge3(start, self.document, document, notes), notes, start)
            others = self.author_since(base, who)
            self._become(merged, who, client, news=False)
        self._tell(notes, who, client, others)
        self.carry(who, client)
        with self.lock:
            return self.version, self.document

    def carry(self, who: dict[str, Any], client: str) -> None:
        """The figure as it is here, put in the deck where it is kept -- unless its words do
        not read (yet), or the deck holds it so already."""

        with self.lock:
            figure = _read(self.document.get("text", ""))
        if figure is None:
            return
        parent = self.parent
        with parent.lock:
            document, version = parent.document, parent.version
            if _same(parent.kind.figure_in(document, self.key), figure):
                return
            changed = parent.kind.with_figure(document, self.key, figure)
        if changed is not None:
            parent.update(changed, version, who, client)

    def followed(self, document: Any, who: dict[str, Any], client: str) -> None:
        """The deck changed (``document``, as it is now): the figure as it holds it, taken in
        here -- or, gone from it, said so."""

        figure = self.parent.kind.figure_in(document, self.key)
        said = None
        with self.lock:
            if figure is None:
                if not self.gone:
                    self.gone = True
                    self.problem = (
                        f"This figure is no longer in {_shown(self.parent.name)}. "
                        "Undo there to bring it back."
                    )
                    said = self.said()
            else:
                if self.gone:
                    self.gone, self.problem = False, None
                    said = self.said()
                here = _read(self.document.get("text", ""))
                if here is None or not _same(here, figure):
                    self._become(
                        {**self.document, "text": words_of(figure)}, who, client, news=False
                    )
        if said is not None:
            self.workspace.broadcast(said)

    # -- the file it has none of --

    def write(self, *, again: bool = False) -> bool:
        """Saved as its deck is: the deck written, if it has changes."""

        self.workspace._write(self.parent)
        with self.lock:
            done = self.parent.saved >= self.parent.version
            if done:
                self.saved = self.version
        return done

    def reread(self) -> str | None:
        return None

    def mend(self, text: str, *, over: bool = False) -> None:
        raise ValueError("This figure is kept in its deck: edit it here, or in the deck.")

    def take_conflict(self, copy_path: Path, service: str) -> bool:
        return False


def _stem(key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in key).strip("-.") or "figure"


def _shown(name: str) -> str:
    stem = name.rsplit("/", 1)[-1]
    for suffix in DOCUMENT_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return f"“{stem}”"


def view(workspace: Workspace, name: str) -> FigureView | None:
    """The view ``name`` names (``talk.yaml#pipeline``), opened if it is not; None if the name
    is no view's (its document's kind holds no figures). A figure its document does not hold
    is a FileNotFoundError, said plainly."""

    parts = split(name)
    if parts is None:
        return None
    views = workspace.views
    with workspace.lock:
        found = views.get(name)
    if found is not None:
        return found
    document, key = parts
    parent = workspace.open(document)
    kind = parent.kind
    if not callable(getattr(kind, "figure_in", None)) or not callable(
        getattr(kind, "with_figure", None)
    ):
        return None
    with parent.lock:
        figure = kind.figure_in(parent.document, key)
    if figure is None:
        raise FileNotFoundError(f"There\u2019s no figure “{key}” in {_shown(parent.name)}.")
    with workspace.lock:
        found = views.get(name)
        if found is None:
            found = views[name] = FigureView(workspace, name, parent, key, copy.deepcopy(figure))
    return found


def views_of(workspace: Workspace, doc: Doc) -> list[FigureView]:
    with workspace.lock:
        return [
            one
            for one in workspace.views.values()
            if isinstance(one, FigureView) and one.parent is doc
        ]


def follow(workspace: Workspace, doc: Doc, after: Any, who: dict[str, Any], client: str) -> None:
    """A document changed: each figure of it open in a tab of its own takes in the change."""

    if isinstance(doc, FigureView):
        return
    for one in views_of(workspace, doc):
        with contextlib.suppress(Exception):
            one.followed(after, who, client)


def saved(workspace: Workspace, doc: Doc) -> None:
    """A document written: each figure of it open in a tab of its own is saved too, and the
    pages told."""

    if isinstance(doc, FigureView) or doc.saved < doc.version:
        return
    for one in views_of(workspace, doc):
        with one.lock:
            one.saved = one.version
            version = one.saved
        workspace.broadcast({"type": "saved", "file": one.name, "version": version})
