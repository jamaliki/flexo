"""A structure's part the size of its molecule as drawn: lines meet the molecule.

mol-sketch frames a molecule in the canvas it is drawn in with room to spare -- a tenth of
the width, 24 pixels of the height, an ångström or so round the atoms it fits on -- and,
where the box's proportions are not the molecule's, the rest of the box is empty too. A
part's lines end at its box, so they stopped well short of the molecule, and the figure kept
room round it for nothing.

So a structure is drawn as it always was -- by mol-sketch, in a canvas of its ``width`` by
``height``, at the same scale -- and its part is then the molecule's drawn extent, with a
small pad round it (``PAD``):

- ``width`` and ``height`` are the most it may take. Given only one, the other follows the
  molecule's proportions at its view (``proportioned``): a long molecule seen end on is not
  drawn in a box as wide as it is long;
- the drawing is cropped to the part: a flat molecule's nested ``<svg>`` by its viewBox, a
  molecule drawn as a picture by its pixels. The studio chooses, sizes and turns it by that
  box, and the canvas it was drawn in is said on it (``data-flexo-canvas``), so that a corner
  dragged sizes the canvas -- the molecule grows as the box does -- and a molecule turned is
  framed in the canvas it will be drawn in;
- structures that share a frame (``flexo.structure_frames``) are cropped alike, to what they
  all draw together about the frame's one centre: still one scale and one centre, and boxes
  of one size where their canvases are of one size.

The extent is read off the drawing made anyway -- drawn here, before the figure is laid out,
and kept for when it is painted (``flexo.structures``) -- so it costs no drawing of its own:
the SVG's ink (``flexo.drawing.ink_bounds``), or the picture's opaque pixels. It is found once
for each drawing (``drawn_extent``) and kept, in memory and on disk beside the drawing
(``flexo.structure_kept``): a figure laid out every way it could be, again and again as it is
changed, and opened again another day, never reads a molecule's drawing again to measure it.
"""

from __future__ import annotations

import functools
import math
import struct
import zlib
from dataclasses import replace

from flexo.ir.semantic import FigureSpec, NodeSpec, Settings
from flexo.style import LayoutStyle, Palette

PAD = 0.15
"""The room kept round a molecule's drawn extent, in label sizes: a line's head stops this
short of it."""

FITTED = "drawn_in"
"""The property a structure laid out round its molecule carries (``hugged``): the canvas it is
drawn in (``box``: width and height, in points) and the part of it shown (``crop``: left, top,
right and bottom, as shares of the canvas)."""

OPAQUE = 8
"""The least opacity (of 255) a pixel of a molecule drawn as a picture is counted at: under
it, specks left of the paper taken out."""


Crop = tuple[float, float, float, float]


def drawn_in(node: NodeSpec) -> tuple[tuple[float, float], Crop] | None:
    """The canvas ``node`` is drawn in (width and height, points) and the part of it its box
    shows (shares of the canvas: left, top, right, bottom) -- or None, for one drawn whole in
    its box."""

    fitted = node.property(FITTED)
    if not isinstance(fitted, Settings):
        return None
    box, crop = fitted.get("box"), fitted.get("crop")
    if not isinstance(box, tuple) or not isinstance(crop, tuple) or len(box) != 2 or len(crop) != 4:
        return None
    return (float(box[0]), float(box[1])), tuple(float(value) for value in crop)  # type: ignore[return-value]


def measured_as_drawn(spec: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``spec`` with its structures sized as compiling it sizes them -- framed, and laid out
    round their molecules -- for a figure measured without being compiled (``flexo.boxfit``'s
    estimates). The drawings are those compiling it makes, and keeps."""

    if not any(node.kind == "structure" for node in spec.nodes):
        return spec
    from flexo.structure_frames import framed
    from flexo.themes import figure_palette

    return hugged(framed(proportioned(spec, style), style), style, figure_palette(spec))


# -- one size given: the other follows the molecule --


def proportioned(spec: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``spec`` with each structure given only a ``width`` or only a ``height`` given the other
    too: as the molecule is proportioned at its view, so that mol-sketch's framing is as tight
    one way as the other. One that can't be drawn keeps the usual for the other."""

    nodes, changed = [], False
    for node in spec.nodes:
        given = [node.property(name) is not None for name in ("width", "height")]
        if node.kind == "structure" and sum(given) == 1:
            aspect = _aspect(node, style)
            if aspect is not None:
                if given[0]:
                    size = ("height", round(float(node.property("width")) / aspect, 3))  # type: ignore[arg-type]
                else:
                    size = ("width", round(float(node.property("height")) * aspect, 3))  # type: ignore[arg-type]
                node = replace(node, properties=(*node.properties, size))
                changed = True
        nodes.append(node)
    return replace(spec, nodes=tuple(nodes)) if changed else spec


def _aspect(node: NodeSpec, style: LayoutStyle) -> float | None:
    """The width to height of the canvas mol-sketch fits ``node``'s molecule as tightly across
    as up and down, at its turn: its ``computeFit`` and ``makeProjector`` solved for the canvas
    (``flexo.structure_frames``)."""

    import numpy as np

    from flexo.structure_frames import LONG_SIDE, _geometry_of, _owner_camera, turned

    held = _geometry_of(node, style)
    if held is None:
        return None
    ask, geometry = held
    camera = _owner_camera(ask, geometry)
    seen = np.asarray(geometry.points) @ (
        turned(camera["yaw"], camera["pitch"], camera["roll"]) @ geometry.seen
    ).T
    across, up = np.maximum(seen.max(axis=0) - seen.min(axis=0), 1.0)[:2]
    ratio = (float(up) + 2.4) / (float(across) + 2.6)
    wide = LONG_SIDE / (24 + 0.9 * LONG_SIDE * ratio)
    return wide if wide >= 1 else (LONG_SIDE - 24) / (0.9 * LONG_SIDE * ratio)


# -- the part round the molecule --


def hugged(spec: FigureSpec, style: LayoutStyle, palette: Palette) -> FigureSpec:
    """``spec`` with each structure that is drawn laid out round its molecule: its ``width``
    and ``height`` those of its drawn extent with ``PAD`` round it, and the canvas it is drawn
    in and the part of it shown kept on it (``FITTED``). Those that share a frame are cropped
    alike about its centre. One that can't be drawn -- a panel saying why -- keeps its box."""

    from flexo.drawn import units
    from flexo.structure_frames import _box, frames_of

    structures = [node for node in spec.nodes if node.kind == "structure"]
    if not structures:
        return spec
    pad = PAD * units(style).u
    # Each one's drawn extent, in points from the middle of its box.
    found: dict[str, tuple[tuple[float, float], tuple[float, ...], tuple[float, float]]] = {}
    for node in structures:
        box = _box(node, style)
        extent = _extent(node, style, palette, box)
        if extent is not None:
            found[node.id] = (box, *extent)
    # A frame's, what they all draw together: one centre, one crop.
    for members in frames_of(spec).values():
        held = [node.id for node in members if node.id in found]
        if len(held) < 2:
            continue
        together = tuple(
            (min if side < 2 else max)(found[identifier][1][side] for identifier in held)
            for side in range(4)
        )
        for identifier in held:
            box, _, canvas = found[identifier]
            found[identifier] = (box, together, canvas)
    if not found:
        return spec
    nodes = []
    for node in spec.nodes:
        if node.id in found:
            node = _fitted(node, *found[node.id], pad)
        nodes.append(node)
    return replace(spec, nodes=tuple(nodes))


def _fitted(node: NodeSpec, box: tuple[float, float], extent: tuple[float, ...],
            canvas: tuple[float, float], pad: float) -> NodeSpec:
    """``node`` sized to ``extent`` (points from its box's middle) and ``pad`` round it: the part
    of its canvas (``canvas``, pixels, drawn centred and as large as fits in ``box``) that shows,
    in whole pixels."""

    width, height = box
    pixels_w, pixels_h = canvas
    scale = min(width / pixels_w, height / pixels_h)  # points to a pixel
    left, top, right, bottom = (
        math.floor(max((extent[0] - pad) / scale + pixels_w / 2, 0.0)),
        math.floor(max((extent[1] - pad) / scale + pixels_h / 2, 0.0)),
        math.ceil(min((extent[2] + pad) / scale + pixels_w / 2, pixels_w)),
        math.ceil(min((extent[3] + pad) / scale + pixels_h / 2, pixels_h)),
    )
    if right - left < 1 or bottom - top < 1:
        return node
    crop = (left / pixels_w, top / pixels_h, right / pixels_w, bottom / pixels_h)
    sized = {
        "width": round((right - left) * scale, 3),
        "height": round((bottom - top) * scale, 3),
        FITTED: Settings((("box", (width, height)),
                          ("crop", tuple(round(share, 6) for share in crop)))),
    }
    properties = [(key, value) for key, value in node.properties if key not in sized]
    return replace(node, properties=(*properties, *sized.items()))


def _extent(node: NodeSpec, style: LayoutStyle, palette: Palette, box: tuple[float, float]
            ) -> tuple[tuple[float, float, float, float], tuple[float, float]] | None:
    """What ``node``'s molecule draws, drawn in ``box``: its extent in points from the box's
    middle (left, top, right, bottom), and the canvas it is drawn on (pixels) -- or None, for
    one that is not drawn, or draws nothing."""

    from flexo.diagnostics import FlexoError
    from flexo.structures import _ask, _problem

    problem = _problem(node, style)
    if problem is not None and not problem.drawn:
        return None
    width, height = box
    try:
        found = drawn_extent(_ask(node, style, palette), width / height)
    except FlexoError:
        return None
    if found is None:
        return None
    (left, top, right, bottom), (pixels_w, pixels_h) = found
    scale = min(width / pixels_w, height / pixels_h)
    return (
        (left - pixels_w / 2) * scale, (top - pixels_h / 2) * scale,
        (right - pixels_w / 2) * scale, (bottom - pixels_h / 2) * scale,
    ), (pixels_w, pixels_h)


def drawn_extent(ask, aspect: float):
    """The ink of the molecule ``ask`` asks for, drawn at ``aspect`` as the figure draws it
    (``flexo.structures.structure_svg``, or ``structure_png``), in its canvas's pixels -- and
    the canvas -- or None, for a drawing of nothing: found from the drawing once, and kept."""

    from flexo.structures import _failed, _failing, _hatched

    if _failed.get(_failing(ask)):
        # (mol-sketch failed to draw it: the panel is hatched, at any aspect.)
        return _png_extent(_hatched(aspect))
    return _drawn_extent(ask, aspect)


_EXTENTS: dict[tuple, object] = {}
"""Each drawing's extent (``drawn_extent``), by what it is drawn from and at what aspect."""

EXTENTS = 1024
"""How many extents are kept in memory; past that it starts again."""


def _drawn_extent(ask, aspect: float):
    from flexo.structure_kept import extent, keep_extent
    from flexo.structures import VECTOR_LOOKS, _drawing, _failed, _failing, _hatched

    key = (ask, aspect)
    if key in _EXTENTS:
        return _EXTENTS[key]
    kind = "shapes" if ask.look in VECTOR_LOOKS else "png"
    known, found = extent(ask, aspect, kind)
    if not known:
        drawn = _drawing(ask, aspect)
        if _failed.get(_failing(ask)):
            return _png_extent(_hatched(aspect))  # (not kept: drawn again another time)
        found = _svg_extent(drawn) if isinstance(drawn, str) else _png_extent(drawn)
        keep_extent(ask, aspect, kind, found)
    if len(_EXTENTS) >= EXTENTS:
        _EXTENTS.clear()
    _EXTENTS[key] = found
    return found


@functools.lru_cache(maxsize=32)
def _svg_extent(markup: str):
    """The ink of a molecule drawn as shapes, in its canvas's pixels -- and the canvas."""

    from flexo.drawing import ink_bounds, read_drawing

    drawing = read_drawing(markup)
    if not any(True for _ in drawing.walk()):
        return None
    left, top, right, bottom = ink_bounds(drawing)
    left, top = max(left, 0.0), max(top, 0.0)
    right, bottom = min(right, drawing.width), min(bottom, drawing.height)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom), (drawing.width, drawing.height)


@functools.lru_cache(maxsize=32)
def _png_extent(png: bytes):
    """The opaque pixels of a molecule drawn as a picture, their box -- and the picture's size."""

    pixels = _pixels(png)
    if pixels is None:
        return None
    opaque = pixels[..., 3] >= OPAQUE
    columns, rows = opaque.any(axis=0).nonzero()[0], opaque.any(axis=1).nonzero()[0]
    if not len(columns):
        return None
    height, width = opaque.shape
    return ((float(columns[0]), float(rows[0]), float(columns[-1] + 1), float(rows[-1] + 1)),
            (float(width), float(height)))


def _pixels(png: bytes):
    """A PNG as ``flexo.structures`` writes one (RGBA, eight bits, rows unfiltered) as an
    array of its pixels -- None for any other."""

    import numpy as np

    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    at, data, header = 8, [], None
    while at + 8 <= len(png):
        (length,), kind = struct.unpack(">I", png[at:at + 4]), png[at + 4:at + 8]
        body = png[at + 8:at + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            data.append(body)
        at += 12 + length
    if header is None or header[2:5] != (8, 6, 0) or header[6] != 0:
        return None
    width, height = header[0], header[1]
    try:
        raw = np.frombuffer(zlib.decompress(b"".join(data)), dtype=np.uint8)
    except zlib.error:
        return None
    if raw.size != height * (width * 4 + 1):
        return None
    rows = raw.reshape(height, width * 4 + 1)
    if rows[:, 0].any():
        return None  # (filtered rows: not one of ours)
    return rows[:, 1:].reshape(height, width, 4)


@functools.lru_cache(maxsize=32)
def cropped_png(png: bytes, crop: tuple[float, float, float, float]) -> bytes:
    """A molecule drawn as a picture cut to ``crop`` (shares of it): the picture itself, for
    one that can't be read."""

    import numpy as np

    from flexo.structures import _png

    pixels = _pixels(png)
    if pixels is None:
        return png
    height, width = pixels.shape[:2]
    left, top = round(crop[0] * width), round(crop[1] * height)
    right, bottom = round(crop[2] * width), round(crop[3] * height)
    if right - left < 1 or bottom - top < 1 or (left, top, right, bottom) == (0, 0, width, height):
        return png
    return _png(np.ascontiguousarray(pixels[top:bottom, left:right]))


def cropped_view(view: str, crop: Crop) -> str:
    """A molecule's viewBox (as mol-sketch writes it) cut to ``crop`` (shares of it)."""

    numbers = [float(value) for value in view.replace(",", " ").split()]
    if len(numbers) != 4:
        return view
    left, top, width, height = numbers
    return " ".join(
        f"{value:.3f}".rstrip("0").rstrip(".")
        for value in (left + crop[0] * width, top + crop[1] * height,
                      (crop[2] - crop[0]) * width, (crop[3] - crop[1]) * height)
    )


def canvas_box(fitted, x: float, y: float, width: float, height: float
               ) -> tuple[float, float, float, float]:
    """Where the whole canvas of a molecule cropped as ``fitted`` (``drawn_in``) lies, drawn
    with its part shown at ``x``, ``y``, ``width`` by ``height``: left, top, width, height."""

    _, (left, top, right, bottom) = fitted
    across, down = width / (right - left), height / (bottom - top)
    return x - left * across, y - top * down, across, down
