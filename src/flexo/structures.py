"""A molecule drawn by hand: a structure rendered by mol-sketch, in the figure's colours.

A ``structure`` component draws a PDB or mmCIF file (or a PDB ID, fetched) with
`mol-sketch <https://github.com/jamaliki/mol-sketch>`_ -- engraved ribbons,
watercolour, pen and ink -- as a panel of the figure:

- its **look** follows the theme unless one is named: watercolour in a sketched
  theme, dark paper on a dark page, engraved colour otherwise;
- it is drawn on the figure's own page colour, which is then taken out, so the
  molecule sits on whatever is behind it with no box round it;
- ``colors`` names a colour for a chain (``"A"``), a residue (``"SER195"``), a
  subunit or an entity -- a hex colour, or one of the figure's **tones**, so the
  kinase domain on the protein map and the chain in the structure are one colour;
- ``yaw``, ``pitch``, ``roll``, and ``zoom`` turn and frame it; ``cartoon``,
  ``sticks``, and ``surface`` say what to draw (mol-sketch selections), and
  ``site`` marks an active site.

mol-sketch is an optional dependency (``pip install "flexo[molecules]"``, or the
``python`` folder of a mol-sketch clone). The picture is drawn at print
resolution and embedded, so the editable SVG, the PDF, and the slides carry it.
"""

from __future__ import annotations

import functools
import struct
import zlib
from pathlib import Path

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Words, units
from flexo.geometry import Side, Size
from flexo.ir.semantic import NodeSpec, PortSpec, Record
from flexo.style import LayoutStyle, Palette

LOOKS = (
    "engraved-colour",
    "engraved",
    "watercolour",
    "ink-colour",
    "ink",
    "dark-paper",
    "chalkboard",
    "assembly-cartoon",
    "assembly-surface",
)


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"structure.{code}", message, entity_id=node.id, hint=hint))


def _colours(node: NodeSpec) -> tuple[tuple[str, str], ...]:
    value = node.property("colors")
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(node, "colors", '"colors" is a list of {group, color} mappings.')
    pairs = []
    for record in value:
        assert isinstance(record, Record)
        group, colour = record.get("group"), record.get("color")
        if group is None or colour is None:
            raise _fail(
                node,
                "colors",
                "each colour names a group and a color.",
                hint='Write colors: [{group: A, color: Kinase}] (a tone) or color: "#3366aa".',
            )
        pairs.append((str(group), str(colour)))
    return tuple(pairs)


def structure_tones(node: NodeSpec) -> tuple[str, ...]:
    """The figure tones a structure's colours name (a colour written ``#rrggbb`` is none)."""

    return tuple(
        dict.fromkeys(colour for _, colour in _colours(node) if not colour.startswith("#"))
    )


def structure_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    """The panel: the molecule's box, under the component's name if it has one."""

    measures = units(style)
    u = measures.u
    width = float(node.property("width") or 20.0 * u)  # type: ignore[arg-type]
    height = float(node.property("height") or 15.0 * u)  # type: ignore[arg-type]
    words = []
    top = 0.0
    if node.label:
        title = measures.measure(node.label, weight=style.typography.title_weight)
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                width / 2.0,
                title.baseline,
                weight=style.typography.title_weight,
            )
        )
        top = title.height + 0.3 * u
    size = Size(width, top + height)
    middle = (top + height / 2.0) / size.height
    return Picture(
        size,
        (),
        tuple(words),
        (PortSpec("input", Side.WEST, middle), PortSpec("output", Side.EAST, middle)),
        images=((f"{node.id}.molecule", 0.0, top, width, height),),
    )


def structure_png(
    node: NodeSpec, style: LayoutStyle, palette: Palette, width: float, height: float
) -> bytes:
    """The molecule, drawn by mol-sketch at ``width`` by ``height`` points, as a PNG with
    the page taken out."""

    source = node.property("source")
    if not isinstance(source, str) or not source.strip():
        raise _fail(node, "source", "A structure needs a file or a PDB ID (source:).")
    look = str(node.property("look") or _theme_look(style, palette)).strip().lower()
    if look not in LOOKS:
        raise _fail(node, "look", f'look "{look}" is not a mol-sketch look.', hint=", ".join(LOOKS))
    paper = palette.get("canvas", "#ffffff")
    colours = []
    for group, colour in _colours(node):
        if not colour.startswith("#"):
            index = palette.tone_index(colour)
            if index is None:
                raise _fail(
                    node, "colors", f'"{colour}" is neither a colour nor a tone of the figure.'
                )
            colour = palette.get(f"tone-{index}-stroke")
        colours.append((group, colour))
    view = tuple(
        (name, float(value))  # type: ignore[arg-type]
        for name in ("yaw", "pitch", "roll", "zoom")
        if (value := node.property(name)) is not None
    )
    show = tuple(
        (name, str(value))
        for name in ("cartoon", "sticks", "surface")
        if (value := node.property(name)) is not None
    )
    site = node.property("site")
    # The figure's own colours where it has them: its ink, and -- when a protein map
    # in the figure draws helices and strands -- theirs, so the two agree.
    roles = [("ink", palette.get("ink", "#000000"))]
    for tone, key in (("helix", "helix"), ("strand", "sheet")):
        index = palette.tone_index(tone)
        if index is not None:
            roles.append((key, palette.get(f"tone-{index}-stroke")))
    path = Path(source).expanduser()
    stamp = path.stat().st_mtime if path.exists() else 0.0
    try:
        return _render(
            str(path) if path.exists() else source.strip(),
            stamp,
            look,
            paper,
            tuple(colours),
            view,
            show,
            None if site is None else str(site),
            tuple(roles),
            width / height,
        )
    except ImportError:
        raise _fail(
            node,
            "molsketch",
            "Drawing a structure needs mol-sketch.",
            hint='pip install "flexo[molecules]", or pip install path/to/mol-sketch/python.',
        ) from None


def _theme_look(style: LayoutStyle, palette: Palette) -> str:
    if style.sketch is not None:
        return "watercolour"
    if _lightness(palette.get("canvas", "#ffffff")) < 0.4:
        return "dark-paper"
    return "engraved-colour"


def _lightness(colour: str) -> float:
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        r, g, b = (int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@functools.lru_cache(maxsize=32)
def _render(
    source: str,
    stamp: float,
    look: str,
    paper: str,
    colours: tuple[tuple[str, str], ...],
    view: tuple[tuple[str, float], ...],
    show: tuple[tuple[str, str], ...],
    site: str | None,
    roles: tuple[tuple[str, str], ...],
    aspect: float,
) -> bytes:
    import molsketch as ms

    del stamp  # part of the cache key: an edited file draws again
    figure = ms.load(source) if Path(source).exists() else ms.fetch(source)
    figure = figure.look(look)
    figure.set(
        palette={"paper": paper, **dict(roles)},
        # A scene's own captions and step labels are the app's; the figure names
        # the panel itself.
        **{"paper.grain": 0, "paper.wash": 0, "show.caption": False, "show.step_label": False},
    )
    for group, colour in colours:
        figure.color(group, colour)
    if show:
        figure.show(**dict(show))
    if view:
        figure.view(**dict(view))
    if site:
        figure.site(site)
    # mol-sketch's pen is sized for its own canvas (1920 wide): drawn at that
    # scale and shrunk into the box, the lines keep their weight against the molecule.
    long_side = 1200
    size = (
        (long_side, round(long_side / aspect))
        if aspect >= 1
        else (round(long_side * aspect), long_side)
    )
    image = figure.render(size, scale=1.0)
    pixels = image.to_numpy()
    return _png(_without_paper(pixels, paper))


def _without_paper(pixels, paper: str):
    """``pixels`` (RGBA) with the paper colour taken out, as GIMP's colour to alpha does:
    each pixel keeps the least opacity that, laid over the paper, gives it back."""

    import numpy as np

    text = paper.lstrip("#")
    ground = np.array([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0
    colour = pixels[..., :3].astype(np.float64) / 255.0
    lighter = np.where(colour > ground, (colour - ground) / np.maximum(1.0 - ground, 1e-6), 0.0)
    darker = np.where(colour < ground, (ground - colour) / np.maximum(ground, 1e-6), 0.0)
    alpha = np.clip(np.max(np.maximum(lighter, darker), axis=-1), 0.0, 1.0)
    safe = np.maximum(alpha, 1e-6)[..., None]
    restored = np.clip((colour - ground) / safe + ground, 0.0, 1.0)
    alpha = alpha * (pixels[..., 3].astype(np.float64) / 255.0)
    out = np.empty(pixels.shape, dtype=np.uint8)
    out[..., :3] = np.round(restored * 255.0)
    out[..., 3] = np.round(alpha * 255.0)
    return out


def _png(pixels) -> bytes:
    """An RGBA array as PNG bytes."""

    height, width = pixels.shape[:2]
    rows = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )
