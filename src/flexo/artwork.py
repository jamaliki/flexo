"""Author-supplied artwork: load, sanitize, and size an embedded SVG, PNG, JPEG or GIF.

An ``image`` component carries no compiler-drawn ink. It carries a file the
author drew -- a molecule icon, a density-map view -- and Flexo's whole job is
to put that file into the figure *without* redrawing it: an SVG arrives as
vector content nested at the node's bounds, a PNG as a data URI, and both travel
inside the editable and portable SVG with no companion file to lose. A GIF is a
photograph as a PNG is, which plays where a screen shows it (``flexo.animated``).

Two consequences shape everything below. Because the artwork is inlined rather
than referenced, it has to be safe to inline: a file that would execute script,
or reach out to the network when the figure is opened, is rejected here with a
diagnostic instead of being quietly stripped, so the author learns that the
drawing they exported is not the drawing that would ship. And because two nodes
may embed the same file next to a figure that has ids of its own, every id in
the artwork is rewritten under the node's own id before it is ever appended.
"""

from __future__ import annotations

import base64
import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from flexo.confine import outside
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.ir.semantic import NodeSpec
from flexo.svg import local_name
from flexo.units import NUMBER_PATTERN, POINTS_PER_UNIT

SVG_SUFFIXES = frozenset({".svg"})
PNG_SUFFIXES = frozenset({".png"})
JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})
GIF_SUFFIXES = frozenset({".gif"})
"""A GIF: a photograph that plays (``flexo.animated``), placed as a PNG is."""
CONVERTED_SUFFIXES = frozenset({".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif", ".avif"})
"""Photographs no drawing's viewers all show (WebP, TIFF, BMP, a phone's HEIC, AVIF): placed as
the PNG they are made once, kept in the cache (``_converted``)."""
RASTER_SUFFIXES = PNG_SUFFIXES | JPEG_SUFFIXES | GIF_SUFFIXES | CONVERTED_SUFFIXES
"""What is read as a photograph -- by what its bytes are, not by its name: a PNG saved from a
web page as ``.jpg``, as one so often is, is the PNG it is (``_sniffed``)."""
PAGE_SUFFIXES = frozenset({".pdf", ".ai"})
"""A PDF's page, and an Illustrator file's artboard (an Illustrator file is a PDF with
Illustrator's own data beside it): read as the vectors they are (``flexo.pdfart``)."""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_XML_DECLARATION = re.compile(r"^﻿?\s*<\?xml\b.*?\?>", re.DOTALL)
_DOCTYPE = re.compile(r"<!DOCTYPE\b[^>\[]*(?:\[[^\]]*\])?[^>]*>", re.DOTALL | re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_FRAGMENT = re.compile(r"#([A-Za-z_][A-Za-z0-9_.:-]*)")
_URL_REFERENCE = re.compile(r"url\(\s*['\"]?([^'\")]*)")
_CSS_IMPORT = re.compile(r"@import\b", re.IGNORECASE)

_SVG_LENGTH = re.compile(rf"^\s*({NUMBER_PATTERN})\s*(px|pt|pc|mm|cm|in|em|ex|%)?\s*$")
_ABSOLUTE_UNITS = {**POINTS_PER_UNIT, "pc": 12.0}
"""SVG length units Flexo can turn into points.

``em``, ``ex``, and ``%`` describe a size the artwork does not carry with it, so
a file sized in them has no intrinsic size and the author has to give one.
"""


@dataclass(frozen=True, slots=True)
class Artwork:
    """One loaded, sanitized artwork file, ready to be placed at a node."""

    node_id: str
    path: Path
    format: str
    """``"svg"``, ``"png"``, ``"jpeg"``, or ``"gif"``."""
    width: float | None
    """Intrinsic width in points, or ``None`` when the file declares none."""
    height: float | None
    markup: str = ""
    """Sanitized, id-prefixed ``<svg>`` markup (SVG artwork only)."""
    stamp: int = 0
    """When the file last changed (nanoseconds): its bytes are read only when wanted."""
    upright: bool = False
    """A JPEG to be redrawn before it is placed: turned by its EXIF orientation (a phone
    photograph), or in CMYK, which a drawing's viewers show wrong or black."""

    @property
    def data_uri(self) -> str:
        """Base64 ``data:`` URI of the bytes (PNG, JPEG and GIF artwork only): the file's
        own -- a GIF's every frame -- or, for a turned or CMYK JPEG, the photograph upright
        and in RGB."""

        if self.format not in PHOTOGRAPHS:
            return ""
        if self.upright:
            return _upright_uri(str(self.path), self.stamp)
        return _data_uri(str(self.path), self.stamp, self.format)

    @property
    def aspect(self) -> float | None:
        """Intrinsic width over height, or ``None`` when the file declares none."""

        if self.width is None or self.height is None or self.height <= 0.0:
            return None
        return self.width / self.height


PHOTOGRAPHS = frozenset({"png", "jpeg", "gif"})
"""The formats carried as their own bytes, a photograph's: not drawn as vectors."""


picture_link: ContextVar[Callable[[Artwork], str] | None] = ContextVar(
    "flexo_picture_link", default=None
)
"""How a drawing names a photograph instead of carrying its bytes: the studio, drawing for
its page, names it by an address the page loads once. Exports carry the bytes."""


def picture_href(artwork: Artwork) -> str:
    """What a drawing's ``<image href>`` says for a photograph: an address, while the
    studio draws for its page, and the photograph itself otherwise."""

    link = picture_link.get()
    if link is not None and artwork.format in PHOTOGRAPHS:
        return link(artwork)
    return artwork.data_uri


@lru_cache(maxsize=8)
def _upright_uri(resolved: str, stamp: int) -> str:
    try:
        from PIL import Image, ImageOps
    except ImportError:  # Pillow is optional: without it, the photograph as it is
        return _data_uri(resolved, stamp, "jpeg")
    from io import BytesIO

    with Image.open(resolved) as image:
        turned = ImageOps.exif_transpose(image).convert("RGB")
    buffer = BytesIO()
    turned.save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _jpeg_orientation(segment: bytes) -> int:
    """The EXIF orientation (1 to 8) an APP1 segment holds, or 1."""

    if not segment.startswith(b"Exif\x00\x00") or len(segment) < 14:
        return 1
    tiff = segment[6:]
    order = "<" if tiff[:2] == b"II" else ">"
    try:
        (offset,) = struct.unpack(order + "I", tiff[4:8])
        (count,) = struct.unpack(order + "H", tiff[offset : offset + 2])
        for entry in range(count):
            at = offset + 2 + entry * 12
            tag, kind, _, value = struct.unpack(order + "HHI4s", tiff[at : at + 12])
            if tag == 0x0112 and kind == 3:
                (orientation,) = struct.unpack(order + "H", value[:2])
                return orientation if 1 <= orientation <= 8 else 1
    except struct.error:
        return 1
    return 1


@lru_cache(maxsize=8)
def _data_uri(resolved: str, stamp: int, format: str) -> str:
    encoded = base64.b64encode(Path(resolved).read_bytes()).decode("ascii")
    return f"data:image/{format};base64,{encoded}"


CROP_SIDES = ("crop_left", "crop_top", "crop_right", "crop_bottom")
"""An image's properties that trim its artwork: how much of it is cut off each side, in
hundredths of its width (left, right) or height (top, bottom)."""


def crop_of(spec: NodeSpec) -> tuple[float, float, float, float] | None:
    """The part of an image's artwork that is kept -- x, y, width and height as fractions
    of it -- from what its properties trim off each side (``CROP_SIDES``): ``None`` for
    all of it. At least a twentieth is kept each way, whatever is asked."""

    def trimmed(name: str) -> float:
        try:
            return min(max(float(spec.property(name, 0) or 0), 0.0), 95.0) / 100.0
        except (TypeError, ValueError):
            return 0.0

    left, top, right, bottom = (trimmed(name) for name in CROP_SIDES)
    if not (left or top or right or bottom):
        return None
    width, height = max(1.0 - left - right, 0.05), max(1.0 - top - bottom, 0.05)
    return (min(left, 1.0 - width), min(top, 1.0 - height), width, height)


def node_artwork(spec: NodeSpec) -> Artwork:
    """The artwork an ``image`` node names, loaded and sanitized.

    Called from measurement *and* from rendering, so the result is cached on the
    file's path and mtime: one parse per file per compile, and a file edited
    between two compiles in the same process is picked up rather than stale.
    """

    source = spec.property("source")
    if source is None or not str(source).strip():
        raise FlexoError(
            Diagnostic(
                "image.source.missing",
                "An image component needs a source file.",
                entity_id=spec.id,
                hint='Write image("<id>", "<path to .svg or .png>").',
            )
        )
    return load_artwork(spec.id, str(source))


def load_artwork(node_id: str, source: str) -> Artwork:
    """Load ``source`` for ``node_id``. Relative paths resolve against the cwd."""

    path, page = _page_of(Path(source).expanduser())
    suffix = path.suffix.lower()
    if suffix not in SVG_SUFFIXES | RASTER_SUFFIXES | PAGE_SUFFIXES:
        raise _error(
            "image.source.unsupported",
            node_id,
            path,
            f'Unsupported artwork format "{suffix or path.name}".',
            hint="Embed an .svg, .pdf or Illustrator (.ai) file for vector artwork, "
            "a .png, .jpg, .webp, .tiff or .heic file for a photograph, or a .gif for one "
            "that plays.",
        )
    if outside(path):
        raise _error(
            "image.source.outside",
            node_id,
            path,
            "The artwork file is outside the folder.",
            hint="Put it in the folder, beside the figure.",
        )
    try:
        stat = path.stat()
    except OSError as exc:
        raise _error(
            "image.source.unreadable",
            node_id,
            path,
            f"Cannot read the artwork file ({exc.strerror or exc}).",
            hint="Absolute paths are the reliable choice; relative ones resolve "
            "against the working directory the figure is compiled in.",
        ) from exc
    if suffix in PAGE_SUFFIXES:
        return _page_artwork(node_id, str(path.resolve()), page, stat.st_mtime_ns)
    return _load(node_id, str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _page_of(path: Path) -> tuple[Path, int]:
    """A PDF or Illustrator file and the page (artboard) of it named: ``art.ai#2`` is the
    second artboard -- unless a file is called that."""

    name, mark, number = path.name.rpartition("#")
    if mark and number.isdigit() and int(number) >= 1 and not path.exists():
        whole = path.with_name(name)
        if whole.suffix.lower() in PAGE_SUFFIXES:
            return whole, int(number)
    return path, 1


@lru_cache(maxsize=32)
def _page_artwork(node_id: str, resolved: str, page: int, stamp: int) -> Artwork:
    """A PDF's page, or an Illustrator file's artboard, as SVG artwork: its shapes and
    words as vectors, what SVG cannot draw as it does as pictures (``flexo.pdfart``)."""

    from flexo.pdfart import PdfArtError, is_pdf, read_page

    path = Path(resolved)
    try:
        with path.open("rb") as handle:
            head = handle.read(1024)
    except OSError as exc:
        raise _error(
            "image.source.unreadable",
            node_id,
            path,
            f"Cannot read the artwork file ({exc.strerror or exc}).",
        ) from exc
    if not is_pdf(head):
        if path.suffix.lower() == ".ai":
            raise _error(
                "image.ai.private",
                node_id,
                path,
                "This Illustrator file was saved without its PDF, so only Illustrator can read it.",
                hint='In Illustrator, choose File > Save As and tick "Create PDF Compatible File" '
                "(or export the artboard as SVG or PDF).",
            )
        raise _error("image.pdf.invalid", node_id, path, "The file does not begin as a PDF does.")
    try:
        # An Illustrator file shows its art, as Illustrator exports it; a PDF, its page.
        art = read_page(resolved, page, stamp, art=path.suffix.lower() == ".ai")
    except PdfArtError as exc:
        raise _error("image.pdf.unreadable", node_id, path, str(exc), hint=exc.hint) from None
    return _svg_artwork(node_id, path, art.markup.encode("utf-8"))


HEADER = 1 << 20
"""Bytes of a photograph read to find its size: its header, and space for the metadata a
camera writes before a JPEG's frame."""


@lru_cache(maxsize=128)
def _load(node_id: str, resolved: str, mtime_ns: int, size: int) -> Artwork:
    path = Path(resolved)
    raster = path.suffix.lower() in RASTER_SUFFIXES
    try:
        if raster:
            with path.open("rb") as handle:
                data = handle.read(HEADER)
        else:
            data = path.read_bytes()
    except OSError as exc:
        raise _error(
            "image.source.unreadable",
            node_id,
            path,
            f"Cannot read the artwork file ({exc.strerror or exc}).",
        ) from exc
    if not raster:
        return _svg_artwork(node_id, path, data)
    # What the bytes are, whatever the name says: a browser shows a PNG named .jpg, and so
    # does the slide.
    kind = _sniffed(data)
    if kind == "png":
        return _png_artwork(node_id, path, data, mtime_ns)
    if kind == "jpeg":
        return _jpeg_artwork(node_id, path, data, mtime_ns)
    if kind == "gif":
        return _gif_artwork(node_id, path, data, mtime_ns)
    if kind is not None:
        made = _converted(node_id, path, kind, mtime_ns, size)
        with made.open("rb") as handle:
            return _png_artwork(node_id, made, handle.read(HEADER), mtime_ns)
    raise _error(
        "image.source.unknown",
        node_id,
        path,
        "The file is not a picture: its bytes are none of PNG, JPEG, GIF, WebP, TIFF, BMP, "
        "HEIC or AVIF.",
        hint="Open it in Preview and choose File > Export as PNG or JPEG.",
    )


def _sniffed(data: bytes) -> str | None:
    """What a photograph's bytes are: ``png``, ``jpeg``, ``gif``, ``webp``, ``tiff``,
    ``bmp``, ``heic`` or ``avif`` -- or None, if none of them."""

    if data.startswith(_PNG_SIGNATURE):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:2] == b"BM":
        return "bmp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "heic"
    return None


def _converted(node_id: str, path: Path, kind: str, mtime_ns: int, size: int) -> Path:
    """A WebP, TIFF, BMP, HEIC or AVIF made the PNG it is placed as, once for each version of
    the file, in the cache (``pdfart``'s, beside its pages): with Pillow, and, for a phone's
    HEIC that Pillow cannot read, with the Mac's own ``sips``."""

    import hashlib
    import shutil
    import subprocess

    from flexo.pdfart import _cache_folder

    key = hashlib.sha256(f"{path}|{mtime_ns}|{size}".encode()).hexdigest()[:32]
    folder = _cache_folder() / "pictures"
    made = folder / f"{key}.png"
    if made.is_file():
        return made
    folder.mkdir(parents=True, exist_ok=True)
    partial = made.with_suffix(".partial.png")
    problem = ""
    try:
        from PIL import Image

        with Image.open(path) as picture:
            picture.seek(0)
            clear = picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info
            picture.convert("RGBA" if clear else "RGB").save(partial, "PNG")
        partial.replace(made)
        return made
    except Exception as exc:  # Pillow missing, or not reading this kind
        problem = str(exc)
    sips = shutil.which("sips")
    if sips is not None:
        done = subprocess.run(
            [sips, "-s", "format", "png", str(path), "--out", str(partial)],
            capture_output=True,
            check=False,
        )
        if done.returncode == 0 and partial.is_file():
            partial.replace(made)
            return made
        problem = done.stderr.decode(errors="replace").strip() or problem
    raise _error(
        "image.source.unconverted",
        node_id,
        path,
        f"The {kind.upper()} picture could not be read{f' ({problem})' if problem else ''}.",
        hint="Open it in Preview and choose File > Export as PNG or JPEG.",
    )


def _png_artwork(node_id: str, path: Path, data: bytes, stamp: int = 0) -> Artwork:
    """A PNG travels as its own bytes; only its pixel size is read out."""

    if not data.startswith(_PNG_SIGNATURE) or len(data) < 24 or data[12:16] != b"IHDR":
        raise _error(
            "image.png.invalid",
            node_id,
            path,
            "The file does not begin with a PNG header.",
        )
    pixel_width, pixel_height = struct.unpack(">II", data[16:24])
    # A PNG pixel is a CSS pixel, which is the unit "px" already means.
    scale = POINTS_PER_UNIT["px"]
    return Artwork(
        node_id,
        path,
        "png",
        float(pixel_width) * scale,
        float(pixel_height) * scale,
        stamp=stamp,
    )


def _gif_artwork(node_id: str, path: Path, data: bytes, stamp: int = 0) -> Artwork:
    """A GIF travels as its own bytes, every frame of it, like a PNG; its size is its
    logical screen's, which every frame is drawn on."""

    from flexo.animated import gif_size

    size = gif_size(data)
    if size is None or not all(size):
        raise _error(
            "image.gif.invalid",
            node_id,
            path,
            "The file does not begin with a GIF header.",
        )
    scale = POINTS_PER_UNIT["px"]
    return Artwork(
        node_id, path, "gif", float(size[0]) * scale, float(size[1]) * scale, stamp=stamp
    )


def _jpeg_artwork(node_id: str, path: Path, data: bytes, stamp: int = 0) -> Artwork:
    """A JPEG travels as its own bytes, like a PNG; its size is read from its frame header."""

    index = 2
    size: tuple[int, int] | None = None
    orientation, components = 1, 3
    while data.startswith(b"\xff\xd8") and index + 9 < len(data):
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if marker == 0xE1 and orientation == 1:
            orientation = _jpeg_orientation(data[index + 4 : index + 2 + length])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            components = data[index + 9]
            size = (width, height)
            break
        index += 2 + length
    if size is None:
        raise _error("image.jpeg.invalid", node_id, path, "The file is not a readable JPEG.")
    if orientation >= 5:  # turned a quarter: it stands the other way up
        size = (size[1], size[0])
    scale = POINTS_PER_UNIT["px"]
    return Artwork(
        node_id,
        path,
        "jpeg",
        float(size[0]) * scale,
        float(size[1]) * scale,
        stamp=stamp,
        upright=orientation != 1 or components == 4,
    )


def _svg_artwork(node_id: str, path: Path, data: bytes) -> Artwork:
    text = data.decode("utf-8", errors="replace")
    # Strip before parsing, not after: the declaration and the DOCTYPE are the
    # two places an SVG can carry instructions to the *parser* -- an encoding
    # this loader has already decided, and entity definitions that could expand
    # into anything at all -- and neither survives into the figure regardless.
    text = _XML_DECLARATION.sub("", text, count=1)
    text = _DOCTYPE.sub("", text)
    text = _COMMENT.sub("", text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise _error(
            "image.svg.invalid",
            node_id,
            path,
            f"The file is not well-formed XML ({exc}).",
        ) from exc
    if local_name(root.tag) != "svg":
        raise _error(
            "image.svg.invalid",
            node_id,
            path,
            f'The document element is <{local_name(root.tag)}>, not <svg>.',
        )
    _sanitize(node_id, path, root)
    _prefix_identifiers(node_id, root)
    width, height, view_box = _svg_intrinsic_size(root)
    if view_box is None and width is not None and height is not None:
        # No viewBox, but a declared size: the user units *are* the declared
        # size, so saying so is what lets the nested viewport scale at all.
        root.set("viewBox", f"0 0 {width / _ABSOLUTE_UNITS['px']} {height / _ABSOLUTE_UNITS['px']}")
    return Artwork(
        node_id,
        path,
        "svg",
        width,
        height,
        markup=ET.tostring(root, encoding="unicode", short_empty_elements=True),
    )


def _sanitize(node_id: str, path: Path, root: ET.Element) -> None:
    """Reject artwork that would do more than draw.

    Rejection, not silent removal: an author who exported a drawing with a
    script or a linked bitmap in it has a drawing that would not survive
    embedding, and the useful moment to learn that is now.
    """

    for item in root.iter():
        if local_name(item.tag) == "script":
            raise _error(
                "image.svg.script",
                node_id,
                path,
                "The artwork contains a <script> element.",
                hint="Export the drawing without interactivity.",
            )
        for name, value in item.attrib.items():
            local = local_name(name).lower()
            if local.startswith("on"):
                raise _error(
                    "image.svg.event-handler",
                    node_id,
                    path,
                    f'The artwork carries the event handler "{local}".',
                    hint="Export the drawing without interactivity.",
                )
            if local in {"href", "src"}:
                _require_internal(node_id, path, value)
            for match in _URL_REFERENCE.finditer(value):
                _require_internal(node_id, path, match.group(1))
        if local_name(item.tag) == "style" and item.text:
            if _CSS_IMPORT.search(item.text):
                raise _error(
                    "image.svg.external-reference",
                    node_id,
                    path,
                    "The artwork's stylesheet imports an external stylesheet.",
                )
            for match in _URL_REFERENCE.finditer(item.text):
                _require_internal(node_id, path, match.group(1))


_EMBEDDED_FONT = re.compile(
    r"data:(font/|application/(x-)?font|application/vnd\.ms-opentype|application/octet-stream)",
    re.IGNORECASE,
)
"""A font carried in the file itself (an ``@font-face`` source), as Flexo's own SVGs carry
theirs: as self-contained as an inlined bitmap."""


def _require_internal(node_id: str, path: Path, reference: str) -> None:
    value = reference.strip().strip("'\"")
    if value.startswith("#") or value.startswith("data:image/") or _EMBEDDED_FONT.match(value):
        return
    raise _error(
        "image.svg.external-reference",
        node_id,
        path,
        f'The artwork references "{value[:80]}" outside itself.',
        hint="Embedded artwork must be self-contained: keep #fragment references "
        "to its own defs, and inline any linked bitmap as a data: URI.",
    )


def _prefix_identifiers(node_id: str, root: ET.Element) -> None:
    """Rename every id under the node that owns the artwork, references and all.

    Two copies of one icon, or one icon beside a figure that already uses the
    id ``gradient``, would otherwise share a definition and paint each other.
    """

    mapping = {
        item.get("id", ""): f"{node_id}.{item.get('id', '')}"
        for item in root.iter()
        if item.get("id")
    }
    if not mapping:
        return

    def rewrite(value: str) -> str:
        return _FRAGMENT.sub(
            lambda match: f"#{mapping[match.group(1)]}"
            if match.group(1) in mapping
            else match.group(0),
            value,
        )

    for item in root.iter():
        for name, value in tuple(item.attrib.items()):
            if local_name(name) == "id":
                item.set(name, mapping.get(value, value))
            else:
                item.set(name, rewrite(value))
        if local_name(item.tag) == "style" and item.text:
            item.text = rewrite(item.text)


def _svg_intrinsic_size(root: ET.Element) -> tuple[float | None, float | None, str | None]:
    """The artwork's own size in points, plus its viewBox if it declares one.

    A declared ``width``/``height`` wins because it is the size the author drew
    the file at; the viewBox is the fallback, read as CSS pixels, which is the
    same convention a browser applies to an unsized SVG.
    """

    view_box = root.get("viewBox")
    width = _svg_length(root.get("width"))
    height = _svg_length(root.get("height"))
    if (width is None or height is None) and view_box is not None:
        numbers = [
            value for value in re.split(r"[,\s]+", view_box.strip()) if value
        ]
        if len(numbers) == 4:
            try:
                box_width, box_height = float(numbers[2]), float(numbers[3])
            except ValueError:
                return width, height, view_box
            scale = _ABSOLUTE_UNITS["px"]
            if width is None and box_width > 0.0:
                width = box_width * scale
            if height is None and box_height > 0.0:
                height = box_height * scale
    return width, height, view_box


def _svg_length(value: str | None) -> float | None:
    if value is None:
        return None
    match = _SVG_LENGTH.match(value)
    if match is None:
        return None
    amount, unit = match.groups()
    factor = _ABSOLUTE_UNITS.get(unit or "px")
    if factor is None:
        return None
    result = float(amount) * factor
    return result if result > 0.0 else None


def _error(
    code: str,
    node_id: str,
    path: Path,
    message: str,
    *,
    hint: str | None = None,
) -> FlexoError:
    return FlexoError(
        Diagnostic(code, f"{message} Source: {path}.", entity_id=node_id, hint=hint)
    )
