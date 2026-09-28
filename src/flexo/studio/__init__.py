"""Flexo studio: a local editor for documents flexo and its companions draw.

``flexo studio figure.yaml`` serves the editor on this machine and opens it in a
browser. What a document is and how it is edited is a *kind*: flexo brings the
figure kind; other packages add theirs (flexo-talk adds decks) through the
``flexo.studio`` entry-point group, each an object with the ``Kind`` interface.
The studio gives every kind the same page: the document's file, saving, undo,
live drawing, exports, and a shared set of controls (``static/studio.js``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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


@dataclass(slots=True)
class Drawing:
    """A document drawn: its pages, what the drawing says, and the files it read
    (so the studio draws again when one changes)."""

    pages: list[Page]
    messages: list[Message] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    """Whatever else the kind's page needs from a drawing (the colours a theme resolved to)."""

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
        """Write the document's outputs into ``base / "build"``; the files written."""

    # A kind may also offer, for agents and the activity list:
    #   dump(document) -> str and parse(text) -> document: the document as text
    #       an agent edits (YAML by default);
    #   guide() -> str: how its documents are written, given to an agent once;
    #   describe(before, after) -> [{"text", "where"}]: what a change did;
    #   check(document, base) -> [str]: what is wrong with a document, quickly;
    #   adopt(data) -> document: a parsed document as this kind keeps it.


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
