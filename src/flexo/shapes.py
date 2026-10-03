"""Shapes drawn from an outline: a database's cylinder, a cloud, a page, a person.

Flowcharts and architecture diagrams draw things that are not boxes -- a
database is a cylinder, the internet a cloud, a file a page with a wavy foot, a
user a person -- and each is still a component: sized round its label, wired at
its sides, painted in the theme's roles, so a palette or a dark theme recolours
it with everything else.

Everything such a shape draws is made here from its bounds, and so is the
outline a line is brought to. A line meets a cylinder at its lid and a document
at its wavy foot, not at the corner of the box around them: routing keeps its
pins on the box, and ``ink_depth`` says how much further in the drawn outline
lies, which the painted line then reaches across (``flexo.routing.trees``).

The kinds:

- ``database``: a cylinder, its lid an ellipse (PowerPoint's *can*, the
  flowchart's stored data), its label on the side below the lid;
- ``server``: a rack -- the unit that carries the label over two slim ones, each
  with a drive slot and its lights;
- ``cloud``: a cloud of round puffs, its label among them;
- ``queue``: a box whose end is divided into slots, messages waiting in them;
- ``document``: a page with a wavy bottom edge (the flowchart's document);
- ``person``: a person -- a head and shoulders -- with the label under it;
- ``io``: the flowchart's input/output, a parallelogram.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from functools import cache, lru_cache

from flexo.geometry import Point, Rect, Size
from flexo.ir.measured import TextMetrics
from flexo.style import LayoutStyle
from flexo.svg import number

SHAPE_KINDS = frozenset({"database", "server", "cloud", "queue", "document", "person", "io"})

LID = 0.125
"""A database lid's depth (half the ellipse's height) as a fraction of the cylinder's
shorter side, as PowerPoint draws its can."""

RACK_UNIT = 0.6
"""Height of one of a server's two rack units, in ems of the label's type."""

SLOT = 0.75
"""Width of one of a queue's three slots, in ems."""

SLOTS = 3

SLANT = 0.4
"""How far an input/output parallelogram leans: its top is set this fraction of its
height to the right of its bottom (at most a quarter of its width)."""

WAVE = 0.8
"""Where a document's straight sides end and its wavy foot begins, as a fraction of
its height. The label is set above it."""

FIGURE = 3.0
"""How tall a person is, head to waist, in ems: about a block's height."""

SHOULDERS = 0.7
"""How far down a person's figure, head to waist, its sides take a line."""


@dataclass(frozen=True, slots=True)
class Outline:
    """What a shape paints, as SVG path data in the figure's coordinates.

    ``body`` is filled and outlined, and it is the outline lines are brought to.
    ``lines`` are drawn over it in the body's stroke (a lid's rim, a server's rack
    units, a queue's slots); ``marks`` are small solid marks (a server's lights);
    ``cells`` are tinted (the messages waiting in a queue).
    """

    body: str
    lines: str = ""
    marks: str = ""
    cells: str = ""


def _path(*commands: object) -> str:
    return " ".join(
        number(item) if isinstance(item, float | int) else str(item) for item in commands
    )


def _inset(bounds: Rect, style: LayoutStyle) -> Rect:
    """The bounds less half a stroke all round, so the ink stays inside the box."""

    half = style.stroke_width.points / 2.0
    return Rect(
        bounds.x + half,
        bounds.y + half,
        max(0.0, bounds.width - 2.0 * half),
        max(0.0, bounds.height - 2.0 * half),
    )


def _rack(em: float) -> float:
    """How much of a server's height its two slim rack units take, gaps and all."""

    return 2.0 * (RACK_UNIT * em + _rack_gap(em))


def _rack_gap(em: float) -> float:
    return max(1.0, 0.16 * em)


def lid_depth(bounds: Rect | Size) -> float:
    """Half the height of a database's lid: an eighth of its shorter side."""

    return LID * min(bounds.width, bounds.height)


def slant(bounds: Rect | Size) -> float:
    """How far an input/output's top sits to the right of its bottom."""

    return min(SLANT * bounds.height, 0.25 * bounds.width)


def person_frame(
    bounds: Rect | Size, label: TextMetrics, style: LayoutStyle
) -> tuple[float, float]:
    """Where a person's figure starts below the top of its box, and how tall it is.

    The name goes under the figure, and as much room again goes over its head, so
    the middle of the box -- where a line meets each side -- is at the figure's
    shoulders (``SHOULDERS`` of the way down) rather than beside its name.
    """

    band = _person_band(label, style)
    figure = (bounds.height - 2.0 * band) / (2.0 - 2.0 * SHOULDERS)
    if band >= (2.0 * SHOULDERS - 1.0) * figure:
        above = band - (2.0 * SHOULDERS - 1.0) * figure
    else:
        # No name, or a short one under a tall figure: nothing above the head.
        figure, above = bounds.height - band, 0.0
    return max(0.0, above), max(0.0, min(figure, bounds.width / 0.85))


def _person_band(label: TextMetrics, style: LayoutStyle) -> float:
    if not label.lines:
        return 0.0
    return _person_gap(style) + label.height


def _person_gap(style: LayoutStyle) -> float:
    return 0.25 * style.typography.size.points


# -- sizes -----------------------------------------------------------------------------


def shape_size(kind: str, label: TextMetrics, style: LayoutStyle) -> Size:
    """The natural size of a shape: its label, padded, in the room the outline leaves."""

    em = style.typography.size.points
    pad_x, pad_y = style.padding_x.points, style.padding_y.points
    words = Size(label.width + 2.0 * pad_x, label.height + 2.0 * pad_y)
    if kind == "database":
        # The label sits between the lid and the curve of the foot: three lid
        # depths more than a box, the lid an eighth of the shorter side.
        width = max(44.0, words.width)
        height = words.height / (1.0 - 3.0 * LID)
        if height > width:
            height = words.height + 3.0 * LID * width
        return Size(width, height)
    if kind == "server":
        return Size(max(44.0, words.width), max(24.0, words.height) + _rack(em))
    if kind == "queue":
        slots = SLOTS * SLOT * em
        return Size(max(44.0 + slots, words.width + slots), max(24.0, words.height))
    if kind == "document":
        return Size(max(44.0, words.width), max(30.0, words.height / WAVE))
    if kind == "io":
        height = max(26.0, words.height)
        lean = SLANT * height
        # At the top and bottom of its lines the slanted sides are further in than
        # at the middle: the label's box has to clear them there.
        reach = lean * (1.0 + label.height / height)
        return Size(max(44.0 + lean, words.width + reach), height)
    if kind == "cloud":
        # The label, with half a box's padding, in the room among the puffs.
        room_x, room_y = CLOUD_ROOM
        width = max(60.0, (label.width + pad_x) / room_x)
        height = max(34.0, (label.height + pad_y) / room_y, 0.45 * width)
        return Size(width, height)
    if kind == "person":
        figure = FIGURE * em
        band = _person_band(label, style)
        above = max(0.0, band - (2.0 * SHOULDERS - 1.0) * figure)
        return Size(max(0.85 * figure, label.width + 2.0), above + figure + band)
    raise ValueError(f"not a shape: {kind}")


def label_room(kind: str, width: float, style: LayoutStyle) -> float:
    """How wide a shape's label may run in a shape ``width`` wide."""

    em = style.typography.size.points
    room = width - 2.0 * style.padding_x.points
    if kind == "queue":
        room -= SLOTS * SLOT * em
    elif kind == "io":
        room -= min(1.4 * SLANT * 26.0, 0.35 * width)
    elif kind == "cloud":
        room = width * CLOUD_ROOM[0] - style.padding_x.points
    elif kind == "person":
        room = width - 2.0
    return max(1.0, room)


CLOUD_ROOM = (0.72, 0.5)
"""The share of a cloud's width and height its label's box may take, centred among
its puffs: the largest such box that keeps inside the dips between them."""

CLOUD_MEASURE = 9.0
"""The longest a cloud's label line runs, in ems: a longer name takes two lines, so
the cloud stays a cloud rather than a long flat lozenge."""


def label_area(kind: str, bounds: Rect, label: TextMetrics, style: LayoutStyle) -> Rect:
    """The part of a shape's bounds its label is centred in."""

    em = style.typography.size.points
    if kind == "database":
        lid = lid_depth(bounds)
        height = max(0.0, bounds.height - 3.0 * lid)
        return Rect(bounds.x, bounds.y + 2.0 * lid, bounds.width, height)
    if kind == "server":
        return Rect(bounds.x, bounds.y, bounds.width, max(0.0, bounds.height - _rack(em)))
    if kind == "queue":
        slots = min(SLOTS * SLOT * em, bounds.width / 2.0)
        return Rect(bounds.x, bounds.y, bounds.width - slots, bounds.height)
    if kind == "document":
        return Rect(bounds.x, bounds.y, bounds.width, bounds.height * WAVE)
    if kind == "cloud":
        (x, y), (room_x, room_y) = _cloud()[1], CLOUD_ROOM
        return Rect(
            bounds.x + (x - room_x / 2.0) * bounds.width,
            bounds.y + (y - room_y / 2.0) * bounds.height,
            room_x * bounds.width,
            room_y * bounds.height,
        )
    if kind == "person":
        top = bounds.bottom - _person_band(label, style) + _person_gap(style)
        return Rect(bounds.x, top, bounds.width, max(0.0, bounds.bottom - top))
    return bounds


# -- outlines --------------------------------------------------------------------------


def outline(kind: str, bounds: Rect, label: TextMetrics, style: LayoutStyle) -> Outline:
    """Everything ``kind`` paints in ``bounds``."""

    box = _inset(bounds, style)
    em = style.typography.size.points
    left, top, right, bottom = box.left, box.top, box.right, box.bottom
    if kind == "database":
        lid = min(lid_depth(bounds), box.height / 3.0)
        rx = box.width / 2.0
        body = _path(
            "M", left, top + lid, "V", bottom - lid,
            "A", rx, lid, 0, 0, 0, right, bottom - lid,
            "V", top + lid,
            "A", rx, lid, 0, 0, 0, left, top + lid, "Z",
        )
        # The near half of the lid's rim, over the body.
        rim = _path("M", left, top + lid, "A", rx, lid, 0, 0, 0, right, top + lid)
        return Outline(body, lines=rim)
    if kind == "server":
        # A rack: the unit that carries the name, and two slim ones under it, each
        # with a drive slot at its left and two lights at its right.
        unit = min(RACK_UNIT * em, box.height / 5.0)
        gap = min(_rack_gap(em), unit / 3.0)
        slim = [
            Rect(left, bottom - unit, box.width, unit),
            Rect(left, bottom - 2.0 * unit - gap, box.width, unit),
        ]
        named = Rect(left, top, box.width, max(0.0, slim[1].top - gap - top))
        radius = min(style.corner_radius.points, named.height / 3.0, box.width / 4.0)
        body = " ".join(
            [_rounded(named, radius), *(_rounded(rack, min(radius, unit / 2.5)) for rack in slim)]
        )
        light = max(0.6, 0.11 * em)
        reach = min(1.8 * em, box.width / 3.0)
        lines = " ".join(
            _path("M", left + 0.7 * em, rack.center.y, "h", reach) for rack in slim
        )
        lights = " ".join(
            _circle(right - 0.7 * em - index * 3.0 * light, rack.center.y, light)
            for rack in slim
            for index in range(2)
        )
        return Outline(body, lines=lines, marks=lights)
    if kind == "queue":
        radius = min(style.corner_radius.points, box.height / 4.0)
        pitch = min(SLOT * em, box.width / (2.0 * SLOTS))
        xs = [right - k * pitch for k in range(SLOTS, 0, -1)]
        lines = " ".join(_path("M", x, top, "V", bottom) for x in xs)
        # Every slot but the last holds a message, so the queue reads as one
        # with room at its tail.
        inset = max(1.0, 0.18 * em)
        size = Size(max(0.0, pitch - 2.0 * inset), max(0.0, box.height - 2.0 * inset))
        cells = " ".join(
            _rounded(Rect(x + inset, top + inset, size.width, size.height), 0.6) for x in xs[:-1]
        )
        return Outline(_rounded(box, radius), lines=lines, cells=cells)
    if kind == "document":
        y0, (c1, c2, end) = top + box.height * _wave()[0], _wave()[1]
        body = _path(
            "M", left, top, "H", right, "V", y0,
            "C", left + c1[0] * box.width, top + c1[1] * box.height,
            left + c2[0] * box.width, top + c2[1] * box.height,
            left + end[0] * box.width, top + end[1] * box.height,
            "Z",
        )
        return Outline(body)
    if kind == "io":
        lean = slant(box)
        body = _path(
            "M", left + lean, top, "H", right, "L", right - lean, bottom, "H", left, "Z"
        )
        return Outline(body)
    if kind == "cloud":
        start, arcs = _cloud()[0]
        commands: list[object] = [
            "M", left + start[0] * box.width, top + start[1] * box.height,
        ]
        for (rx, ry), large, (x, y) in arcs:
            commands += [
                "A", rx * box.width, ry * box.height, 0, int(large), 1,
                left + x * box.width, top + y * box.height,
            ]
        return Outline(_path(*commands, "Z"))
    if kind == "person":
        above, figure = person_frame(bounds, label, style)
        pen = style.stroke_width.points
        return Outline(_person(box, above, figure - pen))
    raise ValueError(f"not a shape: {kind}")


def _rounded(box: Rect, radius: float) -> str:
    r = max(0.0, min(radius, box.width / 2.0, box.height / 2.0))
    left, top, right, bottom = box.left, box.top, box.right, box.bottom
    if r <= 0.0:
        return _path("M", left, top, "H", right, "V", bottom, "H", left, "Z")
    return _path(
        "M", left + r, top, "H", right - r, "A", r, r, 0, 0, 1, right, top + r,
        "V", bottom - r, "A", r, r, 0, 0, 1, right - r, bottom,
        "H", left + r, "A", r, r, 0, 0, 1, left, bottom - r,
        "V", top + r, "A", r, r, 0, 0, 1, left + r, top, "Z",
    )


def _circle(cx: float, cy: float, r: float) -> str:
    return _path(
        "M", cx - r, cy, "A", r, r, 0, 1, 0, cx + r, cy, "A", r, r, 0, 1, 0, cx - r, cy, "Z"
    )


def _person(box: Rect, above: float, figure: float) -> str:
    """A head and shoulders, ``figure`` tall, ``above`` from the top of ``box``."""

    figure = max(0.0, figure)
    cx, top = box.center.x, box.top + above
    head = 0.2 * figure
    width = min(0.85 * figure, box.width)
    shoulders = top + 2.0 * head + 0.07 * figure
    bottom = top + figure
    radius = min(0.42 * width, max(0.0, bottom - shoulders))
    left, right = cx - width / 2.0, cx + width / 2.0
    body = _path(
        "M", left, bottom, "V", shoulders + radius,
        "A", radius, radius, 0, 0, 1, left + radius, shoulders,
        "H", right - radius,
        "A", radius, radius, 0, 0, 1, right, shoulders + radius,
        "V", bottom, "Z",
    )
    return f"{_circle(cx, top + head, head)} {body}"


@cache
def _wave() -> tuple[float, tuple[tuple[float, float], ...]]:
    """A document's foot in the unit square: where its right side ends, and the
    curve (two controls and an end) back to its left side.

    PowerPoint's document, scaled so that the trough of the wave is the bottom of
    the page: a line meets the foot where it is drawn, not short of it.
    """

    start, c1, c2, end = (1.0, 0.802), (0.5, 0.802), (0.5, 1.1075), (0.0, 0.934)
    lowest = max(_bezier(start, c1, c2, end, step / 200.0)[1] for step in range(201))
    scale = 1.0 / lowest
    return start[1] * scale, (
        (c1[0], c1[1] * scale),
        (c2[0], c2[1] * scale),
        (end[0], end[1] * scale),
    )


def _bezier(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u**3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t**3 * d[0],
        u**3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t**3 * d[1],
    )


_CLOUD_PUFFS = (
    # (where a puff's centre sits round the ellipse they stand on, in degrees
    # counter-clockwise from the right; its radius, where the ellipse is 2 by 1)
    (180.0, 0.36),
    (140.0, 0.42),
    (95.0, 0.52),
    (45.0, 0.44),
    (5.0, 0.36),
    (-35.0, 0.34),
    (-80.0, 0.36),
    (-125.0, 0.36),
    (-160.0, 0.34),
)
"""A cloud: nine round puffs in a ring, the largest on top, as Keynote and
PowerPoint draw one. Its outline is the outside of their union."""


@cache
def _cloud() -> tuple[
    tuple[tuple[float, float], tuple[tuple[tuple[float, float], bool, tuple[float, float]], ...]],
    tuple[float, float],
]:
    """The cloud in the unit square: where it starts, and each puff's arc (its radii,
    whether it is the larger arc, and its end); and the middle of its puffs, where
    the label is set.

    Each arc runs clockwise round one puff from where it meets the puff before to
    where it meets the next; the whole is scaled to fill the unit square, so the
    outermost puff on each side touches the shape's box.
    """

    circles = [
        (math.cos(math.radians(angle)), -0.5 * math.sin(math.radians(angle)), radius)
        for angle, radius in sorted(_CLOUD_PUFFS, key=lambda puff: -puff[0])
    ]
    count = len(circles)
    centre = (sum(x for x, _, _ in circles) / count, sum(y for _, y, _ in circles) / count)
    dips = [_outer_meeting(circles[i], circles[(i + 1) % count], centre) for i in range(count)]
    arcs = []
    samples = []
    for index, (x, y, radius) in enumerate(circles):
        start, end = dips[index - 1], dips[index]
        first = math.atan2(start[1] - y, start[0] - x)
        last = math.atan2(end[1] - y, end[0] - x)
        while last < first:
            last += 2.0 * math.pi
        arcs.append((radius, last - first > math.pi, end))
        samples += [
            (x + radius * math.cos(angle), y + radius * math.sin(angle))
            for angle in (first + (last - first) * step / 32.0 for step in range(33))
        ]
    x0 = min(x for x, _ in samples)
    y0 = min(y for _, y in samples)
    width = max(x for x, _ in samples) - x0
    height = max(y for _, y in samples) - y0

    def unit(point: tuple[float, float]) -> tuple[float, float]:
        return ((point[0] - x0) / width, (point[1] - y0) / height)

    return (
        unit(dips[-1]),
        tuple(((radius / width, radius / height), large, unit(end)) for radius, large, end in arcs),
    ), unit(centre)


def _outer_meeting(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    centre: tuple[float, float],
) -> tuple[float, float]:
    """Where two neighbouring puffs cross on the outside of the cloud."""

    (x1, y1, r1), (x2, y2, r2) = first, second
    apart = math.hypot(x2 - x1, y2 - y1)
    along = (r1 * r1 - r2 * r2 + apart * apart) / (2.0 * apart)
    across = math.sqrt(max(0.0, r1 * r1 - along * along))
    mx, my = x1 + along * (x2 - x1) / apart, y1 + along * (y2 - y1) / apart
    ux, uy = (y2 - y1) / apart, -(x2 - x1) / apart
    return max(
        ((mx + across * ux, my + across * uy), (mx - across * ux, my - across * uy)),
        key=lambda point: math.dist(point, centre),
    )


# -- where lines meet the outline ------------------------------------------------------


def ink_depth(
    kind: str,
    bounds: Rect,
    label: TextMetrics,
    style: LayoutStyle,
    point: Point,
    direction: tuple[float, float],
) -> float:
    """How far from ``point`` on a shape's box, going ``direction`` into it, its outline is.

    Zero for a box, and wherever the ray finds no outline within the box. A
    person's label is solid for this, so a line from below stops under the name
    rather than running through it to the figure.
    """

    if kind not in SHAPE_KINDS:
        return 0.0
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0
    dx, dy = dx / length, dy / length
    reach = bounds.width + bounds.height
    best = math.inf
    for polyline in _hit_lines(kind, bounds, label, style):
        for (ax, ay), (bx, by) in itertools.pairwise(polyline):
            hit = _ray_hits(point.x, point.y, dx, dy, ax, ay, bx, by)
            if hit is not None and hit < best:
                best = hit
    if best is math.inf or best > reach:
        return 0.0
    return max(0.0, best)


def _hit_lines(
    kind: str, bounds: Rect, label: TextMetrics, style: LayoutStyle
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """The outline a line meets, as polylines: the body, and a person's name."""

    lines = _flatten(outline(kind, bounds, label, style).body)
    if kind == "person" and label.lines:
        area = label_area(kind, bounds, label, style)
        words = Rect(
            area.center.x - label.width / 2.0, area.y, label.width, min(label.height, area.height)
        )
        corners = (
            (words.left, words.top),
            (words.right, words.top),
            (words.right, words.bottom),
            (words.left, words.bottom),
        )
        lines += ((*corners, corners[0]),)
    return lines


@lru_cache(maxsize=1024)
def _flatten(data: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Path data as polylines, its curves cut into short straight pieces."""

    from flexo.drawing import parse_path

    lines: list[list[tuple[float, float]]] = []
    here = start = (0.0, 0.0)
    for segment in parse_path(data):
        if segment.kind == "M":
            here = start = segment.points[0]
            lines.append([here])
        elif segment.kind == "L":
            here = segment.points[0]
            lines[-1].append(here)
        elif segment.kind == "C":
            c1, c2, end = segment.points
            lines[-1] += [_bezier(here, c1, c2, end, step / 12.0) for step in range(1, 13)]
            here = end
        else:
            lines[-1].append(start)
            here = start
    return tuple(tuple(line) for line in lines)


def _ray_hits(
    px: float, py: float, dx: float, dy: float, ax: float, ay: float, bx: float, by: float
) -> float | None:
    """How far along the ray from (px, py) going (dx, dy) it crosses segment a-b."""

    ex, ey = bx - ax, by - ay
    denominator = dx * ey - dy * ex
    if abs(denominator) < 1e-12:
        return None
    wx, wy = ax - px, ay - py
    t = (wx * ey - wy * ex) / denominator
    s = (wx * dy - wy * dx) / denominator
    if t < -1e-9 or s < -1e-9 or s > 1.0 + 1e-9:
        return None
    return t
