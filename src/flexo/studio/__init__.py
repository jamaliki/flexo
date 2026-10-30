"""Flexo studio: a local editor for documents flexo and its companions draw.

``flexo studio figure.yaml`` serves the editor on this machine and opens it in a
browser. What a document is and how it is edited is a *kind*: flexo brings the
figure kind; other packages add theirs (flexo-talk adds decks) through the
``flexo.studio`` entry-point group, each an object with the ``Kind`` interface.
The studio gives every kind the same page: the document's file, saving, undo,
live drawing, exports, and a shared set of controls (``static/studio.js``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# The folder being edited, while a document is drawn or exported in it: a file the
# document names must be inside it. The workspace sets it.
from flexo.confine import folder_root as folder_root

code_allowed: ContextVar[bool] = ContextVar("flexo_studio_code_allowed", default=True)
"""Whether a document's own code (a deck's plots.py) may run as it is drawn or exported:
not in a folder its person has not said they trust. The workspace sets it."""

_TURN: ContextVar[Any] = ContextVar("flexo_studio_turn", default=None)
"""The lock a drawing holds while it is its folder's turn to draw (``taking_turns``)."""


@contextmanager
def taking_turns(lock: Any) -> Iterator[None]:
    """A folder's documents are drawn one at a time, each in its turn (``lock``, held
    within) -- which a drawing gives up while it waits for another process (``waiting``)."""

    with lock:
        token = _TURN.set(lock)
        try:
            yield
        finally:
            _TURN.reset(token)


@contextmanager
def waiting() -> Iterator[None]:
    """Around a wait for work done in another process -- a plot run apart, which may never
    return: the folder's turn to draw is another document's meanwhile, and is taken again
    after. (Nothing is drawn in this process while it waits; held, its turn would keep
    every other document of the folder waiting out the plot's time with it.)"""

    lock = _TURN.get()
    if lock is None:
        yield
        return
    # (A wait within this one has no turn to give up.)
    token = _TURN.set(None)
    lock.release()
    try:
        yield
    finally:
        lock.acquire()
        _TURN.reset(token)


@dataclass(slots=True)
class Page:
    """One drawn page of a document: a slide, or a figure."""

    id: str
    svg: str
    label: str = ""
    steps: int = 1
    """How many states the page shows in turn (a list revealed item by item)."""
    extra: dict[str, Any] = field(default_factory=dict)
    pending: bool = False
    """Not drawn this time (the drawing ran out of time); the page keeps what it showed."""


@dataclass(slots=True)
class Message:
    """Something the drawing says about the document: ``where`` names the place in
    the kind's own terms (``slides[3].left[1]``, ``nodes[2]``, a page id)."""

    text: str
    severity: str = "warning"
    """``error``, ``warning``, or ``note``."""
    where: str = ""
    page: str = ""
    """The id of the page it concerns, when it concerns one."""
    code: str = ""
    """A stable name for the kind of message (``layout.width.grown``)."""
    place: str = ""
    """``where`` as a person says it (``Slide 4 · Picture``), for the page to show."""


@dataclass(slots=True)
class Drawing:
    """A document drawn: its pages, what the drawing says, and the files it read
    (so the studio draws again when one changes)."""

    pages: list[Page]
    messages: list[Message] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    """Whatever else the kind's page needs from a drawing (the colours a theme resolved to)."""
    again: bool = False
    """Whether the page is to ask for it again as it is: something in it was not ready (a
    plot whose Python was still starting)."""

    @property
    def unfinished(self) -> bool:
        """Whether some pages are still to be drawn: the page asks again for them."""

        return any(page.pending for page in self.pages)


class Kind(Protocol):
    """A kind of document the studio edits."""

    name: str
    """Short and unique: ``figure``, ``deck``."""
    title: str
    """For people: ``Figure``, ``Deck``."""
    static: Path
    """A folder served to the page; its ``editor.js`` exports ``mount(studio)``."""

    def claims(self, document: object) -> bool:
        """Whether a parsed file is a document of this kind."""

    def new(self, path: Path) -> Any:
        """A document to start from, for a file that does not exist yet."""

    def load(self, path: Path) -> Any:
        """The document in a file, as JSON the page edits."""

    def save(self, path: Path, document: Any) -> None:
        """Write the document to its file."""

    def catalog(self) -> dict[str, Any]:
        """What the page offers to choose from (themes, fonts, ...)."""

    def draw(self, document: Any, base: Path, hints: dict[str, Any]) -> Drawing:
        """Draw the document; files it names are found from ``base``. ``hints`` are
        what the page says about where the person is (``{"focus": 3}``); a kind
        with many pages may draw that one first and leave others pending."""

    def export(self, document: Any, base: Path, stem: str, formats: list[str]) -> list[Path]:
        """Write the document's outputs into ``base / "build"``; the files written. A kind
        may take ``into=``, a folder to write them in instead (the page's exports are made
        aside and handed to its person), and options of its own (a deck's ``steps=``)."""

    # A kind may also offer, for agents and the activity list:
    #   dump(document) -> str and parse(text) -> document: the document as text
    #       an agent edits (YAML by default);
    #   guide() -> str: how its documents are written, given to an agent once;
    #   describe(before, after) -> [{"text", "where"}]: what a change did;
    #   check(document, base) -> [str]: what is wrong with a document, quickly;
    #   adopt(data) -> document: a parsed document as this kind keeps it;
    #   act(document, action, base) -> {"document", ...}: an edit the page asks for
    #       by name (a figure's part added or connected), made by the kind.
    #   export_part(document, base, stem, part, formats) -> [Path]: one part of the
    #       document written out by itself (a figure on a slide), as export does.
    #   bundled(document, base) -> document: the document as a bundle of it keeps it,
    #       what it names beside it that belongs inside it written in (a deck's figure
    #       files), as it is packed (flexo.bundle.pack).
    #   figure_in(document, key) -> figure document | None and with_figure(document, key,
    #       figure) -> document: a figure the document holds (a deck's, on a slide), read
    #       and put back, for the figure editor to edit it in a tab of its own
    #       (flexo.studio.embedded).
    #   theme_of(document) -> str | None and with_theme(document, theme, base) ->
    #       document: the theme a document is drawn in (a name, or a theme file named
    #       from its folder), read and set, so one theme can be put to use in many.
    #   malformed(document) -> str | None: what makes a document one its editor cannot
    #       show (a deck whose slides are a number), if anything: such a file is not
    #       taken in (nor written over), and such an edit is refused.
    # And, for agents to read it a little at a time (flexo.studio.agent_guides, agent_read,
    # agent_look, agent_report):
    #   brief() -> str: what an agent is told first, guide()'s topics a call away;
    #   topics() -> {name: agent_guides.Topic}: guide() cut into topics, with examples;
    #   outline(document, drawing) -> [str]: the document in brief, a line a page;
    #   excerpt(text, numbers) -> str: some of its pages (a deck's slides), as the text has them;
    #   selected(document, where) -> str | None: where a person is, as a path in its YAML;
    #   marks(document, number, page) -> [agent_look.Mark]: what to outline on a page;
    #   at_step(page, step) -> str: a page's drawing as it stands at a build step;
    #   report(before, after) -> {"changes", "deleted", "pages", "noun"}: what an edit did.


def kinds() -> dict[str, Kind]:
    """Every kind the studio knows: flexo's own and those installed packages add."""

    from importlib.metadata import entry_points

    from flexo.studio.figure_kind import FigureKind
    from flexo.studio.theme_kind import ThemeKind

    found: dict[str, Kind] = {"figure": FigureKind(), "theme": ThemeKind()}
    for entry in entry_points(group="flexo.studio"):
        try:
            kind = entry.load()
        except Exception:  # a broken plug-in must not take the studio down
            continue
        kind = kind() if isinstance(kind, type) else kind
        found[kind.name] = kind
    return found


__all__ = ["Drawing", "Kind", "Message", "Page", "kinds"]
