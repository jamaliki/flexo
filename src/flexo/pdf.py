"""PDF, written natively from ``flexo.drawing``: vectors, real text, embedded fonts.

Every shape becomes PDF path operators with its paint, dashes, and opacity; an
arrowhead is drawn from its exact outline. Words stay text -- selectable,
searchable, copyable -- set glyph by glyph where Flexo's shaping put them, in
fonts embedded as subsets. Each subset is a small TrueType font built from the
outlines HarfBuzz draws for exactly the glyphs used, at the weight used, so a
variable font, a CFF (``.otf``) font, and a TrueType font are embedded the same
way, as the Type 0 / CIDFontType2 fonts every PDF reader and every journal
checker accepts (no Type 3 fonts). Pictures are embedded as images; nested SVG
artwork is rasterised at print resolution.

``pdf_bytes(pages)`` takes several drawings and writes one page each, sharing
fonts between them: a slide deck is one call.

A formula Flexo draws (``flexo.texmath``) is outlines, as a typesetter's are; the words it
reads as lie under it as invisible text, so it is found, copied and read like any other.
Given ``tags`` (a ``Tagger``), the PDF is tagged: a structure of headings, paragraphs,
lists, tables, figures and formulas, each figure with its description, that a screen
reader reads in order and a checker finds the words of, all else marked as decoration.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import math
import re
import struct
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path

from flexo.colour import to_rgb
from flexo.drawing import Drawing, Group, Image, Paint, Run, Segment, Shape, Text, read_drawing
from flexo.fonts import FontFace, hb_font, load_face
from flexo.outline import _outline, shape, underline
from flexo.portable import SYNTHETIC_SLANT, run_outline

ARTWORK_DPI = 300.0
"""The resolution nested SVG artwork is rasterised at."""

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
_NAMED = {"black": "#000000", "white": "#ffffff", "transparent": None, "none": None}
_OPERATORS = {"M": "m", "L": "l", "C": "c"}
_CAPS = {"butt": 0, "round": 1, "square": 2}
_JOINS = {"miter": 0, "round": 1, "bevel": 2}
_WORD_BREAKS = frozenset("-\u2010/_")
"""What a word too long for its line is broken after: no space follows it there."""


def _beside(run: Run, script: Run) -> bool:
    """Whether ``run`` is set on the same side of the line as ``script``: one script with it."""

    return run.face is not None and bool(run.text.strip()) and run.shift * script.shift > 0


type Pages = str | Drawing | Sequence[str | Drawing]


@dataclass(frozen=True, slots=True)
class Tag:
    """Where what an item draws stands in a tagged PDF's structure: in the elements of
    ``path`` within its page's section, outermost first -- each a structure type and a key
    that makes it one element (``("LI", "slide2.body.0.3")``) -- the last holding it.
    ``alt`` describes the last (a figure, a formula); ``artifact`` marks what is drawn only
    to be looked at (a band, a rule, a page number), which a reader passes over."""

    path: tuple[tuple[str, str], ...] = ()
    alt: str = ""
    artifact: bool = False


ARTIFACT = Tag(artifact=True)

type Tagger = Callable[[Shape | Text | Image | Group, Tag | None], Tag | None]
"""An item's ``Tag``, given the one it is within (``None`` at a page's top); ``None`` keeps
that one. Words tagged by nothing are a paragraph each; anything else, decoration."""


def write_pdf(
    pages: Pages,
    target: str | Path,
    *,
    title: str = "",
    author: str = "",
    tags: Tagger | None = None,
    language: str = "",
) -> Path:
    """Write ``pages`` (Flexo SVGs or drawings) as a PDF, one page each. ``title`` and
    ``author`` are the file's own, as a reader's Properties show them; with ``tags`` it is
    tagged (see ``Tagger``), in ``language`` (``en-GB``) where it is known."""

    target = Path(target)
    target.write_bytes(pdf_bytes(pages, title=title, author=author, tags=tags, language=language))
    return target


def pdf_bytes(
    pages: Pages,
    *,
    title: str = "",
    author: str = "",
    tags: Tagger | None = None,
    language: str = "",
) -> bytes:
    if isinstance(pages, str | Drawing):
        pages = [pages]
    drawings = [read_drawing(page) if isinstance(page, str) else page for page in pages]
    return _Writer(title, author, tags, language).write(drawings)


@dataclass(slots=True)
class _Element:
    """A structure element of a tagged PDF, and what it holds in reading order: elements,
    and marked content as (page object, marked-content id)."""

    kind: str
    alt: str = ""
    kids: list[_Element | tuple[int, int]] = field(default_factory=list)
    keyed: dict[tuple[str, str], _Element] = field(default_factory=dict)
    page: int | None = None
    number: int = 0


# -- the file ------------------------------------------------------------------------


class _Writer:
    def __init__(
        self, title: str, author: str = "", tags: Tagger | None = None, language: str = ""
    ) -> None:
        self.title = title
        self.author = author
        self.objects: list[bytes | None] = [None]  # object 0 is the free head
        self.fonts: dict[tuple[FontFace, int], _Font] = {}
        self.states: dict[tuple[float, float, str], str] = {}
        self.images: list[tuple[str, int]] = []
        self.tags = tags
        self.language = language
        self.document = _Element("Document")
        self.parents: list[list[_Element]] = []
        """Each page's elements, by the id of the marked content each holds there."""

    def reserve(self) -> int:
        self.objects.append(None)
        return len(self.objects) - 1

    def put(self, number: int, body: bytes) -> int:
        self.objects[number] = body
        return number

    def add(self, body: bytes) -> int:
        return self.put(self.reserve(), body)

    def stream(self, data: bytes, extra: str = "", compress: bool = True) -> int:
        if compress:
            # Flate at its usual level: the best (9) takes five times as long on a picture
            # for a few hundredths smaller.
            data = zlib.compress(data, 6)
            extra = "/Filter /FlateDecode " + extra
        head = f"<< {extra}/Length {len(data)} >>\nstream\n".encode()
        return self.add(head + data + b"\nendstream")

    def write(self, drawings: list[Drawing]) -> bytes:
        catalog, tree, resources = self.reserve(), self.reserve(), self.reserve()
        kids = []
        for drawing in drawings:
            page = self.reserve()
            content = _Content(self, drawing.height, page)
            content.items(drawing.root.items)
            stream = self.stream(content.bytes())
            links = [
                self.add(
                    (
                        f"<< /Type /Annot /Subtype /Link /Rect [{' '.join(_n(v) for v in box)}] "
                        f"/Border [0 0 0] /A << /S /URI /URI {_string(url)} >> >>"
                    ).encode()
                )
                for box, url in content.links
            ]
            annotations = f"/Annots [{' '.join(f'{n} 0 R' for n in links)}] " if links else ""
            structure = f"/StructParents {len(self.parents)} /Tabs /S " if self.tags else ""
            if self.tags:
                self.parents.append(content.marked)
            kids.append(
                self.put(
                    page,
                    f"<< /Type /Page /Parent {tree} 0 R "
                    f"/MediaBox [0 0 {_n(drawing.width)} {_n(drawing.height)}] "
                    f"{annotations}{structure}"
                    f"/Resources {resources} 0 R /Contents {stream} 0 R >>".encode(),
                )
            )
        fonts = " ".join(f"/{font.name} {font.embed(self)} 0 R" for font in self.fonts.values())
        states = " ".join(
            f"/{name} << /Type /ExtGState /ca {_n(fill)} /CA {_n(stroke)} "
            f"/BM /{blend.capitalize()} >>"
            for (fill, stroke, blend), name in self.states.items()
        )
        images = " ".join(f"/{name} {number} 0 R" for name, number in self.images)
        self.put(
            resources,
            f"<< /ProcSet [/PDF /Text /ImageC] /Font << {fonts} >> /ExtGState << {states} >> "
            f"/XObject << {images} >> >>".encode(),
        )
        listed = " ".join(f"{kid} 0 R" for kid in kids)
        self.put(tree, f"<< /Type /Pages /Kids [{listed}] /Count {len(kids)} >>".encode())
        tagged = ""
        if self.tags:
            tagged = (
                f" /MarkInfo << /Marked true >> /StructTreeRoot {self._structure()} 0 R"
                " /ViewerPreferences << /DisplayDocTitle true >>"
            )
            if self.language:
                tagged += f" /Lang {_string(self.language)}"
        self.put(catalog, f"<< /Type /Catalog /Pages {tree} 0 R{tagged} >>".encode())
        author = f" /Author {_string(self.author)}" if self.author else ""
        info = self.add(f"<< /Producer (flexo) /Title {_string(self.title)}{author} >>".encode())
        out = BytesIO()
        out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(self.objects[1:], start=1):
            offsets.append(out.tell())
            out.write(f"{number} 0 obj\n".encode() + (body or b"null") + b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(self.objects)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            out.write(f"{offset:010d} 00000 n \n".encode())
        out.write(
            f"trailer\n<< /Size {len(self.objects)} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n".encode()
        )
        return out.getvalue()

    def _structure(self) -> int:
        """The structure tree's objects, and its root's number: every element, and the
        tree that leads from each page's marked content back to its element."""

        root = self.reserve()

        def number(element: _Element) -> None:
            element.number = self.reserve()
            for kid in element.kids:
                if isinstance(kid, _Element):
                    number(kid)

        def put(element: _Element, parent: int) -> None:
            kids = []
            for kid in element.kids:
                if isinstance(kid, _Element):
                    put(kid, element.number)
                    kids.append(f"{kid.number} 0 R")
                else:
                    kids.append(f"<< /Type /MCR /Pg {kid[0]} 0 R /MCID {kid[1]} >>")
            alt = f" /Alt {_string(element.alt)}" if element.alt else ""
            page = f" /Pg {element.page} 0 R" if element.page is not None else ""
            self.put(
                element.number,
                f"<< /Type /StructElem /S /{element.kind} /P {parent} 0 R{page}{alt} "
                f"/K [{' '.join(kids)}] >>".encode(),
            )

        number(self.document)
        put(self.document, root)
        nums = " ".join(
            f"{index} [{' '.join(f'{element.number} 0 R' for element in marked)}]"
            for index, marked in enumerate(self.parents)
        )
        parents = self.add(f"<< /Nums [{nums}] >>".encode())
        return self.put(
            root,
            f"<< /Type /StructTreeRoot /K [{self.document.number} 0 R] /ParentTree {parents} 0 R "
            f"/ParentTreeNextKey {len(self.parents)} >>".encode(),
        )

    def state(self, fill: float, stroke: float, blend: str) -> str:
        key = (round(fill, 4), round(stroke, 4), blend)
        if key not in self.states:
            self.states[key] = f"G{len(self.states)}"
        return self.states[key]

    def font(self, face: FontFace, weight: int) -> _Font:
        weight = weight if face.variable else face.weight
        key = (face, weight)
        if key not in self.fonts:
            self.fonts[key] = _Font(f"F{len(self.fonts)}", face, weight)
        return self.fonts[key]


# -- page content ----------------------------------------------------------------------


class _Content:
    def __init__(self, writer: _Writer, height: float, page: int = 0) -> None:
        self.writer = writer
        self.height = height
        self.page = page
        self.links: list[tuple[tuple[float, float, float, float], str]] = []
        """``(left, bottom, right, top)`` in PDF space, and the URL, of each linked run."""
        # PDF's y runs up; the drawing's runs down. Flip once, for the page.
        self.ops: list[str] = [f"1 0 0 -1 0 {_n(height)} cm"]
        self.marked: list[_Element] = []
        """The element each of the page's marked-content ids belongs to, in order."""
        self.section: _Element | None = None

    def bytes(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")

    def items(self, items, within: Tag | None = None) -> None:
        tagger = self.writer.tags
        for item in items:
            tag = within
            if tagger is not None:
                tag = tagger(item, within) or within
            if isinstance(item, Group):
                if "data-flexo-math" in item.data:
                    self.formula(item, tag)
                else:
                    self.items(item.items, tag)
                continue
            with self.marking(item, tag):
                if isinstance(item, Shape):
                    self.shape(item)
                elif isinstance(item, Text):
                    self.text(item)
                elif isinstance(item, Image):
                    self.image(item)

    @contextlib.contextmanager
    def marking(self, item: object, tag: Tag | None):
        """What ``item`` draws, marked as content of its structure element, or as decoration:
        words no tag places are a paragraph of their own. Unmarked in an untagged PDF."""

        if self.writer.tags is None:
            yield
            return
        if tag is None and isinstance(item, Text):
            tag = Tag((("P", item.id or f"text{len(self.marked)}"),))
        if tag is None or tag.artifact or not tag.path:
            self.ops.append("/Artifact BMC")
            yield
            self.ops.append("EMC")
            return
        if self.section is None:
            self.section = _Element("Sect", page=self.page)
            self.writer.document.kids.append(self.section)
        element = self.section
        for depth, key in enumerate(tag.path):
            found = element.keyed.get(key)
            if found is None:
                found = _Element(key[0], page=self.page)
                element.keyed[key] = found
                element.kids.append(found)
            if depth == len(tag.path) - 1 and tag.alt:
                found.alt = tag.alt
            element = found
        identifier = len(self.marked)
        self.marked.append(element)
        element.kids.append((self.page, identifier))
        self.ops.append(f"/{element.kind} << /MCID {identifier} >> BDC")
        yield
        self.ops.append("EMC")

    def formula(self, group: Group, tag: Tag | None) -> None:
        """A formula drawn as outlines, with the words it reads as under it, invisible: found,
        copied and read like any words. Its own element, a formula described by its words,
        unless it is within words (a title's) or a figure."""

        words = _formula_words(group.data.get("data-flexo-math", ""))
        if tag is None or tag.artifact or not tag.path:
            tag = Tag((("Formula", group.id or f"formula{len(self.marked)}"),), alt=words)
        with self.marking(group, tag):
            self.items_unmarked(group.items)
            self.hidden_words(group, words)

    def items_unmarked(self, items) -> None:
        for item in items:
            if isinstance(item, Group):
                self.items_unmarked(item.items)
            elif isinstance(item, Shape):
                self.shape(item)
            elif isinstance(item, Text):
                self.text(item)
            elif isinstance(item, Image):
                self.image(item)

    def hidden_words(self, group: Group, words: str) -> None:
        """``words`` laid invisibly across what ``group`` draws, as wide as it is."""

        from flexo.drawing import ink_bounds
        from flexo.style import TypographyStyle
        from flexo.text import font_stack

        left, top, right, bottom = ink_bounds(Drawing(0.0, 0.0, Group(None, list(group.items))))
        words = " ".join(words.split())
        if not words or right <= left or bottom <= top:
            return
        face = font_stack(TypographyStyle()).face(400, False)
        font = self.writer.font(face, 400)
        loaded = hb_font(face, 400)
        size = min(bottom - top, 1000.0)
        upem = load_face(face).upem
        shown, advance = [], 0.0
        for character in words:
            gid = loaded.get_nominal_glyph(ord(character)) or 0
            cid, width = font.use(gid, character)
            shown.append(f"<{cid:04X}>")
            advance += width / upem * size
        stretch = 100.0 * (right - left) / advance if advance > 0 else 100.0
        # Within q ... Q: the render mode and scaling are graphics state, which outlasts ET,
        # and would leave every word after these invisible too.
        self.ops.append(
            f"q BT 3 Tr /{font.name} 1 Tf {_n(stretch)} Tz {_n(size)} 0 0 {_n(-size)} {_n(left)} "
            f"{_n(bottom - 0.2 * size)} Tm [{''.join(shown)}] TJ ET Q"
        )

    def paint(self, paint: Paint, segments: Sequence[Segment]) -> None:
        fill = _colour(paint.fill)
        stroke = _colour(paint.stroke) if paint.stroke_width > 0 else None
        if fill is None and stroke is None:
            return
        ops = self.ops
        ops.append("q")
        fill_alpha = paint.fill_opacity * paint.opacity
        stroke_alpha = paint.stroke_opacity * paint.opacity
        if fill_alpha < 1.0 or stroke_alpha < 1.0 or paint.blend != "normal":
            ops.append(f"/{self.writer.state(fill_alpha, stroke_alpha, paint.blend)} gs")
        if fill is not None:
            ops.append(f"{_rgb(fill)} rg")
        if stroke is not None:
            ops.append(f"{_rgb(stroke)} RG {_n(paint.stroke_width)} w")
            ops.append(f"{_CAPS.get(paint.linecap, 0)} J {_JOINS.get(paint.linejoin, 0)} j 4 M")
            if paint.dash and any(value > 0 for value in paint.dash):
                ops.append(f"[{' '.join(_n(value) for value in paint.dash)}] 0 d")
        ops.append(_path(segments))
        ops.append("B" if fill and stroke else "f" if fill else "S")
        ops.append("Q")

    def shape(self, item: Shape) -> None:
        self.paint(item.paint, item.segments)
        for head in item.arrowheads:
            self.paint(head.paint, head.outline)

    def text(self, item: Text) -> None:
        if item.angle:
            # Turned about its pivot, as SVG's rotate(angle, x, y) turns it.
            turn = math.radians(item.angle)
            cos, sin = math.cos(turn), math.sin(turn)
            x, y = item.pivot
            matrix = (cos, sin, -sin, cos, x - cos * x + sin * y, y - sin * x - cos * y)
            self.ops.append("q " + " ".join(_n(value) for value in matrix) + " cm")
        for number, line in enumerate(item.lines):
            runs, at = line.runs, 0
            while at < len(runs):
                run = runs[at]
                at += 1
                if run.face is None:
                    continue
                if not run.text.strip():
                    # A space set as a run of its own (around a sign in maths) is still one
                    # between the words read out.
                    self.space(run, run.x)
                    continue
                if run.shift:
                    # A script, with the runs raised (or lowered) beside it: e^{-m} is one.
                    together = [run]
                    while at < len(runs) and _beside(runs[at], run):
                        together.append(runs[at])
                        at += 1
                    self.scripts(together, after=runs[at].text[:1] if at < len(runs) else "")
                else:
                    self.glyphs(run)
                if run.link:
                    # A link is underlined, as in the PowerPoint, so it is told from the
                    # words around it by more than its colour.
                    left, top, width, thickness = underline(run)
                    self.ops.append(
                        f"q {_rgb(_colour(run.fill) or '#000000')} rg "
                        f"{_n(left)} {_n(top)} {_n(width)} {_n(thickness)} re f Q"
                    )
                    if not item.angle:
                        top, bottom = run.baseline - run.size * 0.85, run.baseline + run.size * 0.25
                        box = (run.x, self.height - bottom, run.x + run.width, self.height - top)
                        self.links.append((box, run.link))
            written = [run for run in line.runs if run.face is not None and run.text]
            last = written[-1].text[-1:] if written else " "
            if number < len(item.lines) - 1 and not last.isspace() and last not in _WORD_BREAKS:
                # Words wrapped onto the next line were parted by a space: it is read there.
                self.space(written[-1], written[-1].x + written[-1].width)
        if item.angle:
            self.ops.append("Q")

    def space(self, run: Run, x: float) -> None:
        """A space at ``x`` on ``run``'s baseline, in its face: drawing nothing, but read
        (and found, and copied) between the words either side."""

        font = self.writer.font(run.face, run.weight)
        gid = hb_font(run.face, run.weight).get_nominal_glyph(ord(" ")) or 0
        cid, _ = font.use(gid, " ")
        # Within q ... Q, so the words after it are drawn (see ``hidden_words``).
        self.ops.append(
            f"q BT 3 Tr /{font.name} 1 Tf {_n(run.size)} 0 0 {_n(-run.size)} {_n(x)} "
            f"{_n(run.baseline)} Tm <{cid:04X}> Tj ET Q"
        )

    def scripts(self, runs: list[Run], after: str = "") -> None:
        """A script among words (``k_auto``, ``e^(-m)``, ``x²``), read as a formula's words
        read (``texmath.scripted``), apart from a letter ``after`` it where it follows its
        mark (k_B p, not k_Bp): drawn as outlines, the words it reads as laid invisibly over
        them -- as a formula is, which every reader reads in its place among the words."""

        from flexo.texmath import scripted

        text = "".join(run.text for run in runs)
        said = scripted(text, raised=runs[0].shift > 0)
        if said[:1] in "_^" and said[-1:].isalnum() and after[:1].isalnum():
            said += " "
        if said == text:
            for run in runs:
                self.glyphs(run)
            return
        for run in runs:
            self.paint(Paint(fill=_colour(run.fill) or "#000000"), run_outline(run))
        first, last = runs[0], runs[-1]
        # On the line's baseline, not the script's: read on with the words either side of it.
        on_line = replace(first, baseline=first.baseline + first.shift)
        self.laid(on_line, said, last.x + last.width - first.x)

    def laid(self, run: Run, words: str, width: float) -> None:
        """``words`` laid invisibly from ``run``'s pen on its baseline, in its face, as wide
        as ``width``: found, copied and read in place of what is drawn there."""

        font = self.writer.font(run.face, run.weight)
        loaded = hb_font(run.face, run.weight)
        upem = load_face(run.face).upem
        shown, advance = [], 0.0
        for character in words:
            cid, wide = font.use(loaded.get_nominal_glyph(ord(character)) or 0, character)
            shown.append(f"<{cid:04X}>")
            advance += wide / upem * run.size
        stretch = 100.0 * width / advance if advance > 0 and width > 0 else 100.0
        # Within q ... Q, so the words after it are drawn (see ``hidden_words``).
        self.ops.append(
            f"q BT 3 Tr /{font.name} 1 Tf {_n(stretch)} Tz {_n(run.size)} 0 0 {_n(-run.size)} "
            f"{_n(run.x)} {_n(run.baseline)} Tm [{''.join(shown)}] TJ ET Q"
        )

    def glyphs(self, run: Run) -> None:
        colour = _colour(run.fill) or "#000000"
        font = self.writer.font(run.face, run.weight)
        size = run.size
        slant = SYNTHETIC_SLANT * size if run.italic and not run.face.italic else 0.0
        scale = size / load_face(run.face).upem
        ops = self.ops
        ops.append(f"BT {_rgb(colour)} rg /{font.name} 1 Tf")
        shown: list[str] = []
        pen: tuple[float, float] | None = None

        def flush() -> None:
            if shown:
                ops.append(f"[{''.join(shown)}] TJ")
                shown.clear()

        for glyph in shape(run):
            if glyph.text == "\u200a":
                # A hair's room (an italic letter's lean before a sign) is left, not written:
                # read beside the space after it, it would be two.
                continue
            cid, width = font.use(glyph.gid, glyph.text)
            if pen is None or abs(glyph.y - pen[1]) > 1e-6 or abs(glyph.x - pen[0]) > 0.5 * size:
                flush()
                ops.append(f"{_n(size)} 0 {_n(slant)} {_n(-size)} {_n(glyph.x)} {_n(glyph.y)} Tm")
            elif abs(glyph.x - pen[0]) > 1e-4:
                shown.append(_n(-(glyph.x - pen[0]) * 1000.0 / size))
            shown.append(f"<{cid:04X}>")
            pen = (glyph.x + width * scale, glyph.y)
        flush()
        ops.append("ET")

    def image(self, item: Image) -> None:
        mime, data = _decode(item.href)
        if mime is None:
            return
        if mime == "image/svg+xml":
            import resvg_py

            pixels = max(1, round(item.width / 72.0 * ARTWORK_DPI))
            # A dpi lets resvg resolve sizes given in pt or mm; the width sets the pixels.
            svg = data.decode("utf-8")
            from flexo.fonts import font_directories

            folders = [str(folder) for folder in font_directories()]
            data = bytes(
                resvg_py.svg_to_bytes(svg_string=svg, dpi=72, width=pixels, font_dirs=folders)
            )
            mime = "image/png"
            x, y, w, h = item.x, item.y, item.width, item.height
        else:
            size = _pixel_size(mime, data)
            if size is None:
                return
            x, y, w, h = item.placed(*size)
        name = f"I{len(self.writer.images)}"
        number = _image_object(self.writer, mime, data)
        if number is None:
            return
        self.writer.images.append((name, number))
        # An image fills the unit square with its first row at the top: flip it back
        # (unless it is to be drawn mirrored).
        across = f"{_n(-w)} 0" if item.flip_x else f"{_n(w)} 0"
        down = f"0 {_n(h)}" if item.flip_y else f"0 {_n(-h)}"
        left = x + w if item.flip_x else x
        top = y if item.flip_y else y + h
        # A picture filling its box by slicing is clipped to the box.
        clip = ""
        if w > item.width + 0.01 or h > item.height + 0.01:
            clip = f"{_n(item.x)} {_n(item.y)} {_n(item.width)} {_n(item.height)} re W n "
        self.ops.append(f"q {clip}{across} {down} {_n(left)} {_n(top)} cm /{name} Do Q")


def _formula_words(source: str) -> str:
    """What a formula reads as, in words (``flexo.texmath.linear``): ``\\frac{a}{b}`` as ``a/b``."""

    from flexo.texmath import linear

    try:
        return linear(source)
    except Exception:
        return source


def _path(segments: Sequence[Segment]) -> str:
    parts = []
    for segment in segments:
        points = " ".join(f"{_n(x)} {_n(y)}" for x, y in segment.points)
        parts.append(f"{points} {_OPERATORS[segment.kind]}" if points else "h")
    return " ".join(parts)


# -- fonts -------------------------------------------------------------------------------


@dataclass(slots=True)
class _Font:
    """One face at one weight, embedded as the subset of glyphs a document uses."""

    name: str
    face: FontFace
    weight: int
    cids: dict[int, int] = field(default_factory=dict)
    """Glyph id in the face -> glyph id (and CID) in the subset."""
    texts: dict[int, str] = field(default_factory=dict)
    widths: dict[int, float] = field(default_factory=dict)

    def use(self, gid: int, text: str) -> tuple[int, float]:
        """The subset's CID for ``gid``, and its advance in font units. A character the
        face lacks (gid 0, its blank) takes a CID of its own, so it still reads as itself."""

        key = gid if gid or not text else -ord(text[0])
        if key not in self.cids:
            cid = len(self.cids) + 1
            self.cids[key] = cid
            self.widths[cid] = hb_font(self.face, self.weight).get_glyph_h_advance(gid)
        cid = self.cids[key]
        if text and cid not in self.texts:
            self.texts[cid] = text
        return cid, self.widths[cid]

    def embed(self, writer: _Writer) -> int:
        loaded = load_face(self.face)
        upem = loaded.upem
        program, box = self._program(upem, loaded.ascent, loaded.descent)
        font_file = writer.stream(program, f"/Length1 {len(program)} ")
        digest = hashlib.sha256(program).digest()
        tag = "".join(chr(ord("A") + digest[i] % 26) for i in range(6))
        italic = self.face.italic
        name = f"{self.face.family}-{self.weight}{'-Italic' if italic else ''}"
        base = f"{tag}+{re.sub(r'[^A-Za-z0-9-]', '', name)}"
        unit = 1000.0 / upem
        descriptor = writer.add(
            (
                f"<< /Type /FontDescriptor /FontName /{base} /Flags {4 | (64 if italic else 0)} "
                f"/FontBBox [{' '.join(_n(v * unit) for v in box)}] "
                f"/ItalicAngle {-12 if italic else 0} "
                f"/Ascent {_n(loaded.ascent * unit)} /Descent {_n(-loaded.descent * unit)} "
                f"/CapHeight {_n((loaded.cap_height or loaded.ascent) * unit)} /StemV 80 "
                f"/FontFile2 {font_file} 0 R >>"
            ).encode()
        )
        widths = " ".join(_n(self.widths[cid] * unit) for cid in range(1, len(self.cids) + 1))
        descendant = writer.add(
            (
                f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{base} "
                f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                f"/FontDescriptor {descriptor} 0 R /DW 0 /W [1 [{widths}]] "
                "/CIDToGIDMap /Identity >>"
            ).encode()
        )
        to_unicode = writer.stream(_cmap(self.texts))
        return writer.add(
            (
                f"<< /Type /Font /Subtype /Type0 /BaseFont /{base} /Encoding /Identity-H "
                f"/DescendantFonts [{descendant} 0 R] /ToUnicode {to_unicode} 0 R >>"
            ).encode()
        )

    def _program(
        self, upem: int, ascent: int, descent: int
    ) -> tuple[bytes, tuple[float, float, float, float]]:
        """A TrueType font of the used glyphs, in CID order, drawn from HarfBuzz's outlines."""

        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.cu2quPen import Cu2QuPen
        from fontTools.pens.ttGlyphPen import TTGlyphPen

        cubic = "CFF " in _tables(self.face) or "CFF2" in _tables(self.face)
        order = [".notdef"] + [f"g{cid}" for cid in range(1, len(self.cids) + 1)]
        glyphs = {".notdef": TTGlyphPen(None).glyph()}
        for gid, cid in self.cids.items():
            pen = TTGlyphPen(None)
            # CFF outlines run counter-clockwise; TrueType's run clockwise.
            target = Cu2QuPen(pen, max_err=upem / 2000.0, reverse_direction=cubic)
            _replay(_outline(self.face, self.weight, max(gid, 0)), target)
            glyphs[f"g{cid}"] = pen.glyph()
        builder = FontBuilder(upem, isTTF=True)
        builder.setupGlyphOrder(order)
        builder.setupCharacterMap({})
        builder.setupGlyf(glyphs)
        table = builder.font["glyf"]
        metrics = {".notdef": (0, 0)}
        for cid in range(1, len(self.cids) + 1):
            glyph = table[f"g{cid}"]
            metrics[f"g{cid}"] = (round(self.widths[cid]), getattr(glyph, "xMin", 0))
        builder.setupHorizontalMetrics(metrics)
        builder.setupHorizontalHeader(ascent=ascent, descent=-descent)
        builder.setupNameTable({"familyName": self.face.family, "styleName": f"W{self.weight}"})
        builder.setupOS2(
            sTypoAscender=ascent, sTypoDescender=-descent, usWinAscent=ascent, usWinDescent=descent
        )
        builder.setupPost()
        out = BytesIO()
        builder.save(out)
        boxes = [table[name] for name in order[1:] if getattr(table[name], "numberOfContours", 0)]
        box = (
            (
                min(g.xMin for g in boxes),
                min(g.yMin for g in boxes),
                max(g.xMax for g in boxes),
                max(g.yMax for g in boxes),
            )
            if boxes
            else (0, -descent, upem, ascent)
        )
        return out.getvalue(), box


def _tables(face: FontFace) -> set[str]:
    from fontTools.ttLib import TTCollection, TTFont

    raw = BytesIO(load_face(face).raw)
    if face.source.lower().endswith((".ttc", ".otc")):
        return set(TTCollection(raw, lazy=True).fonts[face.index].keys())
    return set(TTFont(raw, lazy=True).keys())


def _replay(segments: Sequence[Segment], pen) -> None:
    open_ = False
    for segment in segments:
        if segment.kind == "M":
            if open_:
                pen.closePath()
            pen.moveTo(segment.points[0])
            open_ = True
        elif segment.kind == "L":
            pen.lineTo(segment.points[0])
        elif segment.kind == "C":
            pen.curveTo(*segment.points)
        else:
            pen.closePath()
            open_ = False
    if open_:
        pen.closePath()


def _cmap(texts: dict[int, str]) -> bytes:
    entries = []
    for cid, text in sorted(texts.items()):
        units = text.encode("utf-16-be").hex().upper()
        entries.append(f"<{cid:04X}> <{units}>")
    chunks = [entries[index : index + 100] for index in range(0, len(entries), 100)]
    body = "".join(
        f"{len(chunk)} beginbfchar\n" + "\n".join(chunk) + "\nendbfchar\n" for chunk in chunks
    )
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{body}endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")


# -- images ------------------------------------------------------------------------------


def _decode(href: str) -> tuple[str | None, bytes]:
    match = re.match(r"data:([^;,]+)(;base64)?,(.*)", href, re.DOTALL)
    if match is None:
        path = Path(href.removeprefix("file://"))
        if not path.is_file():
            return None, b""
        return _MIME.get(path.suffix.lower()), path.read_bytes()
    mime, encoded, payload = match.groups()
    if encoded:
        return mime, base64.b64decode(payload)
    from urllib.parse import unquote_to_bytes

    return mime, unquote_to_bytes(payload)


def _pixel_size(mime: str, data: bytes) -> tuple[float, float] | None:
    if mime == "image/png" and data[12:16] == b"IHDR":
        return tuple(float(v) for v in struct.unpack(">II", data[16:24]))  # type: ignore[return-value]
    if mime == "image/jpeg":
        index = 2
        while index + 9 < len(data):
            marker, length = data[index + 1], struct.unpack(">H", data[index + 2 : index + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return float(width), float(height)
            index += 2 + length
    return None


def _image_object(writer: _Writer, mime: str, data: bytes) -> int | None:
    if mime == "image/jpeg":
        size = _pixel_size(mime, data)
        if size is None:
            return None
        components = data[data.find(b"\xff\xc0") + 9] if b"\xff\xc0" in data else 3
        space = {1: "/DeviceGray", 4: "/DeviceCMYK"}.get(components, "/DeviceRGB")
        return writer.stream(
            data,
            f"/Type /XObject /Subtype /Image /Width {int(size[0])} /Height {int(size[1])} "
            f"/ColorSpace {space} /BitsPerComponent 8 /Filter /DCTDecode ",
            compress=False,
        )
    if mime != "image/png":
        return None
    width, height, channels, pixels = _png_pixels(data)
    colour_channels = 1 if channels in (1, 2) else 3
    alpha = channels in (2, 4)
    colour, mask = bytes(pixels), b""
    if alpha:
        # Colour and alpha parted by slicing, not pixel by pixel: a plot drawn as a
        # picture has millions of pixels.
        mask = bytes(pixels[channels - 1 :: channels])
        parted = bytearray(len(mask) * colour_channels)
        for channel in range(colour_channels):
            parted[channel::colour_channels] = pixels[channel::channels]
        colour = bytes(parted)
    smask = ""
    if alpha and mask.count(255) != len(mask):
        soft = writer.stream(
            bytes(mask),
            f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
            "/ColorSpace /DeviceGray /BitsPerComponent 8 ",
        )
        smask = f"/SMask {soft} 0 R "
    space = "/DeviceGray" if colour_channels == 1 else "/DeviceRGB"
    return writer.stream(
        bytes(colour),
        f"/Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace {space} "
        f"/BitsPerComponent 8 {smask}",
    )


def _png_pixels(data: bytes) -> tuple[int, int, int, bytes]:
    """A PNG's pixels as 8-bit rows: ``width, height, channels, bytes``."""

    try:
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(data)) as picture:
            mode = "RGBA" if "A" in picture.getbands() or "transparency" in picture.info else "RGB"
            if picture.mode in ("L", "LA") and mode != "RGBA":
                mode = "L"
            converted = picture.convert(mode)
            return converted.width, converted.height, len(mode), converted.tobytes()
    except ImportError:
        pass
    return _png_decode(data)


def _png_decode(data: bytes) -> tuple[int, int, int, bytes]:
    """A plain-Python PNG decoder for 8-bit, non-interlaced images (Pillow is faster)."""

    index, chunks, header, palette, transparency = 8, [], b"", b"", b""
    while index < len(data):
        length = struct.unpack(">I", data[index : index + 4])[0]
        kind = data[index + 4 : index + 8]
        body = data[index + 8 : index + 8 + length]
        if kind == b"IHDR":
            header = body
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            chunks.append(body)
        index += 12 + length
    width, height, depth, colour_type, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if depth != 8 or interlace:
        raise ValueError("without Pillow, flexo reads 8-bit, non-interlaced PNGs only")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    raw = zlib.decompress(b"".join(chunks))
    stride = width * channels
    rows, previous = [], bytearray(stride)
    position = 0
    for _ in range(height):
        kind, line = raw[position], bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                best = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                line[i] = (line[i] + best) & 255
        rows.append(bytes(line))
        previous = line
    pixels = b"".join(rows)
    if colour_type == 3:
        alpha = transparency + b"\xff" * (256 - len(transparency))
        expanded = bytearray()
        for value in pixels:
            expanded += palette[3 * value : 3 * value + 3] + bytes([alpha[value]])
        return width, height, 4, bytes(expanded)
    return width, height, channels, pixels


# -- values ------------------------------------------------------------------------------


def _colour(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value in _NAMED:
        return _NAMED[value]
    match = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if match:
        parts = [float(part.strip().rstrip("%")) for part in match.group(1).split(",")[:3]]
        return "#" + "".join(f"{round(min(255, max(0, part))):02x}" for part in parts)
    return value if value.startswith("#") else None


def _rgb(colour: str) -> str:
    try:
        return " ".join(_n(channel) for channel in to_rgb(colour))
    except ValueError:
        return "0 0 0"


def _n(value: float) -> str:
    if abs(value) < 5e-6:
        return "0"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _string(text: str) -> str:
    if text.isascii():
        return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    return "<FEFF" + text.encode("utf-16-be").hex().upper() + ">"
