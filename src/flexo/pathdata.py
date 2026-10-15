"""SVG path data, as a ``path`` shape (``flexo.freeform``) writes its outline: read, every
command absolute and relative, what is wrong said in words, and written back as absolute moves,
lines, cubics and closes to a hundredth of a point.

A path's ``d`` is in its page's units, y down. It is read into the segments every shape is
drawn from -- ``("M", x, y)``, ``("L", x, y)``, ``("C", x1, y1, x2, y2, x, y)``, ``("Z",)`` --
its quadratics raised to cubics, its arcs cut into cubics a quarter turn at most each, its
horizontal and vertical lines made lines, a close followed by anything but a move starting its
next piece where the last began (as SVG has it), and a move with nothing drawn from it left
out. What is read is kept by its words (``parsed``): a path drawn again and again -- a drawing
of hundreds of them, thousands of points each -- is read once, and what is found from it
(its outline flattened, where lines meet it) is found once. The studio reads them as this does
(``studio/static/studio/pathdata.js``, kept to it by a test).
"""

from __future__ import annotations

import contextlib
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

type Point = tuple[float, float]
type Segment = tuple[Any, ...]

LIMIT = 100_000.0
"""How far from the page's corner a point may be written: further is a mistake, not a place."""
MOST = 100_000
"""How many pieces (lines, curves, closes) a path may have."""
EXAMPLE = '"M 10 10 L 60 10 L 60 40 Z"'

_TAKES = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
_SAYS = {
    "M": "x y",
    "L": "x y",
    "H": "x",
    "V": "y",
    "C": "x1 y1 x2 y2 x y",
    "S": "x2 y2 x y",
    "Q": "x1 y1 x y",
    "T": "x y",
    "A": "rx ry turn large-arc sweep x y",
}
_NUMBERED = r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_TOKEN = re.compile(rf"([MmLlHhVvCcSsQqTtAaZz])|({_NUMBERED})|([ \t\n\r\f\v,]+)|(.)", re.S)
_NUMBER = re.compile(_NUMBERED)


class PathError(ValueError):
    """Path data written wrong: what is wrong, in words."""


# -- reading -------------------------------------------------------------------------------


def _begun(data: str) -> str:
    text = " ".join(data.split())
    return repr(text if len(text) <= 16 else text[:15] + "…")


def _tokens(data: str) -> list[list[Any]]:
    """Each command and number, with where it is (from 0): ``[text, place, is a command]``."""

    out: list[list[Any]] = []
    for found in _TOKEN.finditer(data):
        command, value, _, other = found.groups()
        if command:
            out.append([command, found.start(), True])
        elif value:
            out.append([value, found.start(), False])
        elif other:
            raise PathError(
                f"{other!r} at character {found.start() + 1} is not a path command or a number: "
                "the commands are M, L, H, V, C, S, Q, T, A and Z (in lower case, relative)."
            )
    return out


def _arc(
    start: Point, rx: float, ry: float, turn: float, large: bool, sweep: bool, end: Point
) -> list[Segment]:
    """An elliptical arc as cubics, a quarter turn at most each (SVG's own reading of one:
    radii too small for its ends grown until they reach)."""

    if start[0] == end[0] and start[1] == end[1]:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0.0 or ry == 0.0:
        return [("L", end[0], end[1])]
    phi = turn % 360.0 * math.pi / 180.0
    cos, sin = math.cos(phi), math.sin(phi)
    hx, hy = (start[0] - end[0]) / 2.0, (start[1] - end[1]) / 2.0
    x1 = cos * hx + sin * hy
    y1 = -sin * hx + cos * hy
    reach = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if reach > 1.0:
        grow = math.sqrt(reach)
        rx, ry = rx * grow, ry * grow
    above = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    below = rx * rx * y1 * y1 + ry * ry * x1 * x1
    share = math.sqrt(max(0.0, above / below)) if below > 0.0 else 0.0
    if large == sweep:
        share = -share
    cx1 = share * rx * y1 / ry
    cy1 = -share * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2.0
    cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2.0
    ux, uy = (x1 - cx1) / rx, (y1 - cy1) / ry
    vx, vy = (-x1 - cx1) / rx, (-y1 - cy1) / ry
    theta = math.atan2(uy, ux)
    delta = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi
    pieces = max(1, math.ceil(abs(delta) / (math.pi / 2.0) - 1e-9))
    step = delta / pieces
    k = 4.0 / 3.0 * math.tan(step / 4.0)

    def at(u: float, v: float) -> Point:
        return (cx + cos * rx * u - sin * ry * v, cy + sin * rx * u + cos * ry * v)

    out: list[Segment] = []
    for piece in range(pieces):
        a = theta + piece * step
        b = a + step
        ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
        first, second = at(ca - k * sa, sa + k * ca), at(cb + k * sb, sb - k * cb)
        last = end if piece == pieces - 1 else at(cb, sb)
        out.append(("C", *first, *second, *last))
    return out


def _flag(tokens: list[list[Any]], index: int, said: str, at: int, which: str) -> tuple[bool, int]:
    """An arc's flag, read off the front of the next number (``0110`` is two flags and 10)."""

    if index >= len(tokens) or tokens[index][2]:
        raise PathError(
            f"{said} at character {at + 1} needs 7 numbers ({_SAYS['A']}), but its {which} "
            "flag is missing."
        )
    text, place, _ = tokens[index]
    if text[0] not in "01":
        raise PathError(
            f"the arc at character {at + 1} has a {which} flag of {text!r}: a flag is 0 or 1."
        )
    rest = text[1:]
    if not rest:
        return text[0] == "1", index + 1
    if not _NUMBER.fullmatch(rest):
        raise PathError(f"{rest!r} at character {place + 2} is not a number.")
    tokens[index] = [rest, place + 1, False]
    return text[0] == "1", index


_SPACE = r"[ \t\n\r]"
_PLAIN_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_PLAIN = re.compile(
    rf"{_SPACE}*M(?:{_SPACE}+{_PLAIN_NUMBER}){{2}}(?:{_SPACE}+(?:[ML](?:{_SPACE}+{_PLAIN_NUMBER}){{2}}"
    rf"|C(?:{_SPACE}+{_PLAIN_NUMBER}){{6}}|Z))*{_SPACE}*"
)
_LETTERS = frozenset("MLCZ")


def _plain(data: str) -> list[Segment] | None:
    """``data`` read quickly where it is written as it is written back -- absolute moves, lines,
    cubics and closes, each letter and number apart -- else nothing (it is read word by word)."""

    if not _PLAIN.fullmatch(data):
        return None
    words = data.split()
    numbers = [float(word) for word in words if word not in _LETTERS]
    out: list[Segment] = []
    start = (0.0, 0.0)
    at = 0
    for word in words:
        if word not in _LETTERS:
            continue
        if word == "Z":
            if out[-1][0] != "Z":
                out.append(("Z",))
            continue
        if word == "M":
            x, y = numbers[at], numbers[at + 1]
            at += 2
            if out and out[-1][0] == "M":
                out[-1] = ("M", x, y)
            else:
                out.append(("M", x, y))
            start = (x, y)
            continue
        if out[-1][0] == "Z":
            out.append(("M", *start))
        if word == "L":
            out.append(("L", numbers[at], numbers[at + 1]))
            at += 2
        else:
            out.append(("C", *numbers[at : at + 6]))
            at += 6
    return out


def _parse(data: str) -> list[Segment]:
    quick = _plain(data)
    if quick is not None:
        return _finished(quick)
    tokens = _tokens(data)
    if not tokens:
        raise PathError(f"d is empty: a path needs a move and a line at least, such as {EXAMPLE}.")
    if not tokens[0][2] or tokens[0][0] not in "Mm":
        raise PathError(
            f"a path starts with M (a move to its first point), such as {EXAMPLE}, "
            f"not {_begun(data)}."
        )
    out: list[Segment] = []
    here: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    cubic: Point | None = None
    quad: Point | None = None
    command = said = ""
    at = 0
    index, count = 0, len(tokens)
    repeated = False
    while index < count:
        token = tokens[index]
        if token[2]:
            command, at = token[0], token[1]
            said = command
            index += 1
            repeated = False
            if command in "Zz":
                if out and out[-1][0] != "Z":
                    out.append(("Z",))
                here, cubic, quad = start, None, None
                if index < count and not tokens[index][2]:
                    raise PathError(
                        f"{tokens[index][0]!r} at character {tokens[index][1] + 1} follows Z, "
                        "which takes no numbers: a command (L, C ...) comes before them."
                    )
                continue
        upper = command.upper()
        relative = command != upper
        ox, oy = here if relative else (0.0, 0.0)
        if upper == "A":
            values: list[float] = []
            for _ in range(3):
                if index >= count or tokens[index][2]:
                    values = []
                    break
                values.append(float(tokens[index][0]))
                index += 1
            if len(values) < 3:
                raise PathError(
                    f"{said} at character {at + 1} needs 7 numbers ({_SAYS['A']})"
                    + (" at a time: some are left over." if repeated else ", but some are missing.")
                )
            large, index = _flag(tokens, index, said, at, "large-arc")
            sweep, index = _flag(tokens, index, said, at, "sweep")
            for _ in range(2):
                if index >= count or tokens[index][2]:
                    raise PathError(
                        f"{said} at character {at + 1} needs 7 numbers ({_SAYS['A']}), but its "
                        "end is missing."
                    )
                values.append(float(tokens[index][0]))
                index += 1
        else:
            takes = _TAKES[upper]
            values = []
            while len(values) < takes:
                if index >= count or tokens[index][2]:
                    have = len(values)
                    has = (
                        f"{have} {'is' if have == 1 else 'are'} left over"
                        if repeated
                        else f"it has {have or 'none'}"
                    )
                    raise PathError(
                        f"{said} at character {at + 1} needs {takes} numbers "
                        f"({_SAYS[said.upper()]}){' at a time' if repeated else ''}, but {has}."
                    )
                values.append(float(tokens[index][0]))
                index += 1
        repeated = True
        if upper == "M":
            point = (ox + values[0], oy + values[1])
            if out and out[-1][0] == "M":
                out[-1] = ("M", *point)
            else:
                out.append(("M", *point))
            here = start = point
            cubic = quad = None
            command = "l" if relative else "L"
            continue
        if out[-1][0] == "Z":
            out.append(("M", *start))
        if upper in "LHV":
            if upper == "L":
                point = (ox + values[0], oy + values[1])
            elif upper == "H":
                point = ((here[0] if relative else 0.0) + values[0], here[1])
            else:
                point = (here[0], (here[1] if relative else 0.0) + values[0])
            out.append(("L", *point))
            here, cubic, quad = point, None, None
        elif upper in "CS":
            if upper == "C":
                first = (ox + values[0], oy + values[1])
                rest = values[2:]
            else:
                first = (2.0 * here[0] - cubic[0], 2.0 * here[1] - cubic[1]) if cubic else here
                rest = values
            second = (ox + rest[0], oy + rest[1])
            end = (ox + rest[2], oy + rest[3])
            out.append(("C", *first, *second, *end))
            here, cubic, quad = end, second, None
        elif upper in "QT":
            if upper == "Q":
                control = (ox + values[0], oy + values[1])
                end = (ox + values[2], oy + values[3])
            else:
                control = (2.0 * here[0] - quad[0], 2.0 * here[1] - quad[1]) if quad else here
                end = (ox + values[0], oy + values[1])
            out.append(
                (
                    "C",
                    here[0] + 2.0 / 3.0 * (control[0] - here[0]),
                    here[1] + 2.0 / 3.0 * (control[1] - here[1]),
                    end[0] + 2.0 / 3.0 * (control[0] - end[0]),
                    end[1] + 2.0 / 3.0 * (control[1] - end[1]),
                    *end,
                )
            )
            here, cubic, quad = end, None, control
        else:
            end = (ox + values[3], oy + values[4])
            out.extend(_arc(here, values[0], values[1], values[2], large, sweep, end))
            here, cubic, quad = end, None, None
    return _finished(out)


def _finished(out: list[Segment]) -> list[Segment]:
    """What was read, a move with nothing after it left out, checked: it draws, it is not too
    long, and it is on (or near) the page."""

    if out and out[-1][0] == "M":
        out.pop()
    if not any(segment[0] in ("L", "C") for segment in out):
        raise PathError(
            f"d only moves: a path needs a line or a curve after its M, such as {EXAMPLE}."
        )
    if len(out) > MOST:
        raise PathError(f"d has {len(out):,} pieces: a path has {MOST:,} at most.")
    far = max(abs(value) for segment in out for value in segment[1:])
    if not far <= LIMIT:
        raise PathError(
            f"d has a point {far:g} points from the page: a point must be on it, or near it."
        )
    return out


# -- what is read, kept --------------------------------------------------------------------


class Parsed:
    """Path data as read: its segments, the box round what they draw (``x, y, width, height``),
    whether its first piece and its last are open (where arrowheads go), whether it was
    written plainly -- absolute moves, lines, cubics and closes, as SVG reads them, so it may
    be drawn as it is written (``plain``) -- and what is found from it when first asked, kept
    with it (``kept``)."""

    __slots__ = ("box", "found", "opens", "plain", "segments")

    def __init__(self, segments: Sequence[Segment], *, plain: bool = False) -> None:
        self.plain = plain
        self.segments: tuple[Segment, ...] = tuple(segments)
        left, top, right, bottom = extent(self.segments)
        self.box = (left, top, right - left, bottom - top)
        starts = [index for index, segment in enumerate(self.segments) if segment[0] == "M"]
        first_end = starts[1] - 1 if len(starts) > 1 else len(self.segments) - 1
        self.opens = (self.segments[first_end][0] != "Z", self.segments[-1][0] != "Z")
        self.found: dict[Any, Any] = {}

    def kept(self, key: object, make: Callable[[], Any]) -> Any:
        found = self.found.get(key)
        if found is None:
            found = self.found[key] = make()
        return found


_READ: OrderedDict[str, Parsed] = OrderedDict()
_KEPT = 4096
_LOCK = threading.Lock()


def _keep(data: str, made: Parsed) -> None:
    with _LOCK:
        _READ[data] = made
        _READ.move_to_end(data)
        while len(_READ) > _KEPT:
            _READ.popitem(last=False)


def parsed(data: str) -> Parsed:
    """``data`` read (``PathError`` if it is wrong), kept by its words."""

    with _LOCK:
        found = _READ.get(data)
        if found is not None:
            _READ.move_to_end(data)
            return found
    quick = _plain(data)
    made = Parsed(_finished(quick), plain=True) if quick is not None else Parsed(_parse(data))
    _keep(data, made)
    return made


def segments_of(data: str) -> list[Segment]:
    """``data`` as absolute moves, lines, cubics and closes."""

    return list(parsed(data).segments)


# -- writing -------------------------------------------------------------------------------


def _hundredths(value: float) -> int:
    """How many hundredths ``value`` is, a half rounded up (as JavaScript's ``Math.round``)."""

    scaled = value * 100.0
    whole = math.floor(scaled)
    return int(whole) + (1 if scaled - whole >= 0.5 else 0)


def _figure(hundredths: int) -> str:
    """A number of hundredths as the words of what it is: 1234 "12.34", 1230 "12.3", -5
    "-0.05". (As the studio says them, word for word.)"""

    if hundredths == 0:
        return "0"
    sign = "-" if hundredths < 0 else ""
    whole, part = divmod(abs(hundredths), 100)
    if not part:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{part:02d}".rstrip("0")


def written(segments: Sequence[Segment]) -> str:
    """Segments as path data: absolute moves, lines, cubics and closes, to a hundredth."""

    words: list[str] = []
    for segment in segments:
        words.append(segment[0])
        words.extend(_figure(_hundredths(value)) for value in segment[1:])
    return " ".join(words)


def _rewritten(segments: Sequence[Segment]) -> str:
    """Segments written, and what the words say kept as read: the same, to a hundredth."""

    kept = [
        (segment[0], *(_hundredths(value) / 100.0 for value in segment[1:])) for segment in segments
    ]
    data = written(kept)
    # (Kept only where its words read as right: moved off the page, they are said wrong.)
    with contextlib.suppress(PathError):
        _keep(data, Parsed(_finished(kept), plain=True))
    return data


def normalised(data: str) -> str:
    """``data`` written as absolute moves, lines, cubics and closes, to a hundredth."""

    return _rewritten(parsed(data).segments)


def mapped(data: str, map: Callable[[Point], Point]) -> str:
    """``data`` with every point mapped (its curves' controls too: for a map that moves,
    stretches, turns or mirrors), written again."""

    out: list[Segment] = []
    for segment in parsed(data).segments:
        values = segment[1:]
        placed: list[float] = []
        for index in range(0, len(values), 2):
            placed.extend(map((values[index], values[index + 1])))
        out.append((segment[0], *placed))
    return _rewritten(out)


_MOVED: OrderedDict[tuple[str, float, float], str] = OrderedDict()


def moved(data: str, dx: float, dy: float) -> str:
    """``data`` moved by ``dx``, ``dy``. (Kept: a shape on a figure's part is moved to it each
    time the figure is drawn.)"""

    key = (data, float(dx), float(dy))
    with _LOCK:
        found = _MOVED.get(key)
        if found is not None:
            _MOVED.move_to_end(key)
            return found
    made = mapped(data, lambda point: (point[0] + dx, point[1] + dy))
    with _LOCK:
        _MOVED[key] = made
        while len(_MOVED) > _KEPT:
            _MOVED.popitem(last=False)
    return made


def fitted(data: str, box: Sequence[float]) -> str:
    """``data`` stretched to fill ``box`` (``x, y, width, height``), as a polyline's points are
    stretched round parts."""

    x, y, w, h = (float(value) for value in box)
    left, top, across, down = parsed(data).box
    across, down = across or 1.0, down or 1.0
    return mapped(data, lambda p: (x + (p[0] - left) / across * w, y + (p[1] - top) / down * h))


# -- geometry ------------------------------------------------------------------------------


def _roots(a: float, b: float, c: float) -> list[float]:
    """Where ``a t² + b t + c`` is nought, strictly between 0 and 1."""

    if abs(a) < 1e-12:
        if abs(b) < 1e-12:
            return []
        found = [-c / b]
    else:
        under = b * b - 4.0 * a * c
        if under < 0.0:
            return []
        root = math.sqrt(under)
        found = [(-b + root) / (2.0 * a), (-b - root) / (2.0 * a)]
    return [t for t in found if 0.0 < t < 1.0]


def extent(
    segments: Sequence[Segment], turn: float = 0.0, centre: Point = (0.0, 0.0)
) -> tuple[float, float, float, float]:
    """``left, top, right, bottom`` of what segments draw -- a curve's own reach, not its
    controls' -- turned ``turn`` degrees about ``centre``."""

    angle = turn * math.pi / 180.0
    cos, sin = (math.cos(angle), math.sin(angle)) if turn else (1.0, 0.0)
    ox, oy = centre

    def place(x: float, y: float) -> Point:
        if not turn:
            return (x, y)
        dx, dy = x - ox, y - oy
        return (ox + cos * dx - sin * dy, oy + sin * dx + cos * dy)

    left = top = math.inf
    right = bottom = -math.inf
    here: Point = (0.0, 0.0)
    for segment in segments:
        kind = segment[0]
        if kind == "Z":
            continue
        end = place(segment[-2], segment[-1])
        left, right = min(left, end[0]), max(right, end[0])
        top, bottom = min(top, end[1]), max(bottom, end[1])
        if kind == "C":
            one, two = place(segment[1], segment[2]), place(segment[3], segment[4])
            for axis in (0, 1):
                p0, p1, p2, p3 = here[axis], one[axis], two[axis], end[axis]
                low, high = (left, right) if axis == 0 else (top, bottom)
                if low <= min(p1, p2) and max(p1, p2) <= high:
                    continue
                for t in _roots(p3 - 3.0 * p2 + 3.0 * p1 - p0, 2.0 * (p0 - 2.0 * p1 + p2), p1 - p0):
                    u = 1.0 - t
                    value = (
                        u * u * u * p0
                        + 3.0 * u * u * t * p1
                        + 3.0 * u * t * t * p2
                        + t * t * t * p3
                    )
                    if axis == 0:
                        left, right = min(left, value), max(right, value)
                    else:
                        top, bottom = min(top, value), max(bottom, value)
        here = end
    if left > right:
        return (0.0, 0.0, 0.0, 0.0)
    return (left, top, right, bottom)


def _steps(p0: Point, p1: Point, p2: Point, p3: Point) -> int:
    """Into how many lines a cubic is cut, by how long its controls reach: more for a longer
    one. (The same in the studio: a length's root, not its hypotenuse function's.)"""

    reach = 0.0
    for a, b in ((p0, p1), (p1, p2), (p2, p3)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        reach += math.sqrt(dx * dx + dy * dy)
    return max(1, min(24, math.ceil(math.sqrt(reach) - 1e-9)))


def rings(segments: Sequence[Segment]) -> list[tuple[list[Point], bool]]:
    """Each piece of a path as points along it (its curves cut into lines), and whether it is
    closed. (Filled, an open one is closed by a line back to its start, as SVG fills it.)"""

    out: list[tuple[list[Point], bool]] = []
    points: list[Point] = []
    here: Point = (0.0, 0.0)
    for segment in segments:
        kind = segment[0]
        if kind == "M":
            if len(points) > 1:
                out.append((points, False))
            here = (segment[1], segment[2])
            points = [here]
        elif kind == "L":
            here = (segment[1], segment[2])
            points.append(here)
        elif kind == "C":
            p1, p2, p3 = (
                (segment[1], segment[2]),
                (segment[3], segment[4]),
                (segment[5], segment[6]),
            )
            steps = _steps(here, p1, p2, p3)
            for step in range(1, steps):
                t = step / steps
                u = 1.0 - t
                a, b, c, d = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t
                points.append(
                    (
                        a * here[0] + b * p1[0] + c * p2[0] + d * p3[0],
                        a * here[1] + b * p1[1] + c * p2[1] + d * p3[1],
                    )
                )
            points.append(p3)
            here = p3
        else:
            out.append((points, True))
            points = []
    if len(points) > 1:
        out.append((points, False))
    return out


def crossing(outlines: Sequence[Sequence[Point]], inside: Point, outside: Point) -> Point | None:
    """Where the line from ``inside`` to ``outside`` last crosses any of ``outlines`` (each
    closed), if it does."""

    best_t = -1.0
    ax, ay = inside
    bx, by = outside
    ex, ey = bx - ax, by - ay
    for outline in outlines:
        count = len(outline)
        if count < 2:
            continue
        cx, cy = outline[-1]
        for dx, dy in outline:
            fx, fy = dx - cx, dy - cy
            below = ex * fy - ey * fx
            if abs(below) >= 1e-12:
                t = ((cx - ax) * fy - (cy - ay) * fx) / below
                u = ((cx - ax) * ey - (cy - ay) * ex) / below
                if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 and t > best_t:
                    best_t = t
            cx, cy = dx, dy
    if best_t < 0.0:
        return None
    return (ax + ex * best_t, ay + ey * best_t)


def nearest(outlines: Sequence[Sequence[Point]], point: Point) -> Point | None:
    """The point on any of ``outlines`` (each closed) nearest ``point``."""

    best: tuple[float, Point] | None = None
    px, py = point
    for outline in outlines:
        if not outline:
            continue
        ax, ay = outline[-1]
        for bx, by in outline:
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length)) if length else 0.0
            qx, qy = ax + dx * t, ay + dy * t
            far = (px - qx) * (px - qx) + (py - qy) * (py - qy)
            if best is None or far < best[0]:
                best = (far, (qx, qy))
            ax, ay = bx, by
    return best[1] if best else None


def inside(outlines: Sequence[Sequence[Point]], point: Point, rule: str = "nonzero") -> bool:
    """Whether ``point`` is in what ``outlines`` (each closed) fill, by the fill ``rule``
    (``nonzero`` or ``evenodd``)."""

    px, py = point
    winding = 0
    for outline in outlines:
        if len(outline) < 3:
            continue
        ax, ay = outline[-1]
        for bx, by in outline:
            if (ay > py) != (by > py):
                across = (bx - ax) * (py - ay) / (by - ay) + ax
                if px < across:
                    winding += 1 if by > ay else -1
            ax, ay = bx, by
    return winding % 2 == 1 if rule == "evenodd" else winding != 0


class Outline:
    """A path placed on its page -- mirrored and turned about its box's middle -- as what a line
    is glued to: its outline's rings (``rings``), and where a line meets it on each side
    (``sites``): on its outline, level with its middle (or straight above, below), as a
    box's sides' middles are on a box. Each is found when first asked, and kept."""

    __slots__ = ("flip", "read", "turn")

    def __init__(self, read: Parsed, flip: str | None, turn: float) -> None:
        self.read, self.flip, self.turn = read, flip or None, float(turn or 0.0)

    @property
    def centre(self) -> Point:
        x, y, w, h = self.read.box
        return (x + w / 2.0, y + h / 2.0)

    def _local(self) -> list[list[Point]]:
        """Its rings mirrored as it is, not turned."""

        def make() -> list[list[Point]]:
            plain = self.read.kept("rings", lambda: rings(self.read.segments))
            if not self.flip:
                return [points for points, _ in plain]
            cx, cy = self.centre
            sx = -1.0 if self.flip in ("horizontal", "both") else 1.0
            sy = -1.0 if self.flip in ("vertical", "both") else 1.0
            return [
                [(cx + sx * (x - cx), cy + sy * (y - cy)) for x, y in points] for points, _ in plain
            ]

        return self.read.kept(("local", self.flip), make)

    def _turned(self, point: Point) -> Point:
        if not self.turn:
            return point
        angle = self.turn * math.pi / 180.0
        cos, sin = math.cos(angle), math.sin(angle)
        cx, cy = self.centre
        dx, dy = point[0] - cx, point[1] - cy
        return (cx + cos * dx - sin * dy, cy + sin * dx + cos * dy)

    def rings(self) -> list[list[Point]]:
        """Its outline's rings on the page, each closed."""

        def make() -> list[list[Point]]:
            local = self._local()
            if not self.turn:
                return local
            return [[self._turned(point) for point in ring] for ring in local]

        return self.read.kept(("rings", self.flip, self.turn), make)

    def sites(self) -> dict[str, Point]:
        """Where a line glued to it meets it, by side, and its middle (``centre``)."""

        def make() -> dict[str, Point]:
            x, y, w, h = self.read.box
            cx, cy = self.centre
            local = self._local()
            places = {
                "top": (cx, y),
                "right": (x + w, cy),
                "bottom": (cx, y + h),
                "left": (x, cy),
            }
            found: dict[str, Point] = {}
            for side, (px, py) in places.items():
                far = (cx + (px - cx) * 1.01, cy + (py - cy) * 1.01)
                met = crossing(local, (cx, cy), far) if far != (cx, cy) else None
                found[side] = self._turned(met or nearest(local, (px, py)) or (px, py))
            found["centre"] = (cx, cy)
            return found

        return self.read.kept(("sites", self.flip, self.turn), make)


# -- PowerPoint's filling ------------------------------------------------------------------


def _area(points: Sequence[Point]) -> float:
    total = 0.0
    ax, ay = points[-1]
    for bx, by in points:
        total += ax * by - bx * ay
        ax, ay = bx, by
    return total / 2.0


def fill_groups(segments: Sequence[Segment], rule: str = "nonzero") -> list[list[Segment]]:
    """A path's pieces gathered so that each gathering, filled even-odd on its own (as a
    PowerPoint freeform fills each of its paths) and the gatherings over one another, fill what
    the path fills by ``rule``: even-odd, one gathering; non-zero, a piece in another that winds
    the same way as it starts a gathering of its own (as it is filled, not a hole)."""

    pieces: list[list[Segment]] = []
    for segment in segments:
        if segment[0] == "M" or not pieces:
            pieces.append([])
        pieces[-1].append(segment)
    if rule == "evenodd" or len(pieces) < 2:
        return [list(segments)]
    flat = [rings(piece) for piece in pieces]
    outlines = [found[0][0] if found and len(found[0][0]) > 2 else [] for found in flat]
    areas = [_area(points) if points else 0.0 for points in outlines]
    order = sorted(range(len(pieces)), key=lambda index: -abs(areas[index]))
    group_of: dict[int, int] = {}
    groups: list[list[int]] = []
    for place, index in enumerate(order):
        parent = None
        if outlines[index]:
            probe = outlines[index][0]
            for other in reversed(order[:place]):
                if outlines[other] and inside([outlines[other]], probe, "evenodd"):
                    parent = other
                    break
        if parent is not None and (areas[parent] > 0) != (areas[index] > 0):
            group_of[index] = group_of[parent]
            groups[group_of[parent]].append(index)
        else:
            group_of[index] = len(groups)
            groups.append([index])
    ordered = sorted(groups, key=min)
    return [[segment for index in sorted(group) for segment in pieces[index]] for group in ordered]
