"""Illustrator and PDF artwork: a page read back as the drawing it is.

An Illustrator file is a PDF with Illustrator's own data beside it -- unless it was
saved with "Create PDF Compatible File" unticked, when only Illustrator can read it --
and its page is the artboard. This module reads a page's objects through pdfium and
writes each as SVG that flexo draws exactly everywhere: paths as paths, words as the
outlines of their glyphs (a file's fonts are seldom installed where its slides are
shown), pictures as pictures. What that SVG cannot say the way the file does -- a
gradient, an object cut by a curved mask, a group with an opacity or a blend of its
own -- is drawn by pdfium, that object alone, as a picture in its place, so the rest
stays vectors: shapes in the PowerPoint, vectors in the PDF.

The reading is then checked: drawn by resvg, it must match pdfium's drawing of the
page. The parts that differ are drawn as pictures instead, and a page that still
differs is placed as pdfium's picture of it, whole -- exact, if no longer editable.
"""

from __future__ import annotations

import base64
import ctypes
import io
import itertools
import math
import struct
import zlib
from dataclasses import dataclass, field
from functools import lru_cache

type Matrix = tuple[float, float, float, float, float, float]
"""PDF's ``a b c d e f``: a point goes to ``(a x + c y + e, b x + d y + f)``."""

type Box = tuple[float, float, float, float]
"""``left, bottom, right, top`` on the page, in points, y up."""

DENSITY = 4.0
"""Pixels per point for a part drawn as a picture: 288 dpi, sharp at twice the size."""

LARGEST = 16_000_000
"""Pixels in any one picture; a larger one is drawn at a lower density."""

CHECK = 1000
"""Pixels along the page's longer side when its reading is checked against pdfium's."""

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# pdfium's names for what its objects are, and for the pieces of a path.
_TEXT, _PATH, _IMAGE, _SHADING, _FORM = 1, 2, 3, 4, 5
_LINE, _CURVE, _MOVE = 0, 1, 2


class PdfArtError(ValueError):
    """A file that cannot be read as artwork, said in words, with what to do."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True, slots=True)
class PageArt:
    """One page of a PDF (an Illustrator file's artboard) as SVG."""

    markup: str
    """An ``<svg>`` whose units are points, its viewBox the page."""
    width: float
    height: float
    pictured: int = 0
    """How many of its parts are drawn as pictures."""
    whole: bool = False
    """Whether the page is one picture: its vectors could not be read exactly."""


def is_pdf(head: bytes) -> bool:
    """Whether a file beginning ``head`` is a PDF (an Illustrator file saved, as it is by
    default, with its PDF): the header may come anywhere in its first kilobyte."""

    return b"%PDF-" in head[:1024]


def read_page(path: str, page: int = 1, stamp: int = 0, *, art: bool = False) -> PageArt:
    """Page ``page`` (from 1) of the PDF or Illustrator file at ``path``, as SVG -- or
    only its ``art`` box, which Illustrator sets to the art on the artboard.

    ``stamp`` is when the file last changed: a page is read once for each version, and
    kept on disk, so a deck built again does not read it again."""

    import hashlib
    import json
    import os

    named = f"{_VERSION}|{os.path.abspath(path)}|{stamp}|{page}|{art}"
    key = hashlib.sha256(named.encode()).hexdigest()
    kept = _cache_folder() / f"{key[:32]}.json"
    try:
        known = json.loads(kept.read_text(encoding="utf-8"))
        os.utime(kept)  # read now: kept the longest
        return PageArt(
            known["markup"], known["width"], known["height"], known["pictured"], known["whole"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    read = _read(path, page, stamp, art)
    try:
        kept.parent.mkdir(parents=True, exist_ok=True)
        others = sorted(kept.parent.glob("*.json"), key=lambda item: item.stat().st_mtime)
        for old in others[: max(0, len(others) - _KEPT + 1)]:
            old.unlink(missing_ok=True)
        kept.write_text(
            json.dumps({"markup": read.markup, "width": read.width, "height": read.height,
                        "pictured": read.pictured, "whole": read.whole}),
            encoding="utf-8",
        )
    except OSError:
        pass  # a cache that cannot be written is only slower
    return read


_VERSION = 1
"""Changed whenever a page is read differently, so pages read before are read again."""

_KEPT = 48
"""How many read pages are kept on disk; the least recently read go first."""


def _cache_folder():
    import os
    import sys
    from pathlib import Path

    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flexo" / "artwork"


@lru_cache(maxsize=16)
def _read(path: str, page: int, stamp: int, art: bool = False) -> PageArt:
    del stamp  # part of the cache key
    try:
        import PIL  # noqa: F401 -- the reading is checked, and pictures written, with it
        import pypdfium2 as pdfium
    except ImportError:
        raise PdfArtError(
            "Reading an Illustrator or PDF file needs pypdfium2 and Pillow.",
            'pip install "flexo[pdf]"',
        ) from None
    try:
        document = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as error:
        words = str(error).lower()
        if "password" in words:
            raise PdfArtError(
                "The file is locked with a password.",
                "Save a copy without one (in Illustrator: File > Save As, with no security).",
            ) from None
        raise PdfArtError(f"The file is not a PDF pdfium can read ({error}).") from None
    try:
        if not 1 <= page <= len(document):
            raise PdfArtError(
                f"The file has {len(document)} page{'s' if len(document) != 1 else ''}, "
                f"not {page}.",
                "An Illustrator file has a page for each artboard.",
            )
        return _Reader(document, document[page - 1], art=art).read()
    finally:
        document.close()


# -- reading -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Part:
    """One object of the page, in the order it is painted."""

    handle: object
    kind: int
    matrix: Matrix
    """Its own space to the page's."""
    chain: tuple[object, ...]
    """The groups (form objects) it is drawn inside, outermost first."""
    bounds: Box
    """Where it can paint on the page: its bounds, cut to its rectangular clips."""
    curved: bool = False
    """Whether a clip that is not a rectangle cuts it (it is drawn as a picture)."""
    cut: bool = False
    """Whether its rectangular clip cuts it (its outline is cut to ``bounds``)."""
    pictured: bool = False
    blend: str = "normal"
    """How it mixes with what is under it: ``normal``, ``multiply``, ``screen``."""
    opacity: float = 1.0
    """The opacity of the group it is drawn in, when it is that group's only part."""
    markup: str = ""
    stroke: float = 0.0
    """The width of its line on the page, if it has one (points)."""


@dataclass(slots=True)
class _Reader:
    document: object
    page: object
    parts: list[_Part] = field(default_factory=list)
    everything: list[object] = field(default_factory=list)
    """Every object at every depth, to switch off while one is drawn alone."""
    glyphs: dict[tuple[int, int], list] = field(default_factory=dict)
    words: dict[int, list] = field(default_factory=dict)
    art: bool = False
    """Whether to show only the page's art box: an Illustrator file's art, without the
    rest of its artboard."""
    box: Box = (0.0, 0.0, 0.0, 0.0)
    """What is shown of the page."""
    crop: Box = (0.0, 0.0, 0.0, 0.0)
    """The page's crop box: what pdfium draws, its top left pdfium's origin."""

    def read(self) -> PageArt:
        import pypdfium2.raw as pdfium

        self.crop = self.box = tuple(self.page.get_cropbox())  # type: ignore[assignment]
        if self.art:
            art = _intersection(self.crop, tuple(self.page.get_artbox()))  # type: ignore[arg-type]
            if art[2] - art[0] > 1.0 and art[3] - art[1] > 1.0:
                self.box = art
        left, bottom, right, top = self.box
        width, height = right - left, top - bottom
        if self.page.get_rotation() % 360:
            # A turned page is rare from Illustrator; pdfium draws it upright, whole.
            return self._whole(width, height, pictured=0)
        self._text()
        for index in range(pdfium.FPDFPage_CountObjects(self.page.raw)):
            self._walk(pdfium.FPDFPage_GetObject(self.page.raw, index), _IDENTITY, [], ())
        self._hidden_layers()
        for part in self.parts:
            part.markup = self._vector(part) if not part.pictured else ""
        for part in self.parts:
            if part.pictured:
                part.markup = self._picture(part)
        for _ in range(3):
            wrong = self._differs()
            if wrong is None:
                return PageArt(self._svg(), width, height, sum(p.pictured for p in self.parts))
            # A part read as nothing is a suspect too: pdfium may draw it.
            suspects = [
                part for part in self.parts
                if not part.pictured and _overlaps(part.bounds, wrong)
            ]
            if not suspects:
                break
            for part in suspects:
                part.pictured = True
                part.markup = self._picture(part)
        return self._whole(width, height, pictured=len(self.parts))

    # -- the objects ---------------------------------------------------------------------

    def _walk(
        self, handle, outer: Matrix, clips: list[list], chain: tuple, opacity: float = 1.0,
        blend: str = "normal",
    ) -> None:
        import pypdfium2.raw as pdfium

        self.everything.append(handle)
        kind = pdfium.FPDFPageObj_GetType(handle)
        own = _object_matrix(handle)
        clips = [*clips, *(_moved(path, outer) for path in _clip_paths(handle))]
        if kind == _FORM:
            inner = _then(own, outer)
            count = pdfium.FPDFFormObj_CountObjects(handle)
            children = [pdfium.FPDFFormObj_GetObject(handle, index) for index in range(count)]
            if pdfium.FPDFPageObj_HasTransparency(handle):
                # A group with an opacity or a blend of its own (or only marked as one, as
                # Illustrator marks many): drawn part by part when that looks the same.
                alpha = (_colour(handle, stroke=False) or (0, 0, 0, 255))[3] / 255
                mixed = self._blend(handle, chain)
                single = (
                    len(children) == 1
                    and pdfium.FPDFPageObj_GetType(children[0]) in {_PATH, _TEXT}
                )
                # One shape takes its group's opacity and blend as its own; a group of
                # several is drawn whole, unless it has neither.
                carried = single and mixed in {"normal", "multiply"}
                if not carried and (mixed != "normal" or alpha < 1.0):
                    blend = mixed or "normal"
                    self._add(handle, kind, inner, clips, chain, pictured=True, blend=blend)
                    return
                opacity *= alpha
                blend = mixed or blend
            for child in children:
                self._walk(child, inner, clips, (*chain, handle), opacity, blend)
            return
        matrix = _then(own, outer) if kind != _SHADING else outer
        pictured = kind in {_IMAGE, _SHADING}
        if kind in {_PATH, _TEXT} and pdfium.FPDFPageObj_HasTransparency(handle):
            fill, stroke = _colour(handle, stroke=False), _colour(handle, stroke=True)
            if all(colour[3] >= 255 for colour in (fill, stroke) if colour):
                # Transparency its colours do not carry: a blend, or a soft mask.
                blend = self._blend(handle, chain) or "mask"
                pictured = blend not in {"normal", "multiply"} or blend == "normal"
        if kind == _TEXT and pdfium.FPDFTextObj_GetTextRenderMode(handle) not in {0, 3, 4, 7}:
            pictured = True  # outlined words
        self._add(
            handle, kind, matrix, clips, chain, pictured=pictured, blend=blend, opacity=opacity
        )

    def _add(self, handle, kind, matrix, clips, chain, *, pictured: bool, blend: str = "normal",
             opacity: float = 1.0) -> None:
        bounds = _page_bounds(handle, chain, self)
        region = self.box
        curved = []
        for path in clips:
            rectangle = _rectangle(path)
            if rectangle is not None:
                region = _intersection(region, rectangle)
            else:
                curved.append(path)
        visible = _intersection(bounds, region)
        if visible[0] >= visible[2] or visible[1] >= visible[3]:
            return  # wholly clipped away
        part = _Part(
            handle, kind, matrix, chain, visible, pictured=pictured, blend=blend, opacity=opacity
        )
        part.cut = not _within(bounds, region)
        part.curved = any(not _inside(bounds, path) for path in curved)
        part.pictured = part.pictured or part.curved
        self.parts.append(part)

    def _hidden_layers(self) -> None:
        """Leave out the parts on layers that are hidden. Illustrator writes its layers as
        optional content; pdfium draws a hidden one's parts not at all, but lists them, and
        does not say which layers are hidden -- so each layer is drawn alone, and one that
        draws nothing is gone."""

        import pypdfium2.raw as pdfium

        layers: dict[str, list[_Part]] = {}
        for part in self.parts:
            holders = (part.handle, *reversed(part.chain))
            name = next((found for item in holders if (found := _layer(item))), None)
            if name is not None:
                layers.setdefault(name, []).append(part)
        if len(layers) < 2:
            return  # one layer, and something on the page: it is shown
        hidden: set[int] = set()
        for parts in layers.values():
            # Its shapes and words show whether it is shown, and are quick to draw; its
            # photographs only if it has nothing else.
            drawn_parts = [part for part in parts if part.kind in {_PATH, _TEXT}] or parts
            for item in self.everything:
                pdfium.FPDFPageObj_SetIsActive(item, False)
            for part in drawn_parts:
                for item in (*part.chain, part.handle):
                    pdfium.FPDFPageObj_SetIsActive(item, True)
            try:
                drawn = self._render(self.box, 0.25, background=(0, 0, 0, 0))
            finally:
                for item in self.everything:
                    pdfium.FPDFPageObj_SetIsActive(item, True)
            if drawn is not None and not any(drawn[0][3::4]):
                hidden.update(id(part) for part in parts)
        self.parts = [part for part in self.parts if id(part) not in hidden]

    def _blend(self, handle, chain: tuple) -> str | None:
        """How an object with transparency of its own mixes with what is under it:
        ``normal``, ``multiply`` or ``screen`` -- or None when it is none of those (a soft
        mask, another blend). pdfium does not say, so it is drawn alone, small, three
        times -- over nothing, over black, over white -- and the three compared."""

        bounds = _page_bounds(handle, chain, self)
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            return "normal"
        scale = min(4.0, 48.0 / max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-6))
        with self._alone(handle, chain):
            drawn = [self._render(bounds, scale, background=ground)
                     for ground in ((0, 0, 0, 0), (0, 0, 0, 255), (255, 255, 255, 255))]
        if any(item is None for item in drawn):
            return None
        alone, dark, light = (item[0] for item in drawn)  # type: ignore[index]
        votes = {"normal": 0, "multiply": 0, "screen": 0}
        covered = 0
        for at in range(0, len(alone), 4):
            alpha = alone[at + 3] / 255
            if alpha < 0.5:
                continue  # an edge, or nothing
            covered += 1
            colour = alone[at : at + 3]
            over_black = [c * alpha for c in colour]
            over_white = [c * alpha + 255 * (1 - alpha) for c in colour]
            seen_dark, seen_light = dark[at : at + 3], light[at : at + 3]
            expected = {
                "normal": (over_black, over_white),
                "multiply": ([0, 0, 0], over_white),
                "screen": (over_black, [255, 255, 255]),
            }
            for name, (low, high) in expected.items():
                pairs = zip((*low, *high), (*seen_dark, *seen_light), strict=True)
                if max(abs(a - b) for a, b in pairs) <= 12:
                    votes[name] += 1
        if not covered:
            return "normal"
        best = max(votes, key=votes.__getitem__)
        return best if votes[best] >= covered * 0.9 else None

    def _alone(self, handle, chain: tuple):
        """While in this context, pdfium draws ``handle`` (inside its groups) and nothing else."""

        import contextlib

        import pypdfium2.raw as pdfium

        @contextlib.contextmanager
        def only():
            switched = []
            top = [
                pdfium.FPDFPage_GetObject(self.page.raw, index)
                for index in range(pdfium.FPDFPage_CountObjects(self.page.raw))
            ]
            path = [*chain, handle]
            for item in top:
                if _address(item) != _address(path[0]):
                    pdfium.FPDFPageObj_SetIsActive(item, False)
                    switched.append(item)
            for group, inside in itertools.pairwise(path):
                for index in range(pdfium.FPDFFormObj_CountObjects(group)):
                    child = pdfium.FPDFFormObj_GetObject(group, index)
                    if _address(child) != _address(inside):
                        pdfium.FPDFPageObj_SetIsActive(child, False)
                        switched.append(child)
            try:
                yield
            finally:
                for item in switched:
                    pdfium.FPDFPageObj_SetIsActive(item, True)

        return only()

    # -- vectors -------------------------------------------------------------------------

    def _vector(self, part: _Part) -> str:
        if part.kind == _PATH:
            return self._path(part)
        if part.kind == _TEXT:
            return self._words(part)
        return ""

    def _path(self, part: _Part) -> str:
        import pypdfium2.raw as pdfium

        handle = part.handle
        mode, stroked = ctypes.c_int(), ctypes.c_int()
        pdfium.FPDFPath_GetDrawMode(handle, mode, stroked)
        if not mode.value and not stroked.value:
            return ""
        segments = _moved(_path_segments(handle), part.matrix)
        attributes = []
        if mode.value:
            red, green, blue, alpha = _colour(handle, stroke=False) or (0, 0, 0, 255)
            attributes.append(f'fill="{_hex(red, green, blue)}"')
            if alpha < 255 or part.opacity < 1.0:
                attributes.append(f'fill-opacity="{_n(alpha / 255 * part.opacity)}"')
            if mode.value == 1:
                attributes.append('fill-rule="evenodd"')
        else:
            attributes.append('fill="none"')
        if stroked.value:
            red, green, blue, alpha = _colour(handle, stroke=True) or (0, 0, 0, 255)
            width = ctypes.c_float()
            pdfium.FPDFPageObj_GetStrokeWidth(handle, width)
            scale = _scale(part.matrix)
            # PDF's zero width is the thinnest line the device can show.
            drawn = width.value * scale if width.value > 0 else 0.25
            part.stroke = drawn
            attributes += [f'stroke="{_hex(red, green, blue)}"', f'stroke-width="{_n(drawn)}"']
            if alpha < 255 or part.opacity < 1.0:
                attributes.append(f'stroke-opacity="{_n(alpha / 255 * part.opacity)}"')
            cap = ("butt", "round", "square")[pdfium.FPDFPageObj_GetLineCap(handle) % 3]
            join = ("miter", "round", "bevel")[pdfium.FPDFPageObj_GetLineJoin(handle) % 3]
            if cap != "butt":
                attributes.append(f'stroke-linecap="{cap}"')
            if join != "miter":
                attributes.append(f'stroke-linejoin="{join}"')
            else:
                attributes.append('stroke-miterlimit="10"')  # PDF's own default
            dashes = _dashes(handle)
            if dashes and any(value > 0 for value in dashes[0]):
                attributes.append(
                    f'stroke-dasharray="{" ".join(_n(value * scale) for value in dashes[0])}"'
                )
                if dashes[1]:
                    attributes.append(f'stroke-dashoffset="{_n(dashes[1] * scale)}"')
        return self._shape(part, segments, " ".join(attributes))

    def _words(self, part: _Part) -> str:
        """A text object as the outlines of its glyphs, placed as the text page places them."""

        import pypdfium2.raw as pdfium

        if pdfium.FPDFTextObj_GetTextRenderMode(part.handle) in {3, 7}:
            return ""  # invisible words: a scan's hidden text, a clip
        characters = self.words.get(_address(part.handle))
        if not characters:
            return ""
        font = pdfium.FPDFTextObj_GetFont(part.handle)
        size = ctypes.c_float(1.0)
        pdfium.FPDFTextObj_GetFontSize(part.handle, size)
        segments: list = []
        for code, origin, linear in characters:
            outline = self._glyph(font, code)
            if outline is None:
                if chr(code).isspace():
                    continue  # a space has no outline to give
                part.pictured = True  # a glyph pdfium cannot give as an outline
                return ""
            # A glyph is drawn at the font's size, by the matrix of its words.
            matrix = (*(value * size.value for value in linear), *origin)
            segments.extend(_moved(outline, matrix))
        if not segments:
            return ""
        red, green, blue, alpha = _colour(part.handle, stroke=False) or (0, 0, 0, 255)
        attributes = f'fill="{_hex(red, green, blue)}"'
        if alpha < 255 or part.opacity < 1.0:
            attributes += f' fill-opacity="{_n(alpha / 255 * part.opacity)}"'
        return self._shape(part, segments, attributes)

    def _glyph(self, font, code: int) -> list | None:
        import pypdfium2.raw as pdfium

        key = (_address(font), code)
        if key not in self.glyphs:
            path = pdfium.FPDFFont_GetGlyphPath(font, code, 1.0)
            if not path:
                self.glyphs[key] = None  # type: ignore[assignment]
            else:
                count = pdfium.FPDFGlyphPath_CountGlyphSegments(path)
                self.glyphs[key] = _segments(
                    pdfium.FPDFGlyphPath_GetGlyphPathSegment(path, index) for index in range(count)
                )
        return self.glyphs[key]

    def _text(self) -> None:
        """Each text object's characters: what each is, where its origin is on the page,
        and the matrix its glyph is drawn with -- as pdfium's text page reads them."""

        import pypdfium2.raw as pdfium

        page = pdfium.FPDFText_LoadPage(self.page.raw)
        if not page:
            return
        try:
            x, y = ctypes.c_double(), ctypes.c_double()
            matrix = pdfium.FS_MATRIX()
            for index in range(pdfium.FPDFText_CountChars(page)):
                if pdfium.FPDFText_IsGenerated(page, index) == 1:
                    continue  # a space or a line's end the reader supposed
                owner = pdfium.FPDFText_GetTextObject(page, index)
                if not owner:
                    continue
                code = pdfium.FPDFText_GetUnicode(page, index)
                pdfium.FPDFText_GetCharOrigin(page, index, x, y)
                pdfium.FPDFText_GetMatrix(page, index, matrix)
                linear = (matrix.a, matrix.b, matrix.c, matrix.d)
                found = (code, (x.value, y.value), linear)
                self.words.setdefault(_address(owner), []).append(found)
        finally:
            pdfium.FPDFText_ClosePage(page)

    def _shape(self, part: _Part, segments: list, attributes: str) -> str:
        if part.blend != "normal":
            attributes += f' style="mix-blend-mode:{part.blend}"'
        if part.cut:
            # flexo's drawing cuts straight-sided outlines to a clip exactly; curves it
            # keeps whole. So a cut outline is given in short straight pieces.
            segments = _flattened(segments)
        data = _data(segments, self.box)
        if not data:
            return ""
        shape = f'<path d="{data}" {attributes}/>'
        if part.cut:
            left, top = part.bounds[0] - self.box[0], self.box[3] - part.bounds[3]
            width, height = part.bounds[2] - part.bounds[0], part.bounds[3] - part.bounds[1]
            shape = (
                f'<g clip-path="url(#clip{id(part)})"><clipPath id="clip{id(part)}">'
                f'<rect x="{_n(left)}" y="{_n(top)}" width="{_n(width)}" height="{_n(height)}"/>'
                f"</clipPath>{shape}</g>"
            )
        return shape

    # -- pictures ------------------------------------------------------------------------

    def _picture(self, part: _Part) -> str:
        """``part`` drawn alone by pdfium -- with its clip, mask and opacity -- as a picture
        over the part of the page it covers."""

        import pypdfium2.raw as pdfium

        density = DENSITY
        if part.kind == _IMAGE:
            across, down = ctypes.c_uint(), ctypes.c_uint()
            pdfium.FPDFImageObj_GetImagePixelSize(part.handle, across, down)
            span = max(math.hypot(part.matrix[0], part.matrix[1]), 1e-6)
            density = min(DENSITY, max(1.0, across.value / span))
        for item in self.everything:
            pdfium.FPDFPageObj_SetIsActive(item, False)
        for item in (*part.chain, part.handle):
            pdfium.FPDFPageObj_SetIsActive(item, True)
        try:
            drawn = self._render(part.bounds, density, background=(0, 0, 0, 0))
        finally:
            for item in self.everything:
                pdfium.FPDFPageObj_SetIsActive(item, True)
        if drawn is None:
            return ""
        pixels, width, height, left, top, scale = drawn
        trimmed = _trimmed(pixels, width, height)
        if trimmed is None:
            return ""
        pixels, (x0, y0, x1, y1) = trimmed
        href = _encoded(pixels, x1 - x0, y1 - y0)
        blend = ""
        if part.blend in {"multiply", "screen"}:
            blend = f' style="mix-blend-mode:{part.blend}"'
        return (
            f'<image x="{_n(left + x0 / scale)}" y="{_n(top + y0 / scale)}" '
            f'width="{_n((x1 - x0) / scale)}" height="{_n((y1 - y0) / scale)}"{blend} '
            f'href="{href}"/>'
        )

    def _render(self, bounds: Box, density: float, *, background: tuple[int, int, int, int]):
        """The page's active objects within ``bounds`` (page points), at ``density``
        pixels a point: RGBA bytes, the pixel size, and where its top left is in the SVG."""

        import pypdfium2.raw as pdfium

        left, bottom, right, top = bounds
        density = min(density, math.sqrt(LARGEST / max((right - left) * (top - bottom), 1e-6)))
        # (Less a hair, so a page scaled to a whole number of pixels is not one over.)
        width = max(1, math.ceil((right - left) * density - 1e-6))
        height = max(1, math.ceil((top - bottom) * density - 1e-6))
        # From the page as pdfium shows it (points, y down from its top left) to pixels.
        matrix = pdfium.FS_MATRIX(
            density, 0.0, 0.0, density,
            -density * (left - self.crop[0]), -density * (self.crop[3] - top),
        )
        clip = pdfium.FS_RECTF(0.0, 0.0, float(width), float(height))
        bitmap = pdfium.FPDFBitmap_Create(width, height, 1)
        if not bitmap:
            return None
        try:
            red, green, blue, alpha = background
            pdfium.FPDFBitmap_FillRect(
                bitmap, 0, 0, width, height, (alpha << 24) | (red << 16) | (green << 8) | blue
            )
            pdfium.FPDF_RenderPageBitmapWithMatrix(
                bitmap, self.page.raw, matrix, clip, pdfium.FPDF_REVERSE_BYTE_ORDER
            )
            stride = pdfium.FPDFBitmap_GetStride(bitmap)
            raw = ctypes.string_at(pdfium.FPDFBitmap_GetBuffer(bitmap), stride * height)
        finally:
            pdfium.FPDFBitmap_Destroy(bitmap)
        rows = b"".join(raw[row * stride : row * stride + width * 4] for row in range(height))
        return rows, width, height, left - self.box[0], self.box[3] - top, density

    def _whole(self, width: float, height: float, *, pictured: int) -> PageArt:
        drawn = self._render(self.box, DENSITY, background=(0, 0, 0, 0))
        image = ""
        if drawn is not None:
            pixels, across, down, _, _, scale = drawn
            image = (
                f'<image x="0" y="0" width="{_n(across / scale)}" height="{_n(down / scale)}" '
                f'href="{_encoded(pixels, across, down)}"/>'
            )
        markup = _wrapped(image, (0.0, 0.0, width, height))
        return PageArt(markup, width, height, pictured, whole=True)

    # -- the whole -----------------------------------------------------------------------

    def _svg(self, *, vectors: bool = False, view: tuple[float, ...] | None = None) -> str:
        """The page as SVG -- or only its vectors, or only a ``view`` of it (x, y, width,
        height in the SVG's units), to be checked."""

        width, height = self.box[2] - self.box[0], self.box[3] - self.box[1]
        x, y, width, height = view or (0.0, 0.0, width, height)
        body = "".join(part.markup for part in self.parts if not (vectors and part.pictured))
        return _wrapped(body, (x, y, width, height))

    def _differs(self) -> list[Box] | None:
        """Where the vectors read, drawn by resvg, differ from pdfium's drawing of the same
        parts (boxes on the page), or None when they agree. The parts drawn as pictures are
        pdfium's own drawing of them, so they are left out of both."""

        import pypdfium2.raw as pdfium
        import resvg_py

        vectors = [part for part in self.parts if not part.pictured]
        if not vectors:
            return None
        region = (
            max(self.box[0], min(part.bounds[0] for part in vectors) - 2.0),
            max(self.box[1], min(part.bounds[1] for part in vectors) - 2.0),
            min(self.box[2], max(part.bounds[2] for part in vectors) + 2.0),
            min(self.box[3], max(part.bounds[3] for part in vectors) + 2.0),
        )
        width, height = region[2] - region[0], region[3] - region[1]
        if width <= 0 or height <= 0:
            return None
        # Fine enough that the thinnest line is two pixels wide: thinner, two renderers
        # draw a line's faint coverage each their own way.
        thinnest = min((part.stroke for part in vectors if part.stroke), default=1.0)
        density = min(max(CHECK / max(width, height), 2.0 / thinnest), 8.0)
        density = min(density, math.sqrt(LARGEST / (width * height)))
        # A whole number of pixels each way, so both drawings fall on one grid.
        across, down = math.ceil(width * density), math.ceil(height * density)
        region = (region[0], region[3] - down / density, region[0] + across / density, region[3])
        pictured = [part.handle for part in self.parts if part.pictured]
        for handle in pictured:
            pdfium.FPDFPageObj_SetIsActive(handle, False)
        try:
            theirs = self._render(region, density, background=(0, 0, 0, 0))
        finally:
            for handle in pictured:
                pdfium.FPDFPageObj_SetIsActive(handle, True)
        if theirs is None:
            return None
        view = (region[0] - self.box[0], self.box[3] - region[3], across / density, down / density)
        ours = bytes(resvg_py.svg_to_bytes(svg_string=self._svg(vectors=True, view=view),
                                           width=theirs[1], dpi=72, skip_system_fonts=True))
        # A part may sit a little over -- pdfium snaps thin lines and glyphs to its
        # pixels -- and half a point is not a difference that is seen.
        reach = max(1, round(density / 2.0))
        cells = _wrong_cells(ours, theirs[0], theirs[1], theirs[2], reach)
        if not cells:
            return None
        cell = _CELL / density
        return [
            (
                region[0] + column * cell, region[3] - (row + 1) * cell,
                region[0] + (column + 1) * cell, region[3] - row * cell,
            )
            for row, column in cells
        ]


# -- geometry ------------------------------------------------------------------------------


def _then(first: Matrix, second: Matrix) -> Matrix:
    """``first``, then ``second``."""

    a, b, c, d, e, f = first
    A, B, C, D, E, F = second
    return (
        a * A + b * C, a * B + b * D,
        c * A + d * C, c * B + d * D,
        e * A + f * C + E, e * B + f * D + F,
    )


def _apply(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _scale(matrix: Matrix) -> float:
    return math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))


def _moved(segments: list, matrix: Matrix) -> list:
    return [(kind, tuple(_apply(matrix, *point) for point in points)) for kind, points in segments]


def _segments(pieces) -> list:
    """pdfium's path pieces as ``(kind, points)``: ``M``, ``L``, ``C`` (three points), ``Z``."""

    import pypdfium2.raw as pdfium

    result: list = []
    controls: list = []
    x, y = ctypes.c_float(), ctypes.c_float()
    for piece in pieces:
        pdfium.FPDFPathSegment_GetPoint(piece, x, y)
        point = (x.value, y.value)
        kind = pdfium.FPDFPathSegment_GetType(piece)
        if kind == _CURVE:
            controls.append(point)
            if len(controls) == 3:
                result.append(("C", tuple(controls)))
                controls = []
        elif kind == _MOVE:
            result.append(("M", (point,)))
        else:
            result.append(("L", (point,)))
        if pdfium.FPDFPathSegment_GetClose(piece):
            result.append(("Z", ()))
    return result


def _path_segments(handle) -> list:
    import pypdfium2.raw as pdfium

    count = pdfium.FPDFPath_CountSegments(handle)
    return _segments(pdfium.FPDFPath_GetPathSegment(handle, index) for index in range(count))


def _clip_paths(handle) -> list[list]:
    """The paths an object is clipped to, in the space of the group it is drawn in."""

    import pypdfium2.raw as pdfium

    clip = pdfium.FPDFPageObj_GetClipPath(handle)
    if not clip:
        return []
    paths = []
    for index in range(pdfium.FPDFClipPath_CountPaths(clip)):
        count = pdfium.FPDFClipPath_CountPathSegments(clip, index)
        pieces = (pdfium.FPDFClipPath_GetPathSegment(clip, index, piece) for piece in range(count))
        paths.append(_segments(pieces))
    return paths


def _object_matrix(handle) -> Matrix:
    import pypdfium2.raw as pdfium

    matrix = pdfium.FS_MATRIX()
    if not pdfium.FPDFPageObj_GetMatrix(handle, matrix):
        return _IDENTITY
    return (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)


def _page_bounds(handle, chain: tuple, reader: _Reader) -> Box:
    """An object's bounds on the page (pdfium gives them in its group's space)."""

    import pypdfium2.raw as pdfium

    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    if not pdfium.FPDFPageObj_GetBounds(handle, left, bottom, right, top):
        return (0.0, 0.0, 0.0, 0.0)
    matrix = _IDENTITY
    for group in reversed(chain):
        matrix = _then(matrix, _object_matrix(group))
    corners = [
        _apply(matrix, x, y)
        for x in (left.value, right.value)
        for y in (bottom.value, top.value)
    ]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _rectangle(path: list) -> Box | None:
    """The box a clip path is, when it is one upright rectangle."""

    points = [point for kind, points in path if kind != "Z" for point in points]
    if any(kind == "C" for kind, _ in path) or not 4 <= len(points) <= 5:
        return None
    if sum(1 for kind, _ in path if kind == "M") != 1:
        return None
    xs = sorted({round(x, 3) for x, _ in points})
    ys = sorted({round(y, 3) for _, y in points})
    if len(xs) != 2 or len(ys) != 2:
        return None
    return (xs[0], ys[0], xs[1], ys[1])


def _intersection(first: Box, second: Box) -> Box:
    return (max(first[0], second[0]), max(first[1], second[1]),
            min(first[2], second[2]), min(first[3], second[3]))


def _within(inner: Box, outer: Box) -> bool:
    slack = 1e-3
    return (inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack
            and inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack)


def _overlaps(box: Box, boxes: list[Box]) -> bool:
    return any(
        box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]
        for other in boxes
    )


def _flattened(segments: list, tolerance: float = 0.05) -> list:
    """``segments`` with each curve as short straight pieces, none farther than
    ``tolerance`` points from the curve."""

    result: list = []
    current = (0.0, 0.0)
    start = current
    for kind, points in segments:
        if kind == "C":
            p1, p2, p3 = points
            span = (math.dist(current, p1) + math.dist(p1, p2) + math.dist(p2, p3))
            steps = max(2, min(64, math.ceil(math.sqrt(span / tolerance))))
            for step in range(1, steps + 1):
                t = step / steps
                u = 1.0 - t
                weights = (u**3, 3 * u * u * t, 3 * u * t * t, t**3)
                points4 = (current, p1, p2, p3)
                result.append(("L", ((
                    sum(w * p[0] for w, p in zip(weights, points4, strict=True)),
                    sum(w * p[1] for w, p in zip(weights, points4, strict=True)),
                ),)))
            current = p3
        else:
            result.append((kind, points))
            if kind == "M":
                current = start = points[0]
            elif kind == "L":
                current = points[0]
            else:
                current = start
    return result


def _inside(box: Box, path: list) -> bool:
    """Whether ``box`` lies wholly inside a clip ``path``: its corners inside, and no edge
    of the path crossing into it."""

    polygon = [points[-1] for kind, points in _flattened(path, 0.2) if kind != "Z"]
    if len(polygon) < 3:
        return False
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    if not all(_point_in(polygon, corner) for corner in corners):
        return False
    return not any(box[0] < x < box[2] and box[1] < y < box[3] for x, y in polygon)


def _point_in(polygon: list, point: tuple[float, float]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _data(segments: list, box: Box) -> str:
    """SVG path data for page ``segments``: y turned to run down from the page's top."""

    left, top = box[0], box[3]
    pieces = []
    for kind, points in segments:
        pieces.append(kind + " ".join(f"{_n(x - left)} {_n(top - y)}" for x, y in points))
    data = "".join(pieces)
    return data if any(kind in {"L", "C"} for kind, _ in segments) else ""


# -- paint -------------------------------------------------------------------------------


def _colour(handle, *, stroke: bool) -> tuple[int, int, int, int] | None:
    import pypdfium2.raw as pdfium

    red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
    read = pdfium.FPDFPageObj_GetStrokeColor if stroke else pdfium.FPDFPageObj_GetFillColor
    if not read(handle, red, green, blue, alpha):
        return None
    return red.value, green.value, blue.value, alpha.value


def _dashes(handle) -> tuple[list[float], float] | None:
    import pypdfium2.raw as pdfium

    count = pdfium.FPDFPageObj_GetDashCount(handle)
    if count <= 0:
        return None
    values = (ctypes.c_float * count)()
    if not pdfium.FPDFPageObj_GetDashArray(handle, values, count):
        return None
    phase = ctypes.c_float()
    pdfium.FPDFPageObj_GetDashPhase(handle, phase)
    return list(values), phase.value


def _layer(handle) -> str | None:
    """The name of the layer (optional content) an object is on, if it is on one."""

    import pypdfium2.raw as pdfium

    for index in range(pdfium.FPDFPageObj_CountMarks(handle)):
        mark = pdfium.FPDFPageObj_GetMark(handle, index)
        size = ctypes.c_ulong()
        if not pdfium.FPDFPageObjMark_GetName(mark, None, 0, size) or size.value < 2:
            continue
        name = (ctypes.c_ushort * (size.value // 2 + 1))()
        pdfium.FPDFPageObjMark_GetName(mark, name, size.value, size)
        if bytes(name)[: size.value - 2].decode("utf-16-le", "replace") != "OC":
            continue
        length = ctypes.c_ulong()
        if not pdfium.FPDFPageObjMark_GetParamStringValue(mark, b"Name", None, 0, length):
            return "layer"  # on a layer that has no name
        value = (ctypes.c_ushort * (length.value // 2 + 1))()
        pdfium.FPDFPageObjMark_GetParamStringValue(mark, b"Name", value, length.value, length)
        return bytes(value)[: max(0, length.value - 2)].decode("utf-16-le", "replace") or "layer"
    return None


def _address(handle) -> int:
    return ctypes.cast(handle, ctypes.c_void_p).value or 0


def _wrapped(body: str, view: tuple[float, float, float, float]) -> str:
    x, y, width, height = view
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(width)}pt" '
        f'height="{_n(height)}pt" viewBox="{_n(x)} {_n(y)} {_n(width)} {_n(height)}">{body}</svg>'
    )


def _hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


def _n(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


# -- pixels --------------------------------------------------------------------------------

_CELL = 8
"""The side, in pixels, of the squares a page is compared in."""


def _wrong_cells(
    ours: bytes, theirs: bytes, across: int, down: int, reach: int
) -> list[tuple[int, int]]:
    """The cells (row, column) where two drawings of a page differ by more than two
    renderers can -- a glyph hinted another way, a line snapped to the pixels: ink in
    one with none of its colour within ``reach`` pixels in the other. That is a part
    missing or moved, or another colour. ``ours`` is a PNG, ``theirs`` RGBA pixels."""

    from PIL import Image, ImageChops, ImageFilter

    white = Image.new("RGBA", (across, down), (255, 255, 255, 255))

    def flat(image: Image.Image) -> Image.Image:
        image = image.convert("RGBA")
        if image.size != (across, down):  # resvg rounds the height its own way: a row
            image = image.crop((0, 0, across, down))
        return Image.alpha_composite(white, image).convert("RGB")

    with Image.open(io.BytesIO(ours)) as drawn:
        mine = flat(drawn)
    reference = flat(Image.frombytes("RGBA", (across, down), theirs))
    near = ImageFilter.MinFilter(2 * reach + 1)  # the darkest ink nearby, each channel
    missing = ImageChops.subtract(mine.filter(near), reference)
    extra = ImageChops.subtract(reference.filter(near), mine)
    red, green, blue = ImageChops.lighter(missing, extra).split()
    difference = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    difference = difference.filter(ImageFilter.BoxBlur(1))
    wrong = difference.point(lambda value: 255 if value > 56 else 0)
    small = wrong.reduce(_CELL)  # each cell's share of differing pixels, 0 to 255
    shares = enumerate(_values(small))
    return [divmod(index, small.width) for index, share in shares if share > 255 // 12]


def _trimmed(pixels: bytes, width: int, height: int):
    """The pixels cut to the box of those not wholly transparent, and that box."""

    alphas = pixels[3::4]
    rows = [row for row in range(height) if any(alphas[row * width : (row + 1) * width])]
    if not rows:
        return None
    top, bottom = rows[0], rows[-1] + 1
    columns = [
        column for column in range(width)
        if any(alphas[row * width + column] for row in range(top, bottom))
    ]
    left, right = columns[0], columns[-1] + 1
    if (left, top, right, bottom) == (0, 0, width, height):
        return pixels, (0, 0, width, height)
    cut = b"".join(
        pixels[(row * width + left) * 4 : (row * width + right) * 4] for row in range(top, bottom)
    )
    return cut, (left, top, right, bottom)


def _encoded(pixels: bytes, width: int, height: int) -> str:
    """A ``data:`` URI for RGBA ``pixels``: a JPEG for an opaque photograph (when Pillow is
    there to write one), a PNG otherwise."""

    opaque = all(alpha == 255 for alpha in pixels[3::4])
    try:
        from PIL import Image
    except ImportError:
        encoded = base64.b64encode(_png(pixels, width, height)).decode("ascii")
        return "data:image/png;base64," + encoded
    image = Image.frombytes("RGBA", (width, height), pixels)
    buffer = io.BytesIO()
    if opaque and _photographic(image):
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    (image.convert("RGB") if opaque else image).save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _photographic(image) -> bool:
    small = image.convert("RGB").resize((64, 64))
    return len(set(_values(small))) > 512


def _values(image) -> list:
    """An image's pixels, in order (Pillow renamed the call that gives them)."""

    flattened = getattr(image, "get_flattened_data", None)
    return list(flattened() if flattened else image.getdata())


def _png(pixels: bytes, width: int, height: int) -> bytes:
    """RGBA ``pixels`` as a PNG, without Pillow."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        check = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + check

    stride = width * 4
    raw = b"".join(b"\x00" + pixels[row * stride : (row + 1) * stride] for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
