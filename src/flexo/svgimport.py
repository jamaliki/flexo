"""A drawing made elsewhere -- Inkscape, Illustrator, Affinity, a browser -- as Flexo's own
shapes (``flexo.freeform``), each editable piece by piece.

The owner of a figure draws a module in Inkscape and pastes it onto a slide or over a figure:
every box, line, arrow, curve and word of it arrives as the shape Flexo has for it, in one
group, painted by the theme where its colours are the theme's. ``shapes_of`` reads the SVG
and says what it made; the studio's paste, its drop of an ``.svg`` and the CLI's
``flexo import-svg`` all come here.

What each part of the drawing becomes:

- ``rect`` a ``rectangle`` (``rounded-rectangle`` with its corner), ``circle`` and
  ``ellipse`` an ``ellipse``, turned (``rotate``) where they are turned, so they stay boxes
  that are sized as boxes are; skewed, they are their outline, a ``path``;
- ``line``, ``polyline`` and ``polygon`` a ``line``, a ``polyline`` or a closed one; a path of
  straight pieces the same, a closed one of four right angles a ``rectangle``, one of two or
  three pieces turning through right angles an ``elbow``; a straight one with arrowheads an
  ``arrow`` or a ``double-arrow``; any other path a ``path``;
- arrowheads (markers) the ends Flexo has -- each marker's outline read, whichever family
  drew it (Inkscape's ``Arrow1``, ``Arrow2``, ``TriangleOut``, ``Stop``, ``Dot``, ``Square``;
  Inkscape 1's ``ArrowWide``, ``Triangle``, ``Dot``, ``Stop``; anyone's): a triangle, a
  notched (stealth) or an open arrowhead, a dot or a ring, a bar or a diamond, sized as it
  was, its tip where it was; one that is none of these (a square, an arrowhead of another
  colour, one pointing back, a marker on a corner) is drawn as it is, a shape of its own in
  a group with its line;
- ``g`` a ``group`` (its opacity kept; one of one shape that shape; layers are the paste's own
  group, not groups of their own); ``use`` and ``symbol`` what they place, each time;
  a nested ``svg`` its content, fitted to its box;
- ``text`` a ``text`` box: its lines (``sodipodi:role="line"``, or several ``tspan`` placed
  one under another) one box, its flowed text (``flowRoot``, or SVG 2's ``shape-inside``) a
  box as wide as what it flows in; bold, italic, coloured, sub- and superscript words in the
  slide's or the figure's markup (``markup``); its size, family (where Flexo has it),
  colour and alignment as drawn, and placed so its baseline is where it was;
- text drawn as outlines (LaTeX's, TexText's, Inkscape's "Object to Path") stays outlines:
  each group of them one ``path``.

Transforms are drawn into the shapes. Paint is read from ``style``, the presentation
attributes and the drawing's ``<style>`` sheet, inherited as SVG inherits it: fill and line,
their opacities and the shape's, line widths (scaled by the transform), dashes (as lengths),
caps, joins and fill rules. Black is the theme's ink and white its paper, and any colour
within a just noticeable difference of one of the theme's (CIEDE2000, ``NEAR``) is that
colour by name, so a change of theme repaints it; ``exact`` keeps every colour as it is
written. Gradients are gradient fills (``{gradient: linear, angle, stops}``,
``{gradient: radial, centre, radius, stops}``).

What has no shape -- a picture, a group cut by a clip or a mask, a blur or a shadow (a
filter), a pattern, HTML -- is kept exactly as drawn: a ``picture`` (``source``, a file of its
own: the bitmap, or an SVG of that part alone with what it needs), in its place among the
rest. Each is said (``Imported.kept``), and so is what is drawn near enough rather than
exactly (``Imported.approximated``).

The whole is placed as asked: its units made points (a millimetre is 72/25.4 of them, a
pixel 0.75), centred on ``centre``, or its top left at ``at``, and made smaller to fit
``fit`` where it is larger. One element in a thousand-element drawing takes a few hundredths
of a millisecond.
"""

from __future__ import annotations

import base64
import binascii
import copy
import itertools
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from flexo import freeform, pathdata

type Matrix = tuple[float, float, float, float, float, float]
"""SVG's ``matrix(a b c d e f)``: a point goes to ``(a x + c y + e, b x + d y + f)``."""
type Point = tuple[float, float]
type Box = tuple[float, float, float, float]
"""``left, top, right, bottom``."""

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"

NEAR = 2.0
"""How near (CIEDE2000) a colour must be to one of the theme's to be painted by it: a
difference only just seen side by side."""
LARGEST = 20_000
"""Elements read at most: a drawing of more is a picture, not shapes (``Imported.whole``)."""
SHAPES_AT_MOST = 2_000
"""How many shapes a drawing makes before the studio places it as a picture instead (a drop
of a huge file): beyond that, editing it piece by piece is not why it was dropped."""

UNITS = {
    "": 1.0,
    "px": 1.0,
    "pt": 4.0 / 3.0,
    "pc": 16.0,
    "mm": 96.0 / 25.4,
    "cm": 96.0 / 2.54,
    "in": 96.0,
    "q": 96.0 / 101.6,
}
"""User units (CSS pixels) in each absolute unit."""
POINTS_PER_PIXEL = 0.75

INHERITED = frozenset(
    {
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "marker-start",
        "marker-mid",
        "marker-end",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "font-variant",
        "text-anchor",
        "text-align",
        "letter-spacing",
        "word-spacing",
        "line-height",
        "visibility",
        "color",
        "white-space",
        "writing-mode",
        "direction",
        "paint-order",
        "clip-rule",
        "vector-effect",
    }
)
"""Properties a child takes from its parent unless it says otherwise."""
PROPERTIES = INHERITED | {
    "opacity",
    "display",
    "clip-path",
    "mask",
    "filter",
    "baseline-shift",
    "stop-color",
    "stop-opacity",
    "overflow",
    "shape-inside",
    "inline-size",
    "mix-blend-mode",
    "text-decoration",
    "dominant-baseline",
    "marker",
    "font",
}
"""Properties read from presentation attributes, ``style`` and the style sheet."""
INITIAL = {
    "fill": "black",
    "fill-opacity": "1",
    "fill-rule": "nonzero",
    "stroke": "none",
    "stroke-width": "1",
    "stroke-opacity": "1",
    "stroke-dasharray": "none",
    "stroke-linecap": "butt",
    "stroke-linejoin": "miter",
    "font-size": "16",
    "font-family": "sans-serif",
    "font-weight": "normal",
    "font-style": "normal",
    "text-anchor": "start",
    "opacity": "1",
    "color": "black",
}

CSS_COLOURS = {
    "aliceblue": "#f0f8ff", "antiquewhite": "#faebd7", "aqua": "#00ffff",
    "aquamarine": "#7fffd4", "azure": "#f0ffff", "beige": "#f5f5dc", "bisque": "#ffe4c4",
    "black": "#000000", "blanchedalmond": "#ffebcd", "blue": "#0000ff",
    "blueviolet": "#8a2be2", "brown": "#a52a2a", "burlywood": "#deb887",
    "cadetblue": "#5f9ea0", "chartreuse": "#7fff00", "chocolate": "#d2691e",
    "coral": "#ff7f50", "cornflowerblue": "#6495ed", "cornsilk": "#fff8dc",
    "crimson": "#dc143c", "cyan": "#00ffff", "darkblue": "#00008b", "darkcyan": "#008b8b",
    "darkgoldenrod": "#b8860b", "darkgray": "#a9a9a9", "darkgreen": "#006400",
    "darkgrey": "#a9a9a9", "darkkhaki": "#bdb76b", "darkmagenta": "#8b008b",
    "darkolivegreen": "#556b2f", "darkorange": "#ff8c00", "darkorchid": "#9932cc",
    "darkred": "#8b0000", "darksalmon": "#e9967a", "darkseagreen": "#8fbc8f",
    "darkslateblue": "#483d8b", "darkslategray": "#2f4f4f", "darkslategrey": "#2f4f4f",
    "darkturquoise": "#00ced1", "darkviolet": "#9400d3", "deeppink": "#ff1493",
    "deepskyblue": "#00bfff", "dimgray": "#696969", "dimgrey": "#696969",
    "dodgerblue": "#1e90ff", "firebrick": "#b22222", "floralwhite": "#fffaf0",
    "forestgreen": "#228b22", "fuchsia": "#ff00ff", "gainsboro": "#dcdcdc",
    "ghostwhite": "#f8f8ff", "gold": "#ffd700", "goldenrod": "#daa520", "gray": "#808080",
    "green": "#008000", "greenyellow": "#adff2f", "grey": "#808080", "honeydew": "#f0fff0",
    "hotpink": "#ff69b4", "indianred": "#cd5c5c", "indigo": "#4b0082", "ivory": "#fffff0",
    "khaki": "#f0e68c", "lavender": "#e6e6fa", "lavenderblush": "#fff0f5",
    "lawngreen": "#7cfc00", "lemonchiffon": "#fffacd", "lightblue": "#add8e6",
    "lightcoral": "#f08080", "lightcyan": "#e0ffff", "lightgoldenrodyellow": "#fafad2",
    "lightgray": "#d3d3d3", "lightgreen": "#90ee90", "lightgrey": "#d3d3d3",
    "lightpink": "#ffb6c1", "lightsalmon": "#ffa07a", "lightseagreen": "#20b2aa",
    "lightskyblue": "#87cefa", "lightslategray": "#778899", "lightslategrey": "#778899",
    "lightsteelblue": "#b0c4de", "lightyellow": "#ffffe0", "lime": "#00ff00",
    "limegreen": "#32cd32", "linen": "#faf0e6", "magenta": "#ff00ff", "maroon": "#800000",
    "mediumaquamarine": "#66cdaa", "mediumblue": "#0000cd", "mediumorchid": "#ba55d3",
    "mediumpurple": "#9370db", "mediumseagreen": "#3cb371", "mediumslateblue": "#7b68ee",
    "mediumspringgreen": "#00fa9a", "mediumturquoise": "#48d1cc",
    "mediumvioletred": "#c71585", "midnightblue": "#191970", "mintcream": "#f5fffa",
    "mistyrose": "#ffe4e1", "moccasin": "#ffe4b5", "navajowhite": "#ffdead",
    "navy": "#000080", "oldlace": "#fdf5e6", "olive": "#808000", "olivedrab": "#6b8e23",
    "orange": "#ffa500", "orangered": "#ff4500", "orchid": "#da70d6",
    "palegoldenrod": "#eee8aa", "palegreen": "#98fb98", "paleturquoise": "#afeeee",
    "palevioletred": "#db7093", "papayawhip": "#ffefd5", "peachpuff": "#ffdab9",
    "peru": "#cd853f", "pink": "#ffc0cb", "plum": "#dda0dd", "powderblue": "#b0e0e6",
    "purple": "#800080", "rebeccapurple": "#663399", "red": "#ff0000",
    "rosybrown": "#bc8f8f", "royalblue": "#4169e1", "saddlebrown": "#8b4513",
    "salmon": "#fa8072", "sandybrown": "#f4a460", "seagreen": "#2e8b57",
    "seashell": "#fff5ee", "sienna": "#a0522d", "silver": "#c0c0c0", "skyblue": "#87ceeb",
    "slateblue": "#6a5acd", "slategray": "#708090", "slategrey": "#708090",
    "snow": "#fffafa", "springgreen": "#00ff7f", "steelblue": "#4682b4", "tan": "#d2b48c",
    "teal": "#008080", "thistle": "#d8bfd8", "tomato": "#ff6347", "turquoise": "#40e0d0",
    "violet": "#ee82ee", "wheat": "#f5deb3", "white": "#ffffff", "whitesmoke": "#f5f5f5",
    "yellow": "#ffff00", "yellowgreen": "#9acd32",
}  # fmt: skip
"""CSS's named colours."""

GENERIC_FAMILIES = frozenset(
    {"sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui", "sans", "inherit"}
)
"""Families that name no face: words in them are set in the page's own font."""

GENERIC_FACES = {"serif": "Latin Modern Roman", "monospace": "IBM Plex Mono", "cursive": "Kalam"}
"""The faces Flexo sets words in that a drawing names only by their kind (as
``flexo.restyle`` sets a picture's)."""

THEME_NAMES = (
    ("ink", "ink"),
    ("paper", "canvas"),
    ("muted", "muted-ink"),
    ("grey", "block-fill"),
    *((f"accent{n if n > 1 else ''}", f"tone-{n}-stroke") for n in range(1, 9)),
    *((f"accent{n if n > 1 else ''}-fill", f"tone-{n}-fill") for n in range(1, 9)),
)
"""The theme's colours a drawing's are matched to, by the names a shape gives them, first
first: where two are one colour, the first name is used."""


class SvgImportError(ValueError):
    """A drawing that cannot be read: what is wrong, in words."""


@dataclass(slots=True)
class Imported:
    """What a drawing became."""

    shapes: list[dict[str, Any]]
    """Its shapes: one group (or the one shape it is), placed as asked."""
    box: tuple[float, float, float, float]
    """Where they are: ``x, y, width, height``, in the units of the page they are for."""
    scale: float = 1.0
    """What its points were scaled by to fit."""
    kept: list[str] = field(default_factory=list)
    """What is kept as a picture, as no shape draws it, said in words."""
    approximated: list[str] = field(default_factory=list)
    """What is drawn near enough rather than exactly, said in words."""
    pictures: dict[str, bytes] = field(default_factory=dict)
    """The pictures' files, by the ``source`` their shapes name (unless ``picture`` wrote
    them)."""
    elements: int = 0
    """How many of the drawing's elements were read."""
    count: int = 0
    """How many shapes it made, a group's own counted."""
    page: tuple[float, float] = (0.0, 0.0)
    """The drawing's own page (its ``width`` and ``height``), in points, as scaled."""


# -- reading the drawing -----------------------------------------------------------------


def shapes_of(
    svg: str | bytes,
    *,
    roles: Mapping[str, str] | None = None,
    exact: bool = False,
    markup: str = "slide",
    centre: Sequence[float] | None = None,
    at: Sequence[float] | None = None,
    fit: Sequence[float] | None = None,
    scale: float | None = None,
    origin: Sequence[float] | None = None,
    picture: Callable[[bytes, str], str] | None = None,
    name: str = "drawing",
    taken: Sequence[str] = (),
) -> Imported:
    """The shapes ``svg`` (a whole SVG document) is drawn with (see the module's words).

    ``roles``: the theme's colours by palette role (``ink``, ``canvas``, ``tone-1-stroke``…)
    its colours are matched to (``exact``: none are); Flexo's default theme's when not given.
    ``markup``: the words' markup, ``slide`` (``**bold**``, ``*italic*``) or ``figure``
    (``[bold]{bold}``). ``centre`` or ``at`` (its top left) place it, in points; ``fit`` is
    the most it may measure, ``[width, height]``, and it is made smaller to fit; ``scale``
    scales it by so much instead (placed by neither, it stays where its page has it, scaled
    from the page's top left -- or with its page's top left at ``origin``: the drawing put
    back where a picture of its page was drawn). ``picture``
    keeps a picture's file -- its bytes and its suffix (``.svg``, ``.png``, ``.jpg``) -- and
    says the ``source`` its shape names it by; without it they are kept in
    ``Imported.pictures`` as ``{name}-1.svg``… ``taken``: names the page has already (a
    figure's parts), which no shape is given."""

    if markup not in ("slide", "figure"):
        raise ValueError(f"markup must be slide or figure, not {markup!r}")
    root = _parse(svg)
    reader = _Reader(root, roles=roles, exact=exact, markup=markup, picture=picture, name=name)
    reader.named.update(str(item) for item in taken)
    made = reader.read()
    box = _union([item.box for item in made])
    if box is None:
        return Imported(
            [],
            (0.0, 0.0, 0.0, 0.0),
            1.0,
            reader.kept,
            reader.approx,
            reader.files,
            reader.elements,
            0,
        )
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    factor = 1.0
    if scale is not None:
        factor = float(scale)
    elif fit is not None and width > 0 and height > 0:
        factor = min(1.0, float(fit[0]) / width, float(fit[1]) / height)
    scale = factor
    if centre is not None:
        dx = float(centre[0]) - (left + width / 2.0) * scale
        dy = float(centre[1]) - (top + height / 2.0) * scale
    elif at is not None:
        dx, dy = float(at[0]) - left * scale, float(at[1]) - top * scale
    elif origin is not None:
        dx, dy = float(origin[0]), float(origin[1])
    else:
        dx = dy = 0.0
    shapes = [_placed(item.spec, scale, dx, dy) for item in made]
    if len(shapes) > 1 or (shapes and shapes[0]["kind"] != "group" and reader.layered):
        shapes = [_group(shapes, reader.group_id())]
    shapes = [_tidy(shape) for shape in shapes]
    placed = (left * scale + dx, top * scale + dy, width * scale, height * scale)
    return Imported(
        shapes,
        tuple(round(value, 2) for value in placed),  # type: ignore[arg-type]
        scale,
        reader.kept,
        reader.approx,
        reader.files,
        reader.elements,
        sum(_count(shape) for shape in shapes),
        (reader.view[0] * POINTS_PER_PIXEL * scale, reader.view[1] * POINTS_PER_PIXEL * scale),
    )


def _count(spec: Mapping[str, Any]) -> int:
    return 1 + sum(_count(child) for child in spec.get("shapes") or [])


_ENTITY = re.compile(rb"<!ENTITY", re.IGNORECASE)


def _parse(svg: str | bytes) -> ET.Element:
    data = svg.encode("utf-8") if isinstance(svg, str) else bytes(svg)
    if _ENTITY.search(data[:65536]):
        # (Entities are how a file of a few bytes names billions: no drawing needs them.)
        raise SvgImportError("The drawing declares XML entities, which Flexo does not read.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise SvgImportError(f"The drawing is not SVG that reads: {error}.") from None
    if _local(root.tag) != "svg":
        raise SvgImportError("The drawing is not SVG: its outermost element is not <svg>.")
    return root


def _local(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _href(element: ET.Element) -> str:
    return element.get(f"{{{XLINK_NS}}}href") or element.get("href") or ""


# -- numbers, lengths, transforms -----------------------------------------------------------

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_LENGTH = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)\s*$")


def _numbers(text: str | None) -> list[float]:
    return [float(value) for value in _NUMBER.findall(text or "")]


def _length(
    value: str | None, default: float = 0.0, *, font: float = 16.0, whole: float = 0.0
) -> float:
    """A length in user units: a number, or one in units (``mm``, ``pt``, ``em``, ``%`` of
    ``whole``)."""

    if value is None:
        return default
    found = _LENGTH.match(str(value))
    if not found:
        numbers = _numbers(str(value))
        return numbers[0] if numbers else default
    number, unit = float(found.group(1)), found.group(2).lower()
    if unit == "%":
        return number / 100.0 * whole
    if unit == "em":
        return number * font
    if unit == "ex":
        return number * font / 2.0
    if unit == "rem":
        return number * 16.0
    return number * UNITS.get(unit, 1.0)


def _multiply(first: Matrix, second: Matrix) -> Matrix:
    """``first`` after ``second``: a point is moved by ``second``, then by ``first``."""

    a, b, c, d, e, f = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def _apply(matrix: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _vector(matrix: Matrix, x: float, y: float) -> Point:
    a, b, c, d, _, _ = matrix
    return (a * x + c * y, b * x + d * y)


def _inverse(matrix: Matrix) -> Matrix:
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    if abs(det) < 1e-12:
        return IDENTITY
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


def _scale_of(matrix: Matrix) -> float:
    """How much a length is scaled, on average, by ``matrix``."""

    a, b, c, d, _, _ = matrix
    return math.sqrt(abs(a * d - b * c))


_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", re.I)


def _transform(text: str | None) -> Matrix:
    """An SVG ``transform`` as a matrix (what it cannot read, none)."""

    matrix = IDENTITY
    for name, arguments in _TRANSFORM.findall(text or ""):
        values = _numbers(arguments)
        name = name.lower()
        step = IDENTITY
        if name == "matrix" and len(values) == 6:
            step = tuple(values)  # type: ignore[assignment]
        elif name == "translate" and values:
            step = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale" and values:
            step = (values[0], 0.0, 0.0, values[1] if len(values) > 1 else values[0], 0.0, 0.0)
        elif name == "rotate" and values:
            angle = math.radians(values[0])
            cos, sin = math.cos(angle), math.sin(angle)
            step = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(values) >= 3:
                cx, cy = values[1], values[2]
                step = _multiply(
                    (1.0, 0.0, 0.0, 1.0, cx, cy), _multiply(step, (1.0, 0.0, 0.0, 1.0, -cx, -cy))
                )
        elif name == "skewx" and values:
            step = (1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0)
        elif name == "skewy" and values:
            step = (1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0)
        matrix = _multiply(matrix, step)
    return matrix


@dataclass(frozen=True, slots=True)
class _Frame:
    """A matrix as a box drawn through it sees it: turned ``turn`` degrees, stretched
    ``sx`` along its own x and ``sy`` along its y, mirrored or not -- or skewed, which no
    box is."""

    turn: float
    sx: float
    sy: float
    mirrored: bool
    skewed: bool


def _frame(matrix: Matrix) -> _Frame:
    a, b, c, d, _, _ = matrix
    sx, sy = math.hypot(a, b), math.hypot(c, d)
    if sx < 1e-12 or sy < 1e-12:
        return _Frame(0.0, sx, sy, False, True)
    skew = abs(a * c + b * d) / (sx * sy)
    turn = math.degrees(math.atan2(b, a))
    turn = 0.0 if abs(turn) < 1e-6 else turn
    return _Frame(turn % 360.0, sx, sy, a * d - b * c < 0, skew > 1e-4)


# -- the style sheet -------------------------------------------------------------------------

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_DECLARATION = re.compile(r"([-a-zA-Z]+)\s*:\s*([^;]+)")


def _declarations(text: str) -> dict[str, str]:
    """``fill:#fff;stroke:none`` as a mapping (``!important`` marked by a leading ``!``)."""

    out: dict[str, str] = {}
    for name, value in _DECLARATION.findall(_COMMENT.sub("", text or "")):
        value = value.strip()
        if value.lower().endswith("!important"):
            value = "!" + value[: -len("!important")].strip()
        out[name.strip().lower()] = value
    return out


@dataclass(slots=True)
class _Rule:
    selector: list[tuple[str, str | None, tuple[str, ...], bool]]
    """Compound selectors, outermost first: (tag or ``*``, id, classes, whether it is a child
    of the one before rather than anywhere in it)."""
    specificity: tuple[int, int, int]
    order: int
    declarations: dict[str, str]


_COMPOUND = re.compile(r"^([a-zA-Z][\w:-]*|\*)?((?:[#.][\w-]+)*)$")


def _rules(text: str, start: int = 0) -> list[_Rule]:
    """The rules of a style sheet that a drawing's elements are styled by: selectors of
    tags, ids and classes, and their descendants (what else a selector says, unread)."""

    text = _COMMENT.sub("", text or "")
    out: list[_Rule] = []
    order = start
    depth, at, head = 0, 0, ""
    skip = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character == "{":
            if depth == 0:
                head = text[at:index].strip()
                skip = 1 if head.startswith("@") and not head.lower().startswith("@media") else 0
                if head.lower().startswith("@media"):
                    # (A media query's rules are the drawing's, as a browser shows it.)
                    at = index + 1
                    index += 1
                    continue
            depth += 1
            at = index + 1
        elif character == "}":
            depth = max(depth - 1, 0)
            body = text[at:index]
            if not skip and head and not head.startswith("@"):
                for selector in head.split(","):
                    parsed = _selector(selector.strip())
                    if parsed is not None:
                        order += 1
                        out.append(_Rule(parsed[0], parsed[1], order, _declarations(body)))
            if depth == 0:
                skip = 0
            at = index + 1
            head = ""
        elif character == ";" and depth == 0:
            at = index + 1
        index += 1
    return out


def _selector(text: str) -> tuple[list, tuple[int, int, int]] | None:
    parts = []
    ids = classes = tags = 0
    # (Each compound after the first says how it stands to the one before: ">" its child,
    # else anywhere in it.)
    child = False
    for word in text.replace(">", " > ").split():
        if word == ">":
            child = True
            continue
        found = _COMPOUND.match(word)
        if not found:
            return None
        tag = found.group(1) or "*"
        rest = found.group(2) or ""
        ident = None
        names = []
        for piece in re.findall(r"[#.][\w-]+", rest):
            if piece[0] == "#":
                ident = piece[1:]
                ids += 1
            else:
                names.append(piece[1:])
                classes += 1
        if tag != "*":
            tags += 1
        parts.append((tag.split(":")[-1], ident, tuple(names), child))
        child = False
    return (parts, (ids, classes, tags)) if parts else None


def _matches_one(part: tuple, element: ET.Element) -> bool:
    tag, ident, names = part[:3]
    if tag != "*" and _local(element.tag) != tag:
        return False
    if ident is not None and element.get("id") != ident:
        return False
    if names:
        own = set((element.get("class") or "").split())
        if not all(name in own for name in names):
            return False
    return True


# -- colours ---------------------------------------------------------------------------------


def _hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(value * 255))):02x}" for value in rgb)


def _rgb(colour: str) -> tuple[float, float, float]:
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return (int(text[0:2], 16) / 255.0, int(text[2:4], 16) / 255.0, int(text[4:6], 16) / 255.0)


_FUNCTION = re.compile(r"(rgba?|hsla?)\(([^)]*)\)", re.I)


def _colour(value: str | None, current: str = "#000000") -> tuple[str | None, float]:
    """A CSS colour as ``#rrggbb`` and its own alpha; ``None`` for none (or what is no
    colour)."""

    if value is None:
        return None, 1.0
    text = value.strip().lstrip("!").strip()
    lower = text.lower()
    if not lower or lower in ("none", "transparent"):
        return None, 1.0
    if lower == "currentcolor":
        return _colour(current)
    if lower.startswith("#"):
        digits = lower[1:]
        if re.fullmatch(r"[0-9a-f]{3}|[0-9a-f]{6}", digits):
            return "#" + (digits if len(digits) == 6 else "".join(ch * 2 for ch in digits)), 1.0
        if re.fullmatch(r"[0-9a-f]{4}|[0-9a-f]{8}", digits):
            if len(digits) == 4:
                digits = "".join(ch * 2 for ch in digits)
            return "#" + digits[:6], int(digits[6:8], 16) / 255.0
        return None, 1.0
    found = _FUNCTION.match(lower)
    if found:
        parts = [part.strip() for part in re.split(r"[,\s/]+", found.group(2).strip()) if part]
        alpha = 1.0
        if len(parts) >= 4:
            alpha = _fraction(parts[3])
        if found.group(1).startswith("rgb") and len(parts) >= 3:
            channels = [
                float(part[:-1]) / 100.0 if part.endswith("%") else float(part) / 255.0
                for part in parts[:3]
            ]
            return _hex(channels), alpha
        if found.group(1).startswith("hsl") and len(parts) >= 3:
            import colorsys

            hue = float(re.sub(r"[a-z]+$", "", parts[0])) / 360.0 % 1.0
            sat, light = (float(part.rstrip("%")) / 100.0 for part in parts[1:3])
            return _hex(colorsys.hls_to_rgb(hue, light, sat)), alpha
        return None, 1.0
    if lower in CSS_COLOURS:
        return CSS_COLOURS[lower], 1.0
    return None, 1.0


def _fraction(value: object, default: float = 1.0) -> float:
    text = str(value).strip().lstrip("!") if value is not None else ""
    if not text:
        return default
    try:
        number = float(text[:-1]) / 100.0 if text.endswith("%") else float(text)
    except ValueError:
        return default
    return max(0.0, min(1.0, number))


def _lab(colour: str) -> tuple[float, float, float]:
    """``colour`` in CIELAB (D65)."""

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in _rgb(colour))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (24389.0 / 27.0 * t + 16.0) / 116.0

    fx, fy, fz = f(x), f(y), f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def difference(first: str, second: str) -> float:
    """How different two colours look: CIEDE2000's ΔE (about 1 is just seen side by side)."""

    l1, a1, b1 = _lab(first)
    l2, a2, b2 = _lab(second)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt(mean_c**7 / (mean_c**7 + 25.0**7)))
    a1p, a2p = a1 * (1.0 + g), a2 * (1.0 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0 if c2p else 0.0
    dl, dc = l2 - l1, c2p - c1p
    dh = 0.0
    if c1p * c2p:
        dh = h2p - h1p
        if dh > 180.0:
            dh -= 360.0
        elif dh < -180.0:
            dh += 360.0
    big_dh = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2.0))
    mean_l, mean_cp = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        mean_h = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        mean_h = (h1p + h2p) / 2.0
    else:
        mean_h = (h1p + h2p + 360.0) / 2.0 if h1p + h2p < 360.0 else (h1p + h2p - 360.0) / 2.0
    t = (
        1.0
        - 0.17 * math.cos(math.radians(mean_h - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * mean_h))
        + 0.32 * math.cos(math.radians(3.0 * mean_h + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * mean_h - 63.0))
    )
    sl = 1.0 + 0.015 * (mean_l - 50.0) ** 2 / math.sqrt(20.0 + (mean_l - 50.0) ** 2)
    sc = 1.0 + 0.045 * mean_cp
    sh = 1.0 + 0.015 * mean_cp * t
    turn = 30.0 * math.exp(-(((mean_h - 275.0) / 25.0) ** 2))
    rc = 2.0 * math.sqrt(mean_cp**7 / (mean_cp**7 + 25.0**7))
    rt = -math.sin(math.radians(2.0 * turn)) * rc
    return math.sqrt(
        (dl / sl) ** 2 + (dc / sc) ** 2 + (big_dh / sh) ** 2 + rt * (dc / sc) * (big_dh / sh)
    )


@cache
def _default_roles() -> dict[str, str]:
    from flexo.themes import resolve_palette, with_tone_roles

    return dict(with_tone_roles(resolve_palette("paper", "default")).paints)


class _Colours:
    """A drawing's colours as a shape writes them: by the theme's name where the theme has
    the colour (``ink``, ``accent2-fill``), else as written (``#3a7d44``)."""

    def __init__(self, roles: Mapping[str, str] | None, exact: bool) -> None:
        self.exact = exact
        found = dict(roles) if roles else _default_roles()
        self.named: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name, role in THEME_NAMES:
            colour = found.get(role)
            if not colour or not str(colour).startswith("#"):
                continue
            colour = _colour(str(colour))[0]
            if colour is None or colour in seen:
                continue
            seen.add(colour)
            self.named.append((name, colour))
        self.roles = {role: str(colour) for role, colour in found.items()}
        self.known: dict[str, str] = {}

    def name(self, colour: str, role: str | None = None) -> str:
        """``colour`` as a shape says it."""

        if self.exact:
            return colour
        if role:
            # (A drawing Flexo made says what each colour is: a role it is still.)
            friendly = _friendly(role)
            if friendly is not None and self.roles.get(role, "").lower() == colour.lower():
                return friendly
        if colour in self.known:
            return self.known[colour]
        named = colour
        if colour == "#000000":
            named = "ink"
        elif colour == "#ffffff":
            named = "paper"
        else:
            best = min(
                ((difference(colour, theirs), name) for name, theirs in self.named),
                default=(math.inf, colour),
            )
            if best[0] <= NEAR:
                named = best[1]
        self.known[colour] = named
        return named


def _friendly(role: str) -> str | None:
    """A palette role by the name a shape gives it (``tone-2-fill`` is ``accent2-fill``)."""

    found = re.fullmatch(r"tone-(\d+)-(stroke|fill)", role)
    if found:
        number = int(found.group(1))
        return f"accent{'' if number == 1 else number}{'-fill' if found.group(2) == 'fill' else ''}"
    if role in ("accent-stroke",):
        return "accent"
    if role == "accent-fill":
        return "accent-fill"
    reverse = {"canvas": "paper", "muted-ink": "muted", "block-fill": "grey", "ink": "ink"}
    if role in reverse:
        return reverse[role]
    return role if role in freeform._roles() else None


# -- what is read, as shapes -----------------------------------------------------------------


@dataclass(slots=True)
class _Made:
    spec: dict[str, Any]
    box: Box
    """What it draws, ``left, top, right, bottom``, in points before it is placed."""
    paint: tuple | None = None
    """A path's paint, for the outlines of words to be joined by (``_merged``)."""


class _TooMany(Exception):
    pass


SKIPPED = frozenset(
    {
        "defs", "title", "desc", "metadata", "style", "script", "marker", "clipPath", "mask",
        "pattern", "linearGradient", "radialGradient", "filter", "symbol", "font", "font-face",
        "namedview", "cursor", "view", "animate", "animateTransform", "animateMotion", "set",
        "glyph", "missing-glyph", "hkern", "vkern", "color-profile", "flowRegion",
        "flowDiv", "flowPara", "flowSpan",
    }
)  # fmt: skip
"""What draws nothing where it is (a definition, a description) or is read with what holds
it (the paragraphs of flowed text)."""

LEAVES = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})

_AUTO_ID = re.compile(
    r"(?:rect|path|text|tspan|g|circle|ellipse|use|line|polyline|polygon|image|flowRoot|"
    r"flowRegion|flowPara|flowSpan|layer|svg|a|defs|marker|stop|linearGradient|"
    r"radialGradient|clipPath|mask|filter|pattern|symbol|namedview|metadata|switch|"
    r"g\d*-\d+|glyph\d*-\d+|surface|clip|image|shape|group|object|connector|ellipse)"
    r"[-_]?\d+(?:[-_]\d+)*",
    re.IGNORECASE,
)
"""Ids a program gives every element it makes (``rect12``, ``path3-7``, ``g1520``): no name
of the drawer's, and none of the shapes'."""


class _Reader:
    def __init__(
        self,
        root: ET.Element,
        *,
        roles: Mapping[str, str] | None,
        exact: bool,
        markup: str,
        picture: Callable[[bytes, str], str] | None,
        name: str,
    ) -> None:
        self.root = root
        self.ids: dict[str, ET.Element] = {}
        self.parents: dict[ET.Element, ET.Element] = {}
        sheets: list[str] = []
        for element in root.iter():
            ident = element.get("id")
            if ident and ident not in self.ids:
                self.ids[ident] = element
            for child in element:
                self.parents[child] = element
            if _local(element.tag) == "style":
                sheets.append("".join(element.itertext()))
        self.rules: list[_Rule] = []
        for sheet in sheets:
            self.rules += _rules(sheet, len(self.rules))
        self.sheet = "\n".join(sheets)
        self.colours = _Colours(roles, exact)
        self.markup = markup
        self.picture = picture
        self.name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "drawing"
        self.kept: list[str] = []
        self.approx: list[str] = []
        self.files: dict[str, bytes] = {}
        self.elements = 0
        self.layered = False
        self.own_cache: dict[int, dict[str, str]] = {}
        self.named: set[str] = set()
        """The ids given to shapes, each once."""
        self.glued: list[tuple[dict[str, Any], str | None, str | None]] = []
        """Lines drawn as connectors (Inkscape's), with the ids of what they join."""
        self.wanted: set[str] = set()
        """Elements a connector joins: their shapes keep their ids."""
        self.root_id: str | None = None
        self.measurers: dict[tuple, Any] = {}
        self.families: dict[str, str | None] = {}
        self.pictured = 0
        self.aliases: dict[str, str] = {}
        """A connector's ends' ids, as the shapes they join are named."""
        self.using: list[ET.Element] = []
        for element in root.iter():
            for key in ("connection-start", "connection-end"):
                linked = element.get(f"{{{INKSCAPE_NS}}}{key}")
                if linked and linked.startswith("#"):
                    self.wanted.add(linked[1:])

    # -- notes --

    def approximate(self, said: str) -> None:
        if said not in self.approx:
            self.approx.append(said)

    def keep(self, said: str) -> None:
        self.kept.append(said)

    def group_id(self) -> str | None:
        return self.root_id

    # -- the whole --

    def read(self) -> list[_Made]:
        root = self.root
        width_text, height_text = root.get("width"), root.get("height")
        view = _numbers(root.get("viewBox"))
        width = _length(width_text) if width_text and not width_text.strip().endswith("%") else 0.0
        height = (
            _length(height_text) if height_text and not height_text.strip().endswith("%") else 0.0
        )
        if len(view) == 4 and view[2] > 0 and view[3] > 0:
            width = width or view[2]
            height = height or view[3]
            matrix = _viewbox(view, width, height, root.get("preserveAspectRatio"))
        else:
            matrix = IDENTITY
        self.view = (width, height)
        self.page_box = tuple(view) if len(view) == 4 else (0.0, 0.0, width, height)
        matrix = _multiply((POINTS_PER_PIXEL, 0.0, 0.0, POINTS_PER_PIXEL, 0.0, 0.0), matrix)
        style = self.style(root, {key: value for key, value in INITIAL.items() if key in INHERITED})
        label = root.get(f"{{{SODIPODI_NS}}}docname") or ""
        ident = root.get("id")
        if ident and not _AUTO_ID.fullmatch(ident) and not ident.startswith("svg"):
            self.root_id = _slug(ident)
        elif label:
            self.root_id = None
        try:
            made = self.children(root, matrix, style, 0, layers=True)
        except _TooMany:
            raise SvgImportError(
                f"The drawing has more than {LARGEST:,} elements: too many to be shapes. "
                "Place it as a picture instead."
            ) from None
        self.glue(made)
        return made

    # -- style --

    def own(self, element: ET.Element) -> dict[str, str]:
        """What ``element`` says of its own style: its presentation attributes, under the
        style sheet's rules for it, under its ``style``; ``!important`` over all."""

        key = id(element)
        found = self.own_cache.get(key)
        if found is not None:
            return found
        out: dict[str, str] = {}
        for name, value in element.attrib.items():
            local = _local(name)
            if local in PROPERTIES and "}" not in name:
                out[local] = value.strip()
        important: dict[str, str] = {}
        if self.rules:
            for rule in sorted(
                (rule for rule in self.rules if self.selects(rule, element)),
                key=lambda rule: (rule.specificity, rule.order),
            ):
                for name, value in rule.declarations.items():
                    if value.startswith("!"):
                        important[name] = value[1:].strip()
                    else:
                        out[name] = value
        for name, value in _declarations(element.get("style") or "").items():
            if value.startswith("!"):
                important[name] = value[1:].strip()
            else:
                out[name] = value
        out.update(important)
        self.own_cache[key] = out
        return out

    def selects(self, rule: _Rule, element: ET.Element) -> bool:
        parts = rule.selector
        if not _matches_one(parts[-1], element):
            return False
        at = self.parents.get(element)
        for index in range(len(parts) - 2, -1, -1):
            part, child = parts[index], parts[index + 1][3]
            if child:
                if at is None or not _matches_one(part, at):
                    return False
            else:
                while at is not None and not _matches_one(part, at):
                    at = self.parents.get(at)
                if at is None:
                    return False
            at = self.parents.get(at)
        return True

    def style(self, element: ET.Element, inherited: Mapping[str, str]) -> dict[str, str]:
        own = self.own(element)
        style = {key: value for key, value in inherited.items() if key in INHERITED}
        if "font" in own:
            style.update(_font_shorthand(own["font"]))
        if "marker" in own:
            for key in ("marker-start", "marker-mid", "marker-end"):
                style[key] = own["marker"]
        for name, value in own.items():
            if name in ("font", "marker"):
                continue
            if value == "inherit":
                if name in inherited:
                    style[name] = inherited[name]
                continue
            style[name] = value
        parent_size = float(inherited.get("font-size", "16") or 16.0)
        if "font-size" in own:
            style["font-size"] = str(_font_size(own["font-size"], parent_size))
        return style

    # -- walking --

    def children(
        self,
        element: ET.Element,
        matrix: Matrix,
        style: dict[str, str],
        depth: int,
        *,
        layers: bool = False,
        outline: bool = False,
    ) -> list[_Made]:
        made: list[_Made] = []
        for child in element:
            if not isinstance(child.tag, str):
                continue
            tag = _local(child.tag)
            if layers and tag == "g" and child.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer":
                self.layered = True
                own = self.style(child, style)
                if own.get("display", "").strip() == "none":
                    continue
                inner = self.children(
                    child,
                    _multiply(matrix, _transform(child.get("transform"))),
                    own,
                    depth,
                    layers=True,
                )
                opacity = _fraction(own.get("opacity"))
                if opacity < 1.0 and inner:
                    group = self.grouped(child, inner, opacity, depth)
                    made += group
                else:
                    made += inner
                continue
            made += self.element(child, matrix, style, depth, outline=outline)
        return made

    def element(
        self,
        element: ET.Element,
        matrix: Matrix,
        inherited: dict[str, str],
        depth: int,
        *,
        outline: bool = False,
        own_style: dict[str, str] | None = None,
    ) -> list[_Made]:
        tag = _local(element.tag)
        namespace = str(element.tag)[1:].split("}")[0] if str(element.tag).startswith("{") else ""
        if tag in SKIPPED or (namespace and namespace != SVG_NS):
            return []
        self.elements += 1
        if self.elements > LARGEST:
            raise _TooMany
        style = own_style if own_style is not None else self.style(element, inherited)
        if style.get("display", "").strip() == "none":
            return []
        placed = _multiply(matrix, _transform(element.get("transform")))
        why = self.unshaped(element, tag, style, placed)
        if why:
            return self.pictured_as(element, matrix, inherited, why)
        if tag in ("g", "a", "switch"):
            return self.group(element, placed, style, depth, outline=outline)
        if tag == "svg":
            return self.nested(element, placed, style, depth, outline=outline)
        if tag == "use":
            return self.use(element, placed, style, depth, outline=outline)
        if style.get("visibility", "").strip() in ("hidden", "collapse"):
            return []
        if tag in LEAVES:
            return self.leaf(element, tag, placed, style, outline=outline)
        if tag in ("text", "flowRoot"):
            return self.text(element, tag, placed, style)
        if tag == "image":
            return self.image(element, placed, style, matrix, inherited)
        if tag == "foreignObject":
            return self.pictured_as(
                element, matrix, inherited, "words set as HTML (a foreignObject)"
            )
        return []

    def unshaped(
        self, element: ET.Element, tag: str, style: Mapping[str, str], placed: Matrix
    ) -> str | None:
        """Why ``element`` cannot be shapes and is kept as a picture (or None)."""

        filtered = style.get("filter", "none").strip()
        if filtered and filtered != "none":
            return "a filter (a blur or a shadow)"
        masked = style.get("mask", "none").strip()
        if masked and masked != "none" and self.target(masked) is not None:
            return "a mask"
        clipped = style.get("clip-path", "none").strip()
        if clipped and clipped != "none":
            clip = self.target(clipped)
            if clip is not None and not self.clip_spares(element, clip, placed):
                return "a clip"
        blend = style.get("mix-blend-mode", "normal").strip()
        if blend and blend not in ("normal", "initial"):
            return f"a blend ({blend})"
        if tag in LEAVES or tag in ("text", "flowRoot"):
            for part in ("fill", "stroke"):
                target = self.target(style.get(part, ""))
                if target is not None and _local(target.tag) == "pattern":
                    return "a pattern"
        return None

    def target(self, value: str | None) -> ET.Element | None:
        found = re.match(r"\s*url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", value or "")
        return self.ids.get(found.group(1)) if found else None

    def clip_spares(self, element: ET.Element, clip: ET.Element, placed: Matrix) -> bool:
        """Whether a clip cuts nothing away: a rectangle round all ``element`` draws (a
        page's clip, a layer's), so its shapes are drawn without it."""

        shapes = [child for child in clip if _local(child.tag) in LEAVES | {"use"}]
        if len(shapes) != 1 or _local(shapes[0].tag) != "rect":
            return False
        rect = shapes[0]
        units = clip.get("clipPathUnits", "userSpaceOnUse")
        if units != "userSpaceOnUse":
            return False
        matrix = _multiply(
            _multiply(placed, _transform(clip.get("transform"))), _transform(rect.get("transform"))
        )
        frame = _frame(matrix)
        if frame.skewed or (frame.turn % 90.0) > 1e-6:
            return False
        x, y = _length(rect.get("x")), _length(rect.get("y"))
        w, h = _length(rect.get("width")), _length(rect.get("height"))
        corners = [_apply(matrix, x, y), _apply(matrix, x + w, y + h)]
        region = (
            min(p[0] for p in corners),
            min(p[1] for p in corners),
            max(p[0] for p in corners),
            max(p[1] for p in corners),
        )
        box = self.extent(element, placed)
        if box is None:
            return True
        return (
            box[0] >= region[0] - 0.5
            and box[1] >= region[1] - 0.5
            and box[2] <= region[2] + 0.5
            and box[3] <= region[3] + 0.5
        )

    def extent(self, element: ET.Element, placed: Matrix) -> Box | None:
        """Roughly what an element draws, on the page: its geometry's box and the width of
        its lines (its words as boxes of their size)."""

        boxes: list[Box] = []

        def walk(item: ET.Element, matrix: Matrix, depth: int) -> None:
            if depth > 40:
                return
            tag = _local(item.tag)
            if tag in SKIPPED:
                return
            if tag in LEAVES:
                segments = _outline_of(item, tag)
                if segments:
                    style = self.own(item)
                    width = (
                        _length(style.get("stroke-width"), 1.0)
                        if style.get("stroke", "none") != "none"
                        else 0.0
                    )
                    box = _segments_box(_mapped(segments, matrix))
                    if box:
                        pad = width * _scale_of(matrix) / 2.0
                        boxes.append((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
                return
            if tag == "image":
                x, y = _length(item.get("x")), _length(item.get("y"))
                w, h = _length(item.get("width")), _length(item.get("height"))
                corners = [
                    _apply(matrix, px, py)
                    for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
                ]
                boxes.append(_points_box(corners))
                return
            if tag in ("text", "flowRoot"):
                size = _font_size(self.own(item).get("font-size", "16"), 16.0)
                x, y = _length(item.get("x")), _length(item.get("y"))
                words = "".join(item.itertext())
                w = max(len(words), 1) * size * 0.6
                corners = [
                    _apply(matrix, px, py)
                    for px, py in (
                        (x - w, y - size),
                        (x + w, y - size),
                        (x + w, y + size / 3),
                        (x - w, y + size / 3),
                    )
                ]
                boxes.append(_points_box(corners))
                return
            if tag == "use":
                target = self.ids.get(_href(item).lstrip("#"))
                if target is not None and target not in self.using and len(self.using) < 30:
                    self.using.append(target)
                    try:
                        moved = _multiply(
                            matrix,
                            (1.0, 0.0, 0.0, 1.0, _length(item.get("x")), _length(item.get("y"))),
                        )
                        if _local(target.tag) == "symbol":
                            for child in target:
                                walk(
                                    child,
                                    _multiply(moved, _transform(child.get("transform"))),
                                    depth + 1,
                                )
                        else:
                            walk(
                                target,
                                _multiply(moved, _transform(target.get("transform"))),
                                depth + 1,
                            )
                    finally:
                        self.using.pop()
                return
            for child in item:
                if isinstance(child.tag, str):
                    walk(child, _multiply(matrix, _transform(child.get("transform"))), depth + 1)

        walk(element, placed, 0)
        return _union(boxes)

    # -- groups --

    def group(
        self,
        element: ET.Element,
        matrix: Matrix,
        style: dict[str, str],
        depth: int,
        *,
        outline: bool = False,
    ) -> list[_Made]:
        if _local(element.tag) == "switch":
            for child in element:
                if (
                    isinstance(child.tag, str)
                    and not child.get("requiredExtensions")
                    and _local(child.tag) != "foreignObject"
                ):
                    return self.element(child, matrix, style, depth + 1, outline=outline)
            return []
        words = element.get("aria-label")
        glyphs = outline or bool(words) or self.glyphs(element)
        inner = self.children(element, matrix, style, depth + 1, outline=glyphs)
        if glyphs and not outline:
            inner = _merged(inner)
        return self.grouped(element, inner, _fraction(style.get("opacity")), depth)

    def glyphs(self, element: ET.Element) -> bool:
        """Whether a group is words drawn as outlines: each thing in it a glyph placed by a
        ``use`` (as LaTeX's drawings, TexText's, are made)."""

        uses = [child for child in element.iter() if _local(child.tag) == "use"]
        if len(uses) < 2:
            return False
        named = 0
        for use in uses:
            ident = _href(use).lstrip("#")
            if re.match(r"(glyph|g\d+-\d+|font_\d+_\d+|text\d+-\d+)", ident):
                named += 1
        return named >= max(2, len(uses) * 0.8)

    def grouped(
        self, element: ET.Element, inner: list[_Made], opacity: float, depth: int
    ) -> list[_Made]:
        if not inner:
            return []
        ident = self.ident(element)
        if len(inner) == 1 and (not ident or "id" in inner[0].spec):
            only = inner[0]
            if opacity < 1.0:
                only.spec["opacity"] = round(float(only.spec.get("opacity", 1.0)) * opacity, 4)
            return [only]
        if depth >= 18:
            # (Nested deeper than a group may be: its shapes in the group over it.)
            if opacity < 1.0:
                for item in inner:
                    item.spec["opacity"] = round(float(item.spec.get("opacity", 1.0)) * opacity, 4)
            return inner
        spec = _group([item.spec for item in inner], ident)
        if opacity < 1.0:
            spec["opacity"] = round(opacity, 4)
        return [_Made(spec, _union([item.box for item in inner]) or inner[0].box)]

    def ident(self, element: ET.Element) -> str | None:
        """The name a shape keeps of what it was drawn from: the drawer's own (``encoder``,
        a layer's label), never a program's (``rect12``); one a connector names, whatever
        it is."""

        raw = element.get("id") or ""
        label = element.get(f"{{{INKSCAPE_NS}}}label") or ""
        if raw and raw in self.wanted:
            chosen = raw
        elif label and not _AUTO_ID.fullmatch(label) and not label.startswith("#"):
            chosen = _slug(label)
        elif raw and not _AUTO_ID.fullmatch(raw):
            chosen = raw
        else:
            return None
        if not chosen:
            return None
        base, n = chosen, 1
        while chosen in self.named:
            n += 1
            chosen = f"{base}-{n}"
        self.named.add(chosen)
        if raw in self.wanted:
            self.aliases[raw] = chosen
        return chosen

    def nested(
        self,
        element: ET.Element,
        matrix: Matrix,
        style: dict[str, str],
        depth: int,
        *,
        outline: bool = False,
    ) -> list[_Made]:
        """A nested ``<svg>``: its drawing fitted into its box (what overflows it drawn, not
        cut)."""

        x, y = _length(element.get("x")), _length(element.get("y"))
        width = _length(element.get("width"), whole=self.view[0]) if element.get("width") else 0.0
        height = (
            _length(element.get("height"), whole=self.view[1]) if element.get("height") else 0.0
        )
        view = _numbers(element.get("viewBox"))
        inner = (1.0, 0.0, 0.0, 1.0, x, y)
        if len(view) == 4 and view[2] > 0 and view[3] > 0:
            width, height = width or view[2], height or view[3]
            inner = _multiply(
                inner, _viewbox(view, width, height, element.get("preserveAspectRatio"))
            )
        made = self.children(element, _multiply(matrix, inner), style, depth + 1, outline=outline)
        return self.grouped(element, made, _fraction(style.get("opacity")), depth)

    def use(
        self,
        element: ET.Element,
        matrix: Matrix,
        style: dict[str, str],
        depth: int,
        *,
        outline: bool = False,
    ) -> list[_Made]:
        ident = _href(element).lstrip("#")
        target = self.ids.get(ident)
        if target is None or target in self.using or len(self.using) > 30:
            return []
        moved = _multiply(
            matrix, (1.0, 0.0, 0.0, 1.0, _length(element.get("x")), _length(element.get("y")))
        )
        self.using.append(target)
        try:
            if _local(target.tag) == "symbol":
                view = _numbers(target.get("viewBox"))
                if len(view) == 4 and view[2] > 0 and view[3] > 0:
                    width = _length(element.get("width")) or _length(target.get("width")) or view[2]
                    height = (
                        _length(element.get("height")) or _length(target.get("height")) or view[3]
                    )
                    moved = _multiply(
                        moved, _viewbox(view, width, height, target.get("preserveAspectRatio"))
                    )
                own = self.style(target, style)
                made = self.children(
                    target,
                    _multiply(moved, _transform(target.get("transform"))),
                    own,
                    depth + 1,
                    outline=outline,
                )
                return self.grouped(element, made, _fraction(style.get("opacity")), depth)
            made = self.element(target, moved, style, depth + 1, outline=outline)
        finally:
            self.using.pop()
        opacity = _fraction(style.get("opacity"))
        if opacity < 1.0:
            for item in made:
                item.spec["opacity"] = round(float(item.spec.get("opacity", 1.0)) * opacity, 4)
        return made

    # -- shapes --

    def leaf(
        self,
        element: ET.Element,
        tag: str,
        matrix: Matrix,
        style: dict[str, str],
        *,
        outline: bool = False,
    ) -> list[_Made]:
        segments = _outline_of(element, tag)
        if not segments:
            return []
        paint = self.paint(element, style, matrix)
        if paint is None:
            return []
        frame = _frame(matrix)
        ident = self.ident(element)
        made: list[_Made] = []
        if not outline and tag in ("rect", "circle", "ellipse") and not frame.skewed:
            made = self.boxed(element, tag, matrix, frame, paint)
        if not made:
            page = _mapped(segments, matrix)
            heads = self.markers(element, style, segments, matrix, paint) if not outline else None
            made = self.traced(element, tag, page, paint, heads, outline=outline)
        if ident and made:
            # (In place: a connector made of it is kept by it, to be glued once all is read.)
            first = made[0].spec
            named = {
                "kind": first["kind"],
                "id": ident,
                **{k: v for k, v in first.items() if k != "kind"},
            }
            first.clear()
            first.update(named)
        return made

    def boxed(
        self, element: ET.Element, tag: str, matrix: Matrix, frame: _Frame, paint: _Paint
    ) -> list[_Made]:
        """A rectangle or an oval as the box it is, turned as it is."""

        if tag == "rect":
            x, y = _length(element.get("x")), _length(element.get("y"))
            w, h = _length(element.get("width")), _length(element.get("height"))
            rx, ry = _radii(element, w, h)
            if w <= 0 or h <= 0:
                return []
            if abs(rx * frame.sx - ry * frame.sy) > 0.02 * max(rx * frame.sx, ry * frame.sy, 1e-9):
                return []  # (corners not round: its outline)
            corner = rx * frame.sx
            kind = "rounded-rectangle" if corner > 0.01 else "rectangle"
        else:
            if tag == "circle":
                cx, cy = _length(element.get("cx")), _length(element.get("cy"))
                rx = ry = _length(element.get("r"))
            else:
                cx, cy = _length(element.get("cx")), _length(element.get("cy"))
                rx, ry = _radii(element, math.inf, math.inf, ellipse=True)
            if rx <= 0 or ry <= 0:
                return []
            x, y, w, h = cx - rx, cy - ry, 2 * rx, 2 * ry
            kind, corner = "ellipse", 0.0
        centre = _apply(matrix, x + w / 2.0, y + h / 2.0)
        width, height = w * frame.sx, h * frame.sy
        turn = frame.turn
        if abs(turn - 180.0) < 1e-6 or turn < 1e-6 or abs(turn - 360.0) < 1e-6:
            turn = 0.0  # (a box turned half round is itself)
        if abs(turn - 90.0) < 1e-6 or abs(turn - 270.0) < 1e-6:
            width, height, turn = height, width, 0.0
        spec: dict[str, Any] = {
            "kind": kind,
            "at": [centre[0] - width / 2.0, centre[1] - height / 2.0],
            "size": [width, height],
        }
        if kind == "rounded-rectangle":
            spec["corner"] = corner
        if turn:
            spec["rotate"] = round(turn, 3)
        local = (spec["at"][0], spec["at"][1], width, height)
        self.painted(spec, paint, local, turn, element)
        corners = [
            freeform._turned(point, centre, turn)
            for point in (
                (local[0], local[1]),
                (local[0] + width, local[1]),
                (local[0] + width, local[1] + height),
                (local[0], local[1] + height),
            )
        ]
        return [_Made(spec, _padded(_points_box(corners), paint.width / 2.0))]

    def traced(
        self,
        element: ET.Element,
        tag: str,
        page: list,
        paint: _Paint,
        heads: _Heads | None,
        *,
        outline: bool = False,
    ) -> list[_Made]:
        """An outline as the shape it is: a line, an arrow, an elbow, a polyline, a box drawn
        as four lines -- or a path."""

        heads = heads or _Heads()
        if heads.moved is not None:
            page = heads.moved
        pieces = [index for index, segment in enumerate(page) if segment[0] == "M"]
        straight = all(segment[0] in ("M", "L", "Z") for segment in page)
        closes = page[-1][0] == "Z"
        points = [(segment[1], segment[2]) for segment in page if segment[0] in ("M", "L")]
        points = _distinct(points)
        spec: dict[str, Any] | None = None
        start, end = heads.start, heads.end
        # (An open outline that is filled is filled as if closed -- unless it holds nothing to
        # fill, a straight line.)
        open_fill = (
            paint.fill is not None
            and not closes
            and not (straight and len(_distinct(points)) == 2 and len(pieces) == 1)
            and _area(page) > 1e-6
        )
        if outline:
            spec = None
        elif straight and len(pieces) == 1 and not closes and not open_fill and len(points) >= 2:
            if len(points) == 2:
                kind = "double-arrow" if start and end else "arrow" if start or end else "line"
                a, b = points
                if start and not end:
                    a, b, start, end = b, a, None, start
                spec = {"kind": kind, "from": list(a), "to": list(b)}
            else:
                elbow = _elbow(points)
                if elbow is not None and (
                    start or end or element.get(f"{{{INKSCAPE_NS}}}connector-type")
                ):
                    spec = {
                        "kind": "elbow",
                        "from": list(points[0]),
                        "to": list(points[-1]),
                        **elbow,
                    }
                else:
                    spec = {"kind": "polyline", "points": [list(point) for point in points]}
        elif straight and len(pieces) == 1 and closes and len(points) >= 3:
            box = _rectangle(points)
            if box is not None and not (start or end):
                (cx, cy), (w, h), turn = box
                spec = {"kind": "rectangle", "at": [cx - w / 2.0, cy - h / 2.0], "size": [w, h]}
                if turn:
                    spec["rotate"] = round(turn, 3)
            elif not (start or end):
                spec = {
                    "kind": "polyline",
                    "points": [list(point) for point in points],
                    "closed": True,
                }
        if spec is None:
            try:
                data = pathdata.written(page)
                pathdata.parsed(data)
            except pathdata.PathError as error:
                self.approximate(f"An outline Flexo can't read was left out ({error}).")
                return []
            spec = {"kind": "path", "d": data}
            if paint.rule == "evenodd":
                spec["fill_rule"] = "evenodd"
        if start:
            spec["start"] = start
        if end:
            spec["end"] = end
        if heads.size is not None:
            spec["__head"] = heads.size
        geometry = freeform.geometry(_plain(spec))
        x, y, w, h = geometry.box
        self.painted(spec, paint, (x, y, w, h), float(spec.get("rotate") or 0.0), element)
        if spec["kind"] in freeform.LINES and spec["kind"] != "arc":
            spec.setdefault("start", "none")
            spec.setdefault("end", "none")
        box = _padded(
            freeform.bounds(_plain(spec)),
            paint.width / 2.0 + 2.0 * paint.width if (start or end) else paint.width / 2.0,
        )
        made = _Made(spec, box, paint.key if spec["kind"] == "path" else None)
        connected = [
            element.get(f"{{{INKSCAPE_NS}}}connection-{end_}") for end_ in ("start", "end")
        ]
        if spec["kind"] in freeform.LINES and any(connected):
            self.glued.append((spec, *(c.lstrip("#") if c else None for c in connected)))
        if heads.extra:
            group = [made, *heads.extra]
            return [
                _Made(
                    _group([item.spec for item in group], None),
                    _union([item.box for item in group]) or box,
                )
            ]
        return [made]

    # -- paint --

    def paint(self, element: ET.Element, style: Mapping[str, str], matrix: Matrix) -> _Paint | None:
        current = _colour(style.get("color"))[0] or "#000000"
        fill, fill_alpha, fill_gradient = self.colour_of(style.get("fill", "black"), current)
        stroke, stroke_alpha, stroke_gradient = self.colour_of(style.get("stroke", "none"), current)
        if stroke_gradient is not None:
            stroke = _middle(stroke_gradient, self)
            self.approximate("A line painted with a gradient is its middle colour.")
        width = _length(style.get("stroke-width"), 1.0, whole=math.hypot(*self.view) / math.sqrt(2))
        scale = _scale_of(matrix)
        if style.get("vector-effect", "").strip() != "non-scaling-stroke":
            width *= scale
        else:
            width *= POINTS_PER_PIXEL
        if width <= 0:
            stroke = None
        fill_opacity = _fraction(style.get("fill-opacity")) * fill_alpha
        stroke_opacity = _fraction(style.get("stroke-opacity")) * stroke_alpha
        dash: list[float] | None = None
        dashes = style.get("stroke-dasharray", "none").strip()
        if dashes and dashes != "none":
            values = [_length(part, 0.0) for part in re.split(r"[\s,]+", dashes) if part]
            if (
                values
                and any(value > 0 for value in values)
                and all(value >= 0 for value in values)
            ):
                if len(values) % 2:
                    values = values * 2
                factor = (
                    scale
                    if style.get("vector-effect", "").strip() != "non-scaling-stroke"
                    else POINTS_PER_PIXEL
                )
                dash = [value * factor for value in values]
                if _length(style.get("stroke-dashoffset"), 0.0):
                    self.approximate("A dash pattern's offset is drawn from the line's start.")
        cap = style.get("stroke-linecap", "butt").strip()
        join = style.get("stroke-linejoin", "miter").strip()
        join = {"miter-clip": "miter", "arcs": "round"}.get(join, join)
        rule = style.get("fill-rule", "nonzero").strip()
        role_fill = element.get("data-flexo-fill")
        role_stroke = element.get("data-flexo-stroke")
        return _Paint(
            fill=fill,
            fill_gradient=fill_gradient,
            fill_opacity=fill_opacity,
            stroke=stroke,
            stroke_opacity=stroke_opacity,
            width=width if stroke else 0.0,
            dash=dash,
            cap=cap if cap in freeform.CAPS else "butt",
            join=join if join in freeform.JOINS else "miter",
            rule="evenodd" if rule == "evenodd" else "nonzero",
            opacity=_fraction(style.get("opacity")),
            fill_role=role_fill,
            stroke_role=role_stroke,
            matrix=matrix,
        )

    def colour_of(self, value: str, current: str) -> tuple[str | None, float, ET.Element | None]:
        """A paint as a colour, its alpha, and the gradient it is (if it is one)."""

        value = (value or "").strip()
        if value.startswith("url("):
            target = self.target(value)
            fallback = value[value.find(")") + 1 :].strip()
            if target is not None and _local(target.tag) in ("linearGradient", "radialGradient"):
                stops = self.stops(target)
                if len(stops) == 1:
                    return stops[0][1], stops[0][2], None
                if stops:
                    return stops[-1][1], 1.0, target
                return None, 1.0, None
            if fallback:
                colour, alpha = _colour(fallback, current)
                return colour, alpha, None
            return None, 1.0, None
        colour, alpha = _colour(value, current)
        return colour, alpha, None

    def painted(
        self,
        spec: dict[str, Any],
        paint: _Paint,
        box: tuple[float, float, float, float],
        turn: float,
        element: ET.Element,
    ) -> None:
        """``spec`` painted as ``paint`` says: each colour by the theme's name where it is the
        theme's."""

        closed = freeform.closed(spec)
        if closed or spec["kind"] == "path":
            if paint.fill_gradient is not None:
                gradient = self.gradient(
                    paint.fill_gradient, element, spec, box, turn, paint.matrix
                )
                spec["fill"] = gradient if gradient is not None else "none"
            else:
                spec["fill"] = (
                    self.colours.name(paint.fill, paint.fill_role) if paint.fill else "none"
                )
            if paint.fill and paint.fill_opacity < 1.0:
                spec["fill_opacity"] = round(paint.fill_opacity, 3)
        opacity = paint.opacity
        if paint.stroke:
            spec["line"] = self.colours.name(paint.stroke, paint.stroke_role)
            spec["line_width"] = paint.width
            if paint.stroke_opacity < 1.0:
                if not (paint.fill and (closed or spec["kind"] == "path")):
                    # (A line alone: its opacity the shape's.)
                    opacity *= paint.stroke_opacity
                else:
                    spec["line_opacity"] = round(paint.stroke_opacity, 3)
            if paint.dash:
                spec["dash"] = _dash_of(paint.dash, paint.width, paint.cap)
            spec["cap"] = paint.cap
            spec["join"] = paint.join
        else:
            spec["line"] = "none"
        if opacity < 1.0:
            spec["opacity"] = round(opacity, 4)

    # -- gradients --

    def chain(self, gradient: ET.Element) -> list[ET.Element]:
        """A gradient and those it names (``href``), nearest first."""

        out = [gradient]
        while len(out) < 16:
            target = self.ids.get(_href(out[-1]).lstrip("#"))
            if (
                target is None
                or target in out
                or _local(target.tag) not in ("linearGradient", "radialGradient")
            ):
                break
            out.append(target)
        return out

    def stops(self, gradient: ET.Element) -> list[tuple[float, str, float]]:
        """A gradient's stops -- its own, or those of the gradient it names: (offset, colour,
        opacity)."""

        for item in self.chain(gradient):
            found = [child for child in item if _local(child.tag) == "stop"]
            if not found:
                continue
            out: list[tuple[float, str, float]] = []
            last = 0.0
            for stop in found:
                own = self.own(stop)
                offset = _fraction(stop.get("offset") or own.get("offset"), 0.0)
                last = max(last, offset)
                colour, alpha = _colour(own.get("stop-color", "black"))
                opacity = _fraction(own.get("stop-opacity")) * alpha
                out.append((last, colour or "#000000", opacity))
            return out
        return []

    def gradient(
        self,
        gradient: ET.Element,
        element: ET.Element,
        spec: Mapping[str, Any],
        box: tuple[float, float, float, float],
        turn: float,
        paint_matrix: Matrix = IDENTITY,
    ) -> dict[str, Any] | None:
        """A gradient fill as a shape's: its stops placed along its own box (``box``,
        unturned, turned ``turn`` about its middle on the page), where the gradient puts
        them; ``paint_matrix`` is what the shape was drawn through."""

        chain = self.chain(gradient)

        def said(name: str) -> str | None:
            for item in chain:
                if item.get(name) is not None:
                    return item.get(name)
            return None

        stops = self.stops(gradient)
        if not stops:
            return None
        kind = "radial" if _local(gradient.tag) == "radialGradient" else "linear"
        units = said("gradientUnits") or "objectBoundingBox"
        spread = (said("spreadMethod") or "pad").strip()
        matrix = paint_matrix
        local_box = _segments_box(_outline_of(element, _local(element.tag)) or [])
        if local_box is None:
            return None
        bx, by = local_box[0], local_box[1]
        bw, bh = local_box[2] - local_box[0], local_box[3] - local_box[1]
        to_user = _transform(said("gradientTransform"))
        if units == "objectBoundingBox":
            if bw <= 0 or bh <= 0:
                return None
            to_user = _multiply((bw, 0.0, 0.0, bh, bx, by), to_user)
        x, y, w, h = box
        centre = (x + w / 2.0, y + h / 2.0)
        unturn = _multiply(
            _multiply((1.0, 0.0, 0.0, 1.0, centre[0], centre[1]), _rotation(-turn)),
            (1.0, 0.0, 0.0, 1.0, -centre[0], -centre[1]),
        )
        whole = _multiply(unturn, _multiply(matrix, to_user))

        def length(name: str, default: str) -> float:
            value = said(name) or default
            if units == "objectBoundingBox":
                return (
                    _fraction(value, 0.0)
                    if value.strip().endswith("%")
                    else float(_numbers(value)[0] if _numbers(value) else 0.0)
                )
            return _length(value, whole=math.hypot(*self.view) / math.sqrt(2))

        if kind == "linear":
            p1 = (length("x1", "0%"), length("y1", "0%"))
            p2 = (length("x2", "100%"), length("y2", "0%"))
            d = (p2[0] - p1[0], p2[1] - p1[1])
            squared = d[0] ** 2 + d[1] ** 2
            if squared < 1e-18:
                return None
            inverse = _inverse(whole)
            # t(q) = (inverse(q) - p1) . d / |d|^2, an affine function of q: g . q + c
            ia, ib, ic, id_, ie, if_ = inverse
            gx = (ia * d[0] + ib * d[1]) / squared
            gy = (ic * d[0] + id_ * d[1]) / squared
            c = ((ie - p1[0]) * d[0] + (if_ - p1[1]) * d[1]) / squared
            strength = math.hypot(gx, gy)
            if strength < 1e-12 or (w <= 0 and h <= 0):
                return None
            ux, uy = gx / strength, gy / strength
            span = abs(w * ux) + abs(h * uy)
            alpha = strength * span
            beta = strength * (centre[0] * ux + centre[1] * uy - span / 2.0) + c
            placed = _unrolled(stops, alpha, beta, spread)
            angle = math.degrees(math.atan2(uy, ux)) % 360.0
            out: dict[str, Any] = {"gradient": "linear", "angle": round(angle, 2)}
        else:
            cx, cy = length("cx", "50%"), length("cy", "50%")
            r = length("r", "50%")
            fx = said("fx")
            fy = said("fy")
            if r <= 0:
                return None
            if (fx is not None and abs(length("fx", "50%") - cx) > 0.01 * r) or (
                fy is not None and abs(length("fy", "50%") - cy) > 0.01 * r
            ):
                self.approximate(
                    "A radial gradient's focus off its centre is drawn from its centre."
                )
            middle = _apply(whole, cx, cy)
            ax, ay = _vector(whole, r, 0.0)
            vx, vy = _vector(whole, 0.0, r)
            if abs(ax * vx + ay * vy) > 1e-6 * (math.hypot(ax, ay) * math.hypot(vx, vy)) or (
                abs(ay) > 1e-6 * math.hypot(ax, ay) and abs(ax) > 1e-6 * math.hypot(ax, ay)
            ):
                self.approximate("A radial gradient stretched aslant is drawn upright.")
            rx = math.hypot(ax, vx) if abs(ay) > abs(ax) else math.hypot(ax, ay)
            ry = math.hypot(ay, vy) if abs(ay) > abs(ax) else math.hypot(vx, vy)
            if abs(ay) > abs(ax):
                rx, ry = math.hypot(vx, vy), math.hypot(ax, ay)
            if w <= 0 or h <= 0:
                return None
            reach = 1.0
            if spread in ("repeat", "reflect"):
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                reach = max(
                    math.hypot((px - middle[0]) / rx, (py - middle[1]) / ry) for px, py in corners
                )
                reach = min(max(1.0, math.ceil(reach)), 8.0)
            placed = _unrolled(stops, reach, 0.0, spread)
            out = {
                "gradient": "radial",
                "centre": [round((middle[0] - x) / w, 4), round((middle[1] - y) / h, 4)],
            }
            radius = [round(rx * reach / w, 4), round(ry * reach / h, 4)]
            out["radius"] = radius[0] if abs(radius[0] - radius[1]) < 1e-4 else radius
        out["stops"] = [
            [round(offset, 4), self.colours.name(colour)]
            + ([round(opacity, 3)] if opacity < 1.0 else [])
            for offset, colour, opacity in placed
        ]
        return out

    # -- arrowheads --

    def markers(
        self,
        element: ET.Element,
        style: Mapping[str, str],
        segments: list,
        matrix: Matrix,
        paint: _Paint,
    ) -> _Heads | None:
        names = {key: style.get(f"marker-{key}", "none").strip() for key in ("start", "mid", "end")}
        if all(not value or value == "none" for value in names.values()):
            return None
        heads = _Heads()
        local_width = _length(style.get("stroke-width"), 1.0)
        vertices = _vertices(segments)
        if len(vertices) < 2:
            return None
        page = _mapped(segments, matrix)
        moved = [list(segment) for segment in page]
        extra: list[_Made] = []
        found: dict[str, tuple[str, float, float]] = {}
        # (A closed outline has no ends for arrowheads: its markers are drawn as they are.)
        shut = segments[-1][0] == "Z"
        for which in ("start", "end"):
            marker = self.target(names[which])
            if marker is None or _local(marker.tag) != "marker":
                continue
            vertex = vertices[0] if which == "start" else vertices[-1]
            way_in, way_out = vertex[2], vertex[3]
            outward_local = (-way_out[0], -way_out[1]) if which == "start" else way_in
            drawn = self.marker_outline(marker, vertex, which, matrix, local_width, paint)
            if not drawn:
                continue
            tip = _apply(matrix, vertex[0], vertex[1])
            way = _vector(matrix, *outward_local)
            length = math.hypot(*way)
            way = (way[0] / length, way[1] / length) if length > 1e-12 else (1.0, 0.0)
            head = None if shut else _head_of(drawn, tip, way, paint)
            if head is None:
                extra += [self.marker_shape(piece) for piece in drawn]
                continue
            found[which] = head
        if names["mid"] and names["mid"] != "none":
            marker = self.target(names["mid"])
            if marker is not None and _local(marker.tag) == "marker":
                for vertex in vertices[1:-1]:
                    drawn = self.marker_outline(marker, vertex, "mid", matrix, local_width, paint)
                    extra += [self.marker_shape(piece) for piece in drawn]
        scales = {
            which: _head_scale(kind, size, paint.width)
            for which, (kind, size, _shift) in found.items()
        }
        if len(scales) == 2 and max(scales.values()) > 1.3 * min(scales.values()):
            # (One shape has one size of arrowhead: the smaller drawn as it is.)
            smaller = "start" if scales["start"] < scales["end"] else "end"
            vertex = vertices[0] if smaller == "start" else vertices[-1]
            marker = self.target(names[smaller])
            drawn = self.marker_outline(marker, vertex, smaller, matrix, local_width, paint)
            extra += [self.marker_shape(piece) for piece in drawn]
            del found[smaller]
        for which, (kind, _size, shift) in found.items():
            setattr(heads, which, kind)
            if abs(shift) > 1e-3:
                _shift_end(moved, which, shift)
        if found:
            heads.size = {which: (kind, size) for which, (kind, size, _shift) in found.items()}
            heads.width = paint.width
        heads.moved = [tuple(segment) for segment in moved]
        heads.extra = extra
        return heads

    def marker_outline(
        self,
        marker: ET.Element,
        vertex: tuple,
        which: str,
        matrix: Matrix,
        stroke_width: float,
        paint: _Paint,
    ) -> list[_Piece]:
        """A marker as drawn at ``vertex``: each of its outlines on the page, painted."""

        x, y, way_in, way_out = vertex
        orient = (marker.get("orient") or "0").strip()
        if orient in ("auto", "auto-start-reverse"):
            # (Along the way the line runs there; at its start, reversed, it points out of it.)
            if which == "start":
                direction = way_out if orient == "auto" else (-way_out[0], -way_out[1])
            elif which == "end":
                direction = way_in
            else:
                direction = (way_in[0] + way_out[0], way_in[1] + way_out[1])
                if math.hypot(*direction) < 1e-9:
                    direction = way_out
            angle = math.atan2(direction[1], direction[0])
        else:
            angle = math.radians(_numbers(orient)[0] if _numbers(orient) else 0.0)
        units = marker.get("markerUnits", "strokeWidth")
        scale = stroke_width if units == "strokeWidth" else 1.0
        view = _numbers(marker.get("viewBox"))
        ref = (_length(marker.get("refX")), _length(marker.get("refY")))
        place = _multiply(
            _multiply(matrix, (1.0, 0.0, 0.0, 1.0, x, y)),
            _multiply(_rotation(math.degrees(angle)), (scale, 0.0, 0.0, scale, 0.0, 0.0)),
        )
        if len(view) == 4 and view[2] > 0 and view[3] > 0:
            mw = _length(marker.get("markerWidth"), 3.0)
            mh = _length(marker.get("markerHeight"), 3.0)
            fit = _viewbox(view, mw, mh, marker.get("preserveAspectRatio"))
            rx, ry = _apply(fit, *ref)
            place = _multiply(place, _multiply((1.0, 0.0, 0.0, 1.0, -rx, -ry), fit))
        else:
            place = _multiply(place, (1.0, 0.0, 0.0, 1.0, -ref[0], -ref[1]))
        style = self.style(
            marker, {key: value for key, value in INITIAL.items() if key in INHERITED}
        )
        out: list[_Piece] = []

        def walk(item: ET.Element, at: Matrix, inherited: dict[str, str], depth: int) -> None:
            if depth > 12:
                return
            for child in item:
                if not isinstance(child.tag, str):
                    continue
                tag = _local(child.tag)
                own = self.style(child, inherited)
                if own.get("display", "").strip() == "none":
                    continue
                placed = _multiply(at, _transform(child.get("transform")))
                if tag in ("g", "a"):
                    walk(child, placed, own, depth + 1)
                elif tag == "use":
                    target = self.ids.get(_href(child).lstrip("#"))
                    if target is not None and target is not item:
                        holder = ET.Element("g")
                        holder.append(target)
                        walk(
                            holder,
                            _multiply(
                                placed,
                                (
                                    1.0,
                                    0.0,
                                    0.0,
                                    1.0,
                                    _length(child.get("x")),
                                    _length(child.get("y")),
                                ),
                            ),
                            own,
                            depth + 1,
                        )
                elif tag in LEAVES:
                    segments = _outline_of(child, tag)
                    if not segments:
                        continue
                    fill = self.context(own.get("fill", "black"), paint, "fill")
                    stroke = self.context(own.get("stroke", "none"), paint, "stroke")
                    width = _length(own.get("stroke-width"), 1.0) * _scale_of(placed)
                    out.append(
                        _Piece(
                            _mapped(segments, placed),
                            fill,
                            stroke if width > 0 else None,
                            width,
                            _fraction(own.get("fill-opacity")) * _fraction(own.get("opacity")),
                            own.get("stroke-linejoin", "miter").strip(),
                            own.get("fill-rule", "nonzero").strip(),
                        )
                    )

        walk(marker, place, style, 0)
        return out

    def context(self, value: str, paint: _Paint, part: str) -> str | None:
        value = (value or "").strip()
        if value == "context-stroke":
            return paint.stroke
        if value == "context-fill":
            return paint.fill
        colour, _alpha, _gradient = self.colour_of(value, paint.stroke or "#000000")
        return colour

    def marker_shape(self, piece: _Piece) -> _Made:
        """A marker Flexo has no arrowhead for, as the shape it draws."""

        spec: dict[str, Any] = {"kind": "path", "d": pathdata.written(piece.segments)}
        if piece.rule == "evenodd":
            spec["fill_rule"] = "evenodd"
        spec["fill"] = self.colours.name(piece.fill) if piece.fill else "none"
        if piece.stroke:
            spec["line"] = self.colours.name(piece.stroke)
            spec["line_width"] = piece.width
            spec["join"] = piece.join if piece.join in freeform.JOINS else "miter"
        else:
            spec["line"] = "none"
        if piece.opacity < 1.0:
            spec["fill_opacity"] = round(piece.opacity, 3)
        box = _segments_box(piece.segments) or (0.0, 0.0, 0.0, 0.0)
        return _Made(spec, _padded(box, piece.width / 2.0))

    # -- words --

    def text(
        self, element: ET.Element, tag: str, matrix: Matrix, style: dict[str, str]
    ) -> list[_Made]:
        if any(_local(child.tag) == "textPath" for child in element.iter()):
            return self.pictured_as(
                element, matrix, style, "words set along a path", placed_already=True
            )
        if tag == "flowRoot":
            region = next((child for child in element if _local(child.tag) == "flowRegion"), None)
            shape = None
            if region is not None:
                shape = next(
                    (child for child in region.iter() if _local(child.tag) in ("rect",)), None
                )
            paragraphs = [
                child for child in element if _local(child.tag) in ("flowPara", "flowDiv")
            ]
            lines = [
                self.runs_of(paragraph, self.style(paragraph, style)) for paragraph in paragraphs
            ]
            if shape is None:
                return []
            flow_matrix = _multiply(
                matrix,
                _multiply(_transform(region.get("transform")), _transform(shape.get("transform"))),
            )
            box = (
                _length(shape.get("x")),
                _length(shape.get("y")),
                _length(shape.get("width")),
                _length(shape.get("height")),
            )
            align = _align_of(style)
            return self.flowed(element, lines, box, flow_matrix, style, align)
        inside = self.target(style.get("shape-inside", ""))
        if inside is not None and _local(inside.tag) == "rect":
            lines = self.lines(element, style)
            joined = _joined_lines(lines)
            region_matrix = _multiply(matrix, _transform(inside.get("transform")))
            box = (
                _length(inside.get("x")),
                _length(inside.get("y")),
                _length(inside.get("width")),
                _length(inside.get("height")),
            )
            return self.flowed(element, joined, box, region_matrix, style, _align_of(style))
        lines = self.lines(element, style)
        if not any(run.text.strip() for line in lines for run in line.runs):
            return []
        wrap = style.get("inline-size", "").strip()
        if wrap and _length(wrap) > 0 and lines:
            width = _length(wrap)
            first = lines[0]
            anchor = first.anchor
            left = first.x - {"start": 0.0, "middle": width / 2.0, "end": width}[anchor]
            top = first.y - first.size * 1.0
            return self.flowed(
                element, _joined_lines(lines), (left, top, width, 0.0), matrix, style, anchor
            )
        blocks = _blocks(lines)
        made: list[_Made] = []
        for block in blocks:
            one = self.words_box(element, block, matrix)
            if one is not None:
                made.append(one)
        if len(made) > 1:
            return [
                _Made(
                    _group([item.spec for item in made], self.ident(element)),
                    _union([item.box for item in made]) or made[0].box,
                )
            ]
        if made and (ident := self.ident(element)):
            made[0].spec = {
                "kind": "text",
                "id": ident,
                **{k: v for k, v in made[0].spec.items() if k != "kind"},
            }
        return made

    def lines(self, element: ET.Element, style: dict[str, str]) -> list[_Line]:
        """A text's lines: where each starts, how it is anchored, and its runs."""

        lines: list[_Line] = []
        preserve = element.get(
            "{http://www.w3.org/XML/1998/namespace}space"
        ) == "preserve" or style.get("white-space", "").strip() in (
            "pre",
            "pre-wrap",
            "break-spaces",
        )
        x0 = (_numbers(element.get("x")) or [0.0])[0]
        y0 = (_numbers(element.get("y")) or [0.0])[0]
        pen = [x0, y0]

        def begin(x: float, y: float, own: Mapping[str, str]) -> _Line:
            line = _Line(x, y, _anchor_of(own), [], float(own.get("font-size", "16")))
            lines.append(line)
            return line

        current = begin(x0, y0, style)
        if len(_numbers(element.get("x"))) > 1:
            self.approximate("Words placed letter by letter are set as one run.")

        def add(words: str | None, own: Mapping[str, str]) -> None:
            if not words:
                return
            if not preserve:
                words = re.sub(r"[\n\r\t]+", " " if True else "", words)
                words = re.sub(r" +", " ", words)
            else:
                words = words.replace("\n", " ").replace("\t", " ")
            current.runs.append(self.run(words, own))

        def walk(node: ET.Element, own: Mapping[str, str], depth: int) -> None:
            nonlocal current
            add(node.text, own)
            for child in node:
                if not isinstance(child.tag, str):
                    continue
                tag = _local(child.tag)
                if tag in ("tspan", "a", "tref", "altGlyph"):
                    inner = self.style(child, own)
                    if inner.get("display", "").strip() == "none":
                        add(child.tail, own)
                        continue
                    xs, ys = _numbers(child.get("x")), _numbers(child.get("y"))
                    dys = _numbers(child.get("dy"))
                    role = child.get(f"{{{SODIPODI_NS}}}role") == "line"
                    new_y = ys[0] if ys else (pen[1] + dys[0] if dys and role else None)
                    if role or (
                        new_y is not None and abs(new_y - current.y) > 1e-6 and current.runs
                    ):
                        x = xs[0] if xs else current.x
                        y = new_y if new_y is not None else current.y + current.size * 1.25
                        if current.runs or role:
                            current = begin(x, y, inner)
                        else:
                            current.x, current.y, current.anchor = x, y, _anchor_of(inner)
                        pen[0], pen[1] = x, y
                    elif new_y is not None and not current.runs:
                        current.y = new_y
                        if xs:
                            current.x = xs[0]
                        current.anchor = _anchor_of(inner)
                        pen[1] = new_y
                    if depth < 8:
                        walk(child, inner, depth + 1)
                add(child.tail, own)

        walk(element, style, 0)
        if not preserve:
            for line in lines:
                if line.runs:
                    line.runs[0].text = line.runs[0].text.lstrip(" ")
                    line.runs[-1].text = line.runs[-1].text.rstrip(" ")
        # (Inkscape keeps an empty line as an empty tspan: a line still.)
        while lines and not any(run.text.strip() for run in lines[-1].runs):
            lines.pop()
        return lines

    def runs_of(self, paragraph: ET.Element, style: dict[str, str]) -> _Line:
        line = _Line(0.0, 0.0, _anchor_of(style), [], float(style.get("font-size", "16")))

        def walk(node: ET.Element, own: Mapping[str, str]) -> None:
            if node.text:
                line.runs.append(self.run(node.text, own))
            for child in node:
                if isinstance(child.tag, str) and _local(child.tag) in ("flowSpan", "tspan"):
                    walk(child, self.style(child, own))
                if child.tail:
                    line.runs.append(self.run(child.tail, own))

        walk(paragraph, style)
        return line

    def run(self, words: str, own: Mapping[str, str]) -> _Run:
        weight = _weight(own.get("font-weight", "normal"))
        italic = own.get("font-style", "normal").strip() in ("italic", "oblique")
        current = _colour(own.get("color"))[0] or "#000000"
        fill, _alpha, gradient = self.colour_of(own.get("fill", "black"), current)
        if gradient is not None:
            fill = _middle(gradient, self)
            self.approximate("Words painted with a gradient are its middle colour.")
        shift = own.get("baseline-shift", "").strip()
        size = float(own.get("font-size", "16"))
        spacing = own.get("letter-spacing", "normal").strip()
        if (
            spacing not in ("normal", "0", "0px", "")
            and abs(_length(spacing, 0.0, font=size)) > 0.04 * size
        ):
            self.approximate("Letters spaced apart are set at their font's own spacing.")
        if own.get("text-decoration", "none").strip() not in ("none", "", "initial"):
            self.approximate("Underlined or struck-through words are set plain.")
        return _Run(
            words,
            weight >= 600,
            italic,
            fill,
            size,
            _shift_of(shift),
            _family_of(own.get("font-family", "sans-serif")),
        )

    def family(self, name: str | None) -> str | None:
        """A family Flexo has by this name, or None (the page's own font)."""

        if not name:
            return None
        if name not in self.families:
            from flexo.fonts import family_faces

            found = None
            generic = name.strip().lower()
            # (A serif, a monospace or a hand as such: the face Flexo sets them in, as a
            # drawing's picture is restyled. Sans serif: the page's own.)
            wanted = GENERIC_FACES.get(generic) if generic in GENERIC_FAMILIES else name
            if wanted:
                try:
                    found = wanted if family_faces(wanted) else None
                except Exception:
                    found = None
            self.families[name] = found
        return self.families[name]

    def measure(
        self, family: str | None, size: float, runs: Sequence[_Run]
    ) -> tuple[float, float, float]:
        """Words' width, the drop from a box's top to their first baseline, and their line's
        height, in points, set as a text shape sets them."""

        from flexo.ir.semantic import TextRun
        from flexo.style import TypographyStyle
        from flexo.text import TextMeasurer
        from flexo.units import pt

        key = (family, round(size, 3))
        measurer = self.measurers.get(key)
        if measurer is None:
            typography = TypographyStyle(size=pt(max(size, 0.5)))
            if family:
                typography = typography.with_family(family)
            measurer = self.measurers[key] = TextMeasurer(typography)
        pieces = tuple(
            TextRun(run.text, 700 if run.bold else 400, run.italic) for run in runs if run.text
        )
        if not pieces:
            pieces = (TextRun(" "),)
        try:
            metrics = measurer.measure(pieces)
        except Exception:
            return (sum(len(run.text) for run in runs) * size * 0.55, size * 0.95, size * 1.22)
        return metrics.width, metrics.baseline, metrics.line_height

    def words_box(self, element: ET.Element, block: list[_Line], matrix: Matrix) -> _Made | None:
        """Lines of words, one under another, as a box of them."""

        runs = [run for line in block for run in line.runs]
        base = _base(runs)
        if base is None:
            return None
        frame = _frame(matrix)
        scale = frame.sy if not frame.skewed else _scale_of(matrix)
        if frame.skewed or abs(frame.sx - frame.sy) > 0.02 * max(frame.sx, frame.sy):
            self.approximate("Words stretched or slanted by a transform are set upright.")
        if frame.mirrored:
            self.approximate("Mirrored words are set the right way round.")
        size = base.size * scale
        family = self.family(base.family)
        widths = []
        baseline = line_height = 0.0
        for line in block:
            width, baseline_here, line_height_here = self.measure(family, size, line.runs)
            widths.append(width)
            if not baseline:
                baseline, line_height = baseline_here, line_height_here
        first = block[0]
        anchor = first.anchor
        if frame.mirrored:
            # (Words mirrored left to right are set the right way round where they were:
            # where they started, they end.)
            anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
        widest = max(widths) if widths else 0.0
        height = line_height * len(block)
        # (In the text's own frame, unturned, in points: its first baseline at (0, 0).)
        # (Words set from their middle or their end are given room either side of them: a
        # face a little wider than the one measured never breaks them into two lines.)
        roomy = anchor != "start"
        box_width = widest * 1.15 + 4.0 if roomy else widest
        local_left = -{"start": 0.0, "middle": box_width / 2.0, "end": box_width}[anchor]
        local_top = -baseline
        origin = _apply(matrix, first.x, first.y)
        turn = _upright_turn(matrix)
        centre_local = (local_left + box_width / 2.0, local_top + height / 2.0)
        centre = freeform._turned(
            (origin[0] + centre_local[0], origin[1] + centre_local[1]), origin, turn
        )
        at = [centre[0] - box_width / 2.0, centre[1] - height / 2.0]
        text, bold, italic, colour = _words(block, base, self.markup, self.colours)
        spec: dict[str, Any] = {"kind": "text", "at": at}
        if roomy:
            spec["width"] = box_width
        if turn:
            spec["rotate"] = round(turn, 3)
        spec["text"] = text
        spec["font_size"] = size
        if bold:
            spec["bold"] = True
        if italic:
            spec["italic"] = True
        if colour and colour != "ink":
            spec["colour"] = colour
        if family:
            spec["font"] = family
        spec["align"] = anchor
        spec["padding"] = 0.0
        corners = [
            freeform._turned(point, centre, turn)
            for point in (
                (at[0], at[1]),
                (at[0] + box_width, at[1]),
                (at[0] + box_width, at[1] + height),
                (at[0], at[1] + height),
            )
        ]
        spec["__size"] = [box_width, height]
        return _Made(
            {key: value for key, value in spec.items() if value is not None}, _points_box(corners)
        )

    def flowed(
        self,
        element: ET.Element,
        lines: list[_Line],
        box: tuple[float, float, float, float],
        matrix: Matrix,
        style: dict[str, str],
        align: str,
    ) -> list[_Made]:
        """Flowed words: a box as wide as what they flow in, its words wrapped in it."""

        runs = [run for line in lines for run in line.runs]
        base = _base(runs)
        if base is None:
            return []
        frame = _frame(matrix)
        scale = frame.sy
        x, y, w, h = box
        corners = [
            _apply(matrix, px, py) for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
        ]
        centre = _apply(matrix, x + w / 2.0, y + h / 2.0)
        width, height = w * frame.sx, (h * frame.sy if h else 0.0)
        size = base.size * scale
        family = self.family(base.family)
        _measured, _baseline, line_height = self.measure(family, size, base and [base])
        height = height or line_height * max(len(lines), 1)
        turn = 0.0 if frame.turn < 1e-6 or abs(frame.turn - 360.0) < 1e-6 else frame.turn
        text, bold, italic, colour = _words(lines, base, self.markup, self.colours)
        spec: dict[str, Any] = {
            "kind": "text",
            "at": [centre[0] - width / 2.0, centre[1] - height / 2.0] if h else list(corners[0]),
            "width": max(width, 1.0),
        }
        if turn:
            spec["rotate"] = round(turn, 3)
        spec["text"] = text
        spec["font_size"] = size
        if bold:
            spec["bold"] = True
        if italic:
            spec["italic"] = True
        if colour and colour != "ink":
            spec["colour"] = colour
        if family:
            spec["font"] = family
        spec["align"] = align
        spec["padding"] = 0.0
        spec["__size"] = [max(width, 1.0), height]
        ident = self.ident(element)
        if ident:
            spec = {"kind": "text", "id": ident, **{k: v for k, v in spec.items() if k != "kind"}}
        return [
            _Made(
                spec,
                _points_box(corners)
                if h
                else (corners[0][0], corners[0][1], corners[0][0] + width, corners[0][1] + height),
            )
        ]

    # -- pictures --

    def image(
        self,
        element: ET.Element,
        placed: Matrix,
        style: dict[str, str],
        matrix: Matrix,
        inherited: dict[str, str],
    ) -> list[_Made]:
        """A picture in the drawing: its bitmap a ``picture`` of its own, where it was."""

        href = _href(element).strip()
        data, suffix = _picture_bytes(href)
        if data is None:
            self.keep(
                f"A picture linked from {href[:60] or 'nowhere'} is left out: only pictures "
                "carried in the drawing come with it."
            )
            return []
        frame = _frame(placed)
        fitting = (element.get("preserveAspectRatio") or "xMidYMid meet").strip()
        if frame.skewed or suffix == ".svg" or "slice" in fitting:
            return self.pictured_as(element, matrix, inherited, "a picture")
        x, y = _length(element.get("x")), _length(element.get("y"))
        w, h = _length(element.get("width")), _length(element.get("height"))
        natural = _pixels(data)
        if natural and fitting != "none" and w > 0 and h > 0:
            x, y, w, h = _meet((x, y, w, h), natural, fitting)
        if w <= 0 or h <= 0:
            return []
        source = self.store(data, suffix)
        centre = _apply(placed, x + w / 2.0, y + h / 2.0)
        width, height = w * frame.sx, h * frame.sy
        turn = 0.0 if frame.turn < 1e-6 or abs(frame.turn - 360.0) < 1e-6 else frame.turn
        spec: dict[str, Any] = {
            "kind": "picture",
            "at": [centre[0] - width / 2.0, centre[1] - height / 2.0],
            "size": [width, height],
        }
        if turn:
            spec["rotate"] = round(turn, 3)
        if frame.mirrored:
            spec["flip"] = "horizontal"
        spec["source"] = source
        opacity = _fraction(style.get("opacity"))
        if opacity < 1.0:
            spec["opacity"] = round(opacity, 4)
        ident = self.ident(element)
        if ident:
            spec = {
                "kind": "picture",
                "id": ident,
                **{k: v for k, v in spec.items() if k != "kind"},
            }
        corners = [
            freeform._turned(p, centre, turn)
            for p in (
                (spec["at"][0], spec["at"][1]),
                (spec["at"][0] + width, spec["at"][1]),
                (spec["at"][0] + width, spec["at"][1] + height),
                (spec["at"][0], spec["at"][1] + height),
            )
        ]
        self.keep("A picture is kept as it is, a picture of its own.")
        return [_Made(spec, _points_box(corners))]

    def store(self, data: bytes, suffix: str) -> str:
        self.pictured += 1
        if self.picture is not None:
            return self.picture(data, suffix)
        name = f"{self.name}-{self.pictured}{suffix}"
        self.files[name] = data
        return name

    def pictured_as(
        self,
        element: ET.Element,
        matrix: Matrix,
        inherited: Mapping[str, str],
        why: str,
        *,
        placed_already: bool = False,
    ) -> list[_Made]:
        """``element`` kept exactly as drawn: an SVG of it alone, with what it needs (its
        clip, its filter, its gradients, the style sheet), placed where it was."""

        placed = (
            matrix if placed_already else _multiply(matrix, _transform(element.get("transform")))
        )
        parent = (
            matrix
            if not placed_already
            else _multiply(matrix, _inverse(_transform(element.get("transform"))))
        )
        box = self.extent(element, placed)
        if box is None:
            return []
        style = self.own(element)
        left, top, right, bottom = box
        grow = 0.0
        if style.get("filter", "none").strip() not in ("none", ""):
            grow = 0.1 * max(right - left, bottom - top) + 2.0
            target = self.target(style.get("filter"))
            if target is not None:
                for blur in target.iter():
                    if _local(blur.tag) == "feGaussianBlur":
                        deviation = max(_numbers(blur.get("stdDeviation")) or [0.0])
                        grow = max(grow, 3.0 * deviation * _scale_of(placed) + 1.0)
                    if _local(blur.tag) in ("feOffset", "feDropShadow"):
                        shift = max(
                            [abs(v) for v in _numbers(blur.get("dx")) + _numbers(blur.get("dy"))]
                            or [0.0]
                        )
                        grow += shift * _scale_of(placed)
        left, top, right, bottom = left - grow, top - grow, right + grow, bottom + grow
        clip = self.target(style.get("clip-path", "none"))
        if clip is not None:
            cut = self.extent(
                clip,
                _multiply(placed, _transform(clip.get("transform")))
                if clip.get("clipPathUnits", "userSpaceOnUse") == "userSpaceOnUse"
                else placed,
            )
            if cut is not None and clip.get("clipPathUnits", "userSpaceOnUse") == "userSpaceOnUse":
                left, top = max(left, cut[0]), max(top, cut[1])
                right, bottom = min(right, cut[2]), min(bottom, cut[3])
        if right - left <= 0.01 or bottom - top <= 0.01:
            return []
        markup = self.alone(element, parent, inherited, (left, top, right - left, bottom - top))
        source = self.store(markup.encode("utf-8"), ".svg")
        spec: dict[str, Any] = {
            "kind": "picture",
            "at": [left, top],
            "size": [right - left, bottom - top],
            "source": source,
        }
        ident = self.ident(element)
        if ident:
            spec = {
                "kind": "picture",
                "id": ident,
                **{k: v for k, v in spec.items() if k != "kind"},
            }
        what = {"g": "A group", "image": "A picture", "text": "Words", "use": "A clone"}.get(
            _local(element.tag), "A shape"
        )
        self.keep(f"{what} with {why} is kept as it is drawn, a picture of its own.")
        return [_Made(spec, (left, top, right, bottom))]

    def alone(
        self,
        element: ET.Element,
        matrix: Matrix,
        inherited: Mapping[str, str],
        view: tuple[float, float, float, float],
    ) -> str:
        """An SVG of ``element`` alone, through ``matrix``, its view ``view`` (in points)."""

        ET.register_namespace("", SVG_NS)
        ET.register_namespace("xlink", XLINK_NS)
        root = ET.Element(
            f"{{{SVG_NS}}}svg",
            {
                "version": "1.1",
                "viewBox": " ".join(_n(value) for value in view),
                "width": f"{_n(view[2])}pt",
                "height": f"{_n(view[3])}pt",
            },
        )
        needed: list[ET.Element] = []
        seen: set[str] = set()

        def references(item: ET.Element) -> None:
            for node in item.iter():
                for name, value in node.attrib.items():
                    for ident in re.findall(r"url\(\s*['\"]?#([^)'\"]+)", value):
                        want(ident)
                    if _local(name) == "href" and value.startswith("#"):
                        want(value[1:])
                if _local(node.tag) == "style" and node.text:
                    for ident in re.findall(r"url\(\s*['\"]?#([^)'\"]+)", node.text):
                        want(ident)

        def want(ident: str) -> None:
            if ident in seen or ident not in self.ids:
                return
            seen.add(ident)
            target = self.ids[ident]
            needed.append(target)
            references(target)

        references(element)
        for value in self.own(element).values():
            for ident in re.findall(r"url\(\s*['\"]?#([^)'\"]+)", value):
                want(ident)
        if self.sheet:
            for ident in re.findall(r"url\(\s*['\"]?#([^)'\"]+)", self.sheet):
                want(ident)
        defs = ET.SubElement(root, f"{{{SVG_NS}}}defs")
        if self.sheet:
            sheet = ET.SubElement(defs, f"{{{SVG_NS}}}style")
            sheet.text = self.sheet
        for item in needed:
            if any(item is other or _within(item, other) for other in needed if other is not item):
                continue
            copied = copy.deepcopy(item)
            units = {"mask": "maskUnits", "filter": "filterUnits"}.get(_local(copied.tag))
            if units and copied.get(units) == "userSpaceOnUse":
                # (Its region, unsaid, is a share of the drawing's page: said, as it was.)
                vx, vy, vw, vh = self.page_box
                for name, value in (
                    ("x", vx - 0.1 * vw),
                    ("y", vy - 0.1 * vh),
                    ("width", 1.2 * vw),
                    ("height", 1.2 * vh),
                ):
                    if copied.get(name) is None:
                        copied.set(name, _n(value))
            defs.append(copied)
        inherited_style = ";".join(
            f"{name}:{value}"
            for name, value in inherited.items()
            if name in INHERITED and name not in ("font-size",)
        )
        if "font-size" in inherited:
            inherited_style += f";font-size:{inherited['font-size']}px"
        holder = ET.SubElement(
            root,
            f"{{{SVG_NS}}}g",
            {
                "transform": "matrix(" + " ".join(_n(value) for value in matrix) + ")",
                "style": inherited_style,
            },
        )
        holder.append(copy.deepcopy(element))
        return ET.tostring(root, encoding="unicode")

    # -- lines joined to shapes --

    def glue(self, made: list[_Made]) -> None:
        """Inkscape's connectors glued to what they join, where Flexo draws them where they
        were: moving a box takes its arrows with it."""

        if not self.glued:
            return
        aliases = self.aliases
        found: dict[str, dict[str, Any]] = {}

        def walk(spec: Mapping[str, Any]) -> None:
            if spec.get("id") is not None:
                found[str(spec["id"])] = spec  # type: ignore[assignment]
            for child in spec.get("shapes") or []:
                walk(child)

        for item in made:
            walk(item.spec)

        def outline(spec: dict[str, Any]) -> dict[str, Any] | None:
            """What a connector joining ``spec`` meets: itself, or a group's largest box."""

            if spec.get("kind") != "group":
                return spec if freeform.family(str(spec["kind"])) in ("box", "path") else None
            boxes = [
                child
                for child in spec.get("shapes") or []
                if freeform.family(str(child["kind"])) in ("box", "path")
                and child["kind"] != "picture"
            ]
            if not boxes:
                return None
            largest = max(boxes, key=lambda child: _box_area(child))
            if largest.get("id") is None:
                name, n = f"{spec['id']}-box", 1
                while name in found:
                    n += 1
                    name = f"{spec['id']}-box-{n}"
                named = {
                    "kind": largest["kind"],
                    "id": name,
                    **{k: v for k, v in largest.items() if k != "kind"},
                }
                largest.clear()
                largest.update(named)
                found[name] = largest
            return largest

        def find(end: Mapping[str, Any]) -> freeform.Target | None:
            target = found.get(str(end.get("shape")))
            if target is None or freeform.family(str(target["kind"])) not in ("box", "path"):
                return None
            return freeform.target_of(_plain(target))

        for spec, start, end in self.glued:
            trial = dict(spec)
            for key, ident in (("from", start), ("to", end)):
                name = aliases.get(ident or "", None)
                joined = outline(found[name]) if name and name in found else None
                if joined is not None and isinstance(trial[key], list):
                    trial[key] = {"shape": joined["id"], "side": "centre", "at": list(trial[key])}
            if trial == spec:
                continue
            try:
                ends = freeform.glued(_plain(trial), find)
            except Exception:
                continue
            drawn = [freeform._point_of(spec["from"]), freeform._point_of(spec["to"])]
            slack = 1.0 + float(spec.get("line_width") or 0.0)
            if all(math.dist(a, b) <= slack for a, b in zip(ends, drawn, strict=True)):
                spec["from"], spec["to"] = trial["from"], trial["to"]


def _box_area(spec: Mapping[str, Any]) -> float:
    try:
        _, _, w, h = freeform.geometry(_plain(spec)).box
    except Exception:
        return 0.0
    return w * h


# -- pieces of the reading -------------------------------------------------------------------


@dataclass(slots=True)
class _Paint:
    fill: str | None
    fill_gradient: ET.Element | None
    fill_opacity: float
    stroke: str | None
    stroke_opacity: float
    width: float
    dash: list[float] | None
    cap: str
    join: str
    rule: str
    opacity: float
    fill_role: str | None = None
    stroke_role: str | None = None
    matrix: Matrix = IDENTITY

    @property
    def key(self) -> tuple:
        return (
            self.fill,
            id(self.fill_gradient) if self.fill_gradient is not None else None,
            round(self.fill_opacity, 3),
            self.stroke,
            round(self.width, 3),
            round(self.opacity, 3),
            self.rule,
        )


@dataclass(slots=True)
class _Heads:
    start: str | None = None
    end: str | None = None
    size: dict[str, tuple[str, float]] | None = None
    width: float = 0.0
    moved: list | None = None
    extra: list[_Made] = field(default_factory=list)


@dataclass(slots=True)
class _Piece:
    """One outline of a marker, on the page, painted."""

    segments: list
    fill: str | None
    stroke: str | None
    width: float
    opacity: float
    join: str
    rule: str


@dataclass(slots=True)
class _Run:
    text: str
    bold: bool
    italic: bool
    colour: str | None
    size: float
    shift: str
    family: str | None
    role: str | None = None


@dataclass(slots=True)
class _Line:
    x: float
    y: float
    anchor: str
    runs: list[_Run]
    size: float


# -- geometry ------------------------------------------------------------------------------


def _n(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _upright_turn(matrix: Matrix) -> float:
    """How far words drawn through ``matrix`` are turned, read by which way is up for them
    (a mirror leaves them upright)."""

    _, _, c, d, _, _ = matrix
    turn = (math.degrees(math.atan2(d, c)) - 90.0) % 360.0
    return 0.0 if turn < 1e-6 or abs(turn - 360.0) < 1e-6 else turn


def _rotation(degrees: float) -> Matrix:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return (cos, sin, -sin, cos, 0.0, 0.0)


def _viewbox(view: Sequence[float], width: float, height: float, aspect: str | None) -> Matrix:
    """What a ``viewBox`` maps its drawing by into a box ``width`` by ``height`` at 0, 0."""

    vx, vy, vw, vh = view
    sx, sy = width / vw, height / vh
    words = (aspect or "xMidYMid meet").split()
    align = words[0] if words else "xMidYMid"
    if align == "none":
        return (sx, 0.0, 0.0, sy, -vx * sx, -vy * sy)
    scale = max(sx, sy) if len(words) > 1 and words[1] == "slice" else min(sx, sy)
    tx = -vx * scale
    ty = -vy * scale
    if "xMid" in align:
        tx += (width - vw * scale) / 2.0
    elif "xMax" in align:
        tx += width - vw * scale
    if "YMid" in align:
        ty += (height - vh * scale) / 2.0
    elif "YMax" in align:
        ty += height - vh * scale
    return (scale, 0.0, 0.0, scale, tx, ty)


def _radii(
    element: ET.Element, w: float, h: float, *, ellipse: bool = False
) -> tuple[float, float]:
    rx_text, ry_text = element.get("rx"), element.get("ry")
    rx = _length(rx_text) if rx_text not in (None, "auto") else None
    ry = _length(ry_text) if ry_text not in (None, "auto") else None
    if rx is None and ry is None:
        return 0.0, 0.0
    rx = ry if rx is None else rx
    ry = rx if ry is None else ry
    if ellipse:
        return max(rx or 0.0, 0.0), max(ry or 0.0, 0.0)
    return max(0.0, min(rx or 0.0, w / 2.0)), max(0.0, min(ry or 0.0, h / 2.0))


def _outline_of(element: ET.Element, tag: str) -> list[tuple]:
    """An element's outline in its own units, as moves, lines, cubics and closes."""

    k = freeform.KAPPA
    if tag == "rect":
        x, y = _length(element.get("x")), _length(element.get("y"))
        w, h = _length(element.get("width")), _length(element.get("height"))
        if w <= 0 or h <= 0:
            return []
        rx, ry = _radii(element, w, h)
        if rx <= 0 or ry <= 0:
            return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
        kx, ky = rx * (1 - k), ry * (1 - k)
        return [
            ("M", x + rx, y), ("L", x + w - rx, y),
            ("C", x + w - kx, y, x + w, y + ky, x + w, y + ry), ("L", x + w, y + h - ry),
            ("C", x + w, y + h - ky, x + w - kx, y + h, x + w - rx, y + h), ("L", x + rx, y + h),
            ("C", x + kx, y + h, x, y + h - ky, x, y + h - ry), ("L", x, y + ry),
            ("C", x, y + ky, x + kx, y, x + rx, y), ("Z",),
        ]  # fmt: skip
    if tag in ("circle", "ellipse"):
        cx, cy = _length(element.get("cx")), _length(element.get("cy"))
        if tag == "circle":
            rx = ry = _length(element.get("r"))
        else:
            rx, ry = _radii(element, math.inf, math.inf, ellipse=True)
        if rx <= 0 or ry <= 0:
            return []
        return [
            ("M", cx + rx, cy),
            ("C", cx + rx, cy + ry * k, cx + rx * k, cy + ry, cx, cy + ry),
            ("C", cx - rx * k, cy + ry, cx - rx, cy + ry * k, cx - rx, cy),
            ("C", cx - rx, cy - ry * k, cx - rx * k, cy - ry, cx, cy - ry),
            ("C", cx + rx * k, cy - ry, cx + rx, cy - ry * k, cx + rx, cy),
            ("Z",),
        ]
    if tag == "line":
        return [
            ("M", _length(element.get("x1")), _length(element.get("y1"))),
            ("L", _length(element.get("x2")), _length(element.get("y2"))),
        ]
    if tag in ("polyline", "polygon"):
        values = _numbers(element.get("points"))
        points = list(zip(values[0::2], values[1::2], strict=False))
        if len(points) < 2:
            return []
        out = [("M", *points[0]), *(("L", *point) for point in points[1:])]
        return [*out, ("Z",)] if tag == "polygon" else out
    if tag == "path":
        data = element.get("d") or ""
        if not data.strip():
            return []
        try:
            return _local_segments(data)
        except pathdata.PathError:
            return _outline_unbounded(data)
    return []


def _local_segments(data: str) -> list[tuple]:
    return list(pathdata.parsed(data).segments)


def _outline_unbounded(data: str) -> list[tuple]:
    """Path data with points further than a page reaches (an outline drawn in large units,
    scaled down by its group): read in smaller units, and scaled back."""

    shrink = 1e-3
    try:
        made = pathdata.parsed(_scaled_data(data, shrink))
    except (pathdata.PathError, ValueError):
        return []
    return [(segment[0], *(value / shrink for value in segment[1:])) for segment in made.segments]


def _scaled_data(data: str, factor: float) -> str:
    """Path data with every number but an arc's flags and turn scaled by ``factor``."""

    out: list[str] = []
    command = ""
    index = 0
    for token in re.findall(
        r"[MmLlHhVvCcSsQqTtAaZz]|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", data
    ):
        if token.isalpha():
            command = token
            index = 0
            out.append(token)
            continue
        value = float(token)
        if command in "Aa" and index % 7 in (2, 3, 4):
            out.append(token)
        else:
            out.append(repr(value * factor))
        index += 1
    return " ".join(out)


def _mapped(segments: Sequence[tuple], matrix: Matrix) -> list[tuple]:
    if matrix == IDENTITY:
        return list(segments)
    out = []
    a, b, c, d, e, f = matrix
    for segment in segments:
        values = segment[1:]
        placed: list[float] = []
        for index in range(0, len(values), 2):
            x, y = values[index], values[index + 1]
            placed += [a * x + c * y + e, b * x + d * y + f]
        out.append((segment[0], *placed))
    return out


def _segments_box(segments: Sequence[tuple]) -> Box | None:
    points = [
        (segment[i], segment[i + 1]) for segment in segments for i in range(1, len(segment) - 1, 2)
    ]
    if not points:
        return None
    try:
        left, top, right, bottom = pathdata.extent(segments)
        return (left, top, right, bottom)
    except Exception:
        return _points_box(points)


def _area(segments: Sequence[tuple]) -> float:
    """How much an outline encloses, roughly (its points' polygon, each piece closed)."""

    total = 0.0
    ring: list[Point] = []
    for segment in [*segments, ("M", 0.0, 0.0)]:
        if segment[0] == "M":
            if len(ring) > 2:
                total += abs(
                    sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise([*ring, ring[0]]))
                )
            ring = [(segment[1], segment[2])]
        elif segment[0] != "Z":
            ring.append((segment[-2], segment[-1]))
    return total / 2.0


def _points_box(points: Sequence[Point]) -> Box:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _union(boxes: Sequence[Box | None]) -> Box | None:
    found = [box for box in boxes if box is not None]
    if not found:
        return None
    return (
        min(b[0] for b in found),
        min(b[1] for b in found),
        max(b[2] for b in found),
        max(b[3] for b in found),
    )


def _padded(box: Box, pad: float) -> Box:
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _within(item: ET.Element, other: ET.Element) -> bool:
    return any(node is item for node in other.iter() if node is not other)


def _distinct(points: Sequence[Point]) -> list[Point]:
    out: list[Point] = []
    for point in points:
        if not out or math.dist(out[-1], point) > 1e-6:
            out.append(point)
    return out


def _elbow(points: Sequence[Point]) -> dict[str, Any] | None:
    """A line turning through right angles once or twice, as an ``elbow`` draws one: its
    route and where it turns. None for any other."""

    if len(points) not in (3, 4):
        return None
    flat = 1e-3

    def level(p: Point, q: Point) -> bool:
        return abs(p[1] - q[1]) <= flat * max(1.0, abs(q[0] - p[0]))

    def upright(p: Point, q: Point) -> bool:
        return abs(p[0] - q[0]) <= flat * max(1.0, abs(q[1] - p[1]))

    a, b = points[0], points[-1]
    if len(points) == 4:
        p0, p1, p2, p3 = points
        if level(p0, p1) and upright(p1, p2) and level(p2, p3) and abs(b[0] - a[0]) > 1e-9:
            return {"elbow": round((p1[0] - a[0]) / (b[0] - a[0]), 4), "route": "across"}
        if upright(p0, p1) and level(p1, p2) and upright(p2, p3) and abs(b[1] - a[1]) > 1e-9:
            return {"elbow": round((p1[1] - a[1]) / (b[1] - a[1]), 4), "route": "down"}
        return None
    p0, p1, p2 = points
    if level(p0, p1) and upright(p1, p2):
        return {"elbow": 1.0, "route": "across"}
    if upright(p0, p1) and level(p1, p2):
        return {"elbow": 1.0, "route": "down"}
    return None


def _rectangle(points: Sequence[Point]) -> tuple[Point, tuple[float, float], float] | None:
    """Four corners making a rectangle (any way round, turned or not): its middle, its sides
    and how far it is turned. None for any other outline."""

    corners = list(points)
    if len(corners) == 5 and math.dist(corners[0], corners[-1]) < 1e-6:
        corners = corners[:4]
    if len(corners) != 4:
        return None
    sides = [
        (corners[(i + 1) % 4][0] - corners[i][0], corners[(i + 1) % 4][1] - corners[i][1])
        for i in range(4)
    ]
    lengths = [math.hypot(*side) for side in sides]
    if min(lengths) < 1e-6:
        return None
    for i in range(4):
        u, v = sides[i], sides[(i + 1) % 4]
        if abs(u[0] * v[0] + u[1] * v[1]) > 1e-3 * lengths[i] * lengths[(i + 1) % 4]:
            return None
    turn = math.degrees(math.atan2(sides[0][1], sides[0][0])) % 180.0
    w, h = lengths[0], lengths[1]
    if abs(turn - 90.0) < 1e-6:
        w, h, turn = h, w, 0.0
    if turn < 1e-6 or abs(turn - 180.0) < 1e-6:
        turn = 0.0
    if turn > 90.0:
        turn -= 180.0
    turn %= 360.0
    centre = (sum(p[0] for p in corners) / 4.0, sum(p[1] for p in corners) / 4.0)
    return centre, (w, h), turn


def _vertices(segments: Sequence[tuple]) -> list[tuple[float, float, Point, Point]]:
    """Where a path turns: each point it passes through, with the way it comes in and the
    way it goes out (unit vectors, in its own units)."""

    out: list[list] = []
    here = start = (0.0, 0.0)
    for segment in segments:
        kind = segment[0]
        if kind == "M":
            here = start = (segment[1], segment[2])
            out.append([here[0], here[1], None, None])
            continue
        if kind == "Z":
            points = [here, start]
        elif kind == "L":
            points = [here, (segment[1], segment[2])]
        else:
            points = [
                here,
                (segment[1], segment[2]),
                (segment[3], segment[4]),
                (segment[5], segment[6]),
            ]
        leave = next(
            (_unit_between(points[0], p) for p in points[1:] if math.dist(points[0], p) > 1e-9),
            None,
        )
        arrive = next(
            (
                _unit_between(p, points[-1])
                for p in reversed(points[:-1])
                if math.dist(p, points[-1]) > 1e-9
            ),
            None,
        )
        if out and leave is not None:
            out[-1][3] = leave
            if out[-1][2] is None:
                out[-1][2] = leave
        end = points[-1]
        out.append([end[0], end[1], arrive, arrive])
        here = end
    cleaned = []
    for x, y, way_in, way_out in out:
        way_in = way_in or way_out or (1.0, 0.0)
        way_out = way_out or way_in
        cleaned.append((x, y, way_in, way_out))
    return cleaned


def _unit_between(p: Point, q: Point) -> Point:
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-12 else (1.0, 0.0)


def _shift_end(segments: list[list], which: str, shift: float) -> None:
    """A path's start or end moved ``shift`` further out along the way it runs there (its
    curve's control with it, so it runs out the same way)."""

    if not segments or segments[-1][0] == "Z":
        return
    if which == "start":
        first = segments[0]
        nxt = segments[1] if len(segments) > 1 else None
        if nxt is None:
            return
        target = (nxt[1], nxt[2])
        way = _unit_between(target, (first[1], first[2]))
        if nxt[0] == "C" and math.dist(target, (first[1], first[2])) < 1e-9:
            target = (nxt[3], nxt[4])
            way = _unit_between(target, (first[1], first[2]))
        first[1] += way[0] * shift
        first[2] += way[1] * shift
        if nxt[0] == "C":
            nxt[1] += way[0] * shift
            nxt[2] += way[1] * shift
        return
    last = segments[-1]
    end = (last[-2], last[-1])
    before = _last_point(segments[:-1])
    if last[0] == "C":
        control = (last[3], last[4])
        reference = control if math.dist(control, end) > 1e-9 else (last[1], last[2])
        way = _unit_between(reference, end)
        last[3] += way[0] * shift
        last[4] += way[1] * shift
    else:
        way = _unit_between(before, end)
    last[-2] += way[0] * shift
    last[-1] += way[1] * shift


def _last_point(segments: Sequence[Sequence]) -> Point:
    for segment in reversed(segments):
        if segment[0] in ("M", "L"):
            return (segment[1], segment[2])
        if segment[0] == "C":
            return (segment[5], segment[6])
    return (0.0, 0.0)


def _head_of(
    pieces: list[_Piece], tip: Point, way: Point, paint: _Paint
) -> tuple[str, float, float] | None:
    """A marker drawn at a line's end (``tip``, the line running out ``way``) as the
    arrowhead Flexo has for it: its kind, its size (a triangle's length, a dot's radius, a
    bar's half length, in points) and how far past the end its tip (or middle) is. None
    for a marker no arrowhead draws."""

    if len(pieces) != 1 or not paint.stroke:
        return None
    piece = pieces[0]
    colour = paint.stroke.lower()
    for own in (piece.fill, piece.stroke):
        if own is not None and own.lower() != colour and own.lower() not in ("#ffffff",):
            return None
    ux, uy = way
    nx, ny = -uy, ux
    flat = freeform.flattened(piece.segments, 8)
    if len(flat) < 2:
        return None
    local = [
        ((px - tip[0]) * ux + (py - tip[1]) * uy, (px - tip[0]) * nx + (py - tip[1]) * ny)
        for px, py in flat
    ]
    closed = piece.segments[-1][0] == "Z" or math.dist(flat[0], flat[-1]) < 1e-6
    pad = piece.width / 2.0 if piece.stroke else 0.0
    front = max(x for x, _ in local) + pad
    back = min(x for x, _ in local) - pad
    half = max(abs(y) for _, y in local) + pad
    length = front - back
    if length <= 1e-6 or half <= 1e-6:
        return None
    if abs(max(y for _, y in local) + min(y for _, y in local)) > 0.25 * half:
        return None  # (lopsided: no head of Flexo's)
    filled = piece.fill is not None
    white_fill = filled and piece.fill.lower() == "#ffffff" and colour != "#ffffff"
    if white_fill and not piece.stroke:
        return None
    straight = [p for p in _corners_of(local)]
    if closed:
        centre = ((front + back) / 2.0, 0.0)
        radii = [math.dist(p, centre) for p in local]
        mean = sum(radii) / len(radii)
        curved = any(segment[0] == "C" for segment in piece.segments)
        round_ = curved and (
            max(abs(r - mean) for r in radii) <= 0.12 * mean
            and abs(length / 2.0 - half) < 0.15 * half
        )
        if round_:
            radius = half
            if filled and not white_fill:
                return ("dot", radius, centre[0])
            return ("circle", radius, centre[0])
        if white_fill or not filled:
            return None
        tip_point = max(local, key=lambda p: p[0])
        if abs(tip_point[1]) > 0.15 * half:
            return None
        # (Where it is widest, its rearmost such point: a triangle's base, a diamond's middle.)
        widest = min((p for p in local if abs(p[1]) >= 0.9 * (half - pad)), key=lambda p: p[0])
        share = (widest[0] - back) / length
        if (
            len(straight) == 4
            and 0.35 <= share <= 0.65
            and abs(min(local, key=lambda p: p[0])[1]) < 0.15 * half
        ):
            return ("diamond", _reach(length, half, 0.425), centre[0])
        if share > 0.35:
            return None
        axis = [x for x, y in local if abs(y) < 0.12 * half and x < tip_point[0] - 0.3 * length]
        notch = max(axis) if axis else back
        if notch > back + 0.15 * length:
            return ("stealth", _reach(length, half, 0.45), front)
        return ("triangle", _reach(length, half, 0.425), front)
    if filled:
        return None
    if len(straight) == 2:
        (x1, y1), (x2, y2) = straight
        if abs(x2 - x1) < 0.2 * abs(y2 - y1):
            return ("bar", half, (x1 + x2) / 2.0)
        return None
    if len(straight) == 3:
        a, b, c = straight
        if b[0] > a[0] and b[0] > c[0] and abs(b[1]) < 0.15 * half and a[1] * c[1] < 0:
            return ("open", _reach(length, half, 0.425), b[0] + pad)
    return None


def _reach(length: float, half: float, share: float) -> float:
    """An arrowhead's length as Flexo's of its kind would be, matched to a marker's length
    and breadth at once (Flexo's are ``share`` as broad, each side, as they are long)."""

    return math.sqrt(length * half / share)


def _corners_of(points: Sequence[Point]) -> list[Point]:
    """The corners of an outline: its points but those on a straight run between others."""

    kept: list[Point] = []
    for point in points:
        if kept and math.dist(kept[-1], point) < 1e-6:
            continue
        kept.append(point)
    if len(kept) > 2 and math.dist(kept[0], kept[-1]) < 1e-6:
        kept.pop()
    changed = True
    while changed and len(kept) > 2:
        changed = False
        for index in range(len(kept)):
            p, q, r = kept[index - 1], kept[index], kept[(index + 1) % len(kept)]
            cross = (q[0] - p[0]) * (r[1] - q[1]) - (q[1] - p[1]) * (r[0] - q[0])
            span = math.dist(p, q) * math.dist(q, r)
            if span < 1e-12 or abs(cross) <= 0.02 * span:
                if (
                    len(kept) <= 3
                    and math.dist(kept[0], kept[-1]) > 1e-6
                    and index in (0, len(kept) - 1)
                ):
                    continue
                del kept[index]
                changed = True
                break
    return kept


def _head_scale(kind: str, size: float, width: float) -> float:
    """An arrowhead's ``head_size`` for its size (``_head_of``) on a line ``width`` wide."""

    if kind in ("dot", "circle"):
        scale = size / (1.5 + 1.2 * width)
    elif kind == "bar":
        scale = 2.0 * size / (6.0 + 3.0 * width)
    else:
        scale = size / (4.0 + 3.0 * width)
    return max(0.25, min(6.0, scale))


def _dash_of(dashes: list[float], width: float, cap: str) -> str | list[float]:
    """A dash pattern as a shape says it: ``dashed`` or ``dotted`` where it is Flexo's own,
    else its lengths."""

    if len(dashes) == 2 and width > 0:
        for name in ("dashed", "dotted"):
            mine = freeform.dash_array({"dash": name, "line_width": width, "cap": cap})
            if all(abs(a - b) <= 0.05 * max(b, 0.1) for a, b in zip(dashes, mine, strict=True)):
                return name
    return [round(value, 3) for value in dashes]


def _unrolled(
    stops: list[tuple[float, str, float]], alpha: float, beta: float, spread: str
) -> list[tuple[float, str, float]]:
    """A gradient's stops (offsets ``t``) along a shape's own run (``s``, 0 to 1), where
    ``t = alpha s + beta``: cut to the run, repeated or reflected as the gradient spreads."""

    if abs(alpha) < 1e-12:
        _offset, colour, opacity = stops[-1]
        return [(0.0, colour, opacity), (1.0, colour, opacity)]
    low, high = sorted((beta, alpha + beta))
    placed: list[tuple[float, str, float]] = []
    if spread in ("repeat", "reflect") and high - low < 64:
        first, last = math.floor(low), math.ceil(high)
        for period in range(first, last):
            pieces = (
                stops
                if spread == "repeat" or period % 2 == 0
                else [
                    (1.0 - offset, colour, opacity) for offset, colour, opacity in reversed(stops)
                ]
            )
            placed += [(period + offset, colour, opacity) for offset, colour, opacity in pieces]
    else:
        placed = list(stops)
    along = [((t - beta) / alpha, colour, opacity) for t, colour, opacity in placed]
    if alpha < 0:
        along.reverse()
    # (By place alone: two stops at one place keep their order, a sharp step between them.)
    return _cut(sorted(along, key=lambda stop: stop[0]))


def _cut(stops: list[tuple[float, str, float]]) -> list[tuple[float, str, float]]:
    """Stops cut to 0..1: those inside kept, the colour at each end found between them."""

    def at(s: float) -> tuple[float, str, float]:
        if s <= stops[0][0]:
            return (s, stops[0][1], stops[0][2])
        if s >= stops[-1][0]:
            return (s, stops[-1][1], stops[-1][2])
        for (a, ca, oa), (b, cb, ob) in itertools.pairwise(stops):
            if a <= s <= b:
                share = 0.0 if b - a < 1e-12 else (s - a) / (b - a)
                mixed = tuple(x + (y - x) * share for x, y in zip(_rgb(ca), _rgb(cb), strict=True))
                return (s, _hex(mixed), oa + (ob - oa) * share)
        return (s, stops[-1][1], stops[-1][2])

    inside = [stop for stop in stops if 0.0 < stop[0] < 1.0]
    out = [(0.0, *at(0.0)[1:]), *inside, (1.0, *at(1.0)[1:])]
    # (An end that only repeats its neighbour's colour says nothing: the gradient keeps the
    # colour of its first stop before it, of its last after it.)
    if len(out) > 2 and out[0][1:] == out[1][1:]:
        out.pop(0)
    if len(out) > 2 and out[-1][1:] == out[-2][1:]:
        out.pop()
    return [(max(0.0, min(1.0, offset)), colour, opacity) for offset, colour, opacity in out]


def _middle(gradient: ET.Element, reader: _Reader) -> str | None:
    """A gradient's colour half way along it: what paints a line or words it was on."""

    stops = reader.stops(gradient)
    if not stops:
        return None
    for (a, ca, _), (b, cb, _) in itertools.pairwise(stops):
        if a <= 0.5 <= b:
            share = 0.0 if b - a < 1e-12 else (0.5 - a) / (b - a)
            return _hex(tuple(x + (y - x) * share for x, y in zip(_rgb(ca), _rgb(cb), strict=True)))
    return stops[-1][1] if stops[-1][0] < 0.5 else stops[0][1]


def _font_size(value: str, parent: float) -> float:
    text = (value or "").strip().lower()
    named = {
        "xx-small": 9.0,
        "x-small": 10.0,
        "small": 13.0,
        "medium": 16.0,
        "large": 18.0,
        "x-large": 24.0,
        "xx-large": 32.0,
    }
    if text in named:
        return named[text]
    if text == "smaller":
        return parent / 1.2
    if text == "larger":
        return parent * 1.2
    if text.endswith("%"):
        return (
            parent * _fraction(text, 1.0)
            if _fraction(text, 1.0) < 1.0
            else parent * float(text[:-1]) / 100.0
        )
    return _length(text, parent, font=parent) or parent


def _font_shorthand(value: str) -> dict[str, str]:
    """CSS's ``font`` shorthand: what it says of style, weight, size and family."""

    out: dict[str, str] = {}
    found = re.match(
        r"\s*((?:(?:italic|oblique|normal|bold|bolder|lighter|[1-9]00|small-caps)\s+)*)"
        r"([\d.]+[a-z%]*)(?:\s*/\s*[\d.]+[a-z%]*)?\s+(.+)$",
        value or "",
    )
    if not found:
        return out
    for word in found.group(1).split():
        if word in ("italic", "oblique"):
            out["font-style"] = word
        elif word in ("bold", "bolder") or word.isdigit():
            out["font-weight"] = word
    out["font-size"] = found.group(2)
    out["font-family"] = found.group(3)
    return out


def _shift_of(value: str) -> str:
    """A ``baseline-shift`` as which way the words go: ``super``, ``sub``, or ``""``."""

    text = (value or "").strip().lower()
    if text in ("super", "sub"):
        return text
    numbers = _numbers(text)
    if not numbers or not numbers[0]:
        return ""
    return "super" if numbers[0] > 0 else "sub"


def _weight(value: str) -> int:
    text = (value or "normal").strip().lower()
    if text in ("bold", "bolder"):
        return 700
    if text in ("normal", "lighter", "inherit"):
        return 400
    numbers = _numbers(text)
    return int(numbers[0]) if numbers else 400


def _family_of(value: str) -> str | None:
    for name in (value or "").split(","):
        name = name.strip().strip("'\"").strip()
        if name:
            return name
    return None


def _anchor_of(style: Mapping[str, str]) -> str:
    anchor = style.get("text-anchor", "start").strip()
    if anchor in ("middle", "end"):
        return anchor
    return "start"


def _align_of(style: Mapping[str, str]) -> str:
    align = style.get("text-align", "").strip()
    if align in ("center", "centre"):
        return "middle"
    if align in ("end", "right"):
        return "end"
    if not align:
        return _anchor_of(style)
    return "start"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-").lower()[:60]


def _plain(spec: Mapping[str, Any]) -> dict[str, Any]:
    """A shape without what the reading keeps in it for later (its arrowheads' sizes, its
    words' measures, a gradient), as ``flexo.freeform`` draws one."""

    out = {key: value for key, value in spec.items() if not key.startswith("__")}
    if isinstance(out.get("fill"), Mapping):
        out["fill"] = "#888888"
    if out.get("kind") == "group":
        out["shapes"] = [_plain(child) for child in out.get("shapes") or []]
    if out.get("kind") == "picture":
        out = {
            "kind": "rectangle",
            "at": out["at"],
            "size": out["size"],
            **({"rotate": out["rotate"]} if out.get("rotate") else {}),
        }
    if out.get("kind") == "text":
        out.setdefault("width", (spec.get("__size") or [240.0])[0])
    dash = out.get("dash")
    if isinstance(dash, list):
        out.pop("dash")
    out.pop("line_opacity", None)
    return out


def _group(shapes: list[dict[str, Any]], ident: str | None) -> dict[str, Any]:
    spec: dict[str, Any] = {"kind": "group"}
    if ident:
        spec["id"] = ident
    spec["shapes"] = shapes
    return spec


def _merged(made: list[_Made]) -> list[_Made]:
    """Outlines of words side by side, painted alike, as one outline: the glyphs of a
    formula one path, not one each."""

    out: list[_Made] = []
    for item in made:
        last = out[-1] if out else None
        if (
            last is not None
            and item.paint is not None
            and last.paint == item.paint
            and item.spec["kind"] == "path"
            and last.spec["kind"] == "path"
            and "start" not in item.spec
            and "end" not in item.spec
            and "start" not in last.spec
            and "end" not in last.spec
            and not isinstance(item.spec.get("fill"), Mapping)
            and not isinstance(last.spec.get("fill"), Mapping)
        ):
            last.spec["d"] = f"{last.spec['d']} {item.spec['d']}"
            last.box = _union([last.box, item.box]) or last.box
            continue
        out.append(_Made(dict(item.spec), item.box, item.paint))
    return out


# -- words -----------------------------------------------------------------------------------


def _base(runs: Sequence[_Run]) -> _Run | None:
    """The run most of the words are set like: its size, family and colour are the box's."""

    counted: dict[tuple, int] = {}
    first: dict[tuple, _Run] = {}
    for run in runs:
        if not run.text.strip() or run.shift:
            continue
        key = (round(run.size, 2), run.family, run.colour)
        counted[key] = counted.get(key, 0) + len(run.text)
        first.setdefault(key, run)
    if not counted:
        found = [run for run in runs if run.text.strip()]
        return found[0] if found else None
    return first[max(counted, key=lambda key: counted[key])]


def _blocks(lines: list[_Line]) -> list[list[_Line]]:
    """Lines set one under another, as a box of words sets them -- same start, same anchor,
    evenly spaced, about as far apart as Flexo spaces lines -- each one box; others apart."""

    blocks: list[list[_Line]] = []
    for line in lines:
        block = blocks[-1] if blocks else None
        if block:
            last = block[-1]
            gap = line.y - last.y
            size = max(last.size, 1e-9)
            even = len(block) < 2 or abs(gap - (block[-1].y - block[-2].y)) <= 0.03 * size
            if (
                abs(line.x - last.x) <= 0.02 * size
                and line.anchor == last.anchor
                and even
                and 1.05 <= gap / size <= 1.45
            ):
                block.append(line)
                continue
        blocks.append([line])
    return [
        block for block in blocks if any(run.text.strip() for line in block for run in line.runs)
    ]


def _joined_lines(lines: list[_Line]) -> list[_Line]:
    """Lines a flow broke (at its width), joined again for Flexo to break: one paragraph."""

    if not lines:
        return []
    joined = _Line(lines[0].x, lines[0].y, lines[0].anchor, [], lines[0].size)
    for index, line in enumerate(lines):
        if (
            index
            and joined.runs
            and not joined.runs[-1].text.endswith(" ")
            and line.runs
            and not line.runs[0].text.startswith(" ")
        ):
            last = joined.runs[-1]
            joined.runs.append(
                _Run(" ", last.bold, last.italic, last.colour, last.size, "", last.family)
            )
        joined.runs += line.runs
    return [joined]


_SLIDE_ESCAPES = str.maketrans({"*": "\\*", "`": "\\`", "$": "\\$"})
_FIGURE_ESCAPES = str.maketrans({"$": "\\$", "`": "\\`"})
_SCRIPTED = re.compile(r"[A-Za-z0-9 +\-=(),.]+")


def _words(
    lines: Sequence[_Line], base: _Run, markup: str, colours: _Colours
) -> tuple[str, bool, bool, str | None]:
    """Lines of runs as a text shape's words in ``markup``: the words, whether all are bold,
    whether all italic, and the colour most are."""

    runs = [run for line in lines for run in line.runs if run.text]
    worded = [run for run in runs if run.text.strip()]
    bold = bool(worded) and all(run.bold for run in worded)
    italic = bool(worded) and all(run.italic for run in worded)
    colour = colours.name(base.colour) if base.colour else None
    out_lines: list[str] = []
    for line in lines:
        pieces: list[tuple[_Run, str]] = []
        for run in line.runs:
            if not run.text:
                continue
            if pieces and _alike(pieces[-1][0], run):
                pieces[-1] = (pieces[-1][0], pieces[-1][1] + run.text)
            else:
                pieces.append((run, run.text))
        words = ""
        for run, text in pieces:
            words += _marked(text, run, bold, italic, colour, markup, colours)
        out_lines.append(words)
    return "\n".join(out_lines), bold, italic, colour


def _alike(one: _Run, other: _Run) -> bool:
    return (one.bold, one.italic, one.colour, one.shift) == (
        other.bold,
        other.italic,
        other.colour,
        other.shift,
    )


def _marked(
    text: str,
    run: _Run,
    bold: bool,
    italic: bool,
    colour: str | None,
    markup: str,
    colours: _Colours,
) -> str:
    """One run's words in ``markup``: its emphasis and colour where the box's are not its."""

    lead = text[: len(text) - len(text.lstrip(" "))]
    tail = text[len(text.rstrip(" ")) :]
    core = text.strip(" ")
    if not core:
        return text
    own_colour = colours.name(run.colour) if run.colour else None
    coloured = own_colour if own_colour and own_colour != colour else None
    strong = run.bold and not bold
    slanted = run.italic and not italic
    if run.shift and _SCRIPTED.fullmatch(core):
        letters = core if core.replace(" ", "").isdigit() else "\\mathrm{" + core + "}"
        if run.italic and not core.replace(" ", "").isdigit():
            letters = core
        mark = "^" if run.shift == "super" else "_"
        return f"{lead}${mark}{{{letters}}}${tail}"
    if markup == "slide":
        words = core.translate(_SLIDE_ESCAPES)
        words = re.sub(r"\\([(\[])", r"\\\\\1", words)
        words = re.sub(r"\](?=[({])", r"\\]", words)
        if strong and slanted:
            words = f"***{words}***"
        elif strong:
            words = f"**{words}**"
        elif slanted:
            words = f"*{words}*"
        if coloured:
            words = f"[{words}]{{{coloured}}}"
        return lead + words + tail
    words = core.translate(_FIGURE_ESCAPES)
    if coloured and "]" not in words:
        return f"{lead}[{words}]{{{coloured}}}{tail}"
    emphasis = (
        "bold-italic" if strong and slanted else "bold" if strong else "italic" if slanted else ""
    )
    if emphasis and "]" not in words:
        return f"{lead}[{words}]{{{emphasis}}}{tail}"
    return lead + words + tail


# -- pictures --------------------------------------------------------------------------------


def _picture_bytes(href: str) -> tuple[bytes | None, str]:
    """A picture's bytes and its suffix, from the drawing's ``href``: carried in it (a
    ``data:`` address), or a file on this machine by its whole path."""

    if href.startswith("data:"):
        head, _, body = href.partition(",")
        kind = head[5:].split(";")[0].strip().lower()
        try:
            data = base64.b64decode(body) if ";base64" in head else _unquoted(body)
        except (binascii.Error, ValueError):
            return None, ""
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/svg+xml": ".svg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(kind, "")
        if not suffix and data[:8] == b"\x89PNG\r\n\x1a\n":
            suffix = ".png"
        if not suffix and data[:3] == b"\xff\xd8\xff":
            suffix = ".jpg"
        if suffix in (".gif", ".webp"):
            data, suffix = _as_png(data), ".png"
        return (data if suffix and data else None), suffix
    path_text = href[7:] if href.startswith("file://") else href
    from pathlib import Path

    candidate = Path(path_text).expanduser()
    if (
        candidate.is_absolute()
        and candidate.is_file()
        and candidate.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg")
    ):
        suffix = ".jpg" if candidate.suffix.lower() == ".jpeg" else candidate.suffix.lower()
        return candidate.read_bytes(), suffix
    return None, ""


def _unquoted(body: str) -> bytes:
    from urllib.parse import unquote_to_bytes

    return unquote_to_bytes(body)


def _as_png(data: bytes) -> bytes:
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return b""


def _pixels(data: bytes) -> tuple[int, int] | None:
    """A PNG's or a JPEG's size in pixels, from its header."""

    import struct

    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        at = 2
        while at + 9 < len(data):
            if data[at] != 0xFF:
                at += 1
                continue
            marker = data[at + 1]
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                height, width = struct.unpack(">HH", data[at + 5 : at + 9])
                return width, height
            length = struct.unpack(">H", data[at + 2 : at + 4])[0]
            at += 2 + length
    return None


def _meet(
    box: tuple[float, float, float, float], natural: tuple[int, int], fitting: str
) -> tuple[float, float, float, float]:
    """Where a picture is drawn in its box, its proportions kept (``meet``)."""

    x, y, w, h = box
    nw, nh = natural
    if nw <= 0 or nh <= 0:
        return box
    scale = min(w / nw, h / nh)
    dw, dh = nw * scale, nh * scale
    align = fitting.split()[0] if fitting else "xMidYMid"
    left = x + (w - dw) / 2.0 if "xMid" in align else x + w - dw if "xMax" in align else x
    top = y + (h - dh) / 2.0 if "YMid" in align else y + h - dh if "YMax" in align else y
    return (left, top, dw, dh)


# -- placing ---------------------------------------------------------------------------------


def _placed(spec: Mapping[str, Any], scale: float, dx: float, dy: float) -> dict[str, Any]:
    """A shape read at its own size, scaled by ``scale`` and moved by ``dx``, ``dy``: every
    place and every length (its lines' widths, its words' size, its dashes, its corners)."""

    def point(value: Sequence[float]) -> list[float]:
        return [_r(value[0] * scale + dx), _r(value[1] * scale + dy)]

    out: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "shapes":
            out[key] = [_placed(child, scale, dx, dy) for child in value]
        elif key in ("at", "tail"):
            out[key] = point(value)
        elif key in ("from", "to"):
            if isinstance(value, Mapping):
                out[key] = {**value, **({"at": point(value["at"])} if value.get("at") else {})}
            else:
                out[key] = point(value)
        elif key == "points":
            out[key] = [point(item) for item in value]
        elif key == "d":
            out[key] = (
                pathdata.mapped(value, lambda p: (p[0] * scale + dx, p[1] * scale + dy))
                if scale != 1.0 or dx or dy
                else pathdata.normalised(value)
            )
        elif key in ("size",):
            out[key] = [_r(value[0] * scale), _r(value[1] * scale)]
        elif key in ("width", "corner"):
            out[key] = _r(value * scale)
        elif key == "line_width":
            out[key] = _r(min(200.0, value * scale))
        elif key == "font_size":
            out[key] = round(max(4.0, min(400.0, value * scale)), 2)
        elif key == "dash" and isinstance(value, list):
            out[key] = [round(item * scale, 3) for item in value]
        elif key == "__head":
            width = float(spec.get("line_width") or 0.0) * scale
            sizes = [_head_scale(kind, size * scale, width) for kind, size in value.values()]
            if sizes:
                out["head_size"] = round(sum(sizes) / len(sizes), 2)
        elif key == "__size":
            continue
        else:
            out[key] = value
    return out


def _r(value: float) -> float:
    rounded = round(value, 2)
    return 0.0 if rounded == 0 else rounded


_FIRST = (
    "kind",
    "id",
    "from",
    "to",
    "points",
    "closed",
    "at",
    "size",
    "width",
    "d",
    "fill_rule",
    "rotate",
    "flip",
    "source",
)


def _tidy(spec: Mapping[str, Any]) -> dict[str, Any]:
    """A shape as it is written: what it says that its kind would not say by itself, its
    place first, then its paint, then its words."""

    kind = str(spec["kind"])
    if kind == "group":
        out = {key: spec[key] for key in ("kind", "id") if key in spec}
        if float(spec.get("opacity", 1.0)) < 1.0:
            out["opacity"] = spec["opacity"]
        out["shapes"] = [_tidy(child) for child in spec.get("shapes") or []]
        return out
    usual = freeform.defaults(kind) if kind in freeform.KINDS else {}
    out: dict[str, Any] = {}
    for key in _FIRST:
        if key in spec:
            out[key] = spec[key]
    for key, value in spec.items():
        if key in out or key.startswith("__"):
            continue
        if key in usual and _same(usual[key], value):
            continue
        if key in ("rotate",) and not value:
            continue
        out[key] = value
    if out.get("rotate") == 0:
        out.pop("rotate")
    if kind == "text" and out.get("colour") is None:
        out.pop("colour", None)
    return out


def _same(one: object, other: object) -> bool:
    if (
        isinstance(one, float | int)
        and isinstance(other, float | int)
        and not isinstance(one, bool)
        and not isinstance(other, bool)
    ):
        return abs(float(one) - float(other)) < 1e-9
    return one == other


__all__ = ["NEAR", "Imported", "SvgImportError", "difference", "shapes_of"]
