"""A compiled figure as drawing primitives: what every non-SVG writer reads.

Flexo's SVG is the master, and it is a small, regular dialect: rectangles,
circles, paths of lines and curves, text set in runs, and arrowheads as
markers. ``read_drawing`` reads that dialect back into typed primitives with
everything a writer for another format needs made explicit:

- **paint** inherited through groups is resolved onto each shape (fill,
  stroke, widths, dashes, opacities, and the paint roles that name them);
- **paths** are lists of moves, lines, and cubic curves in absolute
  coordinates -- quadratic curves and arcs are converted;
- **arrowheads** are resolved from their markers: the end they sit on, the
  direction they point, their shape, and their outline as a path;
- **text** keeps its lines and runs, and each run carries its absolute pen
  position, its baseline, and the font file it is set in, measured with the
  same shaping Flexo laid the figure out with.

So a writer never parses SVG and never measures text: a PowerPoint shape, a
PDF operator, or a text box is placed straight from the numbers here.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Literal

import uharfbuzz as hb

from flexo.fonts import FontFace, family_faces, hb_font, load_face, select_face
from flexo.svg import local_name
from flexo.text import DEFAULT_FALLBACKS

type Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Segment:
    """One piece of a path: ``M``, ``L``, ``C`` (two controls and an end), or ``Z``."""

    kind: Literal["M", "L", "C", "Z"]
    points: tuple[Point, ...] = ()


@dataclass(frozen=True, slots=True)
class Paint:
    fill: str | None = None
    fill_opacity: float = 1.0
    stroke: str | None = None
    stroke_width: float = 1.0
    stroke_opacity: float = 1.0
    dash: tuple[float, ...] = ()
    linecap: str = "butt"
    linejoin: str = "miter"
    opacity: float = 1.0
    fill_role: str | None = None
    stroke_role: str | None = None
    blend: str = "normal"
    """How the paint mixes with what is under it: ``normal`` or ``multiply``."""


@dataclass(frozen=True, slots=True)
class Arrowhead:
    """An arrowhead on one end of a line, resolved from its marker."""

    end: Literal["start", "end"]
    tip: Point
    """The line's end point: where the marker's origin sits."""
    angle: float
    """The direction the head points, in radians (0 is +x, clockwise on the page)."""
    shape: str
    """The marker's shape: ``triangle``, ``stealth``, ``latex``, or ``open``."""
    length: float
    width: float
    outline: tuple[Segment, ...]
    """The head as a path, placed on the page."""
    paint: Paint


@dataclass(frozen=True, slots=True)
class Shape:
    """A rectangle, an ellipse, or a path, with its paint."""

    id: str | None
    kind: Literal["rect", "ellipse", "path"]
    paint: Paint
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    radius: float = 0.0
    """A rectangle's corner radius."""
    segments: tuple[Segment, ...] = ()
    """A path's pieces (a rectangle's and an ellipse's outline too, for writers that want one)."""
    arrowheads: tuple[Arrowhead, ...] = ()
    role: str | None = None


@dataclass(frozen=True, slots=True)
class Run:
    """Words set in one face, at one size, from an absolute pen position."""

    text: str
    x: float
    baseline: float
    width: float
    size: float
    weight: int
    italic: bool
    face: FontFace
    fill: str
    fill_role: str | None
    family: str
    """The family the SVG names for the run."""
    shift: float = 0.0
    """How far the run's baseline is raised from its line's (a superscript)."""


@dataclass(frozen=True, slots=True)
class Line:
    baseline: float
    runs: tuple[Run, ...]

    @property
    def left(self) -> float:
        return min((run.x for run in self.runs), default=0.0)

    @property
    def right(self) -> float:
        return max((run.x + run.width for run in self.runs), default=0.0)


@dataclass(frozen=True, slots=True)
class Text:
    id: str | None
    anchor: Literal["start", "middle", "end"]
    x: float
    lines: tuple[Line, ...]
    size: float
    family: str
    weight: int
    fill: str
    fill_role: str | None
    line_height: float
    simple: bool
    """Whether every run follows the one before on its line: no run is stepped
    back over another (a stacked pair of scripts, an accent's mark), so the
    text can be set as flowing lines."""
    angle: float = 0.0
    """Degrees the text is turned clockwise about ``pivot`` (an axis label): its
    lines and runs are given as if it were not turned."""
    pivot: Point = (0.0, 0.0)


@dataclass(frozen=True, slots=True)
class Image:
    id: str | None
    x: float
    y: float
    width: float
    height: float
    href: str
    """A ``data:`` URI: a PNG, a JPEG, or an SVG (nested artwork, kept as vectors)."""
    fit: str = "none"
    """SVG's ``preserveAspectRatio``: how the picture sits in the box."""

    def placed(self, width: float, height: float) -> tuple[float, float, float, float]:
        """Where a picture of ``width`` by ``height`` is drawn: ``x, y, w, h``."""

        align, _, mode = self.fit.partition(" ")
        if align == "none" or width <= 0.0 or height <= 0.0:
            return self.x, self.y, self.width, self.height
        scale = (min if mode != "slice" else max)(self.width / width, self.height / height)
        drawn_w, drawn_h = width * scale, height * scale
        horizontal = {"xMin": 0.0, "xMid": 0.5, "xMax": 1.0}[align[:4]]
        vertical = {"YMin": 0.0, "YMid": 0.5, "YMax": 1.0}[align[4:]]
        return (
            self.x + (self.width - drawn_w) * horizontal,
            self.y + (self.height - drawn_h) * vertical,
            drawn_w,
            drawn_h,
        )


@dataclass(slots=True)
class Group:
    id: str | None
    items: list[Shape | Text | Image | Group] = field(default_factory=list)
    data: dict[str, str] = field(default_factory=dict)
    label: str | None = None


@dataclass(frozen=True, slots=True)
class Drawing:
    width: float
    height: float
    root: Group

    def walk(self):
        """Every shape, text, and image, depth first, in drawing order."""

        stack = [iter(self.root.items)]
        while stack:
            item = next(stack[-1], None)
            if item is None:
                stack.pop()
                continue
            if isinstance(item, Group):
                stack.append(iter(item.items))
            else:
                yield item


# -- reading ---------------------------------------------------------------------------

_INHERITED = (
    "fill",
    "fill-opacity",
    "stroke",
    "stroke-width",
    "stroke-opacity",
    "stroke-dasharray",
    "stroke-linecap",
    "stroke-linejoin",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-anchor",
    "data-flexo-fill",
    "data-flexo-stroke",
)


def read_drawing(svg_text: str) -> Drawing:
    """The drawing an SVG makes (see the module docs).

    Flexo's own dialect is read exactly. So is the plain SVG plotting libraries
    write (matplotlib's among them): CSS ``style`` attributes and a ``*`` rule,
    ``<use>`` of shapes in ``<defs>``, any affine transform (a turned text keeps
    its ``angle``), rectangular clip paths (lines and polygons are cut to them),
    nested ``<svg>`` viewports, and text in fonts that are not installed (set in
    Flexo's fallback faces).
    """

    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", svg_text, count=1))
    view = [float(value) for value in re.split(r"[ ,]+", root.get("viewBox", "").strip()) if value]
    if len(view) != 4:
        view = [0.0, 0.0, _length(root.get("width")), _length(root.get("height"))]
    environment = _Environment(
        {item.get("id"): item for item in root.iter() if item.get("id")},
    )
    base: dict[str, str] = {}
    for item in root.iter():
        if local_name(item.tag) == "style" and item.text:
            for rule in re.finditer(r"(^|[}\s])\*\s*\{([^}]*)\}", item.text):
                base.update(_css(rule.group(2)))
    drawing = Group(root.get("id"))
    origin = (1.0, 0.0, 0.0, 1.0, -view[0], -view[1])
    _read_children(root, drawing, base, 1.0, environment, origin)
    return Drawing(view[2], view[3], drawing)


@dataclass(frozen=True, slots=True)
class _Environment:
    ids: dict[str | None, ET.Element]

    @property
    def markers(self) -> dict[str | None, ET.Element]:
        return self.ids


def _length(value: str | None) -> float:
    """An SVG length in points (user units are taken as points, as Flexo writes them)."""

    if not value:
        return 0.0
    match = re.fullmatch(r"\s*([-\d.eE+]+)\s*(pt|px|mm|cm|in|pc)?\s*", value)
    if match is None:
        return 0.0
    unit = {"pt": 1.0, "px": 0.75, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "pc": 12.0}
    return float(match.group(1)) * unit.get(match.group(2) or "pt", 1.0)


_CSS_NAMES = frozenset(
    {
        "fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray",
        "stroke-linecap", "stroke-linejoin", "font-family", "font-size", "font-weight",
        "font-style", "text-anchor", "opacity", "mix-blend-mode", "clip-path", "display",
        "visibility",
    }
)


def _css(declarations: str) -> dict[str, str]:
    """A ``style`` attribute's declarations, with ``font`` shorthand expanded."""

    result: dict[str, str] = {}
    for declaration in declarations.split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().lower(), value.strip()
        if not name or not value:
            continue
        if name == "font":
            match = re.search(r"([\d.]+)(px|pt)?\s+(.+)$", value)
            if match:
                result["font-size"] = match.group(1)
                result["font-family"] = match.group(3)
                if re.search(r"\b(italic|oblique)\b", value[: match.start()]):
                    result["font-style"] = "italic"
                weight = re.search(r"\b(bold|[1-9]00)\b", value[: match.start()])
                if weight:
                    result["font-weight"] = weight.group(1)
        elif name in _CSS_NAMES:
            unitless = name in {"font-size", "stroke-width"}
            result[name] = re.sub(r"(px|pt)$", "", value) if unitless else value
    return result


# -- transforms ------------------------------------------------------------------------

type Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _parse_transform(value: str | None) -> Matrix:
    """An SVG ``transform`` as an affine matrix ``(a, b, c, d, e, f)``."""

    matrix = IDENTITY
    for name, arguments in re.findall(r"(\w+)\s*\(([^)]*)\)", value or ""):
        numbers = [float(n) for n in re.findall(r"-?[\d.]+(?:e[-+]?\d+)?", arguments)]
        if name == "translate":
            step = (1.0, 0.0, 0.0, 1.0, numbers[0], numbers[1] if len(numbers) > 1 else 0.0)
        elif name == "scale":
            sx = numbers[0]
            step = (sx, 0.0, 0.0, numbers[1] if len(numbers) > 1 else sx, 0.0, 0.0)
        elif name == "matrix" and len(numbers) == 6:
            step = tuple(numbers)  # type: ignore[assignment]
        elif name == "rotate" and numbers:
            turn = math.radians(numbers[0])
            cos, sin = math.cos(turn), math.sin(turn)
            cx, cy = (numbers[1], numbers[2]) if len(numbers) >= 3 else (0.0, 0.0)
            step = (cos, sin, -sin, cos, cx - cos * cx + sin * cy, cy - sin * cx - cos * cy)
        elif name in {"skewX", "skewY"} and numbers:
            slope = math.tan(math.radians(numbers[0]))
            step = (1.0, 0.0, slope, 1.0, 0.0, 0.0)
            if name == "skewY":
                step = (1.0, slope, 0.0, 1.0, 0.0, 0.0)
        else:
            raise ValueError(f"unsupported transform {name}()")
        matrix = _compose(matrix, step)
    return matrix


def _compose(first: Matrix, second: Matrix) -> Matrix:
    """``first`` then ``second`` applied inside it (SVG's left-to-right order)."""

    a, b, c, d, e, f = first
    g, h, i, j, k, m = second
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * m + e,
        b * k + d * m + f,
    )


def _map(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def _scale_of(matrix: Matrix) -> float:
    a, b, c, d, _, _ = matrix
    if abs(b) > 1e-9 or abs(c) > 1e-9 or abs(abs(a) - abs(d)) > 1e-9:
        raise ValueError("flexo drawings are placed by translation and uniform scale only")
    return abs(a)


def _uniform(matrix: Matrix) -> bool:
    a, b, c, d, _, _ = matrix
    return abs(b) < 1e-9 and abs(c) < 1e-9 and abs(abs(a) - abs(d)) < 1e-9


def _transformed(item, matrix: Matrix):
    """``item`` (a shape, text, or image) moved, scaled, or turned by ``matrix``."""

    if matrix == IDENTITY:
        return item
    if not _uniform(matrix):
        return _turned(item, matrix)
    scale = _scale_of(matrix)
    if isinstance(item, Shape):
        paint = replace(
            item.paint,
            stroke_width=item.paint.stroke_width * scale,
            dash=tuple(value * scale for value in item.paint.dash),
        )
        segments = tuple(
            Segment(s.kind, tuple(_map(matrix, p) for p in s.points)) for s in item.segments
        )
        heads = tuple(
            replace(
                head,
                tip=_map(matrix, head.tip),
                length=head.length * scale,
                width=head.width * scale,
                outline=tuple(
                    Segment(s.kind, tuple(_map(matrix, p) for p in s.points)) for s in head.outline
                ),
                paint=replace(head.paint, stroke_width=head.paint.stroke_width * scale),
            )
            for head in item.arrowheads
        )
        x, y = _map(matrix, (item.x, item.y))
        return replace(
            item,
            paint=paint,
            x=x,
            y=y,
            width=item.width * scale,
            height=item.height * scale,
            radius=item.radius * scale,
            segments=segments,
            arrowheads=heads,
        )
    if isinstance(item, Text):
        x, _ = _map(matrix, (item.x, 0.0))
        lines = tuple(
            Line(
                _map(matrix, (0.0, line.baseline))[1],
                tuple(
                    replace(
                        run,
                        x=_map(matrix, (run.x, 0.0))[0],
                        baseline=_map(matrix, (0.0, run.baseline))[1],
                        width=run.width * scale,
                        size=run.size * scale,
                        shift=run.shift * scale,
                    )
                    for run in line.runs
                ),
            )
            for line in item.lines
        )
        pivot = _map(matrix, item.pivot) if item.angle else item.pivot
        return replace(
            item, x=x, lines=lines, size=item.size * scale, line_height=item.line_height * scale,
            pivot=pivot,
        )
    if isinstance(item, Image):
        x, y = _map(matrix, (item.x, item.y))
        return replace(item, x=x, y=y, width=item.width * scale, height=item.height * scale)
    return item


def _turned(item, matrix: Matrix):
    """``item`` under a matrix that turns, stretches, or shears it.

    A shape becomes a path of its mapped outline, its lines widened by the
    matrix's mean scale. A text keeps its lines in a frame of its own, scaled
    and moved so its anchor lands where the matrix puts it, and turned there.
    """

    a, b, c, d, _, _ = matrix
    scale = math.sqrt(abs(a * d - b * c)) or 1.0
    if isinstance(item, Shape):
        def mapped(segments):
            return tuple(
                Segment(s.kind, tuple(_map(matrix, p) for p in s.points)) for s in segments
            )

        segments = mapped(item.segments)
        points = [p for segment in segments for p in segment.points] or [(0.0, 0.0)]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        heads = tuple(
            replace(
                head,
                tip=_map(matrix, head.tip),
                length=head.length * scale,
                width=head.width * scale,
                outline=mapped(head.outline),
                paint=replace(head.paint, stroke_width=head.paint.stroke_width * scale),
            )
            for head in item.arrowheads
        )
        paint = replace(
            item.paint,
            stroke_width=item.paint.stroke_width * scale,
            dash=tuple(value * scale for value in item.paint.dash),
        )
        return replace(
            item, kind="path", paint=paint, x=min(xs), y=min(ys), width=max(xs) - min(xs),
            height=max(ys) - min(ys), radius=0.0, segments=segments, arrowheads=heads,
        )
    if isinstance(item, Text):
        anchor = item.pivot if item.angle else (item.x, item.lines[0].baseline)
        target = _map(matrix, anchor)
        moved = (target[0] - scale * anchor[0], target[1] - scale * anchor[1])
        uniform = (scale, 0.0, 0.0, scale, *moved)
        placed = _transformed(replace(item, angle=0.0), uniform)
        angle = item.angle + math.degrees(math.atan2(b, a))
        return replace(placed, angle=angle, pivot=target) if abs(angle) > 1e-6 else placed
    if isinstance(item, Image):
        far = (item.x + item.width, item.y + item.height)
        corners = [_map(matrix, p) for p in ((item.x, item.y), far)]
        return replace(
            item, x=min(p[0] for p in corners), y=min(p[1] for p in corners),
            width=abs(corners[1][0] - corners[0][0]), height=abs(corners[1][1] - corners[0][1]),
        )
    return item


def _read_children(
    element: ET.Element,
    group: Group,
    inherited: dict[str, str],
    opacity: float,
    environment: _Environment,
    matrix: Matrix,
) -> None:
    for child in element:
        _read_one(child, group, inherited, opacity, environment, matrix)


_SKIPPED = frozenset(
    {"defs", "title", "desc", "metadata", "style", "marker", "clipPath", "symbol", "mask",
     "pattern", "linearGradient", "radialGradient", "filter", "script", "foreignObject"}
)


def _read_one(
    child: ET.Element,
    group: Group,
    inherited: dict[str, str],
    opacity: float,
    environment: _Environment,
    matrix: Matrix,
) -> None:
    tag = local_name(child.tag)
    if tag in _SKIPPED:
        return
    own = {name: value for name, value in child.attrib.items() if name in _CSS_NAMES}
    own.update(_css(child.get("style", "")))
    if own.get("display") == "none" or own.get("visibility") == "hidden":
        return
    context = dict(inherited)
    for name in _INHERITED:
        if name in own:
            context[name] = own[name]
        elif child.get(name) is not None:
            context[name] = child.get(name)  # type: ignore[assignment]
    # Not inherited: a blend is the element's own.
    context["style"] = f"mix-blend-mode:{own['mix-blend-mode']}" if "mix-blend-mode" in own else ""
    # A painted element without a role of its own keeps no inherited one.
    for part in ("fill", "stroke"):
        if part in own and child.get(f"data-flexo-{part}") is None:
            context.pop(f"data-flexo-{part}", None)
    alpha = opacity * float(own.get("opacity", "1"))
    placed = _compose(matrix, _parse_transform(child.get("transform")))
    clip = own.get("clip-path", "")
    if clip.startswith("url(#"):
        region = _clip_region(environment.ids.get(clip[5:].rstrip(")").rstrip("'\"")), placed)
        if region is not None:
            context["-flexo-clip"] = " ".join(
                str(v) for v in _intersect(region, _region_of(context.get("-flexo-clip")))
            )
    if tag in {"g", "a", "switch"}:
        nested = Group(
            child.get("id"),
            data={k: v for k, v in child.attrib.items() if k.startswith("data-flexo-")},
            label=child.get("{http://www.inkscape.org/namespaces/inkscape}label"),
        )
        _read_children(child, nested, context, alpha, environment, placed)
        if nested.items:
            group.items.append(nested)
    elif tag == "use":
        reference = child.get("href") or child.get("{http://www.w3.org/1999/xlink}href") or ""
        target = environment.ids.get(reference.lstrip("#"))
        if target is not None and target is not child:
            moved = _compose(placed, (1.0, 0.0, 0.0, 1.0, _float(child, "x"), _float(child, "y")))
            used = Group(child.get("id"))
            _read_one(target, used, context, alpha, environment, moved)
            group.items.extend(used.items)
    elif tag in {"rect", "circle", "ellipse", "path", "line", "polyline", "polygon"}:
        shape = _shape(child, tag, context, alpha, environment.markers)
        if shape is not None:
            shape = _clipped(_transformed(shape, placed), _region_of(context.get("-flexo-clip")))
            if shape is not None:
                group.items.append(shape)
    elif tag == "text":
        text = _text(child, context)
        if text is not None:
            group.items.append(_transformed(text, placed))
    elif tag == "image":
        group.items.append(
            _transformed(Image(
                child.get("id"),
                _float(child, "x"),
                _float(child, "y"),
                _float(child, "width"),
                _float(child, "height"),
                child.get("href") or child.get("{http://www.w3.org/1999/xlink}href") or "",
                child.get("preserveAspectRatio", "xMidYMid meet"),
            ), placed)
        )
    elif tag == "svg":
        if _drawable(child):
            _viewport(child, group, context, alpha, environment, placed)
        else:
            group.items.append(_transformed(_nested_svg(child), placed))


_UNDRAWN = frozenset(
    {"mask", "pattern", "linearGradient", "radialGradient", "filter", "foreignObject"}
)


def _drawable(element: ET.Element) -> bool:
    """Whether a nested SVG is made only of what this reader draws exactly."""

    for item in element.iter():
        tag = local_name(item.tag)
        if tag in _UNDRAWN:
            return False
        for name in ("fill", "stroke", "filter", "mask", "style"):
            value = item.get(name, "")
            if "url(#" in value and "clip-path" not in value:
                return False
    return True


def _viewport(
    element: ET.Element,
    group: Group,
    context: dict[str, str],
    opacity: float,
    environment: _Environment,
    matrix: Matrix,
) -> None:
    """A nested ``<svg>``: its viewBox fitted into its box, clipped to the box."""

    x, y = _float(element, "x"), _float(element, "y")
    width = _length(element.get("width")) or 0.0
    height = _length(element.get("height")) or 0.0
    view = [float(v) for v in re.split(r"[ ,]+", element.get("viewBox", "").strip()) if v]
    if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
        view = [0.0, 0.0, width, height]
    width, height = width or view[2], height or view[3]
    fitting = element.get("preserveAspectRatio", "xMidYMid meet")
    picture = Image(None, x, y, width, height, "", fitting)
    left, top, drawn_w, drawn_h = picture.placed(view[2], view[3])
    fit = (drawn_w / view[2], 0.0, 0.0, drawn_h / view[3], left - view[0] * drawn_w / view[2],
           top - view[1] * drawn_h / view[3])
    inner = dict(context)
    corners = (_map(matrix, (x, y)), _map(matrix, (x + width, y + height)))
    region = (min(corners[0][0], corners[1][0]), min(corners[0][1], corners[1][1]),
              max(corners[0][0], corners[1][0]), max(corners[0][1], corners[1][1]))
    clip = _intersect(region, _region_of(context.get("-flexo-clip")))
    inner["-flexo-clip"] = " ".join(str(v) for v in clip)
    nested = Group(element.get("id"))
    _read_children(element, nested, inner, opacity, environment, _compose(matrix, fit))
    if nested.items:
        group.items.append(nested)


# -- clipping ------------------------------------------------------------------------

type Region = tuple[float, float, float, float]
"""A clip rectangle on the page: ``left, top, right, bottom``."""


def _region_of(value: str | None) -> Region | None:
    if not value:
        return None
    left, top, right, bottom = (float(v) for v in value.split())
    return (left, top, right, bottom)


def _intersect(first: Region, second: Region | None) -> Region:
    if second is None:
        return first
    return (max(first[0], second[0]), max(first[1], second[1]),
            min(first[2], second[2]), min(first[3], second[3]))


def _clip_region(clip: ET.Element | None, matrix: Matrix) -> Region | None:
    """The page rectangle a ``<clipPath>`` of one rectangle leaves visible."""

    if clip is None:
        return None
    shapes = [item for item in clip if local_name(item.tag) in {"rect", "path"}]
    if len(shapes) != 1:
        return None
    body = shapes[0]
    placed = _compose(matrix, _parse_transform(clip.get("transform")))
    placed = _compose(placed, _parse_transform(body.get("transform")))
    if local_name(body.tag) == "rect":
        x, y = _float(body, "x"), _float(body, "y")
        points = [(x, y), (x + _float(body, "width"), y + _float(body, "height"))]
    else:
        segments = parse_path(body.get("d", ""))
        points = [p for segment in segments for p in segment.points]
        xs = {round(p[0], 6) for p in points}
        ys = {round(p[1], 6) for p in points}
        if len(xs) != 2 or len(ys) != 2:
            return None
    mapped = [_map(placed, p) for p in points]
    xs, ys = [p[0] for p in mapped], [p[1] for p in mapped]
    return (min(xs), min(ys), max(xs), max(ys))


def _clipped(shape: Shape, region: Region | None) -> Shape | None:
    """``shape`` cut to ``region``: lines and polygons exactly, curves kept whole."""

    if region is None:
        return shape
    left, top, right, bottom = region
    points = [p for segment in shape.segments for p in segment.points]
    if not points:
        return shape
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad = shape.paint.stroke_width / 2.0 if shape.paint.stroke else 0.0
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x0 >= left - 1e-6 and x1 <= right + 1e-6 and y0 >= top - 1e-6 and y1 <= bottom + 1e-6:
        return shape
    if x1 + pad < left or x0 - pad > right or y1 + pad < top or y0 - pad > bottom:
        return None
    if shape.kind == "rect" and not shape.radius:
        x0, y0 = max(shape.x, left), max(shape.y, top)
        x1, y1 = min(shape.x + shape.width, right), min(shape.y + shape.height, bottom)
        if x1 <= x0 or y1 <= y0:
            return None
        return replace(shape, x=x0, y=y0, width=x1 - x0, height=y1 - y0,
                       segments=_rounded(x0, y0, x1 - x0, y1 - y0, 0.0))
    if any(segment.kind == "C" for segment in shape.segments):
        return shape
    pieces = _subpaths(shape.segments)
    kept: list[Segment] = []
    if shape.paint.fill:
        for polygon, _closed in pieces:
            cut = _clip_polygon(polygon, region)
            if len(cut) >= 3:
                kept.append(Segment("M", (cut[0],)))
                kept.extend(Segment("L", (p,)) for p in cut[1:])
                kept.append(Segment("Z"))
    else:
        for line, closed in pieces:
            if closed:
                line = [*line, line[0]]
            for run in _clip_polyline(line, region):
                kept.append(Segment("M", (run[0],)))
                kept.extend(Segment("L", (p,)) for p in run[1:])
    if not kept:
        return None
    points = [p for segment in kept for p in segment.points]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    heads = tuple(
        h for h in shape.arrowheads if left <= h.tip[0] <= right and top <= h.tip[1] <= bottom
    )
    return replace(shape, kind="path", segments=tuple(kept), x=min(xs), y=min(ys),
                   width=max(xs) - min(xs), height=max(ys) - min(ys), arrowheads=heads)


def _subpaths(segments) -> list[tuple[list[Point], bool]]:
    result: list[tuple[list[Point], bool]] = []
    for segment in segments:
        if segment.kind == "M":
            result.append(([segment.points[0]], False))
        elif segment.kind == "L" and result:
            result[-1][0].append(segment.points[0])
        elif segment.kind == "Z" and result:
            result[-1] = (result[-1][0], True)
    return result


def _clip_polygon(polygon: list[Point], region: Region) -> list[Point]:
    """Sutherland-Hodgman against each edge of the rectangle."""

    left, top, right, bottom = region

    def at_x(p: Point, q: Point, x: float) -> Point:
        return (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))

    def at_y(p: Point, q: Point, y: float) -> Point:
        return (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)

    edges = (
        (lambda p: p[0] >= left, lambda p, q: at_x(p, q, left)),
        (lambda p: p[0] <= right, lambda p, q: at_x(p, q, right)),
        (lambda p: p[1] >= top, lambda p, q: at_y(p, q, top)),
        (lambda p: p[1] <= bottom, lambda p, q: at_y(p, q, bottom)),
    )
    output = list(polygon)
    for inside, cross in edges:
        points, output = output, []
        for index, current in enumerate(points):
            previous = points[index - 1]
            if inside(current):
                if not inside(previous):
                    output.append(cross(previous, current))
                output.append(current)
            elif inside(previous):
                output.append(cross(previous, current))
        if not output:
            break
    return output


def _clip_polyline(line: list[Point], region: Region) -> list[list[Point]]:
    """Liang-Barsky on each piece; the visible runs of the line."""

    left, top, right, bottom = region
    runs: list[list[Point]] = []
    for (x0, y0), (x1, y1) in pairwise(line):
        dx, dy = x1 - x0, y1 - y0
        low, high = 0.0, 1.0
        for p, q in ((-dx, x0 - left), (dx, right - x0), (-dy, y0 - top), (dy, bottom - y0)):
            if abs(p) < 1e-12:
                if q < 0:
                    low, high = 1.0, 0.0
                continue
            t = q / p
            if p < 0:
                low = max(low, t)
            else:
                high = min(high, t)
        if low > high:
            continue
        start = (x0 + dx * low, y0 + dy * low)
        end = (x0 + dx * high, y0 + dy * high)
        if runs and runs[-1][-1] == start:
            runs[-1].append(end)
        else:
            runs.append([start, end])
    return runs


def _nested_svg(element: ET.Element) -> Image:
    """Artwork nested as its own ``<svg>``: a picture of that SVG, kept as vectors."""

    import base64

    box = [_float(element, name) for name in ("x", "y", "width", "height")]
    artwork = ET.fromstring(ET.tostring(element, encoding="unicode"))
    for name in ("x", "y", "id"):
        artwork.attrib.pop(name, None)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    markup = ET.tostring(artwork, encoding="unicode")
    encoded = base64.b64encode(markup.encode("utf-8")).decode("ascii")
    return Image(element.get("id"), *box, f"data:image/svg+xml;base64,{encoded}", "none")


def _float(element: ET.Element, name: str, default: float = 0.0) -> float:
    value = element.get(name)
    return float(value) if value not in (None, "") else default


def _paint(context: dict[str, str], opacity: float) -> Paint:
    def colour(name: str) -> str | None:
        value = context.get(name)
        return None if value in (None, "none") or value.startswith("url(") else value

    fill = colour("fill") if "fill" in context else "#000000"
    own_style = context.get("style", "").replace(" ", "")
    pattern = context.get("stroke-dasharray", "none")
    dash = (
        tuple(float(part) for part in re.split(r"[ ,]+", pattern.strip()) if part)
        if pattern != "none"
        else ()
    )
    return Paint(
        fill=fill,
        fill_opacity=float(context.get("fill-opacity", "1")),
        stroke=colour("stroke"),
        stroke_width=float(context.get("stroke-width", "1")),
        stroke_opacity=float(context.get("stroke-opacity", "1")),
        dash=dash,
        linecap=context.get("stroke-linecap", "butt"),
        linejoin=context.get("stroke-linejoin", "miter"),
        opacity=opacity,
        fill_role=context.get("data-flexo-fill") if fill else None,
        stroke_role=context.get("data-flexo-stroke") if colour("stroke") else None,
        blend="multiply" if "mix-blend-mode:multiply" in own_style else "normal",
    )


def _shape(
    element: ET.Element,
    tag: str,
    context: dict[str, str],
    opacity: float,
    markers: dict[str | None, ET.Element],
) -> Shape | None:
    paint = _paint(context, opacity)
    identifier = element.get("id")
    role = element.get("data-flexo-role")
    if tag == "rect":
        x, y = _float(element, "x"), _float(element, "y")
        width, height = _float(element, "width"), _float(element, "height")
        radius = min(_float(element, "rx", _float(element, "ry")), width / 2.0, height / 2.0)
        outline = _rounded(x, y, width, height, radius)
        return Shape(
            identifier, "rect", paint, x, y, width, height, radius, outline, role=role
        )
    if tag in {"circle", "ellipse"}:
        cx, cy = _float(element, "cx"), _float(element, "cy")
        rx = _float(element, "r") if tag == "circle" else _float(element, "rx")
        ry = _float(element, "r") if tag == "circle" else _float(element, "ry")
        outline = _ellipse(cx, cy, rx, ry)
        return Shape(
            identifier, "ellipse", paint, cx - rx, cy - ry, 2 * rx, 2 * ry, 0.0, outline, role=role
        )
    if tag == "line":
        start = f"{element.get('x1', 0)} {element.get('y1', 0)}"
        data = f"M {start} L {element.get('x2', 0)} {element.get('y2', 0)}"
    elif tag in {"polyline", "polygon"}:
        values = re.findall(r"-?[\d.]+(?:e[-+]?\d+)?", element.get("points", ""))
        pairs = [f"{values[i]} {values[i + 1]}" for i in range(0, len(values) - 1, 2)]
        data = "M " + " L ".join(pairs) + (" Z" if tag == "polygon" else "")
    else:
        data = element.get("d", "")
    segments = tuple(parse_path(data))
    if not segments:
        return None
    heads = []
    for end in ("start", "end"):
        reference = element.get(f"marker-{end}") or context.get(f"marker-{end}")
        if reference and reference.startswith("url(#"):
            marker = markers.get(reference[5:-1])
            if marker is not None:
                head = _arrowhead(marker, segments, end, paint)  # type: ignore[arg-type]
                if head is not None:
                    heads.append(head)
    xs = [x for segment in segments for x, _ in segment.points]
    ys = [y for segment in segments for _, y in segment.points]
    return Shape(
        identifier,
        "path",
        paint,
        min(xs),
        min(ys),
        max(xs) - min(xs),
        max(ys) - min(ys),
        0.0,
        segments,
        tuple(heads),
        role=role,
    )


# -- paths ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[MmLlHhVvQqCcSsTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_path(data: str) -> list[Segment]:
    """An SVG path as absolute moves, lines, and cubics; quadratics and arcs converted."""

    tokens = _TOKEN.findall(data)
    out: list[Segment] = []
    index = 0
    here: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    command = ""
    last_control: Point | None = None

    def take(count: int) -> list[float]:
        nonlocal index
        values = [float(token) for token in tokens[index : index + count]]
        index += count
        return values

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in "Zz":
                out.append(Segment("Z"))
                here = start
                last_control = None
                continue
        relative = command.islower()
        kind = command.upper()
        ox, oy = here if relative else (0.0, 0.0)
        if kind == "M":
            x, y = take(2)
            here = start = (ox + x, oy + y)
            out.append(Segment("M", (here,)))
            command = "l" if relative else "L"
            last_control = None
        elif kind in "LHV":
            if kind == "L":
                x, y = take(2)
                point = (ox + x, oy + y)
            elif kind == "H":
                (x,) = take(1)
                point = ((here[0] if relative else 0.0) + x, here[1])
            else:
                (y,) = take(1)
                point = (here[0], (here[1] if relative else 0.0) + y)
            out.append(Segment("L", (point,)))
            here = point
            last_control = None
        elif kind in "QT":
            if kind == "Q":
                qx, qy, x, y = take(4)
                control = (ox + qx, oy + qy)
            else:
                x, y = take(2)
                control = (
                    (2 * here[0] - last_control[0], 2 * here[1] - last_control[1])
                    if last_control
                    else here
                )
            end = (ox + x, oy + y)
            first = (
                here[0] + 2 / 3 * (control[0] - here[0]),
                here[1] + 2 / 3 * (control[1] - here[1]),
            )
            second = (
                end[0] + 2 / 3 * (control[0] - end[0]),
                end[1] + 2 / 3 * (control[1] - end[1]),
            )
            out.append(Segment("C", (first, second, end)))
            here, last_control = end, control
        elif kind in "CS":
            if kind == "C":
                ax, ay, bx, by, x, y = take(6)
                first = (ox + ax, oy + ay)
            else:
                bx, by, x, y = take(4)
                first = (
                    (2 * here[0] - last_control[0], 2 * here[1] - last_control[1])
                    if last_control
                    else here
                )
            second, end = (ox + bx, oy + by), (ox + x, oy + y)
            out.append(Segment("C", (first, second, end)))
            here, last_control = end, second
        elif kind == "A":
            rx, ry, rotation, large, sweep, x, y = take(7)
            end = (ox + x, oy + y)
            out.extend(_arc(here, rx, ry, rotation, bool(large), bool(sweep), end))
            here = end
            last_control = None
        else:  # pragma: no cover - flexo writes no other command
            break
    return out


def _arc(
    start: Point, rx: float, ry: float, rotation: float, large: bool, sweep: bool, end: Point
) -> list[Segment]:
    """An elliptical arc as cubic Béziers, a quarter turn at most each."""

    if rx == 0 or ry == 0 or start == end:
        return [Segment("L", (end,))]
    phi = math.radians(rotation)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2.0, (start[1] - end[1]) / 2.0
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    scale = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator else 0.0
    if large == sweep:
        factor = -factor
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2.0
    cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    theta = angle(1.0, 0.0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    pieces = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    step = delta / pieces
    k = 4.0 / 3.0 * math.tan(step / 4.0)

    def at(t: float) -> Point:
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (cos * x - sin * y + cx, sin * x + cos * y + cy)

    def tangent(t: float) -> Point:
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (cos * x - sin * y, sin * x + cos * y)

    out = []
    for piece in range(pieces):
        a, b = theta + piece * step, theta + (piece + 1) * step
        pa, pb = at(a), at(b)
        ta, tb = tangent(a), tangent(b)
        out.append(
            Segment(
                "C",
                (
                    (pa[0] + k * ta[0], pa[1] + k * ta[1]),
                    (pb[0] - k * tb[0], pb[1] - k * tb[1]),
                    end if piece == pieces - 1 else pb,
                ),
            )
        )
    return out


def _rounded(x: float, y: float, w: float, h: float, r: float) -> tuple[Segment, ...]:
    if r <= 0:
        return (
            Segment("M", ((x, y),)),
            Segment("L", ((x + w, y),)),
            Segment("L", ((x + w, y + h),)),
            Segment("L", ((x, y + h),)),
            Segment("Z"),
        )
    data = (
        f"M {x + r} {y} H {x + w - r} A {r} {r} 0 0 1 {x + w} {y + r} V {y + h - r} "
        f"A {r} {r} 0 0 1 {x + w - r} {y + h} H {x + r} A {r} {r} 0 0 1 {x} {y + h - r} "
        f"V {y + r} A {r} {r} 0 0 1 {x + r} {y} Z"
    )
    return tuple(parse_path(data))


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> tuple[Segment, ...]:
    data = (
        f"M {cx + rx} {cy} A {rx} {ry} 0 0 1 {cx} {cy + ry} A {rx} {ry} 0 0 1 {cx - rx} {cy} "
        f"A {rx} {ry} 0 0 1 {cx} {cy - ry} A {rx} {ry} 0 0 1 {cx + rx} {cy} Z"
    )
    return tuple(parse_path(data))


# -- markers ---------------------------------------------------------------------------

_SHAPES = {"triangle", "stealth", "latex", "open"}


def _arrowhead(
    marker: ET.Element, segments: tuple[Segment, ...], end: str, line: Paint
) -> Arrowhead | None:
    points = [point for segment in segments for point in segment.points]
    if len(points) < 2:
        return None
    if end == "end":
        tip, before = points[-1], next((p for p in reversed(points[:-1]) if p != points[-1]), None)
        if before is None:
            return None
        angle = math.atan2(tip[1] - before[1], tip[0] - before[0])
    else:
        tip, after = points[0], next((p for p in points[1:] if p != points[0]), None)
        if after is None:
            return None
        # ``auto-start-reverse``: the head at the start points back along the line.
        angle = math.atan2(tip[1] - after[1], tip[0] - after[0])
    body = next((item for item in marker if local_name(item.tag) == "path"), None)
    if body is None:
        return None
    local = parse_path(body.get("d", ""))
    cos, sin = math.cos(angle), math.sin(angle)

    def place(point: Point) -> Point:
        x, y = point
        return (tip[0] + x * cos - y * sin, tip[1] + x * sin + y * cos)

    outline = tuple(
        Segment(segment.kind, tuple(place(p) for p in segment.points)) for segment in local
    )
    xs = [x for segment in local for x, _ in segment.points]
    ys = [y for segment in local for _, y in segment.points]
    identifier = marker.get("id") or ""
    filled = body.get("fill", "none") != "none"
    shape = "open" if not filled else _marker_shape(local)
    paint = Paint(
        fill=body.get("fill") if filled else None,
        stroke=body.get("stroke") if body.get("stroke") not in (None, "none") else None,
        stroke_width=float(body.get("stroke-width", line.stroke_width)),
        linecap=body.get("stroke-linecap", "round"),
        linejoin=body.get("stroke-linejoin", "round"),
        opacity=line.opacity,
        fill_role=body.get("data-flexo-fill"),
        stroke_role=body.get("data-flexo-stroke"),
    )
    del identifier
    return Arrowhead(
        end,  # type: ignore[arg-type]
        tip,
        angle,
        shape,
        max(xs) - min(0.0, min(xs)) if xs else 0.0,
        max(ys) - min(ys) if ys else 0.0,
        outline,
        paint,
    )


def _marker_shape(local: list[Segment]) -> str:
    """Which of Flexo's heads a marker draws, from its outline."""

    if any(segment.kind == "C" for segment in local):
        return "latex"
    corners = [segment.points[-1] for segment in local if segment.kind in {"M", "L"}]
    # A stealth head's back is notched in: a fourth corner inside the triangle.
    return "stealth" if len(corners) >= 4 and corners[3][0] > 0.0 else "triangle"


# -- text ------------------------------------------------------------------------------


def _text(element: ET.Element, context: dict[str, str]) -> Text | None:
    family = context.get("font-family", "sans-serif").split(",")[0].strip().strip("'\"")
    size = float(context.get("font-size", "8"))
    weight = _weight(context.get("font-weight"))
    anchor = context.get("text-anchor", "start")
    x = _float(element, "x")
    baseline = _float(element, "y")
    fill = context.get("fill", "#000000")
    role = context.get("data-flexo-fill")
    lines: list[list[Run]] = []
    pen = x
    line_baseline = baseline
    line_height = 0.0
    simple = True
    pieces = list(_pieces(element, context))
    run_baseline = baseline
    for piece in pieces:
        attributes, text = piece
        if not lines or ("x" in attributes and "y" not in attributes):
            # A new line: Flexo starts each with an ``x`` (and a ``dy`` after the first).
            if lines and "dy" in attributes:
                step = float(attributes["dy"])
                line_height = line_height or step
                line_baseline += step
            lines.append([])
            pen = float(attributes.get("x", x))
            run_baseline = float(attributes["y"]) if "y" in attributes else line_baseline
            if "y" in attributes:
                line_baseline = run_baseline
        elif "x" in attributes:
            # A piece placed absolutely on the same line (a plotting library's maths).
            step = float(attributes["x"])
            if step < pen - 1e-6:
                simple = False
            pen = step
            run_baseline = float(attributes["y"])
            if abs(run_baseline - line_baseline) > 1e-6:
                simple = False
        if "dx" in attributes:
            step = float(attributes["dx"])
            if step < -1e-6:
                simple = False
            pen += step
        run_family = attributes.get("font-family", family).split(",")[0].strip().strip("'\"")
        run_size = float(attributes.get("font-size", size))
        declared = attributes.get("font-weight")
        run_weight = _weight(declared) if declared is not None else weight
        italic = attributes.get("font-style", "normal") in {"italic", "oblique"}
        shift = float(attributes.get("baseline-shift", "0") or 0) + line_baseline - run_baseline
        for face, part, family_name in _faces_for(run_family, run_weight, italic, text):
            width = _advance(face, run_weight, part) * run_size
            lines[-1].append(
                Run(
                    part,
                    pen,
                    line_baseline - shift,
                    width,
                    run_size,
                    run_weight,
                    italic,
                    face,
                    attributes.get("fill", fill),
                    role,
                    family_name,
                    shift,
                )
            )
            pen += width
    placed = []
    for runs in lines:
        if not runs:
            continue
        width = max(run.x + run.width for run in runs) - min(run.x for run in runs)
        offset = {"start": 0.0, "middle": -width / 2.0, "end": -width}.get(anchor, 0.0)
        placed.append(
            Line(
                runs[0].baseline + runs[0].shift,
                tuple(
                    Run(
                        run.text, run.x + offset, run.baseline, run.width, run.size, run.weight,
                        run.italic, run.face, run.fill, run.fill_role, run.family, run.shift,
                    )
                    for run in runs
                ),
            )
        )
    if not placed:
        return None
    return Text(
        element.get("id"),
        anchor,  # type: ignore[arg-type]
        x,
        tuple(placed),
        size,
        family,
        weight,
        fill,
        role,
        line_height,
        simple,
    )


def _pieces(element: ET.Element, context: dict[str, str]):
    """The text of ``element`` as ``(attributes, text)`` pieces, attributes inherited.

    Attributes that place a piece (``x``, ``dy``, ``dx``) belong to the first
    piece of the tspan that carries them only.
    """

    def walk(node: ET.Element, inherited: dict[str, str], placing: dict[str, str]):
        attributes = dict(inherited)
        declared = _css(node.get("style", "")) if node is not element else {}
        for name in _RUN_ATTRIBUTES:
            if name in declared:
                attributes[name] = declared[name]
            elif node.get(name) is not None:
                attributes[name] = node.get(name)  # type: ignore[assignment]
        own = dict(placing)
        if node is not element:
            for name in ("x", "y", "dx", "dy"):
                if node.get(name) is not None:
                    own[name] = node.get(name)  # type: ignore[assignment]
        if node.text:
            yield {**attributes, **own}, node.text
            own = {}
        for child in node:
            if local_name(child.tag) != "tspan":
                continue
            yield from walk(child, attributes, own)
            own = {}
            if child.tail and child.tail.strip():
                yield attributes, child.tail

    names = ("font-family", "font-size", "font-weight", "font-style", "fill")
    base = {name: context[name] for name in names if name in context}
    yield from walk(element, base, {})


_RUN_ATTRIBUTES = (
    *("font-family", "font-size", "font-weight"),
    *("font-style", "baseline-shift", "fill"),
)


def _weight(value: str | None) -> int:
    if value is None:
        return 400
    if value.isdigit():
        return int(value)
    return 700 if value == "bold" else 400


def _face(family: str, weight: int, italic: bool) -> FontFace | None:
    faces = family_faces(family)
    return select_face(faces, weight, italic) if faces else None


_GENERIC = {
    "sans-serif": "IBM Plex Sans",
    "serif": "Latin Modern Roman",
    "monospace": "Liberation Mono",
}


def _faces_for(
    family: str, weight: int, italic: bool, text: str
) -> list[tuple[FontFace, str, str]]:
    """``text`` split into pieces of one face each: the named family where it has
    the characters, else Flexo's fallback families (as a browser falls back)."""

    if not text:
        return []
    names = [family, _GENERIC.get(family.lower(), ""), *DEFAULT_FALLBACKS]
    faces = [(_face(name, weight, italic), name) for name in names if name]
    faces = [(face, name) for face, name in faces if face is not None]
    if not faces:
        return []
    first = faces[0][0]
    if all(load_face(first).has(character) or character.isspace() for character in text):
        return [(first, text, faces[0][1])]
    pieces: list[tuple[FontFace, str, str]] = []
    for character in text:
        face, name = next(
            ((face, name) for face, name in faces if load_face(face).has(character)), faces[0]
        )
        if character.isspace() and pieces:
            face, name = pieces[-1][0], pieces[-1][2]
        if pieces and pieces[-1][0] == face:
            pieces[-1] = (face, pieces[-1][1] + character, name)
        else:
            pieces.append((face, character, name))
    return pieces


def _advance(face: FontFace, weight: int, text: str) -> float:
    """The advance of ``text`` in ``face``, in ems."""

    font = hb_font(face, weight)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True})
    return sum(position.x_advance for position in buffer.glyph_positions) / load_face(face).upem
