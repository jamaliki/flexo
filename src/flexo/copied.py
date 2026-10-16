"""What is copied out of Flexo, drawn as Flexo draws it, for other apps to paste.

A copy is part of a drawing -- a figure's parts, the objects and shapes chosen on a slide --
or all of it. ``cut_out`` takes the drawing's SVG and the ids of what is copied and makes
the SVG of those alone, on a page of their own just big enough for them (and, nothing
named, the whole page as it is). A ``Copied`` then makes each form an app pastes, when it
is first asked for, and once:

- ``pdf()``: its words text, in the fonts Flexo set them in, embedded (``flexo.pdf``) --
  what Keynote, PowerPoint, Word and Pages paste as a crisp drawing;
- ``svg()``: its words as outlines (``flexo.portable``), for Inkscape, Illustrator,
  Affinity and Google Slides, none of which draws an SVG's own fonts;
- ``png()``: a picture of it, four times its size and saying so (its ``pHYs``), so it
  pastes at its own size, for apps that take only pictures.

Each is drawn from the same drawing an export is (``flexo.drawing``): the same faces, the
theme's colours, a picture at its full size. What is there only while it is edited -- a
placeholder's faint words, a slide's words held in place while typed -- is left out, as
Present and the exports leave it out.
"""

from __future__ import annotations

import re
import struct
import threading
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable, Iterable
from functools import cached_property

from flexo.drawing import Drawing, Group, Image, Shape, Text, ink_bounds, read_drawing
from flexo.svg import local_name, number, xml_document

MARGIN = 2.0
"""Points of room round what is cut out: a stroke's antialiased edge is never cut."""

PNG_SCALE = 4.0
"""How many times its size a copy's picture is drawn: 288 pixels to the inch."""

PNG_PIXELS = 40_000_000
"""The most pixels a copy's picture has: a large slide's is drawn smaller than four times."""

EDITING = ("data-flexo-placeholder", "data-flexo-editing")
"""What marks a piece of a drawing as there only while it is edited."""

PRESENTED = "data-flexo-presented"
"""What marks a slide as it is presented, kept hidden in the drawing edited (flexo-talk)."""

HELD = "data-flexo-held"
"""What marks a group kept only because it holds what is copied (its transform, its clip):
an app that groups shapes pastes its shapes without it."""

_KEPT = frozenset(
    {
        "defs",
        "style",
        "title",
        "desc",
        "metadata",
        "clipPath",
        "mask",
        "marker",
        "linearGradient",
        "radialGradient",
        "pattern",
        "filter",
        "symbol",
    }
)
"""What is kept of a drawing however little of it is copied: what its shapes may use."""

_HREF = ("href", "{http://www.w3.org/1999/xlink}href")


def cut_out(
    svg: str,
    keep: Iterable[str] = (),
    *,
    margin: float = MARGIN,
    picture: Callable[[str], str | None] | None = None,
) -> str:
    """The SVG of what ``svg`` draws with the ids in ``keep``, and what they hold, on a page
    just big enough for it, ``margin`` points round it; with no ids, the whole page.

    ``picture``, given, carries the pictures it names by an address (``carried``): a
    ``Copied`` may carry them only when it is first drawn instead. Raises ``ValueError`` when
    none of the ids is drawn, or they draw nothing."""

    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", svg, count=1))
    wanted = [str(identifier) for identifier in keep if identifier]
    parents = {child: parent for parent in root.iter() for child in parent}
    _editing_left_out(root, parents, whole=not wanted)
    if not wanted:
        return carried(xml_document(root), picture)
    named = {item.get("id"): item for item in root.iter() if item.get("id")}
    chosen = [named[identifier] for identifier in dict.fromkeys(wanted) if identifier in named]
    if not chosen:
        raise ValueError("Nothing of what is copied is drawn.")
    _pruned(root, parents, chosen)
    text = xml_document(root)
    bounds = _bounds(read_drawing(text))
    if bounds is None:
        raise ValueError("What is copied draws nothing.")
    view = _view(root)
    per_unit = _points_per_unit(root, view)
    room = margin / per_unit
    left, top, right, bottom = bounds
    x, y = view[0] + left - room, view[1] + top - room
    width, height = right - left + 2 * room, bottom - top + 2 * room
    root.set("viewBox", f"{number(x)} {number(y)} {number(width)} {number(height)}")
    root.set("width", f"{number(width * per_unit)}pt")
    root.set("height", f"{number(height * per_unit)}pt")
    # (A background under it all, the slide's or the canvas's, was not chosen: it is gone.)
    return carried(xml_document(root), picture)


_LINKED = re.compile(r"<image\b[^>]*\b(?:xlink:)?href=\"(?!data:)")


def carried(svg: str, picture: Callable[[str], str | None] | None) -> str:
    """``svg`` carrying each picture it names by an address (the studio names photographs so
    for its page): ``picture`` gives its bytes, as a ``data:`` URI; one it gives nothing for
    is left out. A drawing that names none is as it was."""

    if picture is None or not _LINKED.search(svg):
        return svg
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", svg, count=1))
    parents = {child: parent for parent in root.iter() for child in parent}
    _pictures_carried(root, parents, picture)
    return xml_document(root)


def _editing_left_out(root: ET.Element, parents: dict, *, whole: bool) -> None:
    """What is drawn only while editing taken out. A slide copied whole is the slide as it is
    presented (where it keeps one, hidden, beside the slide edited); one copied in part is
    the slide edited, whose ids the parts copied have."""

    for item in list(root.iter()):
        if item.get(PRESENTED) is not None:
            if whole:
                item.attrib.pop("display", None)
                item.attrib.pop(PRESENTED, None)
            elif item in parents:
                parents[item].remove(item)
    for item in list(root.iter()):
        editing = any(item.get(mark) is not None for mark in EDITING)
        if editing and item in parents and (whole or item.get("data-flexo-editing") is None):
            parents[item].remove(item)


def _pictures_carried(
    root: ET.Element, parents: dict, picture: Callable[[str], str | None]
) -> None:
    for item in list(root.iter()):
        if local_name(item.tag) != "image":
            continue
        for name in _HREF:
            href = item.get(name)
            if href is None or href.startswith("data:"):
                continue
            carried = picture(href)
            if carried:
                item.set(name, carried)
            elif item in parents:
                parents[item].remove(item)
            break


def _pruned(root: ET.Element, parents: dict, chosen: list[ET.Element]) -> None:
    """Only ``chosen`` left, whole, in the groups they are in (their transforms, their
    clips), and what any drawing keeps (``_KEPT``)."""

    whole = set(chosen)
    holding: set[ET.Element] = set()
    for item in chosen:
        holder = parents.get(item)
        while holder is not None and holder is not root:
            holding.add(holder)
            holder = parents.get(holder)

    def prune(holder: ET.Element) -> None:
        for child in list(holder):
            if child in whole:
                continue
            if child in holding:
                # (Marked: what only holds what is copied is no group of its own pasted.)
                child.set(HELD, "")
                prune(child)
            elif local_name(child.tag) not in _KEPT:
                holder.remove(child)

    prune(root)


def _view(root: ET.Element) -> list[float]:
    from flexo.drawing import _length

    view = [float(value) for value in re.split(r"[ ,]+", root.get("viewBox", "").strip()) if value]
    if len(view) != 4:
        view = [0.0, 0.0, _length(root.get("width")), _length(root.get("height"))]
    return view


def _points_per_unit(root: ET.Element, view: list[float]) -> float:
    from flexo.drawing import _length

    width = _length(root.get("width"))
    return width / view[2] if width > 0 and view[2] > 0 else 1.0


def _bounds(drawing: Drawing) -> tuple[float, float, float, float] | None:
    """What ``drawing`` paints, ``left, top, right, bottom``; None if it paints nothing."""

    def paints(item: Shape | Text | Image | Group) -> bool:
        if isinstance(item, Shape):
            return item.paint.fill is not None or item.paint.stroke is not None
        if isinstance(item, Text):
            return any(line.runs for line in item.lines)
        return isinstance(item, Image)

    if not any(paints(item) for item in drawing.walk()):
        return None
    return ink_bounds(drawing)


class Copied:
    """A copy, drawn: its SVG as Flexo writes it (``editable``), and each form an app pastes,
    made when first asked for and kept. Its pictures named by an address are carried
    (``picture``, as ``carried``) only then: a copy of a slide's large photograph is made at
    once. Safe to ask from any thread."""

    def __init__(
        self, svg: str, *, title: str = "", picture: Callable[[str], str | None] | None = None
    ) -> None:
        self.cut = svg
        self.title = title
        self._picture = picture
        self._lock = threading.RLock()
        self._made: dict[str, bytes | str] = {}

    @cached_property
    def editable(self) -> str:
        return carried(self.cut, self._picture)

    @cached_property
    def drawing(self) -> Drawing:
        return read_drawing(self.editable)

    @cached_property
    def size(self) -> tuple[float, float]:
        """Its width and height in points."""

        root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", self.cut, count=1))
        view = _view(root)
        per_unit = _points_per_unit(root, view)
        return view[2] * per_unit, view[3] * per_unit

    def once(self, name: str, make: Callable[[], bytes | str]) -> bytes | str:
        with self._lock:
            if name not in self._made:
                self._made[name] = make()
            return self._made[name]

    def pdf(self) -> bytes:
        from flexo.pdf import pdf_bytes

        return self.once("pdf", lambda: pdf_bytes(self.drawing, title=self.title))  # type: ignore[return-value]

    def svg(self) -> str:
        """The portable SVG: every word an outline of its glyphs, as drawn."""

        from flexo.portable import portable_svg

        def make() -> str:
            width, height = self.size
            return portable_svg(
                self.drawing, width=f"{number(width)}pt", height=f"{number(height)}pt"
            )

        return self.once("svg", make)  # type: ignore[return-value]

    @property
    def scale(self) -> float:
        """How many times its size its picture is: ``PNG_SCALE``, less for one so large it
        would have more than ``PNG_PIXELS``."""

        width, height = self.size
        largest = (PNG_PIXELS / max(width * height, 1.0)) ** 0.5
        return max(min(PNG_SCALE, largest), 0.01)

    def pixels(self) -> tuple[int, int]:
        """The picture's width and height in pixels."""

        width, height = self.size
        return max(round(width * self.scale), 1), max(round(height * self.scale), 1)

    def png(self) -> bytes:
        """A picture of it, ``scale`` times its size, its resolution written in it."""

        def make() -> bytes:
            import resvg_py

            from flexo.export import _pictures_drawn, _pixels_shown
            from flexo.fonts import font_directories

            dpi = 72.0 * self.scale
            outlined = self.svg()
            fonts = [str(directory) for directory in font_directories()]
            if "data:image/gif" in outlined:
                from flexo.animated import stilled

                outlined = stilled(outlined)  # (a picture does not play: a GIF's first frame)
            if "data:image/svg+xml;base64," in outlined:
                outlined = _pictures_drawn(outlined, dpi, fonts)
            if "<image" in outlined:
                outlined = _pixels_shown(outlined, dpi)
            data = bytes(resvg_py.svg_to_bytes(svg_string=outlined, font_dirs=fonts, dpi=dpi))
            return with_resolution(data, dpi)

        return self.once("png", make)  # type: ignore[return-value]


def with_resolution(png: bytes, dpi: float) -> bytes:
    """``png`` saying it is ``dpi`` pixels to the inch (its ``pHYs``), so an app pastes it at
    its size rather than at a pixel a point."""

    if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        return png
    per_metre = round(dpi / 0.0254)
    body = b"pHYs" + struct.pack(">IIB", per_metre, per_metre, 1)
    chunk = struct.pack(">I", 9) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    # Any it says already, gone: one chunk, after the header.
    rest, at = bytearray(), 33
    while at + 8 <= len(png):
        length = struct.unpack(">I", png[at : at + 4])[0]
        end = at + 12 + length
        if png[at + 4 : at + 8] != b"pHYs":
            rest += png[at:end]
        at = end
    return png[:33] + chunk + bytes(rest)
