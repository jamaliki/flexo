"""A diagram drawn as shapes, read as a figure's parts.

A diagram drawn in Inkscape and pasted in, drawn on a slide, or drawn over a figure arrives as
shapes (``flexo.freeform``): boxes with words in them, arrows between them, words alone, a box
round some of them with a title over it. ``recognise`` reads such shapes as the figure they
draw, so that it takes the figure's theme, spacing and layout, and is edited as anything built
in flexo is:

- a closed shape with words is a **part** of the kind nearest its outline: a rectangle (a
  hexagon, a trapezoid) a ``block``; a pill a ``terminal`` (a start or an end); a diamond a
  ``decision``; a parallelogram an ``io``; a circle with a name of a few letters a ``circle``,
  with one symbol an ``op``; an oval a ``terminal``; a cloud a ``cloud``. Its words are its own,
  or those laid on it (a text box inside it); its fill is the theme's tone nearest it
  (``tone: 2``) -- a grey, white or none none -- or, with no tone near, its own colour
  (``paint-fill``); a dashed outline is dashed, a shadow a shadow, bold words bold;
- words alone are a ``text`` part;
- a line whose ends are glued to two of them, or end near them, is a **line** between them:
  its heads its direction (``arrow: none``, ``both``) and its heads' shapes (``head``,
  ``tail``), its dashes its ``line``, a curve ``curved``, words on it (its own, or words laid
  beside it) its ``label``; one coloured unlike the rest a ``tone``. A line ending on the box
  round some parts ends at the part in it nearest its end;
- a closed shape round others is a **group** of them: a ``module`` titled by the words over it
  or in its top band, else a frame (``container``);
- what a group holds is laid out as it was drawn: a ``row``, a ``column`` or a ``grid`` where
  they line up, else cut into rows and columns where the drawing has gaps (a column of rows, a
  row of columns), each laid out so in turn; parts drawn the same size are made so
  (``equal_size``);
- what is no part of a diagram stays a shape -- a highlight, a ring, a brace, a free curve, a
  line with an end at nothing -- attached to the parts it was drawn at: ``around`` those it goes
  round (a brace along their side), a line's end glued to the part it ends at (``{part: id}``),
  and ``on`` the part nearest it, its places measured from that part's top left.

Places are the units the shapes are drawn in (a figure's points, a slide's 960 across), y down.
``recognise`` answers with the parts as a figure file writes them (``Recognised``);
``figure_document`` with a whole figure file's document, and ``figure_of`` with the figure.
"""

from __future__ import annotations

import copy
import functools
import itertools
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from flexo import freeform

type Box = tuple[float, float, float, float]
"""left, top, right, bottom."""

NOT_PARTS = frozenset({"highlight", "ring", "bubble", "check", "cross", "plus", "star"})
"""Closed shapes that mark a diagram up rather than draw part of it: a highlight, a ring, a
callout, a tick -- kept as shapes, whatever words they have."""

MEASURES = frozenset({"brace", "bracket", "dimension", "scale-bar"})
"""Lines that measure or gather what they are beside: kept as shapes."""

KINDS = {
    "rectangle": "block",
    "rounded-rectangle": "block",
    "diamond": "decision",
    "parallelogram": "io",
    "trapezoid": "block",
    "polygon": "block",
    "cloud": "cloud",
    "triangle": "block",
    "right-triangle": "block",
    "chevron": "block",
    "arrow-right": "block",
    "arrow-left": "block",
    "arrow-up": "block",
    "arrow-down": "block",
    "arrow-left-right": "block",
    "polyline": "block",
    "pen": "block",
    "text": "block",
}
"""The kind of part each closed shape with words becomes (an ellipse and a rounded rectangle
by their proportions too: ``_kind``)."""

SYMBOLS = {
    "+": "+",
    "\N{CIRCLED PLUS}": "+",
    "\N{MULTIPLICATION SIGN}": "\N{MULTIPLICATION SIGN}",
    "x": "\N{MULTIPLICATION SIGN}",
    "*": "\N{MULTIPLICATION SIGN}",
    "\N{CIRCLED TIMES}": "\N{MULTIPLICATION SIGN}",
    "\N{MIDDLE DOT}": "\N{MIDDLE DOT}",
    "\N{CIRCLED DOT OPERATOR}": "\N{MIDDLE DOT}",
    "-": "\N{MINUS SIGN}",
    "\N{MINUS SIGN}": "\N{MINUS SIGN}",
    "~": "~",
    "\N{GREEK CAPITAL LETTER SIGMA}": "\N{GREEK SMALL LETTER SIGMA}",
    "\N{GREEK SMALL LETTER SIGMA}": "\N{GREEK SMALL LETTER SIGMA}",
}
"""Words that are an operator's symbol alone, and the symbol an ``op`` draws for each."""

HEADS = {
    "triangle": "arrow",
    "stealth": "stealth",
    "open": "open",
    "dot": "dot",
    "circle": "catalysis",
    "bar": "inhibition",
    "diamond": "diamond",
}
"""A drawn line's end, as a figure's line's head: a triangle the theme's arrow; an open circle
and a bar the heads that look like them."""

HUE_NEAR = 40.0
"""How far round the colour wheel (degrees) a fill may be from a tone's and still be it."""
SAME_HUE = 15.0
"""How near in hue two fills are that are one colour, the one lighter: one tone."""
GREY = 5.0
"""How little colour (CIELAB chroma) a fill has that is grey, white or black: no tone. (A
tone's own light tint has little more: 9 or 10.)"""


@dataclass(slots=True)
class Recognised:
    """A diagram's parts, as a figure file writes them, and what stays a shape."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    """The groups made, the outermost first; each a group as a figure file writes it."""
    top: list[str] = field(default_factory=list)
    """What the diagram's outermost level holds, in order: one part or group, or several."""
    layout: dict[str, Any] = field(default_factory=dict)
    """How ``top`` is laid out, when it holds several (``{kind: row}``)."""
    shapes: list[dict[str, Any]] = field(default_factory=list)
    """The shapes kept as shapes, as written, attached to the parts they were drawn at."""
    taken: list[int] = field(default_factory=list)
    """The places, in the list recognised, of the shapes made parts (a group's, all of it)."""
    kept: list[int] = field(default_factory=list)
    """The places of the shapes kept, each that of its own in ``shapes`` -- a group some of whose
    shapes were made parts is kept as the rest of it."""
    parts: dict[str, str] = field(default_factory=dict)
    """The id each shape made a part had, and the part it is now: for what was glued to it."""
    box: Box = (0.0, 0.0, 0.0, 0.0)
    """Where the diagram was drawn: its parts' box."""
    notes: list[str] = field(default_factory=list)
    """What was read one way that might have been read another, in words."""

    @property
    def said(self) -> str:
        """What was made, in a few words: "5 shapes, 4 lines and a group; 2 kept as shapes"."""

        def count(number: int, noun: str) -> str:
            return f"{'a' if number == 1 else number} {noun}{'' if number == 1 else 's'}"

        made = [count(len(self.nodes), "shape")]
        if self.edges:
            made.append(count(len(self.edges), "line"))
        framed = [group for group in self.groups if group.get("role") != "layout"]
        if framed:
            made.append(count(len(framed), "group"))
        words = made[0] if len(made) == 1 else f"{', '.join(made[:-1])} and {made[-1]}"
        if self.shapes:
            words += f"; {len(self.shapes)} kept as shape{'' if len(self.shapes) == 1 else 's'}"
        return words[:1].upper() + words[1:]


# -- reading what is drawn -------------------------------------------------------------------


@dataclass(eq=False)
class _Leaf:
    at: int
    """Its place among the leaves."""
    top: int
    """The place, in the list given, of the shape it is (or is one of a group's)."""
    spec: dict[str, Any]
    drawn: dict[str, Any]
    box: Box
    words: str = ""
    role: str = ""
    """``block``, ``frame``, ``text``, ``line`` or ``mark``: what it is in the diagram."""
    outline: list[tuple[float, float]] | None = None
    ends: tuple[tuple[float, float], tuple[float, float]] | None = None
    path: list[tuple[float, float]] = field(default_factory=list)
    glue: tuple[Mapping[str, Any] | None, Mapping[str, Any] | None] = (None, None)
    parent: _Leaf | None = None
    texts: list[_Leaf] = field(default_factory=list)
    """Words laid on it (a block's label; a frame's title is ``title``)."""
    title: _Leaf | None = None
    held: list[_Leaf] = field(default_factory=list)
    """A frame's: what it holds directly."""
    node: str | None = None
    label: str | None = None
    """A line's: the words on it, if they were laid beside it."""

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0)

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)


def _plain(words: str) -> str:
    """Words as read, their markup taken away: ``**Encoder** $x$`` is ``Encoder x``."""

    return re.sub(r"\\[A-Za-z]+|[*_`${}]", "", str(words)).strip()


def _text_box(spec: Mapping[str, Any], word_size: float) -> Box:
    """Where a box of words is, by its words: as wide as its longest line (or its width), as
    tall as its lines, near enough."""

    size = float(spec.get("font_size") or word_size)
    pad = float(spec["padding"]) if spec.get("padding") is not None else 5.0
    lines = _plain(str(spec.get("text") or "")).split("\n") or [""]
    across = size * 0.55
    width = spec.get("width")
    if width:
        room = max(float(width) - 2 * pad, across)
        count = sum(max(1, math.ceil(len(line) * across / room)) for line in lines)
        w = float(width)
    else:
        count = len(lines)
        w = max(len(line) for line in lines) * across + 2 * pad
    x, y = (float(value) for value in spec["at"])
    return (x, y, x + max(w, size), y + count * size * 1.25 + 2 * pad)


def _leaves(shapes: Sequence[Mapping[str, Any]]) -> list[_Leaf]:
    """Every shape, a group's own shapes each in their place."""

    found: list[_Leaf] = []

    def take(spec: Mapping[str, Any], top: int) -> None:
        if spec.get("kind") == "group":
            for child in spec.get("shapes") or []:
                take(child, top)
            return
        drawn = freeform.normalised(spec)
        found.append(_Leaf(len(found), top, dict(spec), drawn, (0.0, 0.0, 0.0, 0.0)))

    for top, spec in enumerate(shapes):
        if isinstance(spec, Mapping):
            take(spec, top)
    return found


def _read(leaves: list[_Leaf], parts: Mapping[str, Sequence[float]], word_size: float) -> None:
    """Each leaf's box, outline and role; a line's ends where they are glued."""

    named = {str(leaf.spec["id"]): leaf for leaf in leaves if leaf.spec.get("id") is not None}
    sized: dict[int, Box] = {}
    for leaf in leaves:
        kind = leaf.drawn["kind"]
        form = freeform.family(kind)
        leaf.words = str(leaf.drawn.get("text") or "").strip()
        if form == "text":
            leaf.box = sized[leaf.at] = _text_box(leaf.drawn, word_size)
            visible = leaf.drawn.get("fill") not in (None, "none") or (
                leaf.drawn.get("line") not in (None, "none") and leaf.drawn.get("line_width")
            )
            leaf.role = "block" if visible and leaf.words else "text" if leaf.words else "mark"
            continue
        if form == "box" or (form == "points" and leaf.drawn.get("closed")):
            made = freeform.geometry(leaf.drawn)
            leaf.box = freeform.bounds(leaf.drawn, made)
            leaf.outline = freeform.target_of(leaf.drawn, made).outline
            if kind in NOT_PARTS or _faint(leaf.drawn):
                leaf.role = "mark"
            elif _invisible(leaf.drawn):
                # (Words in a box that draws nothing: words alone.)
                leaf.role = "text" if leaf.words else "mark"
            else:
                leaf.role = "block"
            continue
        leaf.role = "line" if kind not in MEASURES else "mark"

    def find(end: Mapping[str, Any]) -> freeform.Target | None:
        if end.get("shape") is not None and str(end["shape"]) in named:
            other = named[str(end["shape"])]
            x0, y0, x1, y1 = other.box
            return freeform.Target((x0, y0, x1 - x0, y1 - y0), 0.0, other.outline)
        if end.get("part") is not None and str(end["part"]) in parts:
            x, y, w, h = (float(value) for value in parts[str(end["part"])])
            return freeform.Target((x, y, w, h))
        return None

    for leaf in leaves:
        form = freeform.family(leaf.drawn["kind"])
        if form not in ("line", "points") or (form == "points" and leaf.drawn.get("closed")):
            continue
        if form == "line":
            ends = freeform.glued(leaf.drawn, find)
            made = freeform.geometry(leaf.drawn, ends=ends)
            leaf.ends = ends
            leaf.glue = tuple(  # type: ignore[assignment]
                end if isinstance(end, Mapping) else None
                for end in (leaf.spec.get("from"), leaf.spec.get("to"))
            )
        else:
            made = freeform.geometry(leaf.drawn)
            points = [(float(x), float(y)) for x, y in leaf.drawn["points"]]
            leaf.ends = (points[0], points[-1])
        leaf.path = freeform.flattened(made.segments)
        leaf.box = freeform.bounds(leaf.drawn, made)


def _faint(spec: Mapping[str, Any]) -> bool:
    """A box drawn see-through and unoutlined: a highlight in all but name."""

    filled = spec.get("fill") not in (None, "none")
    outlined = spec.get("line") not in (None, "none") and float(spec.get("line_width") or 0) > 0
    see_through = float(spec.get("fill_opacity", 1.0)) * float(spec.get("opacity", 1.0)) < 0.6
    return filled and see_through and not outlined


def _invisible(spec: Mapping[str, Any]) -> bool:
    filled = spec.get("fill") not in (None, "none") and float(spec.get("fill_opacity", 1.0)) > 0
    outlined = spec.get("line") not in (None, "none") and float(spec.get("line_width") or 0) > 0
    return not filled and not outlined


def _inside(inner: Box, outer: Box, slack: float = 2.0) -> bool:
    return (
        inner[0] >= outer[0] - slack
        and inner[1] >= outer[1] - slack
        and inner[2] <= outer[2] + slack
        and inner[3] <= outer[3] + slack
    )


def _holds(box: Box, point: tuple[float, float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _distance(box: Box, point: tuple[float, float]) -> float:
    """How far ``point`` is from ``box`` (none, inside it)."""

    dx = max(box[0] - point[0], 0.0, point[0] - box[2])
    dy = max(box[1] - point[1], 0.0, point[1] - box[3])
    return math.hypot(dx, dy)


def _to_path(path: Sequence[tuple[float, float]], point: tuple[float, float]) -> float:
    """How far ``point`` is from a line through ``path``."""

    best = math.inf
    for (ax, ay), (bx, by) in itertools.pairwise(path):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = (
            0.0
            if length == 0
            else max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length))
        )
        best = min(best, math.hypot(point[0] - ax - t * dx, point[1] - ay - t * dy))
    return best if path[1:] else math.dist(path[0], point) if path else math.inf


# -- what holds what, and whose words are whose ----------------------------------------------


FRAMES = frozenset({"rectangle", "rounded-rectangle"})
"""The shapes that, drawn round others, group them: a box round boxes. (An oval round some
is a ring drawn round them.)"""


def _nest(leaves: list[_Leaf]) -> None:
    """Each block's frame (the smallest box round it); boxes round others are frames, and
    other shapes round them rings (marks)."""

    blocks = [leaf for leaf in leaves if leaf.role == "block"]
    for leaf in blocks:
        round_ = [
            other
            for other in blocks
            if other is not leaf and other.area > leaf.area * 1.2 and _inside(leaf.box, other.box)
        ]
        leaf.parent = min(round_, key=lambda other: other.area) if round_ else None
    for leaf in blocks:
        if leaf.parent is not None:
            leaf.parent.role = "frame" if leaf.parent.drawn["kind"] in FRAMES else "mark"
    for leaf in blocks:
        while leaf.parent is not None and leaf.parent.role == "mark":
            leaf.parent = leaf.parent.parent


def _words(leaves: list[_Leaf], word_size: float) -> None:
    """Words laid on a block are its words; words in a frame's top band, or just over it, its
    title; the rest are words alone, in the frame they are in."""

    frames = [leaf for leaf in leaves if leaf.role == "frame"]
    blocks = [leaf for leaf in leaves if leaf.role in ("block", "frame")]
    texts = sorted(
        (leaf for leaf in leaves if leaf.role == "text"),
        key=lambda leaf: (leaf.box[1], leaf.box[0]),
    )
    for text in texts:
        round_ = [block for block in blocks if _holds(block.box, text.centre)]
        holder = min(round_, key=lambda block: block.area) if round_ else None
        if holder is not None and holder.role == "block":
            holder.texts.append(text)
            text.role = "words"
            continue
        if holder is not None:
            # A frame's: its title if over all it holds (and it has none of its own), else
            # words alone in it.
            inner = [leaf for leaf in blocks if leaf.parent is holder]
            if (
                not holder.words
                and holder.title is None
                and inner
                and text.box[3] <= min(leaf.box[1] for leaf in inner) + 2.0
            ):
                holder.title = text
                text.role = "title"
                continue
            text.parent = holder
    # Words just over a frame (and over no other part), across it from its left: its title.
    for text in texts:
        if text.role != "text" or text.parent is not None:
            continue
        line = max(text.height, word_size)
        below = [
            frame
            for frame in frames
            if frame.title is None
            and not frame.words
            and -2.0 <= frame.box[1] - text.box[3] <= line * 1.2
            and frame.box[0] - line <= text.centre[0] <= frame.box[2]
            and text.box[0] < frame.box[2]
        ]
        if below:
            frame = min(below, key=lambda frame: frame.box[1] - text.box[3])
            frame.title = text
            text.role = "title"
            text.parent = frame.parent
    for frame in frames:
        frame.held = [leaf for leaf in blocks if leaf.parent is frame]


# -- lines ------------------------------------------------------------------------------------


def _tolerance(leaf: _Leaf, word_size: float) -> float:
    """How near a line's end must come to a part to be taken as ending at it."""

    return max(word_size * 0.8, min(0.25 * min(leaf.width, leaf.height), word_size * 2.4))


def _at(
    point: tuple[float, float],
    glue: Mapping[str, Any] | None,
    named: Mapping[str, _Leaf],
    parts: Mapping[str, Box],
    nodes: frozenset[str],
    candidates: list[_Leaf],
    word_size: float,
) -> _Leaf | str | None:
    """What a line's end is at: a leaf (a block, words, a frame), an existing part by id (one
    of ``nodes``), or nothing."""

    if glue is not None:
        if glue.get("shape") is not None and str(glue["shape"]) in named:
            found = named[str(glue["shape"])]
            return found if found.role in ("block", "frame", "text") else None
        if glue.get("part") is not None:
            part = str(glue["part"])
            return part if part in nodes else None
    best: tuple[float, float, Any] | None = None
    for leaf in candidates:
        gap = _distance(leaf.box, point)
        if leaf.role == "frame":
            # A frame is met at its edge: an end deep inside it is at what it holds.
            x0, y0, x1, y1 = leaf.box
            edge = min(
                abs(point[0] - x0), abs(point[0] - x1), abs(point[1] - y0), abs(point[1] - y1)
            )
            gap = gap if gap > 0 else edge
            if gap > _tolerance(leaf, word_size):
                continue
            rank = (gap + word_size * 0.5, leaf.area)
        elif leaf.role == "text":
            if gap > word_size:
                continue
            rank = (gap + word_size * 0.6, leaf.area)
        else:
            if gap > _tolerance(leaf, word_size):
                continue
            rank = (gap, leaf.area)
        if best is None or rank < best[:2]:
            best = (*rank, leaf)
    for part, box in parts.items():
        if part not in nodes:
            continue
        gap = _distance(box, point)
        x0, y0, x1, y1 = box
        tolerance = max(word_size * 0.8, min(0.25 * min(x1 - x0, y1 - y0), word_size * 2.4))
        if gap <= tolerance and (best is None or (gap, (x1 - x0) * (y1 - y0)) < best[:2]):
            best = (gap, (x1 - x0) * (y1 - y0), part)
    return best[2] if best else None


def _deepest(frame: _Leaf, point: tuple[float, float]) -> _Leaf | None:
    """The part in ``frame`` (in a frame in it, ...) nearest ``point``."""

    inner: list[_Leaf] = []
    stack = list(frame.held)
    while stack:
        leaf = stack.pop()
        if leaf.role == "frame":
            stack.extend(leaf.held)
        elif leaf.role == "block":
            inner.append(leaf)
    return min(inner, key=lambda leaf: _distance(leaf.box, point)) if inner else None


def _ways(spec: Mapping[str, Any]) -> tuple[str, str]:
    """A line's heads at its start and its end, as drawn."""

    return str(spec.get("start") or "none"), str(spec.get("end") or "none")


# -- colours ---------------------------------------------------------------------------------


def _lab(colour: str) -> tuple[float, float, float]:
    """``#rrggbb`` in CIELAB (D65)."""

    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(digit * 2 for digit in text)
    channels = [int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    r, g, b = linear
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _hue(lab: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(lab[2], lab[1])) % 360.0


def _chroma(lab: tuple[float, float, float]) -> float:
    return math.hypot(lab[1], lab[2])


def _turn(one: float, other: float) -> float:
    """How far apart two hues are round the wheel, in degrees."""

    return abs((one - other + 180.0) % 360.0 - 180.0)


class _Colours:
    """A drawing's colours as the figure's tones: each fill the tone nearest it in hue, two
    fills drawn apart kept apart (the second the next tone near it), and a fill near none of
    them its own colour."""

    def __init__(self, palette: Any) -> None:
        self.palette = palette
        self.tones: dict[int, list[float]] = {}
        if palette is not None:
            from flexo.themes import TONE_COUNT

            seen: set[str] = set()
            for index in range(1, TONE_COUNT + 1):
                stroke = palette.paints.get(f"tone-{index}-stroke")
                if not stroke or stroke.lower() in seen or not stroke.startswith("#"):
                    continue
                seen.add(stroke.lower())
                for role in ("stroke", "fill"):
                    colour = palette.paints.get(f"tone-{index}-{role}", "")
                    lab = _lab(colour) if colour.startswith("#") else (0.0, 0.0, 0.0)
                    if _chroma(lab) > GREY:
                        self.tones.setdefault(index, []).append(_hue(lab))
        self.chosen: dict[str, str | None] = {}

    def hex_of(self, value: object) -> tuple[str | None, int | None]:
        """A shape's colour as written: its hex, or the tone it names (``accent2-fill``)."""

        if value is None or value == "none":
            return None, None
        text = str(value)
        found = re.fullmatch(r"accent(\d*)(-fill)?", text)
        if found:
            return None, int(found.group(1) or 1)
        role = freeform.role_of(text)
        found = re.fullmatch(r"tone-(\d+)-(fill|stroke|motif|ink)", role)
        if found:
            return None, int(found.group(1))
        if text.startswith("#"):
            return text, None
        colour = self.palette.get(role, "") if self.palette is not None else ""
        return (colour or None), None

    def plan(self, colours: Iterable[str]) -> None:
        """The tone of each drawn colour, the commonest choosing first."""

        counts = Counter(colour.lower() for colour in colours)
        taken: dict[int, float] = {}
        for colour, _ in counts.most_common():
            lab = _lab(colour)
            if _chroma(lab) <= GREY:
                self.chosen[colour] = None
                continue
            hue = _hue(lab)
            near = sorted(
                (min(_turn(hue, each) for each in hues), index)
                for index, hues in self.tones.items()
            )
            pick = None
            for gap, index in near:
                if gap > HUE_NEAR:
                    break
                if index not in taken or _turn(taken[index], hue) < SAME_HUE:
                    pick = index
                    break
            if pick is None:
                self.chosen[colour] = colour
                continue
            taken.setdefault(pick, hue)
            self.chosen[colour] = str(pick)

    def tone(self, value: object) -> tuple[str | None, str | None]:
        """The tone a colour is (``"2"``), or its own (``#rrggbb``); none for a grey."""

        colour, named = self.hex_of(value)
        if named is not None:
            return str(named), None
        if colour is None:
            return None, None
        chosen = self.chosen.get(colour.lower())
        if chosen is None:
            return None, None
        if chosen.startswith("#"):
            return None, chosen
        return chosen, None


# -- the arrangement ---------------------------------------------------------------------------


@dataclass(eq=False)
class _Placed:
    """A part, or an arrangement of them, where it was drawn."""

    box: Box
    leaf: _Leaf | None = None
    kind: str = ""
    children: list[_Placed] = field(default_factory=list)
    columns: int = 0
    cells: list[tuple[int, int]] = field(default_factory=list)
    align: str = ""
    equal: bool = False

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0)


def _union(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bands(items: list[_Placed], axis: int) -> list[list[_Placed]]:
    """``items`` cut where nothing spans the gap between them along ``axis`` (0: across)."""

    order = sorted(items, key=lambda item: item.box[axis])
    bands: list[list[_Placed]] = []
    reach = -math.inf
    for item in order:
        start, end = item.box[axis], item.box[axis + 2]
        # (Sloppy drawing: a little overlap is no span.)
        slack = min(2.0, (end - start) * 0.1)
        if bands and start < reach - slack:
            bands[-1].append(item)
            reach = max(reach, end)
        else:
            bands.append([item])
            reach = end
    return bands


def _gap_score(bands: list[list[_Placed]], axis: int) -> float:
    """How plainly ``bands`` stand apart: the narrowest gap between them, in their parts'
    usual size along ``axis``."""

    if len(bands) < 2:
        return -1.0
    sizes = sorted(item.box[axis + 2] - item.box[axis] for band in bands for item in band)
    usual = max(sizes[len(sizes) // 2], 1.0)
    gaps = [
        min(item.box[axis] for item in later) - max(item.box[axis + 2] for item in earlier)
        for earlier, later in itertools.pairwise(bands)
    ]
    return min(gaps) / usual


def _clusters(items: list[_Placed], axis: int) -> list[list[_Placed]]:
    """``items`` in lines across ``axis``: those whose middles are near one another's."""

    order = sorted(items, key=lambda item: item.centre[axis])
    lines: list[list[_Placed]] = []
    for item in order:
        size = item.box[axis + 2] - item.box[axis]
        if lines:
            line = lines[-1]
            middle = sum(other.centre[axis] for other in line) / len(line)
            least = min(size, *(other.box[axis + 2] - other.box[axis] for other in line))
            if abs(item.centre[axis] - middle) < least * 0.5:
                line.append(item)
                continue
        lines.append([item])
    return lines


def _grid(items: list[_Placed]) -> _Placed | None:
    """``items`` as a grid, where they stand in rows and columns both."""

    if len(items) < 4:
        return None
    rows, columns = _clusters(items, 1), _clusters(items, 0)
    if len(rows) < 2 or len(columns) < 2:
        return None
    where = {}
    for r, row in enumerate(rows):
        for item in row:
            where[id(item)] = [r, 0]
    for c, column in enumerate(columns):
        for item in column:
            where[id(item)][1] = c
    cells = [tuple(where[id(item)]) for item in items]
    if len(set(cells)) != len(cells) or len(items) < 0.75 * len(rows) * len(columns):
        return None
    # The rows must stand apart, as must the columns: a grid's lines don't interleave.
    if len(_bands(items, 1)) != len(rows) or len(_bands(items, 0)) != len(columns):
        return None
    order = sorted(items, key=lambda item: tuple(where[id(item)]))
    made = _Placed(_union(item.box for item in items), kind="grid", children=order)
    made.columns = len(columns)
    made.cells = [tuple(where[id(item)]) for item in order]  # type: ignore[misc]
    return made


def _arrange(items: list[_Placed]) -> _Placed:
    """``items`` laid out as drawn: a grid, a row, a column, or rows and columns of them."""

    if len(items) == 1:
        return items[0]
    found = _grid(items)
    if found is not None:
        return _finished(found)
    down, across = _bands(items, 1), _bands(items, 0)
    if len(down) > 1 or len(across) > 1:
        if _gap_score(down, 1) >= _gap_score(across, 0):
            made = _Placed(_union(item.box for item in items), kind="column")
            made.children = [_arrange(band) for band in down]
        else:
            made = _Placed(_union(item.box for item in items), kind="row")
            made.children = [_arrange(band) for band in across]
        return _finished(made)
    # Overlapping every way: read top to bottom.
    made = _Placed(_union(item.box for item in items), kind="column")
    made.children = sorted(items, key=lambda item: (item.box[1], item.box[0]))
    return _finished(made)


def _finished(made: _Placed) -> _Placed:
    """How the parts of an arrangement align, and whether they are drawn one size."""

    children = made.children
    if made.kind in ("row", "column"):
        axis = 1 if made.kind == "row" else 0
        sizes = [child.box[axis + 2] - child.box[axis] for child in children]
        least = max(min(sizes), 1.0)
        starts = [child.box[axis] for child in children]
        ends = [child.box[axis + 2] for child in children]
        middles = [child.centre[axis] for child in children]
        tight = least * 0.08
        if max(sizes) - least > least * 0.2 and max(middles) - min(middles) > tight:
            if max(starts) - min(starts) <= tight:
                made.align = "start"
            elif max(ends) - min(ends) <= tight:
                made.align = "end"
    leaves = [child.leaf for child in children if child.leaf is not None and not child.children]
    if len(leaves) == len(children) >= 2 and all(leaf.role == "block" for leaf in leaves):
        widths = [leaf.width for leaf in leaves]
        heights = [leaf.height for leaf in leaves]
        alike = (
            max(widths) - min(widths) <= min(widths) * 0.06
            and max(heights) - min(heights) <= min(heights) * 0.06
        )
        if alike:
            made.equal = True
    return made


def _words_of(leaf: _Leaf) -> str:
    """A block's words: its own, then those laid on it, top to bottom."""

    laid = sorted(leaf.texts, key=lambda text: (round(text.box[1]), text.box[0]))
    return "\n".join([word for word in [leaf.words, *(text.words for text in laid)] if word])


# -- ids ----------------------------------------------------------------------------------------

_SMALL = frozenset(
    {"a", "an", "and", "the", "of", "on", "in", "at", "to", "for", "with", "or", "by"}
)


def slug(words: str) -> str:
    """An id made from words (a label, a kind), as the figure editor makes one:
    ``Encoder block`` is ``encoder-block``."""

    words = re.sub(r"\$|\\[A-Za-z]+|[*_`{}]", "", str(words))
    pieces = [piece for piece in re.split(r"[^A-Za-z0-9]+", words.lower()) if piece]
    lead = next((at for at, piece in enumerate(pieces) if piece[0].isalpha()), None)
    if lead:
        pieces = pieces[lead:] + pieces[:lead]
    kept: list[str] = []
    for piece in pieces:
        if len("-".join([*kept, piece])) > 24:
            while len(kept) > 1 and kept[-1] in _SMALL:
                kept.pop()
            break
        kept.append(piece)
    made = "-".join(kept) or (pieces[0][:24] if pieces else "")
    if not made or not made[0].isalpha():
        made = f"part-{made}" if made else "part"
    return made


class _Names:
    def __init__(self, taken: Iterable[str]) -> None:
        self.taken = set(taken)

    def __call__(self, base: str) -> str:
        stem = slug(base)
        made, number = stem, 2
        while made in self.taken:
            made, number = f"{stem}-{number}", number + 1
        self.taken.add(made)
        return made


# -- reading it all -------------------------------------------------------------------------------


def recognise(
    shapes: Sequence[Mapping[str, Any]],
    *,
    palette: Any = None,
    taken: Iterable[str] = (),
    parts: Mapping[str, Sequence[float]] | None = None,
    nodes: Iterable[str] = (),
    holder: str = "diagram",
    word_size: float = 10.0,
    scale: float | None = None,
    style: str = "paper",
) -> Recognised:
    """The parts a diagram drawn as ``shapes`` draws (``flexo.freeform`` shapes, placed where
    they are drawn: no ``on`` or ``around`` of their own), and what of it stays a shape.

    ``palette``: the figure's (a flexo ``Palette``), whose tones the fills are matched to;
    ``taken``: ids the figure has already (none is given again); ``parts``: where the figure's
    own parts are (``[x, y, width, height]`` by id), and ``nodes``, which of them are shapes a
    line may join -- for lines glued to them (``{part: id}``), or drawn to them; ``holder``:
    the id of the group the diagram will be put in, which a shape kept near none of its parts
    goes ``on``; ``word_size``: how large the words are drawn, in the shapes' units, where they
    say none of their own (lines end near a part within about that, and words stand by a line
    within it); ``scale``: the
    figure's units in the shapes' -- a shape kept is put on the parts that size, the parts being
    drawn as the theme (``style``) draws them, not as drawn: by default, the theme's block of
    one line over the boxes of one line drawn (``drawn_scale``)."""

    parts = {str(key): tuple(float(value) for value in box) for key, box in (parts or {}).items()}
    part_boxes = {key: (x, y, x + w, y + h) for key, (x, y, w, h) in parts.items()}
    nodes = frozenset(nodes)
    leaves = _leaves(shapes)
    # (Words drawn a size of their own say how large the drawing is drawn.)
    sizes = sorted(float(leaf.drawn["font_size"]) for leaf in leaves if leaf.drawn.get("font_size"))
    word_size = sizes[len(sizes) // 2] if sizes else word_size
    _read(leaves, parts, word_size)
    _nest(leaves)
    _words(leaves, word_size)
    named = {str(leaf.spec["id"]): leaf for leaf in leaves if leaf.spec.get("id") is not None}
    made = Recognised()
    if scale is None:
        scale = drawn_scale(leaves, block_height(style))

    # Lines: between two parts, a line of the figure's; else a shape.
    candidates = [leaf for leaf in leaves if leaf.role in ("block", "frame", "text")]
    joined: list[tuple[_Leaf, Any, Any]] = []
    for leaf in leaves:
        if leaf.role != "line" or leaf.ends is None:
            continue
        if leaf.drawn["kind"] == "pen" and _ways(leaf.drawn) == ("none", "none"):
            continue  # a free curve: drawn, not a line between parts
        ends = [
            _at(point, glue, named, part_boxes, nodes, candidates, word_size)
            for point, glue in zip(leaf.ends, leaf.glue, strict=True)
        ]
        for index, end in enumerate(ends):
            if isinstance(end, _Leaf) and end.role == "frame":
                ends[index] = _deepest(end, leaf.ends[index])
        if ends[0] is None or ends[1] is None or ends[0] is ends[1] or ends[0] == ends[1]:
            continue
        joined.append((leaf, ends[0], ends[1]))
    ended = {id(end) for _, *both in joined for end in both if isinstance(end, _Leaf)}
    # An empty box no line ends at is a mark (a backdrop), not a part.
    for leaf in leaves:
        if leaf.role == "block" and not _words_of(leaf) and id(leaf) not in ended:
            leaf.role = "mark"
    _label(leaves, joined, ended, word_size)

    # What each frame holds; a frame left holding nothing is a box (with its words), or a mark.
    for leaf in leaves:
        if leaf.role == "text" and leaf.parent is not None and leaf.parent.role == "frame":
            leaf.parent.held.append(leaf)
    for frame in sorted((leaf for leaf in leaves if leaf.role == "frame"), key=lambda f: f.area):
        frame.held = [leaf for leaf in frame.held if leaf.role in ("block", "frame", "text")]
        if frame.held:
            continue
        if frame.title is not None:
            frame.texts.append(frame.title)
            frame.title.role = "words"
            frame.title = None
        frame.role = "block" if _words_of(frame) or id(frame) in ended else "mark"
    outer = [
        leaf
        for leaf in leaves
        if leaf.role in ("block", "frame", "text")
        and (leaf.parent is None or leaf.parent.role != "frame")
    ]
    if not outer:
        raise ValueError(
            "Nothing chosen reads as a diagram: draw boxes with words in them, words alone, "
            "and lines between them."
        )

    # (A shape that stays one keeps its name: no part is given it.)
    staying = {
        str(leaf.spec["id"])
        for leaf in leaves
        if leaf.spec.get("id") is not None
        and (
            leaf.role == "mark"
            or (leaf.role == "line" and not any(leaf is one for one, *_ in joined))
        )
    }
    names = _Names({*taken, *staying})
    colours = _Colours(palette)
    colours.plan(
        colour
        for leaf in leaves
        if leaf.role == "block" and (colour := colours.hex_of(leaf.drawn.get("fill"))[0])
    )

    def placed(leaf: _Leaf) -> _Placed:
        if leaf.role != "frame":
            return _Placed(leaf.box, leaf)
        frame = _Placed(leaf.box, leaf)
        frame.children = [_arrange([placed(child) for child in leaf.held])]
        return frame

    top = _arrange([placed(leaf) for leaf in outer])

    def write(item: _Placed) -> str:
        """The id of the part or group ``item`` is, written (and what it holds)."""

        leaf = item.leaf
        if leaf is not None and leaf.role != "frame":
            node = _node(leaf, names, colours, made.notes)
            made.nodes.append(node)
            return node["id"]
        if leaf is not None:
            return _frame(item, leaf, names, made.groups, write)
        return _layout(item, names(item.kind), made.groups, write)

    if top.leaf is None:
        made.top = [write(child) for child in top.children]
        made.layout = _layout_of(top, made.top)
    else:
        made.top = [write(top)]
    drawn = [leaf for leaf in leaves if leaf.role in ("block", "frame", "text") and leaf.node]
    made.box = _union(leaf.box for leaf in drawn)
    boxes = {leaf.node: leaf.box for leaf in drawn}

    # The lines between them: the colour most of them are drawn in is the theme's.
    tones = []
    for leaf, _, _ in joined:
        colour, _ = colours.hex_of(leaf.drawn.get("line"))
        tones.append((colour or str(leaf.drawn.get("line"))).lower())
    usual = Counter(tones).most_common(1)[0][0] if tones else None
    lines = _Colours(palette)
    lines.plan(tone for tone in tones if tone.startswith("#") and tone != usual)
    for (leaf, start, end), tone in zip(joined, tones, strict=True):
        source = start.node if isinstance(start, _Leaf) else start
        target = end.node if isinstance(end, _Leaf) else end
        if source is None or target is None or source == target:
            continue
        made.edges.append(
            _edge(leaf, source, target, lines if tone != usual else None, {**part_boxes, **boxes})
        )
        leaf.node = LINE

    # The shapes made parts, and those kept, attached to them.
    for leaf in leaves:
        if leaf.spec.get("id") is not None and leaf.node is not None and leaf.node != LINE:
            made.parts[str(leaf.spec["id"])] = leaf.node
    within = {child: group["id"] for group in made.groups for child in group["children"]}
    anchor = made.top[0] if len(made.top) == 1 else holder
    anchors = {**boxes, anchor: made.box}
    kept: dict[int, list[_Leaf]] = {}
    for leaf in leaves:
        if leaf.node is None and leaf.role not in _CONSUMED:
            kept.setdefault(leaf.top, []).append(leaf)
    every: dict[int, int] = Counter(leaf.top for leaf in leaves)
    for index, spec in enumerate(shapes):
        if index not in kept:
            made.taken.append(index)
            continue
        if len(kept[index]) != every[index]:
            # A group some of whose shapes were made parts: the rest, kept together.
            rest = [leaf.spec for leaf in kept[index]]
            spec = (
                rest[0]
                if len(rest) == 1
                else {
                    "kind": "group",
                    **({"id": spec["id"]} if spec.get("id") else {}),
                    "shapes": rest,
                }
            )
            made.taken.append(index)
        made.kept.append(index)
        made.shapes.append(
            _attached(spec, made.parts, boxes, anchors, anchor, word_size, scale, within)
        )
    made.taken = [index for index in made.taken if index not in made.kept]
    return made


LINE = "\0line"
"""What a line made a line of the figure's is (it is no part: it has no id of its own)."""


def _label(
    leaves: list[_Leaf], joined: list[tuple[_Leaf, Any, Any]], ended: set[int], word_size: float
) -> None:
    """Words beside a line, at no part, are its words: each line's the nearest words to it."""

    loose = [leaf for leaf in leaves if leaf.role == "text" and id(leaf) not in ended]
    claims: list[tuple[float, _Leaf, _Leaf]] = []
    for text in loose:
        x0, y0, x1, y1 = text.box
        for leaf, _, _ in joined:
            if leaf.words:
                continue
            gap = min(
                _to_path(leaf.path, point)
                for point in (text.centre, (x0, y0), (x1, y0), (x0, y1), (x1, y1))
            )
            if gap <= max(text.height, word_size) * 1.1:
                claims.append((gap, text, leaf))
    for _, text, leaf in sorted(claims, key=lambda claim: claim[0]):
        if text.role == "text" and leaf.label is None:
            leaf.label = text.words
            text.role = "label"


_CONSUMED = frozenset({"words", "title", "label"})
"""What words become that are no part of their own: a part's, a frame's title, a line's."""


def _kind(leaf: _Leaf, words: str) -> tuple[str, dict[str, Any]]:
    """The kind of part a block drawn as ``leaf`` is, and what that kind takes besides."""

    kind = leaf.drawn["kind"]
    w, h = max(leaf.width, 1e-6), max(leaf.height, 1e-6)
    plain = _plain(words)
    if kind == "ellipse":
        if plain in SYMBOLS:
            return "op", {"symbol": SYMBOLS[plain]}
        if max(w, h) / min(w, h) <= 1.25:
            return "circle", {}
        return "terminal", {}
    if kind == "rounded-rectangle":
        corner = float(leaf.drawn.get("corner") or 0.0)
        return ("terminal" if corner >= 0.4 * min(w, h) else "block"), {}
    return KINDS.get(kind, "block"), {}


def _node(leaf: _Leaf, names: _Names, colours: _Colours, notes: list[str]) -> dict[str, Any]:
    """A part of the figure, as its file writes it, from the shape it was drawn as."""

    drawn = leaf.drawn
    words = _words_of(leaf) if leaf.role == "block" else leaf.words
    if leaf.role == "text":
        kind, extra = "text", {}
    else:
        kind, extra = _kind(leaf, words)
    own = str(leaf.spec.get("id") or "")
    stem = words if _plain(words) else own if own and not re.fullmatch(r"[a-z]+\d+", own) else kind
    if kind == "op":
        stem = "op"
    identifier = names(_plain(stem.split("\n")[0]) if _plain(stem) else stem)
    leaf.node = identifier
    node: dict[str, Any] = {"id": identifier}
    if kind != "block":
        node["kind"] = kind
    if words and kind != "op":
        node["label"] = words
    properties: dict[str, Any] = dict(extra)
    if leaf.role == "block":
        tone, own_colour = colours.tone(drawn.get("fill"))
        if tone is not None:
            properties["tone"] = int(tone)
        elif own_colour is not None:
            properties["paint-fill"] = own_colour
            notes.append(
                f"{_said(words, kind)} keeps its own colour, {own_colour}: no tone is near it."
            )
        if drawn.get("dash") in ("dashed", "dotted"):
            node["line"] = drawn["dash"]
        if drawn.get("shadow"):
            node["shadow"] = True
    if drawn.get("bold") or any(text.drawn.get("bold") for text in leaf.texts):
        properties["bold"] = True
    if drawn.get("italic") or any(text.drawn.get("italic") for text in leaf.texts):
        properties["italic"] = True
    if kind == "text" and "\n" in words and drawn.get("align") in ("start", "end"):
        properties["align"] = "left" if drawn["align"] == "start" else "right"
    if properties:
        node["properties"] = properties
    for text in leaf.texts:
        text.node = identifier
    return node


def _said(words: str, kind: str) -> str:
    plain = _plain(words).split("\n")[0]
    return f"“{plain}”" if plain else f"A {kind}"


def _frame(item: _Placed, leaf: _Leaf, names: _Names, groups: list[dict[str, Any]], write) -> str:
    """A group of the parts a frame was drawn round: a module, titled, or a frame."""

    title = leaf.words or (leaf.title.words if leaf.title is not None else "")
    identifier = names(_plain(title.split("\n")[0]) if _plain(title) else "group")
    leaf.node = identifier
    if leaf.title is not None:
        leaf.title.node = identifier
    group: dict[str, Any] = {"id": identifier}
    groups.append(group)
    inner = item.children[0] if item.children else None
    if inner is None:
        children, layout = [], {"kind": "row"}
    elif inner.leaf is not None:
        children = [write(inner)]
        layout = {"kind": "row"}
    else:
        children = [write(child) for child in inner.children]
        layout = _layout_of(inner, children)
    if title:
        group["label"] = title
    group["children"] = children
    group["layout"] = layout
    group["role"] = "module" if title else "container"
    if leaf.drawn.get("dash") in ("dashed", "dotted"):
        group["line"] = leaf.drawn["dash"]
    if leaf.drawn.get("shadow"):
        group["shadow"] = True
    return identifier


def _layout(item: _Placed, identifier: str, groups: list[dict[str, Any]], write) -> str:
    """A group that only arranges what it holds, as drawn: a row, a column, a grid."""

    group: dict[str, Any] = {"id": identifier}
    groups.append(group)
    children = [write(child) for child in item.children]
    group["children"] = children
    group["layout"] = _layout_of(item, children)
    group["role"] = "layout"
    return identifier


def _layout_of(item: _Placed, children: list[str]) -> dict[str, Any]:
    layout: dict[str, Any] = {"kind": item.kind}
    if item.kind == "grid":
        layout["columns"] = item.columns
        flowed = [(index // item.columns, index % item.columns) for index in range(len(children))]
        if flowed != item.cells:
            layout["placements"] = [
                {"child": child, "row": row, "column": column}
                for child, (row, column) in zip(children, item.cells, strict=True)
            ]
    if item.align:
        layout["align"] = item.align
    if item.equal:
        layout["equal_size"] = True
    return layout


def _edge(
    leaf: _Leaf,
    source: str,
    target: str,
    colours: _Colours | None,
    boxes: Mapping[str, Box],
) -> dict[str, Any]:
    """A line of the figure's, from the line drawn between two of its parts: the sides it was
    glued to kept where they are not the sides that face (a line round the side, back to a
    step before), as the figure would choose."""

    drawn = leaf.drawn
    start, end = _ways(drawn)
    if start != "none" and end == "none":
        source, target, start, end = target, source, end, start
        flipped = True
    else:
        flipped = False
    edge: dict[str, Any] = {"from": source, "to": target}
    words = leaf.words or leaf.label
    if words:
        edge["label"] = words
    if start == "none" and end == "none":
        edge["arrow"] = "none"
    elif start != "none":
        edge["arrow"] = "both"
    head = HEADS.get(end, "arrow") if end != "none" else "arrow"
    if head != "arrow":
        edge["head"] = head
    if start != "none" and HEADS.get(start, "arrow") != head:
        edge["tail"] = HEADS.get(start, "arrow")
    if drawn.get("dash") in ("dashed", "dotted"):
        edge["line"] = drawn["dash"]
    kind = drawn["kind"]
    if kind in ("curved-arrow", "arc", "pen"):
        edge["shape"] = "curved"
        if kind in ("curved-arrow", "arc") and drawn.get("bend") is not None:
            bend = max(-1.0, min(1.0, float(drawn["bend"]) * (-1 if flipped else 1)))
            edge["bend"] = round(bend, 2)
    for key, glue, here, there in (
        ("depart", leaf.glue[1 if flipped else 0], source, target),
        ("arrive", leaf.glue[0 if flipped else 1], target, source),
    ):
        side = glue.get("side") if isinstance(glue, Mapping) else None
        if side in _COMPASS and here in boxes and there in boxes:
            x0, y0, x1, y1 = boxes[here]
            facing = freeform.facing(
                freeform.Target((x0, y0, x1 - x0, y1 - y0)), _middle(boxes[there])
            )
            if side != facing:
                edge[key] = _COMPASS[side]
    if colours is not None:
        tone, own = colours.tone(drawn.get("line"))
        if tone is not None:
            edge["tone"] = int(tone)
        elif own is None and colours.hex_of(drawn.get("line"))[0]:
            # (A grey or black line among coloured ones: the theme's grey.)
            edge["tone"] = "neutral"
    return edge


_COMPASS = {"top": "north", "right": "east", "bottom": "south", "left": "west"}


# -- what stays a shape -------------------------------------------------------------------------

ROUNDING = frozenset(
    {"highlight", "ring", "ellipse", "rectangle", "rounded-rectangle", "cloud", "polygon"}
)
"""The closed shapes that go round what they were drawn round."""


def _attached(
    spec: Mapping[str, Any],
    parts: Mapping[str, str],
    boxes: Mapping[str, Box],
    anchors: Mapping[str, Box],
    anchor: str,
    word_size: float,
    scale: float,
    within: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """A shape kept, attached to the parts it was drawn at: round them, glued to them, on the
    nearest of them -- else on the diagram (``anchor``)."""

    made = copy.deepcopy(dict(spec))
    kind = str(made.get("kind"))
    if kind == "group":
        made["shapes"] = [
            _glued(dict(child), parts, boxes, word_size) for child in made.get("shapes") or []
        ]
        outer = freeform.bounds(made)
    else:
        made = _glued(made, parts, boxes, word_size)
        outer = freeform.bounds(made)
    within = within or {}
    # Round the parts it was drawn round (the group round some, not they as well).
    if freeform.family(kind) == "box" and kind in ROUNDING and not made.get("text"):
        round_ = [part for part, box in boxes.items() if _holds(outer, _middle(box))]
        round_ = [part for part in round_ if within.get(part) not in round_]
        if round_:
            for key in ("at", "size"):
                made.pop(key, None)
            return _ordered(made, around=round_)
    if kind in ("brace", "bracket"):
        beside = _beside(made, boxes, word_size)
        if beside:
            round_, side = beside
            for key in ("from", "to"):
                made.pop(key, None)
            return _ordered(made, around=round_, side=None if side == "right" else side)
    # On the part it is glued to, else the part nearest it -- or the diagram itself.
    glued = [
        str(end["part"])
        for end in (made.get("from"), made.get("to"))
        if isinstance(end, Mapping) and end.get("part") in anchors
    ]
    middle = ((outer[0] + outer[2]) / 2.0, (outer[1] + outer[3]) / 2.0)
    near = sorted((_distance(box, middle), part) for part, box in boxes.items())
    on = glued[0] if glued else near[0][1] if near and near[0][0] <= word_size * 4 else anchor
    box = anchors[on]
    made = freeform.moved(made, -box[0], -box[1])
    if scale != 1.0:
        made = _scaled(made, scale)
        made.pop("font_size", None)
    return _ordered(made, on=on)


def _ordered(made: Mapping[str, Any], **attached: Any) -> dict[str, Any]:
    """A shape kept as a person writes one: its kind, its id, what it is attached to, then
    the rest -- its places to a tenth."""

    first = {key: made[key] for key in ("kind", "id") if key in made}
    rest = {key: value for key, value in made.items() if key not in ("kind", "id", "on", "around")}
    tied = {key: value for key, value in attached.items() if value is not None}
    return {
        **first,
        **tied,
        **{key: _tenths(value) if key in PLACES else _whole(value) for key, value in rest.items()},
    }


PLACES = frozenset(
    {
        "at",
        "size",
        "from",
        "to",
        "points",
        "tail",
        "width",
        "depth",
        "corner",
        "line_width",
        "padding",
    }
)
"""What of a shape kept is a place or a size: written to a tenth."""


def _whole(value: Any) -> Any:
    """A number as a person writes it: ``2``, not ``2.0``."""

    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _tenths(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, 1)
        return int(rounded) if rounded == int(rounded) else rounded
    if isinstance(value, list):
        return [_tenths(item) for item in value]
    if isinstance(value, dict):
        return {key: _tenths(item) for key, item in value.items()}
    return value


def _middle(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _glued(
    spec: dict[str, Any], parts: Mapping[str, str], boxes: Mapping[str, Box], word_size: float
) -> dict[str, Any]:
    """A line's ends glued to the parts made of the shapes they were glued to, or glued to the
    part they end at -- each keeping where it was (``at``)."""

    kind = str(spec.get("kind"))
    if freeform.family(kind) != "line" or kind in MEASURES:
        return spec
    for key in ("from", "to"):
        end = spec.get(key)
        if isinstance(end, Mapping):
            shape = end.get("shape")
            if shape is not None and str(shape) in parts:
                part = parts[str(shape)]
                glue: dict[str, Any] = {"part": part}
                if end.get("side") is not None:
                    glue["side"] = end["side"]
                at = end.get("at") or (list(_middle(boxes[part])) if part in boxes else None)
                if at is not None:
                    glue["at"] = [float(at[0]), float(at[1])]
                spec[key] = glue
            continue
        point = (float(end[0]), float(end[1]))
        near = sorted((_distance(box, point), part) for part, box in boxes.items())
        if near and near[0][0] <= word_size * 0.8:
            x0, y0, x1, y1 = boxes[near[0][1]]
            side = freeform.facing(freeform.Target((x0, y0, x1 - x0, y1 - y0)), point)
            spec[key] = {"part": near[0][1], "side": side, "at": [point[0], point[1]]}
    return spec


def _beside(
    drawn: Mapping[str, Any], boxes: Mapping[str, Box], word_size: float
) -> tuple[list[str], str] | None:
    """The parts a brace (a bracket) was drawn along, and their side it is on."""

    (ax, ay), (bx, by) = (
        (float(drawn["from"][0]), float(drawn["from"][1])),
        (float(drawn["to"][0]), float(drawn["to"][1])),
    )
    upright = abs(by - ay) >= abs(bx - ax)
    if upright:
        low, high, at = min(ay, by), max(ay, by), (ax + bx) / 2.0
        found = [
            part
            for part, box in boxes.items()
            if _middle(box)[1] >= low - 1 and _middle(box)[1] <= high + 1
        ]
        left = [part for part in found if boxes[part][2] <= at + 2]
        right = [part for part in found if boxes[part][0] >= at - 2]
        side, round_ = ("right", left) if len(left) >= len(right) else ("left", right)
        if round_:
            reach = min(abs(at - (boxes[p][2] if side == "right" else boxes[p][0])) for p in round_)
            if reach <= word_size * 6:
                return sorted(round_, key=lambda p: boxes[p][1]), side
        return None
    low, high, at = min(ax, bx), max(ax, bx), (ay + by) / 2.0
    found = [part for part, box in boxes.items() if low - 1 <= _middle(box)[0] <= high + 1]
    above = [part for part in found if boxes[part][3] <= at + 2]
    below = [part for part in found if boxes[part][1] >= at - 2]
    side, round_ = ("bottom", above) if len(above) >= len(below) else ("top", below)
    if round_:
        reach = min(abs(at - (boxes[p][3] if side == "bottom" else boxes[p][1])) for p in round_)
        if reach <= word_size * 6:
            return sorted(round_, key=lambda p: boxes[p][0]), side
    return None


def _scaled(spec: dict[str, Any], scale: float) -> dict[str, Any]:
    """A shape's places (from what it is on), its sizes and its line ``scale`` as large."""

    made = dict(spec)

    def point(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {**value, **({"at": point(value["at"])} if value.get("at") is not None else {})}
        return [float(value[0]) * scale, float(value[1]) * scale]

    for key in ("at", "tail", "from", "to"):
        if made.get(key) is not None:
            made[key] = point(made[key])
    for key in ("size",):
        if made.get(key) is not None:
            made[key] = [float(value) * scale for value in made[key]]
    if made.get("points") is not None:
        made["points"] = [point(value) for value in made["points"]]
    for key in ("width", "corner", "depth", "line_width", "padding"):
        if isinstance(made.get(key), int | float) and not isinstance(made.get(key), bool):
            made[key] = float(made[key]) * scale
    if made.get("kind") == "group":
        made["shapes"] = [_scaled(child, scale) for child in made.get("shapes") or []]
    return made


@functools.cache
def block_height(style: str = "paper") -> float:
    """How tall the theme ``style`` draws a block of one line of words, in points."""

    from flexo.layout.measure import measure_figure
    from flexo.serialization import parse_figure
    from flexo.themes import figure_style

    try:
        spec = parse_figure(
            {"figure": {"id": "x", "style": style}, "nodes": [{"id": "n", "label": "Block"}]}
        )
        return float(measure_figure(spec, style=figure_style(spec)).nodes[0].intrinsic_size.height)
    except Exception:  # (a theme that does not read: a usual block's)
        return 22.0


def drawn_scale(leaves: Sequence[_Leaf], height: float) -> float:
    """How large the figure draws its parts, to how large they were drawn: a block of one line,
    ``height`` tall, over the boxes of one line drawn (the middle of them). One near enough is
    one."""

    drawn = sorted(
        leaf.height
        for leaf in leaves
        if leaf.role == "block"
        and leaf.drawn["kind"] in ("rectangle", "rounded-rectangle", "parallelogram", "text")
        and "\n" not in _words_of(leaf)
        and leaf.height > 0
    )
    if not drawn:
        return 1.0
    scale = max(0.2, min(4.0, height / drawn[len(drawn) // 2]))
    return 1.0 if abs(scale - 1.0) < 0.15 else round(scale, 2)


# -- a figure of its own ---------------------------------------------------------------------


def figure_document(
    shapes: Sequence[Mapping[str, Any]],
    *,
    id: str = "figure",
    style: str | None = None,
    palette: str | None = None,
    word_size: float = 10.0,
    scale: float | None = None,
) -> dict[str, Any]:
    """A figure file's document of the diagram drawn as ``shapes``: its parts laid out in its
    root as drawn, and what is no part of it drawn over them. ``style`` and ``palette`` are
    written into it when given (the tones are matched to theirs either way: paper's, else)."""

    from flexo.themes import resolve_palette, with_tone_roles

    paint = with_tone_roles(resolve_palette(style or "paper", palette or "default"))
    found = recognise(
        shapes,
        palette=paint,
        taken={"root"},
        holder="root",
        word_size=word_size,
        scale=scale,
        style=style or "paper",
    )
    return document_of(found, id=id, style=style, palette=palette)


def document_of(
    found: Recognised, *, id: str = "figure", style: str | None = None, palette: str | None = None
) -> dict[str, Any]:
    """A figure file's document of what ``recognise`` found, its root holding it all."""

    figure: dict[str, Any] = {"id": id}
    if style:
        figure["style"] = style
    if palette and palette != "default":
        figure["palette"] = palette
    document: dict[str, Any] = {"figure": figure, "nodes": found.nodes}
    if found.edges:
        document["edges"] = found.edges
    root = {
        "id": "root",
        "children": list(found.top),
        "layout": found.layout or {"kind": "row"},
        "role": "canvas",
    }
    only = found.groups[0] if found.groups else None
    if only is not None and found.top == [only["id"]] and only.get("role") == "layout":
        # The diagram is one arrangement: the root is it.
        root = {**only, "id": "root", "role": "canvas"}
        groups = [root, *found.groups[1:]]
        for shape in found.shapes:
            if shape.get("on") == only["id"]:
                shape["on"] = "root"
    else:
        groups = [root, *found.groups]
    document["groups"] = groups
    if found.shapes:
        document["shapes"] = found.shapes
    return document


def figure_of(shapes: Sequence[Mapping[str, Any]], **options: Any):
    """The figure (``FigureSpec``) a diagram drawn as ``shapes`` draws: ``figure_document``,
    read."""

    from flexo.serialization import parse_figure

    return parse_figure(figure_document(shapes, **options))


__all__ = ["Recognised", "document_of", "figure_document", "figure_of", "recognise", "slug"]
