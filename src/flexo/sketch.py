"""Hand drawing: any figure redrawn as if by pen, pencil, and brush.

A finished SVG is redrawn in place, after every word and line has been laid
out, so a sketched figure has exactly the layout of the clean one: the boxes are
where they were, the arrows still end on them, the text is still live. Only the
ink changes, after mol-sketch's stroke engine:

- **Lines** are drawn in ``passes`` jittered strokes. The first is the line; the
  others are lighter, a little off it, the way a hand goes back over a line.
  A closed outline starts at a random point and runs a little past where it
  began; a box with square corners is drawn one side at a time, each side
  running past the corner. A connector keeps its two ends exactly, so its
  arrowhead still points where it should.
- **Fills** are one of ``"wash"`` (watercolour: translucent layers, each a
  little deformed, pooling darker at the edge), ``"hatch"`` (pencil lines at an
  angle), ``"solid"`` (flat colour in the wobbling outline), or ``"none"``.
- **Paper** takes a few faint watercolour stains, so a page reads as paper.

``roughness`` is the one number that makes a hand loose or careful: 0 is a
ruled line, 1 a quick sketch. Everything is seeded from the element's id, so a
figure draws the same way every time, and changing one box leaves the rest of
the drawing as it was.
"""

from __future__ import annotations

import itertools
import math
import random
import re
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Literal

from flexo.colour import is_dark, mix
from flexo.svg import local_name, number, svg_tag

type Fill = Literal["wash", "hatch", "solid", "none"]
FILLS: tuple[str, ...] = ("wash", "hatch", "solid", "none")

type Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Sketch:
    """How a figure is drawn by hand; see the module docs."""

    roughness: float = 0.5
    """How loose the hand is: 0 is a ruled line, 1 a quick sketch."""
    passes: int = 2
    """Strokes per line: the line, then lighter strokes going back over it."""
    fill: Fill = "wash"
    """How a box is coloured in: ``"wash"``, ``"hatch"``, ``"solid"``, or ``"none"``."""
    paper: bool = True
    """Whether the page takes a few faint stains, as paper does."""
    seed: int = 0
    """Change it to draw the same figure with a different hand."""

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.roughness) <= 1.0:
            raise ValueError(f"sketch roughness must be from 0 to 1, not {self.roughness}")
        if not 1 <= int(self.passes) <= 4:
            raise ValueError(f"sketch passes must be from 1 to 4, not {self.passes}")
        if self.fill not in FILLS:
            raise ValueError(
                f'unknown sketch fill "{self.fill}"; valid values: {", ".join(FILLS)}'
            )

    def with_updates(self, updates: Mapping[str, object] | Sketch | None) -> Sketch:
        """This hand with ``updates`` laid over it."""

        if updates is None:
            return self
        if isinstance(updates, Sketch):
            updates = updates.changes()
        names = [field.name for field in fields(self)]
        unknown = set(updates) - set(names)
        if unknown:
            raise ValueError(
                f"unknown sketch setting {', '.join(sorted(unknown))}; "
                f"settings are {', '.join(names)}"
            )
        return replace(self, **dict(updates))  # type: ignore[arg-type]

    def changes(self) -> dict[str, object]:
        """The fields that differ from the defaults, as a plain mapping."""

        default = Sketch()
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if getattr(self, field.name) != getattr(default, field.name)
        }


def parse_sketch(value: Mapping[str, object] | Sketch | bool | None) -> Sketch | None:
    """``value`` as a ``Sketch``: ``True`` is the default hand, ``False``/``None`` none."""

    if value is None or value is False:
        return None
    if value is True:
        return Sketch()
    if isinstance(value, Sketch):
        return value
    return Sketch().with_updates(value)


# -- noise -------------------------------------------------------------------------


class _Noise:
    """Smooth value noise along one axis: random values at whole numbers, eased between."""

    def __init__(self, rng: random.Random, size: int = 32) -> None:
        self._values = [rng.uniform(-1.0, 1.0) for _ in range(size)]

    def at(self, x: float) -> float:
        size = len(self._values)
        base = math.floor(x)
        t = x - base
        t = t * t * (3.0 - 2.0 * t)
        a = self._values[base % size]
        b = self._values[(base + 1) % size]
        return a + (b - a) * t


def _rng(*keys: object) -> random.Random:
    return random.Random(zlib.crc32("\x1f".join(str(key) for key in keys).encode()))


# -- geometry ----------------------------------------------------------------------


def _length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def _resample(points: list[Point], step: float) -> list[Point]:
    """``points`` at every ``step`` along the line, keeping its corners."""

    out = [points[0]]
    for a, b in itertools.pairwise(points):
        span = math.dist(a, b)
        pieces = max(1, math.ceil(span / step))
        for index in range(1, pieces + 1):
            u = index / pieces
            out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
    return out


def _normals(points: list[Point]) -> list[Point]:
    result = []
    for index in range(len(points)):
        a = points[max(0, index - 1)]
        b = points[min(len(points) - 1, index + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        size = math.hypot(dx, dy) or 1.0
        result.append((-dy / size, dx / size))
    return result


def _arc(
    start: Point, rx: float, ry: float, rotation: float, large: bool, sweep: bool, end: Point
) -> list[Point]:
    """An SVG elliptical arc as points, by the endpoint-to-centre conversion."""

    if rx == 0 or ry == 0 or start == end:
        return [end]
    phi = math.radians(rotation)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2.0, (start[1] - end[1]) / 2.0
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    scale = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
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
    count = max(4, math.ceil(abs(delta) / (math.pi / 16)))
    points = []
    for index in range(1, count + 1):
        t = theta + delta * index / count
        x, y = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * x - sin * y + cx, sin * x + cos * y + cy))
    return points


_TOKEN = re.compile(r"[MmLlHhVvQqCcSsTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def path_outlines(data: str) -> list[tuple[list[Point], bool]]:
    """The subpaths of an SVG path as ``(points, closed)``, curves flattened."""

    tokens = _TOKEN.findall(data)
    outlines: list[tuple[list[Point], bool]] = []
    current: list[Point] = []
    here: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    command = ""
    index = 0

    def take(count: int) -> list[float]:
        nonlocal index
        values = [float(token) for token in tokens[index : index + count]]
        index += count
        return values

    def flush(closed: bool) -> None:
        nonlocal current
        if len(current) > 1:
            outlines.append((current, closed))
        current = []

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                if current and current[-1] != start:
                    current.append(start)
                flush(True)
                here = start
                continue
        relative = command.islower()
        kind = command.upper()
        ox, oy = here if relative else (0.0, 0.0)
        if kind == "M":
            x, y = take(2)
            flush(False)
            here = start = (ox + x, oy + y)
            current = [here]
            command = "l" if relative else "L"
        elif kind == "L":
            x, y = take(2)
            here = (ox + x, oy + y)
            current.append(here)
        elif kind == "H":
            (x,) = take(1)
            here = ((here[0] if relative else 0.0) + x, here[1])
            current.append(here)
        elif kind == "V":
            (y,) = take(1)
            here = (here[0], (here[1] if relative else 0.0) + y)
            current.append(here)
        elif kind in "QT":
            if kind == "Q":
                qx, qy, x, y = take(4)
                control = (ox + qx, oy + qy)
            else:
                x, y = take(2)
                control = here
            end = (ox + x, oy + y)
            for step in range(1, 9):
                t = step / 8
                current.append(
                    (
                        (1 - t) ** 2 * here[0] + 2 * (1 - t) * t * control[0] + t * t * end[0],
                        (1 - t) ** 2 * here[1] + 2 * (1 - t) * t * control[1] + t * t * end[1],
                    )
                )
            here = end
        elif kind in "CS":
            if kind == "C":
                ax, ay, bx, by, x, y = take(6)
                first = (ox + ax, oy + ay)
            else:
                bx, by, x, y = take(4)
                first = here
            second, end = (ox + bx, oy + by), (ox + x, oy + y)
            for step in range(1, 13):
                t = step / 12
                u = 1 - t
                current.append(
                    (
                        u**3 * here[0] + 3 * u * u * t * first[0] + 3 * u * t * t * second[0]
                        + t**3 * end[0],
                        u**3 * here[1] + 3 * u * u * t * first[1] + 3 * u * t * t * second[1]
                        + t**3 * end[1],
                    )
                )
            here = end
        elif kind == "A":
            rx, ry, rotation, large, sweep, x, y = take(7)
            end = (ox + x, oy + y)
            current.extend(_arc(here, rx, ry, rotation, bool(large), bool(sweep), end))
            here = end
        else:  # pragma: no cover - an unknown command ends the parse
            break
    flush(False)
    return outlines


def _rounded_rect(x: float, y: float, w: float, h: float, rx: float, ry: float) -> list[Point]:
    rx, ry = min(rx, w / 2.0), min(ry, h / 2.0)
    if rx <= 0 or ry <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    points: list[Point] = []
    corners = (
        (x + w - rx, y + ry, -math.pi / 2),
        (x + w - rx, y + h - ry, 0.0),
        (x + rx, y + h - ry, math.pi / 2),
        (x + rx, y + ry, math.pi),
    )
    for cx, cy, first in corners:
        for step in range(7):
            angle = first + (math.pi / 2) * step / 6
            points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    points.append(points[0])
    return points


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Point]:
    count = max(24, round(max(rx, ry) * 1.5))
    points = [
        (cx + rx * math.cos(2 * math.pi * i / count), cy + ry * math.sin(2 * math.pi * i / count))
        for i in range(count)
    ]
    return [*points, points[0]]


def _number(element: ET.Element, name: str, default: float = 0.0) -> float:
    value = element.get(name)
    if value is None:
        return default
    try:
        return float(value.replace("px", "").replace("pt", ""))
    except ValueError:
        return default


def element_outlines(element: ET.Element) -> list[tuple[list[Point], bool]]:
    """The outline(s) an SVG shape draws, as ``(points, closed)``."""

    tag = local_name(element.tag)
    if tag == "rect":
        x, y = _number(element, "x"), _number(element, "y")
        w, h = _number(element, "width"), _number(element, "height")
        rx = _number(element, "rx", _number(element, "ry"))
        ry = _number(element, "ry", rx)
        if w <= 0 or h <= 0:
            return []
        return [(_rounded_rect(x, y, w, h, rx, ry), True)]
    if tag == "circle":
        r = _number(element, "r")
        return [(_ellipse(_number(element, "cx"), _number(element, "cy"), r, r), True)] if r else []
    if tag == "ellipse":
        rx, ry = _number(element, "rx"), _number(element, "ry")
        cx, cy = _number(element, "cx"), _number(element, "cy")
        return [(_ellipse(cx, cy, rx, ry), True)] if rx and ry else []
    if tag == "line":
        return [
            (
                [
                    (_number(element, "x1"), _number(element, "y1")),
                    (_number(element, "x2"), _number(element, "y2")),
                ],
                False,
            )
        ]
    if tag in {"polyline", "polygon"}:
        found = re.findall(r"-?[\d.]+(?:e[-+]?\d+)?", element.get("points", ""))
        values = [float(value) for value in found]
        points = list(zip(values[0::2], values[1::2], strict=False))
        if len(points) < 2:
            return []
        if tag == "polygon":
            return [([*points, points[0]], True)]
        return [(points, False)]
    if tag == "path":
        return path_outlines(element.get("d", ""))
    return []


# -- strokes -----------------------------------------------------------------------


def _wobble(
    points: list[Point],
    *,
    amplitude: float,
    rng: random.Random,
    pinned: bool,
    overshoot: float,
) -> list[Point]:
    """One pass of a hand along ``points``: a drift off the line, and a bow.

    ``pinned`` keeps both ends exactly where they were (a connector's ends, so
    its arrowhead points true); otherwise the stroke runs ``overshoot`` past
    each end, as a quick line does.
    """

    step = max(1.5, min(4.0, _length(points) / 6.0))
    dense = _resample(points, step)
    normals = _normals(dense)
    noise = _Noise(rng)
    total = _length(dense) or 1.0
    bow = rng.uniform(-1.0, 1.0) * amplitude * 0.8
    phase = rng.uniform(0.0, 10.0)
    taper = min(6.0, total / 3.0)
    out: list[Point] = []
    along = 0.0
    for index, (point, normal) in enumerate(zip(dense, normals, strict=True)):
        if index:
            along += math.dist(dense[index - 1], point)
        u = along / total
        offset = amplitude * noise.at(along * 0.06 + phase) + bow * math.sin(math.pi * u)
        if pinned:
            offset *= min(1.0, along / taper, (total - along) / taper) if taper > 0 else 0.0
        out.append((point[0] + normal[0] * offset, point[1] + normal[1] * offset))
    if not pinned and overshoot > 0 and len(out) > 1:
        (ax, ay), (bx, by) = out[0], out[1]
        size = math.hypot(bx - ax, by - ay) or 1.0
        out.insert(0, (ax - (bx - ax) / size * overshoot, ay - (by - ay) / size * overshoot))
        (ax, ay), (bx, by) = out[-2], out[-1]
        size = math.hypot(bx - ax, by - ay) or 1.0
        reach = overshoot * 0.6 / size
        out.append((bx + (bx - ax) * reach, by + (by - ay) * reach))
    return out


def _sharp(points: list[Point]) -> bool:
    """Whether a closed outline turns through square corners (it is a plain polygon)."""

    return len(points) <= 9


def _sides(points: list[Point]) -> list[list[Point]]:
    return [[a, b] for a, b in itertools.pairwise(points) if math.dist(a, b) > 1e-6]


def _loop(points: list[Point], rng: random.Random, extra: float) -> list[Point]:
    """A closed outline started at a random point and carried ``extra`` past it."""

    ring = points[:-1] if points[0] == points[-1] else points
    start = rng.randrange(len(ring))
    ordered = ring[start:] + ring[:start]
    total = _length([*ordered, ordered[0]])
    out = [*ordered, ordered[0]]
    carried = 0.0
    for a, b in itertools.pairwise(ordered):
        span = math.dist(a, b)
        if carried + span >= extra:
            u = (extra - carried) / span if span else 0.0
            out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
            break
        out.append(b)
        carried += span
        if carried > total:
            break
    return out


def _path_data(points: list[Point], closed: bool = False) -> str:
    head = f"M {number(points[0][0])} {number(points[0][1])}"
    body = " ".join(f"L {number(x)} {number(y)}" for x, y in points[1:])
    return f"{head} {body}{' Z' if closed else ''}"


# -- fills -------------------------------------------------------------------------


def _deform(points: list[Point], depth: int, variance: float, rng: random.Random) -> list[Point]:
    """Watercolour's edge: each segment split at a jittered midpoint, ``depth`` times."""

    ring = points[:-1] if points[0] == points[-1] else list(points)
    for _ in range(depth):
        out: list[Point] = []
        for index, a in enumerate(ring):
            b = ring[(index + 1) % len(ring)]
            mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            ex, ey = b[0] - a[0], b[1] - a[1]
            size = math.hypot(ex, ey) or 1.0
            nx, ny = -ey / size, ex / size
            normal = rng.gauss(0.0, 1.0) * variance * min(size, 12.0)
            tangent = rng.gauss(0.0, 1.0) * variance * min(size, 12.0) * 0.35
            along = tangent / size
            middle = (mx + nx * normal + ex * along, my + ny * normal + ey * along)
            out.extend([a, middle])
        ring = out
    return ring


def _hatch_lines(points: list[Point], angle: float, spacing: float) -> list[tuple[Point, Point]]:
    """Parallel lines at ``angle`` across the polygon ``points``, cut to its inside."""

    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    ring = points[:-1] if points[0] == points[-1] else points
    offsets = [px * nx + py * ny for px, py in ring]
    low, high = min(offsets), max(offsets)
    lines = []
    level = low + spacing / 2.0
    while level < high:
        cuts = []
        for index, a in enumerate(ring):
            b = ring[(index + 1) % len(ring)]
            da, db = a[0] * nx + a[1] * ny - level, b[0] * nx + b[1] * ny - level
            if (da < 0) != (db < 0):
                u = da / (da - db)
                point = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
                cuts.append((point[0] * dx + point[1] * dy, point))
        cuts.sort()
        for first, second in zip(cuts[0::2], cuts[1::2], strict=False):
            lines.append((first[1], second[1]))
        level += spacing
    return lines


# -- the pass ------------------------------------------------------------------------

_SHAPES = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})
_PAINT_DATA = ("data-flexo-fill", "data-flexo-stroke")
_GEOMETRY = (
    *("x", "y", "width", "height", "rx", "ry"),
    *("cx", "cy", "r", "x1", "y1", "x2", "y2", "points"),
)


def _paint(element: ET.Element, inherited: dict[str, str], name: str) -> str | None:
    value = element.get(name, inherited.get(name))
    if value is None or value == "none" or value.startswith("url("):
        return None
    return value


def _opacity(element: ET.Element, inherited: dict[str, str], name: str) -> float:
    try:
        return float(element.get(name, inherited.get(name, "1")))
    except ValueError:
        return 1.0


def sketch_svg(root: ET.Element, sketch: Sketch, *, canvas: str = "#ffffff") -> None:
    """Redraw every shape under ``root`` by hand, in place (see the module docs)."""

    dark = is_dark(canvas)
    parents = {child: parent for parent in root.iter() for child in parent}
    inherited: dict[ET.Element, dict[str, str]] = {}

    def paint_of(element: ET.Element) -> dict[str, str]:
        if element in inherited:
            return inherited[element]
        parent = parents.get(element)
        base = dict(paint_of(parent)) if parent is not None else {}
        for name in ("fill", "stroke", "stroke-width", "fill-opacity", "stroke-opacity", "opacity"):
            if element.get(name) is not None:
                base[name] = element.get(name)  # type: ignore[assignment]
        inherited[element] = base
        return base

    shapes = [
        element
        for element in root.iter()
        if local_name(element.tag) in _SHAPES and not _skipped(element, parents)
    ]
    for element in shapes:
        parent = parents[element]
        context = paint_of(parent)
        key = element.get("id") or f"{local_name(element.tag)}{shapes.index(element)}"
        if element.get("id") == "canvas.background":
            # Stains are marks on paper: a transparent page has none.
            if sketch.paper and element.get("fill", "none") != "none":
                _stain_paper(parent, element, sketch, canvas, dark)
            continue
        _sketch_shape(parent, element, context, key, sketch, canvas, dark)


def _skipped(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    """Parts drawn for their exact shape: clip paths, images' frames inside defs."""

    node: ET.Element | None = element
    while node is not None:
        tag = local_name(node.tag)
        if tag in {"clipPath", "mask", "pattern", "linearGradient", "radialGradient", "filter"}:
            return True
        node = parents.get(node)
    return False


def _sketch_shape(
    parent: ET.Element,
    element: ET.Element,
    context: dict[str, str],
    key: str,
    sketch: Sketch,
    canvas: str,
    dark: bool,
) -> None:
    outlines = element_outlines(element)
    if not outlines:
        return
    fill = _paint(element, context, "fill") if local_name(element.tag) != "line" else None
    stroke = _paint(element, context, "stroke")
    try:
        width = float(element.get("stroke-width", context.get("stroke-width", "1")))
    except ValueError:
        width = 1.0
    extent = max(
        max(x for points, _ in outlines for x, _y in points)
        - min(x for points, _ in outlines for x, _y in points),
        max(y for points, _ in outlines for _x, y in points)
        - min(y for points, _ in outlines for _x, y in points),
    )
    in_marker = _inside(element, "marker")
    # A hand wanders less on a small mark: amplitude grows with the shape, up
    # to a point and a half on a large box at full roughness.
    amplitude = sketch.roughness * min(1.5, 0.05 * extent + 0.2) * (0.35 if in_marker else 1.0)
    connector = element.get("marker-end") is not None or element.get("marker-start") is not None
    position = list(parent).index(element)
    inserted: list[ET.Element] = []
    data = {name: element.get(name) for name in _PAINT_DATA if element.get(name) is not None}

    closed_any = any(closed for _, closed in outlines)
    if fill is not None and closed_any and sketch.fill != "none" and not in_marker:
        # A wash or a hatch on a mark a few points across is only noise:
        # small cells (a vector's, a legend swatch) are filled flat.
        hand = sketch if extent >= 14.0 else replace(sketch, fill="solid")
        inserted.extend(_fills(element, outlines, fill, context, key, hand, canvas, dark, data))
    elif fill is not None and in_marker:
        # An arrowhead keeps a solid head; only its edge is redrawn below.
        pass

    strokes: list[str] = []
    if stroke is not None or (fill is not None and in_marker):
        for pass_index in range(sketch.passes):
            rng = _rng(sketch.seed, key, "stroke", pass_index)
            pieces: list[str] = []
            for outline_index, (points, closed) in enumerate(outlines):
                ink_rng = _rng(sketch.seed, key, pass_index, outline_index)
                scale = 1.0 if pass_index == 0 else 1.3
                if closed and _sharp(points) and not in_marker:
                    for side in _sides(points):
                        line = _wobble(
                            side,
                            amplitude=amplitude * scale * 0.6,
                            rng=ink_rng,
                            pinned=False,
                            overshoot=sketch.roughness * 1.8,
                        )
                        pieces.append(_path_data(line))
                elif closed and not in_marker:
                    loop = _loop(points, rng, extra=min(8.0, _length(points) * 0.08))
                    line = _wobble(
                        loop, amplitude=amplitude * scale, rng=ink_rng, pinned=True, overshoot=0.0
                    )
                    pieces.append(_path_data(line))
                else:
                    line = _wobble(
                        points,
                        amplitude=amplitude * scale,
                        rng=ink_rng,
                        pinned=connector or in_marker or closed,
                        overshoot=0.0 if connector else sketch.roughness * 1.2,
                    )
                    pieces.append(_path_data(line, closed and in_marker))
            strokes.append(" ".join(pieces))

    if not strokes:
        if inserted:
            element.set("fill", "none")
            for offset, item in enumerate(inserted):
                parent.insert(position + offset, item)
        return
    # The element keeps its id, its data, and its markers, and becomes the first pass.
    element.tag = svg_tag("path")
    for name in _GEOMETRY:
        element.attrib.pop(name, None)
    element.set("d", strokes[0])
    if not in_marker:
        element.set("fill", "none")
        element.attrib.pop("data-flexo-fill", None)
        element.set("stroke-linecap", "round")
        element.set("stroke-linejoin", "round")
    extra_passes = []
    for pass_index, data_string in enumerate(strokes[1:], start=1):
        again = ET.Element(svg_tag("path"))
        again.set("id", f"{key}.pass{pass_index}")
        again.set("d", data_string)
        again.set("fill", "none")
        colour = stroke if stroke is not None else fill
        again.set("stroke", colour or "#000")
        if "data-flexo-stroke" in data:
            again.set("data-flexo-stroke", data["data-flexo-stroke"] or "")
        elif in_marker and "data-flexo-fill" in data:
            again.set("data-flexo-stroke", data["data-flexo-fill"] or "")
        again.set("stroke-width", number(width * (0.7 if not in_marker else 0.5)))
        again.set("stroke-opacity", number(0.45 * _opacity(element, context, "stroke-opacity")))
        again.set("stroke-linecap", "round")
        again.set("stroke-linejoin", "round")
        if element.get("stroke-dasharray") is not None:
            again.set("stroke-dasharray", element.get("stroke-dasharray") or "")
        extra_passes.append(again)
    for offset, item in enumerate(inserted):
        parent.insert(position + offset, item)
    after = list(parent).index(element) + 1
    for offset, item in enumerate(extra_passes):
        parent.insert(after + offset, item)


def _inside(element: ET.Element, tag: str) -> bool:
    return (element.get("id") or "").startswith("arrow.") if tag == "marker" else False


def _fills(
    element: ET.Element,
    outlines: list[tuple[list[Point], bool]],
    fill: str,
    context: dict[str, str],
    key: str,
    sketch: Sketch,
    canvas: str,
    dark: bool,
    data: dict[str, str | None],
) -> list[ET.Element]:
    """The colouring-in of one closed shape, as elements drawn under its outline."""

    opacity = _opacity(element, context, "fill-opacity") * _opacity(element, context, "opacity")
    role = data.get("data-flexo-fill")
    if role == "container-fill":
        # A container is the ground its boxes stand on: the faintest wash.
        opacity *= 0.45
    out: list[ET.Element] = []
    for outline_index, (points, closed) in enumerate(outlines):
        if not closed or len(points) < 3:
            continue
        rng = _rng(sketch.seed, key, "fill", outline_index)
        if sketch.fill == "solid":
            shape = _deform(points, 1, 0.02 * sketch.roughness, rng)
            out.append(_filled(f"{key}.fill{outline_index}", shape, fill, opacity, role))
        elif sketch.fill == "wash":
            # Stacked translucent layers, each a little deformed and scaled,
            # pool darker where they overlap -- toward the middle and in a
            # ring where the paint dried at the edge.
            cx = sum(x for x, _ in points) / len(points)
            cy = sum(y for _, y in points) / len(points)
            shift = (rng.uniform(-1, 1) * sketch.roughness, rng.uniform(-1, 1) * sketch.roughness)
            layers = 4
            base = _deform(points, 1, 0.03, rng)
            for layer in range(layers):
                scale = 0.97 + rng.uniform(0.0, 0.05)
                scaled = [
                    (cx + (x - cx) * scale + shift[0], cy + (y - cy) * scale + shift[1])
                    for x, y in base
                ]
                shape = _deform(scaled, 2, 0.02 + 0.03 * sketch.roughness, rng)
                item = _filled(
                    f"{key}.wash{outline_index}.{layer}", shape, fill, opacity * 0.22, role
                )
                if not dark:
                    item.set("style", "mix-blend-mode:multiply")
                out.append(item)
            edge = _deform(base, 1, 0.02, rng)
            ring = _filled(f"{key}.edge{outline_index}", edge, "none", 1.0, None)
            ring.set("stroke", mix(fill, "#000000", 0.18))
            if role:
                ring.set("data-flexo-stroke", role)
            ring.set("stroke-width", "0.6")
            ring.set("stroke-opacity", number(0.35 * opacity))
            out.append(ring)
        elif sketch.fill == "hatch" and role == "container-fill":
            # Hatching a whole panel would bury its contents: a pale tint only.
            out.append(_filled(f"{key}.tint{outline_index}", points, fill, opacity * 0.6, role))
        elif sketch.fill == "hatch":
            angle = math.radians(-50.0 + rng.uniform(-6.0, 6.0))
            # Pale enough on light paper that the outline and the words stay on top.
            hatch = fill if dark else mix(fill, "#000000", 0.12)
            under = _filled(f"{key}.tint{outline_index}", points, fill, opacity * 0.35, role)
            out.append(under)
            lines = _hatch_lines(_deform(points, 1, 0.01, rng), angle, 2.2)
            pieces = []
            for line_index, (a, b) in enumerate(lines):
                wobbled = _wobble(
                    [a, b],
                    amplitude=0.4 * sketch.roughness,
                    rng=_rng(sketch.seed, key, "hatch", line_index),
                    pinned=False,
                    overshoot=sketch.roughness * 0.8,
                )
                pieces.append(_path_data(wobbled))
            if pieces:
                strokes = ET.Element(svg_tag("path"))
                strokes.set("id", f"{key}.hatch{outline_index}")
                strokes.set("d", " ".join(pieces))
                strokes.set("fill", "none")
                strokes.set("stroke", hatch)
                if role:
                    strokes.set("data-flexo-stroke", role)
                strokes.set("stroke-width", "0.55")
                strokes.set("stroke-opacity", number(0.8 * opacity))
                strokes.set("stroke-linecap", "round")
                out.append(strokes)
    return out


def _filled(
    identifier: str, points: list[Point], fill: str, opacity: float, role: str | None
) -> ET.Element:
    item = ET.Element(svg_tag("path"))
    item.set("id", identifier)
    item.set("d", _path_data(points, closed=True))
    item.set("fill", fill)
    if role and fill != "none":
        item.set("data-flexo-fill", role)
    if opacity < 1.0:
        item.set("fill-opacity", number(opacity))
    return item


def _stain_paper(
    parent: ET.Element, background: ET.Element, sketch: Sketch, canvas: str, dark: bool
) -> None:
    """A few faint, broad watercolour stains over the page, as on paper that was worked on."""

    width, height = _number(background, "width"), _number(background, "height")
    if width <= 0 or height <= 0:
        return
    rng = _rng(sketch.seed, "paper")
    # A stain is the page's own colour, deeper: sepia on cream, grey on white.
    tint = mix(canvas, "#ffffff" if dark else "#000000", 0.45)
    position = list(parent).index(background) + 1
    for index in range(3):
        cx, cy = rng.uniform(0.1, 0.9) * width, rng.uniform(0.1, 0.9) * height
        rx = rng.uniform(0.2, 0.45) * width
        ry = rng.uniform(0.3, 0.7) * height
        blob = _deform(_ellipse(cx, cy, rx, ry)[::4], 4, 0.16, rng)
        item = _filled(f"paper.stain{index}", blob, tint, 0.012 + 0.012 * rng.random(), None)
        parent.insert(position + index, item)
