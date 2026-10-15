"""Shapes drawn where they are put: lines, arrows, boxes, callouts, braces and measures.

A slide's drawing layer (flexo-talk) is made of these, and so is what is drawn over a figure
(``flexo.figure_shapes``): a ring round part of a structure, an arrow pointing at a residue, a
brace and its label beside a stack, a highlight behind a word, a dimension line saying
"3.1 Å". Each is
written as a mapping that says what it is and where -- ``{kind: arrow, from: [120, 300],
to: [260, 220]}`` -- and drawn here from that alone: its outline, its arrowheads, its
shadow, and where its words go. The studio's editor draws the same outlines as it is
dragged (``studio/static/studio/freeform.js``, kept to this file by a test), so what is seen
while drawing is what is saved.

Kinds by their family:

- **lines**, from one point to another (``from``, ``to``): ``line``, ``arrow``,
  ``double-arrow``, ``curved-arrow`` (bowed by ``bend``, its middle moved along by
  ``lean``, as a figure's curved line is), ``elbow`` (turning through right angles, the
  turn ``elbow`` of the way across, ``route: across`` or ``down`` first), ``arc`` (a
  circle's arc, bowed by ``bend``), and the measures: ``brace`` and ``bracket`` (along
  the span from ``from`` to ``to``, their tip ``depth`` off it, to the left of the way
  they run), ``dimension`` (ticked at its ends) and ``scale-bar`` (a thick bar), each
  with its words beside it;
- **lines through points** (``points``): ``polyline`` (straight between them) and ``pen``
  (smoothed through them, as drawn by hand); ``closed: true`` closes either;
- **closed shapes** in a box (``at``, its top left, and ``size``): ``rectangle``,
  ``rounded-rectangle`` (``corner``), ``ellipse``, ``triangle`` (``apex``),
  ``right-triangle``, ``diamond``, ``polygon`` (``sides``), ``star`` (``tips``, its
  inner ``ratio``), ``parallelogram`` (``slant``), ``trapezoid`` (``inset``), the block
  arrows ``arrow-right``, ``arrow-left``, ``arrow-up``, ``arrow-down`` and
  ``arrow-left-right`` (``shaft``, ``head``), ``chevron`` (``point``), ``plus`` and
  ``cross`` (``arm``), ``check``, ``cloud``, ``bubble`` (a speech bubble whose ``tail``
  points anywhere; its ``body`` rounded, a rectangle or an oval), and the highlights:
  ``highlight`` (a translucent box) and ``ring`` (an ellipse drawn round something);
- **text**: a box of words (``at``, and ``width`` to wrap them in);
- **inset**: a zoom inset, a box showing part ``of`` what its page holds (a slide's object, a
  figure's part) magnified, joined to it (``flexo.insets``): never turned nor mirrored.
- **path**: any outline, as SVG path data (``d``, ``flexo.pathdata``: every command, its
  pieces as many as it has -- holes too -- open or closed), filled by its ``fill_rule``
  (``nonzero`` or ``evenodd``); its box is what it draws, so it has no ``at`` or ``size``,
  turns and mirrors about that box's middle as a box does, and its words are set in it.

A box turns (``rotate``, degrees clockwise about its middle) and mirrors (``flip``). Every
shape is painted by the theme unless it says otherwise: ``fill`` and ``line`` are a theme's
colour by name (``accent``, ``accent2``, ``accent-fill`` its light tint, ``muted``,
``ink``, ``paper``, ``grey``, or any palette role) -- so a change of theme repaints them
-- or ``#rrggbb``, kept as written, or ``none``. ``line_width``, ``dash`` (``solid``,
``dashed``, ``dotted``), ``cap``, ``join``, the arrowheads at each end (``start``, ``end``:
``none``, ``triangle``, ``open``, ``stealth``, ``dot``, ``circle``, ``bar``,
``diamond``) and their ``head_size``, ``fill_opacity``, ``opacity`` and ``shadow`` say the
rest. Words (``text``, in the slide's markup) are set in the shape -- a closed shape's
inside its outline, a line's beside it -- by ``font_size``, ``bold``, ``italic``,
``colour``, ``font``, ``align``, ``valign`` and ``padding``.

An end of a line may be glued to a shape (``{shape: box1, side: right}``) or to what else
its writer can name (a slide's objects: ``{object: "body[0]"}``; a figure's parts:
``{part: encoder}``), at a side's middle
(``top``, ``right``, ``bottom``, ``left``), its ``centre`` (the line stopping at its
outline) or, left out, the side facing the line's other end; ``at`` keeps where it was, for
when what it was glued to is gone. ``glued`` finds where such an end is.

Everything here is in the units of the page the shapes are on, y down; nothing is laid out:
a shape is where it is written.
"""

from __future__ import annotations

import itertools
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from flexo import pathdata
from flexo.svg import element, number

# -- the vocabulary -----------------------------------------------------------------------

type Point = tuple[float, float]
type Segment = tuple  # ("M", x, y) | ("L", x, y) | ("C", x1, y1, x2, y2, x, y) | ("Z",)

LINES = (
    "line",
    "arrow",
    "double-arrow",
    "curved-arrow",
    "elbow",
    "arc",
    "brace",
    "bracket",
    "dimension",
    "scale-bar",
)
"""The kinds drawn from one point to another (``from``, ``to``)."""
TRACED = ("polyline", "pen")
"""The kinds drawn through points (``points``)."""
BOXED = (
    "rectangle",
    "rounded-rectangle",
    "ellipse",
    "triangle",
    "right-triangle",
    "diamond",
    "polygon",
    "star",
    "parallelogram",
    "trapezoid",
    "arrow-right",
    "arrow-left",
    "arrow-up",
    "arrow-down",
    "arrow-left-right",
    "chevron",
    "plus",
    "cross",
    "check",
    "cloud",
    "bubble",
    "highlight",
    "ring",
    "inset",
)
"""The closed shapes, each drawn in a box (``at``, ``size``): a zoom inset too, a box showing
part of something else magnified (``flexo.insets``)."""
KINDS = (*LINES, *TRACED, *BOXED, "text", "path")
"""Every kind of shape, but a group of them (``group``, its ``shapes``)."""

SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Lines",
        (
            "line",
            "arrow",
            "double-arrow",
            "curved-arrow",
            "elbow",
            "arc",
            "polyline",
            "pen",
            "path",
        ),
    ),
    (
        "Shapes",
        (
            "rectangle",
            "rounded-rectangle",
            "ellipse",
            "triangle",
            "right-triangle",
            "diamond",
            "parallelogram",
            "trapezoid",
            "polygon",
            "star",
            "plus",
            "cross",
            "check",
            "cloud",
        ),
    ),
    (
        "Arrows & Callouts",
        (
            "arrow-right",
            "arrow-left",
            "arrow-up",
            "arrow-down",
            "arrow-left-right",
            "chevron",
            "bubble",
        ),
    ),
    ("Brackets & Measures", ("brace", "bracket", "dimension", "scale-bar")),
    ("Highlights", ("highlight", "ring")),
    ("Text", ("text",)),
)
"""The kinds as an editor offers them, in groups, in this order."""

LABELS = {
    "line": "Line",
    "arrow": "Arrow",
    "double-arrow": "Double Arrow",
    "curved-arrow": "Curved Arrow",
    "elbow": "Elbow Connector",
    "arc": "Arc",
    "polyline": "Polyline",
    "pen": "Pencil",
    "rectangle": "Rectangle",
    "rounded-rectangle": "Rounded Rectangle",
    "ellipse": "Oval",
    "triangle": "Triangle",
    "right-triangle": "Right Triangle",
    "diamond": "Diamond",
    "polygon": "Polygon",
    "star": "Star",
    "parallelogram": "Parallelogram",
    "trapezoid": "Trapezoid",
    "arrow-right": "Right Arrow",
    "arrow-left": "Left Arrow",
    "arrow-up": "Up Arrow",
    "arrow-down": "Down Arrow",
    "arrow-left-right": "Left-Right Arrow",
    "chevron": "Chevron",
    "plus": "Plus",
    "cross": "Cross",
    "check": "Check Mark",
    "cloud": "Cloud",
    "bubble": "Speech Bubble",
    "brace": "Brace",
    "bracket": "Bracket",
    "dimension": "Dimension Line",
    "scale-bar": "Scale Bar",
    "highlight": "Highlight",
    "ring": "Highlight Ring",
    "text": "Text Box",
    "inset": "Zoom Inset",
    "path": "Path",
    "group": "Group",
}
"""What a person calls each kind (never a slide's own objects' names: Text Box, Speech Bubble)."""

TOOLS = {"path": "Pen"}
"""What the tool that draws a kind is called, where that is not the kind's own name: the pen
draws a path (point by point, as a Bézier pen does), the pencil (``pen``) by hand."""

HEADS = ("none", "triangle", "open", "stealth", "dot", "circle", "bar", "diamond")
"""The ends a line may have."""
DASHES = ("solid", "dashed", "dotted")
CAPS = ("butt", "round", "square")
JOINS = ("miter", "round", "bevel")
ALIGNS = ("start", "middle", "end")
VALIGNS = ("top", "middle", "bottom")
SIDES = ("top", "right", "bottom", "left", "centre")
FLIPS = ("horizontal", "vertical", "both")
BODIES = ("rounded", "rectangle", "oval")
ROUTES = ("across", "down")
FILL_RULES = ("nonzero", "evenodd")

_LINE = {"fill": "none", "line": "accent", "line_width": 2.0, "cap": "round", "join": "round"}
_CLOSED = {
    "fill": "accent-fill",
    "line": "accent",
    "line_width": 1.5,
    "cap": "butt",
    "join": "miter",
}
_SOLID = {"fill": "accent", "line": "none", "line_width": 1.5, "cap": "butt", "join": "miter"}
_MEASURE = {"fill": "none", "line": "ink", "line_width": 1.5, "cap": "butt", "join": "miter"}

STYLES: dict[str, dict[str, object]] = {
    "line": _LINE,
    "arrow": {**_LINE, "end": "triangle"},
    "double-arrow": {**_LINE, "start": "triangle", "end": "triangle"},
    "curved-arrow": {**_LINE, "end": "triangle"},
    "elbow": {**_LINE, "end": "triangle", "join": "miter"},
    "arc": _LINE,
    "polyline": _LINE,
    "pen": _LINE,
    **{kind: _CLOSED for kind in BOXED},
    "check": _SOLID,
    "cross": _SOLID,
    "highlight": {
        "fill": "accent",
        "fill_opacity": 0.25,
        "line": "none",
        "line_width": 1.5,
        "cap": "butt",
        "join": "miter",
    },
    "ring": {"fill": "none", "line": "accent", "line_width": 3.0, "cap": "butt", "join": "miter"},
    "brace": {**_MEASURE, "cap": "round", "join": "round"},
    "bracket": _MEASURE,
    "dimension": {**_MEASURE, "line_width": 1.25, "start": "bar", "end": "bar"},
    "scale-bar": {**_MEASURE, "line_width": 4.0},
    "text": {"fill": "none", "line": "none", "line_width": 1.5, "cap": "butt", "join": "miter"},
    "inset": {
        "fill": "paper",
        "line": "accent",
        "line_width": 1.5,
        "cap": "butt",
        "join": "miter",
        "align": "start",
        "valign": "top",
        "bold": True,
        "padding": 4.0,
    },
    "path": _CLOSED,
}
"""How each kind is painted when it says nothing: the theme's accent, its outlines a little
lighter than its lines; measures in ink; words on nothing."""

PARAMETERS: dict[str, dict[str, object]] = {
    "curved-arrow": {"bend": 0.25, "lean": 0.0},
    "arc": {"bend": 0.3},
    "elbow": {"elbow": 0.5, "route": "across"},
    "brace": {"depth": 16.0, "curl": 0.5, "tip": 0.5},
    "bracket": {"depth": 12.0, "curl": 0.0},
    "rectangle": {"corner": 0.0},
    "rounded-rectangle": {"corner": 12.0},
    "highlight": {"corner": 3.0},
    "triangle": {"apex": 0.5},
    "polygon": {"sides": 6},
    "star": {"tips": 5, "ratio": 0.38},
    "parallelogram": {"slant": 0.25},
    "trapezoid": {"inset": 0.25},
    **{
        kind: {"shaft": 0.5, "head": 0.5}
        for kind in ("arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-left-right")
    },
    "chevron": {"point": 0.5},
    "plus": {"arm": 0.25},
    "cross": {"arm": 0.2},
    "bubble": {"body": "rounded", "corner": 10.0},
    "polyline": {"closed": False},
    "pen": {"closed": False},
    "path": {"fill_rule": "nonzero"},
}
"""Each kind's own settings, as they are when it says nothing of them."""

SIZES: dict[str, tuple[float, float]] = {
    **{kind: (160.0, 100.0) for kind in BOXED},
    "ellipse": (120.0, 120.0),
    "ring": (140.0, 100.0),
    "polygon": (120.0, 120.0),
    "star": (120.0, 120.0),
    "diamond": (120.0, 120.0),
    "triangle": (120.0, 104.0),
    "right-triangle": (120.0, 104.0),
    "plus": (100.0, 100.0),
    "cross": (100.0, 100.0),
    "check": (100.0, 80.0),
    "chevron": (100.0, 80.0),
    "arrow-up": (80.0, 140.0),
    "arrow-down": (80.0, 140.0),
    "highlight": (200.0, 40.0),
    "cloud": (180.0, 120.0),
    "text": (240.0, 40.0),
    "inset": (200.0, 150.0),
    **{kind: (160.0, 0.0) for kind in LINES},
    "brace": (0.0, 160.0),
    "bracket": (0.0, 160.0),
    **{kind: (160.0, 0.0) for kind in TRACED},
}
"""How large a shape is made by a click, without a drag: a box's width and height, a line's
run across and down."""

STYLE_KEYS = (
    "fill",
    "fill_opacity",
    "line",
    "line_width",
    "dash",
    "cap",
    "join",
    "start",
    "end",
    "head_size",
    "shadow",
    "opacity",
)
TEXT_KEYS = ("text", "font_size", "bold", "italic", "colour", "font", "align", "valign", "padding")
PLACE_KEYS = {
    "line": ("from", "to"),
    "points": ("points",),
    "box": ("at", "size", "rotate", "flip"),
    "text": ("at", "width", "rotate"),
    "path": ("d", "rotate", "flip"),
}
COMMON_KEYS = ("kind", "id", *STYLE_KEYS, *TEXT_KEYS)
INSET_KEYS = (
    "of",
    "region",
    "frame_line",
    "frame_width",
    "frame_dash",
    "connector_line",
    "connector_width",
    "connector_dash",
)
"""What a zoom inset says besides its box (``flexo.insets``): what it shows part ``of``, the
``region`` of it shown, and how the frame round that region and the lines joining it to the
box are drawn (each as the box's outline, unless it says)."""


def family(kind: str) -> str:
    """``line``, ``points``, ``box``, ``text``, ``path`` or ``group``: how a kind is placed."""

    if kind == "path":
        return "path"
    if kind in LINES:
        return "line"
    if kind in TRACED:
        return "points"
    if kind == "text":
        return "text"
    if kind == "group":
        return "group"
    return "box"


def closed(spec: Mapping[str, Any]) -> bool:
    """Whether a shape is closed, its words set inside it. (A path is, open or not: it is
    filled as SVG fills one, and its words are set in its box.)"""

    kind = spec.get("kind")
    return kind in BOXED or kind == "path" or (kind in TRACED and bool(spec.get("closed")))


def keys_of(kind: str) -> tuple[str, ...]:
    """The keys a shape of ``kind`` takes."""

    if kind == "group":
        return ("kind", "id", "shapes", "opacity")
    if kind == "inset":
        return (*COMMON_KEYS, *PLACE_KEYS["box"], *INSET_KEYS)
    return (
        *COMMON_KEYS,
        *PLACE_KEYS[family(kind)],
        *PARAMETERS.get(kind, {}),
        *(("tail",) if kind == "bubble" else ()),
    )


def defaults(kind: str) -> dict[str, object]:
    """Everything a shape of ``kind`` is drawn with when it says nothing of it."""

    style = {
        "fill": "none",
        "fill_opacity": 1.0,
        "line": "accent",
        "line_width": 2.0,
        "dash": "solid",
        "cap": "butt",
        "join": "miter",
        "start": "none",
        "end": "none",
        "head_size": 1.0,
        "shadow": False,
        "opacity": 1.0,
        "rotate": 0.0,
        "flip": None,
        "text": "",
        "font_size": None,
        "bold": False,
        "italic": False,
        "colour": None,
        "font": None,
        "padding": 5.0,
    }
    closedish = kind in BOXED or kind == "text"
    words = {
        "align": "start" if kind == "text" else "middle",
        "valign": "top" if kind == "text" else "middle",
    }
    if not closedish:
        words = {"align": "middle", "valign": "middle"}
    return {**style, **words, **STYLES.get(kind, {}), **PARAMETERS.get(kind, {})}


def normalised(spec: Mapping[str, Any]) -> dict[str, Any]:
    """A shape as it is drawn: what it says, over what its kind is when it says nothing.
    (A group's shapes are each its own.)"""

    kind = str(spec.get("kind"))
    if kind == "group":
        return {
            "opacity": 1.0,
            **spec,
            "shapes": [normalised(child) for child in spec.get("shapes") or []],
        }
    made = {**defaults(kind), **{key: value for key, value in spec.items() if value is not None}}
    if kind == "bubble" and made.get("tail") is None and made.get("at") and made.get("size"):
        (x, y), (w, h) = made["at"], made["size"]
        made["tail"] = [x + w * 0.25, y + h + h * 0.45]
    return made


# -- checking what is written --------------------------------------------------------------


class ShapeError(ValueError):
    """A shape written wrong: ``key`` names the setting (``to``, ``fill``), so a document can
    say where (``slides[2].shapes[0].fill``)."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
        self.message = message


ALIASES = {"muted": "muted-ink", "paper": "canvas", "grey": "block-fill", "gray": "block-fill"}
"""Theme colours by the names a person gives them."""


def role_of(name: str) -> str:
    """The palette role a theme colour's name paints: ``accent`` (``accent2``...) a tone's
    colour, ``accent-fill`` (``accent2-fill``...) its light tint, ``muted`` the muted ink,
    ``paper`` the page, ``grey`` the neutral fill; a role is itself."""

    found = re.fullmatch(r"accent(\d*)(-fill)?", name)
    if found:
        return f"tone-{found.group(1) or 1}-{'fill' if found.group(2) else 'stroke'}"
    return ALIASES.get(name, name)


@cache
def _roles() -> frozenset[str]:
    from flexo.themes import resolve_palette, with_tone_roles

    palette = with_tone_roles(resolve_palette("paper", "default"))
    return frozenset({*palette.paints, *(alias for alias, _ in palette.aliases)})


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _said(value: object) -> str:
    return (
        f"{value:g}"
        if isinstance(value, int | float) and not isinstance(value, bool)
        else repr(value)
    )


def _number(value: object, key: str, low: float, high: float, example: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ShapeError(key, f"{key} must be a number, such as {example}, not {value!r}.")
    if not low <= value <= high:
        raise ShapeError(
            key, f"{key} must be between {_said(low)} and {_said(high)}, not {_said(value)}."
        )
    return float(value)


def _whole(value: object, key: str, low: int, high: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or value != int(value)
        or not low <= value <= high
    ):
        raise ShapeError(key, f"{key} must be a whole number from {low} to {high}, not {value!r}.")
    return int(value)


def _choice(value: object, key: str, allowed: Sequence[str]) -> str:
    value = (
        {"centre": "middle", "center": "middle", "left": "start", "right": "end"}.get(value, value)
        if key == "align"
        else {"center": "middle", "centre": "middle"}.get(value, value)
        if key == "valign"
        else value
    )
    if value not in allowed:
        raise ShapeError(key, f"{key} must be one of {', '.join(allowed)}, not {value!r}.")
    return str(value)


def _flag(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        raise ShapeError(key, f"{key} must be true or false, not {value!r}.")
    return value


LIMIT = 100_000.0
"""How far from the page's corner a point may be written: further is a mistake, not a place."""


def _point(value: object, key: str) -> list[float]:
    if (
        isinstance(value, str)
        or not isinstance(value, Sequence)
        or len(value) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item)
            for item in value
        )
    ):
        raise ShapeError(
            key,
            f"{key} must be a point, [x, y] in points from the page's top left, such as "
            f"[120, 80], not {value!r}.",
        )
    if any(abs(item) > LIMIT for item in value):
        raise ShapeError(
            key,
            f"{key} is {_said(max(abs(item) for item in value))} points from the page: "
            "a point must be on it, or near it.",
        )
    return [float(value[0]), float(value[1])]


GLUED_TO = ("shape", "object", "part")
"""What a line's end may name to be glued to: another shape, a slide's object, a figure's
part."""


def _end(value: object, key: str) -> list[float] | dict[str, object]:
    """A line's end: a point, or what it is glued to (``{shape: box1, side: right}``,
    ``{object: "body[0]"}``, ``{part: encoder}``), with where it was (``at``)."""

    if not isinstance(value, Mapping):
        return _point(value, key)
    said = (
        f"{key} must be a point ([x, y]) or what it is glued to, such as "
        f'{{shape: box1, side: right}}, {{object: "body[0]"}} or {{part: encoder}}'
    )
    unknown = [name for name in value if name not in (*GLUED_TO, "side", "at")]
    if unknown:
        raise ShapeError(key, f"{said}: it has {', '.join(map(str, unknown))}.")
    named = [name for name in GLUED_TO if value.get(name) is not None]
    if (
        len(named) != 1
        or not isinstance(value[named[0]], str | int)
        or isinstance(value[named[0]], bool)
        or not str(value[named[0]]).strip()
    ):
        raise ShapeError(key, f"{said}, not {dict(value)!r}.")
    end: dict[str, object] = {named[0]: str(value[named[0]])}
    if value.get("side") is not None:
        side = {"center": "centre", "middle": "centre"}.get(value["side"], value["side"])
        if side not in SIDES:
            raise ShapeError(
                key, f"{key}'s side must be one of {', '.join(SIDES)}, not {value['side']!r}."
            )
        end["side"] = side
    if value.get("at") is not None:
        end["at"] = _point(value["at"], f"{key}.at")
    return end


def colour_of(value: object, key: str) -> str:
    """A colour as written: ``none``, a theme colour's name or a palette role, or #rrggbb."""

    if value is None or value is False:
        return "none"
    if not isinstance(value, str) or not value.strip():
        raise ShapeError(
            key,
            f"{key} must be none, a theme colour (accent, accent2, accent-fill, muted, ink, "
            f"paper, grey) or a #rrggbb colour, not {value!r}.",
        )
    value = value.strip()
    if value.lower() in ("none", "transparent"):
        return "none"
    if value.startswith("#"):
        if not _HEX.fullmatch(value):
            raise ShapeError(
                key,
                f"{key} must be a colour written as #rgb or #rrggbb in hex digits, not {value!r}.",
            )
        return value
    if role_of(value) not in _roles():
        raise ShapeError(
            key,
            f"{key} must be none, a theme colour (accent, accent2, accent-fill, muted, ink, "
            f"paper, grey) or a #rrggbb colour, not {value!r}.",
        )
    return value


def checked(data: object, *, extra: Sequence[str] = (), depth: int = 0) -> dict[str, Any]:
    """A shape as written, checked: each setting what it can be, said in words under its
    own key (``ShapeError``) -- unknown keys too -- and kept as written (nothing added). A
    page's own keys a shape may also take (a slide's ``build``) are ``extra``, left to it."""

    if not isinstance(data, Mapping):
        raise ShapeError(
            "",
            "A shape must be a mapping, such as "
            f"{{kind: arrow, from: [100, 100], to: [200, 100]}}, not {data!r}.",
        )
    kind = data.get("kind")
    if kind not in (*KINDS, "group"):
        hint = "" if kind is None else f"Unknown kind of shape {kind!r}. "
        raise ShapeError(
            "kind", f"{hint}A shape's kind must be one of {', '.join(KINDS)}, or group."
        )
    allowed = (*keys_of(str(kind)), *extra)
    unknown = [str(key) for key in data if key not in allowed]
    if unknown:
        raise ShapeError(
            unknown[0],
            f"Unknown {'key' if len(unknown) == 1 else 'keys'} {', '.join(unknown)} for a "
            f"{kind}. Valid keys: {', '.join(allowed)}.",
        )
    made: dict[str, Any] = {"kind": kind}
    for key, value in data.items():
        if key == "kind" or key in extra:
            if key in extra:
                made[key] = value
            continue
        made[key] = _checked_value(str(kind), key, value, extra, depth)
    form = family(str(kind))
    needed = {
        "line": ("from", "to"),
        "points": ("points",),
        "box": ("at", "size"),
        "text": ("at",),
        "path": ("d",),
        "group": ("shapes",),
    }[form]
    if kind == "inset":
        needed = (*needed, "of")
    for key in needed:
        if key not in made:
            example = {
                "from": "[100, 100]",
                "to": "[260, 100]",
                "points": "[[100, 100], [180, 140], [260, 100]]",
                "at": "[100, 100]",
                "size": "[160, 100]",
                "shapes": "a list of shapes",
                "of": "body[0] (on a slide) or a part's id (on a figure)",
                "d": pathdata.EXAMPLE,
            }[key]
            raise ShapeError(key, f"A {kind} needs {key}, such as {key}: {example}.")
    return made


def _checked_value(kind: str, key: str, value: object, extra: Sequence[str], depth: int) -> object:
    if key == "id":
        if isinstance(value, bool) or not isinstance(value, str | int) or not str(value).strip():
            raise ShapeError(key, f"id must be a name, such as box1, not {value!r}.")
        return str(value)
    if key in ("fill", "line", "colour"):
        return None if key == "colour" and value is None else colour_of(value, key)
    if key in INSET_KEYS:
        return _inset_value(key, value)
    if key in ("fill_opacity", "opacity"):
        return _number(value, key, 0.0, 1.0, "0.5")
    if key == "line_width":
        return _number(value, key, 0.0, 200.0, "2 (points)")
    if key == "head_size":
        return _number(value, key, 0.25, 6.0, "1.5 (times the usual)")
    if key == "dash":
        return _choice(value, key, DASHES)
    if key == "cap":
        return _choice(value, key, CAPS)
    if key == "join":
        return _choice(value, key, JOINS)
    if key in ("start", "end"):
        if value is None or value is False:
            return "none"
        return _choice(value, key, HEADS)
    if key in ("shadow", "bold", "italic", "closed"):
        return _flag(value, key)
    if key == "text":
        if value is None:
            return ""
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ShapeError(key, f"text must be words, not {value!r}.")
        return str(value)
    if key == "font_size":
        return _number(value, key, 4.0, 400.0, "18 (points)")
    if key == "padding":
        return _number(value, key, 0.0, 500.0, "6 (points)")
    if key == "font":
        if not isinstance(value, str) or not value.strip():
            raise ShapeError(
                key, f"font must be a font family's name, such as IBM Plex Sans, not {value!r}."
            )
        return value.strip()
    if key == "align":
        return _choice(value, key, ALIGNS)
    if key == "valign":
        return _choice(value, key, VALIGNS)
    if key in ("from", "to"):
        return _end(value, key)
    if key in ("at", "tail"):
        return _point(value, key)
    if key == "size":
        if isinstance(value, str) or not isinstance(value, Sequence) or len(value) != 2:
            raise ShapeError(
                key, f"size must be [width, height] in points, such as [160, 100], not {value!r}."
            )
        return [
            _number(value[0], key, 0.0, LIMIT, "[160, 100]"),
            _number(value[1], key, 0.0, LIMIT, "[160, 100]"),
        ]
    if key == "width":
        return None if value is None else _number(value, key, 1.0, LIMIT, "240 (points)")
    if key == "rotate":
        turned = _number(value, key, -36000.0, 36000.0, "30 (degrees, clockwise)")
        return turned % 360.0 if abs(turned) >= 360.0 else turned
    if key == "flip":
        if value is None or value is False:
            return None
        return _choice(
            {"h": "horizontal", "v": "vertical", True: "horizontal"}.get(value, value), key, FLIPS
        )
    if key == "points":
        if isinstance(value, str) or not isinstance(value, Sequence) or len(value) < 2:
            raise ShapeError(
                key,
                f"points must be a list of two points or more, such as [[100, 100], [180, 140]], "
                f"not {value!r}.",
            )
        if len(value) > 5000:
            raise ShapeError(key, f"points has {len(value):,} points: a shape has 5,000 at most.")
        return [_point(item, key) for item in value]
    if key == "shapes":
        if depth >= 20:
            raise ShapeError(key, "Groups are nested more than 20 deep.")
        if isinstance(value, str) or not isinstance(value, Sequence) or not value:
            raise ShapeError(key, "A group's shapes must be a list of shapes, one at least.")
        made = []
        for index, item in enumerate(value):
            try:
                made.append(checked(item, extra=(), depth=depth + 1))
            except ShapeError as error:
                raise ShapeError(
                    f"shapes[{index}].{error.key}" if error.key else f"shapes[{index}]",
                    error.message,
                ) from None
        return made
    ranges = {
        "corner": (0.0, LIMIT, "12 (points)"),
        "apex": (0.0, 1.0, "0.5 (of the way across)"),
        "ratio": (0.05, 0.95, "0.38 (of the outer points)"),
        "slant": (0.0, 1.0, "0.25"),
        "inset": (0.0, 0.5, "0.25"),
        "shaft": (0.05, 1.0, "0.5"),
        "head": (0.0, 1.0, "0.5"),
        "point": (0.0, 1.0, "0.5"),
        "arm": (0.02, 0.48, "0.25"),
        "bend": (-4.0, 4.0, "0.25 (of its length)"),
        "lean": (-0.5, 0.5, "0.1 (of its length)"),
        "elbow": (-4.0, 5.0, "0.5 (of the way across)"),
        "depth": (-LIMIT, LIMIT, "16 (points)"),
        "curl": (0.0, 1.0, "0.5"),
        "tip": (0.05, 0.95, "0.5"),
    }
    if key in ranges:
        return _number(value, key, *ranges[key])
    if key == "sides":
        return _whole(value, key, 3, 24)
    if key == "tips":
        return _whole(value, key, 3, 32)
    if key == "route":
        return _choice(value, key, ROUTES)
    if key == "body":
        return _choice(value, key, BODIES)
    if key == "d":
        return _path_data(value)
    if key == "fill_rule":
        named = {"even-odd": "evenodd", "non-zero": "nonzero"}
        return _choice(
            named.get(value, value) if isinstance(value, str) else value, key, FILL_RULES
        )
    raise ShapeError(
        key, f"Unknown key {key} for a {kind}."
    )  # pragma: no cover - keys_of lists them all


def _inset_value(key: str, value: object) -> object:
    """A zoom inset's own setting, checked (``INSET_KEYS``)."""

    if key == "of":
        if isinstance(value, bool) or not isinstance(value, str | int) or not str(value).strip():
            raise ShapeError(
                key,
                f"of must name what the inset shows part of: an object of a slide (body[0]) or "
                f"a part of a figure (its id), not {value!r}.",
            )
        return str(value).strip()
    if key == "region":
        said = (
            "region must be the part shown, [x, y, width, height] as fractions of what it "
            f"shows part of, such as [0.4, 0.3, 0.2, 0.2], not {value!r}."
        )
        if (
            isinstance(value, str)
            or not isinstance(value, Sequence)
            or len(value) != 4
            or any(
                isinstance(item, bool)
                or not isinstance(item, int | float)
                or not math.isfinite(item)
                for item in value
            )
        ):
            raise ShapeError(key, said)
        x, y, w, h = (float(item) for item in value)
        if w <= 0.0 or h <= 0.0 or x < -1e-6 or y < -1e-6 or x + w > 1.0001 or y + h > 1.0001:
            raise ShapeError(key, said)
        return [x, y, w, h]
    if key.endswith("_line"):
        return colour_of(value, key)
    if key.endswith("_width"):
        return _number(value, key, 0.0, 200.0, "1.5 (points)")
    return _choice(value, key, DASHES)


def _path_data(value: object) -> str:
    """A path's outline as written (``d``), checked: SVG path data, read as ``flexo.pathdata``
    reads it, what is wrong said in words."""

    if not isinstance(value, str):
        raise ShapeError(
            "d", f"d must be SVG path data, such as {pathdata.EXAMPLE}, not {value!r}."
        )
    try:
        pathdata.parsed(value)
    except pathdata.PathError as error:
        raise ShapeError("d", str(error)) from None
    return value


# -- geometry ------------------------------------------------------------------------------

KAPPA = 0.5522847498307936
"""How far a cubic's handles stand from its ends to draw a quarter circle."""

CLOUD_START = (0.03171, 0.66922)
CLOUD = (
    (0.00644, 0.62621, -0.00453, 0.56924, 0.00171, 0.51343),
    (0.00796, 0.45763, 0.03078, 0.40863, 0.06412, 0.37944),
    (0.06241, 0.29946, 0.09012, 0.2242, 0.13688, 0.18187),
    (0.18364, 0.13955, 0.24237, 0.13655, 0.29106, 0.17401),
    (0.32083, 0.06679, 0.39316, -0.00249, 0.47275, 0.0),
    (0.55233, 0.00249, 0.62255, 0.07623, 0.6491, 0.18521),
    (0.69516, 0.12126, 0.76276, 0.10246, 0.82183, 0.13718),
    (0.88089, 0.1719, 0.92046, 0.25368, 0.92292, 0.34616),
    (0.9691, 0.37704, 0.99904, 0.44355, 1.0, 0.51736),
    (1.00096, 0.59117, 0.97277, 0.65927, 0.92743, 0.69266),
    (0.92897, 0.77426, 0.89287, 0.84734, 0.83916, 0.87137),
    (0.78544, 0.8954, 0.72728, 0.86449, 0.69694, 0.79579),
    (0.69566, 0.86579, 0.66877, 0.92949, 0.62639, 0.96289),
    (0.584, 0.99629, 0.53257, 0.99432, 0.49146, 0.95771),
    (0.45036, 0.92111, 0.42582, 0.85543, 0.42709, 0.78543),
    (0.43313, 0.89162, 0.37875, 0.98481, 0.30563, 0.99358),
    (0.23251, 1.00235, 0.16834, 0.92338, 0.1623, 0.81719),
    (0.09931, 0.82272, 0.04334, 0.7593, 0.03171, 0.66922),
)
"""A cloud in the unit square, as cubics: a figure's cloud (``flexo.shapes``), the same puffs."""


@dataclass(slots=True)
class Label:
    """Where a line's words go: a point, which side of it they stand on (``align``, across;
    ``valign``, down), turned ``angle`` degrees about it."""

    x: float
    y: float
    align: str = "middle"
    valign: str = "middle"
    angle: float = 0.0


@dataclass(slots=True)
class Head:
    end: str
    """``start`` or ``end``."""
    kind: str
    segments: list[Segment]
    filled: bool
    stroked: bool
    tip: Point
    angle: float
    """The way it points, degrees clockwise from +x."""


@dataclass(slots=True)
class Geometry:
    """A shape as drawn: its outline (``segments``: a box's before it is turned, about
    ``centre`` by ``turn``), its heads, and where its words go -- inside it (``area``, in
    the same unturned frame) or beside it (``label``)."""

    segments: list[Segment]
    closed: bool
    box: tuple[float, float, float, float]
    """Its frame, unturned: x, y, width, height."""
    turn: float = 0.0
    heads: list[Head] = field(default_factory=list)
    area: tuple[float, float, float, float] | None = None
    label: Label | None = None
    ends: tuple[Point, Point] | None = None
    """A line's ends, as drawn (glued ends where they are glued)."""
    extra: list[list[Segment]] = field(default_factory=list)
    """Strokes drawn besides the outline, unfilled: none, for now."""
    data: str | None = None
    """Its outline as SVG path data, where that is kept with what was read (a path's, written
    once however often it is drawn); else it is written from ``segments``."""

    @property
    def centre(self) -> Point:
        x, y, w, h = self.box
        return (x + w / 2.0, y + h / 2.0)


def path_data(segments: Sequence[Segment]) -> str:
    """Segments as an SVG path's data."""

    words = []
    for segment in segments:
        words.append(segment[0])
        words.extend(number(value) for value in segment[1:])
    return " ".join(words)


def _rounded_box(x: float, y: float, w: float, h: float, r: float) -> list[Segment]:
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    if r <= 1e-9:
        return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
    k = r * (1.0 - KAPPA)
    return [
        ("M", x + r, y),
        ("L", x + w - r, y),
        ("C", x + w - k, y, x + w, y + k, x + w, y + r),
        ("L", x + w, y + h - r),
        ("C", x + w, y + h - k, x + w - k, y + h, x + w - r, y + h),
        ("L", x + r, y + h),
        ("C", x + k, y + h, x, y + h - k, x, y + h - r),
        ("L", x, y + r),
        ("C", x, y + k, x + k, y, x + r, y),
        ("Z",),
    ]


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Segment]:
    kx, ky = rx * KAPPA, ry * KAPPA
    return [
        ("M", cx + rx, cy),
        ("C", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry),
        ("C", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy),
        ("C", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry),
        ("C", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy),
        ("Z",),
    ]


def _polygon(points: Sequence[Point]) -> list[Segment]:
    return [("M", *points[0]), *(("L", *point) for point in points[1:]), ("Z",)]


def _fitted(points: Sequence[Point], x: float, y: float, w: float, h: float) -> list[Point]:
    """Points stretched to fill a box, as a slide program's polygons and stars fill theirs."""

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    left, top = min(xs), min(ys)
    across, down = (max(xs) - left) or 1.0, (max(ys) - top) or 1.0
    return [(x + (px - left) / across * w, y + (py - top) / down * h) for px, py in points]


def _arc_cubics(
    cx: float, cy: float, rx: float, ry: float, start: float, sweep: float
) -> list[Segment]:
    """An ellipse's arc from angle ``start`` through ``sweep`` (radians, y down), as cubics."""

    pieces = max(1, math.ceil(abs(sweep) / (math.pi / 2.0) - 1e-9))
    step = sweep / pieces
    k = 4.0 / 3.0 * math.tan(step / 4.0)
    out: list[Segment] = []
    angle = start
    for _ in range(pieces):
        a, b = angle, angle + step
        out.append(
            (
                "C",
                cx + rx * (math.cos(a) - k * math.sin(a)),
                cy + ry * (math.sin(a) + k * math.cos(a)),
                cx + rx * (math.cos(b) + k * math.sin(b)),
                cy + ry * (math.sin(b) - k * math.cos(b)),
                cx + rx * math.cos(b),
                cy + ry * math.sin(b),
            )
        )
        angle = b
    return out


def _callout(spec: Mapping[str, Any], x: float, y: float, w: float, h: float) -> list[Segment]:
    """A speech bubble whose tail points at ``tail``, as a slide program's callouts are drawn
    (wedgeRectCallout, wedgeRoundRectCallout, wedgeEllipseCallout): the tail's foot on the
    side facing its point, a twelfth of the side either side of a third of the way along."""

    tail = spec.get("tail") or [x + w * 0.25, y + h * 1.45]
    tx, ty = _unturned(tail, (x + w / 2.0, y + h / 2.0), float(spec.get("rotate") or 0.0))
    cx, cy = x + w / 2.0, y + h / 2.0
    dx, dy = tx - cx, ty - cy
    if spec.get("body") == "oval":
        rx, ry = w / 2.0, h / 2.0
        angle = math.atan2(dy * w, dx * h)
        start, end = angle + math.radians(11.0), angle - math.radians(11.0)
        first = (cx + rx * math.cos(start), cy + ry * math.sin(start))
        sweep = (end - start) % (2.0 * math.pi)
        return [("M", *first), *_arc_cubics(cx, cy, rx, ry, start, sweep), ("L", tx, ty), ("Z",)]
    vertical = abs(dy) - abs(dx * h / max(w, 1e-9)) > 0
    x1, x2 = x + w * (7 if dx > 0 else 2) / 12.0, x + w * (10 if dx > 0 else 5) / 12.0
    y1, y2 = y + h * (7 if dy > 0 else 2) / 12.0, y + h * (10 if dy > 0 else 5) / 12.0
    top = (tx, ty) if vertical and dy <= 0 else (x1, y)
    bottom = (tx, ty) if vertical and dy > 0 else (x1, y + h)
    left = (tx, ty) if not vertical and dx <= 0 else (x, y1)
    right = (tx, ty) if not vertical and dx > 0 else (x + w, y1)
    r = (
        0.0
        if spec.get("body") == "rectangle"
        else max(0.0, min(float(spec.get("corner") or 0.0), w / 2.0, h / 2.0))
    )
    k = r * (1.0 - KAPPA)
    out: list[Segment] = [("M", x, y + r)]
    if r:
        out.append(("C", x, y + k, x + k, y, x + r, y))
    out += [("L", x1, y), ("L", *top), ("L", x2, y), ("L", x + w - r, y)]
    if r:
        out.append(("C", x + w - k, y, x + w, y + k, x + w, y + r))
    out += [("L", x + w, y1), ("L", *right), ("L", x + w, y2), ("L", x + w, y + h - r)]
    if r:
        out.append(("C", x + w, y + h - k, x + w - k, y + h, x + w - r, y + h))
    out += [("L", x2, y + h), ("L", *bottom), ("L", x1, y + h), ("L", x + r, y + h)]
    if r:
        out.append(("C", x + k, y + h, x, y + h - k, x, y + h - r))
    out += [("L", x, y2), ("L", *left), ("L", x, y1), ("Z",)]
    return out


def _closed_outline(
    spec: Mapping[str, Any], x: float, y: float, w: float, h: float
) -> list[Segment]:
    kind = spec["kind"]
    ss = min(w, h)
    cx, cy = x + w / 2.0, y + h / 2.0
    if kind in ("rectangle", "rounded-rectangle", "highlight", "inset"):
        return _rounded_box(x, y, w, h, float(spec.get("corner") or 0.0))
    if kind in ("ellipse", "ring"):
        return _ellipse(cx, cy, w / 2.0, h / 2.0)
    if kind == "triangle":
        return _polygon([(x, y + h), (x + w * float(spec["apex"]), y), (x + w, y + h)])
    if kind == "right-triangle":
        return _polygon([(x, y), (x + w, y + h), (x, y + h)])
    if kind == "diamond":
        return _polygon([(cx, y), (x + w, cy), (cx, y + h), (x, cy)])
    if kind == "polygon":
        n = int(spec["sides"])
        unit = [
            (
                math.cos(-math.pi / 2.0 + 2.0 * math.pi * k / n),
                math.sin(-math.pi / 2.0 + 2.0 * math.pi * k / n),
            )
            for k in range(n)
        ]
        return _polygon(_fitted(unit, x, y, w, h))
    if kind == "star":
        n, ratio = int(spec["tips"]), float(spec["ratio"])
        unit = []
        for k in range(2 * n):
            angle = -math.pi / 2.0 + math.pi * k / n
            radius = 1.0 if k % 2 == 0 else ratio
            unit.append((radius * math.cos(angle), radius * math.sin(angle)))
        outer = [unit[k] for k in range(0, 2 * n, 2)]
        xs, ys = [p[0] for p in outer], [p[1] for p in outer]
        left, top, across, down = (
            min(xs),
            min(ys),
            (max(xs) - min(xs)) or 1.0,
            (max(ys) - min(ys)) or 1.0,
        )
        return _polygon(
            [(x + (px - left) / across * w, y + (py - top) / down * h) for px, py in unit]
        )
    if kind == "parallelogram":
        slant = min(ss * float(spec["slant"]), w)
        return _polygon([(x, y + h), (x + slant, y), (x + w, y), (x + w - slant, y + h)])
    if kind == "trapezoid":
        inset = min(ss * float(spec["inset"]), w / 2.0)
        return _polygon([(x, y + h), (x + inset, y), (x + w - inset, y), (x + w, y + h)])
    if kind in ("arrow-right", "arrow-left"):
        head = min(ss * float(spec["head"]), w)
        half = h * float(spec["shaft"]) / 2.0
        points = [
            (x, cy - half),
            (x + w - head, cy - half),
            (x + w - head, y),
            (x + w, cy),
            (x + w - head, y + h),
            (x + w - head, cy + half),
            (x, cy + half),
        ]
        if kind == "arrow-left":
            points = [(2.0 * cx - px, py) for px, py in points]
        return _polygon(points)
    if kind in ("arrow-up", "arrow-down"):
        head = min(ss * float(spec["head"]), h)
        half = w * float(spec["shaft"]) / 2.0
        points = [
            (x, y + head),
            (cx, y),
            (x + w, y + head),
            (cx + half, y + head),
            (cx + half, y + h),
            (cx - half, y + h),
            (cx - half, y + head),
        ]
        if kind == "arrow-down":
            points = [(px, 2.0 * cy - py) for px, py in points]
        return _polygon(points)
    if kind == "arrow-left-right":
        head = min(ss * float(spec["head"]), w / 2.0)
        half = h * float(spec["shaft"]) / 2.0
        return _polygon(
            [
                (x, cy),
                (x + head, y),
                (x + head, cy - half),
                (x + w - head, cy - half),
                (x + w - head, y),
                (x + w, cy),
                (x + w - head, y + h),
                (x + w - head, cy + half),
                (x + head, cy + half),
                (x + head, y + h),
            ]
        )
    if kind == "chevron":
        point = min(ss * float(spec["point"]), w)
        return _polygon(
            [
                (x, y),
                (x + w - point, y),
                (x + w, cy),
                (x + w - point, y + h),
                (x, y + h),
                (x + point, cy),
            ]
        )
    if kind == "plus":
        arm = ss * float(spec["arm"])
        return _polygon(
            [
                (x, y + arm),
                (x + arm, y + arm),
                (x + arm, y),
                (x + w - arm, y),
                (x + w - arm, y + arm),
                (x + w, y + arm),
                (x + w, y + h - arm),
                (x + w - arm, y + h - arm),
                (x + w - arm, y + h),
                (x + arm, y + h),
                (x + arm, y + h - arm),
                (x, y + h - arm),
            ]
        )
    if kind == "cross":
        k = float(spec["arm"])
        unit = [
            (0.0, k),
            (k, 0.0),
            (0.5, 0.5 - k),
            (1.0 - k, 0.0),
            (1.0, k),
            (0.5 + k, 0.5),
            (1.0, 1.0 - k),
            (1.0 - k, 1.0),
            (0.5, 0.5 + k),
            (k, 1.0),
            (0.0, 1.0 - k),
            (0.5 - k, 0.5),
        ]
        return _polygon([(x + u * w, y + v * h) for u, v in unit])
    if kind == "check":
        unit = [(0.0, 0.58), (0.13, 0.44), (0.37, 0.68), (0.87, 0.02), (1.0, 0.16), (0.37, 1.0)]
        return _polygon([(x + u * w, y + v * h) for u, v in unit])
    if kind == "cloud":
        out: list[Segment] = [("M", x + CLOUD_START[0] * w, y + CLOUD_START[1] * h)]
        for cubic in CLOUD:
            out.append(
                (
                    "C",
                    *(
                        x + value * w if index % 2 == 0 else y + value * h
                        for index, value in enumerate(cubic)
                    ),
                )
            )
        out.append(("Z",))
        return out
    if kind == "bubble":
        return _callout(spec, x, y, w, h)
    raise ValueError(f"Not a closed shape: {kind}")  # pragma: no cover


def _area(
    spec: Mapping[str, Any], x: float, y: float, w: float, h: float
) -> tuple[float, float, float, float]:
    """Where a closed shape's words go, unturned: as a slide program sets them in its shapes
    (each preset's text rectangle), so its words land in the same place in a PowerPoint."""

    kind = spec["kind"]
    ss = min(w, h)
    if kind in ("rectangle", "rounded-rectangle", "highlight") or (
        kind == "bubble" and spec.get("body") != "oval"
    ):
        corner = (
            0.0
            if kind == "bubble" and spec.get("body") == "rectangle"
            else max(0.0, min(float(spec.get("corner") or 0.0), w / 2.0, h / 2.0))
        )
        inset = corner * 0.29289
        return (x + inset, y + inset, w - 2 * inset, h - 2 * inset)
    if kind in ("ellipse", "ring", "bubble"):
        return (x + w * 0.14645, y + h * 0.14645, w * 0.7071, h * 0.7071)
    if kind == "triangle":
        apex = float(spec["apex"])
        return (x + w * apex / 2.0, y + h / 2.0, w / 2.0, h / 2.0)
    if kind == "right-triangle":
        return (x + w / 12.0, y + h * 7.0 / 12.0, w / 2.0, h / 3.0)
    if kind in ("diamond", "cross"):
        return (x + w / 4.0, y + h / 4.0, w / 2.0, h / 2.0)
    if kind == "parallelogram":
        share = float(spec["slant"]) * ss / max(w, 1e-9)
        inset = (1.0 + 5.0 * share) / 12.0
        return (x + w * inset, y + h * inset, w * (1 - 2 * inset), h * (1 - 2 * inset))
    if kind == "trapezoid":
        share = float(spec["inset"]) * ss / max(w / 2.0, 1e-9)
        return (
            x + w / 3.0 * share,
            y + h / 3.0 * share,
            w - 2.0 * w / 3.0 * share,
            h - h / 3.0 * share,
        )
    if kind in ("polygon", "star"):
        inner = (
            math.cos(math.pi / int(spec["sides"])) if kind == "polygon" else float(spec["ratio"])
        )
        half = 0.5 * inner * 0.8
        return (x + w * (0.5 - half), y + h * (0.5 - half), w * 2 * half, h * 2 * half)
    if kind in ("arrow-right", "arrow-left"):
        head, half = min(ss * float(spec["head"]), w), h * float(spec["shaft"]) / 2.0
        reach = w - head + half * head / max(h / 2.0, 1e-9)
        left = x if kind == "arrow-right" else x + w - reach
        return (left, y + h / 2.0 - half, reach, 2.0 * half)
    if kind in ("arrow-up", "arrow-down"):
        head, half = min(ss * float(spec["head"]), h), w * float(spec["shaft"]) / 2.0
        reach = h - head + half * head / max(w / 2.0, 1e-9)
        top = y + h - reach if kind == "arrow-up" else y
        return (x + w / 2.0 - half, top, 2.0 * half, reach)
    if kind == "arrow-left-right":
        head, half = min(ss * float(spec["head"]), w / 2.0), h * float(spec["shaft"]) / 2.0
        inner = head - half * head / max(h / 2.0, 1e-9)
        return (x + inner, y + h / 2.0 - half, w - 2.0 * inner, 2.0 * half)
    if kind == "chevron":
        point = min(ss * float(spec["point"]), w)
        return (x + point, y, max(w - 2.0 * point, 0.0), h)
    if kind == "plus":
        arm = ss * float(spec["arm"])
        return (x, y + arm, w, h - 2.0 * arm)
    if kind == "cloud":
        return (
            x + w * 2977 / 21600,
            y + h * 3262 / 21600,
            w * (17087 - 2977) / 21600,
            h * (17337 - 3262) / 21600,
        )
    return (x, y, w, h)


def _flipped(segments: list[Segment], flip: str | None, cx: float, cy: float) -> list[Segment]:
    if not flip:
        return segments
    sx = -1.0 if flip in ("horizontal", "both") else 1.0
    sy = -1.0 if flip in ("vertical", "both") else 1.0
    out: list[Segment] = []
    for segment in segments:
        values = segment[1:]
        out.append(
            (
                segment[0],
                *(
                    cx + sx * (value - cx) if index % 2 == 0 else cy + sy * (value - cy)
                    for index, value in enumerate(values)
                ),
            )
        )
    return out


def _turned(point: Sequence[float], centre: Point, degrees: float) -> Point:
    if not degrees:
        return (float(point[0]), float(point[1]))
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    return (centre[0] + cos * dx - sin * dy, centre[1] + sin * dx + cos * dy)


def _unturned(point: Sequence[float], centre: Point, degrees: float) -> Point:
    return _turned(point, centre, -degrees)


def _cubic_at(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _split(
    p0: Point, p1: Point, p2: Point, p3: Point, t: float
) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    def mix(a: Point, b: Point) -> Point:
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    a, b, c = mix(p0, p1), mix(p1, p2), mix(p2, p3)
    d, e = mix(a, b), mix(b, c)
    f = mix(d, e)
    return (p0, a, d, f), (f, e, c, p3)


def _ends_of(segments: list[Segment]) -> tuple[Point, Point, Point, Point]:
    """A line's first and last points, and the way it runs out of each (unit vectors,
    outward)."""

    points = []
    for segment in segments:
        if segment[0] in ("M", "L"):
            points.append(("P", (segment[1], segment[2])))
        elif segment[0] == "C":
            points.append(
                ("C", (segment[1], segment[2]), (segment[3], segment[4]), (segment[5], segment[6]))
            )
    flat: list[Point] = []
    for item in points:
        flat.extend(item[1:])
    start, end = flat[0], flat[-1]
    after = next((p for p in flat[1:] if math.dist(p, start) > 1e-6), (start[0] + 1.0, start[1]))
    before = next(
        (p for p in reversed(flat[:-1]) if math.dist(p, end) > 1e-6), (end[0] - 1.0, end[1])
    )
    way_out_start = _unit(start[0] - after[0], start[1] - after[1])
    way_out_end = _unit(end[0] - before[0], end[1] - before[1])
    return start, way_out_start, end, way_out_end


def _unit(dx: float, dy: float) -> Point:
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-12 else (1.0, 0.0)


def head_size(spec: Mapping[str, Any]) -> tuple[float, float]:
    """An arrowhead's length and width, by the line's width and ``head_size``."""

    width = float(spec.get("line_width") or 0.0)
    length = float(spec.get("head_size") or 1.0) * (4.0 + 3.0 * width)
    return length, length * 0.85


def _head(
    kind: str, end: str, tip: Point, way: Point, spec: Mapping[str, Any]
) -> tuple[Head, float]:
    """An arrowhead at ``tip`` pointing ``way`` (outward), and how far the line is cut short
    under it."""

    length, width = head_size(spec)
    line = float(spec.get("line_width") or 0.0)
    ux, uy = way
    px, py = -uy, ux
    tx, ty = tip
    scale = float(spec.get("head_size") or 1.0)

    def at(along: float, across: float) -> Point:
        return (tx + ux * along + px * across, ty + uy * along + py * across)

    angle = math.degrees(math.atan2(uy, ux))
    if kind == "triangle":
        return Head(
            end,
            kind,
            _polygon([tip, at(-length, width / 2), at(-length, -width / 2)]),
            True,
            False,
            tip,
            angle,
        ), length * 0.8
    if kind == "stealth":
        return Head(
            end,
            kind,
            _polygon(
                [
                    tip,
                    at(-length, width * 0.53),
                    at(-length * 0.65, 0.0),
                    at(-length, -width * 0.53),
                ]
            ),
            True,
            False,
            tip,
            angle,
        ), length * 0.6
    if kind == "open":
        return Head(
            end,
            kind,
            [("M", *at(-length, width / 2)), ("L", *tip), ("L", *at(-length, -width / 2))],
            False,
            True,
            tip,
            angle,
        ), 0.0
    if kind in ("dot", "circle"):
        radius = scale * (1.5 + 1.2 * line)
        return Head(
            end, kind, _ellipse(tx, ty, radius, radius), kind == "dot", kind == "circle", tip, angle
        ), (radius if kind == "circle" else 0.0)
    if kind == "bar":
        reach = scale * (6.0 + 3.0 * line) / 2.0
        return Head(
            end, kind, [("M", *at(0.0, reach)), ("L", *at(0.0, -reach))], False, True, tip, angle
        ), 0.0
    # diamond: centred on the end, as a slide program's diamond line end is
    return Head(
        end,
        kind,
        _polygon(
            [at(length / 2, 0.0), at(0.0, width / 2), at(-length / 2, 0.0), at(0.0, -width / 2)]
        ),
        True,
        False,
        tip,
        angle,
    ), 0.0


def _trimmed(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """An open line cut short by ``start`` at its start and ``end`` at its end (along it,
    near enough), never past its middle."""

    out = list(segments)
    if end > 1e-9:
        last = out[-1]
        before = _last_point(out[:-1])
        if last[0] == "L":
            point = (last[1], last[2])
            length = math.dist(before, point)
            cut = min(end, length * 0.9)
            ux, uy = _unit(point[0] - before[0], point[1] - before[1])
            out[-1] = ("L", point[0] - ux * cut, point[1] - uy * cut)
        elif last[0] == "C":
            p0, p1, p2, p3 = before, (last[1], last[2]), (last[3], last[4]), (last[5], last[6])
            t = _cut_at(p0, p1, p2, p3, end, from_end=True)
            (a, b, c, d), _ = _split(p0, p1, p2, p3, t)
            out[-1] = ("C", *b, *c, *d)
    if start > 1e-9 and len(out) > 1:
        first = (out[0][1], out[0][2])
        nxt = out[1]
        if nxt[0] == "L":
            point = (nxt[1], nxt[2])
            length = math.dist(first, point)
            cut = min(start, length * 0.9)
            ux, uy = _unit(point[0] - first[0], point[1] - first[1])
            out[0] = ("M", first[0] + ux * cut, first[1] + uy * cut)
        elif nxt[0] == "C":
            p0, p1, p2, p3 = first, (nxt[1], nxt[2]), (nxt[3], nxt[4]), (nxt[5], nxt[6])
            t = _cut_at(p0, p1, p2, p3, start, from_end=False)
            _, (a, b, c, d) = _split(p0, p1, p2, p3, t)
            out[0] = ("M", *a)
            out[1] = ("C", *b, *c, *d)
    return out


def _cut_at(
    p0: Point, p1: Point, p2: Point, p3: Point, distance: float, *, from_end: bool
) -> float:
    """Where along a cubic (its parameter) a point is ``distance`` from its end (or start)."""

    anchor = p3 if from_end else p0
    low, high = (0.5, 1.0) if from_end else (0.0, 0.5)
    for _ in range(40):
        middle = (low + high) / 2.0
        far = math.dist(_cubic_at(p0, p1, p2, p3, middle), anchor)
        if from_end:
            low, high = (low, middle) if far < distance else (middle, high)
        else:
            low, high = (middle, high) if far < distance else (low, middle)
    return (low + high) / 2.0


def _last_point(segments: Sequence[Segment]) -> Point:
    for segment in reversed(segments):
        if segment[0] in ("M", "L"):
            return (segment[1], segment[2])
        if segment[0] == "C":
            return (segment[5], segment[6])
    return (0.0, 0.0)


def _point_of(value: object) -> Point:
    if isinstance(value, Mapping):
        at = value.get("at")
        return (float(at[0]), float(at[1])) if at else (0.0, 0.0)
    return (float(value[0]), float(value[1]))  # type: ignore[index]


def _line_path(
    spec: Mapping[str, Any], a: Point, b: Point
) -> tuple[list[Segment], Label | None, Point | None]:
    """A line's path from ``a`` to ``b``, where its words go, and its tip (a brace's)."""

    kind = spec["kind"]
    length = math.dist(a, b)
    ux, uy = _unit(b[0] - a[0], b[1] - a[1])
    nx, ny = uy, -ux  # left of the way it runs, on the page
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    gap = float(spec.get("line_width") or 0.0) / 2.0 + 4.0
    if kind == "curved-arrow":
        bend, lean = float(spec.get("bend") or 0.0), float(spec.get("lean") or 0.0)
        through = (
            mid[0] + (nx * bend + ux * lean) * length,
            mid[1] + (ny * bend + uy * lean) * length,
        )
        control = (2 * through[0] - mid[0], 2 * through[1] - mid[1])
        c1 = (a[0] + 2.0 / 3.0 * (control[0] - a[0]), a[1] + 2.0 / 3.0 * (control[1] - a[1]))
        c2 = (b[0] + 2.0 / 3.0 * (control[0] - b[0]), b[1] + 2.0 / 3.0 * (control[1] - b[1]))
        side = 1.0 if bend >= 0 else -1.0
        return [("M", *a), ("C", *c1, *c2, *b)], _beside(through, (nx * side, ny * side), gap), None
    if kind == "arc":
        bend = float(spec.get("bend") or 0.0)
        sagitta = bend * length
        if abs(sagitta) < 1e-6 or length < 1e-9:
            return [("M", *a), ("L", *b)], _beside(mid, (nx, ny), gap), None
        radius = (length * length / 4.0 + sagitta * sagitta) / (2.0 * abs(sagitta))
        t = sagitta - math.copysign(radius, sagitta)
        cx, cy = mid[0] + nx * t, mid[1] + ny * t
        top = (mid[0] + nx * sagitta, mid[1] + ny * sagitta)
        a0 = math.atan2(a[1] - cy, a[0] - cx)
        a1 = math.atan2(b[1] - cy, b[0] - cx)
        am = math.atan2(top[1] - cy, top[0] - cx)
        turn = 2.0 * math.pi
        forward = (a1 - a0) % turn
        sweep = forward if (am - a0) % turn < forward else -((a0 - a1) % turn)
        side = 1.0 if sagitta >= 0 else -1.0
        return (
            [("M", *a), *_arc_cubics(cx, cy, radius, radius, a0, sweep)],
            _beside(top, (nx * side, ny * side), gap),
            None,
        )
    if kind == "elbow":
        share = float(spec.get("elbow", 0.5))
        if spec.get("route") == "down":
            ym = a[1] + share * (b[1] - a[1])
            corners = [a, (a[0], ym), (b[0], ym), b]
        else:
            xm = a[0] + share * (b[0] - a[0])
            corners = [a, (xm, a[1]), (xm, b[1]), b]
        middle = ((corners[1][0] + corners[2][0]) / 2.0, (corners[1][1] + corners[2][1]) / 2.0)
        way = _unit(corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
        return (
            [("M", *corners[0]), *(("L", *point) for point in corners[1:])],
            _beside(middle, (way[1], -way[0]), gap),
            None,
        )
    if kind in ("brace", "bracket"):
        depth = float(spec.get("depth") or 0.0)
        reach = abs(depth)

        def at(u: float, v: float) -> Point:
            # (In its own frame -- u along it, v towards its tip -- on the page.)
            return (a[0] + ux * u + nx * v, a[1] + uy * u + ny * v)

        sign = 1.0 if depth >= 0 else -1.0
        if kind == "bracket":
            curl = min(float(spec.get("curl") or 0.0) * reach, length / 2.0)
            out: list[Segment] = [("M", *at(0.0, 0.0))]
            if curl > 1e-9:
                out += _bracket_corner(at, curl, depth, first=True)
            else:
                out.append(("L", *at(0.0, depth)))
            out.append(("L", *at(length - curl, depth)))
            if curl > 1e-9:
                out += _bracket_corner(at, curl, depth, first=False, length=length)
            else:
                out.append(("L", *at(length, 0.0)))
            tip = at(length / 2.0, depth)
            return out, _beside(tip, (nx * sign, ny * sign), gap + 2.0), tip
        tip_at = float(spec.get("tip", 0.5)) * length
        curl = min(float(spec.get("curl") or 0.0) * reach, tip_at / 2.0, (length - tip_at) / 2.0)
        mid_v = depth / 2.0
        out = [("M", *at(0.0, 0.0))]
        out += _brace_quarter(
            at, (curl, 0.0), curl, mid_v, from_angle=math.pi, to_angle=math.pi / 2.0
        )
        out.append(("L", *at(tip_at - curl, mid_v)))
        out += _brace_quarter(
            at, (tip_at - curl, depth), curl, mid_v, from_angle=-math.pi / 2.0, to_angle=0.0
        )
        out += _brace_quarter(
            at, (tip_at + curl, depth), curl, mid_v, from_angle=math.pi, to_angle=1.5 * math.pi
        )
        out.append(("L", *at(length - curl, mid_v)))
        out += _brace_quarter(
            at, (length - curl, 0.0), curl, mid_v, from_angle=math.pi / 2.0, to_angle=0.0
        )
        tip = at(tip_at, depth)
        return out, _beside(tip, (nx * sign, ny * sign), gap + 2.0), tip
    if kind in ("dimension", "scale-bar"):
        angle = math.degrees(math.atan2(uy, ux))
        upright = angle + 180.0 if angle > 90.0 or angle <= -90.0 else angle
        side = 1.0 if kind == "dimension" else -1.0
        width = float(spec.get("line_width") or 0.0)
        heads = max((_head_reach(spec, end) for end in ("start", "end")), default=0.0)
        away = (heads if kind == "dimension" else width / 2.0) + 3.0
        point = (mid[0] + nx * side * away, mid[1] + ny * side * away)
        # Which way the side they stand on is, in the frame of the words turned upright.
        turn = math.radians(upright)
        local_y = -(nx * side) * math.sin(turn) + (ny * side) * math.cos(turn)
        return (
            [("M", *a), ("L", *b)],
            Label(point[0], point[1], "middle", "bottom" if local_y < 0 else "top", upright),
            None,
        )
    return [("M", *a), ("L", *b)], _beside(mid, (nx, ny), gap), None


def _head_reach(spec: Mapping[str, Any], end: str) -> float:
    kind = spec.get(end) or "none"
    if kind == "bar":
        return (
            float(spec.get("head_size") or 1.0)
            * (6.0 + 3.0 * float(spec.get("line_width") or 0.0))
            / 2.0
        )
    if kind == "none":
        return float(spec.get("line_width") or 0.0) / 2.0
    return head_size(spec)[1] / 2.0


def _bracket_corner(
    at: Callable[[float, float], Point],
    curl: float,
    depth: float,
    *,
    first: bool,
    length: float = 0.0,
) -> list[Segment]:
    # A corner rounded as a slide program's bracket rounds it: a quarter ellipse ``curl`` along
    # the bracket and all its depth across.
    k = KAPPA
    if first:
        return [("C", *at(0.0, depth * k), *at(curl * (1 - k), depth), *at(curl, depth))]
    return [("C", *at(length - curl * (1 - k), depth), *at(length, depth * k), *at(length, 0.0))]


def _brace_quarter(
    at: Callable[[float, float], Point],
    centre: tuple[float, float],
    ru: float,
    rv: float,
    *,
    from_angle: float,
    to_angle: float,
) -> list[Segment]:
    """A quarter ellipse of a brace's curl, in its own frame (u along it, v towards its tip),
    on the page."""

    local = _arc_cubics(
        centre[0], centre[1], ru, abs(rv) if rv else 0.0, from_angle, to_angle - from_angle
    )
    sign = 1.0 if rv >= 0 else -1.0
    out: list[Segment] = []
    for segment in local:
        values = segment[1:]
        mapped: list[float] = []
        for index in range(0, 6, 2):
            u = values[index]
            v = centre[1] + (values[index + 1] - centre[1]) * sign
            mapped.extend(at(u, v))
        out.append(("C", *mapped))
    return out


def _beside(point: Point, normal: Point, gap: float) -> Label:
    """Words beside a line at ``point``, on the side ``normal`` points to, ``gap`` off it."""

    nx, ny = normal
    x, y = point[0] + nx * gap, point[1] + ny * gap
    if abs(nx) >= abs(ny) * 1.2:
        return Label(x, y, "start" if nx > 0 else "end", "middle")
    return Label(x, y, "middle", "top" if ny > 0 else "bottom")


def _smooth(points: Sequence[Point], is_closed: bool) -> list[Segment]:
    """A curve through every point, as a hand draws it (Catmull and Rom's)."""

    count = len(points)
    if count < 3:
        return [("M", *points[0]), *(("L", *point) for point in points[1:])] + (
            [("Z",)] if is_closed else []
        )
    out: list[Segment] = [("M", *points[0])]
    last = count if is_closed else count - 1
    for index in range(last):
        p0 = points[(index - 1) % count] if (is_closed or index > 0) else points[index]
        p1 = points[index]
        p2 = points[(index + 1) % count]
        p3 = points[(index + 2) % count] if (is_closed or index + 2 < count) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        out.append(("C", *c1, *c2, *p2))
    if is_closed:
        out.append(("Z",))
    return out


def geometry(
    spec: Mapping[str, Any],
    ends: tuple[Point, Point] | None = None,
    size: tuple[float, float] | None = None,
) -> Geometry:
    """A shape as drawn (see ``Geometry``). ``ends``: a line's ends where it is glued
    (``glued``); ``size``: a text box's, as its words make it."""

    spec = normalised(spec)
    kind = spec["kind"]
    form = family(kind)
    if form == "group":
        children = [geometry(child) for child in spec["shapes"]]
        boxes = [bounds(child, made) for child, made in zip(spec["shapes"], children, strict=True)]
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        return Geometry([], False, (left, top, right - left, bottom - top))
    if form == "path":
        return _path_geometry(spec)
    if form in ("box", "text"):
        x, y = (float(value) for value in spec["at"])
        if form == "text":
            w, h = (
                size
                if size is not None
                else (float(spec.get("width") or SIZES["text"][0]), SIZES["text"][1])
            )
        else:
            w, h = (float(value) for value in spec["size"])
        cx, cy = x + w / 2.0, y + h / 2.0
        # (A zoom inset shows what it magnifies as it is: never turned, nor mirrored.)
        turn = float(spec.get("rotate") or 0.0) if kind != "inset" else 0.0
        if form == "text":
            segments = _rounded_box(x, y, w, h, 0.0)
            area = (x, y, w, h)
        else:
            segments = _closed_outline(spec, x, y, w, h)
            area = _area(spec, x, y, w, h)
            if kind not in ("bubble", "inset"):
                segments = _flipped(segments, spec.get("flip"), cx, cy)
                flipped = _flipped(
                    [("M", area[0], area[1]), ("L", area[0] + area[2], area[1] + area[3])],
                    spec.get("flip"),
                    cx,
                    cy,
                )
                xs, ys = (flipped[0][1], flipped[1][1]), (flipped[0][2], flipped[1][2])
                area = (min(xs), min(ys), abs(xs[1] - xs[0]), abs(ys[1] - ys[0]))
        return Geometry(segments, True, (x, y, w, h), turn, [], area)
    if form == "points":
        points = [(float(p[0]), float(p[1])) for p in spec["points"]]
        is_closed = bool(spec.get("closed"))
        if kind == "pen":
            segments = _smooth(points, is_closed)
        else:
            segments = [("M", *points[0]), *(("L", *point) for point in points[1:])] + (
                [("Z",)] if is_closed else []
            )
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        label = None
        made = Geometry(segments, is_closed, box)
        if is_closed:
            made.area = box
        else:
            middle = _half_way(points)
            label = _beside(middle[0], middle[1], float(spec.get("line_width") or 0.0) / 2.0 + 4.0)
            made.label = label
            made.heads, made.segments = _headed(spec, segments)
            made.ends = (points[0], points[-1])
        return made
    a, b = ends if ends is not None else (_point_of(spec["from"]), _point_of(spec["to"]))
    segments, label, _tip = _line_path(spec, a, b)
    heads, segments = (
        _headed(spec, segments) if kind not in ("brace", "bracket") else ([], segments)
    )
    xs = [value for segment in segments for value in segment[1::2]]
    ys = [value for segment in segments for value in segment[2::2]]
    box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)) if xs else (a[0], a[1], 0.0, 0.0)
    return Geometry(segments, False, box, 0.0, heads, None, label, (a, b))


def _path_geometry(spec: Mapping[str, Any]) -> Geometry:
    """A path as drawn: its outline as read, in its box (what it draws), mirrored about that
    box's middle as it says, turned about it; its words in the box; an arrowhead at the start
    of its first piece and the end of its last, where those are open."""

    read = pathdata.parsed(str(spec["d"]))
    x, y, w, h = read.box
    flip = spec.get("flip") or None
    segments = _flipped(list(read.segments), flip, x + w / 2.0, y + h / 2.0)
    made = Geometry(segments, True, read.box, float(spec.get("rotate") or 0.0), [], read.box)
    first_open, last_open = read.opens
    ends = {
        **spec,
        "start": spec.get("start") if first_open else "none",
        "end": spec.get("end") if last_open else "none",
    }
    if (ends["start"] or "none") != "none" or (ends["end"] or "none") != "none":
        made.heads, made.segments = _headed(ends, segments)
    elif read.plain and not flip:
        # (Written plainly, it is drawn as written: a long path is not written out again.)
        made.data = str(spec["d"])
    else:
        made.data = read.kept(("data", flip), lambda: path_data(segments))
    return made


def path_open(spec: Mapping[str, Any]) -> bool:
    """Whether a path's first piece or its last is open: arrowheads go there."""

    return any(pathdata.parsed(str(spec["d"])).opens)


def _half_way(points: Sequence[Point]) -> tuple[Point, Point]:
    """The point half way along a polyline, and the normal on its left there."""

    lengths = [math.dist(p, q) for p, q in itertools.pairwise(points)]
    total = sum(lengths) / 2.0
    for (p, q), length in zip(itertools.pairwise(points), lengths, strict=True):
        if total <= length and length > 0:
            t = total / length
            ux, uy = _unit(q[0] - p[0], q[1] - p[1])
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t), (uy, -ux)
        total -= length
    return points[-1], (0.0, -1.0)


def _headed(spec: Mapping[str, Any], segments: list[Segment]) -> tuple[list[Head], list[Segment]]:
    start, start_way, end, end_way = _ends_of(segments)
    heads: list[Head] = []
    cuts = [0.0, 0.0]
    for index, (name, tip, way) in enumerate((("start", start, start_way), ("end", end, end_way))):
        kind = spec.get(name) or "none"
        if kind == "none":
            continue
        head, cut = _head(kind, name, tip, way, spec)
        heads.append(head)
        cuts[index] = cut
    return heads, _trimmed(segments, cuts[0], cuts[1]) if any(cuts) else segments


def corners(spec: Mapping[str, Any], made: Geometry) -> list[Point]:
    """The points a shape's frame turns about: its box's corners, turned as it is."""

    x, y, w, h = made.box
    return [
        _turned(point, made.centre, made.turn)
        for point in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    ]


def bounds(
    spec: Mapping[str, Any], made: Geometry | None = None
) -> tuple[float, float, float, float]:
    """``left, top, right, bottom`` of what a shape draws, turned as it is (its heads too)."""

    made = made or geometry(spec)
    if spec.get("kind") == "path" and made.segments:
        return _path_bounds(made)
    points: list[Point] = []
    for segments in [made.segments, *(head.segments for head in made.heads)]:
        for segment in segments:
            values = segment[1:]
            points.extend((values[index], values[index + 1]) for index in range(0, len(values), 2))
    if made.turn:
        points = [_turned(point, made.centre, made.turn) for point in points]
    if not points:
        x, y, w, h = made.box
        return (x, y, x + w, y + h)
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _path_bounds(made: Geometry) -> tuple[float, float, float, float]:
    """What a path draws: its curves' own reach, not their controls', turned as it is."""

    x, y, w, h = made.box
    if not made.turn and not made.heads:
        return (x, y, x + w, y + h)
    left, top, right, bottom = pathdata.extent(made.segments, made.turn, made.centre)
    for head in made.heads:
        for point in flattened(head.segments, 1):
            px, py = _turned(point, made.centre, made.turn)
            left, top = min(left, px), min(top, py)
            right, bottom = max(right, px), max(bottom, py)
    return (left, top, right, bottom)


def flattened(segments: Sequence[Segment], steps: int = 8) -> list[Point]:
    """A path as points, its curves cut into ``steps`` each."""

    out: list[Point] = []
    here: Point = (0.0, 0.0)
    for segment in segments:
        if segment[0] in ("M", "L"):
            here = (segment[1], segment[2])
            out.append(here)
        elif segment[0] == "C":
            p1, p2, p3 = (
                (segment[1], segment[2]),
                (segment[3], segment[4]),
                (segment[5], segment[6]),
            )
            out.extend(_cubic_at(here, p1, p2, p3, step / steps) for step in range(1, steps + 1))
            here = p3
    return out


# -- what a line's end is glued to --------------------------------------------------------


@dataclass(slots=True)
class Target:
    """What a line's end may be glued to: a box (unturned), how far it is turned, and its
    outline on the page (for an end at its centre to stop at), if it has one."""

    box: tuple[float, float, float, float]
    turn: float = 0.0
    outline: list[Point] | None = None
    traced: pathdata.Outline | None = None
    """A path's outline -- its rings, holes and all, and where a line meets it on each side --
    found from it when first asked."""


def target_of(spec: Mapping[str, Any], made: Geometry | None = None) -> Target:
    """A shape as something a line is glued to."""

    made = made or geometry(spec)
    if spec.get("kind") == "path":
        read = pathdata.parsed(str(spec["d"]))
        return Target(
            made.box, made.turn, None, pathdata.Outline(read, spec.get("flip"), made.turn)
        )
    outline = None
    if made.closed:
        outline = [_turned(point, made.centre, made.turn) for point in flattened(made.segments)]
    return Target(made.box, made.turn, outline)


def sites(target: Target) -> dict[str, Point]:
    """Where a line glued to ``target`` meets it, by side: its sides' middles and its centre
    (a path's on its outline, level with its middle)."""

    if target.traced is not None:
        return target.traced.sites()
    x, y, w, h = target.box
    centre = (x + w / 2.0, y + h / 2.0)
    places = {
        "top": (x + w / 2.0, y),
        "right": (x + w, y + h / 2.0),
        "bottom": (x + w / 2.0, y + h),
        "left": (x, y + h / 2.0),
        "centre": centre,
    }
    return {side: _turned(point, centre, target.turn) for side, point in places.items()}


def facing(target: Target, other: Point) -> str:
    """The side of ``target`` that faces ``other``, by where it is from its middle, its
    proportions taken into account (a wide box is met at its ends less often)."""

    x, y, w, h = target.box
    centre = (x + w / 2.0, y + h / 2.0)
    dx, dy = _unturned(other, centre, target.turn)
    dx, dy = dx - centre[0], dy - centre[1]
    if abs(dx) * max(h, 1e-9) >= abs(dy) * max(w, 1e-9):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def _met(outline: Sequence[Point], inside: Point, outside: Point) -> Point | None:
    """Where the segment from ``inside`` to ``outside`` last crosses ``outline``."""

    best: tuple[float, Point] | None = None
    ax, ay = inside
    bx, by = outside
    for (cx, cy), (dx, dy) in zip(outline, [*outline[1:], outline[0]], strict=True):
        denominator = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
        if abs(denominator) < 1e-12:
            continue
        t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denominator
        u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denominator
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 and (best is None or t > best[0]):
            best = (t, (ax + (bx - ax) * t, ay + (by - ay) * t))
    return best[1] if best else None


def glued(
    spec: Mapping[str, Any], find: Callable[[Mapping[str, Any]], Target | None]
) -> tuple[Point, Point]:
    """Where a line's ends are: each written point, or the place on what it is glued to that
    ``find`` gives (``None``, gone: where it was, its ``at``). An end at a centre stops at its
    outline, on the way to the other end."""

    ends = [spec["from"], spec["to"]]
    targets = [find(end) if isinstance(end, Mapping) else None for end in ends]
    points: list[Point] = []
    for end, target in zip(ends, targets, strict=True):
        if target is not None:
            points.append(sites(target)["centre"])
        elif isinstance(end, Mapping) and end.get("at") is None:
            points.append((math.nan, math.nan))
        else:
            points.append(_point_of(end))
    # (An end glued to what is not there, with no place of its own kept: at the other end.)
    for index in (0, 1):
        if math.isnan(points[index][0]):
            other = points[1 - index]
            points[index] = (0.0, 0.0) if math.isnan(other[0]) else other
    for _ in range(2):
        for index, (end, target) in enumerate(zip(ends, targets, strict=True)):
            if target is None:
                continue
            other = points[1 - index]
            side = end.get("side") or facing(target, other)  # type: ignore[union-attr]
            if side == "centre" and target.traced is not None:
                centre = sites(target)["centre"]
                met = pathdata.crossing(target.traced.rings(), centre, other)
                points[index] = met or centre
            elif side == "centre":
                centre = sites(target)["centre"]
                outline = target.outline or [
                    _turned(p, centre, target.turn)
                    for p in (
                        (target.box[0], target.box[1]),
                        (target.box[0] + target.box[2], target.box[1]),
                        (target.box[0] + target.box[2], target.box[1] + target.box[3]),
                        (target.box[0], target.box[1] + target.box[3]),
                    )
                ]
                points[index] = _met(outline, centre, other) or centre
            else:
                points[index] = sites(target)[side]
    return points[0], points[1]


# -- painting -----------------------------------------------------------------------------


def paint(value: object, palette: object) -> tuple[str | None, str | None]:
    """A colour as written, painted with ``palette`` (a flexo ``Palette``): the colour, and
    the palette role that names it (``None`` for one written as #rrggbb, or none)."""

    if value is None or value == "none":
        return None, None
    text = str(value)
    if text.startswith("#"):
        return text, None
    role = role_of(text)
    return palette.get(role), role  # type: ignore[attr-defined]


def dash_array(spec: Mapping[str, Any]) -> tuple[float, ...]:
    """A line's dashes as drawn: a dash four widths long and three apart, a dot one and two
    apart -- what shows, a round or square cap's reach included."""

    dash = spec.get("dash") or "solid"
    if dash == "solid":
        return ()
    width = max(float(spec.get("line_width") or 0.0), 0.1)
    on, off = (4.0, 3.0) if dash == "dashed" else (1.0, 2.0)
    if spec.get("cap") in ("round", "square"):
        on, off = max(on - 1.0, 0.0), off + 1.0
    return (on * width, off * width)


@dataclass(slots=True)
class Shadow:
    """The theme's drop shadow: how far it falls (down and right), how far it spreads, how
    dark it is, and whether it is soft or a hard slab."""

    offset: float = 2.5
    spread: float = 2.0
    opacity: float = 0.18
    style: str = "soft"


def draw(
    parent: ET.Element,
    spec: Mapping[str, Any],
    made: Geometry,
    ident: str,
    palette: object,
    shadow: Shadow | None = None,
) -> ET.Element:
    """A shape drawn into ``parent``: a group (turned, as it is) holding its shadow, its
    outline and its heads, painted with ``palette``; its words are its writer's to set
    (``made.area``, ``made.label``)."""

    spec = normalised(spec)
    group = element(parent, "g", id=ident)
    if made.turn:
        cx, cy = made.centre
        group.set("transform", f"rotate({number(made.turn)} {number(cx)} {number(cy)})")
    if float(spec.get("opacity", 1.0)) < 1.0:
        group.set("opacity", number(float(spec["opacity"])))
    if spec.get("kind") == "path" and spec.get("fill_rule") == "evenodd":
        # (On the group, so its shadow is filled as it is.)
        group.set("fill-rule", "evenodd")
    fill, fill_role = paint(spec.get("fill"), palette)
    stroke, stroke_role = paint(spec.get("line"), palette)
    width = float(spec.get("line_width") or 0.0)
    if width <= 0.0:
        stroke = None
    if not made.closed:
        fill = None
    if spec.get("shadow") and shadow is not None and (fill or stroke):
        _shadow(group, ident, made, fill is not None, width if stroke else 0.0, palette, shadow)
    attributes: dict[str, object] = {"fill": fill or "none"}
    if fill_role and fill:
        attributes["data__flexo__fill"] = fill_role
    if fill and float(spec.get("fill_opacity", 1.0)) < 1.0:
        attributes["fill_opacity"] = float(spec["fill_opacity"])
    if stroke:
        attributes |= {
            "stroke": stroke,
            "stroke_width": width,
            "stroke_linecap": spec.get("cap") or "butt",
            "stroke_linejoin": spec.get("join") or "miter",
        }
        if stroke_role:
            attributes["data__flexo__stroke"] = stroke_role
        dashes = dash_array(spec)
        if dashes:
            attributes["stroke_dasharray"] = " ".join(number(value) for value in dashes)
    if made.segments and (fill or stroke):
        element(
            group,
            "path",
            id=f"{ident}.outline",
            d=made.data or path_data(made.segments),
            **attributes,
        )
    for head in made.heads:
        if not stroke:
            continue
        paint_of: dict[str, object] = {"fill": stroke if head.filled else "none"}
        if head.stroked:
            paint_of |= {
                "stroke": stroke,
                "stroke_width": width,
                "stroke_linecap": "round" if head.kind == "open" else "butt",
                "stroke_linejoin": "round",
            }
        if stroke_role:
            paint_of["data__flexo__" + ("fill" if head.filled else "stroke")] = stroke_role
        element(
            group, "path", id=f"{ident}.head-{head.end}", d=path_data(head.segments), **paint_of
        )
    return group


def _shadow(
    group: ET.Element,
    ident: str,
    made: Geometry,
    filled: bool,
    width: float,
    palette: object,
    shadow: Shadow,
) -> None:
    """The theme's shadow under a shape: its outline again, down and to the right, in layers
    each reaching a little less far (a soft shadow), or once (a hard one) -- as a figure's
    shadows are drawn, from vector shapes, never a filter."""

    colour = palette.get("shadow")  # type: ignore[attr-defined]
    held = element(group, "g", id=f"{ident}.shadow")
    data = made.data or path_data(made.segments)
    if shadow.style == "hard" or shadow.spread <= 0.0:
        element(
            held,
            "path",
            d=data,
            transform=f"translate({number(shadow.offset)} {number(shadow.offset)})",
            fill=colour if filled else "none",
            stroke=colour if width else ("none" if filled else colour),
            stroke_width=max(width, 0.0) or None,
            stroke_linejoin="round",
            opacity=min(1.0, shadow.opacity),
            data__flexo__fill="shadow",
        )
        return
    layers = 5
    offset = max(shadow.offset, shadow.spread)
    alpha = 1.0 - (1.0 - shadow.opacity) ** (1.0 / layers)
    for index in range(layers):
        reach = shadow.spread * (layers - index) / layers
        element(
            held,
            "path",
            d=data,
            transform=f"translate({number(offset)} {number(offset)})",
            fill=colour if filled else "none",
            stroke=colour,
            stroke_width=width + 2.0 * reach,
            stroke_linejoin="round",
            stroke_linecap="round",
            opacity=alpha,
            data__flexo__fill="shadow",
        )


# -- moving and sizing (as an editor does) --------------------------------------------------


def moved(spec: Mapping[str, Any], dx: float, dy: float) -> dict[str, Any]:
    """A shape moved by ``dx``, ``dy``: its box, its points, its tail, a path's outline
    (written again, ``flexo.pathdata``); glued ends stay glued."""

    made = dict(spec)
    if made.get("kind") == "group":
        made["shapes"] = [moved(child, dx, dy) for child in made.get("shapes") or []]
        return made
    for key in ("at", "tail"):
        if made.get(key) is not None:
            made[key] = [made[key][0] + dx, made[key][1] + dy]
    for key in ("from", "to"):
        end = made.get(key)
        if isinstance(end, Mapping):
            if end.get("at") is not None:
                made[key] = {**end, "at": [end["at"][0] + dx, end["at"][1] + dy]}
        elif end is not None:
            made[key] = [end[0] + dx, end[1] + dy]
    if made.get("points") is not None:
        made["points"] = [[x + dx, y + dy] for x, y in made["points"]]
    if made.get("kind") == "path" and isinstance(made.get("d"), str) and (dx or dy):
        made["d"] = pathdata.moved(made["d"], dx, dy)
    return made


__all__ = [
    "BOXED",
    "HEADS",
    "KINDS",
    "LABELS",
    "LINES",
    "SECTIONS",
    "SIZES",
    "TRACED",
    "Geometry",
    "Head",
    "Label",
    "Shadow",
    "ShapeError",
    "Target",
    "bounds",
    "catalogue",
    "checked",
    "closed",
    "colour_of",
    "corners",
    "dash_array",
    "defaults",
    "draw",
    "facing",
    "family",
    "flattened",
    "geometry",
    "glued",
    "head_size",
    "keys_of",
    "moved",
    "normalised",
    "paint",
    "path_data",
    "path_open",
    "role_of",
    "sites",
    "target_of",
]


def catalogue() -> dict[str, Any]:
    """The vocabulary as an editor shows it: the kinds by section with their names, the
    sizes a click makes them, the heads, dashes and the rest of what may be chosen."""

    return {
        "sections": [{"name": name, "kinds": list(kinds)} for name, kinds in SECTIONS],
        "labels": dict(LABELS),
        "tools": dict(TOOLS),
        "families": {kind: family(kind) for kind in (*KINDS, "group")},
        "defaults": {kind: defaults(kind) for kind in KINDS},
        "sizes": {kind: list(size) for kind, size in SIZES.items()},
        "heads": list(HEADS),
        "dashes": list(DASHES),
        "caps": list(CAPS),
        "joins": list(JOINS),
    }
