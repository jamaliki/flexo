"""The pages a figure is made for, and the letters of its panels.

A figure's page is its ``width`` and, where the page has a depth, its ``height``. The sizes
here are the ones with names: a journal's columns and a sheet of paper, what the studio's
Page Size offers. In a file a size is written as its lengths (``width: 89mm``), so a file
reads the same wherever it is opened; the two names a theme sizes itself
(``single-column``, ``double-column``) stay names.

A panel is a group with ``role: panel``: no frame, and a letter where a title goes. The
letters run in the order the panels are read -- the root's children first to last, and into
each -- so a panel moved or removed never leaves a letter out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.ir.semantic import FigureSpec, TextRun

PANEL_ROLE = "panel"
PANEL_LABELS = ("a", "A", "(a)", "(A)")
"""The ways of lettering panels a studio offers; ``panel_letter`` reads any written the same way."""
_PATTERN = re.compile(r"^([^A-Za-z0-9]*)([aA])([^A-Za-z0-9]*)$")
_TITLE_GAP = "\u2003"
"""Between a panel's letter and its title, where it has one: an em."""


@dataclass(frozen=True, slots=True)
class PageSize:
    name: str
    title: str
    width: str
    height: str | None = None
    """``None``: as tall as what is on it."""
    family: str = ""
    """What it is one of (a journal, "Paper"): the sizes of a family are listed together."""


PAGE_SIZES = (
    # Nature: its columns, and the full depth of its page (a figure with its legend under
    # it is kept to 170 mm).
    PageSize("nature-1", "Nature, One Column", "89mm", family="Nature"),
    PageSize("nature-2", "Nature, Two Columns", "183mm", family="Nature"),
    PageSize("nature-page", "Nature, Full Page", "183mm", "247mm", family="Nature"),
    # Science: as its instructions for revised research articles give them (1 column 9 cm,
    # 2 columns 18.4 cm, a figure narrower than two columns 14.4 cm at most); its older
    # guides give a three-column page's 5.5, 12 and 18.3 cm.
    PageSize("science-1", "Science, One Column", "90mm", family="Science"),
    PageSize("science-1.5", "Science, 1.5 Columns", "144mm", family="Science"),
    PageSize("science-2", "Science, Two Columns", "184mm", family="Science"),
    PageSize("cell-1", "Cell, One Column", "85mm", family="Cell"),
    PageSize("cell-1.5", "Cell, 1.5 Columns", "114mm", family="Cell"),
    PageSize("cell-2", "Cell, Full Width", "174mm", family="Cell"),
    PageSize("pnas-1", "PNAS, One Column", "87mm", family="PNAS"),
    PageSize("pnas-1.5", "PNAS, 1.5 Columns", "114mm", family="PNAS"),
    PageSize("pnas-2", "PNAS, Two Columns", "178mm", family="PNAS"),
    PageSize("a3", "A3", "297mm", "420mm", family="Paper"),
    PageSize("a4", "A4", "210mm", "297mm", family="Paper"),
    PageSize("a5", "A5", "148mm", "210mm", family="Paper"),
    PageSize("letter", "US Letter", "8.5in", "11in", family="Paper"),
)
"""The named sizes, in the order they are offered."""


def page_size(name: str) -> PageSize:
    """The size called ``name``; a ``FlexoError`` naming the ones there are otherwise."""

    for size in PAGE_SIZES:
        if size.name == name:
            return size
    raise FlexoError(
        Diagnostic(
            "figure.page.unknown",
            f'Unknown page size "{name}".',
            hint=f"Use one of: {', '.join(size.name for size in PAGE_SIZES)}.",
        )
    )


def panel_letter(index: int, pattern: str = "a") -> str:
    """The label of the panel at ``index`` (from 0), lettered as ``pattern`` shows the first:
    ``a`` gives a, b, c; ``(A)`` gives (A), (B), (C). After z come aa, ab, as columns are
    lettered."""

    found = _PATTERN.match(pattern)
    if found is None:
        raise FlexoError(
            Diagnostic(
                "figure.panel_labels.unknown",
                f'Panels can\'t be lettered as "{pattern}".',
                hint='Write the first panel\'s label: "a", "A", "(a)", "a)".',
            )
        )
    before, first, after = found.groups()
    letters, number = "", index + 1
    while number:
        number, at = divmod(number - 1, 26)
        letters = chr(ord(first) + at) + letters
    return f"{before}{letters}{after}"


def panels(figure: FigureSpec) -> tuple[str, ...]:
    """The figure's panels in the order they are read: the root's children first to last,
    each followed by what it holds. (A panel no group holds comes after, in the order
    written.)"""

    groups = {group.id: group for group in figure.groups}
    found: list[str] = []
    seen: set[str] = set()

    def walk(group_id: str) -> None:
        group = groups.get(group_id)
        if group is None or group_id in seen:
            return
        seen.add(group_id)
        if group.role == PANEL_ROLE:
            found.append(group_id)
        for child in group.children:
            walk(child)

    walk(figure.root)
    for group in figure.groups:
        walk(group.id)
    return tuple(found)


def lettered(figure: FigureSpec) -> FigureSpec:
    """``figure`` with each panel's letter written into its title, before a title of its
    own if it has one: what is measured and drawn. A figure with no panels is itself."""

    order = panels(figure)
    if not order:
        return figure
    letters = {
        group_id: panel_letter(index, figure.panel_labels) for index, group_id in enumerate(order)
    }
    return replace(
        figure,
        groups=tuple(
            replace(group, label=_titled(letters[group.id], group.label))
            if group.id in letters
            else group
            for group in figure.groups
        ),
    )


def _titled(letter: str, title: tuple[TextRun, ...]) -> tuple[TextRun, ...]:
    if not title:
        return (TextRun(letter),)
    return (TextRun(f"{letter}{_TITLE_GAP}"), *title)
