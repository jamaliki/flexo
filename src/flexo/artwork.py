"""Author-supplied artwork: load, sanitize, and size an embedded SVG or PNG.

An ``image`` component carries no compiler-drawn ink. It carries a file the
author drew -- a molecule icon, a density-map view -- and Flexo's whole job is
to put that file into the figure *without* redrawing it: an SVG arrives as
vector content nested at the node's bounds, a PNG as a data URI, and both travel
inside the editable and portable SVG with no companion file to lose.

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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.ir.semantic import NodeSpec
from flexo.svg import local_name
from flexo.units import NUMBER_PATTERN, POINTS_PER_UNIT

SVG_SUFFIXES = frozenset({".svg"})
PNG_SUFFIXES = frozenset({".png"})

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
    """``"svg"`` or ``"png"``."""
    width: float | None
    """Intrinsic width in points, or ``None`` when the file declares none."""
    height: float | None
    markup: str = ""
    """Sanitized, id-prefixed ``<svg>`` markup (SVG artwork only)."""
    data_uri: str = ""
    """Base64 ``data:`` URI of the original bytes (PNG artwork only)."""

    @property
    def aspect(self) -> float | None:
        """Intrinsic width over height, or ``None`` when the file declares none."""

        if self.width is None or self.height is None or self.height <= 0.0:
            return None
        return self.width / self.height


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

    path = Path(source).expanduser()
    suffix = path.suffix.lower()
    if suffix not in SVG_SUFFIXES | PNG_SUFFIXES:
        raise _error(
            "image.source.unsupported",
            node_id,
            path,
            f'Unsupported artwork format "{suffix or path.name}".',
            hint="Embed an .svg file for vector artwork or a .png file for a render.",
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
    return _load(node_id, str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=128)
def _load(node_id: str, resolved: str, mtime_ns: int, size: int) -> Artwork:
    path = Path(resolved)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise _error(
            "image.source.unreadable",
            node_id,
            path,
            f"Cannot read the artwork file ({exc.strerror or exc}).",
        ) from exc
    if path.suffix.lower() in PNG_SUFFIXES:
        return _png_artwork(node_id, path, data)
    return _svg_artwork(node_id, path, data)


def _png_artwork(node_id: str, path: Path, data: bytes) -> Artwork:
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
    encoded = base64.b64encode(data).decode("ascii")
    return Artwork(
        node_id,
        path,
        "png",
        float(pixel_width) * scale,
        float(pixel_height) * scale,
        data_uri=f"data:image/png;base64,{encoded}",
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


def _require_internal(node_id: str, path: Path, reference: str) -> None:
    value = reference.strip()
    if value.startswith("#") or value.startswith("data:image/"):
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
