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
from typing import Literal

import uharfbuzz as hb

from flexo.fonts import FontFace, family_faces, hb_font, load_face, select_face
from flexo.svg import local_name

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


@dataclass(frozen=True, slots=True)
class Image:
    id: str | None
    x: float
    y: float
    width: float
    height: float
    href: str


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
    """The drawing a Flexo SVG makes (see the module docs)."""

    root = ET.fromstring(svg_text)
    view = [float(value) for value in root.get("viewBox", "0 0 0 0").split()]
    markers = {
        item.get("id"): item for item in root.iter() if local_name(item.tag) == "marker"
    }
    drawing = Group(root.get("id"))
    _read_children(root, drawing, {}, 1.0, markers, IDENTITY)
    return Drawing(view[2], view[3], drawing)


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
        else:
            raise ValueError(f"unsupported transform {name}(): flexo writes translate and scale")
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


def _transformed(item, matrix: Matrix):
    """``item`` (a shape, text, or image) moved and scaled by ``matrix``."""

    if matrix == IDENTITY:
        return item
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
        return replace(
            item, x=x, lines=lines, size=item.size * scale, line_height=item.line_height * scale
        )
    if isinstance(item, Image):
        x, y = _map(matrix, (item.x, item.y))
        return replace(item, x=x, y=y, width=item.width * scale, height=item.height * scale)
    return item


def _read_children(
    element: ET.Element,
    group: Group,
    inherited: dict[str, str],
    opacity: float,
    markers: dict[str | None, ET.Element],
    matrix: Matrix,
) -> None:
    for child in element:
        tag = local_name(child.tag)
        if tag in {"defs", "title", "desc", "metadata", "style", "marker", "clipPath"}:
            continue
        context = dict(inherited)
        for name in _INHERITED:
            value = child.get(name)
            if value is not None:
                context[name] = value
        # A painted element without a role of its own keeps no inherited one.
        for part in ("fill", "stroke"):
            if child.get(part) is not None and child.get(f"data-flexo-{part}") is None:
                context.pop(f"data-flexo-{part}", None)
        alpha = opacity * float(child.get("opacity", "1"))
        placed = _compose(matrix, _parse_transform(child.get("transform")))
        if tag == "g":
            nested = Group(
                child.get("id"),
                data={k: v for k, v in child.attrib.items() if k.startswith("data-flexo-")},
                label=child.get("{http://www.inkscape.org/namespaces/inkscape}label"),
            )
            _read_children(child, nested, context, alpha, markers, placed)
            if nested.items:
                group.items.append(nested)
        elif tag in {"rect", "circle", "ellipse", "path", "line", "polyline", "polygon"}:
            shape = _shape(child, tag, context, alpha, markers)
            if shape is not None:
                group.items.append(_transformed(shape, placed))
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
                ), placed)
            )


def _float(element: ET.Element, name: str, default: float = 0.0) -> float:
    value = element.get(name)
    return float(value) if value not in (None, "") else default


def _paint(context: dict[str, str], opacity: float) -> Paint:
    def colour(name: str) -> str | None:
        value = context.get(name)
        return None if value in (None, "none") or value.startswith("url(") else value

    fill = colour("fill") if "fill" in context else "#000000"
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
    for piece in pieces:
        attributes, text = piece
        if "x" in attributes or not lines:
            if lines and "dy" in attributes:
                step = float(attributes["dy"])
                line_height = line_height or step
                line_baseline += step
            lines.append([])
            pen = float(attributes.get("x", x))
        if "dx" in attributes:
            step = float(attributes["dx"])
            if step < -1e-6:
                simple = False
            pen += step
        run_family = attributes.get("font-family", family).split(",")[0].strip().strip("'\"")
        run_size = float(attributes.get("font-size", size))
        declared = attributes.get("font-weight")
        run_weight = _weight(declared) if declared is not None else weight
        italic = attributes.get("font-style", "normal") == "italic"
        shift = float(attributes.get("baseline-shift", "0") or 0)
        face = _face(run_family, run_weight, italic)
        width = _advance(face, run_weight, text) * run_size if face else 0.0
        if text:
            lines[-1].append(
                Run(
                    text,
                    pen,
                    line_baseline - shift,
                    width,
                    run_size,
                    run_weight,
                    italic,
                    face,  # type: ignore[arg-type]
                    attributes.get("fill", fill),
                    role,
                    run_family,
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
        for name in _RUN_ATTRIBUTES:
            if node.get(name) is not None:
                attributes[name] = node.get(name)  # type: ignore[assignment]
        own = dict(placing)
        if node is not element:
            for name in ("x", "dx", "dy"):
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

    names = ("font-family", "font-size", "font-weight", "fill")
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


def _advance(face: FontFace, weight: int, text: str) -> float:
    """The advance of ``text`` in ``face``, in ems."""

    font = hb_font(face, weight)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True})
    return sum(position.x_advance for position in buffer.glyph_positions) / load_face(face).upem
