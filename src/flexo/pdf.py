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
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from flexo.colour import to_rgb
from flexo.drawing import Drawing, Group, Image, Paint, Run, Segment, Shape, Text, read_drawing
from flexo.fonts import FontFace, hb_font, load_face
from flexo.outline import _outline, shape
from flexo.portable import SYNTHETIC_SLANT

ARTWORK_DPI = 300.0
"""The resolution nested SVG artwork is rasterised at."""

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
_NAMED = {"black": "#000000", "white": "#ffffff", "transparent": None, "none": None}
_OPERATORS = {"M": "m", "L": "l", "C": "c"}
_CAPS = {"butt": 0, "round": 1, "square": 2}
_JOINS = {"miter": 0, "round": 1, "bevel": 2}


type Pages = str | Drawing | Sequence[str | Drawing]


def write_pdf(pages: Pages, target: str | Path, *, title: str = "") -> Path:
    """Write ``pages`` (Flexo SVGs or drawings) as a PDF, one page each."""

    target = Path(target)
    target.write_bytes(pdf_bytes(pages, title=title))
    return target


def pdf_bytes(pages: Pages, *, title: str = "") -> bytes:
    if isinstance(pages, str | Drawing):
        pages = [pages]
    drawings = [read_drawing(page) if isinstance(page, str) else page for page in pages]
    return _Writer(title).write(drawings)


# -- the file ------------------------------------------------------------------------


class _Writer:
    def __init__(self, title: str) -> None:
        self.title = title
        self.objects: list[bytes | None] = [None]  # object 0 is the free head
        self.fonts: dict[tuple[FontFace, int], _Font] = {}
        self.states: dict[tuple[float, float, str], str] = {}
        self.images: list[tuple[str, int]] = []

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
            data = zlib.compress(data, 9)
            extra = "/Filter /FlateDecode " + extra
        head = f"<< {extra}/Length {len(data)} >>\nstream\n".encode()
        return self.add(head + data + b"\nendstream")

    def write(self, drawings: list[Drawing]) -> bytes:
        catalog, tree, resources = self.reserve(), self.reserve(), self.reserve()
        kids = []
        for drawing in drawings:
            content = _Content(self, drawing.height)
            content.items(drawing.root.items)
            stream = self.stream(content.bytes())
            kids.append(
                self.add(
                    f"<< /Type /Page /Parent {tree} 0 R "
                    f"/MediaBox [0 0 {_n(drawing.width)} {_n(drawing.height)}] "
                    f"/Resources {resources} 0 R /Contents {stream} 0 R >>".encode()
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
        self.put(catalog, f"<< /Type /Catalog /Pages {tree} 0 R >>".encode())
        info = self.add(f"<< /Producer (flexo) /Title {_string(self.title)} >>".encode())
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
    def __init__(self, writer: _Writer, height: float) -> None:
        self.writer = writer
        # PDF's y runs up; the drawing's runs down. Flip once, for the page.
        self.ops: list[str] = [f"1 0 0 -1 0 {_n(height)} cm"]

    def bytes(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")

    def items(self, items) -> None:
        for item in items:
            if isinstance(item, Group):
                self.items(item.items)
            elif isinstance(item, Shape):
                self.shape(item)
            elif isinstance(item, Text):
                self.text(item)
            elif isinstance(item, Image):
                self.image(item)

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
        for line in item.lines:
            for run in line.runs:
                if run.face is not None and run.text.strip():
                    self.run(run)
        if item.angle:
            self.ops.append("Q")

    def run(self, run: Run) -> None:
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
            data = bytes(resvg_py.svg_to_bytes(svg_string=data.decode("utf-8"), width=pixels))
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
        self.ops.append(f"q {across} {down} {_n(left)} {_n(top)} cm /{name} Do Q")


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
        """The subset's CID for ``gid``, and its advance in font units."""

        if gid not in self.cids:
            cid = len(self.cids) + 1
            self.cids[gid] = cid
            self.widths[cid] = hb_font(self.face, self.weight).get_glyph_h_advance(gid)
        cid = self.cids[gid]
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
            _replay(_outline(self.face, self.weight, gid), target)
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
    colour = bytearray()
    mask = bytearray()
    stride = width * channels
    for row in range(height):
        line = pixels[row * stride : (row + 1) * stride]
        if alpha:
            for start in range(0, len(line), channels):
                colour += line[start : start + colour_channels]
                mask.append(line[start + channels - 1])
        else:
            colour += line
    smask = ""
    if alpha and any(value != 255 for value in mask):
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
