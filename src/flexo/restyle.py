"""An SVG picture's words and colours, restyled where it is placed -- never in its file.

A drawing made in another program (Inkscape, Illustrator) names the fonts it was drawn
in, and each program that draws it afterwards finds whatever it has of them: the page a
slide is edited on, a picture's thumbnail, the PNG, the PDF and the PowerPoint each fell
back to a face of its own, and words ran past the drawing or were cut off by it. Here a
picture's words are set in a font Flexo has, named outright on every text, so that every
output draws the same face from the same file Flexo measured:

- by default the figure's font (on a slide, the deck's figure font);
- ``font: drawn``, the faces the file names, each found as Flexo finds any family
  (bundled, installed or registered) and Flexo's fallback face where none is;
- or a family by name.

What a person changes of a drawing -- a text's words, size, bold, italic and colour, and
any colour it is painted in, every use of it at once -- is kept beside the picture, in
the figure or the deck, keyed to the drawing's own elements (``Restyle``): a text by the
id its program gave it, or one without an id by its place among the file's texts
(``text: 3``). It is applied as the picture is drawn, so the file stays its program's and
opens there as it was; a change to a text the file no longer has is passed over.

Where the words set so reach past the drawing's page, the picture grows to hold them, so
nothing is cut off or overhangs its box. Text keeps its place, size and anchor as drawn.
"""

from __future__ import annotations

import copy
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from flexo.artwork import Artwork
from flexo.fonts import FontFace, css_family_list, family_faces
from flexo.svg import local_name, number, svg_tag
from flexo.text import DEFAULT_FALLBACKS

ET.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")

AS_DRAWN = "drawn"
"""A picture's ``font`` that keeps the faces its file names."""

SODIPODI_ROLE = "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}role"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

GENERIC_FACES = {
    "sans-serif": "IBM Plex Sans",
    "serif": "Latin Modern Roman",
    "monospace": "IBM Plex Mono",
    "cursive": "Kalam",
    "fantasy": "IBM Plex Sans",
    "system-ui": "IBM Plex Sans",
}
"""The bundled face a generic family is drawn in: the same on every machine."""

DEFAULT_SIZE = 16.0
"""A text's size where its file gives none: what every browser draws it at."""

_UNDRAWN = frozenset({"defs", "clipPath", "mask", "marker", "pattern", "symbol"})
_PAINTS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color")
_SHAPES = frozenset({"rect", "circle", "ellipse", "path", "polygon", "polyline", "text"})
_CHANGED = ("font-family", "font-size", "font-weight", "font-style", "fill")


@dataclass(frozen=True, slots=True)
class TextChange:
    """What is changed of one of a drawing's texts: each ``None`` left as drawn."""

    id: str | None = None
    """The text's id in the file, as its program wrote it."""
    number: int | None = None
    """For a text without an id: its place among the file's texts, from 1."""
    words: str | None = None
    """Its words, its lines parted by ``\\n``."""
    size: float | None = None
    """Its size in points, at the drawing's own size: its first words', the rest in step."""
    bold: bool | None = None
    italic: bool | None = None
    colour: str | None = None

    def record(self) -> dict[str, Any]:
        """As a document writes it: its key, then what is changed."""

        key = {"id": self.id} if self.id is not None else {"text": self.number}
        said = {"words": self.words, "size": self.size, "bold": self.bold, "italic": self.italic,
                "colour": self.colour}
        return {**key, **{name: value for name, value in said.items() if value is not None}}


@dataclass(frozen=True, slots=True)
class Restyle:
    """How a picture's words and colours are drawn: its ``font`` (``None`` for the
    figure's, ``AS_DRAWN``, or a family), changes to its texts, and its colours swapped
    (``#rrggbb`` as drawn, ``#rrggbb`` drawn instead)."""

    font: str | None = None
    texts: tuple[TextChange, ...] = ()
    colours: tuple[tuple[str, str], ...] = ()


def restyle_of(font: object = None, texts: object = None, colours: object = None) -> Restyle:
    """A picture's ``font``, ``texts`` and ``colours`` as a document writes them (a deck's
    image, a figure's image node's properties), read; ``ValueError`` for what does not
    read, saying which."""

    if font is not None and (not isinstance(font, str)):
        raise ValueError(f"font must be a family's name, or {AS_DRAWN}, not {font!r}")
    font = (font or "").strip() or None
    listed = "texts must be a list of changes, each {id, words, size, bold, italic, colour}"
    if texts is not None and not isinstance(texts, list | tuple):
        raise ValueError(listed)
    changes: list[TextChange] = []
    for item in texts or ():
        entry = item.as_dict() if hasattr(item, "as_dict") else item
        if not isinstance(entry, Mapping):
            raise ValueError(listed)
        changes.append(_change(entry))
    pairs = colours.as_dict() if hasattr(colours, "as_dict") else colours
    if pairs is not None and not isinstance(pairs, Mapping):
        raise ValueError(
            'colours must map a colour drawn to the colour drawn instead: {"#4a90d9": "#2e7d32"}'
        )
    swapped: list[tuple[str, str]] = []
    for was, now in (pairs or {}).items():
        key, given = colour_key(str(was)), colour_key(str(now)) if isinstance(now, str) else None
        if key is None or given is None:
            raise ValueError(
                f"colours: {was!r} to {now!r} is not a colour to a colour, such as #4a90d9"
            )
        if key != given:
            swapped.append((key, given))
    return Restyle(font, tuple(changes), tuple(swapped))


def _change(entry: Mapping[str, Any]) -> TextChange:
    known = {"id", "text", "words", "size", "bold", "italic", "colour"}
    unknown = sorted(set(entry) - known)
    if unknown:
        raise ValueError(
            f"texts: unknown {', '.join(unknown)} (each takes {', '.join(sorted(known))})"
        )
    identifier, place = entry.get("id"), entry.get("text")
    if identifier is not None and not isinstance(identifier, str | int):
        raise ValueError(f"texts: id must be a text's id, not {identifier!r}")
    if identifier is None and (isinstance(place, bool) or not isinstance(place, int) or place < 1):
        raise ValueError(
            "texts: each names its text, by id (text1) or, with none, by place (text: 3)"
        )
    words = entry.get("words")
    if words is not None and not isinstance(words, str | int | float):
        raise ValueError(f"texts: words must be text, not {words!r}")
    size = entry.get("size")
    points = isinstance(size, int | float) and not isinstance(size, bool)
    if size is not None and (not points or not 0.5 <= size <= 2000):
        raise ValueError(f"texts: size must be points, such as 12, not {size!r}")
    for name in ("bold", "italic"):
        if entry.get(name) is not None and not isinstance(entry.get(name), bool):
            raise ValueError(f"texts: {name} must be true or false, not {entry.get(name)!r}")
    colour = entry.get("colour")
    if colour is not None and colour_key(str(colour)) is None:
        raise ValueError(f"texts: colour must be a colour such as #c0392b, not {colour!r}")
    return TextChange(
        str(identifier) if identifier is not None else None,
        None if identifier is not None else int(place),
        # (A file's writer may end words over several lines with a line break: no line more.)
        None if words is None else str(words).rstrip("\n"),
        None if size is None else float(size),
        entry.get("bold"),
        entry.get("italic"),
        None if colour is None else colour_key(str(colour)),
    )


# -- colours ------------------------------------------------------------------------------

_NAMED = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000",
    "navy": "#000080", "teal": "#008080", "olive": "#808000", "lime": "#00ff00",
    "aqua": "#00ffff", "cyan": "#00ffff", "fuchsia": "#ff00ff", "magenta": "#ff00ff",
    "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9", "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3", "dimgray": "#696969", "dimgrey": "#696969", "brown": "#a52a2a",
    "pink": "#ffc0cb", "gold": "#ffd700", "indigo": "#4b0082", "violet": "#ee82ee",
    "crimson": "#dc143c", "coral": "#ff7f50", "tomato": "#ff6347", "steelblue": "#4682b4",
    "darkblue": "#00008b", "darkred": "#8b0000", "darkgreen": "#006400",
    "lightblue": "#add8e6", "skyblue": "#87ceeb", "royalblue": "#4169e1",
    "forestgreen": "#228b22", "seagreen": "#2e8b57", "salmon": "#fa8072",
    "orangered": "#ff4500", "slategray": "#708090", "slategrey": "#708090",
    "whitesmoke": "#f5f5f5", "gainsboro": "#dcdcdc", "beige": "#f5f5dc", "ivory": "#fffff0",
}
"""CSS's colour names a drawing may paint in (the rest are left as they are)."""

_HEX_DIGITS = frozenset("0123456789abcdef")


def colour_key(value: str) -> str | None:
    """A colour as ``#rrggbb``, however it is written (``#abc``, ``rgb(...)``, a name);
    ``None`` for no colour of its own (``none``, a gradient, ``currentColor``)."""

    text = value.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if not digits or not _HEX_DIGITS.issuperset(digits):
            return None
        if len(digits) in (3, 4):
            return "#" + "".join(digit * 2 for digit in digits[:3])
        if len(digits) in (6, 8):
            return "#" + digits[:6]
        return None
    found = re.fullmatch(
        r"rgba?\(\s*([\d.]+%?)[\s,]+([\d.]+%?)[\s,]+([\d.]+%?)(?:[\s,/]+[\d.]+%?)?\s*\)", text
    )
    if found:
        channels = []
        for part in found.groups():
            amount = float(part[:-1]) * 2.55 if part.endswith("%") else float(part)
            channels.append(max(0, min(255, round(amount))))
        return "#" + "".join(f"{channel:02x}" for channel in channels)
    return _NAMED.get(text)


def _swap(value: str, swaps: Mapping[str, str]) -> str | None:
    """``value`` (a paint) drawn instead in its swap, or None should it have none."""

    key = colour_key(value)
    return swaps.get(key) if key is not None else None


_CSS_PAINT = re.compile(r"((?:^|[;{\s])(?:fill|stroke|stop-color)\s*:\s*)([^;}!]+)", re.IGNORECASE)


def _recoloured(root: ET.Element, swaps: Mapping[str, str]) -> None:
    """Every paint in ``swaps`` drawn in its swap: in attributes, styles and stylesheets --
    and black, where the file leaves a fill to be black by default."""

    for item in root.iter():
        for name in _PAINTS:
            value = item.get(name)
            if value is not None and _swap(value, swaps):
                item.set(name, _swap(value, swaps))  # type: ignore[arg-type]
        pairs = _style(item)
        if any(name in _PAINTS and _swap(value, swaps) for name, value in pairs):
            _set_style(item, [(name, (_swap(value, swaps) or value) if name in _PAINTS else value)
                              for name, value in pairs])
        if local_name(item.tag) == "style" and item.text:
            item.text = _CSS_PAINT.sub(
                lambda found: found.group(1) + (_swap(found.group(2), swaps) or found.group(2)),
                item.text,
            )
    black = swaps.get("#000000")
    if black and _black_by_default(root):
        # Drawn black as nothing paints it: what it is drawn in is said where it starts.
        for child in root:
            drawn = local_name(child.tag) in {"g", "a", "switch", "use", "svg", *_SHAPES}
            if drawn and _declared(child, "fill") is None:
                _declare(child, "fill", black)


def _black_by_default(root: ET.Element) -> bool:
    """Whether a shape or a text of the drawing is drawn black because nothing paints it."""

    if root.get("fill") is not None or _declared(root, "fill") is not None:
        return False
    if any(local_name(item.tag) == "style" and "fill" in (item.text or "") for item in root.iter()):
        return False  # (its stylesheet may paint it: what it says is not read)

    def walk(item: ET.Element) -> bool:
        tag = local_name(item.tag)
        if tag in _UNDRAWN or _declared(item, "fill") is not None:
            return False
        return tag in _SHAPES or any(walk(child) for child in item)

    return any(walk(child) for child in root)


def colours_of(root: ET.Element) -> list[dict[str, Any]]:
    """Every colour the drawing paints in, in the order the file first uses each: as a
    fill (a gradient's stops among them) or an outline, or both."""

    found: dict[str, dict[str, Any]] = {}

    def use(value: str | None, how: str) -> None:
        key = colour_key(value) if value else None
        if key is None:
            return
        entry = found.setdefault(key, {"colour": key, "fill": False, "outline": False})
        entry[how] = True

    for item in root.iter():
        for name in _PAINTS[:3]:
            how = "outline" if name == "stroke" else "fill"
            use(item.get(name), how)
            for declared, value in _style(item):
                if declared == name:
                    use(value, how)
        if local_name(item.tag) == "style" and item.text:
            for found_paint in _CSS_PAINT.finditer(item.text):
                name = found_paint.group(1).strip(" ;{\t\n").split(":")[0].strip().lower()
                use(found_paint.group(2), "outline" if name == "stroke" else "fill")
    if _black_by_default(root):
        use("#000000", "fill")
    return list(found.values())


# -- styles -------------------------------------------------------------------------------


def _style(item: ET.Element) -> list[tuple[str, str]]:
    pairs = []
    for declaration in (item.get("style") or "").split(";"):
        name, colon, value = declaration.partition(":")
        if colon and name.strip() and value.strip():
            pairs.append((name.strip().lower(), value.strip()))
    return pairs


def _set_style(item: ET.Element, pairs: Iterable[tuple[str, str]]) -> None:
    said = ";".join(f"{name}:{value}" for name, value in pairs)
    if said:
        item.set("style", said)
    else:
        item.attrib.pop("style", None)


def _declared(item: ET.Element, name: str) -> str | None:
    """What ``item`` itself says of ``name``: its style over its attribute (a ``font``
    shorthand saying a family too)."""

    for declared, value in reversed(_style(item)):
        if declared == name:
            return value
        if declared == "font" and name == "font-family":
            found = re.search(r"[\d.]+(?:px|pt|em|%)?(?:\s*/\s*\S+)?\s+(.+)$", value)
            if found:
                return found.group(1)
    return item.get(name)


def _declare(item: ET.Element, name: str, value: str) -> None:
    """``item`` says ``name`` is ``value``, in its style (where it beats a stylesheet)."""

    kept = [(declared, said) for declared, said in _style(item) if declared != name]
    _set_style(item, [*kept, (name, value)])
    item.attrib.pop(name, None)


def _undeclare(item: ET.Element, name: str) -> None:
    pairs = _style(item)
    kept = [(declared, value) for declared, value in pairs if declared != name]
    if len(kept) != len(pairs):
        _set_style(item, kept)
    item.attrib.pop(name, None)


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _inherited(item: ET.Element, name: str, parents: Mapping[ET.Element, ET.Element]) -> str | None:
    at: ET.Element | None = item
    while at is not None:
        value = _declared(at, name)
        if value is not None and value.strip().lower() != "inherit":
            return value
        at = parents.get(at)
    return None


# -- fonts --------------------------------------------------------------------------------


def drawn_family(names: str | None) -> str:
    """The family a CSS ``font-family`` list is drawn in, the same in every output: the
    first of its families Flexo finds (bundled, registered or installed), a generic one's
    bundled face, else Flexo's fallback face."""

    for name in re.split(r",", names or ""):
        name = name.strip().strip("'\"").strip()
        if not name:
            continue
        if name.lower() in GENERIC_FACES:
            return GENERIC_FACES[name.lower()]
        faces = family_faces(name)
        if faces:
            return faces[0].family
    return DEFAULT_FALLBACKS[0]


@lru_cache(maxsize=64)
def _family_value(family: str) -> str:
    """``font-family`` naming ``family``, then Flexo's fallbacks as Flexo falls back for a
    character it lacks: a browser draws what it lacks from the same faces."""

    return css_family_list([family, *DEFAULT_FALLBACKS], generic="")


_CSS_FAMILY = re.compile(r"(font-family\s*:\s*)([^;}]+)", re.IGNORECASE)


def _set_fonts(root: ET.Element, texts: list[ET.Element], font: str | None, family: str,
               parents: Mapping[ET.Element, ET.Element]) -> None:
    """Every text's words in one family Flexo has, named on it and on each of its pieces
    that names one (or may, by a stylesheet's class): ``family`` (the figure's), a family
    named, or -- ``AS_DRAWN`` -- each in the family it names, as found."""

    drawn = font == AS_DRAWN

    def chosen(names: str | None) -> str:
        return drawn_family(names) if drawn else drawn_family(font or family)

    sized = not any(
        local_name(item.tag) == "style" and re.search(r"\bfont(-size)?\s*:", item.text or "")
        for item in root.iter()
    )
    for text in texts:
        named = _inherited(text, "font-family", parents)
        _declare(text, "font-family", _family_value(chosen(named)))
        for piece in text.iter():
            own = _declared(piece, "font-family")
            if piece is not text and (own is not None or piece.get("class")):
                _declare(piece, "font-family", _family_value(chosen(own)))
            # (Inkscape's own name for the face it drew, which it would show over this one.)
            _undeclare(piece, "-inkscape-font-specification")
        if sized and _inherited(text, "font-size", parents) is None:
            # As every browser draws it: Flexo's outputs too.
            _declare(text, "font-size", number(DEFAULT_SIZE))
    for item in root.iter():
        if local_name(item.tag) == "style" and item.text and "font-family" in item.text:
            item.text = _CSS_FAMILY.sub(
                lambda found: found.group(1) + _family_value(chosen(found.group(2))), item.text
            )


# -- texts --------------------------------------------------------------------------------


def _texts(root: ET.Element) -> list[ET.Element]:
    """The file's texts, in the order it writes them: their places (``text: 3``)."""

    return [item for item in root.iter() if local_name(item.tag) == "text"]


def _key(text: ET.Element, place: int, prefix: str) -> dict[str, Any]:
    identifier = text.get("id")
    if identifier:
        return {"id": identifier.removeprefix(prefix)}
    return {"text": place}


def _changed(change: TextChange, text: ET.Element, place: int, prefix: str) -> bool:
    if change.id is not None:
        return text.get("id") in {change.id, f"{prefix}{change.id}"}
    return change.number == place and not text.get("id")


def _preserved(text: ET.Element) -> bool:
    return text.get(XML_SPACE) == "preserve"


def _line_holders(text: ET.Element) -> list[ET.Element] | None:
    """The pieces that each hold one of a text's lines (Inkscape's lines, a piece placed
    anew under the one before) -- or None: the text is one line, held in itself."""

    pieces = [child for child in text if local_name(child.tag) == "tspan"]
    loose = (text.text or "").strip() or any((piece.tail or "").strip() for piece in pieces)
    if not pieces or loose:
        return None
    if len(pieces) != len(text):
        return None

    def starts(index: int, piece: ET.Element) -> bool:
        if piece.get(SODIPODI_ROLE) == "line":
            return True
        placed = piece.get("x") is not None
        return placed and (index == 0 or piece.get("y") is not None or piece.get("dy") is not None)

    if not all(starts(index, piece) for index, piece in enumerate(pieces)):
        return None
    return pieces


def _words(holder: ET.Element, preserved: bool) -> str:
    words = "".join(holder.itertext())
    return words if preserved else " ".join(words.split())


def lines_of(text: ET.Element) -> list[str]:
    """A text's words, a line each, as it is drawn."""

    holders = _line_holders(text)
    preserved = _preserved(text)
    if holders is None:
        return [_words(text, preserved)]
    return [_words(holder, preserved) for holder in holders]


def _hoist(holder: ET.Element) -> None:
    """The look of a holder's first words (an inner piece's face, size, weight, colour)
    made the holder's own, before its pieces go."""

    pieces = (piece for piece in holder.iter() if piece is not holder)
    first = next((piece for piece in pieces if (piece.text or "").strip()), None)
    if first is None:
        return
    chain = []
    at: ET.Element | None = first
    parents = _parents(holder)
    while at is not None and at is not holder:
        chain.append(at)
        at = parents.get(at)
    for piece in reversed(chain):
        for name in _CHANGED:
            value = _declared(piece, name)
            if value is not None:
                _declare(holder, name, value)


def _put_words(holder: ET.Element, words: str) -> None:
    _hoist(holder)
    for child in list(holder):
        holder.remove(child)
    holder.text = words


def _numbers(value: str | None) -> list[float]:
    return [float(part) for part in re.split(r"[\s,]+", (value or "").strip()) if part]


def _set_words(text: ET.Element, words: str, size: float) -> None:
    """``text`` saying ``words``, a line each: lines kept where they are, one more put a
    line's step under the last, one fewer taken from the end."""

    wanted = words.split("\n")
    if lines_of(text) == wanted:
        return
    holders = _line_holders(text)
    if holders is None:
        if len(wanted) == 1:
            alone = len(text) == 1 and local_name(text[0].tag) == "tspan"
            if alone and not (text.text or "").strip() and not (text[0].tail or "").strip():
                _put_words(text[0], wanted[0])  # its words in one piece, kept with its look
            else:
                _put_words(text, wanted[0])
            return
        # One line set in itself: made lines, Inkscape's way, from where it was.
        _hoist(text)
        x, y = text.get("x", "0"), text.get("y", "0")
        for child in list(text):
            text.remove(child)
        text.text = None
        first = ET.SubElement(text, svg_tag("tspan"), {"x": _first(x), "y": _first(y)})
        first.set(SODIPODI_ROLE, "line")
        holders = [first]
    step = _step(holders, size, text)
    for index, line in enumerate(wanted):
        if index < len(holders):
            if _words(holders[index], _preserved(text)) != line:
                _put_words(holders[index], line)
            continue
        last = holders[-1]
        made = copy.deepcopy(last)
        made.attrib.pop("id", None)
        for inner in made.iter():
            inner.attrib.pop("id", None)
        ys = _numbers(last.get("y"))
        if ys:
            made.set("y", number(ys[0] + step))
            made.attrib.pop("dy", None)
        else:
            made.set("dy", number(step))
        _put_words(made, line)
        text.append(made)
        holders.append(made)
    for extra in holders[len(wanted):]:
        text.remove(extra)


def _first(value: str) -> str:
    numbers = _numbers(value)
    return number(numbers[0]) if numbers else "0"


def _step(holders: list[ET.Element], size: float, text: ET.Element) -> float:
    """How far apart the text's lines are: as its lines stand, else its line height."""

    ys = [(_numbers(holder.get("y")) or [None])[0] for holder in holders]
    if len(ys) >= 2 and ys[-1] is not None and ys[-2] is not None and ys[-1] != ys[-2]:
        return ys[-1] - ys[-2]  # type: ignore[operator]
    if len(holders) >= 2 and _numbers(holders[-1].get("dy")):
        return _numbers(holders[-1].get("dy"))[0]
    height = _declared(text, "line-height") or "1.25"
    found = re.fullmatch(r"\s*([\d.]+)\s*(%)?\s*", height)
    share = float(found.group(1)) / (100.0 if found.group(2) else 1.0) if found else 1.25
    return size * share


_LENGTH = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(px|pt|mm|cm|in|pc)?\s*$")
_USER_UNITS = {
    "px": 1.0, None: 1.0, "pt": 4.0 / 3.0, "pc": 16.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54,
    "in": 96.0,
}


def _size_of(item: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> float:
    """``item``'s font size in user units, as it inherits it."""

    value = _declared(item, "font-size")
    parent = parents.get(item)
    above = _size_of(parent, parents) if parent is not None else DEFAULT_SIZE
    if value is None or value.strip().lower() == "inherit":
        return above
    found = _LENGTH.match(value)
    if found:
        return float(found.group(1)) * _USER_UNITS[found.group(2)]
    relative = re.fullmatch(r"\s*([\d.]+)\s*(em|%)\s*", value)
    if relative:
        return above * float(relative.group(1)) / (100.0 if relative.group(2) == "%" else 1.0)
    return above


def _scaled(value: str, ratio: float) -> str | None:
    found = _LENGTH.match(value)
    if not found:
        return None
    return f"{number(float(found.group(1)) * ratio)}{found.group(2) or ''}"


def _resize(text: ET.Element, ratio: float, parents: Mapping[ET.Element, ET.Element]) -> None:
    """``text`` ``ratio`` times as large, about its first line: each piece's size, and how
    far its lines and raised pieces stand from the first."""

    if abs(ratio - 1.0) < 1e-9:
        return
    own = _declared(text, "font-size")
    if own is None or _scaled(own, ratio) is None:
        _declare(text, "font-size", number(_size_of(text, parents) * ratio))
    else:
        _declare(text, "font-size", _scaled(own, ratio))  # type: ignore[arg-type]
    for piece in text.iter():
        if piece is text:
            continue
        value = _declared(piece, "font-size")
        if value is not None and _scaled(value, ratio) is not None:
            _declare(piece, "font-size", _scaled(value, ratio))  # type: ignore[arg-type]
    holders = _line_holders(text) or []
    first_y = (_numbers(holders[0].get("y")) or _numbers(text.get("y"))) if holders else []
    origin = (first_y or [0.0])[0]
    for piece in text.iter():
        if piece is text:
            continue
        for name in ("dx", "dy"):
            if piece.get(name) is not None:
                steps = _numbers(piece.get(name))
                piece.set(name, " ".join(number(value * ratio) for value in steps))
        if piece in holders and piece.get("y") is not None:
            ys = _numbers(piece.get("y"))
            piece.set("y", " ".join(number(origin + (value - origin) * ratio) for value in ys))


def _own(text: ET.Element, name: str, value: str) -> None:
    """``text`` all in ``value`` (a weight, a slant, a colour): said on it, and taken off
    its pieces -- said on any a stylesheet may style otherwise."""

    _declare(text, name, value)
    for piece in text.iter():
        if piece is text:
            continue
        if piece.get("class"):
            _declare(piece, name, value)
        else:
            _undeclare(piece, name)


# -- restyling ----------------------------------------------------------------------------


def points_per_unit(artwork: Artwork, root: ET.Element | None = None) -> float:
    """How many points a unit of the drawing is, at its own size."""

    root = root if root is not None else ET.fromstring(artwork.markup)
    view = _numbers(root.get("viewBox"))
    if artwork.width and len(view) == 4 and view[2] > 0:
        return artwork.width / view[2]
    return 0.75


def restyled(artwork: Artwork, restyle: Restyle, family: str, *, embed: bool = False,
             shared: str | None = None) -> Artwork:
    """``artwork`` (an SVG) as it is drawn restyled -- in a font Flexo has, its texts and
    colours changed -- and grown to hold its words. ``family`` is the figure's font (a
    slide's: the deck's figure font). ``embed`` carries the bundled faces its words are
    drawn in, cut to the characters they use, for a picture drawn where the page's fonts
    are not (an ``<img>``, an export's picture, a viewer of the SVG) -- but ``shared``,
    a family the drawing round it carries already. A PNG or JPEG is as it is."""

    if artwork.format != "svg" or artwork.path.suffix.lower() != ".svg":
        return artwork  # (a PDF's page is drawn as its own vectors, its words among them)
    return _restyled(artwork, restyle, family, embed, shared)


@lru_cache(maxsize=64)
def _restyled(
    artwork: Artwork, restyle: Restyle, family: str, embed: bool, shared: str | None
) -> Artwork:
    root = ET.fromstring(artwork.markup)
    texts = _texts(root)
    swaps = dict(restyle.colours)
    if not texts and not swaps:
        return artwork
    parents = _parents(root)
    if swaps:
        _recoloured(root, swaps)
    _set_fonts(root, texts, restyle.font, family, parents)
    scale = points_per_unit(artwork, root)
    prefix = f"{artwork.node_id}."
    for place, text in enumerate(texts, start=1):
        for change in restyle.texts:
            if _changed(change, text, place, prefix):
                _apply(text, change, scale, _parents(root))
    width, height = artwork.width, artwork.height
    grown = _grown(root)
    if grown is not None:
        width, height = _grow(root, grown, width, height)
    if embed:
        _embed(root, shared)
    markup = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return replace(artwork, markup=markup, width=width, height=height)


def _apply(
    text: ET.Element, change: TextChange, scale: float, parents: Mapping[ET.Element, ET.Element]
) -> None:
    size = _size_of(_first_piece(text), parents)
    drawn = size * _magnified(text, parents)
    if change.words is not None:
        _set_words(text, change.words, size)
        parents = _parents(_root_of(text, parents))
    if change.size is not None and drawn > 0:
        _resize(text, change.size / scale / drawn, parents)
    if change.bold is not None:
        _own(text, "font-weight", "bold" if change.bold else "normal")
    if change.italic is not None:
        _own(text, "font-style", "italic" if change.italic else "normal")
    if change.colour is not None:
        _own(text, "fill", change.colour)


def _magnified(item: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> float:
    """How much larger ``item`` is drawn than its own units say: its transforms' and its
    groups', together (a size is shown as drawn)."""

    from flexo.drawing import _parse_transform

    scale = 1.0
    at: ET.Element | None = item
    while at is not None:
        try:
            a, b, c, d, _, _ = _parse_transform(at.get("transform"))
        except (ValueError, IndexError):
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
        scale *= math.sqrt(abs(a * d - b * c)) or 1.0
        at = parents.get(at)
    return scale


def _root_of(item: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> ET.Element:
    while item in parents:
        item = parents[item]
    return item


def _first_piece(text: ET.Element) -> ET.Element:
    """The piece holding a text's first words: whose size it is said to be."""

    return next((piece for piece in text.iter() if (piece.text or "").strip()), text)


# -- holding its words --------------------------------------------------------------------


def _ink(text: Any) -> tuple[float, float, float, float] | None:
    """Where a text's glyphs reach, on the drawing: their outlines' extent."""

    from flexo.portable import run_outline

    xs: list[float] = []
    ys: list[float] = []
    for line in text.lines:
        for run in line.runs:
            if run.face is None or not run.text.strip():
                continue
            for segment in run_outline(run):
                for x, y in segment.points:
                    xs.append(x)
                    ys.append(y)
    if not xs:
        return None
    if text.angle:
        turn = math.radians(text.angle)
        cos, sin = math.cos(turn), math.sin(turn)
        px, py = text.pivot
        points = [
            (px + cos * (x - px) - sin * (y - py), py + sin * (x - px) + cos * (y - py))
            for x, y in zip(xs, ys, strict=True)
        ]
        xs, ys = [x for x, _ in points], [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _grown(root: ET.Element) -> tuple[float, float, float, float] | None:
    """How far the drawing's words reach past its page, each side (left, top, right,
    bottom, in its units): None where they are on it."""

    from flexo.drawing import Text, read_drawing

    # (Words set along a path are not where the reader would put them: left to stand as drawn.)
    measured = copy.deepcopy(root)
    for holder in measured.iter():
        for text in [child for child in holder if local_name(child.tag) == "text"]:
            if any(local_name(piece.tag) == "textPath" for piece in text.iter()):
                holder.remove(text)
    try:
        drawing = read_drawing(ET.tostring(measured, encoding="unicode"))
    except Exception:  # a drawing the reader does not read is drawn as it is
        return None
    if drawing.width <= 0 or drawing.height <= 0:
        return None
    reach = [0.0, 0.0, 0.0, 0.0]
    for item in drawing.walk():
        if not isinstance(item, Text):
            continue
        try:
            ink = _ink(item)
        except Exception:
            continue
        if ink is None:
            continue
        left, top, right, bottom = ink
        reach = [max(reach[0], -left), max(reach[1], -top), max(reach[2], right - drawing.width),
                 max(reach[3], bottom - drawing.height)]
    # (Past it by a hair -- a glyph's edge on the page's, as its program measured it -- is on it.)
    least = 0.002 * max(drawing.width, drawing.height)
    if all(side <= least for side in reach):
        return None
    room = 0.01 * max(drawing.width, drawing.height)
    return tuple(side + room if side > least else 0.0 for side in reach)  # type: ignore[return-value]


def _grow(root: ET.Element, sides: tuple[float, float, float, float], width: float | None,
          height: float | None) -> tuple[float | None, float | None]:
    view = _numbers(root.get("viewBox"))
    if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
        return width, height
    left, top, right, bottom = sides
    wide, tall = view[2] + left + right, view[3] + top + bottom
    box = (view[0] - left, view[1] - top, wide, tall)
    root.set("viewBox", " ".join(number(value) for value in box))
    for name, ratio in (("width", wide / view[2]), ("height", tall / view[3])):
        said = root.get(name)
        if said is not None:
            root.set(name, _scaled(said, ratio) or said)
    return (
        None if width is None else width * wide / view[2],
        None if height is None else height * tall / view[3],
    )


# -- carrying its faces -------------------------------------------------------------------


def _embed(root: ET.Element, shared: str | None) -> None:
    """A stylesheet of the bundled faces the drawing's words are drawn in, each cut to the
    characters drawn in it, first in the drawing."""

    from flexo.drawing import Text, read_drawing
    from flexo.svg_resources import font_face_rule

    try:
        drawing = read_drawing(ET.tostring(root, encoding="unicode"))
    except Exception:
        return
    used: dict[FontFace, set[str]] = {}
    for item in drawing.walk():
        if not isinstance(item, Text):
            continue
        for line in item.lines:
            for run in line.runs:
                if run.face is not None and run.face.bundled and run.face.family != shared:
                    used.setdefault(run.face, set()).update(run.text)
    rules = [font_face_rule(face, frozenset(ord(character) for character in characters | {" "}))
             for face, characters in used.items()]
    if rules:
        sheet = ET.Element(svg_tag("style"), {"type": "text/css"})
        sheet.text = "".join(rules)
        root.insert(0, sheet)


# -- what a panel shows -------------------------------------------------------------------


@lru_cache(maxsize=16)
def described(artwork: Artwork) -> dict[str, Any]:
    """A drawing's texts and colours as its file has them, for a panel to show and change:
    each text's key (``id``, or ``text``, its place among the texts), its lines, size (in
    points at the drawing's size), bold, italic, colour and family -- in reading order,
    a line of texts at a time, left to right -- and each colour, with how it is used."""

    from flexo.drawing import Text, read_drawing

    if artwork.format != "svg" or artwork.path.suffix.lower() != ".svg":
        return {"texts": [], "colours": []}
    root = ET.fromstring(artwork.markup)
    prefix = f"{artwork.node_id}."
    texts = _texts(root)
    scale = points_per_unit(artwork, root)
    keys = {}
    for place, text in enumerate(texts, start=1):
        keys[f"flexo-text-{place}"] = (place, text, _key(text, place, prefix))
    marked = copy.deepcopy(root)
    for place, text in enumerate(_texts(marked), start=1):
        text.set("id", f"flexo-text-{place}")
    try:
        drawing = read_drawing(ET.tostring(marked, encoding="unicode"))
        drawn = [item for item in drawing.walk() if isinstance(item, Text) and item.id in keys]
    except Exception:
        drawn = []
    found = []
    for item in drawn:
        place, text, key = keys[item.id]  # type: ignore[index]
        runs = [run for line in item.lines for run in line.runs if run.text.strip()]
        first = runs[0] if runs else None
        size = (first.size if first else item.size) * scale
        top = min(line.baseline for line in item.lines) - item.size * 0.8
        left = min((line.left for line in item.lines), default=item.x)
        found.append(({
            **key,
            "lines": lines_of(text),
            "size": round(size, 1),
            "bold": (first.weight if first else item.weight) >= 600,
            "italic": bool(first.italic) if first else False,
            "colour": colour_key(first.fill if first else item.fill) or "#000000",
            "family": item.family,
        }, top, left, item.size))
    return {"texts": [entry for entry, *_ in _read_in_order(found)], "colours": colours_of(root)}


type _Placed = tuple[dict[str, Any], float, float, float]


def _read_in_order(found: list[_Placed]) -> list[_Placed]:
    """Texts as they are read: a line of them at a time, from the top, each line left to
    right (texts whose tops are within half a line of one another are on one)."""

    rows: list[list[_Placed]] = []
    for entry in sorted(found, key=lambda item: item[1]):
        if rows and entry[1] - rows[-1][0][1] < 0.5 * min(entry[3], rows[-1][0][3]):
            rows[-1].append(entry)
        else:
            rows.append([entry])
    return [entry for row in rows for entry in sorted(row, key=lambda item: item[2])]


# -- a figure's picture -------------------------------------------------------------------


def node_picture(spec: Any, family: str, *, embed: bool = False) -> Artwork:
    """An ``image`` node's artwork as the figure draws it: an SVG's words in ``family``
    (the figure's font), or as its properties say -- ``font``, ``texts``, ``colours`` --
    and grown to hold them. ``embed``: carrying the bundled faces it is drawn in but the
    figure's own, which the figure carries."""

    from flexo.artwork import node_artwork
    from flexo.diagnostics import Diagnostic, FlexoError

    artwork = node_artwork(spec)
    if artwork.format != "svg":
        return artwork
    try:
        restyle = restyle_of(
            spec.property("font"), spec.property("texts"), spec.property("colours")
        )
    except ValueError as error:
        raise FlexoError(
            Diagnostic(
                "image.restyle.invalid",
                f"The picture's words or colours can't be read: {error}.",
                entity_id=spec.id,
                hint='Write font: drawn (or a family), texts: [{id: text1, words: "...", size: 12, '
                'bold: true}], colours: {"#4a90d9": "#2e7d32"}.',
            )
        ) from None
    return restyled(artwork, restyle, family, embed=embed, shared=family)
