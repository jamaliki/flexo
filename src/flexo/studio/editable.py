"""A drawing placed as a picture, made the shapes it draws: Make Editable.

A drawing made in Inkscape (an SVG; a PDF's or an Illustrator file's page) placed as one
picture -- before the studio read drawings as shapes, or with Paste as Picture -- is one
object: nothing in it can be moved, sized or retyped by itself. Made editable, it is the shapes
``flexo.svgimport`` reads it as, one group, put exactly where the picture was drawn and scaled
to the box it was drawn in (the picture's page, made the box's size), so nothing on the page
moves. It is read as the picture was drawn -- restyled (``flexo.restyle``: its words in the
font they were shown in, its texts and colours changed as they were) -- and its colours are the
theme's where they are the theme's, its words in the page's markup, as a drawing pasted is.
What no shape draws (a photograph in it, a blur) is kept as a picture among them, written
beside the document as a paste's are. The drawing's file is left as it was: another picture
may show it, and it opens in Inkscape as before.

A deck's pictures come here (flexo-talk), saying where each was drawn. A figure's picture is
not offered: it is a part of the figure's layout, so taking it out lays the figure out again --
the parts after it close up into its room, under the drawing put where it was, and the lines
joined to it lose their end -- and keeping its room would need a part that draws nothing in
its place. A drawing pasted over a figure is its shapes already.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flexo import freeform, svgimport

DRAWING = re.compile(r"\.(svg|pdf|ai)(#\d+)?$", re.IGNORECASE)
"""A picture's file that is a drawing, read as shapes: an SVG, a PDF's or an Illustrator
file's page (``art.ai#2``, its second artboard)."""

OWNER = "flexo-editable"
"""The name the drawing is read under (its ids are given it as a prefix, taken off again)."""


def is_drawing(source: object) -> bool:
    """Whether a picture's file is a drawing that can be made shapes."""

    return isinstance(source, str) and bool(DRAWING.search(source.strip()))


@dataclass(slots=True)
class Editable:
    """What a picture became: the group of its shapes, and what was said of it."""

    group: dict[str, Any]
    """One group, its id given, placed where the picture was drawn."""
    count: int
    """How many shapes it is, the group's own counted."""
    kept: list[str] = field(default_factory=list)
    """What is kept as a picture among the shapes, as no shape draws it, in words."""
    approximated: list[str] = field(default_factory=list)
    cropped: int = 0
    """Shapes left out, wholly outside the part of the picture its crop kept."""


class NotEditable(ValueError):
    """A picture that can't be made shapes, and why, in words."""


def shapes_of_picture(
    source: Path,
    box: Sequence[float],
    *,
    restyle: Any = None,
    family: str = "",
    roles: Mapping[str, str] | None = None,
    markup: str = "slide",
    keep: Callable[[bytes, str], str] | None = None,
    taken: Sequence[str] = (),
    kept_box: Sequence[float] | None = None,
) -> Editable:
    """The drawing ``source`` as the shapes it draws, its page in ``box`` (``x, y, width,
    height``, in the units of the page it is on): where a picture of it was drawn. ``restyle``
    and ``family`` restyle it as its picture was (a ``flexo.restyle.Restyle`` and the font its
    words are set in); ``roles`` are the theme's colours by role, ``markup`` its words' markup
    (``slide`` or ``figure``); ``keep`` writes a picture kept among the shapes and names it.
    ``taken``: the ids the page has already. ``kept_box``: the part of the picture shown (its
    crop), outside which no shape is kept."""

    from flexo.artwork import load_artwork
    from flexo.restyle import Restyle, restyled

    try:
        art = load_artwork(OWNER, str(source))
    except Exception as error:  # a file that is not there, or does not read
        raise NotEditable(f"{Path(str(source)).name} can\u2019t be read: {error}") from None
    if art.format != "svg" or not art.markup:
        raise NotEditable(f"{Path(str(source)).name} is a photograph, not a drawing.")
    art = restyled(art, restyle or Restyle(), family or "")
    drawing = _unprefixed(art.markup)
    x, y, width, _ = (float(value) for value in box)
    page_width = art.width
    if not page_width:
        # (A drawing that says no size: its page as the reader finds it.)
        page_width = svgimport.shapes_of(drawing, scale=1.0).page[0] or width
    stem = Path(str(source).split("#")[0]).stem
    try:
        made = svgimport.shapes_of(
            drawing,
            roles=roles,
            markup=markup,
            scale=width / page_width,
            origin=(x, y),
            picture=keep,
            name=stem,
            taken=list(taken),
        )
    except svgimport.SvgImportError as error:
        raise NotEditable(str(error)) from None
    if not made.shapes:
        raise NotEditable(f"Nothing in {Path(str(source)).name} is drawn as shapes.")
    if made.count > svgimport.SHAPES_AT_MOST:
        raise NotEditable(
            f"{Path(str(source)).name} is {made.count:,} pieces: more than are edited one by one."
        )
    # One group, named: what a line glued to the picture is glued to now.
    whole = len(made.shapes) == 1 and made.shapes[0].get("kind") == "group"
    group = _lifted(dict(made.shapes[0]) if whole else {"kind": "group", "shapes": made.shapes})
    if not group.get("id"):
        rest = {key: value for key, value in group.items() if key not in ("kind", "id")}
        group = {"kind": "group", "id": _free(_name(stem), taken, group), **rest}
    cropped = 0
    if kept_box is not None:
        group["shapes"], cropped = _within(group["shapes"], kept_box)
    count = sum(_count(shape) for shape in group["shapes"]) + 1
    return Editable(group, count, list(made.kept), list(made.approximated), cropped)


def keeper(folder: Path, stem: str) -> Callable[[bytes, str], str]:
    """Writes a picture kept among a drawing's shapes into ``folder``'s ``assets``, as a
    paste's are (``{stem}-part-1.png``…), and names it from ``folder``."""

    from flexo.studio.importing import _clean, _unique

    def keep(content: bytes, suffix: str) -> str:
        target = _unique(folder / "assets", f"{_clean(stem)}-part", suffix, content)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return target.relative_to(folder).as_posix()

    return keep


def ids_of(shapes: Sequence[Any]) -> list[str]:
    """Every id among ``shapes``, a group's shapes' too."""

    found: list[str] = []
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        if shape.get("id") is not None:
            found.append(str(shape["id"]))
        if shape.get("kind") == "group":
            found += ids_of(shape.get("shapes") or [])
    return found


def _unprefixed(markup: str) -> str:
    """The drawing's ids as its program wrote them (the reader gives them to the shapes it
    names after them), and every reference to them."""

    return markup.replace(f'id="{OWNER}.', 'id="').replace(f"#{OWNER}.", "#")


def _name(stem: str) -> str:
    named = re.sub(r"[^A-Za-z0-9._-]+", "-", stem.strip()).strip("-").lower()[:60]
    return named or "drawing"


def _free(name: str, taken: Sequence[str], group: Mapping[str, Any]) -> str:
    """``name``, or ``name-2``…: one neither the page nor the drawing has."""

    used = set(taken) | set(ids_of(group.get("shapes") or []))
    chosen, number = name, 2
    while chosen in used:
        chosen, number = f"{name}-{number}", number + 1
    return chosen


def _lifted(group: dict[str, Any]) -> dict[str, Any]:
    """``group`` without the groups that only wrap another (a layer, a drawing's one outer
    ``<g>``): its pieces one Ungroup away, not several. One the drawing named, or drawn
    see-through as a whole, stays."""

    while True:
        shapes = group.get("shapes") or []
        if (
            len(shapes) != 1
            or not isinstance(shapes[0], Mapping)
            or shapes[0].get("kind") != "group"
        ):
            return group
        inner = shapes[0]
        if inner.get("id") is not None or inner.get("opacity") is not None:
            return group
        group = {**group, "shapes": list(inner.get("shapes") or [])}


def _count(shape: Mapping[str, Any]) -> int:
    return 1 + sum(_count(child) for child in shape.get("shapes") or [])


def _within(shapes: list[dict[str, Any]], box: Sequence[float]) -> tuple[list[dict[str, Any]], int]:
    """The shapes with any of them in ``box`` (``x, y, width, height``): the rest -- what a
    crop hid -- left out, and how many."""

    x, y, width, height = (float(value) for value in box)
    kept, gone = [], 0
    for shape in shapes:
        try:
            left, top, right, bottom = freeform.bounds(shape)
        except (KeyError, TypeError, ValueError):
            kept.append(shape)
            continue
        if right < x or left > x + width or bottom < y or top > y + height:
            gone += _count(shape)
            continue
        kept.append(shape)
    return kept, gone


__all__ = [
    "DRAWING",
    "Editable",
    "NotEditable",
    "ids_of",
    "is_drawing",
    "keeper",
    "shapes_of_picture",
]
